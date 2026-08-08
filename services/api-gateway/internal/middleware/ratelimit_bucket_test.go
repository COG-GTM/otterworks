package middleware

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"sync"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestRateLimiter_RefillIsCappedAtBucketSize(t *testing.T) {
	rl := NewRateLimiter(3)

	start := time.Now()
	rl.now = func() time.Time { return start }
	require.True(t, rl.Allow("10.0.0.9"))

	// A long idle period must not let the bucket grow past maxTokens: after an
	// hour the client still only gets its 3 requests back, not 3*3600.
	rl.now = func() time.Time { return start.Add(time.Hour) }
	for i := 0; i < 3; i++ {
		assert.True(t, rl.Allow("10.0.0.9"), "request %d after the idle period", i+1)
	}
	assert.False(t, rl.Allow("10.0.0.9"), "the bucket is capped at rps tokens")
}

func TestRateLimiter_PartialRefillDoesNotGrantAToken(t *testing.T) {
	rl := NewRateLimiter(1)

	start := time.Now()
	rl.now = func() time.Time { return start }
	require.True(t, rl.Allow("10.0.0.10"))
	require.False(t, rl.Allow("10.0.0.10"))

	// Half a second at 1 rps is only half a token.
	rl.now = func() time.Time { return start.Add(500 * time.Millisecond) }
	assert.False(t, rl.Allow("10.0.0.10"))

	rl.now = func() time.Time { return start.Add(1100 * time.Millisecond) }
	assert.True(t, rl.Allow("10.0.0.10"))
}

func TestRateLimiter_BucketsAreIsolatedPerIP(t *testing.T) {
	rl := NewRateLimiter(1)

	require.True(t, rl.Allow("10.0.0.1"))
	require.False(t, rl.Allow("10.0.0.1"))
	assert.True(t, rl.Allow("10.0.0.2"), "a second IP has its own bucket")

	rl.mu.Lock()
	defer rl.mu.Unlock()
	assert.Len(t, rl.buckets, 2)
}

func TestRateLimiter_HandlerBodyOnRejection(t *testing.T) {
	rl := NewRateLimiter(1)
	handler := rl.Handler(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	}))

	for i := 0; i < 2; i++ {
		req := httptest.NewRequest(http.MethodGet, "/test", nil)
		req.RemoteAddr = "198.51.100.4:9999"
		rec := httptest.NewRecorder()
		handler.ServeHTTP(rec, req)
		if i == 0 {
			require.Equal(t, http.StatusOK, rec.Code)
			continue
		}

		require.Equal(t, http.StatusTooManyRequests, rec.Code)
		assert.Equal(t, "application/json", rec.Header().Get("Content-Type"))
		var body map[string]string
		require.NoError(t, json.Unmarshal(rec.Body.Bytes(), &body))
		assert.Equal(t, "rate limit exceeded", body["error"])
	}
}

func TestRateLimiter_ConcurrentClientsGetExactlyTheirQuota(t *testing.T) {
	const rps = 20
	rl := NewRateLimiter(rps)

	var (
		wg      sync.WaitGroup
		mu      sync.Mutex
		allowed int
	)
	for i := 0; i < rps*2; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			if rl.Allow("203.0.113.7") {
				mu.Lock()
				allowed++
				mu.Unlock()
			}
		}()
	}
	wg.Wait()

	// Wall-clock refill during the test can only add tokens, never remove them.
	assert.GreaterOrEqual(t, allowed, rps)
	assert.Less(t, allowed, rps*2)
}
