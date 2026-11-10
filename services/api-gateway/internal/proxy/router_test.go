package proxy

import (
	"net/http"
	"net/http/httptest"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/golang-jwt/jwt/v5"
	"github.com/rs/zerolog"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/Cognition-Partner-Workshops/otterworks/services/api-gateway/internal/audit"
	"github.com/Cognition-Partner-Workshops/otterworks/services/api-gateway/internal/middleware"
)

const routerTestSecret = "test-secret-key-for-jwt-signing"

func newTestRouter(t *testing.T, backendURL string) http.Handler {
	t.Helper()
	router := NewRouter(RouterConfig{
		Routes: []Route{{Prefix: "/api/v1/files", TargetURL: backendURL}},
		CBManager: NewCircuitBreakerManager(CircuitBreakerConfig{
			MaxRequests:  1,
			Interval:     time.Minute,
			Timeout:      time.Minute,
			FailureRatio: 0.9,
		}),
		Logger: zerolog.Nop(),
	})
	return middleware.JWTAuth(middleware.JWTConfig{
		Secret:     routerTestSecret,
		PublicPath: middleware.DefaultPublicPaths(),
		PrefixPath: middleware.DefaultPrefixPaths(),
	})(router)
}

func TestProxyForwardsUserIdentityHeaders(t *testing.T) {
	var gotUserID, gotEmail string
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotUserID = r.Header.Get("X-User-ID")
		gotEmail = r.Header.Get("X-User-Email")
		w.WriteHeader(http.StatusOK)
	}))
	defer backend.Close()

	handler := newTestRouter(t, backend.URL)

	claims := middleware.JWTClaims{
		UserID: "user-123",
		Email:  "test@otterworks.dev",
		RegisteredClaims: jwt.RegisteredClaims{
			ExpiresAt: jwt.NewNumericDate(time.Now().Add(time.Hour)),
			Subject:   "user-123",
		},
	}
	token := jwt.NewWithClaims(jwt.SigningMethodHS256, claims)
	tokenStr, err := token.SignedString([]byte(routerTestSecret))
	require.NoError(t, err)

	req := httptest.NewRequest(http.MethodGet, "/api/v1/files/list", nil)
	req.Header.Set("Authorization", "Bearer "+tokenStr)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	assert.Equal(t, http.StatusOK, rec.Code)
	assert.Equal(t, "user-123", gotUserID)
	assert.Equal(t, "test@otterworks.dev", gotEmail)
}

func TestProxyStripsSpoofedIdentityHeaders(t *testing.T) {
	var emailPresent bool
	var gotUserID string
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, emailPresent = r.Header["X-User-Email"]
		gotUserID = r.Header.Get("X-User-ID")
		w.WriteHeader(http.StatusOK)
	}))
	defer backend.Close()

	handler := newTestRouter(t, backend.URL)

	claims := middleware.JWTClaims{
		UserID: "user-123",
		RegisteredClaims: jwt.RegisteredClaims{
			ExpiresAt: jwt.NewNumericDate(time.Now().Add(time.Hour)),
			Subject:   "user-123",
		},
	}
	token := jwt.NewWithClaims(jwt.SigningMethodHS256, claims)
	tokenStr, err := token.SignedString([]byte(routerTestSecret))
	require.NoError(t, err)

	req := httptest.NewRequest(http.MethodGet, "/api/v1/files/list", nil)
	req.Header.Set("Authorization", "Bearer "+tokenStr)
	req.Header.Set("X-User-Email", "victim@example.com")
	req.Header.Set("X-User-ID", "someone-else")
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	assert.Equal(t, http.StatusOK, rec.Code)
	assert.False(t, emailPresent, "spoofed X-User-Email must not reach the backend when the JWT has no email claim")
	assert.Equal(t, "user-123", gotUserID, "X-User-ID must come from the JWT, not the client")
}

type capturedHeaders struct {
	mu sync.Mutex
	h  http.Header
}

func (c *capturedHeaders) get(name string) string {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.h.Get(name)
}

func (c *capturedHeaders) values(name string) []string {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.h.Values(name)
}

func headerCapturingBackend(t *testing.T, status int) (*httptest.Server, *capturedHeaders) {
	t.Helper()
	got := &capturedHeaders{}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		got.mu.Lock()
		got.h = r.Header.Clone()
		got.mu.Unlock()
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(status)
		_, _ = w.Write([]byte(`{"ok":true}`))
	}))
	t.Cleanup(srv.Close)
	return srv, got
}

// newGatewayStack mirrors the production middleware order in cmd/server/main.go.
func newGatewayStack(t *testing.T, routes []Route, emitter audit.Emitter, trustedCIDRs ...string) http.Handler {
	t.Helper()
	trust, err := middleware.NewProxyTrust(trustedCIDRs)
	require.NoError(t, err)

	router := NewRouter(RouterConfig{
		Routes: routes,
		CBManager: NewCircuitBreakerManager(CircuitBreakerConfig{
			MaxRequests: 1, Interval: time.Minute, Timeout: time.Minute, FailureRatio: 0.9,
		}),
		Logger: zerolog.Nop(),
	})
	prefixes := make([]string, 0, len(routes))
	for _, r := range routes {
		prefixes = append(prefixes, r.Prefix)
	}

	var h http.Handler = router
	h = middleware.JWTAuth(middleware.JWTConfig{
		Secret:              routerTestSecret,
		PublicPath:          middleware.DefaultPublicPaths(),
		PrefixPath:          middleware.DefaultPrefixPaths(),
		ProtectedPrefixPath: prefixes,
		Audit:               emitter,
	})(h)
	h = middleware.NewRateLimiter(1000).Handler(h)
	h = middleware.AuditAuthDenials(middleware.AuthDenialAuditConfig{
		Emitter: emitter, PathPrefixes: middleware.DefaultAuthDenialPrefixes(),
	})(h)
	h = middleware.ClientOriginMiddleware(trust)(h)
	h = middleware.RequestID(h)
	return h
}

func validToken(t *testing.T) string {
	t.Helper()
	tok, err := jwt.NewWithClaims(jwt.SigningMethodHS256, middleware.JWTClaims{
		RegisteredClaims: jwt.RegisteredClaims{Subject: "user-123", ExpiresAt: jwt.NewNumericDate(time.Now().Add(time.Hour))},
	}).SignedString([]byte(routerTestSecret))
	require.NoError(t, err)
	return tok
}

func TestProxyOverwritesSpoofedRealIPAndForwardsOrigin(t *testing.T) {
	backend, got := headerCapturingBackend(t, http.StatusOK)
	handler := newGatewayStack(t, []Route{{Prefix: "/api/v1/files", TargetURL: backend.URL}}, audit.Nop{}, "10.0.0.0/8")

	req := httptest.NewRequest(http.MethodGet, "/api/v1/files/list", nil)
	req.RemoteAddr = "203.0.113.7:50000"
	req.Header.Set("Authorization", "Bearer "+validToken(t))
	req.Header.Set("X-Real-IP", "1.1.1.1")
	req.Header.Set("X-Forwarded-For", "6.6.6.6")
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	require.Equal(t, http.StatusOK, rec.Code)
	assert.Equal(t, "203.0.113.7", got.get("X-Real-IP"), "spoofed X-Real-IP from an untrusted peer is overwritten")
	assert.Equal(t, []string{"203.0.113.7"}, got.values("X-Forwarded-For"), "spoofed X-Forwarded-For is discarded")

	generated := rec.Header().Get("X-Request-ID")
	require.NotEmpty(t, generated)
	assert.Equal(t, generated, got.get("X-Request-ID"), "a gateway-generated request ID reaches the upstream")
}

func TestProxyForwardsTrustedChainWithClientFirst(t *testing.T) {
	backend, got := headerCapturingBackend(t, http.StatusOK)
	handler := newGatewayStack(t, []Route{{Prefix: "/api/v1/files", TargetURL: backend.URL}}, audit.Nop{}, "10.0.0.0/8")

	req := httptest.NewRequest(http.MethodGet, "/api/v1/files/list", nil)
	req.RemoteAddr = "10.0.0.5:443" // ingress controller
	req.Header.Set("Authorization", "Bearer "+validToken(t))
	req.Header.Set("X-Forwarded-For", "6.6.6.6, 198.51.100.2")
	req.Header.Set("X-Real-IP", "6.6.6.6")
	req.Header.Set("X-Request-ID", "client-req-1")
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	require.Equal(t, http.StatusOK, rec.Code)
	assert.Equal(t, "198.51.100.2", got.get("X-Real-IP"))
	assert.Equal(t, "198.51.100.2, 10.0.0.5", got.get("X-Forwarded-For"), "first entry is the resolved client")
	assert.Equal(t, "client-req-1", got.get("X-Request-ID"))
}

func TestProxyStripsClientAuditToken(t *testing.T) {
	backend, got := headerCapturingBackend(t, http.StatusOK)
	handler := newGatewayStack(t, []Route{{Prefix: "/api/v1/audit", TargetURL: backend.URL}}, audit.Nop{})

	req := httptest.NewRequest(http.MethodPost, "/api/v1/audit/events", nil)
	req.Header.Set("Authorization", "Bearer "+validToken(t))
	req.Header.Set("X-Audit-Token", "guessed-token")
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	require.Equal(t, http.StatusOK, rec.Code)
	assert.Empty(t, got.values("X-Audit-Token"))
}

func TestAuditServiceFailureDoesNotAffectProxiedResponses(t *testing.T) {
	unblock := make(chan struct{})
	scenarios := map[string]http.HandlerFunc{
		"returns_500": func(w http.ResponseWriter, r *http.Request) {
			w.WriteHeader(http.StatusInternalServerError)
		},
		"hangs": func(w http.ResponseWriter, r *http.Request) {
			select {
			case <-unblock:
			case <-r.Context().Done():
			}
		},
	}

	var once sync.Once
	release := func() { once.Do(func() { close(unblock) }) }
	t.Cleanup(release)

	for name, auditHandler := range scenarios {
		t.Run(name, func(t *testing.T) {
			var auditCalls int32
			auditSrv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				atomic.AddInt32(&auditCalls, 1)
				auditHandler(w, r)
			}))
			defer auditSrv.Close()

			client := audit.New(audit.Config{
				URL:          auditSrv.URL,
				Token:        "otterworks-audit-dev-token",
				Timeout:      100 * time.Millisecond,
				MaxRetries:   1,
				RetryBackoff: time.Millisecond,
				Logger:       zerolog.Nop(),
			})

			files, _ := headerCapturingBackend(t, http.StatusOK)
			auth, _ := headerCapturingBackend(t, http.StatusForbidden)
			handler := newGatewayStack(t, []Route{
				{Prefix: "/api/v1/files", TargetURL: files.URL},
				{Prefix: "/api/v1/auth", TargetURL: auth.URL},
			}, client)

			start := time.Now()

			// Proxied success path.
			req := httptest.NewRequest(http.MethodGet, "/api/v1/files/list", nil)
			req.Header.Set("Authorization", "Bearer "+validToken(t))
			rec := httptest.NewRecorder()
			handler.ServeHTTP(rec, req)
			assert.Equal(t, http.StatusOK, rec.Code)
			assert.JSONEq(t, `{"ok":true}`, rec.Body.String())

			// Audited 401 path.
			req = httptest.NewRequest(http.MethodGet, "/api/v1/files/list", nil)
			rec = httptest.NewRecorder()
			handler.ServeHTTP(rec, req)
			assert.Equal(t, http.StatusUnauthorized, rec.Code)
			assert.JSONEq(t, `{"error":"missing or invalid authorization header"}`, rec.Body.String())

			// Audited upstream 403 path.
			req = httptest.NewRequest(http.MethodDelete, "/api/v1/auth/users/9", nil)
			req.Header.Set("Authorization", "Bearer "+validToken(t))
			rec = httptest.NewRecorder()
			handler.ServeHTTP(rec, req)
			assert.Equal(t, http.StatusForbidden, rec.Code)
			assert.JSONEq(t, `{"ok":true}`, rec.Body.String())

			assert.Less(t, time.Since(start), 100*time.Millisecond, "requests must not wait on audit-service")

			assert.Eventually(t, func() bool { return atomic.LoadInt32(&auditCalls) >= 2 },
				2*time.Second, 10*time.Millisecond, "both denials were sent to audit-service")
			if name == "hangs" {
				release()
			}
		})
	}
}
