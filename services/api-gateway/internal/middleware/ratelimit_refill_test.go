package middleware

import (
	"net/http"
	"net/http/httptest"
	"sync"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestRateLimiter_RefillIsCappedAtBurstSize(t *testing.T) {
	rl := NewRateLimiter(3)
	now := time.Now()
	rl.now = func() time.Time { return now }

	require.True(t, rl.Allow("1.2.3.4"))

	// A long idle period must not let the bucket accumulate more than one
	// second's worth of tokens, otherwise a client could bank a huge burst.
	rl.now = func() time.Time { return now.Add(time.Hour) }

	for i := 0; i < 3; i++ {
		assert.True(t, rl.Allow("1.2.3.4"), "token %d of the capped burst", i+1)
	}
	assert.False(t, rl.Allow("1.2.3.4"), "the bucket is capped at the configured rps")
}

func TestRateLimiter_BucketsAreIsolatedPerIP(t *testing.T) {
	rl := NewRateLimiter(1)
	now := time.Now()
	rl.now = func() time.Time { return now }

	require.True(t, rl.Allow("1.1.1.1"))
	require.False(t, rl.Allow("1.1.1.1"))

	assert.True(t, rl.Allow("2.2.2.2"), "a second client starts with a full bucket")
}

func TestRateLimiter_HandlerIsSafeUnderConcurrency(t *testing.T) {
	const (
		rps     = 20
		clients = 50
	)

	rl := NewRateLimiter(rps)
	now := time.Now()
	rl.now = func() time.Time { return now }

	handler := rl.Handler(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	}))

	var (
		mu       sync.Mutex
		allowed  int
		rejected int
		wg       sync.WaitGroup
	)
	start := make(chan struct{})

	for i := 0; i < clients; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			req := httptest.NewRequest(http.MethodGet, "/api/v1/files", nil)
			req.RemoteAddr = "9.9.9.9:1234"
			rec := httptest.NewRecorder()
			<-start
			handler.ServeHTTP(rec, req)

			mu.Lock()
			defer mu.Unlock()
			if rec.Code == http.StatusTooManyRequests {
				rejected++
				assert.Equal(t, "1", rec.Header().Get("Retry-After"))
				assert.JSONEq(t, `{"error":"rate limit exceeded"}`, rec.Body.String())
			} else {
				allowed++
				assert.Equal(t, http.StatusOK, rec.Code)
			}
		}()
	}
	close(start)
	wg.Wait()

	// Time is frozen, so exactly one bucket's worth of tokens may be spent no
	// matter how the goroutines interleave.
	assert.Equal(t, rps, allowed)
	assert.Equal(t, clients-rps, rejected)
}
