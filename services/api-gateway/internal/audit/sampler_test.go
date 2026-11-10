package audit

import (
	"sync"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
)

type collector struct {
	mu     sync.Mutex
	events []Event
}

func (c *collector) Emit(e Event) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.events = append(c.events, e)
}

func (c *collector) count() int {
	c.mu.Lock()
	defer c.mu.Unlock()
	return len(c.events)
}

func TestPerIPLimited_CapsEventsPerIPPerWindow(t *testing.T) {
	next := &collector{}
	now := time.Now()
	p := NewPerIPLimited(next, 3, time.Minute)
	p.now = func() time.Time { return now }

	for i := 0; i < 10; i++ {
		p.Emit(Event{Action: "auth.token.rejected", IPAddress: "203.0.113.7"})
	}
	assert.Equal(t, 3, next.count(), "a probe spike from one IP is capped")

	p.Emit(Event{Action: "auth.token.rejected", IPAddress: "203.0.113.8"})
	assert.Equal(t, 4, next.count(), "other IPs keep their own budget")

	now = now.Add(time.Minute)
	p.Emit(Event{Action: "auth.token.rejected", IPAddress: "203.0.113.7"})
	assert.Equal(t, 5, next.count(), "budget resets after the window")
}

func TestPerIPLimited_BoundsTrackedIPs(t *testing.T) {
	next := &collector{}
	p := NewPerIPLimited(next, 1, time.Minute)
	p.maxKeys = 2

	p.Emit(Event{IPAddress: "198.51.100.1"})
	p.Emit(Event{IPAddress: "198.51.100.2"})
	p.Emit(Event{IPAddress: "198.51.100.3"})
	assert.Equal(t, 2, next.count())
	assert.Len(t, p.windows, 2)
}

func TestPerIPLimited_ZeroLimitDisables(t *testing.T) {
	next := &collector{}
	p := NewPerIPLimited(next, 0, time.Minute)
	for i := 0; i < 5; i++ {
		p.Emit(Event{IPAddress: "203.0.113.7"})
	}
	assert.Equal(t, 5, next.count())
}
