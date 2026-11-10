package audit

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/prometheus/client_golang/prometheus/testutil"
	"github.com/rs/zerolog"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func sampleEvent() Event {
	return Event{
		UserID:       "anonymous",
		ActorType:    ActorAnonymous,
		Action:       "auth.token.rejected",
		ResourceType: "api_route",
		ResourceID:   "/api/v1/files",
		Outcome:      OutcomeDenied,
		Details:      map[string]string{"reason": "missing_token"},
		IPAddress:    "203.0.113.7",
		UserAgent:    "curl/8.0",
		RequestID:    "req-abc",
	}
}

func closeClient(t *testing.T, c *Client) {
	t.Helper()
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	require.NoError(t, c.Close(ctx))
}

func TestClient_PostsContractPayloadAndHeaders(t *testing.T) {
	var (
		mu      sync.Mutex
		headers http.Header
		path    string
		body    map[string]any
	)
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		defer mu.Unlock()
		headers = r.Header.Clone()
		path = r.URL.Path
		raw, _ := io.ReadAll(r.Body)
		_ = json.Unmarshal(raw, &body)
		w.WriteHeader(http.StatusCreated)
	}))
	defer srv.Close()

	c := New(Config{URL: srv.URL + "/", Token: "ingest-token", Logger: zerolog.Nop()})
	c.Emit(sampleEvent())
	closeClient(t, c)

	mu.Lock()
	defer mu.Unlock()
	assert.Equal(t, EventsPath, path)
	assert.Equal(t, "application/json", headers.Get("Content-Type"))
	assert.Equal(t, "ingest-token", headers.Get("X-Audit-Token"))
	assert.Equal(t, "req-abc", headers.Get("X-Request-ID"))

	assert.Equal(t, "anonymous", body["userId"])
	assert.Equal(t, "anonymous", body["actorType"])
	assert.Equal(t, "auth.token.rejected", body["action"])
	assert.Equal(t, "api_route", body["resourceType"])
	assert.Equal(t, "/api/v1/files", body["resourceId"])
	assert.Equal(t, "denied", body["outcome"])
	assert.Equal(t, "203.0.113.7", body["ipAddress"])
	assert.Equal(t, "curl/8.0", body["userAgent"])
	assert.Equal(t, "req-abc", body["requestId"])
	assert.Equal(t, "api-gateway", body["serviceName"])
	assert.Equal(t, map[string]any{"reason": "missing_token"}, body["details"])

	ts, ok := body["timestamp"].(string)
	require.True(t, ok)
	parsed, err := time.Parse(time.RFC3339, ts)
	require.NoError(t, err)
	assert.Equal(t, time.UTC, parsed.Location())
}

func TestClient_RetriesServerErrorsThenCountsFailure(t *testing.T) {
	var calls int32
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		atomic.AddInt32(&calls, 1)
		w.WriteHeader(http.StatusInternalServerError)
	}))
	defer srv.Close()

	before := testutil.ToFloat64(emitFailures.WithLabelValues("http_5xx"))
	c := New(Config{URL: srv.URL, MaxRetries: 2, RetryBackoff: time.Millisecond, Workers: 1, Logger: zerolog.Nop()})
	c.Emit(sampleEvent())
	closeClient(t, c)

	assert.Equal(t, int32(3), atomic.LoadInt32(&calls), "one attempt plus two bounded retries")
	assert.Equal(t, before+1, testutil.ToFloat64(emitFailures.WithLabelValues("http_5xx")))
}

func TestClient_DoesNotRetryClientErrors(t *testing.T) {
	var calls int32
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		atomic.AddInt32(&calls, 1)
		w.WriteHeader(http.StatusUnauthorized)
	}))
	defer srv.Close()

	before := testutil.ToFloat64(emitFailures.WithLabelValues("http_4xx"))
	c := New(Config{URL: srv.URL, MaxRetries: 2, RetryBackoff: time.Millisecond, Logger: zerolog.Nop()})
	c.Emit(sampleEvent())
	closeClient(t, c)

	assert.Equal(t, int32(1), atomic.LoadInt32(&calls))
	assert.Equal(t, before+1, testutil.ToFloat64(emitFailures.WithLabelValues("http_4xx")))
}

func TestClient_TimesOutSlowAuditService(t *testing.T) {
	release := make(chan struct{})
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		select {
		case <-release:
		case <-r.Context().Done():
		}
	}))
	defer srv.Close()
	defer close(release)

	before := testutil.ToFloat64(emitFailures.WithLabelValues("timeout"))
	c := New(Config{URL: srv.URL, Timeout: 50 * time.Millisecond, MaxRetries: 0, Logger: zerolog.Nop()})

	start := time.Now()
	c.Emit(sampleEvent())
	assert.Less(t, time.Since(start), 10*time.Millisecond, "Emit must not wait on audit-service")

	closeClient(t, c)
	assert.Equal(t, before+1, testutil.ToFloat64(emitFailures.WithLabelValues("timeout")))
}

func TestClient_DropsWhenQueueFull(t *testing.T) {
	release := make(chan struct{})
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		<-release
		w.WriteHeader(http.StatusCreated)
	}))
	defer srv.Close()

	before := testutil.ToFloat64(emitFailures.WithLabelValues("queue_full"))
	c := New(Config{URL: srv.URL, QueueSize: 1, Workers: 1, Logger: zerolog.Nop()})

	// The worker holds one in-flight event, the queue holds one more; the rest are dropped.
	for i := 0; i < 10; i++ {
		c.Emit(sampleEvent())
	}
	close(release)
	closeClient(t, c)

	assert.GreaterOrEqual(t, testutil.ToFloat64(emitFailures.WithLabelValues("queue_full"))-before, float64(8))
}

func TestClient_EmitAfterCloseDoesNotPanic(t *testing.T) {
	c := New(Config{URL: "http://127.0.0.1:1", Logger: zerolog.Nop()})
	closeClient(t, c)
	assert.NotPanics(t, func() { c.Emit(sampleEvent()) })
}
