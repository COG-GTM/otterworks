package config

import (
	"testing"

	"github.com/stretchr/testify/assert"
)

func TestTrustedProxyCIDRs_DefaultsToPrivateRanges(t *testing.T) {
	t.Setenv("JWT_SECRET", "x")
	assert.Equal(t, DefaultTrustedProxyCIDRs, Load().TrustedProxyCIDRs)
}

func TestTrustedProxyCIDRs_EmptyTrustsNoProxy(t *testing.T) {
	t.Setenv("TRUSTED_PROXY_CIDRS", "")
	assert.Empty(t, Load().TrustedProxyCIDRs)
}

func TestTrustedProxyCIDRs_Explicit(t *testing.T) {
	t.Setenv("TRUSTED_PROXY_CIDRS", "10.42.0.0/16,192.0.2.10")
	assert.Equal(t, []string{"10.42.0.0/16", "192.0.2.10"}, Load().TrustedProxyCIDRs)
}

func TestRateLimitMaxBuckets(t *testing.T) {
	assert.Equal(t, 50000, Load().RateLimitMaxBuckets)
	t.Setenv("RATE_LIMIT_MAX_BUCKETS", "123")
	assert.Equal(t, 123, Load().RateLimitMaxBuckets)
}
