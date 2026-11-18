package main

import (
	"context"
	"io"
	"net"
	"net/http"
	"os"
	"os/signal"
	"strconv"
	"strings"
	"syscall"
	"testing"
	"time"

	"github.com/golang-jwt/jwt/v5"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/Cognition-Partner-Workshops/otterworks/services/api-gateway/internal/middleware"
	"github.com/Cognition-Partner-Workshops/otterworks/services/api-gateway/internal/proxy"
)

const mainTestSecret = "main-test-secret"

func freePort(t *testing.T) string {
	t.Helper()
	l, err := net.Listen("tcp", "127.0.0.1:0")
	require.NoError(t, err)
	defer l.Close()
	return strconv.Itoa(l.Addr().(*net.TCPAddr).Port)
}

func TestRoutePrefixes(t *testing.T) {
	assert.Empty(t, routePrefixes(nil))
	assert.Equal(t, []string{"/a", "/b"}, routePrefixes([]proxy.Route{{Prefix: "/a"}, {Prefix: "/b"}}))
}

func TestInitTracer(t *testing.T) {
	t.Setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://127.0.0.1:1")
	shutdown := initTracer()
	require.NotNil(t, shutdown)
	ctx, cancel := context.WithTimeout(context.Background(), time.Second)
	defer cancel()
	assert.NoError(t, shutdown(ctx))
}

// TestMain_ServesFullStackAndShutsDownOnSignal runs main() in-process. The
// test registers its own SIGTERM handler first so the signal never kills the
// test binary.
func TestMain_ServesFullStackAndShutsDownOnSignal(t *testing.T) {
	type seen struct{ path, userID string }
	hits := make(chan seen, 16)
	backend := http.Server{Handler: http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		hits <- seen{r.URL.Path, r.Header.Get("X-User-ID")}
		w.WriteHeader(http.StatusOK)
	})}
	bl, err := net.Listen("tcp", "127.0.0.1:0")
	require.NoError(t, err)
	go backend.Serve(bl)
	defer backend.Close()
	backendURL := "http://" + bl.Addr().String()

	port := freePort(t)
	t.Setenv("PORT", port)
	t.Setenv("JWT_SECRET", mainTestSecret)
	t.Setenv("AUTH_SERVICE_URL", backendURL)
	t.Setenv("FILE_SERVICE_URL", backendURL)
	t.Setenv("LOG_LEVEL", "error")
	t.Setenv("SHUTDOWN_TIMEOUT_SECONDS", "2")
	t.Setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://127.0.0.1:1")
	t.Setenv("OTEL_EXPORTER_OTLP_TIMEOUT", "100")

	sig := make(chan os.Signal, 1)
	signal.Notify(sig, syscall.SIGTERM)
	defer signal.Stop(sig)

	done := make(chan struct{})
	go func() {
		defer close(done)
		main()
	}()

	base := "http://127.0.0.1:" + port
	client := &http.Client{Timeout: 2 * time.Second}
	require.Eventually(t, func() bool {
		resp, err := client.Get(base + "/health")
		if err != nil {
			return false
		}
		resp.Body.Close()
		return resp.StatusCode == http.StatusOK
	}, 5*time.Second, 20*time.Millisecond)

	do := func(method, path string, hdr map[string]string) *http.Response {
		req, err := http.NewRequest(method, base+path, nil)
		require.NoError(t, err)
		for k, v := range hdr {
			req.Header.Set(k, v)
		}
		resp, err := client.Do(req)
		require.NoError(t, err)
		t.Cleanup(func() { resp.Body.Close() })
		return resp
	}

	resp := do(http.MethodGet, "/health", nil)
	assert.NotEmpty(t, resp.Header.Get("X-Request-ID"))

	resp = do(http.MethodGet, "/api/v1/files/list", nil)
	assert.Equal(t, http.StatusUnauthorized, resp.StatusCode)

	resp = do(http.MethodPost, "/api/v1/auth/login", nil)
	assert.Equal(t, http.StatusOK, resp.StatusCode)
	assert.Equal(t, seen{"/api/v1/auth/login", ""}, <-hits)

	tok, err := jwt.NewWithClaims(jwt.SigningMethodHS256, middleware.JWTClaims{
		RegisteredClaims: jwt.RegisteredClaims{
			Subject:   "user-7",
			ExpiresAt: jwt.NewNumericDate(time.Now().Add(time.Hour)),
		},
	}).SignedString([]byte(mainTestSecret))
	require.NoError(t, err)
	resp = do(http.MethodGet, "/api/v1/files/list", map[string]string{"Authorization": "Bearer " + tok})
	assert.Equal(t, http.StatusOK, resp.StatusCode)
	assert.Equal(t, seen{"/api/v1/files/list", "user-7"}, <-hits)

	resp = do(http.MethodGet, "/not-a-route", nil)
	assert.Equal(t, http.StatusNotFound, resp.StatusCode)

	resp = do(http.MethodOptions, "/api/v1/files/list", map[string]string{
		"Origin":                        "http://localhost:3000",
		"Access-Control-Request-Method": "GET",
	})
	assert.Equal(t, "http://localhost:3000", resp.Header.Get("Access-Control-Allow-Origin"))

	resp = do(http.MethodGet, "/metrics", nil)
	assert.Equal(t, http.StatusOK, resp.StatusCode)
	body, err := io.ReadAll(resp.Body)
	require.NoError(t, err)
	assert.True(t, strings.Contains(string(body), "api_gateway_http_requests_total"))

	deadline := time.After(10 * time.Second)
	tick := time.NewTicker(50 * time.Millisecond)
	defer tick.Stop()
	for {
		select {
		case <-done:
			_, err := client.Get(base + "/health")
			assert.Error(t, err, "server should be closed after shutdown")
			return
		case <-tick.C:
			require.NoError(t, syscall.Kill(os.Getpid(), syscall.SIGTERM))
		case <-deadline:
			t.Fatal("main did not exit after SIGTERM")
		}
	}
}
