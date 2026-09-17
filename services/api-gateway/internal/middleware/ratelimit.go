package middleware

import (
	"encoding/json"
	"math"
	"net"
	"net/http"
	"strconv"
	"sync"
	"time"

	"github.com/go-chi/chi/v5/middleware"
)

// TokenBucket implements a per-IP token bucket rate limiter.
type TokenBucket struct {
	tokens     float64
	maxTokens  float64
	refillRate float64 // tokens per second
	lastRefill time.Time
}

// RateLimiter manages per-IP token buckets.
type RateLimiter struct {
	mu         sync.Mutex
	buckets    map[string]*TokenBucket
	refillRate float64          // tokens per second
	burst      float64          // bucket size
	now        func() time.Time // for testing
}

// NewRateLimiter creates a rate limiter with the specified requests per second limit.
func NewRateLimiter(rps int) *RateLimiter {
	return NewBurstRateLimiter(float64(rps), float64(rps))
}

// NewBurstRateLimiter creates a rate limiter refilling at refillRate tokens per second
// and allowing bursts of up to burst requests. Rates below one per second are supported.
func NewBurstRateLimiter(refillRate, burst float64) *RateLimiter {
	rl := &RateLimiter{
		buckets:    make(map[string]*TokenBucket),
		refillRate: refillRate,
		burst:      burst,
		now:        time.Now,
	}
	go rl.cleanup()
	return rl
}

// Allow checks if a request from the given IP is allowed.
func (rl *RateLimiter) Allow(ip string) bool {
	rl.mu.Lock()
	defer rl.mu.Unlock()

	now := rl.now()
	bucket := rl.bucketFor(ip, now)
	refill(bucket, now)

	if bucket.tokens >= 1 {
		bucket.tokens--
		return true
	}
	return false
}

// Available reports whether the bucket for the given IP holds a token, without taking
// it. Callers that only spend on some outcomes check with Available and spend with Allow.
func (rl *RateLimiter) Available(ip string) bool {
	rl.mu.Lock()
	defer rl.mu.Unlock()

	now := rl.now()
	bucket := rl.bucketFor(ip, now)
	refill(bucket, now)

	return bucket.tokens >= 1
}

// refill accrues the tokens earned since the bucket was last touched.
func refill(bucket *TokenBucket, now time.Time) {
	elapsed := now.Sub(bucket.lastRefill).Seconds()
	bucket.tokens += elapsed * bucket.refillRate
	if bucket.tokens > bucket.maxTokens {
		bucket.tokens = bucket.maxTokens
	}
	bucket.lastRefill = now
}

// bucketFor returns the bucket for an IP, creating a full one if it has none.
// Callers must hold rl.mu.
func (rl *RateLimiter) bucketFor(ip string, now time.Time) *TokenBucket {
	bucket, exists := rl.buckets[ip]
	if !exists {
		bucket = &TokenBucket{
			tokens:     rl.burst,
			maxTokens:  rl.burst,
			refillRate: rl.refillRate,
			lastRefill: now,
		}
		rl.buckets[ip] = bucket
	}
	return bucket
}

// Handler returns an HTTP middleware that rate-limits by client IP.
func (rl *RateLimiter) Handler(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		ip := extractIP(r)
		if !rl.Allow(ip) {
			rl.reject(w)
			return
		}
		next.ServeHTTP(w, r)
	})
}

// DefaultCredentialPaths returns the exact-match paths where credentials are submitted
// and guessing must be throttled independently of the global limit.
func DefaultCredentialPaths() []string {
	return []string{
		"/api/v1/auth/login",
	}
}

// CredentialThrottle returns an HTTP middleware that limits *rejected* credential
// submissions per client IP on the given paths. Only a rejected submission spends
// budget, so ordinary sign-ins stay unthrottled while password guessing is capped well
// below the global rate limit. Backend faults (5xx) do not spend budget either: an
// outage must not lock users out.
func CredentialThrottle(rl *RateLimiter, paths ...string) func(http.Handler) http.Handler {
	throttled := make(map[string]bool, len(paths))
	for _, p := range paths {
		throttled[p] = true
	}

	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			if !throttled[r.URL.Path] {
				next.ServeHTTP(w, r)
				return
			}

			ip := extractIP(r)
			if !rl.Available(ip) {
				rl.reject(w)
				return
			}

			ww := middleware.NewWrapResponseWriter(w, r.ProtoMajor)
			next.ServeHTTP(ww, r)

			if rejectedCredentials(ww.Status()) {
				rl.Allow(ip)
			}
		})
	}
}

// rejectedCredentials reports whether a login response is a refusal of the submitted
// credentials. auth-service answers an unknown email or a wrong password with a 400
// (IllegalArgumentException), and a malformed body with the same, so 400 counts too.
func rejectedCredentials(status int) bool {
	switch status {
	case http.StatusBadRequest, http.StatusUnauthorized, http.StatusForbidden:
		return true
	default:
		return false
	}
}

func (rl *RateLimiter) reject(w http.ResponseWriter) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Retry-After", strconv.Itoa(rl.retryAfterSeconds()))
	w.WriteHeader(http.StatusTooManyRequests)
	json.NewEncoder(w).Encode(map[string]string{
		"error": "rate limit exceeded",
	})
}

// retryAfterSeconds is how long a drained bucket needs to accrue one token.
func (rl *RateLimiter) retryAfterSeconds() int {
	if rl.refillRate <= 0 {
		return 1
	}
	seconds := int(math.Ceil(1 / rl.refillRate))
	if seconds < 1 {
		return 1
	}
	return seconds
}

func extractIP(r *http.Request) string {
	// chimw.RealIP has already set r.RemoteAddr to the client IP
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
		idleTTL := rl.idleTTL()
		for ip, bucket := range rl.buckets {
			if now.Sub(bucket.lastRefill) > idleTTL {
				delete(rl.buckets, ip)
			}
		}
		rl.mu.Unlock()
	}
}

// idleTTL is how long a bucket must go untouched before dropping it is equivalent to
// keeping it: long enough for an empty bucket to have refilled to capacity.
func (rl *RateLimiter) idleTTL() time.Duration {
	ttl := 10 * time.Minute
	if rl.refillRate <= 0 {
		return ttl
	}
	if full := time.Duration(rl.burst / rl.refillRate * float64(time.Second)); full > ttl {
		return full
	}
	return ttl
}
