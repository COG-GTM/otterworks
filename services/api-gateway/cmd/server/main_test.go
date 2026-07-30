package main

import (
	"context"
	"encoding/json"
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
	tests := []struct {
		name   string
		routes []proxy.Route
		want   []string
	}{
		{name: "no routes", routes: nil, want: []string{}},
		{
			name: "keeps order",
			routes: []proxy.Route{
				{Prefix: "/api/v1/auth", TargetURL: "http://auth:1"},
				{Prefix: "/socket.io", TargetURL: "http://collab:2"},
			},
			want: []string{"/api/v1/auth", "/socket.io"},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			assert.Equal(t, tt.want, routePrefixes(tt.routes))
		})
	}
}

func TestInitTracer(t *testing.T) {
	shutdown := initTracer()
	require.NotNil(t, shutdown, "the OTLP exporter is created lazily, so setup must succeed")

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	assert.NoError(t, shutdown(ctx))
}

// TestMainRunsAndShutsDownGracefully boots the real process wiring on an
// ephemeral port and stops it the way Kubernetes would, with SIGTERM.
func TestMainRunsAndShutsDownGracefully(t *testing.T) {
	// Register a handler before main does: an unhandled SIGTERM would kill the
	// test binary if it arrived before main's own signal.Notify.
	guard := make(chan os.Signal, 1)
	signal.Notify(guard, syscall.SIGTERM)
	defer signal.Stop(guard)

	port := freePort(t)
	t.Setenv("PORT", port)
	t.Setenv("JWT_SECRET", "main-test-secret")
	t.Setenv("LOG_LEVEL", "error")
	t.Setenv("SHUTDOWN_TIMEOUT_SECONDS", "10")
	t.Setenv("RATE_LIMIT_RPS", "1000")

	exited := make(chan struct{})
	go func() {
		defer close(exited)
		main()
	}()

	base := "http://127.0.0.1:" + port
	body := waitForHealth(t, base+"/health")

	var health struct {
		Status  string `json:"status"`
		Version string `json:"version"`
	}
	require.NoError(t, json.Unmarshal(body, &health))
	assert.Equal(t, "healthy", health.Status)

	t.Run("metrics are exposed", func(t *testing.T) {
		assert.Equal(t, http.StatusOK, getStatus(t, base+"/metrics"))
	})

	t.Run("protected route requires a token", func(t *testing.T) {
		assert.Equal(t, http.StatusUnauthorized, getStatus(t, base+"/api/v1/files"))
	})

	t.Run("unknown route is a JSON 404", func(t *testing.T) {
		assert.Equal(t, http.StatusNotFound, getStatus(t, base+"/no-such-route"))
	})

	self, err := os.FindProcess(os.Getpid())
	require.NoError(t, err)

	deadline := time.After(30 * time.Second)
	for {
		require.NoError(t, self.Signal(syscall.SIGTERM))
		select {
		case <-exited:
			_, err := http.Get(base + "/health")
			assert.Error(t, err, "the listener is closed once main returns")
			return
		case <-time.After(100 * time.Millisecond):
		case <-deadline:
			t.Fatal("main did not shut down after SIGTERM")
		}
	}
}

// freePort reserves an ephemeral port and releases it for the server to claim.
func freePort(t *testing.T) string {
	t.Helper()
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	require.NoError(t, err)
	_, port, err := net.SplitHostPort(ln.Addr().String())
	require.NoError(t, err)
	require.NoError(t, ln.Close())
	return port
}

func waitForHealth(t *testing.T, url string) []byte {
	t.Helper()
	deadline := time.Now().Add(30 * time.Second)
	for time.Now().Before(deadline) {
		res, err := http.Get(url)
		if err != nil {
			time.Sleep(20 * time.Millisecond)
			continue
		}
		defer res.Body.Close()
		require.Equal(t, http.StatusOK, res.StatusCode)
		body, err := io.ReadAll(res.Body)
		require.NoError(t, err)
		return body
	}
	t.Fatalf("gateway did not become healthy at %s", url)
	return nil
}

func getStatus(t *testing.T, url string) int {
	t.Helper()
	res, err := http.Get(url)
	require.NoError(t, err)
	defer res.Body.Close()
	_, err = io.Copy(io.Discard, res.Body)
	require.NoError(t, err)
	return res.StatusCode
}
