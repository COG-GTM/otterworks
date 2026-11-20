package middleware

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/alicebob/miniredis/v2"
	"github.com/golang-jwt/jwt/v5"
	"github.com/redis/go-redis/v9"
	"github.com/rs/zerolog"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestMemoryLimiter_Take(t *testing.T) {
	ml := NewMemoryLimiter(5, 5)
	ctx := context.Background()

	for i := 0; i < 5; i++ {
		res, err := ml.Take(ctx, "ip:192.168.1.1")
		require.NoError(t, err)
		assert.True(t, res.Allowed, "request %d should be allowed", i+1)
		assert.Equal(t, 5, res.Limit)
		assert.Equal(t, 4-i, res.Remaining)
	}

	res, _ := ml.Take(ctx, "ip:192.168.1.1")
	assert.False(t, res.Allowed, "6th request should be denied")
	assert.Greater(t, res.RetryAfter, time.Duration(0))

	res, _ = ml.Take(ctx, "ip:192.168.1.2")
	assert.True(t, res.Allowed, "different client should be allowed")
}

func TestMemoryLimiter_TokenRefill(t *testing.T) {
	ml := NewMemoryLimiter(2, 2)
	ctx := context.Background()

	now := time.Now()
	ml.now = func() time.Time { return now }

	take := func() bool {
		res, err := ml.Take(ctx, "ip:10.0.0.1")
		require.NoError(t, err)
		return res.Allowed
	}

	assert.True(t, take())
	assert.True(t, take())
	assert.False(t, take())

	// 1 second at 2 tokens/s refills 2 tokens
	ml.now = func() time.Time { return now.Add(1 * time.Second) }
	assert.True(t, take())
	assert.True(t, take())
	assert.False(t, take())
}

func TestMemoryLimiter_BurstSeparateFromRate(t *testing.T) {
	ml := NewMemoryLimiter(1, 3)
	ctx := context.Background()
	now := time.Now()
	ml.now = func() time.Time { return now }

	for i := 0; i < 3; i++ {
		res, _ := ml.Take(ctx, "k")
		assert.True(t, res.Allowed)
	}
	res, _ := ml.Take(ctx, "k")
	assert.False(t, res.Allowed)
	assert.Equal(t, time.Second, res.RetryAfter)
}

func newTestRedis(t *testing.T) (*miniredis.Miniredis, *redis.Client) {
	t.Helper()
	mr := miniredis.RunT(t)
	client := redis.NewClient(&redis.Options{Addr: mr.Addr()})
	t.Cleanup(func() { _ = client.Close() })
	return mr, client
}

func TestRedisLimiter_Take(t *testing.T) {
	mr, client := newTestRedis(t)
	now := time.Unix(1_700_000_000, 0)
	mr.SetTime(now)

	rl := NewRedisLimiter(client, 2, 3, "rl:", time.Second)
	ctx := context.Background()

	for i := 0; i < 3; i++ {
		res, err := rl.Take(ctx, "user:alice")
		require.NoError(t, err)
		assert.True(t, res.Allowed, "request %d should be allowed", i+1)
		assert.Equal(t, 3, res.Limit)
		assert.Equal(t, 2-i, res.Remaining)
	}

	res, err := rl.Take(ctx, "user:alice")
	require.NoError(t, err)
	assert.False(t, res.Allowed)
	assert.Equal(t, 0, res.Remaining)
	assert.Equal(t, 500*time.Millisecond, res.RetryAfter)

	// Other clients have their own bucket.
	res, err = rl.Take(ctx, "user:bob")
	require.NoError(t, err)
	assert.True(t, res.Allowed)

	// State is stored under the prefix with a TTL.
	assert.True(t, mr.Exists("rl:user:alice"))
	assert.Greater(t, mr.TTL("rl:user:alice"), time.Duration(0))

	// Refill based on the Redis server clock: 1s at 2 tokens/s.
	mr.SetTime(now.Add(time.Second))
	for i := 0; i < 2; i++ {
		res, err = rl.Take(ctx, "user:alice")
		require.NoError(t, err)
		assert.True(t, res.Allowed)
	}
	res, err = rl.Take(ctx, "user:alice")
	require.NoError(t, err)
	assert.False(t, res.Allowed)
}

func TestRedisLimiter_SharedAcrossInstances(t *testing.T) {
	mr, client := newTestRedis(t)
	mr.SetTime(time.Unix(1_700_000_000, 0))

	a := NewRedisLimiter(client, 1, 2, "rl:", time.Second)
	b := NewRedisLimiter(client, 1, 2, "rl:", time.Second)
	ctx := context.Background()

	res, _ := a.Take(ctx, "ip:10.0.0.1")
	assert.True(t, res.Allowed)
	res, _ = b.Take(ctx, "ip:10.0.0.1")
	assert.True(t, res.Allowed)
	res, _ = a.Take(ctx, "ip:10.0.0.1")
	assert.False(t, res.Allowed, "bucket must be shared between gateway replicas")
}

func TestRedisLimiter_Error(t *testing.T) {
	mr, client := newTestRedis(t)
	mr.Close()

	rl := NewRedisLimiter(client, 1, 1, "rl:", 50*time.Millisecond)
	_, err := rl.Take(context.Background(), "k")
	assert.Error(t, err)
}

func doRequest(h http.Handler, remoteAddr, auth, path string) *httptest.ResponseRecorder {
	req := httptest.NewRequest(http.MethodGet, path, nil)
	req.RemoteAddr = remoteAddr
	if auth != "" {
		req.Header.Set("Authorization", auth)
	}
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	return rec
}

var okHandler = http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
	w.WriteHeader(http.StatusOK)
})

func TestRateLimit_Handler(t *testing.T) {
	ml := NewMemoryLimiter(0.25, 2)
	handler := RateLimit(RateLimitConfig{Limiter: ml, Backend: "memory", Logger: zerolog.Nop()})(okHandler)

	for i := 0; i < 2; i++ {
		rec := doRequest(handler, "192.168.1.1:12345", "", "/test")
		assert.Equal(t, http.StatusOK, rec.Code, "request %d should succeed", i+1)
		assert.Equal(t, "2", rec.Header().Get("X-RateLimit-Limit"))
		assert.Equal(t, []string{"1", "0"}[i], rec.Header().Get("X-RateLimit-Remaining"))
	}

	rec := doRequest(handler, "192.168.1.1:12345", "", "/test")
	assert.Equal(t, http.StatusTooManyRequests, rec.Code)
	assert.Equal(t, "4", rec.Header().Get("Retry-After"), "1 token at 0.25 tokens/s needs 4s")
	assert.Equal(t, "application/json", rec.Header().Get("Content-Type"))
	assert.JSONEq(t, `{"error":"rate limit exceeded"}`, rec.Body.String())
}

func TestRateLimit_ExemptPrefixes(t *testing.T) {
	ml := NewMemoryLimiter(1, 1)
	handler := RateLimit(RateLimitConfig{
		Limiter:        ml,
		ExemptPrefixes: []string{"/health"},
		Logger:         zerolog.Nop(),
	})(okHandler)

	for i := 0; i < 5; i++ {
		assert.Equal(t, http.StatusOK, doRequest(handler, "10.0.0.1:1", "", "/health").Code)
	}
	assert.Equal(t, http.StatusOK, doRequest(handler, "10.0.0.1:1", "", "/api/v1/files").Code)
	assert.Equal(t, http.StatusTooManyRequests, doRequest(handler, "10.0.0.1:1", "", "/api/v1/files").Code)
}

type failingLimiter struct{}

func (failingLimiter) Take(context.Context, string) (RateLimitResult, error) {
	return RateLimitResult{}, errors.New("redis down")
}

func TestRateLimit_FallbackOnError(t *testing.T) {
	handler := RateLimit(RateLimitConfig{
		Limiter:  failingLimiter{},
		Backend:  "redis",
		Fallback: NewMemoryLimiter(1, 1),
		Logger:   zerolog.Nop(),
	})(okHandler)

	assert.Equal(t, http.StatusOK, doRequest(handler, "10.0.0.1:1", "", "/x").Code)
	rec := doRequest(handler, "10.0.0.1:1", "", "/x")
	assert.Equal(t, http.StatusTooManyRequests, rec.Code)
	assert.Equal(t, "1", rec.Header().Get("Retry-After"))
}

func TestRateLimit_FailOpenWithoutFallback(t *testing.T) {
	handler := RateLimit(RateLimitConfig{Limiter: failingLimiter{}, Logger: zerolog.Nop()})(okHandler)
	for i := 0; i < 3; i++ {
		assert.Equal(t, http.StatusOK, doRequest(handler, "10.0.0.1:1", "", "/x").Code)
	}
}

func TestRateLimit_RedisBackedPerUser(t *testing.T) {
	mr, client := newTestRedis(t)
	mr.SetTime(time.Unix(1_700_000_000, 0))
	secret := "test-secret"

	handler := RateLimit(RateLimitConfig{
		Limiter: NewRedisLimiter(client, 1, 1, "rl:", time.Second),
		Backend: "redis",
		KeyFunc: ClientKey(secret),
		Logger:  zerolog.Nop(),
	})(okHandler)

	alice := "Bearer " + generateTestToken(t, secret, JWTClaims{
		RegisteredClaims: jwt.RegisteredClaims{Subject: "alice", ExpiresAt: jwt.NewNumericDate(time.Now().Add(time.Hour))},
	})
	bob := "Bearer " + generateTestToken(t, secret, JWTClaims{
		RegisteredClaims: jwt.RegisteredClaims{Subject: "bob", ExpiresAt: jwt.NewNumericDate(time.Now().Add(time.Hour))},
	})

	// Same IP, different users: separate buckets.
	assert.Equal(t, http.StatusOK, doRequest(handler, "10.0.0.1:1", alice, "/x").Code)
	assert.Equal(t, http.StatusOK, doRequest(handler, "10.0.0.1:1", bob, "/x").Code)
	assert.Equal(t, http.StatusTooManyRequests, doRequest(handler, "10.0.0.1:1", alice, "/x").Code)

	// Same user from another IP shares the user's bucket.
	assert.Equal(t, http.StatusTooManyRequests, doRequest(handler, "10.0.0.2:1", alice, "/x").Code)
	assert.True(t, mr.Exists("rl:user:alice"))
}

func TestClientKey(t *testing.T) {
	secret := "test-secret"
	keyFunc := ClientKey(secret)
	exp := jwt.NewNumericDate(time.Now().Add(time.Hour))

	tests := []struct {
		name     string
		auth     string
		expected string
	}{
		{"no token", "", "ip:10.0.0.1"},
		{"subject claim", "Bearer " + generateTestToken(t, secret, JWTClaims{RegisteredClaims: jwt.RegisteredClaims{Subject: "u1", ExpiresAt: exp}}), "user:u1"},
		{"user_id claim", "Bearer " + generateTestToken(t, secret, JWTClaims{UserID: "u2", RegisteredClaims: jwt.RegisteredClaims{ExpiresAt: exp}}), "user:u2"},
		{"wrong secret", "Bearer " + generateTestToken(t, "other", JWTClaims{RegisteredClaims: jwt.RegisteredClaims{Subject: "u1", ExpiresAt: exp}}), "ip:10.0.0.1"},
		{"garbage token", "Bearer not-a-jwt", "ip:10.0.0.1"},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			req := httptest.NewRequest(http.MethodGet, "/", nil)
			req.RemoteAddr = "10.0.0.1:5678"
			if tt.auth != "" {
				req.Header.Set("Authorization", tt.auth)
			}
			assert.Equal(t, tt.expected, keyFunc(req))
		})
	}
}

func TestClientKey_IPOnlyPaths(t *testing.T) {
	secret := "test-secret"
	keyFunc := ClientKey(secret, "/api/v1/auth/login")
	token := generateTestToken(t, secret, JWTClaims{RegisteredClaims: jwt.RegisteredClaims{
		Subject: "u1", ExpiresAt: jwt.NewNumericDate(time.Now().Add(time.Hour)),
	}})

	for path, expected := range map[string]string{
		"/api/v1/auth/login": "ip:10.0.0.1",
		"/api/v1/files":      "user:u1",
	} {
		req := httptest.NewRequest(http.MethodPost, path, nil)
		req.RemoteAddr = "10.0.0.1:5678"
		req.Header.Set("Authorization", "Bearer "+token)
		assert.Equal(t, expected, keyFunc(req), path)
	}
}

func TestMemoryLimiter_EvictIdleWaitsForFullRefill(t *testing.T) {
	ml := NewMemoryLimiter(0.001, 2) // full refill takes 2000s
	now := time.Unix(1000, 0)
	ml.now = func() time.Time { return now }
	ctx := context.Background()

	for i := 0; i < 2; i++ {
		res, _ := ml.Take(ctx, "k")
		require.True(t, res.Allowed)
	}

	now = now.Add(15 * time.Minute)
	ml.evictIdle()
	res, _ := ml.Take(ctx, "k")
	assert.False(t, res.Allowed, "a depleted bucket must not be reset before it refills")

	now = now.Add(2001 * time.Second)
	ml.evictIdle()
	ml.mu.Lock()
	_, exists := ml.buckets["k"]
	ml.mu.Unlock()
	assert.False(t, exists)
}

func TestRetryAfterSeconds(t *testing.T) {
	assert.Equal(t, 1, retryAfterSeconds(0))
	assert.Equal(t, 1, retryAfterSeconds(10*time.Millisecond))
	assert.Equal(t, 1, retryAfterSeconds(time.Second))
	assert.Equal(t, 2, retryAfterSeconds(1001*time.Millisecond))
}

func TestExtractIP(t *testing.T) {
	tests := []struct {
		name       string
		remoteAddr string
		expected   string
	}{
		{"RemoteAddr with port", "10.0.0.1:5678", "10.0.0.1"},
		{"RemoteAddr without port", "10.0.0.1", "10.0.0.1"},
		{"Uses RemoteAddr set by chimw.RealIP", "203.0.113.50:1234", "203.0.113.50"},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			req := httptest.NewRequest(http.MethodGet, "/", nil)
			req.RemoteAddr = tt.remoteAddr
			require.Equal(t, tt.expected, extractIP(req))
		})
	}
}
