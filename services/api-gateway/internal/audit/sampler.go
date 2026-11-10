package audit

import (
	"sync"
	"time"

	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promauto"
)

var eventsSuppressed = promauto.NewCounterVec(prometheus.CounterOpts{
	Name: "audit_events_suppressed_total",
	Help: "Audit events not emitted because the per-IP audit budget was exhausted.",
}, []string{"action"})

type ipWindow struct {
	start time.Time
	count int
}

// PerIPLimited caps how many events a single client IP can generate per
// window, so a flood of unauthenticated probes cannot flood audit-service.
type PerIPLimited struct {
	next    Emitter
	limit   int
	window  time.Duration
	maxKeys int
	now     func() time.Time

	mu      sync.Mutex
	windows map[string]*ipWindow
}

// NewPerIPLimited wraps next, allowing at most limit events per IP per window.
// A limit <= 0 disables limiting.
func NewPerIPLimited(next Emitter, limit int, window time.Duration) *PerIPLimited {
	return &PerIPLimited{
		next:    next,
		limit:   limit,
		window:  window,
		maxKeys: 10000,
		now:     time.Now,
		windows: make(map[string]*ipWindow),
	}
}

func (p *PerIPLimited) Emit(e Event) {
	if p.limit > 0 && !p.allow(e.IPAddress) {
		eventsSuppressed.WithLabelValues(e.Action).Inc()
		return
	}
	p.next.Emit(e)
}

func (p *PerIPLimited) allow(ip string) bool {
	p.mu.Lock()
	defer p.mu.Unlock()

	now := p.now()
	w, ok := p.windows[ip]
	if !ok || now.Sub(w.start) >= p.window {
		if !ok && len(p.windows) >= p.maxKeys {
			p.evictExpired(now)
			if len(p.windows) >= p.maxKeys {
				return false
			}
		}
		p.windows[ip] = &ipWindow{start: now, count: 1}
		return true
	}
	if w.count >= p.limit {
		return false
	}
	w.count++
	return true
}

func (p *PerIPLimited) evictExpired(now time.Time) {
	for ip, w := range p.windows {
		if now.Sub(w.start) >= p.window {
			delete(p.windows, ip)
		}
	}
}
