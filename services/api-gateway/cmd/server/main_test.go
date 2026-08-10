package main

import (
	"context"
	"encoding/json"
	"io"
	"net"
	"net/http"
	"os"
	"os/signal"
	"strconv"
	"syscall"
	"testing"
	"time"

	"github.com/golang-jwt/jwt/v5"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"go.opentelemetry.io/otel"

	"github.com/Cognition-Partner-Workshops/otterworks/services/api-gateway/internal/middleware"
	"github.com/Cognition-Partner-Workshops/otterworks/services/api-gateway/internal/proxy"
)

func TestRoutePrefixes(t *testing.T) {
	tests := []struct {
		name   string
		routes []proxy.Route
		want   []string
	}{
		{name: "no routes yields an empty slice", routes: nil, want: []string{}},
		{
			name: "prefixes are extracted in order",
			routes: []proxy.Route{
				{Prefix: "/api/v1/auth", TargetURL: "http://auth:1"},
				{Prefix: "/api/v1/files", TargetURL: "http://file:2"},
			},
			want: []string{"/api/v1/auth", "/api/v1/files"},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := routePrefixes(tt.routes)

			assert.Equal(t, tt.want, got)
			assert.Len(t, got, len(tt.routes))
		})
	}
}

func TestInitTracer_InstallsProviderAndReturnsShutdown(t *testing.T) {
	shutdown := initTracer()

	require.NotNil(t, shutdown, "the OTLP HTTP exporter is lazy, so setup must succeed without a collector")
	assert.NotNil(t, otel.GetTracerProvider())
	assert.NotNil(t, otel.GetTextMapPropagator())

	// The composite propagator must carry both W3C trace context and baggage.
	fields := otel.GetTextMapPropagator().Fields()
	assert.Contains(t, fields, "traceparent")
	assert.Contains(t, fields, "baggage")

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	assert.NoError(t, shutdown(ctx))
}

// freePort reserves an ephemeral port and immediately releases it, so the
// gateway under test binds a port nothing else in CI is using. The kernel does
// not hand the same ephemeral port out again straight away, so the window in
// which another process could steal it is negligible.
func freePort(t *testing.T) string {
	t.Helper()
	l, err := net.Listen("tcp", "127.0.0.1:0")
	require.NoError(t, err)
	port := l.Addr().(*net.TCPAddr).Port
	require.NoError(t, l.Close())
	return strconv.Itoa(port)
}

func waitFor(t *testing.T, what string, cond func() bool) {
	t.Helper()
	deadline := time.Now().Add(30 * time.Second)
	for time.Now().Before(deadline) {
		if cond() {
			return
		}
		time.Sleep(20 * time.Millisecond)
	}
	t.Fatalf("timed out waiting for %s", what)
}

// backendPath reads the next path the stub backend saw, bounded so that a
// regression which stops the request from reaching the backend fails the test
// instead of hanging until the package timeout.
func backendPath(t *testing.T, paths <-chan string) string {
	t.Helper()
	select {
	case p := <-paths:
		return p
	case <-time.After(5 * time.Second):
		t.Fatal("the request never reached the stub backend")
		return ""
	}
}

func getJSON(t *testing.T, client *http.Client, req *http.Request) (*http.Response, map[string]any) {
	t.Helper()
	res, err := client.Do(req)
	require.NoError(t, err)
	defer res.Body.Close()

	body, err := io.ReadAll(res.Body)
	require.NoError(t, err)

	var payload map[string]any
	if len(body) > 0 {
		require.NoError(t, json.Unmarshal(body, &payload), "body: %q", string(body))
	}
	return res, payload
}

// TestMain_WiresTheGatewayAndShutsDownGracefully boots the real process entry
// point against a stub backend and exercises the assembled middleware stack
// end to end, then proves SIGTERM drains the listener.
func TestMain_WiresTheGatewayAndShutsDownGracefully(t *testing.T) {
	// Register a SIGTERM handler up front: without one, the signal we send
	// below would terminate the test binary if it landed before main's own
	// signal.Notify call.
	guard := make(chan os.Signal, 1)
	signal.Notify(guard, syscall.SIGTERM)
	defer signal.Stop(guard)

	backendPathsCh := make(chan string, 16)
	backend := &http.Server{}
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	require.NoError(t, err)
	backend.Handler = http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		backendPathsCh <- r.URL.Path
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"backend":"ok"}`))
	})
	go func() { _ = backend.Serve(ln) }()
	t.Cleanup(func() { _ = backend.Close() })
	backendURL := "http://" + ln.Addr().String()

	port := freePort(t)
	t.Setenv("PORT", port)
	t.Setenv("JWT_SECRET", "test-secret")
	t.Setenv("LOG_LEVEL", "error")
	t.Setenv("RATE_LIMIT_RPS", "1000")
	t.Setenv("SHUTDOWN_TIMEOUT_SECONDS", "10")
	t.Setenv("AUTH_SERVICE_URL", backendURL)
	t.Setenv("FILE_SERVICE_URL", backendURL)

	done := make(chan struct{})
	go func() {
		defer close(done)
		main()
	}()

	base := "http://127.0.0.1:" + port
	client := &http.Client{Timeout: 5 * time.Second}

	waitFor(t, "the gateway to accept connections", func() bool {
		res, err := client.Get(base + "/health")
		if err != nil {
			return false
		}
		_ = res.Body.Close()
		return res.StatusCode == http.StatusOK
	})

	t.Run("health is public and reports the service version", func(t *testing.T) {
		req, err := http.NewRequest(http.MethodGet, base+"/health", nil)
		require.NoError(t, err)

		res, payload := getJSON(t, client, req)

		assert.Equal(t, http.StatusOK, res.StatusCode)
		assert.Equal(t, "healthy", payload["status"])
		assert.NotEmpty(t, res.Header.Get("X-Request-ID"), "RequestID middleware is installed")
	})

	t.Run("prometheus metrics are exposed without a token", func(t *testing.T) {
		res, err := client.Get(base + "/metrics")
		require.NoError(t, err)
		defer res.Body.Close()
		body, err := io.ReadAll(res.Body)
		require.NoError(t, err)

		assert.Equal(t, http.StatusOK, res.StatusCode)
		assert.Contains(t, string(body), "api_gateway_http_requests_total")
	})

	t.Run("public auth routes are proxied without a token", func(t *testing.T) {
		req, err := http.NewRequest(http.MethodPost, base+"/api/v1/auth/login", nil)
		require.NoError(t, err)

		res, payload := getJSON(t, client, req)

		assert.Equal(t, http.StatusOK, res.StatusCode)
		assert.Equal(t, "ok", payload["backend"])
		assert.Equal(t, "/api/v1/auth/login", backendPath(t, backendPathsCh))
	})

	t.Run("protected routes reject anonymous requests", func(t *testing.T) {
		req, err := http.NewRequest(http.MethodGet, base+"/api/v1/files", nil)
		require.NoError(t, err)

		res, payload := getJSON(t, client, req)

		assert.Equal(t, http.StatusUnauthorized, res.StatusCode)
		assert.Contains(t, payload["error"], "missing or invalid authorization header")
	})

	t.Run("protected routes are proxied with the caller identity", func(t *testing.T) {
		token, err := jwt.NewWithClaims(jwt.SigningMethodHS256, &middleware.JWTClaims{
			RegisteredClaims: jwt.RegisteredClaims{
				Subject:   "user-42",
				ExpiresAt: jwt.NewNumericDate(time.Now().Add(time.Hour)),
			},
		}).SignedString([]byte("test-secret"))
		require.NoError(t, err)

		req, err := http.NewRequest(http.MethodGet, base+"/api/v1/files/report.pdf", nil)
		require.NoError(t, err)
		req.Header.Set("Authorization", "Bearer "+token)

		res, payload := getJSON(t, client, req)

		assert.Equal(t, http.StatusOK, res.StatusCode)
		assert.Equal(t, "ok", payload["backend"])
		assert.Equal(t, "/api/v1/files/report.pdf", backendPath(t, backendPathsCh))
	})

	t.Run("CORS preflight is answered for the web app origin", func(t *testing.T) {
		req, err := http.NewRequest(http.MethodOptions, base+"/api/v1/files", nil)
		require.NoError(t, err)
		req.Header.Set("Origin", "http://localhost:3000")
		req.Header.Set("Access-Control-Request-Method", http.MethodGet)

		res, err := client.Do(req)
		require.NoError(t, err)
		defer res.Body.Close()

		assert.Equal(t, http.StatusNoContent, res.StatusCode)
		assert.Equal(t, "http://localhost:3000", res.Header.Get("Access-Control-Allow-Origin"))
		assert.Equal(t, "true", res.Header.Get("Access-Control-Allow-Credentials"))
		assert.Contains(t, res.Header.Get("Access-Control-Allow-Methods"), http.MethodDelete)
	})

	t.Run("unmapped paths fall through to the proxy router's 404", func(t *testing.T) {
		req, err := http.NewRequest(http.MethodGet, base+"/definitely-not-a-route", nil)
		require.NoError(t, err)

		res, payload := getJSON(t, client, req)

		assert.Equal(t, http.StatusNotFound, res.StatusCode)
		assert.Equal(t, "route not found", payload["error"])
	})

	// SIGTERM must drain the listener and let main return. The signal is
	// re-sent until main exits so the test cannot race main's signal.Notify.
	waitFor(t, "main to exit after SIGTERM", func() bool {
		_ = syscall.Kill(syscall.Getpid(), syscall.SIGTERM)
		select {
		case <-done:
			return true
		case <-time.After(100 * time.Millisecond):
			return false
		}
	})

	_, err = client.Get(base + "/health")
	assert.Error(t, err, "the listener is closed once main returns")
}
