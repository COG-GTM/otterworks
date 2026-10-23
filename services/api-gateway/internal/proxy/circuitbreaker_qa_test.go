package proxy

import (
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func statusHandler(code int) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) { w.WriteHeader(code) })
}

func run(cb *CircuitBreaker, code, n int) {
	for i := 0; i < n; i++ {
		_ = cb.Execute(statusHandler(code), httptest.NewRecorder(), httptest.NewRequest(http.MethodGet, "/", nil))
	}
}

func fakeClock(cb *CircuitBreaker) *time.Time {
	now := time.Unix(1_700_000_000, 0)
	cb.now = func() time.Time { return now }
	return &now
}

func TestQACircuitBreaker_NeedsMinimumSample(t *testing.T) {
	cb := NewCircuitBreaker("svc", CircuitBreakerConfig{MaxRequests: 1, Interval: time.Minute, Timeout: time.Minute, FailureRatio: 0.1})
	run(cb, http.StatusBadGateway, 4)
	assert.Equal(t, StateClosed, cb.State(), "four failures are below the minimum sample of five")
	run(cb, http.StatusBadGateway, 1)
	assert.Equal(t, StateOpen, cb.State())
}

func TestQACircuitBreaker_HalfOpenFailureReopens(t *testing.T) {
	cb := NewCircuitBreaker("svc", CircuitBreakerConfig{MaxRequests: 2, Interval: time.Minute, Timeout: 10 * time.Second, FailureRatio: 0.5})
	now := fakeClock(cb)
	run(cb, http.StatusInternalServerError, 5)
	require.Equal(t, StateOpen, cb.State())
	*now = now.Add(11 * time.Second)
	require.Equal(t, StateHalfOpen, cb.State())
	run(cb, http.StatusServiceUnavailable, 1)
	assert.Equal(t, StateOpen, cb.State())
}

func TestQACircuitBreaker_HalfOpenLimitsProbes(t *testing.T) {
	cb := NewCircuitBreaker("svc", CircuitBreakerConfig{MaxRequests: 1, Interval: time.Minute, Timeout: time.Second, FailureRatio: 0.5})
	now := fakeClock(cb)
	run(cb, http.StatusInternalServerError, 5)
	*now = now.Add(2 * time.Second)
	require.Equal(t, StateHalfOpen, cb.State())

	// First probe is admitted but blocks; a concurrent second probe is rejected.
	release := make(chan struct{})
	started := make(chan struct{})
	go func() {
		_ = cb.Execute(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
			close(started)
			<-release
		}), httptest.NewRecorder(), httptest.NewRequest(http.MethodGet, "/", nil))
	}()
	<-started
	err := cb.Execute(statusHandler(http.StatusOK), httptest.NewRecorder(), httptest.NewRequest(http.MethodGet, "/", nil))
	close(release)
	assert.Error(t, err)
}

func TestQACircuitBreaker_RejectsWhileOpen(t *testing.T) {
	cb := NewCircuitBreaker("svc", CircuitBreakerConfig{MaxRequests: 1, Interval: time.Minute, Timeout: time.Minute, FailureRatio: 0.5})
	run(cb, http.StatusBadGateway, 5)
	called := false
	err := cb.Execute(http.HandlerFunc(func(http.ResponseWriter, *http.Request) { called = true }), httptest.NewRecorder(), httptest.NewRequest(http.MethodGet, "/", nil))
	assert.Error(t, err)
	assert.False(t, called, "open breaker must not forward to the backend")
}

// QA-GW-06: NewCircuitBreaker never starts the first closed-state generation,
// so CB_INTERVAL_SECONDS is ignored until the breaker has tripped once. A
// gateway that served N healthy requests needs ~1.5N consecutive upstream
// failures before it opens.
func TestQACircuitBreaker_IntervalResetsCountsFromStart(t *testing.T) {
	t.Skip("xfail QA-GW-06: first closed generation never expires; CB interval ignored until first trip (internal/proxy/circuitbreaker.go NewCircuitBreaker)")
	cb := NewCircuitBreaker("svc", CircuitBreakerConfig{MaxRequests: 1, Interval: time.Minute, Timeout: time.Minute, FailureRatio: 0.6})
	now := fakeClock(cb)
	run(cb, http.StatusOK, 100)
	*now = now.Add(2 * time.Minute)
	run(cb, http.StatusBadGateway, 5)
	assert.Equal(t, StateOpen, cb.State())
}

func TestQACircuitBreaker_StaleSuccessesCurrentlyMaskOutage(t *testing.T) {
	cb := NewCircuitBreaker("svc", CircuitBreakerConfig{MaxRequests: 1, Interval: time.Minute, Timeout: time.Minute, FailureRatio: 0.6})
	now := fakeClock(cb)
	run(cb, http.StatusOK, 100)
	*now = now.Add(time.Hour)
	run(cb, http.StatusBadGateway, 100)
	assert.Equal(t, StateClosed, cb.State(), "characterises QA-GW-06")
}
