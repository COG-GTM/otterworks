package middleware

import (
	"encoding/json"
	"net"
	"net/http"
	"sync"
	"time"
)

// TokenBucket implements a per-client token bucket rate limiter.
type TokenBucket struct {
	tokens     float64
	maxTokens  float64
	refillRate float64 // tokens per second
	lastRefill time.Time
}

// RateLimiter manages per-client token buckets.
type RateLimiter struct {
	mu        sync.Mutex
	buckets   map[string]*TokenBucket
	rps       int
	jwtSecret string
	now       func() time.Time // for testing
}

// RateLimitOption configures a RateLimiter.
type RateLimitOption func(*RateLimiter)

// KeyBySubject buckets requests carrying a valid JWT by the token's subject
// instead of the client IP, so callers sharing an address (e.g. behind a NAT or
// a proxy hop) cannot exhaust each other's allowance. Requests without a valid
// token are still bucketed by IP.
func KeyBySubject(secret string) RateLimitOption {
	return func(rl *RateLimiter) { rl.jwtSecret = secret }
}

// NewRateLimiter creates a rate limiter with the specified requests per second limit.
func NewRateLimiter(rps int, opts ...RateLimitOption) *RateLimiter {
	rl := &RateLimiter{
		buckets: make(map[string]*TokenBucket),
		rps:     rps,
		now:     time.Now,
	}
	for _, opt := range opts {
		opt(rl)
	}
	go rl.cleanup()
	return rl
}

// Allow checks if a request for the given bucket key is allowed.
func (rl *RateLimiter) Allow(key string) bool {
	rl.mu.Lock()
	defer rl.mu.Unlock()

	now := rl.now()
	bucket, exists := rl.buckets[key]
	if !exists {
		bucket = &TokenBucket{
			tokens:     float64(rl.rps),
			maxTokens:  float64(rl.rps),
			refillRate: float64(rl.rps),
			lastRefill: now,
		}
		rl.buckets[key] = bucket
	}

	elapsed := now.Sub(bucket.lastRefill).Seconds()
	bucket.tokens += elapsed * bucket.refillRate
	if bucket.tokens > bucket.maxTokens {
		bucket.tokens = bucket.maxTokens
	}
	bucket.lastRefill = now

	if bucket.tokens >= 1 {
		bucket.tokens--
		return true
	}
	return false
}

// Handler returns an HTTP middleware that rate-limits by authenticated subject
// (with KeyBySubject) or client IP.
func (rl *RateLimiter) Handler(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if !rl.Allow(rl.bucketKey(r)) {
			w.Header().Set("Content-Type", "application/json")
			w.Header().Set("Retry-After", "1")
			w.WriteHeader(http.StatusTooManyRequests)
			json.NewEncoder(w).Encode(map[string]string{
				"error": "rate limit exceeded",
			})
			return
		}
		next.ServeHTTP(w, r)
	})
}

func (rl *RateLimiter) bucketKey(r *http.Request) string {
	if rl.jwtSecret != "" {
		if tokenStr := extractBearerToken(r); tokenStr != "" {
			if claims, err := validateToken(tokenStr, rl.jwtSecret); err == nil {
				subject := claims.Subject
				if subject == "" {
					subject = claims.UserID
				}
				if subject != "" {
					return "sub:" + subject
				}
			}
		}
	}
	return "ip:" + extractIP(r)
}

func extractIP(r *http.Request) string {
	// ClientIP has already set r.RemoteAddr to the client IP
	host, _, err := net.SplitHostPort(r.RemoteAddr)
	if err != nil {
		return r.RemoteAddr
	}
	return host
}

// cleanup periodically removes stale buckets to prevent memory leaks.
func (rl *RateLimiter) cleanup() {
	ticker := time.NewTicker(5 * time.Minute)
	defer ticker.Stop()
	for range ticker.C {
		rl.mu.Lock()
		now := rl.now()
		for key, bucket := range rl.buckets {
			if now.Sub(bucket.lastRefill) > 10*time.Minute {
				delete(rl.buckets, key)
			}
		}
		rl.mu.Unlock()
	}
}
