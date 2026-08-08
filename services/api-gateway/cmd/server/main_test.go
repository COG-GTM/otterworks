package main

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/Cognition-Partner-Workshops/otterworks/services/api-gateway/internal/proxy"
)

func TestRoutePrefixes(t *testing.T) {
	t.Run("maps routes to their prefixes in order", func(t *testing.T) {
		prefixes := routePrefixes([]proxy.Route{
			{Prefix: "/api/v1/auth", TargetURL: "http://auth:1"},
			{Prefix: "/api/v1/files", TargetURL: "http://file:2"},
		})

		assert.Equal(t, []string{"/api/v1/auth", "/api/v1/files"}, prefixes)
	})

	t.Run("returns an empty slice for no routes", func(t *testing.T) {
		assert.Empty(t, routePrefixes(nil))
	})
}

func TestInitTracer(t *testing.T) {
	// Point the OTLP exporter at a collector that always accepts, so shutdown
	// never falls back to retrying against a dead localhost:4318.
	collector := newFakeOTLPCollector(t)
	t.Setenv("OTEL_EXPORTER_OTLP_ENDPOINT", collector)
	t.Setenv("OTEL_EXPORTER_OTLP_TRACES_INSECURE", "true")

	shutdown := initTracer()

	require.NotNil(t, shutdown, "a tracer provider is installed")
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	assert.NoError(t, shutdown(ctx))
}

// newFakeOTLPCollector starts an HTTP server that accepts OTLP/HTTP exports.
func newFakeOTLPCollector(t *testing.T) string {
	t.Helper()

	ln, err := net.Listen("tcp", "127.0.0.1:0")
	require.NoError(t, err)

	srv := &http.Server{
		Handler: http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			_, _ = io.Copy(io.Discard, r.Body)
			w.WriteHeader(http.StatusOK)
		}),
		ReadHeaderTimeout: 5 * time.Second,
	}
	go func() { _ = srv.Serve(ln) }()
	t.Cleanup(func() {
		ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		_ = srv.Shutdown(ctx)
	})

	return "http://" + ln.Addr().String()
}

// freePort asks the kernel for an unused port and immediately releases it.
func freePort(t *testing.T) string {
	t.Helper()

	ln, err := net.Listen("tcp", "127.0.0.1:0")
	require.NoError(t, err)
	port := ln.Addr().(*net.TCPAddr).Port
	require.NoError(t, ln.Close())
	return fmt.Sprintf("%d", port)
}

// TestMain_ServesAndShutsDownGracefully boots the real gateway the way the
// container does -- configuration from the environment, a signal to stop --
// and exercises the assembled middleware stack end to end.
func TestMain_ServesAndShutsDownGracefully(t *testing.T) {
	// Register a handler for SIGTERM before main() does, so the signal below can
	// never fall through to the default action and kill the test binary.
	guard := make(chan os.Signal, 1)
	signal.Notify(guard, syscall.SIGTERM)
	defer signal.Stop(guard)

	backend := newFakeOTLPCollector(t)
	port := freePort(t)

	t.Setenv("PORT", port)
	t.Setenv("LOG_LEVEL", "error")
	t.Setenv("JWT_SECRET", "test-secret")
	t.Setenv("SHUTDOWN_TIMEOUT_SECONDS", "5")
	t.Setenv("OTEL_EXPORTER_OTLP_ENDPOINT", backend)
	t.Setenv("AUTH_SERVICE_URL", backend)

	done := make(chan struct{})
	go func() {
		defer close(done)
		main()
	}()

	base := "http://127.0.0.1:" + port
	client := &http.Client{Timeout: 2 * time.Second}
	requireServerUp(t, client, base+"/health")

	t.Run("health endpoint is public", func(t *testing.T) {
		res, err := client.Get(base + "/health")
		require.NoError(t, err)
		defer func() { _ = res.Body.Close() }()

		var body map[string]string
		require.NoError(t, json.NewDecoder(res.Body).Decode(&body))
		assert.Equal(t, http.StatusOK, res.StatusCode)
		assert.Equal(t, "healthy", body["status"])
		assert.NotEmpty(t, res.Header.Get("X-Request-ID"), "the request-ID middleware is wired in")
	})

	t.Run("prometheus metrics are exposed", func(t *testing.T) {
		res, err := client.Get(base + "/metrics")
		require.NoError(t, err)
		defer func() { _ = res.Body.Close() }()
		body, err := io.ReadAll(res.Body)
		require.NoError(t, err)

		assert.Equal(t, http.StatusOK, res.StatusCode)
		assert.Contains(t, string(body), "api_gateway_http_requests_total")
	})

	t.Run("protected routes require a token", func(t *testing.T) {
		res, err := client.Get(base + "/api/v1/files/1")
		require.NoError(t, err)
		defer func() { _ = res.Body.Close() }()

		assert.Equal(t, http.StatusUnauthorized, res.StatusCode)
	})

	t.Run("public auth routes reach the backend", func(t *testing.T) {
		res, err := client.Post(base+"/api/v1/auth/login", "application/json", nil)
		require.NoError(t, err)
		defer func() { _ = res.Body.Close() }()

		assert.Equal(t, http.StatusOK, res.StatusCode, "proxied to the stub auth backend")
	})

	t.Run("unknown routes return the gateway 404", func(t *testing.T) {
		res, err := client.Get(base + "/definitely-not-a-route")
		require.NoError(t, err)
		defer func() { _ = res.Body.Close() }()

		assert.Equal(t, http.StatusNotFound, res.StatusCode)
	})

	t.Run("CORS preflight is answered for an allowed origin", func(t *testing.T) {
		req, err := http.NewRequest(http.MethodOptions, base+"/api/v1/files", nil)
		require.NoError(t, err)
		req.Header.Set("Origin", "http://localhost:3000")
		req.Header.Set("Access-Control-Request-Method", http.MethodGet)

		res, err := client.Do(req)
		require.NoError(t, err)
		defer func() { _ = res.Body.Close() }()

		assert.Equal(t, http.StatusNoContent, res.StatusCode)
		assert.Equal(t, "http://localhost:3000", res.Header.Get("Access-Control-Allow-Origin"))
	})

	require.NoError(t, syscall.Kill(os.Getpid(), syscall.SIGTERM))

	select {
	case <-done:
	case <-time.After(30 * time.Second):
		t.Fatal("main() did not return after SIGTERM")
	}

	_, err := client.Get(base + "/health")
	assert.Error(t, err, "the listener is closed once main() returns")
}

func requireServerUp(t *testing.T, client *http.Client, url string) {
	t.Helper()

	deadline := time.Now().Add(15 * time.Second)
	for time.Now().Before(deadline) {
		res, err := client.Get(url)
		if err == nil {
			_ = res.Body.Close()
			return
		}
		time.Sleep(20 * time.Millisecond)
	}
	t.Fatal("the gateway did not start listening in time")
}
