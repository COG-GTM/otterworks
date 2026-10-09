package middleware

import (
	"container/list"
	"encoding/json"
	"net"
	"net/http"
	"sync"
	"time"
)

// DefaultMaxBuckets bounds the limiter's memory when RATE_LIMIT_MAX_BUCKETS
// is unset.
const DefaultMaxBuckets = 50000

// bucketRefillWindow is how long an untouched bucket takes to refill: capacity
// and refill rate are both rps.
const bucketRefillWindow = time.Second

// TokenBucket implements a per-IP token bucket rate limiter.
type TokenBucket struct {
	key        string
	tokens     float64
	maxTokens  float64
	refillRate float64 // tokens per second
	lastRefill time.Time
	elem       *list.Element
}

// RateLimiter manages per-IP token buckets. At most maxBuckets are kept: a
// bucket idle long enough to have refilled is indistinguishable from a new one
// and is dropped first; otherwise the least recently used bucket is evicted.
type RateLimiter struct {
	mu         sync.Mutex
	buckets    map[string]*TokenBucket
	lru        *list.List // front = most recently used
	rps        int
	maxBuckets int
	now        func() time.Time // for testing
}

// NewRateLimiter creates a rate limiter with the specified requests per second
// limit, holding at most maxBuckets buckets (DefaultMaxBuckets if <= 0).
func NewRateLimiter(rps, maxBuckets int) *RateLimiter {
	if maxBuckets <= 0 {
		maxBuckets = DefaultMaxBuckets
	}
	rl := &RateLimiter{
		buckets:    make(map[string]*TokenBucket),
		lru:        list.New(),
		rps:        rps,
		maxBuckets: maxBuckets,
		now:        time.Now,
	}
	go rl.cleanup()
	return rl
}

// Allow checks if a request from the given IP is allowed.
func (rl *RateLimiter) Allow(ip string) bool {
	if rl.rps <= 0 {
		return false
	}
	rl.mu.Lock()
	defer rl.mu.Unlock()

	now := rl.now()
	bucket, exists := rl.buckets[ip]
	if !exists {
		if len(rl.buckets) >= rl.maxBuckets {
			rl.evictLocked(now)
		}
		bucket = &TokenBucket{
			key:        ip,
			tokens:     float64(rl.rps),
			maxTokens:  float64(rl.rps),
			refillRate: float64(rl.rps),
			lastRefill: now,
		}
		bucket.elem = rl.lru.PushFront(bucket)
		rl.buckets[ip] = bucket
	} else {
		rl.lru.MoveToFront(bucket.elem)
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

// evictLocked frees room for one bucket: refilled buckets go first, then the
// least recently used one.
func (rl *RateLimiter) evictLocked(now time.Time) {
	rl.pruneLocked(now)
	for len(rl.buckets) >= rl.maxBuckets {
		rl.removeLocked(rl.lru.Back().Value.(*TokenBucket))
	}
}

// pruneLocked drops buckets that have refilled completely; recreating one
// later yields the same full bucket, so this never changes a decision.
func (rl *RateLimiter) pruneLocked(now time.Time) {
	for e := rl.lru.Back(); e != nil; {
		bucket := e.Value.(*TokenBucket)
		if now.Sub(bucket.lastRefill) < bucketRefillWindow {
			return
		}
		e = e.Prev()
		rl.removeLocked(bucket)
	}
}

func (rl *RateLimiter) removeLocked(bucket *TokenBucket) {
	rl.lru.Remove(bucket.elem)
	delete(rl.buckets, bucket.key)
}

// Len reports how many buckets are held.
func (rl *RateLimiter) Len() int {
	rl.mu.Lock()
	defer rl.mu.Unlock()
	return len(rl.buckets)
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
	// ClientIP has already set r.RemoteAddr to the TCP peer, or to the
	// X-Forwarded-For client when the peer is a trusted proxy.
	host, _, err := net.SplitHostPort(r.RemoteAddr)
	if err != nil {
		return r.RemoteAddr
	}
	return host
}

// cleanup periodically removes refilled buckets to prevent memory leaks.
func (rl *RateLimiter) cleanup() {
	ticker := time.NewTicker(time.Minute)
	defer ticker.Stop()
	for range ticker.C {
		rl.mu.Lock()
		rl.pruneLocked(rl.now())
		rl.mu.Unlock()
	}
}
