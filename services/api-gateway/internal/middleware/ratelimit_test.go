package middleware

import (
	"fmt"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestRateLimiter_Allow(t *testing.T) {
	rl := NewRateLimiter(5, 0)

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
	rl := NewRateLimiter(2, 0)

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
	rl := NewRateLimiter(2, 0)

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

func TestRateLimiter_RotatingKeysStayBounded(t *testing.T) {
	rl := NewRateLimiter(5, 100)
	now := time.Now()
	rl.now = func() time.Time { return now }

	for i := 0; i < 10000; i++ {
		rl.Allow(fmt.Sprintf("10.9.%d.%d", i/256, i%256))
	}
	assert.LessOrEqual(t, rl.Len(), 100)
}

func TestRateLimiter_EvictsRefilledBucketsBeforeActiveOnes(t *testing.T) {
	rl := NewRateLimiter(2, 3)
	now := time.Now()
	rl.now = func() time.Time { return now }

	assert.True(t, rl.Allow("idle"))
	now = now.Add(2 * time.Second)
	assert.True(t, rl.Allow("busy"))
	assert.True(t, rl.Allow("busy"))
	assert.False(t, rl.Allow("busy"))
	assert.True(t, rl.Allow("other"))

	// Map is full; the refilled "idle" bucket is dropped, "busy" keeps its debt.
	assert.True(t, rl.Allow("new"))
	assert.Equal(t, 3, rl.Len())
	assert.False(t, rl.Allow("busy"))
}

func TestRateLimiter_EvictsLeastRecentlyUsedWhenAllActive(t *testing.T) {
	rl := NewRateLimiter(1, 2)
	now := time.Now()
	rl.now = func() time.Time { return now }

	assert.True(t, rl.Allow("a"))
	assert.True(t, rl.Allow("b"))
	assert.False(t, rl.Allow("a")) // a is now most recently used
	assert.True(t, rl.Allow("c"))  // evicts b
	assert.Equal(t, 2, rl.Len())
	assert.False(t, rl.Allow("a"))
}

func TestRateLimiter_ZeroRPSDeniesWithoutStoring(t *testing.T) {
	rl := NewRateLimiter(0, 0)
	assert.False(t, rl.Allow("10.0.0.1"))
	assert.Equal(t, 0, rl.Len())
}

func TestRateLimiter_SpoofedForwardingHeadersShareOneBucket(t *testing.T) {
	rl := NewRateLimiter(2, 0)
	handler := ClientIP(nil)(rl.Handler(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	})))

	codes := map[int]int{}
	for i := 0; i < 10; i++ {
		req := httptest.NewRequest(http.MethodPost, "/api/v1/auth/login", nil)
		req.RemoteAddr = "198.51.100.7:40000"
		req.Header.Set("True-Client-IP", fmt.Sprintf("203.0.113.%d", i))
		req.Header.Set("X-Real-IP", fmt.Sprintf("203.0.114.%d", i))
		req.Header.Set("X-Forwarded-For", fmt.Sprintf("10.9.0.%d", i))
		rec := httptest.NewRecorder()
		handler.ServeHTTP(rec, req)
		codes[rec.Code]++
	}
	assert.Equal(t, 2, codes[http.StatusOK])
	assert.Equal(t, 8, codes[http.StatusTooManyRequests])
}
