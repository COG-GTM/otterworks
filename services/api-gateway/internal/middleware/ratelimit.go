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

// Refund returns a token taken by Allow to the bucket for the given IP.
func (rl *RateLimiter) Refund(ip string) {
	rl.mu.Lock()
	defer rl.mu.Unlock()

	bucket := rl.bucketFor(ip, rl.now())
	bucket.tokens = math.Min(bucket.tokens+1, bucket.maxTokens)
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
// submissions per client IP on the given paths. A request whose response is not an
// authentication failure has its token refunded, so ordinary sign-ins stay unthrottled
// while password guessing is capped well below the global rate limit.
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
			if !rl.Allow(ip) {
				rl.reject(w)
				return
			}

			ww := middleware.NewWrapResponseWriter(w, r.ProtoMajor)
			next.ServeHTTP(ww, r)

			if status := ww.Status(); status != http.StatusUnauthorized && status != http.StatusForbidden {
				rl.Refund(ip)
			}
		})
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
		for ip, bucket := range rl.buckets {
			if now.Sub(bucket.lastRefill) > 10*time.Minute {
				delete(rl.buckets, ip)
			}
		}
		rl.mu.Unlock()
	}
}
