package middleware

import (
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
)

func TestRateLimiter_RefillIsCappedAtBurst(t *testing.T) {
	rl := NewRateLimiter(3)
	now := time.Now()
	rl.now = func() time.Time { return now }

	assert.True(t, rl.Allow("10.1.1.1"))

	rl.now = func() time.Time { return now.Add(time.Hour) }
	for i := 0; i < 3; i++ {
		assert.True(t, rl.Allow("10.1.1.1"), "request %d", i+1)
	}
	assert.False(t, rl.Allow("10.1.1.1"), "an idle hour must not bank more than rps tokens")
}
