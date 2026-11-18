package proxy

import (
	"bufio"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/golang-jwt/jwt/v5"
	"github.com/rs/zerolog"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/Cognition-Partner-Workshops/otterworks/services/api-gateway/internal/middleware"
)

func signRouterToken(t *testing.T, claims middleware.JWTClaims) string {
	t.Helper()
	tok, err := jwt.NewWithClaims(jwt.SigningMethodHS256, claims).SignedString([]byte(routerTestSecret))
	require.NoError(t, err)
	return tok
}

func decodeJSON(t *testing.T, body io.Reader) map[string]string {
	t.Helper()
	var m map[string]string
	require.NoError(t, json.NewDecoder(body).Decode(&m))
	return m
}

func TestRouter_NotFoundReturnsJSON(t *testing.T) {
	handler := NewRouter(RouterConfig{
		Routes:    []Route{{Prefix: "/api/v1/files", TargetURL: "http://127.0.0.1:1"}},
		CBManager: NewCircuitBreakerManager(defaultTestConfig()),
		Logger:    zerolog.Nop(),
	})
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/api/v1/unknown", nil))

	assert.Equal(t, http.StatusNotFound, rec.Code)
	assert.Equal(t, "application/json", rec.Header().Get("Content-Type"))
	assert.Equal(t, "route not found", decodeJSON(t, rec.Body)["error"])
}

func TestRouter_BackendDownReturns502(t *testing.T) {
	dead := httptest.NewServer(http.NotFoundHandler())
	deadURL := dead.URL
	dead.Close()

	router := NewRouter(RouterConfig{
		Routes:    []Route{{Prefix: "/api/v1/search", TargetURL: deadURL}},
		CBManager: NewCircuitBreakerManager(defaultTestConfig()),
		Logger:    zerolog.Nop(),
	})
	rec := httptest.NewRecorder()
	router.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/api/v1/search?q=otter", nil))

	assert.Equal(t, http.StatusBadGateway, rec.Code)
	assert.Equal(t, "application/json", rec.Header().Get("Content-Type"))
	body := decodeJSON(t, rec.Body)
	assert.Equal(t, "service unavailable", body["error"])
	assert.Equal(t, "/api/v1/search", body["target"])
}

func TestRouter_OpenCircuitReturns503(t *testing.T) {
	var hits int
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		hits++
		w.WriteHeader(http.StatusInternalServerError)
	}))
	defer backend.Close()

	router := NewRouter(RouterConfig{
		Routes:    []Route{{Prefix: "/api/v1/audit", TargetURL: backend.URL}},
		CBManager: NewCircuitBreakerManager(defaultTestConfig()),
		Logger:    zerolog.Nop(),
	})

	for i := 0; i < 5; i++ {
		rec := httptest.NewRecorder()
		router.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/api/v1/audit/logs", nil))
		assert.Equal(t, http.StatusInternalServerError, rec.Code)
	}

	rec := httptest.NewRecorder()
	router.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/api/v1/audit/logs", nil))
	assert.Equal(t, http.StatusServiceUnavailable, rec.Code)
	assert.Equal(t, "application/json", rec.Header().Get("Content-Type"))
	body := decodeJSON(t, rec.Body)
	assert.Equal(t, "service temporarily unavailable", body["error"])
	assert.Equal(t, "/api/v1/audit", body["service"])
	assert.Equal(t, "circuit breaker open", body["reason"])
	assert.Equal(t, 5, hits, "open breaker must not forward to the backend")
}

func TestRouter_PrefixRootIsProxied(t *testing.T) {
	var gotPath string
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotPath = r.URL.Path
	}))
	defer backend.Close()

	router := NewRouter(RouterConfig{
		Routes:    []Route{{Prefix: "/api/v1/reports", TargetURL: backend.URL}},
		CBManager: NewCircuitBreakerManager(defaultTestConfig()),
		Logger:    zerolog.Nop(),
	})
	rec := httptest.NewRecorder()
	router.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/api/v1/reports", nil))
	assert.Equal(t, http.StatusOK, rec.Code)
	assert.Equal(t, "/api/v1/reports", gotPath)
}

func TestProxy_FallsBackToUserIDClaim(t *testing.T) {
	var gotUserID string
	var emailPresent bool
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotUserID = r.Header.Get("X-User-ID")
		_, emailPresent = r.Header["X-User-Email"]
	}))
	defer backend.Close()

	tok := signRouterToken(t, middleware.JWTClaims{
		UserID: "legacy-42",
		RegisteredClaims: jwt.RegisteredClaims{
			ExpiresAt: jwt.NewNumericDate(time.Now().Add(time.Hour)),
		},
	})
	req := httptest.NewRequest(http.MethodGet, "/api/v1/files/list", nil)
	req.Header.Set("Authorization", "Bearer "+tok)
	rec := httptest.NewRecorder()
	newTestRouter(t, backend.URL).ServeHTTP(rec, req)

	assert.Equal(t, http.StatusOK, rec.Code)
	assert.Equal(t, "legacy-42", gotUserID)
	assert.False(t, emailPresent)
}

func TestProxy_NoIdentityClaimsSetsNoHeaders(t *testing.T) {
	var userPresent bool
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, userPresent = r.Header["X-User-Id"]
	}))
	defer backend.Close()

	tok := signRouterToken(t, middleware.JWTClaims{
		RegisteredClaims: jwt.RegisteredClaims{ExpiresAt: jwt.NewNumericDate(time.Now().Add(time.Hour))},
	})
	req := httptest.NewRequest(http.MethodGet, "/api/v1/files/list", nil)
	req.Header.Set("Authorization", "Bearer "+tok)
	req.Header.Set("X-User-ID", "spoofed")
	rec := httptest.NewRecorder()
	newTestRouter(t, backend.URL).ServeHTTP(rec, req)

	assert.Equal(t, http.StatusOK, rec.Code)
	assert.False(t, userPresent)
}

func TestProxy_UnauthenticatedRouteStripsIdentityHeaders(t *testing.T) {
	var userPresent, emailPresent bool
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, userPresent = r.Header["X-User-Id"]
		_, emailPresent = r.Header["X-User-Email"]
	}))
	defer backend.Close()

	router := NewRouter(RouterConfig{
		Routes:    []Route{{Prefix: "/api/v1/auth", TargetURL: backend.URL}},
		CBManager: NewCircuitBreakerManager(defaultTestConfig()),
		Logger:    zerolog.Nop(),
	})
	req := httptest.NewRequest(http.MethodPost, "/api/v1/auth/login", nil)
	req.Header.Set("X-User-ID", "admin")
	req.Header.Set("X-User-Email", "admin@example.com")
	rec := httptest.NewRecorder()
	router.ServeHTTP(rec, req)

	assert.Equal(t, http.StatusOK, rec.Code)
	assert.False(t, userPresent)
	assert.False(t, emailPresent)
}

func TestProxy_WebSocketUpgradePassesThroughWithTracing(t *testing.T) {
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if !strings.EqualFold(r.Header.Get("Upgrade"), "otter-echo") {
			http.Error(w, "expected upgrade", http.StatusBadRequest)
			return
		}
		conn, brw, err := w.(http.Hijacker).Hijack()
		if err != nil {
			return
		}
		defer conn.Close()
		fmt.Fprint(brw, "HTTP/1.1 101 Switching Protocols\r\nConnection: Upgrade\r\nUpgrade: otter-echo\r\n\r\n")
		brw.Flush()
		line, _ := brw.ReadString('\n')
		fmt.Fprint(brw, "echo:"+line)
		brw.Flush()
	}))
	defer backend.Close()

	router := NewRouter(RouterConfig{
		Routes:        []Route{{Prefix: "/socket.io", TargetURL: backend.URL}},
		CBManager:     NewCircuitBreakerManager(defaultTestConfig()),
		Logger:        zerolog.Nop(),
		EnableTracing: true,
	})
	gw := httptest.NewServer(router)
	defer gw.Close()

	conn, err := net.Dial("tcp", strings.TrimPrefix(gw.URL, "http://"))
	require.NoError(t, err)
	defer conn.Close()
	require.NoError(t, conn.SetDeadline(time.Now().Add(5*time.Second)))

	fmt.Fprint(conn, "GET /socket.io/?EIO=4 HTTP/1.1\r\nHost: gw\r\nConnection: Upgrade\r\nUpgrade: otter-echo\r\n\r\n")
	br := bufio.NewReader(conn)
	resp, err := http.ReadResponse(br, nil)
	require.NoError(t, err)
	assert.Equal(t, http.StatusSwitchingProtocols, resp.StatusCode)

	fmt.Fprint(conn, "ping\n")
	line, err := br.ReadString('\n')
	require.NoError(t, err)
	assert.Equal(t, "echo:ping\n", line)
}

func TestProxy_TracingWrapperStillProxies(t *testing.T) {
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusAccepted)
	}))
	defer backend.Close()

	router := NewRouter(RouterConfig{
		Routes:        []Route{{Prefix: "/api/v1/analytics", TargetURL: backend.URL}},
		CBManager:     NewCircuitBreakerManager(defaultTestConfig()),
		Logger:        zerolog.Nop(),
		EnableTracing: true,
	})
	rec := httptest.NewRecorder()
	router.ServeHTTP(rec, httptest.NewRequest(http.MethodPost, "/api/v1/analytics/events", nil))
	assert.Equal(t, http.StatusAccepted, rec.Code)
}
