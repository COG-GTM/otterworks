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

// loginHandler builds a throttled login handler whose backend always answers status.
func loginHandler(rl *RateLimiter, status int) http.Handler {
	return CredentialThrottle(rl, "/api/v1/auth/login")(
		http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			w.WriteHeader(status)
		}))
}

func postLogin(handler http.Handler) *httptest.ResponseRecorder {
	req := httptest.NewRequest(http.MethodPost, "/api/v1/auth/login", nil)
	req.RemoteAddr = "192.168.1.1:12345"
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)
	return rec
}

// auth-service answers wrong credentials with 400, not 401.
func TestCredentialThrottle_LimitsRejectedLogins(t *testing.T) {
	for _, status := range []int{http.StatusBadRequest, http.StatusUnauthorized} {
		rl := NewBurstRateLimiter(10.0/60, 3)
		now := time.Now()
		rl.now = func() time.Time { return now }
		handler := loginHandler(rl, status)

		for i := 0; i < 3; i++ {
			assert.Equal(t, status, postLogin(handler).Code, "attempt %d should reach the backend", i+1)
		}

		rec := postLogin(handler)
		assert.Equal(t, http.StatusTooManyRequests, rec.Code, "backend status %d should be throttled", status)
		assert.Equal(t, "6", rec.Header().Get("Retry-After"))
	}
}

func TestCredentialThrottle_BackendFailuresDoNotSpendBudget(t *testing.T) {
	rl := NewBurstRateLimiter(10.0/60, 3)
	now := time.Now()
	rl.now = func() time.Time { return now }
	handler := loginHandler(rl, http.StatusBadGateway)

	for i := 0; i < 10; i++ {
		assert.Equal(t, http.StatusBadGateway, postLogin(handler).Code, "attempt %d should reach the backend", i+1)
	}
}

func TestCredentialThrottle_SuccessfulLoginsAreNotThrottled(t *testing.T) {
	rl := NewBurstRateLimiter(10.0/60, 3)
	now := time.Now()
	rl.now = func() time.Time { return now }

	handler := loginHandler(rl, http.StatusOK)

	for i := 0; i < 10; i++ {
		assert.Equal(t, http.StatusOK, postLogin(handler).Code, "successful login %d should not be throttled", i+1)
	}
}

func TestCredentialThrottle_OtherPathsUnaffected(t *testing.T) {
	rl := NewBurstRateLimiter(10.0/60, 1)
	now := time.Now()
	rl.now = func() time.Time { return now }

	handler := loginHandler(rl, http.StatusBadRequest)

	for i := 0; i < 5; i++ {
		req := httptest.NewRequest(http.MethodGet, "/api/v1/files", nil)
		req.RemoteAddr = "192.168.1.1:12345"
		rec := httptest.NewRecorder()
		handler.ServeHTTP(rec, req)
		assert.Equal(t, http.StatusBadRequest, rec.Code, "request %d should pass through", i+1)
	}
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
			name:       "Uses RemoteAddr set by chimw.RealIP",
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
