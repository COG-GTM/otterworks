package proxy

import (
	"net/http"
	"net/http/httptest"
	"sync"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func okHandler() http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(http.StatusOK) }
}

func failHandler() http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(http.StatusInternalServerError) }
}

func execute(t *testing.T, cb *CircuitBreaker, h http.Handler) (int, error) {
	t.Helper()
	rec := httptest.NewRecorder()
	err := cb.Execute(h, rec, httptest.NewRequest(http.MethodGet, "/", nil))
	return rec.Code, err
}

// trip drives the breaker to StateOpen using the minimum sample size.
func trip(t *testing.T, cb *CircuitBreaker) {
	t.Helper()
	for i := 0; i < 5; i++ {
		_, err := execute(t, cb, failHandler())
		require.NoError(t, err)
	}
	require.Equal(t, StateOpen, cb.State())
}

func TestCircuitState_StringUnknown(t *testing.T) {
	assert.Equal(t, "unknown", CircuitState(42).String())
}

func TestCircuitBreaker_FailureInHalfOpenReopensImmediately(t *testing.T) {
	cb := NewCircuitBreaker("test-svc", CircuitBreakerConfig{
		MaxRequests: 2, Interval: time.Minute, Timeout: 5 * time.Second, FailureRatio: 0.5,
	})
	now := time.Now()
	cb.now = func() time.Time { return now }

	trip(t, cb)

	cb.now = func() time.Time { return now.Add(6 * time.Second) }
	require.Equal(t, StateHalfOpen, cb.State())

	_, err := execute(t, cb, failHandler())
	require.NoError(t, err)

	// A single probe failure re-opens the breaker without waiting for the ratio.
	assert.Equal(t, StateOpen, cb.State())
}

func TestCircuitBreaker_RejectsExcessConcurrentProbesInHalfOpen(t *testing.T) {
	cb := NewCircuitBreaker("test-svc", CircuitBreakerConfig{
		MaxRequests: 1, Interval: time.Minute, Timeout: 5 * time.Second, FailureRatio: 0.5,
	})
	now := time.Now()
	cb.now = func() time.Time { return now }

	trip(t, cb)

	cb.now = func() time.Time { return now.Add(6 * time.Second) }
	require.Equal(t, StateHalfOpen, cb.State())

	entered := make(chan struct{})
	release := make(chan struct{})
	blocking := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		close(entered)
		<-release
		w.WriteHeader(http.StatusOK)
	})

	var wg sync.WaitGroup
	wg.Add(1)
	go func() {
		defer wg.Done()
		_, err := execute(t, cb, blocking)
		assert.NoError(t, err)
	}()

	<-entered // the single allowed probe is now in flight

	_, err := execute(t, cb, okHandler())
	require.Error(t, err)
	assert.Contains(t, err.Error(), "too many requests in half-open state")

	close(release)
	wg.Wait()

	// The in-flight probe succeeded, so the breaker closes again.
	assert.Equal(t, StateClosed, cb.State())
}

func TestCircuitBreaker_ClosedGenerationRollsOverAfterInterval(t *testing.T) {
	cb := NewCircuitBreaker("test-svc", CircuitBreakerConfig{
		MaxRequests: 1, Interval: 30 * time.Second, Timeout: 5 * time.Second, FailureRatio: 0.5,
	})
	now := time.Now()
	cb.now = func() time.Time { return now }

	trip(t, cb)

	// Recover: open -> half-open -> closed, which arms the generation expiry.
	cb.now = func() time.Time { return now.Add(6 * time.Second) }
	_, err := execute(t, cb, okHandler())
	require.NoError(t, err)
	require.Equal(t, StateClosed, cb.State())
	require.False(t, cb.expiry.IsZero())

	cb.mu.Lock()
	cb.counts.onFailure()
	failuresBefore := cb.counts.totalFailures
	cb.mu.Unlock()
	require.Equal(t, uint32(1), failuresBefore)

	// Crossing the interval starts a new generation: counts are cleared and
	// the expiry is re-armed, so old failures cannot trip a future breaker.
	rollover := now.Add(6*time.Second + 31*time.Second)
	cb.now = func() time.Time { return rollover }
	require.Equal(t, StateClosed, cb.State())

	cb.mu.Lock()
	defer cb.mu.Unlock()
	assert.Equal(t, uint32(0), cb.counts.totalFailures)
	assert.Equal(t, rollover.Add(30*time.Second), cb.expiry)
}

func TestCircuitBreaker_ZeroIntervalClearsExpiryOnRollover(t *testing.T) {
	cb := NewCircuitBreaker("test-svc", CircuitBreakerConfig{
		MaxRequests: 1, Interval: 0, Timeout: 5 * time.Second, FailureRatio: 0.5,
	})
	now := time.Now()
	cb.now = func() time.Time { return now }

	// A stale generation expiry left over from a previous configuration: with
	// no interval configured the rollover must clear it instead of re-arming
	// it, otherwise every state read would reset the counts.
	cb.counts.onFailure()
	cb.expiry = now.Add(-time.Second)

	require.Equal(t, StateClosed, cb.State())

	cb.mu.Lock()
	defer cb.mu.Unlock()
	assert.Equal(t, uint32(0), cb.counts.totalFailures, "the new generation starts from zero")
	assert.True(t, cb.expiry.IsZero())
}

func TestCircuitBreaker_ExecuteReportsBackendStatusToCaller(t *testing.T) {
	cb := NewCircuitBreaker("test-svc", defaultTestConfig())

	code, err := execute(t, cb, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusNotFound)
	}))

	require.NoError(t, err)
	assert.Equal(t, http.StatusNotFound, code)
	// 4xx is the client's fault, not the backend's: it must not count as a failure.
	cb.mu.Lock()
	defer cb.mu.Unlock()
	assert.Equal(t, uint32(0), cb.counts.totalFailures)
	assert.Equal(t, uint32(1), cb.counts.totalSuccesses)
}

func TestCircuitBreakerManager_GetIsSafeUnderConcurrency(t *testing.T) {
	const (
		attempts   = 64
		goroutines = 8
	)

	// Repeated on a fresh manager each time so the racing callers genuinely
	// contend for the creation of the same, not-yet-existing breaker.
	for attempt := 0; attempt < attempts; attempt++ {
		mgr := NewCircuitBreakerManager(defaultTestConfig())
		results := make([]*CircuitBreaker, goroutines)
		start := make(chan struct{})

		var wg sync.WaitGroup
		for i := 0; i < goroutines; i++ {
			wg.Add(1)
			go func(i int) {
				defer wg.Done()
				<-start
				results[i] = mgr.Get("service-a")
			}(i)
		}
		close(start)
		wg.Wait()

		require.NotNil(t, results[0])
		for i := 1; i < goroutines; i++ {
			require.Same(t, results[0], results[i], "concurrent Get must not create duplicate breakers")
		}
	}
}
