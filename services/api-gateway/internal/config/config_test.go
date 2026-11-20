package config

import (
	"math"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
)

func TestLoad_RateLimitDefaults(t *testing.T) {
	cfg := Load()
	assert.True(t, cfg.RateLimitEnabled)
	assert.Equal(t, "redis", cfg.RateLimitBackend)
	assert.Equal(t, 100.0, cfg.RateLimitRPS)
	assert.Equal(t, 100, cfg.RateLimitBurst)
	assert.Equal(t, "otterworks:api-gateway:ratelimit:", cfg.RateLimitKeyPrefix)
	assert.Equal(t, 100*time.Millisecond, cfg.RateLimitRedisTimeout)
	assert.Equal(t, "redis", cfg.RedisHost)
	assert.Equal(t, "6379", cfg.RedisPort)
}

func TestLoad_RateLimitFromEnv(t *testing.T) {
	t.Setenv("RATE_LIMIT_ENABLED", "false")
	t.Setenv("RATE_LIMIT_BACKEND", "Memory")
	t.Setenv("RATE_LIMIT_RPS", "2.5")
	t.Setenv("RATE_LIMIT_BURST", "10")
	t.Setenv("RATE_LIMIT_KEY_PREFIX", "rl:")
	t.Setenv("RATE_LIMIT_REDIS_TIMEOUT_MS", "25")
	t.Setenv("RATE_LIMIT_REDIS_URL", "redis://:pw@cache:6380/2")
	t.Setenv("REDIS_HOST", "cache")
	t.Setenv("REDIS_DB", "3")

	cfg := Load()
	assert.False(t, cfg.RateLimitEnabled)
	assert.Equal(t, "memory", cfg.RateLimitBackend)
	assert.Equal(t, 2.5, cfg.RateLimitRPS)
	assert.Equal(t, 10, cfg.RateLimitBurst)
	assert.Equal(t, "rl:", cfg.RateLimitKeyPrefix)
	assert.Equal(t, 25*time.Millisecond, cfg.RateLimitRedisTimeout)
	assert.Equal(t, "redis://:pw@cache:6380/2", cfg.RedisURL)
	assert.Equal(t, "cache", cfg.RedisHost)
	assert.Equal(t, 3, cfg.RedisDB)
}

func TestLoad_BurstDefaultsToRPS(t *testing.T) {
	t.Setenv("RATE_LIMIT_RPS", "0.5")
	assert.Equal(t, 1, Load().RateLimitBurst)

	t.Setenv("RATE_LIMIT_RPS", "7.2")
	assert.Equal(t, 8, Load().RateLimitBurst)
}

func TestValidate_RateLimit(t *testing.T) {
	base := func() *Config {
		return &Config{JWTSecret: "s", RateLimitEnabled: true, RateLimitBackend: "redis", RateLimitRPS: 1, RateLimitBurst: 1}
	}
	assert.NoError(t, base().Validate())

	c := base()
	c.RateLimitRPS = 0
	assert.ErrorContains(t, c.Validate(), "RATE_LIMIT_RPS")

	for _, rps := range []float64{math.NaN(), math.Inf(1)} {
		c = base()
		c.RateLimitRPS = rps
		assert.ErrorContains(t, c.Validate(), "RATE_LIMIT_RPS", rps)
	}

	c = base()
	c.RateLimitBurst = 0
	assert.ErrorContains(t, c.Validate(), "RATE_LIMIT_BURST")

	c = base()
	c.RateLimitBackend = "memcached"
	assert.ErrorContains(t, c.Validate(), "RATE_LIMIT_BACKEND")

	c = base()
	c.RateLimitEnabled = false
	c.RateLimitRPS = 0
	assert.NoError(t, c.Validate())
}

func TestLoad_RedisPortServiceLink(t *testing.T) {
	for val, expected := range map[string]string{
		"6380":                     "6380",
		"tcp://172.20.229.93:6379": "6379",
		"garbage":                  "6379",
	} {
		t.Setenv("REDIS_PORT", val)
		assert.Equal(t, expected, Load().RedisPort, val)
	}
}
