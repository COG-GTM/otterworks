package proxy

import (
	"io"
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

const testSecret = "router-test-secret"

func newTestRouterConfig(routes []Route, tracing bool) RouterConfig {
	return RouterConfig{
		Routes:        routes,
		CBManager:     NewCircuitBreakerManager(CircuitBreakerConfig{MaxRequests: 1, Timeout: time.Minute, FailureRatio: 0.5}),
		Logger:        zerolog.Nop(),
		EnableTracing: tracing,
	}
}

// signToken issues a token the real JWT middleware accepts, so the proxy's
// director sees claims exactly as it would in production.
func signToken(t *testing.T, claims middleware.JWTClaims) string {
	t.Helper()
	if claims.ExpiresAt == nil {
		claims.ExpiresAt = jwt.NewNumericDate(time.Now().Add(time.Hour))
	}
	signed, err := jwt.NewWithClaims(jwt.SigningMethodHS256, claims).SignedString([]byte(testSecret))
	require.NoError(t, err)
	return signed
}

func TestNewRouter_ProxiesToBackendPreservingPath(t *testing.T) {
	var gotMethod, gotBody string
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		gotMethod, gotBody = r.Method, string(body)
		w.Header().Set("X-Backend-Path", r.URL.Path)
		w.WriteHeader(http.StatusCreated)
		_, _ = w.Write([]byte("backend ok"))
	}))
	defer backend.Close()

	r := NewRouter(newTestRouterConfig([]Route{{Prefix: "/api/v1/auth", TargetURL: backend.URL}}, false))

	req := httptest.NewRequest(http.MethodPost, "/api/v1/auth/login", strings.NewReader(`{"email":"a@b.c"}`))
	rec := httptest.NewRecorder()
	r.ServeHTTP(rec, req)

	res := rec.Result()
	defer res.Body.Close()
	body, err := io.ReadAll(res.Body)
	require.NoError(t, err)

	assert.Equal(t, http.StatusCreated, res.StatusCode)
	assert.Equal(t, "/api/v1/auth/login", res.Header.Get("X-Backend-Path"))
	assert.Equal(t, "backend ok", string(body))
	assert.Equal(t, http.MethodPost, gotMethod)
	assert.Equal(t, `{"email":"a@b.c"}`, gotBody)
}

func TestNewRouter_ProxiesBarePrefix(t *testing.T) {
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("X-Backend-Path", r.URL.Path)
	}))
	defer backend.Close()

	r := NewRouter(newTestRouterConfig([]Route{{Prefix: "/api/v1/files", TargetURL: backend.URL}}, false))

	rec := httptest.NewRecorder()
	r.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/api/v1/files", nil))

	assert.Equal(t, http.StatusOK, rec.Code)
	assert.Equal(t, "/api/v1/files", rec.Header().Get("X-Backend-Path"))
}

func TestNewRouter_ForwardsUserIDFromJWTClaims(t *testing.T) {
	tests := []struct {
		name       string
		claims     *middleware.JWTClaims
		wantUserID string
	}{
		{
			name:       "subject claim wins over user_id",
			claims:     &middleware.JWTClaims{UserID: "legacy-id", RegisteredClaims: jwt.RegisteredClaims{Subject: "sub-id"}},
			wantUserID: "sub-id",
		},
		{
			name:       "falls back to the user_id claim",
			claims:     &middleware.JWTClaims{UserID: "legacy-id"},
			wantUserID: "legacy-id",
		},
		{
			name:       "claims carry no identity",
			claims:     &middleware.JWTClaims{Email: "a@b.c"},
			wantUserID: "",
		},
		{
			name:       "no claims on the context",
			claims:     nil,
			wantUserID: "",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			var seen string
			var sawHeader bool
			backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				seen = r.Header.Get("X-User-ID")
				_, sawHeader = r.Header["X-User-Id"]
			}))
			defer backend.Close()

			router := NewRouter(newTestRouterConfig([]Route{{Prefix: "/api/v1/files", TargetURL: backend.URL}}, false))
			handler := middleware.JWTAuth(middleware.JWTConfig{
				Secret:              testSecret,
				ProtectedPrefixPath: []string{"/api/v1/files"},
			})(router)

			req := httptest.NewRequest(http.MethodGet, "/api/v1/files/1", nil)
			if tt.claims != nil {
				req.Header.Set("Authorization", "Bearer "+signToken(t, *tt.claims))
			} else {
				// Unprotected route: the request reaches the proxy with no claims.
				handler = router
			}
			rec := httptest.NewRecorder()
			handler.ServeHTTP(rec, req)

			require.Equal(t, http.StatusOK, rec.Code)
			assert.Equal(t, tt.wantUserID, seen)
			assert.Equal(t, tt.wantUserID != "", sawHeader)
		})
	}
}

func TestNewRouter_UnreachableBackendReturnsJSON502(t *testing.T) {
	backend := httptest.NewServer(http.HandlerFunc(func(http.ResponseWriter, *http.Request) {}))
	target := backend.URL
	backend.Close() // nothing is listening on this port any more

	r := NewRouter(newTestRouterConfig([]Route{{Prefix: "/api/v1/search", TargetURL: target}}, false))

	rec := httptest.NewRecorder()
	r.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/api/v1/search/q", nil))

	assert.Equal(t, http.StatusBadGateway, rec.Code)
	assert.Equal(t, "application/json", rec.Header().Get("Content-Type"))
	assert.JSONEq(t, `{"error":"service unavailable","target":"/api/v1/search"}`, rec.Body.String())
}

func TestNewRouter_OpenCircuitBreakerReturnsJSON503(t *testing.T) {
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusInternalServerError)
	}))
	defer backend.Close()

	cfg := newTestRouterConfig([]Route{{Prefix: "/api/v1/admin", TargetURL: backend.URL}}, false)
	r := NewRouter(cfg)

	// shouldTrip requires at least 5 samples before the failure ratio applies.
	for i := 0; i < 5; i++ {
		rec := httptest.NewRecorder()
		r.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/api/v1/admin/users", nil))
		require.Equal(t, http.StatusInternalServerError, rec.Code)
	}
	require.Equal(t, StateOpen, cfg.CBManager.Get("/api/v1/admin").State())

	rec := httptest.NewRecorder()
	r.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/api/v1/admin/users", nil))

	assert.Equal(t, http.StatusServiceUnavailable, rec.Code)
	assert.Equal(t, "application/json", rec.Header().Get("Content-Type"))
	assert.JSONEq(t,
		`{"error":"service temporarily unavailable","service":"/api/v1/admin","reason":"circuit breaker open"}`,
		rec.Body.String())
}

func TestNewRouter_TracingEnabledStillProxies(t *testing.T) {
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("X-Backend-Path", r.URL.Path)
		_, _ = w.Write([]byte("traced"))
	}))
	defer backend.Close()

	r := NewRouter(newTestRouterConfig([]Route{{Prefix: "/api/v1/documents", TargetURL: backend.URL}}, true))

	rec := httptest.NewRecorder()
	r.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/api/v1/documents/42", nil))

	assert.Equal(t, http.StatusOK, rec.Code)
	assert.Equal(t, "/api/v1/documents/42", rec.Header().Get("X-Backend-Path"))
	assert.Equal(t, "traced", rec.Body.String())
}

func TestNewRouter_UnknownRouteReturnsJSON404(t *testing.T) {
	r := NewRouter(newTestRouterConfig(nil, false))

	rec := httptest.NewRecorder()
	r.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/nope", nil))

	assert.Equal(t, http.StatusNotFound, rec.Code)
	assert.Equal(t, "application/json", rec.Header().Get("Content-Type"))
	assert.JSONEq(t, `{"error":"route not found"}`, rec.Body.String())
}

func TestNewRouter_EachRouteGetsItsOwnCircuitBreaker(t *testing.T) {
	healthy := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		_, _ = w.Write([]byte("fine"))
	}))
	defer healthy.Close()
	broken := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusBadGateway)
	}))
	defer broken.Close()

	cfg := newTestRouterConfig([]Route{
		{Prefix: "/api/v1/auth", TargetURL: healthy.URL},
		{Prefix: "/api/v1/reports", TargetURL: broken.URL},
	}, false)
	r := NewRouter(cfg)

	for i := 0; i < 6; i++ {
		rec := httptest.NewRecorder()
		r.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/api/v1/reports/x", nil))
	}

	assert.Equal(t, StateOpen, cfg.CBManager.Get("/api/v1/reports").State())
	assert.Equal(t, StateClosed, cfg.CBManager.Get("/api/v1/auth").State())

	rec := httptest.NewRecorder()
	r.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/api/v1/auth/me", nil))
	assert.Equal(t, http.StatusOK, rec.Code)
	assert.Equal(t, "fine", rec.Body.String())
}
