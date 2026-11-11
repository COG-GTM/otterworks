package middleware

import (
	"encoding/json"
	"net"
	"net/http"
	"sync"
	"time"
)

// DefaultMaxBuckets bounds the limiter's memory when no explicit cap is set.
const DefaultMaxBuckets = 100000

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
	rps        int
	maxBuckets int
	lastPrune  time.Time
	now        func() time.Time // for testing
}

// NewRateLimiter creates a rate limiter with the specified requests per second limit.
func NewRateLimiter(rps int) *RateLimiter {
	return NewRateLimiterWithCap(rps, DefaultMaxBuckets)
}

// NewRateLimiterWithCap creates a rate limiter that tracks at most maxBuckets
// client addresses at once.
func NewRateLimiterWithCap(rps, maxBuckets int) *RateLimiter {
	if maxBuckets <= 0 {
		maxBuckets = DefaultMaxBuckets
	}
	rl := &RateLimiter{
		buckets:    make(map[string]*TokenBucket),
		rps:        rps,
		maxBuckets: maxBuckets,
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
	bucket, exists := rl.buckets[ip]
	if !exists {
		if len(rl.buckets) >= rl.maxBuckets {
			rl.pruneRefilled(now)
			if len(rl.buckets) >= rl.maxBuckets {
				return false
			}
		}
		bucket = &TokenBucket{
			tokens:     float64(rl.rps),
			maxTokens:  float64(rl.rps),
			refillRate: float64(rl.rps),
			lastRefill: now,
		}
		rl.buckets[ip] = bucket
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

// pruneRefilled drops buckets that have been idle long enough to refill
// completely; such a bucket is indistinguishable from a new one, so removing it
// never loosens the limit. It runs at most once per second while the map is full.
func (rl *RateLimiter) pruneRefilled(now time.Time) {
	if now.Sub(rl.lastPrune) < time.Second {
		return
	}
	rl.lastPrune = now
	for ip, b := range rl.buckets {
		if b.tokens+now.Sub(b.lastRefill).Seconds()*b.refillRate >= b.maxTokens {
			delete(rl.buckets, ip)
		}
	}
}

// Handler returns an HTTP middleware that rate-limits by client IP.
func (rl *RateLimiter) Handler(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		ip := extractIP(r)
		if !rl.Allow(ip) {
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
		for ip, bucket := range rl.buckets {
			if now.Sub(bucket.lastRefill) > 10*time.Minute {
				delete(rl.buckets, ip)
			}
		}
		rl.mu.Unlock()
	}
}
