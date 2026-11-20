package middleware

import (
	"context"
	"encoding/json"
	"math"
	"net"
	"net/http"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promauto"
	"github.com/redis/go-redis/v9"
	"github.com/rs/zerolog"
)

var rateLimitDecisions = promauto.NewCounterVec(
	prometheus.CounterOpts{
		Namespace: "api_gateway",
		Name:      "rate_limit_decisions_total",
		Help:      "Rate limit decisions by backend and result.",
	},
	[]string{"backend", "result"},
)

// RateLimitResult is the outcome of taking one token from a client's bucket.
type RateLimitResult struct {
	Allowed    bool
	Limit      int
	Remaining  int
	RetryAfter time.Duration
}

// Limiter takes a token from the bucket identified by key.
type Limiter interface {
	Take(ctx context.Context, key string) (RateLimitResult, error)
}

// TokenBucket is the in-memory state of one client's bucket.
type TokenBucket struct {
	tokens     float64
	lastRefill time.Time
}

// MemoryLimiter is a process-local token bucket limiter. It is used when
// Redis is disabled and as the fallback when Redis is unreachable.
type MemoryLimiter struct {
	mu      sync.Mutex
	buckets map[string]*TokenBucket
	rate    float64
	burst   float64
	now     func() time.Time
}

// NewMemoryLimiter creates an in-memory limiter refilling rate tokens per
// second up to burst tokens.
func NewMemoryLimiter(rate float64, burst int) *MemoryLimiter {
	ml := &MemoryLimiter{
		buckets: make(map[string]*TokenBucket),
		rate:    rate,
		burst:   float64(burst),
		now:     time.Now,
	}
	go ml.cleanup()
	return ml
}

// Take implements Limiter.
func (ml *MemoryLimiter) Take(_ context.Context, key string) (RateLimitResult, error) {
	ml.mu.Lock()
	defer ml.mu.Unlock()

	now := ml.now()
	bucket, exists := ml.buckets[key]
	if !exists {
		bucket = &TokenBucket{tokens: ml.burst, lastRefill: now}
		ml.buckets[key] = bucket
	}

	if elapsed := now.Sub(bucket.lastRefill).Seconds(); elapsed > 0 {
		bucket.tokens = math.Min(ml.burst, bucket.tokens+elapsed*ml.rate)
	}
	bucket.lastRefill = now

	res := RateLimitResult{Limit: int(ml.burst)}
	if bucket.tokens >= 1 {
		bucket.tokens--
		res.Allowed = true
	} else {
		res.RetryAfter = time.Duration((1 - bucket.tokens) / ml.rate * float64(time.Second))
	}
	res.Remaining = int(bucket.tokens)
	return res, nil
}

// cleanup periodically removes stale buckets to prevent memory leaks.
func (ml *MemoryLimiter) cleanup() {
	ticker := time.NewTicker(5 * time.Minute)
	defer ticker.Stop()
	for range ticker.C {
		ml.evictIdle()
	}
}

// evictIdle drops buckets idle long enough to have refilled completely, so
// recreating one at full burst grants nothing the client wasn't owed.
func (ml *MemoryLimiter) evictIdle() {
	idle := 10 * time.Minute
	if refill := time.Duration(ml.burst / ml.rate * float64(time.Second)); refill > idle {
		idle = refill
	}
	ml.mu.Lock()
	defer ml.mu.Unlock()
	now := ml.now()
	for key, bucket := range ml.buckets {
		if now.Sub(bucket.lastRefill) > idle {
			delete(ml.buckets, key)
		}
	}
}

// tokenBucketScript atomically refills and takes one token. It uses the Redis
// server clock so every gateway replica shares one view of time.
// Returns {allowed (0|1), remaining tokens (floored), retry after in microseconds}.
var tokenBucketScript = redis.NewScript(`
local key = KEYS[1]
local rate = tonumber(ARGV[1])
local burst = tonumber(ARGV[2])

local t = redis.call('TIME')
local now = tonumber(t[1]) * 1000000 + tonumber(t[2])

local state = redis.call('HMGET', key, 'tokens', 'ts')
local tokens = tonumber(state[1])
local ts = tonumber(state[2])
if tokens == nil or ts == nil then
  tokens = burst
  ts = now
end

local elapsed = math.max(0, now - ts) / 1000000
tokens = math.min(burst, tokens + elapsed * rate)

local allowed = 0
local retry_us = 0
if tokens >= 1 then
  tokens = tokens - 1
  allowed = 1
else
  retry_us = math.ceil((1 - tokens) / rate * 1000000)
end

redis.call('HSET', key, 'tokens', string.format('%.6f', tokens), 'ts', string.format('%.0f', now))
redis.call('PEXPIRE', key, math.ceil(burst / rate * 1000) + 1000)

return {allowed, math.floor(tokens), retry_us}
`)

// RedisLimiter is a token bucket limiter whose state lives in Redis, so the
// limit is shared across all gateway replicas.
type RedisLimiter struct {
	client  redis.UniversalClient
	rate    float64
	burst   int
	prefix  string
	timeout time.Duration
}

// NewRedisLimiter creates a Redis-backed limiter refilling rate tokens per
// second up to burst tokens. Keys are stored as prefix+clientKey.
func NewRedisLimiter(client redis.UniversalClient, rate float64, burst int, prefix string, timeout time.Duration) *RedisLimiter {
	return &RedisLimiter{client: client, rate: rate, burst: burst, prefix: prefix, timeout: timeout}
}

// Take implements Limiter.
func (rl *RedisLimiter) Take(ctx context.Context, key string) (RateLimitResult, error) {
	if rl.timeout > 0 {
		var cancel context.CancelFunc
		ctx, cancel = context.WithTimeout(ctx, rl.timeout)
		defer cancel()
	}

	vals, err := tokenBucketScript.Run(ctx, rl.client,
		[]string{rl.prefix + key},
		strconv.FormatFloat(rl.rate, 'f', -1, 64),
		rl.burst,
	).Int64Slice()
	if err != nil {
		return RateLimitResult{}, err
	}

	return RateLimitResult{
		Allowed:    vals[0] == 1,
		Limit:      rl.burst,
		Remaining:  int(vals[1]),
		RetryAfter: time.Duration(vals[2]) * time.Microsecond,
	}, nil
}

// KeyFunc derives the rate-limit client key for a request.
type KeyFunc func(r *http.Request) string

// ClientKey identifies a client by the user in a valid bearer token, falling
// back to the client IP. Invalid tokens are keyed by IP so they cannot be
// used to spread requests across buckets. Requests to ipOnlyPaths (e.g.
// login and register) are always keyed by IP, so tokens minted from fresh
// sign-ups cannot multiply the allowance on those endpoints.
func ClientKey(jwtSecret string, ipOnlyPaths ...string) KeyFunc {
	ipOnly := make(map[string]bool, len(ipOnlyPaths))
	for _, p := range ipOnlyPaths {
		ipOnly[p] = true
	}
	return func(r *http.Request) string {
		if ipOnly[r.URL.Path] {
			return "ip:" + extractIP(r)
		}
		if tokenStr := extractBearerToken(r); tokenStr != "" && jwtSecret != "" {
			if claims, err := validateToken(tokenStr, jwtSecret); err == nil {
				userID := claims.Subject
				if userID == "" {
					userID = claims.UserID
				}
				if userID != "" {
					return "user:" + userID
				}
			}
		}
		return "ip:" + extractIP(r)
	}
}

// RateLimitConfig configures the rate limiting middleware.
type RateLimitConfig struct {
	// Limiter is the primary limiter (typically Redis-backed).
	Limiter Limiter
	// Backend labels metrics for the primary limiter (e.g. "redis", "memory").
	Backend string
	// Fallback is used when Limiter returns an error. If nil, requests are
	// allowed through when the primary limiter fails.
	Fallback Limiter
	// KeyFunc derives the client key. Defaults to the client IP.
	KeyFunc KeyFunc
	// ExemptPrefixes are path prefixes that are never rate limited.
	ExemptPrefixes []string
	Logger         zerolog.Logger
}

// RateLimit returns middleware enforcing a per-client token bucket. Requests
// over the limit receive 429 with a Retry-After header (whole seconds).
func RateLimit(cfg RateLimitConfig) func(http.Handler) http.Handler {
	keyFunc := cfg.KeyFunc
	if keyFunc == nil {
		keyFunc = func(r *http.Request) string { return "ip:" + extractIP(r) }
	}
	backend := cfg.Backend
	if backend == "" {
		backend = "primary"
	}
	var lastErrLog atomic.Int64

	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			for _, p := range cfg.ExemptPrefixes {
				if strings.HasPrefix(r.URL.Path, p) {
					next.ServeHTTP(w, r)
					return
				}
			}

			key := keyFunc(r)
			usedBackend := backend
			res, err := cfg.Limiter.Take(r.Context(), key)
			if err != nil {
				if now := time.Now().UnixNano(); now-lastErrLog.Load() > int64(30*time.Second) {
					lastErrLog.Store(now)
					cfg.Logger.Warn().Err(err).Str("backend", backend).Msg("rate limiter unavailable, using fallback")
				}
				if cfg.Fallback == nil {
					rateLimitDecisions.WithLabelValues(backend, "error").Inc()
					next.ServeHTTP(w, r)
					return
				}
				usedBackend = "fallback"
				if res, err = cfg.Fallback.Take(r.Context(), key); err != nil {
					rateLimitDecisions.WithLabelValues(usedBackend, "error").Inc()
					next.ServeHTTP(w, r)
					return
				}
			}

			w.Header().Set("X-RateLimit-Limit", strconv.Itoa(res.Limit))
			w.Header().Set("X-RateLimit-Remaining", strconv.Itoa(res.Remaining))

			if !res.Allowed {
				rateLimitDecisions.WithLabelValues(usedBackend, "limited").Inc()
				w.Header().Set("Content-Type", "application/json")
				w.Header().Set("Retry-After", strconv.Itoa(retryAfterSeconds(res.RetryAfter)))
				w.WriteHeader(http.StatusTooManyRequests)
				json.NewEncoder(w).Encode(map[string]string{
					"error": "rate limit exceeded",
				})
				return
			}
			rateLimitDecisions.WithLabelValues(usedBackend, "allowed").Inc()
			next.ServeHTTP(w, r)
		})
	}
}

func retryAfterSeconds(d time.Duration) int {
	secs := int(math.Ceil(d.Seconds()))
	if secs < 1 {
		return 1
	}
	return secs
}

func extractIP(r *http.Request) string {
	// chimw.RealIP has already set r.RemoteAddr to the client IP
	host, _, err := net.SplitHostPort(r.RemoteAddr)
	if err != nil {
		return r.RemoteAddr
	}
	return host
}
