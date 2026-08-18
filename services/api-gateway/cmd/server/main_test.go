package main

import (
	"context"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"os/signal"
	"strings"
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

const mainTestSecret = "main-test-secret"

func TestRoutePrefixes(t *testing.T) {
	tests := []struct {
		name   string
		routes []proxy.Route
		want   []string
	}{
		{
			name:   "no routes",
			routes: nil,
			want:   []string{},
		},
		{
			name: "prefixes are preserved in order",
			routes: []proxy.Route{
				{Prefix: "/api/v1/auth", TargetURL: "http://auth:1"},
				{Prefix: "/api/v1/files", TargetURL: "http://file:2"},
				{Prefix: "/socket.io", TargetURL: "http://collab:3"},
			},
			want: []string{"/api/v1/auth", "/api/v1/files", "/socket.io"},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			assert.Equal(t, tt.want, routePrefixes(tt.routes))
		})
	}
}

// stubCollector accepts OTLP/HTTP exports so tracing shutdown is fast and offline.
func stubCollector(t *testing.T) *httptest.Server {
	t.Helper()
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusOK)
	}))
	t.Cleanup(srv.Close)
	return srv
}

func TestInitTracer(t *testing.T) {
	collector := stubCollector(t)
	t.Setenv("OTEL_EXPORTER_OTLP_ENDPOINT", collector.URL)

	shutdown := initTracer()

	require.NotNil(t, shutdown, "a reachable exporter must yield a shutdown func")

	_, span := otel.Tracer("test").Start(context.Background(), "unit")
	assert.True(t, span.SpanContext().IsValid(), "the registered provider must produce recorded spans")
	span.End()

	fields := otel.GetTextMapPropagator().Fields()
	assert.Contains(t, fields, "traceparent")
	assert.Contains(t, fields, "baggage")

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	require.NoError(t, shutdown(ctx))
}

func freePort(t *testing.T) string {
	t.Helper()
	l, err := net.Listen("tcp", "127.0.0.1:0")
	require.NoError(t, err)
	defer l.Close()
	_, port, err := net.SplitHostPort(l.Addr().String())
	require.NoError(t, err)
	return port
}

func mainTestToken(t *testing.T, userID string) string {
	t.Helper()
	claims := middleware.JWTClaims{
		UserID:           userID,
		Email:            "otter@otterworks.test",
		RegisteredClaims: jwt.RegisteredClaims{Subject: userID, ExpiresAt: jwt.NewNumericDate(time.Now().Add(time.Hour))},
	}
	signed, err := jwt.NewWithClaims(jwt.SigningMethodHS256, claims).SignedString([]byte(mainTestSecret))
	require.NoError(t, err)
	return signed
}

// TestMain_ServesTrafficAndShutsDownOnSIGTERM boots the real gateway process
// wiring (config, middleware stack, proxy routes, metrics, graceful shutdown)
// and drives it over a real socket.
func TestMain_ServesTrafficAndShutsDownOnSIGTERM(t *testing.T) {
	// Catch SIGTERM in the test process first: with a handler registered the
	// signal can never terminate the test binary, whatever the ordering.
	sink := make(chan os.Signal, 1)
	signal.Notify(sink, syscall.SIGTERM)
	defer signal.Stop(sink)

	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("X-Backend-Path", r.URL.Path)
		w.Header().Set("X-Seen-User", r.Header.Get("X-User-ID"))
		_, _ = w.Write([]byte("backend ok"))
	}))
	defer backend.Close()
	collector := stubCollector(t)

	port := freePort(t)
	t.Setenv("PORT", port)
	t.Setenv("LOG_LEVEL", "error")
	t.Setenv("JWT_SECRET", mainTestSecret)
	t.Setenv("SHUTDOWN_TIMEOUT_SECONDS", "10")
	t.Setenv("RATE_LIMIT_RPS", "1000")
	t.Setenv("OTEL_EXPORTER_OTLP_ENDPOINT", collector.URL)
	for _, key := range []string{
		"AUTH_SERVICE_URL", "FILE_SERVICE_URL", "DOCUMENT_SERVICE_URL", "COLLAB_SERVICE_URL",
		"NOTIFICATION_SERVICE_URL", "SEARCH_SERVICE_URL", "ANALYTICS_SERVICE_URL",
		"ADMIN_SERVICE_URL", "AUDIT_SERVICE_URL", "REPORT_SERVICE_URL",
	} {
		t.Setenv(key, backend.URL)
	}

	done := make(chan struct{})
	go func() {
		defer close(done)
		main()
	}()

	base := "http://127.0.0.1:" + port
	client := &http.Client{Timeout: 5 * time.Second}
	require.Eventually(t, func() bool {
		res, err := client.Get(base + "/health")
		if err != nil {
			return false
		}
		defer res.Body.Close()
		return res.StatusCode == http.StatusOK
	}, 20*time.Second, 50*time.Millisecond, "gateway never became healthy on "+base)

	t.Run("health is public and carries a request id", func(t *testing.T) {
		res, err := client.Get(base + "/health")
		require.NoError(t, err)
		defer res.Body.Close()
		body, err := io.ReadAll(res.Body)
		require.NoError(t, err)

		assert.Equal(t, http.StatusOK, res.StatusCode)
		assert.Contains(t, string(body), "healthy")
		assert.NotEmpty(t, res.Header.Get("X-Request-ID"))
	})

	t.Run("prometheus metrics are exposed", func(t *testing.T) {
		res, err := client.Get(base + "/metrics")
		require.NoError(t, err)
		defer res.Body.Close()
		body, err := io.ReadAll(res.Body)
		require.NoError(t, err)

		assert.Equal(t, http.StatusOK, res.StatusCode)
		assert.Contains(t, string(body), "api_gateway_http_requests_total")
	})

	t.Run("protected routes reject anonymous callers", func(t *testing.T) {
		res, err := client.Get(base + "/api/v1/files")
		require.NoError(t, err)
		defer res.Body.Close()
		body, err := io.ReadAll(res.Body)
		require.NoError(t, err)

		assert.Equal(t, http.StatusUnauthorized, res.StatusCode)
		assert.Contains(t, string(body), "missing or invalid authorization header")
	})

	t.Run("authenticated requests are proxied with the user identity", func(t *testing.T) {
		req, err := http.NewRequest(http.MethodGet, base+"/api/v1/files/42", nil)
		require.NoError(t, err)
		req.Header.Set("Authorization", "Bearer "+mainTestToken(t, "user-7"))

		res, err := client.Do(req)
		require.NoError(t, err)
		defer res.Body.Close()
		body, err := io.ReadAll(res.Body)
		require.NoError(t, err)

		assert.Equal(t, http.StatusOK, res.StatusCode)
		assert.Equal(t, "backend ok", string(body))
		assert.Equal(t, "/api/v1/files/42", res.Header.Get("X-Backend-Path"))
		assert.Equal(t, "user-7", res.Header.Get("X-Seen-User"))
	})

	t.Run("login is public and reaches the auth backend", func(t *testing.T) {
		res, err := client.Post(base+"/api/v1/auth/login", "application/json", strings.NewReader(`{"email":"a@b.c"}`))
		require.NoError(t, err)
		defer res.Body.Close()

		assert.Equal(t, http.StatusOK, res.StatusCode)
		assert.Equal(t, "/api/v1/auth/login", res.Header.Get("X-Backend-Path"))
	})

	t.Run("CORS preflight is answered for an allowed origin", func(t *testing.T) {
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
	})

	t.Run("unmapped paths fall through to the proxy 404", func(t *testing.T) {
		res, err := client.Get(base + "/definitely-not-a-route")
		require.NoError(t, err)
		defer res.Body.Close()
		body, err := io.ReadAll(res.Body)
		require.NoError(t, err)

		assert.Equal(t, http.StatusNotFound, res.StatusCode)
		assert.Contains(t, string(body), "route not found")
	})

	// SIGTERM must unwind the server gracefully. Resend until main observes it:
	// the handler is only installed once main reaches its shutdown wiring.
	deadline := time.After(30 * time.Second)
	ticker := time.NewTicker(100 * time.Millisecond)
	defer ticker.Stop()
	for exited := false; !exited; {
		require.NoError(t, syscall.Kill(syscall.Getpid(), syscall.SIGTERM))
		select {
		case <-done:
			exited = true
		case <-ticker.C:
		case <-deadline:
			t.Fatal("main did not exit within 30s of SIGTERM")
		}
	}

	_, err := client.Get(base + "/health")
	require.Error(t, err, "the listener must be closed after shutdown")
}
