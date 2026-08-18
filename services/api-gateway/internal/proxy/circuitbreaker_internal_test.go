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

// fakeClock drives cb.now so state transitions are asserted without sleeping.
type fakeClock struct {
	mu sync.Mutex
	t  time.Time
}

func (c *fakeClock) now() time.Time {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.t
}

func (c *fakeClock) advance(d time.Duration) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.t = c.t.Add(d)
}

func okHandler() http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusOK)
	})
}

func failHandler() http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusInternalServerError)
	})
}

func execute(t *testing.T, cb *CircuitBreaker, h http.Handler) (*httptest.ResponseRecorder, error) {
	t.Helper()
	rec := httptest.NewRecorder()
	err := cb.Execute(h, rec, httptest.NewRequest(http.MethodGet, "/x", nil))
	return rec, err
}

func TestCircuitState_String_UnknownState(t *testing.T) {
	assert.Equal(t, "unknown", CircuitState(99).String())
}

func TestCircuitBreaker_ClosedIntervalStartsNewGeneration(t *testing.T) {
	clock := &fakeClock{t: time.Unix(1700000000, 0)}
	cb := NewCircuitBreaker("gen", CircuitBreakerConfig{MaxRequests: 1, Interval: time.Minute, Timeout: time.Minute, FailureRatio: 0.6})
	cb.now = clock.now
	cb.setState(StateClosed, clock.now()) // arms the interval expiry

	// Four failures: below the 5-sample minimum, so the breaker stays closed.
	for i := 0; i < 4; i++ {
		_, err := execute(t, cb, failHandler())
		require.NoError(t, err)
	}
	require.Equal(t, uint32(4), cb.counts.totalFailures)

	clock.advance(2 * time.Minute)

	assert.Equal(t, StateClosed, cb.State())
	assert.Equal(t, uint32(0), cb.counts.totalFailures, "expired interval must clear the counts")
	assert.Equal(t, clock.now().Add(time.Minute), cb.expiry)
}

func TestCircuitBreaker_NewGenerationWithoutIntervalClearsExpiry(t *testing.T) {
	clock := &fakeClock{t: time.Unix(1700000000, 0)}
	cb := NewCircuitBreaker("no-interval", CircuitBreakerConfig{MaxRequests: 1, Timeout: time.Minute})
	cb.now = clock.now
	cb.expiry = clock.now().Add(-time.Second) // already-expired generation
	cb.counts.totalFailures = 3

	assert.Equal(t, StateClosed, cb.State())
	assert.True(t, cb.expiry.IsZero(), "no Interval configured means no new expiry")
	assert.Equal(t, uint32(0), cb.counts.totalFailures)
}

func TestCircuitBreaker_HalfOpenFailureReopensCircuit(t *testing.T) {
	clock := &fakeClock{t: time.Unix(1700000000, 0)}
	cb := NewCircuitBreaker("half-open", CircuitBreakerConfig{MaxRequests: 2, Timeout: 30 * time.Second, FailureRatio: 0.6})
	cb.now = clock.now
	cb.setState(StateOpen, clock.now())

	clock.advance(31 * time.Second)
	require.Equal(t, StateHalfOpen, cb.State())

	_, err := execute(t, cb, failHandler())
	require.NoError(t, err)

	assert.Equal(t, StateOpen, cb.state, "a probe failure must re-open the circuit")
	assert.Equal(t, clock.now().Add(30*time.Second), cb.expiry)
}

func TestCircuitBreaker_HalfOpenRejectsExcessProbes(t *testing.T) {
	clock := &fakeClock{t: time.Unix(1700000000, 0)}
	cb := NewCircuitBreaker("probe-limit", CircuitBreakerConfig{MaxRequests: 1, Timeout: 30 * time.Second, FailureRatio: 0.6})
	cb.now = clock.now
	cb.setState(StateOpen, clock.now())
	clock.advance(31 * time.Second)
	require.Equal(t, StateHalfOpen, cb.State())

	// The single allowed probe succeeds and closes the circuit again.
	rec, err := execute(t, cb, okHandler())
	require.NoError(t, err)
	require.Equal(t, http.StatusOK, rec.Code)
	require.Equal(t, StateClosed, cb.State())

	// Re-open, then exhaust the probe budget without letting a probe finish.
	cb.setState(StateOpen, clock.now())
	clock.advance(31 * time.Second)
	require.Equal(t, StateHalfOpen, cb.State())
	cb.counts.requests = 1

	_, err = execute(t, cb, okHandler())
	require.Error(t, err)
	assert.Contains(t, err.Error(), "too many requests in half-open state")
}

func TestCircuitBreaker_OpenCircuitRejectsWithoutCallingHandler(t *testing.T) {
	clock := &fakeClock{t: time.Unix(1700000000, 0)}
	cb := NewCircuitBreaker("open", CircuitBreakerConfig{MaxRequests: 1, Timeout: time.Hour})
	cb.now = clock.now
	cb.setState(StateOpen, clock.now())

	called := false
	rec := httptest.NewRecorder()
	err := cb.Execute(http.HandlerFunc(func(http.ResponseWriter, *http.Request) { called = true }), rec, httptest.NewRequest(http.MethodGet, "/x", nil))

	require.Error(t, err)
	assert.Contains(t, err.Error(), "is open")
	assert.False(t, called)
	assert.Zero(t, rec.Body.Len(), "nothing should have been written")
	assert.Empty(t, rec.Result().Header)
}

func TestStatusRecorder_WriteImpliesStatusOK(t *testing.T) {
	rec := httptest.NewRecorder()
	sr := &statusRecorder{ResponseWriter: rec, statusCode: http.StatusOK}

	n, err := sr.Write([]byte("hello"))

	require.NoError(t, err)
	assert.Equal(t, 5, n)
	assert.True(t, sr.written)
	assert.Equal(t, http.StatusOK, sr.statusCode)
	assert.Equal(t, "hello", rec.Body.String())

	// A WriteHeader after the first Write must not change the recorded status.
	sr.WriteHeader(http.StatusInternalServerError)
	assert.Equal(t, http.StatusOK, sr.statusCode)
}

func TestStatusRecorder_WriteAfterExplicitStatusKeepsStatus(t *testing.T) {
	rec := httptest.NewRecorder()
	sr := &statusRecorder{ResponseWriter: rec, statusCode: http.StatusOK}

	sr.WriteHeader(http.StatusTeapot)
	_, err := sr.Write([]byte("body"))

	require.NoError(t, err)
	assert.Equal(t, http.StatusTeapot, sr.statusCode)
	assert.Equal(t, http.StatusTeapot, rec.Code)
}

func TestStatusRecorder_Unwrap(t *testing.T) {
	rec := httptest.NewRecorder()
	sr := &statusRecorder{ResponseWriter: rec, statusCode: http.StatusOK}

	assert.Same(t, rec, sr.Unwrap())
}

func TestStatusRecorder_FlushDelegatesWhenSupported(t *testing.T) {
	rec := httptest.NewRecorder()
	sr := &statusRecorder{ResponseWriter: rec, statusCode: http.StatusOK}

	_, err := sr.Write([]byte("chunk"))
	require.NoError(t, err)
	sr.Flush()

	assert.True(t, rec.Flushed)
}

// nonFlusher implements only http.ResponseWriter, so Flush/Hijack must degrade.
type nonFlusher struct {
	header http.Header
	status int
}

func (n *nonFlusher) Header() http.Header {
	if n.header == nil {
		n.header = http.Header{}
	}
	return n.header
}
func (n *nonFlusher) Write(b []byte) (int, error) { return len(b), nil }
func (n *nonFlusher) WriteHeader(code int)        { n.status = code }

func TestStatusRecorder_FlushIsNoOpWhenUnsupported(t *testing.T) {
	sr := &statusRecorder{ResponseWriter: &nonFlusher{}, statusCode: http.StatusOK}

	assert.NotPanics(t, sr.Flush)
}

func TestStatusRecorder_HijackUnsupported(t *testing.T) {
	sr := &statusRecorder{ResponseWriter: &nonFlusher{}, statusCode: http.StatusOK}

	conn, rw, err := sr.Hijack()

	require.Error(t, err)
	assert.Nil(t, conn)
	assert.Nil(t, rw)
	assert.Contains(t, err.Error(), "does not support hijacking")
}

// hijackable wraps a ResponseWriter with a canned Hijack implementation.
type hijackable struct {
	http.ResponseWriter
	conn   net.Conn
	rw     *bufio.ReadWriter
	called bool
}

func (h *hijackable) Hijack() (net.Conn, *bufio.ReadWriter, error) {
	h.called = true
	return h.conn, h.rw, nil
}

func TestStatusRecorder_HijackDelegates(t *testing.T) {
	client, server := net.Pipe()
	defer client.Close()
	defer server.Close()

	want := &hijackable{ResponseWriter: httptest.NewRecorder(), conn: server}
	sr := &statusRecorder{ResponseWriter: want, statusCode: http.StatusOK}

	conn, _, err := sr.Hijack()

	require.NoError(t, err)
	assert.True(t, want.called)
	assert.Same(t, server, conn)
}

func TestCircuitBreakerManager_GetIsConcurrencySafe(t *testing.T) {
	m := NewCircuitBreakerManager(CircuitBreakerConfig{MaxRequests: 1, Timeout: time.Minute})

	const goroutines = 32
	results := make([]*CircuitBreaker, goroutines)
	var wg sync.WaitGroup
	wg.Add(goroutines)
	for i := 0; i < goroutines; i++ {
		go func(i int) {
			defer wg.Done()
			results[i] = m.Get("/api/v1/files")
		}(i)
	}
	wg.Wait()

	for _, cb := range results {
		require.NotNil(t, cb)
		assert.Same(t, results[0], cb, "all callers must share one breaker per route")
	}
	assert.NotSame(t, results[0], m.Get("/api/v1/auth"))
}
