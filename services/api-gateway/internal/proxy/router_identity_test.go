package proxy

import (
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

type capturedIdentity struct {
	userID      string
	email       string
	userIDSet   bool
	emailSet    bool
	authHeader  string
	requestPath string
}

// newIdentityBackend records the identity headers the gateway forwarded.
func newIdentityBackend(t *testing.T, got *capturedIdentity) *httptest.Server {
	t.Helper()
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		got.userID = r.Header.Get("X-User-ID")
		got.email = r.Header.Get("X-User-Email")
		_, got.userIDSet = r.Header["X-User-Id"]
		_, got.emailSet = r.Header["X-User-Email"]
		got.authHeader = r.Header.Get("Authorization")
		got.requestPath = r.URL.Path
		w.WriteHeader(http.StatusOK)
	}))
	t.Cleanup(backend.Close)
	return backend
}

// newIdentityRouter mounts both a protected and a public route behind the gateway's
// JWT middleware, mirroring how main.go wires the proxy.
func newIdentityRouter(t *testing.T, backendURL string) http.Handler {
	t.Helper()
	router := NewRouter(RouterConfig{
		Routes: []Route{
			{Prefix: "/api/v1/files", TargetURL: backendURL},
			{Prefix: "/api/v1/auth", TargetURL: backendURL},
		},
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

func signIdentityToken(t *testing.T, claims middleware.JWTClaims) string {
	t.Helper()
	token := jwt.NewWithClaims(jwt.SigningMethodHS256, claims)
	tokenStr, err := token.SignedString([]byte(routerTestSecret))
	require.NoError(t, err)
	return tokenStr
}

func TestProxyReplacesSpoofedIdentityWithJWTClaims(t *testing.T) {
	var got capturedIdentity
	backend := newIdentityBackend(t, &got)
	handler := newIdentityRouter(t, backend.URL)

	token := signIdentityToken(t, middleware.JWTClaims{
		Email: "owner@otterworks.dev",
		RegisteredClaims: jwt.RegisteredClaims{
			Subject:   "owner-id",
			ExpiresAt: jwt.NewNumericDate(time.Now().Add(time.Hour)),
		},
	})

	req := httptest.NewRequest(http.MethodGet, "/api/v1/files/list", nil)
	req.Header.Set("Authorization", "Bearer "+token)
	req.Header.Set("X-User-ID", "victim-id")
	req.Header.Set("X-User-Email", "victim@otterworks.dev")
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	assert.Equal(t, http.StatusOK, rec.Code)
	assert.Equal(t, "owner-id", got.userID)
	assert.Equal(t, "owner@otterworks.dev", got.email)
}

func TestProxyPrefersSubjectOverUserIDClaim(t *testing.T) {
	var got capturedIdentity
	backend := newIdentityBackend(t, &got)
	handler := newIdentityRouter(t, backend.URL)

	token := signIdentityToken(t, middleware.JWTClaims{
		UserID: "legacy-claim-id",
		RegisteredClaims: jwt.RegisteredClaims{
			Subject:   "subject-id",
			ExpiresAt: jwt.NewNumericDate(time.Now().Add(time.Hour)),
		},
	})

	req := httptest.NewRequest(http.MethodGet, "/api/v1/files/list", nil)
	req.Header.Set("Authorization", "Bearer "+token)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	assert.Equal(t, http.StatusOK, rec.Code)
	assert.Equal(t, "subject-id", got.userID)
}

func TestProxyFallsBackToUserIDClaimWhenSubjectEmpty(t *testing.T) {
	var got capturedIdentity
	backend := newIdentityBackend(t, &got)
	handler := newIdentityRouter(t, backend.URL)

	token := signIdentityToken(t, middleware.JWTClaims{
		UserID: "legacy-claim-id",
		RegisteredClaims: jwt.RegisteredClaims{
			ExpiresAt: jwt.NewNumericDate(time.Now().Add(time.Hour)),
		},
	})

	req := httptest.NewRequest(http.MethodGet, "/api/v1/files/list", nil)
	req.Header.Set("Authorization", "Bearer "+token)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	assert.Equal(t, http.StatusOK, rec.Code)
	assert.Equal(t, "legacy-claim-id", got.userID)
}

func TestProxyStripsIdentityHeadersOnPublicPaths(t *testing.T) {
	var got capturedIdentity
	backend := newIdentityBackend(t, &got)
	handler := newIdentityRouter(t, backend.URL)

	req := httptest.NewRequest(http.MethodPost, "/api/v1/auth/login", nil)
	req.Header.Set("X-User-ID", "victim-id")
	req.Header.Set("X-User-Email", "victim@otterworks.dev")
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	assert.Equal(t, http.StatusOK, rec.Code)
	assert.False(t, got.userIDSet, "unauthenticated caller must not inject X-User-ID")
	assert.False(t, got.emailSet, "unauthenticated caller must not inject X-User-Email")
	assert.Equal(t, "/api/v1/auth/login", got.requestPath)
}

func TestProxyForwardsAuthorizationHeaderToBackend(t *testing.T) {
	var got capturedIdentity
	backend := newIdentityBackend(t, &got)
	handler := newIdentityRouter(t, backend.URL)

	token := signIdentityToken(t, middleware.JWTClaims{
		RegisteredClaims: jwt.RegisteredClaims{
			Subject:   "owner-id",
			ExpiresAt: jwt.NewNumericDate(time.Now().Add(time.Hour)),
		},
	})

	req := httptest.NewRequest(http.MethodGet, "/api/v1/files/list", nil)
	req.Header.Set("Authorization", "Bearer "+token)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	assert.Equal(t, http.StatusOK, rec.Code)
	assert.Equal(t, "Bearer "+token, got.authHeader,
		"backends that decode the JWT themselves still need the original token")
}

func TestProxyRejectsExpiredTokenBeforeReachingBackend(t *testing.T) {
	reached := false
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		reached = true
		w.WriteHeader(http.StatusOK)
	}))
	defer backend.Close()

	handler := newIdentityRouter(t, backend.URL)

	token := signIdentityToken(t, middleware.JWTClaims{
		RegisteredClaims: jwt.RegisteredClaims{
			Subject:   "owner-id",
			ExpiresAt: jwt.NewNumericDate(time.Now().Add(-time.Hour)),
		},
	})

	req := httptest.NewRequest(http.MethodGet, "/api/v1/files/list", nil)
	req.Header.Set("Authorization", "Bearer "+token)
	req.Header.Set("X-User-ID", "victim-id")
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	assert.Equal(t, http.StatusUnauthorized, rec.Code)
	assert.False(t, reached, "request must not be proxied when the token is rejected")
}
