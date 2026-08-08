package proxy

import (
	"io"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func defaultTestConfig() CircuitBreakerConfig {
	return CircuitBreakerConfig{
		MaxRequests:  2,
		Interval:     60 * time.Second,
		Timeout:      10 * time.Second,
		FailureRatio: 0.5,
	}
}

func TestCircuitBreaker_StartsInClosedState(t *testing.T) {
	cb := NewCircuitBreaker("test-svc", defaultTestConfig())
	assert.Equal(t, StateClosed, cb.State())
}

func TestCircuitBreaker_SuccessfulRequests(t *testing.T) {
	cb := NewCircuitBreaker("test-svc", defaultTestConfig())

	handler := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	})

	for i := 0; i < 10; i++ {
		req := httptest.NewRequest(http.MethodGet, "/", nil)
		rec := httptest.NewRecorder()
		err := cb.Execute(handler, rec, req)
		require.NoError(t, err)
		assert.Equal(t, http.StatusOK, rec.Code)
	}

	assert.Equal(t, StateClosed, cb.State())
}

func TestCircuitBreaker_TripsOnFailures(t *testing.T) {
	cfg := CircuitBreakerConfig{
		MaxRequests:  2,
		Interval:     60 * time.Second,
		Timeout:      10 * time.Second,
		FailureRatio: 0.5,
	}
	cb := NewCircuitBreaker("test-svc", cfg)

	failHandler := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusInternalServerError)
	})

	// Send enough requests to trip the breaker (need at least 5 total, >50% failures)
	for i := 0; i < 6; i++ {
		req := httptest.NewRequest(http.MethodGet, "/", nil)
		rec := httptest.NewRecorder()
		cb.Execute(failHandler, rec, req)
	}

	assert.Equal(t, StateOpen, cb.State())

	// Next request should be rejected
	req := httptest.NewRequest(http.MethodGet, "/", nil)
	rec := httptest.NewRecorder()
	err := cb.Execute(failHandler, rec, req)
	assert.Error(t, err)
	assert.Contains(t, err.Error(), "circuit breaker test-svc is open")
}

func TestCircuitBreaker_TransitionsToHalfOpen(t *testing.T) {
	cfg := CircuitBreakerConfig{
		MaxRequests:  2,
		Interval:     60 * time.Second,
		Timeout:      5 * time.Second,
		FailureRatio: 0.5,
	}
	cb := NewCircuitBreaker("test-svc", cfg)

	now := time.Now()
	cb.now = func() time.Time { return now }

	failHandler := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusInternalServerError)
	})

	// Trip the breaker
	for i := 0; i < 6; i++ {
		req := httptest.NewRequest(http.MethodGet, "/", nil)
		rec := httptest.NewRecorder()
		cb.Execute(failHandler, rec, req)
	}
	assert.Equal(t, StateOpen, cb.State())

	// Advance time past timeout
	cb.now = func() time.Time { return now.Add(6 * time.Second) }
	assert.Equal(t, StateHalfOpen, cb.State())
}

func TestCircuitBreaker_RecoveryFromHalfOpen(t *testing.T) {
	cfg := CircuitBreakerConfig{
		MaxRequests:  2,
		Interval:     60 * time.Second,
		Timeout:      5 * time.Second,
		FailureRatio: 0.5,
	}
	cb := NewCircuitBreaker("test-svc", cfg)

	now := time.Now()
	cb.now = func() time.Time { return now }

	failHandler := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusInternalServerError)
	})
	successHandler := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	})

	// Trip the breaker
	for i := 0; i < 6; i++ {
		req := httptest.NewRequest(http.MethodGet, "/", nil)
		rec := httptest.NewRecorder()
		cb.Execute(failHandler, rec, req)
	}
	assert.Equal(t, StateOpen, cb.State())

	// Advance time to half-open
	cb.now = func() time.Time { return now.Add(6 * time.Second) }

	// Successful requests in half-open should close the breaker
	for i := 0; i < 2; i++ {
		req := httptest.NewRequest(http.MethodGet, "/", nil)
		rec := httptest.NewRecorder()
		err := cb.Execute(successHandler, rec, req)
		require.NoError(t, err)
	}

	assert.Equal(t, StateClosed, cb.State())
}

func TestCircuitBreakerManager_GetOrCreate(t *testing.T) {
	mgr := NewCircuitBreakerManager(defaultTestConfig())

	cb1 := mgr.Get("service-a")
	cb2 := mgr.Get("service-a")
	cb3 := mgr.Get("service-b")

	assert.Same(t, cb1, cb2, "same name should return same instance")
	assert.NotSame(t, cb1, cb3, "different names should return different instances")
}

func TestCircuitState_String(t *testing.T) {
	assert.Equal(t, "closed", StateClosed.String())
	assert.Equal(t, "open", StateOpen.String())
	assert.Equal(t, "half-open", StateHalfOpen.String())
}

func TestCircuitState_StringUnknown(t *testing.T) {
	assert.Equal(t, "unknown", CircuitState(99).String())
}

func TestCircuitBreaker_ClosedStateStartsNewGeneration(t *testing.T) {
	now := time.Now()

	t.Run("with interval", func(t *testing.T) {
		cb := NewCircuitBreaker("gen-svc", CircuitBreakerConfig{Interval: 60 * time.Second, FailureRatio: 0.5})
		cb.now = func() time.Time { return now }
		cb.setState(StateClosed, now)
		cb.counts.onFailure()
		require.Equal(t, uint32(1), cb.counts.totalFailures)

		cb.now = func() time.Time { return now.Add(90 * time.Second) }
		assert.Equal(t, StateClosed, cb.State())
		assert.Equal(t, uint32(0), cb.counts.totalFailures, "counts are cleared for the new generation")
		assert.Equal(t, now.Add(150*time.Second), cb.expiry)
	})

	t.Run("without interval", func(t *testing.T) {
		cb := NewCircuitBreaker("gen-svc", CircuitBreakerConfig{FailureRatio: 0.5})
		cb.now = func() time.Time { return now.Add(time.Second) }
		cb.expiry = now
		cb.counts.onFailure()

		assert.Equal(t, StateClosed, cb.State())
		assert.Equal(t, uint32(0), cb.counts.totalFailures)
		assert.True(t, cb.expiry.IsZero(), "no interval means no expiry")
	})
}

func TestCircuitBreaker_HalfOpenRejectsExcessRequests(t *testing.T) {
	now := time.Now()
	cb := NewCircuitBreaker("half-open-svc", CircuitBreakerConfig{MaxRequests: 2, Timeout: 5 * time.Second})
	cb.now = func() time.Time { return now }
	cb.setState(StateHalfOpen, now)
	cb.counts.requests = 2 // the probe budget is already spent

	err := cb.Execute(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		t.Error("handler must not run when the probe budget is exhausted")
	}), httptest.NewRecorder(), httptest.NewRequest(http.MethodGet, "/", nil))

	require.Error(t, err)
	assert.Contains(t, err.Error(), "too many requests in half-open state")
}

func TestCircuitBreaker_HalfOpenFailureReopens(t *testing.T) {
	now := time.Now()
	cb := NewCircuitBreaker("half-open-svc", CircuitBreakerConfig{MaxRequests: 2, Timeout: 5 * time.Second})
	cb.now = func() time.Time { return now }
	cb.setState(StateHalfOpen, now)

	err := cb.Execute(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusBadGateway)
	}), httptest.NewRecorder(), httptest.NewRequest(http.MethodGet, "/", nil))

	require.NoError(t, err)
	assert.Equal(t, StateOpen, cb.State())
	assert.Equal(t, now.Add(5*time.Second), cb.expiry)
}

func TestStatusRecorder_WriteWithoutExplicitHeader(t *testing.T) {
	cb := NewCircuitBreaker("write-svc", defaultTestConfig())
	rec := httptest.NewRecorder()

	err := cb.Execute(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		_, writeErr := w.Write([]byte("implicit 200"))
		require.NoError(t, writeErr)
	}), rec, httptest.NewRequest(http.MethodGet, "/", nil))

	require.NoError(t, err)
	assert.Equal(t, http.StatusOK, rec.Code)
	assert.Equal(t, "implicit 200", rec.Body.String())
	assert.Equal(t, StateClosed, cb.State())
}

func TestStatusRecorder_UnwrapAndFlush(t *testing.T) {
	rec := httptest.NewRecorder()
	sr := &statusRecorder{ResponseWriter: rec, statusCode: http.StatusOK}

	assert.Same(t, rec, sr.Unwrap())

	sr.Flush()
	assert.True(t, rec.Flushed)

	// A writer that is not an http.Flusher must be a no-op rather than a panic.
	assert.NotPanics(t, func() {
		(&statusRecorder{ResponseWriter: nonFlusherWriter{rec}, statusCode: http.StatusOK}).Flush()
	})
}

// nonFlusherWriter hides the Flush/Hijack methods of the writer it wraps.
type nonFlusherWriter struct {
	rec *httptest.ResponseRecorder
}

func (w nonFlusherWriter) Header() http.Header         { return w.rec.Header() }
func (w nonFlusherWriter) Write(b []byte) (int, error) { return w.rec.Write(b) }
func (w nonFlusherWriter) WriteHeader(code int)        { w.rec.WriteHeader(code) }

func TestStatusRecorder_Hijack(t *testing.T) {
	t.Run("unsupported", func(t *testing.T) {
		sr := &statusRecorder{ResponseWriter: httptest.NewRecorder(), statusCode: http.StatusOK}

		conn, rw, err := sr.Hijack()

		require.Error(t, err)
		assert.Nil(t, conn)
		assert.Nil(t, rw)
		assert.Contains(t, err.Error(), "does not support hijacking")
	})

	t.Run("supported", func(t *testing.T) {
		srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
			sr := &statusRecorder{ResponseWriter: w, statusCode: http.StatusOK}
			conn, rw, err := sr.Hijack()
			if err != nil {
				t.Error(err)
				return
			}
			defer conn.Close()
			_, _ = rw.WriteString("HTTP/1.1 200 OK\r\nContent-Length: 8\r\n\r\nhijacked")
			_ = rw.Flush()
		}))
		defer srv.Close()

		res, err := http.Get(srv.URL)
		require.NoError(t, err)
		defer res.Body.Close()
		body, err := io.ReadAll(res.Body)
		require.NoError(t, err)

		assert.Equal(t, http.StatusOK, res.StatusCode)
		assert.Equal(t, "hijacked", string(body))
	})
}
