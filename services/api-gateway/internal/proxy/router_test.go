package proxy

import (
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"sync"
	"testing"
	"time"

	"github.com/golang-jwt/jwt/v5"
	"github.com/rs/zerolog"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/Cognition-Partner-Workshops/otterworks/services/api-gateway/internal/middleware"
)

// receivedRequest is what the proxied request looked like once it arrived at
// the backend, so tests can assert on path and header rewriting.
type receivedRequest struct {
	path   string
	userID string
	method string
}

// echoBackend guards the recorded request with a mutex: the handler runs on the
// httptest server's own connection goroutine, and the loopback TCP connection
// alone is not a happens-before edge the race detector recognises.
type echoBackend struct {
	*httptest.Server
	mu   sync.Mutex
	last receivedRequest
}

func newEchoBackend(t *testing.T) *echoBackend {
	t.Helper()
	b := &echoBackend{}
	b.Server = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		b.mu.Lock()
		b.last = receivedRequest{path: r.URL.Path, userID: r.Header.Get("X-User-ID"), method: r.Method}
		b.mu.Unlock()
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte(`{"ok":true}`))
	}))
	t.Cleanup(b.Close)
	return b
}

func (b *echoBackend) received() receivedRequest {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.last
}

func testRouter(t *testing.T, backendURL string, tracing bool) http.Handler {
	t.Helper()
	return NewRouter(RouterConfig{
		Routes:        []Route{{Prefix: "/api/v1/auth", TargetURL: backendURL}},
		CBManager:     NewCircuitBreakerManager(defaultTestConfig()),
		Logger:        zerolog.Nop(),
		EnableTracing: tracing,
	})
}

func TestNewRouter_ProxiesPreservingFullPath(t *testing.T) {
	backend := newEchoBackend(t)
	r := testRouter(t, backend.URL, false)

	req := httptest.NewRequest(http.MethodPost, "/api/v1/auth/login", nil)
	rec := httptest.NewRecorder()
	r.ServeHTTP(rec, req)

	res := rec.Result()
	defer res.Body.Close()
	body, err := io.ReadAll(res.Body)
	require.NoError(t, err)

	assert.Equal(t, http.StatusOK, res.StatusCode)
	assert.JSONEq(t, `{"ok":true}`, string(body))
	got := backend.received()
	assert.Equal(t, "/api/v1/auth/login", got.path)
	assert.Equal(t, http.MethodPost, got.method)
}

func TestNewRouter_ProxiesPrefixRootPath(t *testing.T) {
	backend := newEchoBackend(t)
	r := testRouter(t, backend.URL, false)

	req := httptest.NewRequest(http.MethodGet, "/api/v1/auth", nil)
	rec := httptest.NewRecorder()
	r.ServeHTTP(rec, req)

	assert.Equal(t, http.StatusOK, rec.Code)
	assert.Equal(t, "/api/v1/auth", backend.received().path)
}

func TestNewRouter_WithTracingStillProxies(t *testing.T) {
	backend := newEchoBackend(t)
	r := testRouter(t, backend.URL, true)

	req := httptest.NewRequest(http.MethodGet, "/api/v1/auth/me", nil)
	rec := httptest.NewRecorder()
	r.ServeHTTP(rec, req)

	assert.Equal(t, http.StatusOK, rec.Code)
	assert.Equal(t, "/api/v1/auth/me", backend.received().path)
}

func TestNewRouter_UnknownRouteReturnsJSON404(t *testing.T) {
	r := NewRouter(RouterConfig{
		CBManager: NewCircuitBreakerManager(defaultTestConfig()),
		Logger:    zerolog.Nop(),
	})

	req := httptest.NewRequest(http.MethodGet, "/nope", nil)
	rec := httptest.NewRecorder()
	r.ServeHTTP(rec, req)

	assert.Equal(t, http.StatusNotFound, rec.Code)
	assert.Equal(t, "application/json", rec.Header().Get("Content-Type"))
	assert.JSONEq(t, `{"error":"route not found"}`, rec.Body.String())
}

func TestNewRouter_UnreachableBackendReturnsJSON502(t *testing.T) {
	dead := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {}))
	deadURL := dead.URL
	dead.Close() // nothing is listening on deadURL any more

	r := testRouter(t, deadURL, false)

	req := httptest.NewRequest(http.MethodGet, "/api/v1/auth/login", nil)
	rec := httptest.NewRecorder()
	r.ServeHTTP(rec, req)

	assert.Equal(t, http.StatusBadGateway, rec.Code)
	assert.Equal(t, "application/json", rec.Header().Get("Content-Type"))
	assert.JSONEq(t, `{"error":"service unavailable","target":"/api/v1/auth"}`, rec.Body.String())
}

func TestNewRouter_OpenCircuitBreakerReturnsJSON503(t *testing.T) {
	failing := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusInternalServerError)
	}))
	defer failing.Close()

	r := NewRouter(RouterConfig{
		Routes: []Route{{Prefix: "/api/v1/auth", TargetURL: failing.URL}},
		CBManager: NewCircuitBreakerManager(CircuitBreakerConfig{
			MaxRequests:  1,
			Interval:     time.Minute,
			Timeout:      time.Minute,
			FailureRatio: 0.5,
		}),
		Logger: zerolog.Nop(),
	})

	// shouldTrip needs a minimum sample of 5 requests before it can open.
	for i := 0; i < 5; i++ {
		rec := httptest.NewRecorder()
		r.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/api/v1/auth/login", nil))
		require.Equal(t, http.StatusInternalServerError, rec.Code)
	}

	rec := httptest.NewRecorder()
	r.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/api/v1/auth/login", nil))

	assert.Equal(t, http.StatusServiceUnavailable, rec.Code)
	assert.Equal(t, "application/json", rec.Header().Get("Content-Type"))

	var body map[string]string
	require.NoError(t, json.Unmarshal(rec.Body.Bytes(), &body))
	assert.Equal(t, "service temporarily unavailable", body["error"])
	assert.Equal(t, "/api/v1/auth", body["service"])
	assert.Equal(t, "circuit breaker open", body["reason"])
}

// signedToken builds an HS256 token the real JWT middleware will accept, so
// the director's identity forwarding is exercised end to end.
func signedToken(t *testing.T, secret string, claims middleware.JWTClaims) string {
	t.Helper()
	claims.ExpiresAt = jwt.NewNumericDate(time.Now().Add(time.Hour))
	token, err := jwt.NewWithClaims(jwt.SigningMethodHS256, claims).SignedString([]byte(secret))
	require.NoError(t, err)
	return token
}

func TestNewRouter_ForwardsUserIdentityHeader(t *testing.T) {
	const secret = "test-secret"

	tests := []struct {
		name       string
		claims     middleware.JWTClaims
		wantUserID string
	}{
		{
			name:       "prefers the standard sub claim",
			claims:     middleware.JWTClaims{UserID: "legacy-id", RegisteredClaims: jwt.RegisteredClaims{Subject: "sub-id"}},
			wantUserID: "sub-id",
		},
		{
			name:       "falls back to the custom user_id claim",
			claims:     middleware.JWTClaims{UserID: "legacy-id"},
			wantUserID: "legacy-id",
		},
		{
			name:       "sends no header when the token carries no identity",
			claims:     middleware.JWTClaims{Email: "nobody@example.test"},
			wantUserID: "",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			backend := newEchoBackend(t)
			handler := middleware.JWTAuth(middleware.JWTConfig{
				Secret:              secret,
				ProtectedPrefixPath: []string{"/api/v1/auth"},
			})(testRouter(t, backend.URL, false))

			req := httptest.NewRequest(http.MethodGet, "/api/v1/auth/me", nil)
			req.Header.Set("Authorization", "Bearer "+signedToken(t, secret, tt.claims))
			rec := httptest.NewRecorder()
			handler.ServeHTTP(rec, req)

			require.Equal(t, http.StatusOK, rec.Code)
			assert.Equal(t, tt.wantUserID, backend.received().userID)
		})
	}
}

func TestNewRouter_WithoutClaimsSetsNoUserHeader(t *testing.T) {
	backend := newEchoBackend(t)
	r := testRouter(t, backend.URL, false)

	req := httptest.NewRequest(http.MethodGet, "/api/v1/auth/me", nil)
	rec := httptest.NewRecorder()
	r.ServeHTTP(rec, req)

	require.Equal(t, http.StatusOK, rec.Code)
	assert.Empty(t, backend.received().userID)
}
