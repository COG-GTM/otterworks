// Package audit emits structured audit events to audit-service without
// blocking the request path: events are queued on a bounded channel and
// delivered by background workers with a short timeout and bounded retry.
package audit

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"sync"
	"time"

	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promauto"
	"github.com/rs/zerolog"
)

const (
	EventsPath = "/api/v1/audit/events"

	OutcomeSuccess = "success"
	OutcomeFailure = "failure"
	OutcomeDenied  = "denied"

	ActorUser      = "user"
	ActorAdmin     = "admin"
	ActorService   = "service"
	ActorAnonymous = "anonymous"
)

// Event is the audit-service v2 wire contract (camelCase JSON).
type Event struct {
	UserID       string            `json:"userId"`
	ActorEmail   string            `json:"actorEmail,omitempty"`
	ActorType    string            `json:"actorType,omitempty"`
	TenantID     string            `json:"tenantId,omitempty"`
	Action       string            `json:"action"`
	ResourceType string            `json:"resourceType"`
	ResourceID   string            `json:"resourceId"`
	Outcome      string            `json:"outcome"`
	Details      map[string]string `json:"details,omitempty"`
	IPAddress    string            `json:"ipAddress,omitempty"`
	UserAgent    string            `json:"userAgent,omitempty"`
	RequestID    string            `json:"requestId,omitempty"`
	ServiceName  string            `json:"serviceName"`
	Timestamp    string            `json:"timestamp"`
}

// Emitter accepts audit events. Implementations must never block the caller.
type Emitter interface {
	Emit(Event)
}

// Nop discards every event.
type Nop struct{}

func (Nop) Emit(Event) {}

var (
	eventsEmitted = promauto.NewCounterVec(prometheus.CounterOpts{
		Name: "audit_events_emitted_total",
		Help: "Audit events accepted by audit-service.",
	}, []string{"action"})

	emitFailures = promauto.NewCounterVec(prometheus.CounterOpts{
		Name: "audit_emit_failures_total",
		Help: "Audit events that could not be delivered to audit-service.",
	}, []string{"reason"})
)

// Config configures a Client.
type Config struct {
	URL          string // audit-service base URL, e.g. http://audit-service:8090
	Token        string // sent as X-Audit-Token
	ServiceName  string
	QueueSize    int
	Workers      int
	Timeout      time.Duration // per attempt
	MaxRetries   int           // retries after the first attempt
	RetryBackoff time.Duration
	HTTPClient   *http.Client
	Logger       zerolog.Logger
}

// Client is an asynchronous audit-service client.
type Client struct {
	cfg      Config
	endpoint string
	http     *http.Client
	queue    chan Event
	wg       sync.WaitGroup
	mu       sync.RWMutex
	closed   bool
}

// New starts a Client and its workers.
func New(cfg Config) *Client {
	if cfg.QueueSize <= 0 {
		cfg.QueueSize = 1024
	}
	if cfg.Workers <= 0 {
		cfg.Workers = 2
	}
	if cfg.Timeout <= 0 {
		cfg.Timeout = 2 * time.Second
	}
	if cfg.MaxRetries < 0 {
		cfg.MaxRetries = 0
	}
	if cfg.RetryBackoff <= 0 {
		cfg.RetryBackoff = 100 * time.Millisecond
	}
	if cfg.ServiceName == "" {
		cfg.ServiceName = "api-gateway"
	}
	httpClient := cfg.HTTPClient
	if httpClient == nil {
		httpClient = &http.Client{}
	}

	c := &Client{
		cfg:      cfg,
		endpoint: strings.TrimRight(cfg.URL, "/") + EventsPath,
		http:     httpClient,
		queue:    make(chan Event, cfg.QueueSize),
	}
	for i := 0; i < cfg.Workers; i++ {
		c.wg.Add(1)
		go c.worker()
	}
	return c
}

// Emit enqueues an event, dropping it (and counting the drop) if the queue is full.
func (c *Client) Emit(e Event) {
	if e.ServiceName == "" {
		e.ServiceName = c.cfg.ServiceName
	}
	if e.Timestamp == "" {
		e.Timestamp = time.Now().UTC().Format(time.RFC3339)
	}

	c.mu.RLock()
	defer c.mu.RUnlock()
	if c.closed {
		emitFailures.WithLabelValues("closed").Inc()
		return
	}
	select {
	case c.queue <- e:
	default:
		emitFailures.WithLabelValues("queue_full").Inc()
		c.cfg.Logger.Warn().Str("action", e.Action).Msg("audit queue full, event dropped")
	}
}

// Close stops accepting events and waits for queued events to drain, or for ctx to end.
func (c *Client) Close(ctx context.Context) error {
	c.mu.Lock()
	if !c.closed {
		c.closed = true
		close(c.queue)
	}
	c.mu.Unlock()

	done := make(chan struct{})
	go func() {
		c.wg.Wait()
		close(done)
	}()
	select {
	case <-done:
		return nil
	case <-ctx.Done():
		return ctx.Err()
	}
}

func (c *Client) worker() {
	defer c.wg.Done()
	for e := range c.queue {
		if reason, err := c.deliver(e); err != nil {
			emitFailures.WithLabelValues(reason).Inc()
			c.cfg.Logger.Warn().
				Err(err).
				Str("action", e.Action).
				Str("request_id", e.RequestID).
				Msg("audit event delivery failed")
			continue
		}
		eventsEmitted.WithLabelValues(e.Action).Inc()
	}
}

func (c *Client) deliver(e Event) (string, error) {
	body, err := json.Marshal(e)
	if err != nil {
		return "marshal", err
	}

	reason, lastErr := "", error(nil)
	for attempt := 0; attempt <= c.cfg.MaxRetries; attempt++ {
		if attempt > 0 {
			time.Sleep(c.cfg.RetryBackoff * time.Duration(attempt))
		}
		var retryable bool
		reason, retryable, lastErr = c.post(body, e.RequestID)
		if lastErr == nil {
			return "", nil
		}
		if !retryable {
			break
		}
	}
	return reason, lastErr
}

func (c *Client) post(body []byte, requestID string) (reason string, retryable bool, err error) {
	ctx, cancel := context.WithTimeout(context.Background(), c.cfg.Timeout)
	defer cancel()

	req, err := http.NewRequestWithContext(ctx, http.MethodPost, c.endpoint, bytes.NewReader(body))
	if err != nil {
		return "request", false, err
	}
	req.Header.Set("Content-Type", "application/json")
	if c.cfg.Token != "" {
		req.Header.Set("X-Audit-Token", c.cfg.Token)
	}
	if requestID != "" {
		req.Header.Set("X-Request-ID", requestID)
	}

	resp, err := c.http.Do(req)
	if err != nil {
		if ctx.Err() != nil {
			return "timeout", true, err
		}
		return "network", true, err
	}
	defer resp.Body.Close()
	_, _ = io.Copy(io.Discard, io.LimitReader(resp.Body, 4096))

	switch {
	case resp.StatusCode >= 200 && resp.StatusCode < 300:
		return "", false, nil
	case resp.StatusCode >= 500, resp.StatusCode == http.StatusTooManyRequests, resp.StatusCode == http.StatusRequestTimeout:
		return "http_5xx", true, fmt.Errorf("audit-service returned %d", resp.StatusCode)
	default:
		return "http_4xx", false, fmt.Errorf("audit-service returned %d", resp.StatusCode)
	}
}
