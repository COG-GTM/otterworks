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

var (
	okHandler   = http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(http.StatusOK) })
	failHandler = http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(http.StatusBadGateway) })
)

func run(t *testing.T, cb *CircuitBreaker, h http.Handler) error {
	t.Helper()
	return cb.Execute(h, httptest.NewRecorder(), httptest.NewRequest(http.MethodGet, "/", nil))
}

func newClockedBreaker(cfg CircuitBreakerConfig) (*CircuitBreaker, *time.Time) {
	now := time.Unix(1_700_000_000, 0)
	cb := NewCircuitBreaker("svc", cfg)
	cb.now = func() time.Time { return now }
	return cb, &now
}

func tripToHalfOpen(t *testing.T, cb *CircuitBreaker, now *time.Time) {
	t.Helper()
	for i := 0; i < 5; i++ {
		require.NoError(t, run(t, cb, failHandler))
	}
	require.Equal(t, StateOpen, cb.State())
	*now = now.Add(cb.config.Timeout + time.Second)
	require.Equal(t, StateHalfOpen, cb.State())
}

func TestCircuitBreaker_OpenRejectsWithError(t *testing.T) {
	cb, now := newClockedBreaker(defaultTestConfig())
	for i := 0; i < 5; i++ {
		require.NoError(t, run(t, cb, failHandler))
	}
	err := run(t, cb, okHandler)
	require.Error(t, err)
	assert.Contains(t, err.Error(), "circuit breaker svc is open")
	*now = now.Add(time.Second)
	assert.Equal(t, StateOpen, cb.State(), "breaker stays open until timeout elapses")
}

func TestCircuitBreaker_HalfOpenFailureReopens(t *testing.T) {
	cb, now := newClockedBreaker(defaultTestConfig())
	tripToHalfOpen(t, cb, now)

	require.NoError(t, run(t, cb, failHandler))
	assert.Equal(t, StateOpen, cb.State())
	assert.Error(t, run(t, cb, okHandler))
}

func TestCircuitBreaker_HalfOpenLimitsConcurrentProbes(t *testing.T) {
	cfg := defaultTestConfig()
	cfg.MaxRequests = 1
	cb, now := newClockedBreaker(cfg)
	tripToHalfOpen(t, cb, now)

	started := make(chan struct{})
	release := make(chan struct{})
	var wg sync.WaitGroup
	wg.Add(1)
	go func() {
		defer wg.Done()
		_ = cb.Execute(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			close(started)
			<-release
		}), httptest.NewRecorder(), httptest.NewRequest(http.MethodGet, "/", nil))
	}()
	<-started

	err := run(t, cb, okHandler)
	require.Error(t, err)
	assert.Contains(t, err.Error(), "too many requests in half-open state")

	close(release)
	wg.Wait()
	assert.Equal(t, StateClosed, cb.State())
}

func TestCircuitBreaker_BelowMinimumSampleDoesNotTrip(t *testing.T) {
	cb, _ := newClockedBreaker(defaultTestConfig())
	for i := 0; i < 4; i++ {
		require.NoError(t, run(t, cb, failHandler))
	}
	assert.Equal(t, StateClosed, cb.State())
}

func TestCircuitBreaker_FailureRatioBelowThresholdStaysClosed(t *testing.T) {
	cb, _ := newClockedBreaker(defaultTestConfig())
	for i := 0; i < 6; i++ {
		require.NoError(t, run(t, cb, okHandler))
	}
	for i := 0; i < 5; i++ {
		require.NoError(t, run(t, cb, failHandler))
	}
	assert.Equal(t, StateClosed, cb.State())
	require.NoError(t, run(t, cb, failHandler))
	assert.Equal(t, StateOpen, cb.State())
}

func TestCircuitBreaker_ClosedIntervalClearsCountsAfterRecovery(t *testing.T) {
	cb, now := newClockedBreaker(defaultTestConfig())
	tripToHalfOpen(t, cb, now)
	require.NoError(t, run(t, cb, okHandler))
	require.NoError(t, run(t, cb, okHandler))
	require.Equal(t, StateClosed, cb.State())
	require.False(t, cb.expiry.IsZero())

	for i := 0; i < 4; i++ {
		require.NoError(t, run(t, cb, failHandler))
	}
	*now = now.Add(cb.config.Interval + time.Second)
	assert.Equal(t, StateClosed, cb.State())
	assert.Equal(t, uint32(0), cb.counts.totalFailures)

	require.NoError(t, run(t, cb, failHandler))
	assert.Equal(t, StateClosed, cb.State(), "failures from the previous interval must not count")
}

func TestCircuitBreaker_RecoveryWithZeroIntervalNeverExpires(t *testing.T) {
	cfg := defaultTestConfig()
	cfg.Interval = 0
	cb, now := newClockedBreaker(cfg)
	tripToHalfOpen(t, cb, now)
	require.NoError(t, run(t, cb, okHandler))
	require.NoError(t, run(t, cb, okHandler))
	assert.Equal(t, StateClosed, cb.State())
	assert.True(t, cb.expiry.IsZero())
}

func TestCircuitBreaker_WriteWithoutHeaderCountsAsSuccess(t *testing.T) {
	cb, _ := newClockedBreaker(defaultTestConfig())
	rec := httptest.NewRecorder()
	err := cb.Execute(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte("body"))
		w.WriteHeader(http.StatusInternalServerError)
	}), rec, httptest.NewRequest(http.MethodGet, "/", nil))
	require.NoError(t, err)
	assert.Equal(t, http.StatusOK, rec.Code)
	assert.Equal(t, "body", rec.Body.String())
	assert.Equal(t, uint32(1), cb.counts.totalSuccesses)
	assert.Equal(t, uint32(0), cb.counts.totalFailures)
}

func TestStatusRecorder_FirstWriteHeaderWins(t *testing.T) {
	rec := httptest.NewRecorder()
	sr := &statusRecorder{ResponseWriter: rec, statusCode: http.StatusOK}
	sr.WriteHeader(http.StatusServiceUnavailable)
	sr.WriteHeader(http.StatusOK)
	_, _ = sr.Write([]byte("x"))
	assert.Equal(t, http.StatusServiceUnavailable, sr.statusCode)
	assert.Equal(t, http.StatusServiceUnavailable, rec.Code)
}

func TestStatusRecorder_UnwrapAndFlush(t *testing.T) {
	rec := httptest.NewRecorder()
	sr := &statusRecorder{ResponseWriter: rec}
	assert.Same(t, rec, sr.Unwrap())
	sr.Flush()
	assert.True(t, rec.Flushed)

	noFlush := &statusRecorder{ResponseWriter: plainWriter{rec}}
	assert.NotPanics(t, noFlush.Flush)
}

func TestStatusRecorder_ResponseControllerFlush(t *testing.T) {
	rec := httptest.NewRecorder()
	sr := &statusRecorder{ResponseWriter: rec}
	require.NoError(t, http.NewResponseController(sr).Flush())
	assert.True(t, rec.Flushed)
}

func TestStatusRecorder_HijackUnsupported(t *testing.T) {
	sr := &statusRecorder{ResponseWriter: httptest.NewRecorder()}
	conn, brw, err := sr.Hijack()
	assert.Nil(t, conn)
	assert.Nil(t, brw)
	require.Error(t, err)
	assert.Contains(t, err.Error(), "does not support hijacking")
}

func TestStatusRecorder_HijackDelegates(t *testing.T) {
	client, server := net.Pipe()
	defer client.Close()
	defer server.Close()
	h := &hijackWriter{ResponseRecorder: httptest.NewRecorder(), conn: server}
	sr := &statusRecorder{ResponseWriter: h}

	conn, brw, err := sr.Hijack()
	require.NoError(t, err)
	assert.Same(t, server, conn)
	assert.NotNil(t, brw)
	assert.True(t, h.hijacked)
}

func TestCircuitBreakerManager_ConcurrentGetReturnsSingleInstance(t *testing.T) {
	m := NewCircuitBreakerManager(defaultTestConfig())
	const n = 32
	results := make([]*CircuitBreaker, n)
	var wg sync.WaitGroup
	for i := 0; i < n; i++ {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			results[i] = m.Get("shared")
		}(i)
	}
	wg.Wait()
	for _, cb := range results {
		assert.Same(t, results[0], cb)
	}
	assert.Len(t, m.breakers, 1)
}

type plainWriter struct{ w http.ResponseWriter }

func (p plainWriter) Header() http.Header         { return p.w.Header() }
func (p plainWriter) Write(b []byte) (int, error) { return p.w.Write(b) }
func (p plainWriter) WriteHeader(code int)        { p.w.WriteHeader(code) }

type hijackWriter struct {
	*httptest.ResponseRecorder
	conn     net.Conn
	hijacked bool
}

func (h *hijackWriter) Hijack() (net.Conn, *bufio.ReadWriter, error) {
	h.hijacked = true
	return h.conn, bufio.NewReadWriter(bufio.NewReader(h.conn), bufio.NewWriter(h.conn)), nil
}

func TestCircuitState_UnknownString(t *testing.T) {
	assert.Equal(t, "unknown", CircuitState(42).String())
}

func TestCircuitBreaker_InFlightFailureAfterTripKeepsOpen(t *testing.T) {
	cb, _ := newClockedBreaker(defaultTestConfig())
	started := make(chan struct{})
	release := make(chan struct{})
	errc := make(chan error, 1)
	go func() {
		errc <- cb.Execute(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			close(started)
			<-release
			w.WriteHeader(http.StatusInternalServerError)
		}), httptest.NewRecorder(), httptest.NewRequest(http.MethodGet, "/", nil))
	}()
	<-started
	for i := 0; i < 5; i++ {
		require.NoError(t, run(t, cb, failHandler))
	}
	require.Equal(t, StateOpen, cb.State())
	expiry := cb.expiry

	close(release)
	require.NoError(t, <-errc)
	assert.Equal(t, StateOpen, cb.State())
	assert.Equal(t, expiry, cb.expiry, "late failure must not extend the open timeout")
}
