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

func signedRouterToken(t *testing.T, claims middleware.JWTClaims) string {
	t.Helper()
	tokenStr, err := jwt.NewWithClaims(jwt.SigningMethodHS256, claims).SignedString([]byte(routerTestSecret))
	require.NoError(t, err)
	return tokenStr
}

func TestProxyIdentityHeadersSurviveConnectionHopByHopRemoval(t *testing.T) {
	var gotUserID, gotEmail, gotToken string
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotUserID = r.Header.Get("X-User-ID")
		gotEmail = r.Header.Get("X-User-Email")
		gotToken = r.Header.Get(InternalServiceTokenHeader)
		w.WriteHeader(http.StatusOK)
	}))
	defer backend.Close()

	handler := newTestRouter(t, backend.URL)
	tokenStr := signedRouterToken(t, middleware.JWTClaims{
		Email: "attacker@otterworks.dev",
		RegisteredClaims: jwt.RegisteredClaims{
			ExpiresAt: jwt.NewNumericDate(time.Now().Add(time.Hour)),
			Subject:   "user-123",
		},
	})

	for _, conn := range []string{"X-User-ID", "x-user-id, X-User-Email", "keep-alive, X-User-Email, X-User-ID"} {
		gotUserID, gotEmail, gotToken = "", "", ""
		req := httptest.NewRequest(http.MethodGet, "/api/v1/files/list?owner_id=victim", nil)
		req.Header.Set("Authorization", "Bearer "+tokenStr)
		req.Header.Set("Connection", conn)
		req.Header.Set(InternalServiceTokenHeader, "guessed")
		rec := httptest.NewRecorder()
		handler.ServeHTTP(rec, req)

		assert.Equal(t, http.StatusOK, rec.Code, conn)
		assert.Equal(t, "user-123", gotUserID, "Connection: %q must not strip X-User-ID", conn)
		assert.Equal(t, "attacker@otterworks.dev", gotEmail, "Connection: %q must not strip X-User-Email", conn)
		assert.Empty(t, gotToken, "client-supplied internal service token must not reach the backend")
	}
}

func TestProxyPreservesPathQueryHostAndForwardedFor(t *testing.T) {
	var gotPath, gotQuery, gotHost, gotXFF, gotProto string
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotPath = r.URL.Path
		gotQuery = r.URL.RawQuery
		gotHost = r.Host
		gotXFF = r.Header.Get("X-Forwarded-For")
		gotProto = r.Header.Get("X-Forwarded-Proto")
		w.WriteHeader(http.StatusOK)
	}))
	defer backend.Close()

	handler := newTestRouter(t, backend.URL)
	tokenStr := signedRouterToken(t, middleware.JWTClaims{
		RegisteredClaims: jwt.RegisteredClaims{
			ExpiresAt: jwt.NewNumericDate(time.Now().Add(time.Hour)),
			Subject:   "user-123",
		},
	})

	req := httptest.NewRequest(http.MethodGet, "http://api.otterworks.test/api/v1/files/abc?page=2", nil)
	req.RemoteAddr = "203.0.113.7:4321"
	req.Header.Set("Authorization", "Bearer "+tokenStr)
	req.Header.Set("X-Forwarded-For", "198.51.100.1")
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	assert.Equal(t, http.StatusOK, rec.Code)
	assert.Equal(t, "/api/v1/files/abc", gotPath)
	assert.Equal(t, "page=2", gotQuery)
	assert.Equal(t, "api.otterworks.test", gotHost)
	assert.Equal(t, "198.51.100.1, 203.0.113.7", gotXFF)
	assert.Equal(t, "http", gotProto)
}

func TestProxyKeepsInboundForwardedProtoAndHost(t *testing.T) {
	var gotProto, gotHost string
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotProto = r.Header.Get("X-Forwarded-Proto")
		gotHost = r.Header.Get("X-Forwarded-Host")
		w.WriteHeader(http.StatusOK)
	}))
	defer backend.Close()

	handler := newTestRouter(t, backend.URL)
	tokenStr := signedRouterToken(t, middleware.JWTClaims{
		RegisteredClaims: jwt.RegisteredClaims{
			ExpiresAt: jwt.NewNumericDate(time.Now().Add(time.Hour)),
			Subject:   "user-123",
		},
	})

	req := httptest.NewRequest(http.MethodGet, "/api/v1/files/abc", nil)
	req.Header.Set("Authorization", "Bearer "+tokenStr)
	req.Header.Set("X-Forwarded-Proto", "https")
	req.Header.Set("X-Forwarded-Host", "app.otterworks.dev")
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	assert.Equal(t, http.StatusOK, rec.Code)
	assert.Equal(t, "https", gotProto)
	assert.Equal(t, "app.otterworks.dev", gotHost)
}
