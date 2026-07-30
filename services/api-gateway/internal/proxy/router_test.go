package proxy

import (
	"io"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/golang-jwt/jwt/v5"
	"github.com/rs/zerolog"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/Cognition-Partner-Workshops/otterworks/services/api-gateway/internal/middleware"
)

const testJWTSecret = "router-test-secret"

// newEchoBackend stands up a real loopback backend that mirrors what it
// received back in response headers, so assertions need no shared state.
func newEchoBackend(t *testing.T) *httptest.Server {
	t.Helper()
	be := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("X-Backend-Path", r.URL.Path)
		w.Header().Set("X-Backend-User-ID", r.Header.Get("X-User-ID"))
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("backend ok"))
	}))
	t.Cleanup(be.Close)
	return be
}

func newTestRouter(routes []Route, tracing bool) http.Handler {
	return NewRouter(RouterConfig{
		Routes:        routes,
		CBManager:     NewCircuitBreakerManager(defaultTestConfig()),
		Logger:        zerolog.Nop(),
		EnableTracing: tracing,
	})
}

// signedToken issues a token the JWT middleware accepts, so the proxy director
// sees real claims in the request context.
func signedToken(t *testing.T, claims middleware.JWTClaims) string {
	t.Helper()
	claims.ExpiresAt = jwt.NewNumericDate(time.Now().Add(time.Hour))
	signed, err := jwt.NewWithClaims(jwt.SigningMethodHS256, claims).SignedString([]byte(testJWTSecret))
	require.NoError(t, err)
	return signed
}

func TestNewRouter_ProxiesToBackend(t *testing.T) {
	backend := newEchoBackend(t)
	r := newTestRouter([]Route{{Prefix: "/api/v1/auth", TargetURL: backend.URL}}, false)

	for _, path := range []string{"/api/v1/auth/login", "/api/v1/auth"} {
		t.Run(path, func(t *testing.T) {
			req := httptest.NewRequest(http.MethodGet, path, nil)
			rec := httptest.NewRecorder()

			r.ServeHTTP(rec, req)

			res := rec.Result()
			defer res.Body.Close()
			body, err := io.ReadAll(res.Body)
			require.NoError(t, err)

			assert.Equal(t, http.StatusOK, res.StatusCode)
			// NewSingleHostReverseProxy preserves req.URL.Path all the way to the backend.
			assert.Equal(t, path, res.Header.Get("X-Backend-Path"))
			assert.Equal(t, "backend ok", string(body))
			assert.Empty(t, res.Header.Get("X-Backend-User-ID"))
		})
	}
}

func TestNewRouter_ForwardsUserIDFromClaims(t *testing.T) {
	tests := []struct {
		name   string
		claims middleware.JWTClaims
		want   string
	}{
		{
			name:   "subject claim",
			claims: middleware.JWTClaims{RegisteredClaims: jwt.RegisteredClaims{Subject: "user-from-sub"}},
			want:   "user-from-sub",
		},
		{
			name:   "user_id fallback",
			claims: middleware.JWTClaims{UserID: "user-from-custom-claim"},
			want:   "user-from-custom-claim",
		},
		{
			name:   "no identity",
			claims: middleware.JWTClaims{},
			want:   "",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			backend := newEchoBackend(t)
			proxyRouter := newTestRouter([]Route{{Prefix: "/api/v1/files", TargetURL: backend.URL}}, false)
			handler := middleware.JWTAuth(middleware.JWTConfig{
				Secret:              testJWTSecret,
				ProtectedPrefixPath: []string{"/api/v1/files"},
			})(proxyRouter)

			req := httptest.NewRequest(http.MethodGet, "/api/v1/files/abc", nil)
			req.Header.Set("Authorization", "Bearer "+signedToken(t, tt.claims))
			rec := httptest.NewRecorder()

			handler.ServeHTTP(rec, req)

			require.Equal(t, http.StatusOK, rec.Code)
			assert.Equal(t, tt.want, rec.Header().Get("X-Backend-User-ID"))
			assert.Equal(t, "/api/v1/files/abc", rec.Header().Get("X-Backend-Path"))
		})
	}
}

func TestNewRouter_TracingEnabled(t *testing.T) {
	backend := newEchoBackend(t)
	r := newTestRouter([]Route{{Prefix: "/api/v1/documents", TargetURL: backend.URL}}, true)

	req := httptest.NewRequest(http.MethodGet, "/api/v1/documents/1", nil)
	rec := httptest.NewRecorder()

	r.ServeHTTP(rec, req)

	assert.Equal(t, http.StatusOK, rec.Code)
	assert.Equal(t, "/api/v1/documents/1", rec.Header().Get("X-Backend-Path"))
}

func TestNewRouter_UnreachableBackendReturns502(t *testing.T) {
	dead := httptest.NewServer(http.HandlerFunc(func(http.ResponseWriter, *http.Request) {}))
	deadURL := dead.URL
	dead.Close() // nothing is listening on deadURL any more

	r := newTestRouter([]Route{{Prefix: "/api/v1/search", TargetURL: deadURL}}, false)

	req := httptest.NewRequest(http.MethodGet, "/api/v1/search/q", nil)
	rec := httptest.NewRecorder()

	r.ServeHTTP(rec, req)

	assert.Equal(t, http.StatusBadGateway, rec.Code)
	assert.Equal(t, "application/json", rec.Header().Get("Content-Type"))
	assert.JSONEq(t, `{"error":"service unavailable","target":"/api/v1/search"}`, rec.Body.String())
}

func TestNewRouter_OpenCircuitBreakerReturns503(t *testing.T) {
	failing := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusInternalServerError)
	}))
	defer failing.Close()

	cbManager := NewCircuitBreakerManager(CircuitBreakerConfig{
		MaxRequests:  1,
		Interval:     time.Minute,
		Timeout:      time.Minute,
		FailureRatio: 0.5,
	})
	r := NewRouter(RouterConfig{
		Routes:    []Route{{Prefix: "/api/v1/reports", TargetURL: failing.URL}},
		CBManager: cbManager,
		Logger:    zerolog.Nop(),
	})

	// shouldTrip needs a minimum sample size of 5 before the ratio applies.
	for i := 0; i < 5; i++ {
		rec := httptest.NewRecorder()
		r.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/api/v1/reports/daily", nil))
		require.Equal(t, http.StatusInternalServerError, rec.Code)
	}
	require.Equal(t, StateOpen, cbManager.Get("/api/v1/reports").State())

	rec := httptest.NewRecorder()
	r.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/api/v1/reports/daily", nil))

	assert.Equal(t, http.StatusServiceUnavailable, rec.Code)
	assert.Equal(t, "application/json", rec.Header().Get("Content-Type"))
	assert.JSONEq(t,
		`{"error":"service temporarily unavailable","service":"/api/v1/reports","reason":"circuit breaker open"}`,
		rec.Body.String())
}

func TestNewRouter_UnknownRouteReturnsJSON404(t *testing.T) {
	r := newTestRouter(nil, false)

	req := httptest.NewRequest(http.MethodGet, "/nope", nil)
	rec := httptest.NewRecorder()

	r.ServeHTTP(rec, req)

	assert.Equal(t, http.StatusNotFound, rec.Code)
	assert.Equal(t, "application/json", rec.Header().Get("Content-Type"))
	assert.JSONEq(t, `{"error":"route not found"}`, rec.Body.String())
}
