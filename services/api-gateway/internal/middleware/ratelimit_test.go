package middleware

import (
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestRateLimiter_Allow(t *testing.T) {
	rl := NewRateLimiter(5)

	// First 5 requests should be allowed
	for i := 0; i < 5; i++ {
		assert.True(t, rl.Allow("192.168.1.1"), "request %d should be allowed", i+1)
	}

	// 6th request should be denied
	assert.False(t, rl.Allow("192.168.1.1"), "6th request should be denied")

	// Different IP should still be allowed
	assert.True(t, rl.Allow("192.168.1.2"), "different IP should be allowed")
}

func TestRateLimiter_TokenRefill(t *testing.T) {
	rl := NewRateLimiter(2)

	now := time.Now()
	rl.now = func() time.Time { return now }

	// Consume all tokens
	assert.True(t, rl.Allow("10.0.0.1"))
	assert.True(t, rl.Allow("10.0.0.1"))
	assert.False(t, rl.Allow("10.0.0.1"))

	// Advance time by 1 second - should refill 2 tokens
	rl.now = func() time.Time { return now.Add(1 * time.Second) }
	assert.True(t, rl.Allow("10.0.0.1"))
	assert.True(t, rl.Allow("10.0.0.1"))
	assert.False(t, rl.Allow("10.0.0.1"))
}

func TestRateLimiter_Handler(t *testing.T) {
	rl := NewRateLimiter(2)

	handler := rl.Handler(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	}))

	// First 2 requests succeed
	for i := 0; i < 2; i++ {
		req := httptest.NewRequest(http.MethodGet, "/test", nil)
		req.RemoteAddr = "192.168.1.1:12345"
		rec := httptest.NewRecorder()
		handler.ServeHTTP(rec, req)
		assert.Equal(t, http.StatusOK, rec.Code, "request %d should succeed", i+1)
	}

	// 3rd request gets rate limited
	req := httptest.NewRequest(http.MethodGet, "/test", nil)
	req.RemoteAddr = "192.168.1.1:12345"
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)
	assert.Equal(t, http.StatusTooManyRequests, rec.Code)
	assert.Equal(t, "1", rec.Header().Get("Retry-After"))
}

func TestExtractIP(t *testing.T) {
	tests := []struct {
		name       string
		remoteAddr string
		expected   string
	}{
		{
			name:       "RemoteAddr with port",
			remoteAddr: "10.0.0.1:5678",
			expected:   "10.0.0.1",
		},
		{
			name:       "RemoteAddr without port",
			remoteAddr: "10.0.0.1",
			expected:   "10.0.0.1",
		},
		{
			name:       "Uses RemoteAddr set by ClientIP",
			remoteAddr: "203.0.113.50:1234",
			expected:   "203.0.113.50",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			req := httptest.NewRequest(http.MethodGet, "/", nil)
			req.RemoteAddr = tt.remoteAddr
			result := extractIP(req)
			require.Equal(t, tt.expected, result)
		})
	}
}

func TestRateLimiter_BucketCap(t *testing.T) {
	rl := NewRateLimiterWithCap(5, 3)
	now := time.Now()
	rl.now = func() time.Time { return now }

	assert.True(t, rl.Allow("10.0.0.1"))
	assert.True(t, rl.Allow("10.0.0.2"))
	assert.True(t, rl.Allow("10.0.0.3"))

	// Map is full of active buckets: a new address is refused, not tracked.
	assert.False(t, rl.Allow("10.0.0.4"))
	assert.Len(t, rl.buckets, 3)

	// Known addresses keep working.
	assert.True(t, rl.Allow("10.0.0.1"))

	// Once existing buckets have refilled they are pruned to make room.
	rl.now = func() time.Time { return now.Add(2 * time.Second) }
	assert.True(t, rl.Allow("10.0.0.4"))
	assert.LessOrEqual(t, len(rl.buckets), 3)
}

func TestRateLimiter_BucketCapDoesNotResetActiveLimits(t *testing.T) {
	rl := NewRateLimiterWithCap(2, 2)
	now := time.Now()
	rl.now = func() time.Time { return now }

	assert.True(t, rl.Allow("10.0.0.1"))
	assert.True(t, rl.Allow("10.0.0.1"))
	assert.False(t, rl.Allow("10.0.0.1"))

	rl.now = func() time.Time { return now.Add(1100 * time.Millisecond) }
	assert.True(t, rl.Allow("10.0.0.2"))
	assert.True(t, rl.Allow("10.0.0.3")) // prunes refilled 10.0.0.1

	// 10.0.0.2 was just used, so it was not pruned and is still limited.
	assert.True(t, rl.Allow("10.0.0.2"))
	assert.False(t, rl.Allow("10.0.0.2"))
}
