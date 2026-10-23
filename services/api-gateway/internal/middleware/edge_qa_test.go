package middleware

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/prometheus/client_golang/prometheus/promhttp"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

var okHandler = http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) { w.WriteHeader(http.StatusOK) })

// ── Rate limiting ────────────────────────────────────────────

func TestQARateLimit_BucketsArePerIP(t *testing.T) {
	rl := &RateLimiter{buckets: map[string]*TokenBucket{}, rps: 2, now: time.Now}
	assert.True(t, rl.Allow("10.0.0.1"))
	assert.True(t, rl.Allow("10.0.0.1"))
	assert.False(t, rl.Allow("10.0.0.1"))
	assert.True(t, rl.Allow("10.0.0.2"), "another client keeps its own budget")
}

func TestQARateLimit_RefillIsCappedAtBurst(t *testing.T) {
	now := time.Unix(1_700_000_000, 0)
	rl := &RateLimiter{buckets: map[string]*TokenBucket{}, rps: 3, now: func() time.Time { return now }}
	for i := 0; i < 3; i++ {
		require.True(t, rl.Allow("ip"))
	}
	require.False(t, rl.Allow("ip"))
	now = now.Add(time.Hour)
	allowed := 0
	for i := 0; i < 10; i++ {
		if rl.Allow("ip") {
			allowed++
		}
	}
	assert.Equal(t, 3, allowed, "an idle hour must not bank more than one second of burst")
}

func TestQARateLimit_429ResponseShape(t *testing.T) {
	rl := &RateLimiter{buckets: map[string]*TokenBucket{}, rps: 1, now: time.Now}
	h := rl.Handler(okHandler)
	do := func() *httptest.ResponseRecorder {
		req := httptest.NewRequest(http.MethodGet, "/api/v1/files", nil)
		req.RemoteAddr = "192.0.2.10:5555"
		rec := httptest.NewRecorder()
		h.ServeHTTP(rec, req)
		return rec
	}
	require.Equal(t, http.StatusOK, do().Code)
	rec := do()
	assert.Equal(t, http.StatusTooManyRequests, rec.Code)
	assert.Equal(t, "1", rec.Header().Get("Retry-After"))
	assert.Contains(t, rec.Header().Get("Content-Type"), "application/json")
	var body map[string]string
	require.NoError(t, json.Unmarshal(rec.Body.Bytes(), &body))
	assert.Equal(t, "rate limit exceeded", body["error"])
}

func TestQARateLimit_ZeroRPSBlocksEverything(t *testing.T) {
	rl := &RateLimiter{buckets: map[string]*TokenBucket{}, rps: 0, now: time.Now}
	assert.False(t, rl.Allow("ip"), "RATE_LIMIT_RPS=0 denies all traffic rather than disabling the limiter")
}

func TestQARateLimit_IPv6RemoteAddr(t *testing.T) {
	req := httptest.NewRequest(http.MethodGet, "/", nil)
	req.RemoteAddr = "[2001:db8::1]:443"
	assert.Equal(t, "2001:db8::1", extractIP(req))
}

// ── CORS ─────────────────────────────────────────────────────

func TestQACORS_DefaultConfigAllowsAppOriginsOnly(t *testing.T) {
	h := CORS(DefaultCORSConfig())(okHandler)
	for _, origin := range []string{"http://localhost:3000", "http://localhost:4200", "https://localhost", "capacitor://localhost"} {
		req := httptest.NewRequest(http.MethodGet, "/api/v1/files", nil)
		req.Header.Set("Origin", origin)
		rec := httptest.NewRecorder()
		h.ServeHTTP(rec, req)
		assert.Equal(t, origin, rec.Header().Get("Access-Control-Allow-Origin"))
		assert.Equal(t, "true", rec.Header().Get("Access-Control-Allow-Credentials"))
		assert.Equal(t, "Link, X-Request-ID", rec.Header().Get("Access-Control-Expose-Headers"))
	}
	for _, origin := range []string{"https://evil.example", "http://localhost:3000.evil.example", "null", "http://localhost"} {
		req := httptest.NewRequest(http.MethodGet, "/api/v1/files", nil)
		req.Header.Set("Origin", origin)
		rec := httptest.NewRecorder()
		h.ServeHTTP(rec, req)
		assert.Empty(t, rec.Header().Get("Access-Control-Allow-Origin"), origin)
		assert.Empty(t, rec.Header().Get("Access-Control-Allow-Credentials"), origin)
	}
}

func TestQACORS_PreflightAdvertisesAuthorizationHeader(t *testing.T) {
	h := CORS(DefaultCORSConfig())(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		t.Fatal("allowed preflight must be answered by the CORS middleware")
	}))
	req := httptest.NewRequest(http.MethodOptions, "/api/v1/documents/1", nil)
	req.Header.Set("Origin", "http://localhost:3000")
	req.Header.Set("Access-Control-Request-Method", "PATCH")
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	assert.Equal(t, http.StatusNoContent, rec.Code)
	assert.Contains(t, rec.Header().Get("Access-Control-Allow-Methods"), "PATCH")
	assert.Contains(t, rec.Header().Get("Access-Control-Allow-Headers"), "Authorization")
	assert.Equal(t, "300", rec.Header().Get("Access-Control-Max-Age"))
}

func TestQACORS_OptionsWithoutOriginReachesHandler(t *testing.T) {
	called := false
	h := CORS(DefaultCORSConfig())(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) { called = true }))
	h.ServeHTTP(httptest.NewRecorder(), httptest.NewRequest(http.MethodOptions, "/api/v1/files", nil))
	assert.True(t, called)
}

// ── Metrics path labels ──────────────────────────────────────

func TestQAMetrics_NormalizePathKnownPrefixes(t *testing.T) {
	cases := map[string]string{
		"/api/v1/auth/login":            "/api/v1/auth",
		"/api/v1/files/123/download":    "/api/v1/files",
		"/api/v1/documents/abc":         "/api/v1/documents",
		"/api/v1/collab/rooms":          "/api/v1/collab",
		"/api/v1/notifications/unread":  "/api/v1/notifications",
		"/api/v1/search?q=x":            "/api/v1/search",
		"/api/v1/analytics/events":      "/api/v1/analytics",
		"/api/v1/admin/users/42":        "/api/v1/admin",
		"/api/v1/audit/events":          "/api/v1/audit",
		"/health":                       "other",
		"/totally/unknown/" + "x" + "y": "other",
	}
	for in, want := range cases {
		assert.Equal(t, want, normalizePath(in), in)
	}
}

func TestQAMetrics_LabelsAreBoundedForIDs(t *testing.T) {
	seen := map[string]bool{}
	for i := 0; i < 50; i++ {
		seen[normalizePath("/api/v1/files/"+strings.Repeat("a", i))] = true
	}
	assert.Len(t, seen, 1, "per-id paths must collapse into one label")
}

// QA-GW-04: routed prefixes missing from normalizePath are all lumped into
// "other", so their traffic is indistinguishable from 404 noise.
func TestQAMetrics_EveryRoutedPrefixHasItsOwnLabel(t *testing.T) {
	t.Skip("xfail QA-GW-04: /api/v1/folders, templates, preferences, reports, settings and /socket.io are labelled \"other\" (internal/middleware/metrics.go normalizePath)")
	for _, p := range []string{"/api/v1/folders", "/api/v1/templates", "/api/v1/preferences", "/api/v1/reports", "/api/v1/settings", "/socket.io"} {
		assert.Equal(t, p, normalizePath(p+"/x"), p)
	}
}

// QA-GW-04 (boundary): prefix match does not stop at a path segment.
func TestQAMetrics_PrefixMatchRespectsSegmentBoundary(t *testing.T) {
	t.Skip("xfail QA-GW-04: /api/v1/filesystem is labelled /api/v1/files (internal/middleware/metrics.go normalizePath uses raw string prefix)")
	assert.Equal(t, "other", normalizePath("/api/v1/filesystem"))
}

func TestQAMetrics_MiddlewareRecordsStatusAndLabel(t *testing.T) {
	h := Metrics(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) { w.WriteHeader(http.StatusTeapot) }))
	h.ServeHTTP(httptest.NewRecorder(), httptest.NewRequest(http.MethodDelete, "/api/v1/audit/qa-metrics", nil))

	rec := httptest.NewRecorder()
	promhttp.Handler().ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/metrics", nil))
	body := rec.Body.String()
	assert.Contains(t, body, `api_gateway_http_requests_total{method="DELETE",path="/api/v1/audit",status="418"}`)
	assert.Contains(t, body, `api_gateway_http_request_duration_seconds_count{method="DELETE",path="/api/v1/audit"}`)
	assert.NotContains(t, body, "qa-metrics", "raw paths must never become label values")
}

// ── Request ID ───────────────────────────────────────────────

func TestQARequestID_AvailableToDownstreamHandlers(t *testing.T) {
	var got string
	h := RequestID(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { got = GetRequestID(r.Context()) }))
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/", nil))
	assert.Len(t, got, 36)
	assert.Equal(t, got, rec.Header().Get("X-Request-ID"))
}
