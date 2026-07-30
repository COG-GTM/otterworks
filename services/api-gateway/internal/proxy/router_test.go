package proxy

import (
	"encoding/json"
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

func newTestRouter(t *testing.T, cfg RouterConfig) http.Handler {
	t.Helper()
	if cfg.CBManager == nil {
		cfg.CBManager = NewCircuitBreakerManager(CircuitBreakerConfig{
			MaxRequests:  2,
			Interval:     time.Minute,
			Timeout:      time.Minute,
			FailureRatio: 0.5,
		})
	}
	cfg.Logger = zerolog.Nop()
	return NewRouter(cfg)
}

func TestNewRouter_ProxiesToBackendPreservingPath(t *testing.T) {
	var gotPath, gotMethod, gotUserID string
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotPath, gotMethod, gotUserID = r.URL.Path, r.Method, r.Header.Get("X-User-ID")
		w.Header().Set("X-Backend", "auth")
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("backend ok"))
	}))
	defer backend.Close()

	r := newTestRouter(t, RouterConfig{
		Routes: []Route{{Prefix: "/api/v1/auth", TargetURL: backend.URL}},
	})

	rec := httptest.NewRecorder()
	r.ServeHTTP(rec, httptest.NewRequest(http.MethodPost, "/api/v1/auth/login", nil))

	res := rec.Result()
	defer func() { _ = res.Body.Close() }()
	body, err := io.ReadAll(res.Body)
	require.NoError(t, err)

	assert.Equal(t, http.StatusOK, res.StatusCode)
	assert.Equal(t, "auth", res.Header.Get("X-Backend"))
	assert.Equal(t, "backend ok", string(body))
	assert.Equal(t, "/api/v1/auth/login", gotPath, "the full path survives the proxy hop")
	assert.Equal(t, http.MethodPost, gotMethod)
	assert.Empty(t, gotUserID, "no identity header without authenticated claims")
}

func TestNewRouter_ProxiesThePrefixRootItself(t *testing.T) {
	var gotPath string
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotPath = r.URL.Path
		w.WriteHeader(http.StatusNoContent)
	}))
	defer backend.Close()

	r := newTestRouter(t, RouterConfig{
		Routes: []Route{{Prefix: "/api/v1/files", TargetURL: backend.URL}},
	})

	rec := httptest.NewRecorder()
	r.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/api/v1/files", nil))

	assert.Equal(t, http.StatusNoContent, rec.Code)
	assert.Equal(t, "/api/v1/files", gotPath)
}

func TestNewRouter_MultipleRoutesAreIndependent(t *testing.T) {
	auth := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte("auth"))
	}))
	defer auth.Close()
	files := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte("files"))
	}))
	defer files.Close()

	r := newTestRouter(t, RouterConfig{Routes: []Route{
		{Prefix: "/api/v1/auth", TargetURL: auth.URL},
		{Prefix: "/api/v1/files", TargetURL: files.URL},
	}})

	for path, want := range map[string]string{
		"/api/v1/auth/login":  "auth",
		"/api/v1/files/1":     "files",
		"/api/v1/files/a/b/c": "files",
	} {
		rec := httptest.NewRecorder()
		r.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, path, nil))
		assert.Equal(t, want, rec.Body.String(), "path %s", path)
	}
}

func TestNewRouter_UnknownRouteReturnsJSON404(t *testing.T) {
	r := newTestRouter(t, RouterConfig{})

	rec := httptest.NewRecorder()
	r.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/nope", nil))

	assert.Equal(t, http.StatusNotFound, rec.Code)
	assert.Equal(t, "application/json", rec.Header().Get("Content-Type"))
	assert.JSONEq(t, `{"error":"route not found"}`, rec.Body.String())
}

func TestNewRouter_UnreachableBackendReturns502(t *testing.T) {
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {}))
	target := backend.URL
	backend.Close() // nothing is listening on target any more

	r := newTestRouter(t, RouterConfig{
		Routes: []Route{{Prefix: "/api/v1/search", TargetURL: target}},
	})

	rec := httptest.NewRecorder()
	r.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/api/v1/search/q", nil))

	assert.Equal(t, http.StatusBadGateway, rec.Code)
	assert.Equal(t, "application/json", rec.Header().Get("Content-Type"))
	var body map[string]string
	require.NoError(t, json.Unmarshal(rec.Body.Bytes(), &body))
	assert.Equal(t, "service unavailable", body["error"])
	assert.Equal(t, "/api/v1/search", body["target"])
}

func TestNewRouter_OpenCircuitBreakerReturns503(t *testing.T) {
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusInternalServerError)
	}))
	defer backend.Close()

	cbm := NewCircuitBreakerManager(CircuitBreakerConfig{
		MaxRequests:  1,
		Interval:     time.Minute,
		Timeout:      time.Minute,
		FailureRatio: 0.5,
	})
	r := newTestRouter(t, RouterConfig{
		Routes:    []Route{{Prefix: "/api/v1/documents", TargetURL: backend.URL}},
		CBManager: cbm,
	})

	// shouldTrip needs a minimum sample of 5 requests before it opens.
	for i := 0; i < 5; i++ {
		rec := httptest.NewRecorder()
		r.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/api/v1/documents/1", nil))
		require.Equal(t, http.StatusInternalServerError, rec.Code, "request %d reaches the backend", i+1)
	}
	require.Equal(t, StateOpen, cbm.Get("/api/v1/documents").State())

	rec := httptest.NewRecorder()
	r.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/api/v1/documents/1", nil))

	assert.Equal(t, http.StatusServiceUnavailable, rec.Code)
	assert.Equal(t, "application/json", rec.Header().Get("Content-Type"))
	var body map[string]string
	require.NoError(t, json.Unmarshal(rec.Body.Bytes(), &body))
	assert.Equal(t, "service temporarily unavailable", body["error"])
	assert.Equal(t, "/api/v1/documents", body["service"])
	assert.Equal(t, "circuit breaker open", body["reason"])
}

func TestNewRouter_TracingWrapperStillProxies(t *testing.T) {
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte("traced"))
	}))
	defer backend.Close()

	r := newTestRouter(t, RouterConfig{
		Routes:        []Route{{Prefix: "/api/v1/analytics", TargetURL: backend.URL}},
		EnableTracing: true,
	})

	rec := httptest.NewRecorder()
	r.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/api/v1/analytics/events", nil))

	assert.Equal(t, http.StatusOK, rec.Code)
	assert.Equal(t, "traced", rec.Body.String())
}

// signToken issues an HS256 token the JWT middleware will accept.
func signToken(t *testing.T, secret string, claims middleware.JWTClaims) string {
	t.Helper()
	signed, err := jwt.NewWithClaims(jwt.SigningMethodHS256, &claims).SignedString([]byte(secret))
	require.NoError(t, err)
	return signed
}

func TestNewRouter_ForwardsAuthenticatedIdentity(t *testing.T) {
	const secret = "s3cret"

	tests := []struct {
		name   string
		claims middleware.JWTClaims
		want   string
	}{
		{
			name:   "prefers the standard subject claim",
			claims: middleware.JWTClaims{UserID: "legacy-id", RegisteredClaims: jwt.RegisteredClaims{Subject: "user-42"}},
			want:   "user-42",
		},
		{
			name:   "falls back to the custom user_id claim",
			claims: middleware.JWTClaims{UserID: "legacy-id"},
			want:   "legacy-id",
		},
		{
			name:   "sends no header when the token carries no identity",
			claims: middleware.JWTClaims{},
			want:   "",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			var gotUserID string
			backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				gotUserID = r.Header.Get("X-User-ID")
			}))
			defer backend.Close()

			router := newTestRouter(t, RouterConfig{
				Routes: []Route{{Prefix: "/api/v1/files", TargetURL: backend.URL}},
			})
			handler := middleware.JWTAuth(middleware.JWTConfig{
				Secret:              secret,
				ProtectedPrefixPath: []string{"/api/v1/files"},
			})(router)

			req := httptest.NewRequest(http.MethodGet, "/api/v1/files/1", nil)
			req.Header.Set("Authorization", "Bearer "+signToken(t, secret, tt.claims))
			rec := httptest.NewRecorder()
			handler.ServeHTTP(rec, req)

			require.Equal(t, http.StatusOK, rec.Code)
			assert.Equal(t, tt.want, gotUserID)
		})
	}
}
