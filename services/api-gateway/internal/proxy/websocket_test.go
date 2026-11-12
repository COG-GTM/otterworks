package proxy

import (
	"bufio"
	"net"
	"net/http"
	"net/http/httptest"
	"net/url"
	"sync/atomic"
	"testing"
	"time"

	"github.com/golang-jwt/jwt/v5"
	"github.com/rs/zerolog"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/Cognition-Partner-Workshops/otterworks/services/api-gateway/internal/middleware"
)

// newWebSocketGateway mirrors cmd/server/main.go: every route prefix is JWT-protected.
func newWebSocketGateway(t *testing.T, backendURL string) *httptest.Server {
	t.Helper()
	routes := []Route{{Prefix: "/ws/notifications", TargetURL: backendURL}}
	router := NewRouter(RouterConfig{
		Routes: routes,
		CBManager: NewCircuitBreakerManager(CircuitBreakerConfig{
			MaxRequests:  1,
			Interval:     time.Minute,
			Timeout:      time.Minute,
			FailureRatio: 0.9,
		}),
		Logger: zerolog.Nop(),
	})
	gateway := httptest.NewServer(middleware.JWTAuth(middleware.JWTConfig{
		Secret:              routerTestSecret,
		PublicPath:          middleware.DefaultPublicPaths(),
		PrefixPath:          middleware.DefaultPrefixPaths(),
		ProtectedPrefixPath: []string{"/ws/notifications"},
	})(router))
	t.Cleanup(gateway.Close)
	return gateway
}

// upgradingBackend completes a websocket handshake and records the identity and credentials the gateway forwarded.
func upgradingBackend(t *testing.T, hits *int32, gotUserID, gotAuth *atomic.Value) *httptest.Server {
	t.Helper()
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		atomic.AddInt32(hits, 1)
		gotUserID.Store(r.Header.Get("X-User-ID"))
		gotAuth.Store(r.Header.Get("Authorization"))
		conn, rw, err := w.(http.Hijacker).Hijack()
		if err != nil {
			return
		}
		defer conn.Close()
		_, _ = rw.WriteString("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n" +
			"Sec-WebSocket-Accept: s3pPLMBiTxaQ9kYGzzhZRbK+xOo=\r\n\r\n")
		_ = rw.Flush()
	}))
	t.Cleanup(backend.Close)
	return backend
}

func handshake(t *testing.T, gatewayURL, path string, headers map[string]string) int {
	t.Helper()
	u, err := url.Parse(gatewayURL)
	require.NoError(t, err)
	conn, err := net.DialTimeout("tcp", u.Host, 5*time.Second)
	require.NoError(t, err)
	defer conn.Close()
	require.NoError(t, conn.SetDeadline(time.Now().Add(5*time.Second)))

	req, err := http.NewRequest(http.MethodGet, gatewayURL+path, nil)
	require.NoError(t, err)
	req.Header.Set("Connection", "Upgrade")
	req.Header.Set("Upgrade", "websocket")
	req.Header.Set("Sec-WebSocket-Version", "13")
	req.Header.Set("Sec-WebSocket-Key", "dGhlIHNhbXBsZSBub25jZQ==")
	for k, v := range headers {
		req.Header.Set(k, v)
	}
	require.NoError(t, req.Write(conn))

	resp, err := http.ReadResponse(bufio.NewReader(conn), req)
	require.NoError(t, err)
	defer resp.Body.Close()
	return resp.StatusCode
}

func signedToken(t *testing.T, subject string) string {
	t.Helper()
	token := jwt.NewWithClaims(jwt.SigningMethodHS256, middleware.JWTClaims{
		RegisteredClaims: jwt.RegisteredClaims{
			ExpiresAt: jwt.NewNumericDate(time.Now().Add(time.Hour)),
			Subject:   subject,
		},
	})
	s, err := token.SignedString([]byte(routerTestSecret))
	require.NoError(t, err)
	return s
}

func TestNotificationWebSocketRequiresToken(t *testing.T) {
	var hits int32
	var gotUserID, gotAuth atomic.Value
	gateway := newWebSocketGateway(t, upgradingBackend(t, &hits, &gotUserID, &gotAuth).URL)

	assert.Equal(t, http.StatusUnauthorized, handshake(t, gateway.URL, "/ws/notifications", nil))
	assert.Equal(t, http.StatusUnauthorized, handshake(t, gateway.URL, "/ws/notifications/alice", map[string]string{"X-User-ID": "alice"}))
	assert.Equal(t, http.StatusUnauthorized, handshake(t, gateway.URL, "/ws/notifications", map[string]string{"Authorization": "Bearer not-a-jwt"}))
	assert.Zero(t, atomic.LoadInt32(&hits), "unauthenticated handshakes must not reach notification-service")
}

func TestNotificationWebSocketForwardsTokenIdentity(t *testing.T) {
	var hits int32
	var gotUserID, gotAuth atomic.Value
	gateway := newWebSocketGateway(t, upgradingBackend(t, &hits, &gotUserID, &gotAuth).URL)
	bearer := "Bearer " + signedToken(t, "alice")

	status := handshake(t, gateway.URL, "/ws/notifications", map[string]string{
		"Authorization": bearer,
		"X-User-ID":     "bob",
	})

	assert.Equal(t, http.StatusSwitchingProtocols, status)
	assert.Equal(t, int32(1), atomic.LoadInt32(&hits))
	assert.Equal(t, "alice", gotUserID.Load(), "X-User-ID must come from the JWT, not the client")
	assert.Equal(t, bearer, gotAuth.Load(), "notification-service verifies the bearer token itself, so the gateway must forward it")
}
