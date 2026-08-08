package proxy

import (
	"bufio"
	"net"
	"net/http"
	"net/http/httptest"
	"sync"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func generationTestConfig() CircuitBreakerConfig {
	return CircuitBreakerConfig{
		MaxRequests:  2,
		Interval:     60 * time.Second,
		Timeout:      10 * time.Second,
		FailureRatio: 0.5,
	}
}

func TestCircuitState_StringUnknown(t *testing.T) {
	assert.Equal(t, "unknown", CircuitState(42).String())
	assert.Equal(t, "unknown", CircuitState(-1).String())
}

func TestCircuitBreaker_ClosedStateRollsOverToANewGeneration(t *testing.T) {
	cb := NewCircuitBreaker("test-svc", generationTestConfig())

	now := time.Now()
	cb.now = func() time.Time { return now }

	failHandler := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusInternalServerError)
	})

	// Start the interval clock, then record failures that stay under the trip
	// threshold (5 requests minimum sample).
	cb.setState(StateClosed, now)
	for i := 0; i < 3; i++ {
		require.NoError(t, cb.Execute(failHandler, httptest.NewRecorder(), httptest.NewRequest(http.MethodGet, "/", nil)))
	}
	require.Equal(t, uint32(3), cb.counts.totalFailures)

	// Crossing the interval boundary starts a fresh generation, discarding the
	// old counts so a slow trickle of failures never trips the breaker.
	cb.now = func() time.Time { return now.Add(61 * time.Second) }
	assert.Equal(t, StateClosed, cb.State())
	assert.Equal(t, uint32(0), cb.counts.totalFailures)
	assert.Equal(t, uint32(0), cb.counts.requests)
	assert.Equal(t, now.Add(61*time.Second).Add(60*time.Second), cb.expiry)
}

func TestCircuitBreaker_NewGenerationWithoutIntervalClearsExpiry(t *testing.T) {
	cb := NewCircuitBreaker("test-svc", CircuitBreakerConfig{FailureRatio: 0.5})

	now := time.Now()
	cb.counts.onFailure()
	cb.expiry = now.Add(time.Second)

	cb.toNewGeneration(now)

	assert.Equal(t, uint32(0), cb.counts.totalFailures)
	assert.True(t, cb.expiry.IsZero(), "with no interval configured the generation never expires")
}

func TestCircuitBreaker_HalfOpenRejectsBeyondMaxRequests(t *testing.T) {
	cb := NewCircuitBreaker("test-svc", generationTestConfig())

	now := time.Now()
	cb.now = func() time.Time { return now }
	cb.setState(StateHalfOpen, now)

	blocked := make(chan struct{})
	release := make(chan struct{})
	slowHandler := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		blocked <- struct{}{}
		<-release
		w.WriteHeader(http.StatusOK)
	})

	// MaxRequests probes are admitted and left in flight...
	var wg sync.WaitGroup
	for i := 0; i < int(generationTestConfig().MaxRequests); i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			_ = cb.Execute(slowHandler, httptest.NewRecorder(), httptest.NewRequest(http.MethodGet, "/", nil))
		}()
		<-blocked
	}

	// ...so the next one is rejected without ever reaching the handler.
	err := cb.Execute(slowHandler, httptest.NewRecorder(), httptest.NewRequest(http.MethodGet, "/", nil))
	require.Error(t, err)
	assert.Contains(t, err.Error(), "too many requests in half-open state")

	close(release)
	wg.Wait()
}

func TestCircuitBreaker_HalfOpenReopensOnASingleFailure(t *testing.T) {
	cb := NewCircuitBreaker("test-svc", generationTestConfig())

	now := time.Now()
	cb.now = func() time.Time { return now }
	cb.setState(StateHalfOpen, now)

	failHandler := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusBadGateway)
	})
	require.NoError(t, cb.Execute(failHandler, httptest.NewRecorder(), httptest.NewRequest(http.MethodGet, "/", nil)))

	cb.mu.Lock()
	state := cb.state
	expiry := cb.expiry
	cb.mu.Unlock()

	assert.Equal(t, StateOpen, state, "one failed probe re-opens the breaker")
	assert.Equal(t, now.Add(10*time.Second), expiry)
}

func TestCircuitBreaker_OpenRejectsWithoutCallingTheHandler(t *testing.T) {
	cb := NewCircuitBreaker("test-svc", generationTestConfig())

	now := time.Now()
	cb.now = func() time.Time { return now }
	cb.setState(StateOpen, now)

	called := false
	handler := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { called = true })

	err := cb.Execute(handler, httptest.NewRecorder(), httptest.NewRequest(http.MethodGet, "/", nil))

	require.Error(t, err)
	assert.Contains(t, err.Error(), "is open")
	assert.False(t, called)
}

func TestCircuitBreaker_ShouldTripNeedsAMinimumSample(t *testing.T) {
	cb := NewCircuitBreaker("test-svc", generationTestConfig())

	for i := 0; i < 4; i++ {
		cb.counts.onFailure()
	}
	assert.False(t, cb.shouldTrip(), "4 failures is below the minimum sample size")

	cb.counts.onFailure()
	assert.True(t, cb.shouldTrip(), "the 5th failure crosses both the sample size and the ratio")
}

func TestCircuitBreakerManager_GetIsSafeUnderConcurrency(t *testing.T) {
	mgr := NewCircuitBreakerManager(generationTestConfig())

	const goroutines = 64
	start := make(chan struct{})
	results := make([]*CircuitBreaker, goroutines)

	var wg sync.WaitGroup
	for i := 0; i < goroutines; i++ {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			<-start
			results[i] = mgr.Get("service-race")
		}(i)
	}
	close(start)
	wg.Wait()

	for i, cb := range results {
		require.NotNil(t, cb, "goroutine %d", i)
		assert.Same(t, results[0], cb, "every goroutine sees the same breaker instance")
	}
	mgr.mu.RLock()
	defer mgr.mu.RUnlock()
	assert.Len(t, mgr.breakers, 1)
}

// hijackableWriter is a ResponseWriter that supports hijacking, like a real
// *http.response does for websocket upgrades on /socket.io.
type hijackableWriter struct {
	http.ResponseWriter
	conn net.Conn
}

func (h *hijackableWriter) Hijack() (net.Conn, *bufio.ReadWriter, error) {
	return h.conn, bufio.NewReadWriter(bufio.NewReader(h.conn), bufio.NewWriter(h.conn)), nil
}

// nonFlusherWriter deliberately implements neither Flusher nor Hijacker.
type nonFlusherWriter struct {
	header http.Header
	body   []byte
	status int
}

func (w *nonFlusherWriter) Header() http.Header {
	if w.header == nil {
		w.header = http.Header{}
	}
	return w.header
}

func (w *nonFlusherWriter) Write(b []byte) (int, error) {
	w.body = append(w.body, b...)
	return len(b), nil
}

func (w *nonFlusherWriter) WriteHeader(status int) { w.status = status }

func TestStatusRecorder_WriteMarksTheResponseWritten(t *testing.T) {
	rec := httptest.NewRecorder()
	sr := &statusRecorder{ResponseWriter: rec, statusCode: http.StatusOK}

	n, err := sr.Write([]byte("hello"))

	require.NoError(t, err)
	assert.Equal(t, 5, n)
	assert.True(t, sr.written)
	assert.Equal(t, http.StatusOK, sr.statusCode)
	assert.Equal(t, "hello", rec.Body.String())

	// An implicit 200 must not be overwritten by a later WriteHeader.
	sr.WriteHeader(http.StatusTeapot)
	assert.Equal(t, http.StatusOK, sr.statusCode)
}

func TestStatusRecorder_WriteHeaderRecordsTheFirstStatusOnly(t *testing.T) {
	rec := httptest.NewRecorder()
	sr := &statusRecorder{ResponseWriter: rec, statusCode: http.StatusOK}

	sr.WriteHeader(http.StatusServiceUnavailable)
	sr.WriteHeader(http.StatusOK)

	assert.Equal(t, http.StatusServiceUnavailable, sr.statusCode)
	assert.Equal(t, http.StatusServiceUnavailable, rec.Code)
}

func TestStatusRecorder_Unwrap(t *testing.T) {
	rec := httptest.NewRecorder()
	sr := &statusRecorder{ResponseWriter: rec}

	assert.Same(t, rec, sr.Unwrap())
}

func TestStatusRecorder_Flush(t *testing.T) {
	t.Run("delegates to a flushable writer", func(t *testing.T) {
		rec := httptest.NewRecorder()
		sr := &statusRecorder{ResponseWriter: rec}

		sr.Flush()

		assert.True(t, rec.Flushed)
	})

	t.Run("is a no-op for a writer that cannot flush", func(t *testing.T) {
		sr := &statusRecorder{ResponseWriter: &nonFlusherWriter{}}
		assert.NotPanics(t, sr.Flush)
	})
}

func TestStatusRecorder_Hijack(t *testing.T) {
	t.Run("delegates to a hijackable writer", func(t *testing.T) {
		client, server := net.Pipe()
		defer func() { _ = client.Close() }()
		defer func() { _ = server.Close() }()

		sr := &statusRecorder{ResponseWriter: &hijackableWriter{ResponseWriter: httptest.NewRecorder(), conn: server}}

		conn, buf, err := sr.Hijack()

		require.NoError(t, err)
		assert.Same(t, server, conn)
		assert.NotNil(t, buf)
	})

	t.Run("errors when the writer does not support hijacking", func(t *testing.T) {
		sr := &statusRecorder{ResponseWriter: httptest.NewRecorder()}

		conn, buf, err := sr.Hijack()

		require.Error(t, err)
		assert.Nil(t, conn)
		assert.Nil(t, buf)
		assert.Contains(t, err.Error(), "does not support hijacking")
	})
}
