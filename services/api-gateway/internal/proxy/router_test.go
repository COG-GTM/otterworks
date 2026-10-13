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

func TestProxyPreservesHostPathAndForwardingHeaders(t *testing.T) {
	var got *http.Request
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		got = r.Clone(r.Context())
		w.WriteHeader(http.StatusOK)
	}))
	defer backend.Close()

	handler := newTestRouter(t, backend.URL)

	req := httptest.NewRequest(http.MethodGet, "/api/v1/files/list?page=2", nil)
	req.Host = "api.otterworks.test"
	req.RemoteAddr = "203.0.113.7:4321"
	req.Header.Set("Authorization", "Bearer "+signedToken(t, "user-123", ""))
	req.Header.Set("X-Forwarded-For", "198.51.100.1")
	req.Header.Set("X-Forwarded-Proto", "https")
	req.Header.Set("X-Forwarded-Host", "app.otterworks.test")
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	require.Equal(t, http.StatusOK, rec.Code)
	require.NotNil(t, got)
	assert.Equal(t, "api.otterworks.test", got.Host, "inbound Host must be preserved")
	assert.Equal(t, "/api/v1/files/list", got.URL.Path)
	assert.Equal(t, "page=2", got.URL.RawQuery)
	assert.Equal(t, "198.51.100.1, 203.0.113.7", got.Header.Get("X-Forwarded-For"))
	assert.Equal(t, "https", got.Header.Get("X-Forwarded-Proto"))
	assert.Equal(t, "app.otterworks.test", got.Header.Get("X-Forwarded-Host"))
}

func TestProxyIdentityHeadersSurviveConnectionHeaderStripping(t *testing.T) {
	var gotUserID string
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotUserID = r.Header.Get("X-User-ID")
		w.WriteHeader(http.StatusOK)
	}))
	defer backend.Close()

	handler := newTestRouter(t, backend.URL)

	req := httptest.NewRequest(http.MethodGet, "/api/v1/files/list", nil)
	req.Header.Set("Authorization", "Bearer "+signedToken(t, "user-123", ""))
	req.Header.Set("Connection", "X-User-ID")
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	assert.Equal(t, http.StatusOK, rec.Code)
	assert.Equal(t, "user-123", gotUserID)
}

func signedToken(t *testing.T, subject, email string) string {
	t.Helper()
	claims := middleware.JWTClaims{
		Email: email,
		RegisteredClaims: jwt.RegisteredClaims{
			ExpiresAt: jwt.NewNumericDate(time.Now().Add(time.Hour)),
			Subject:   subject,
		},
	}
	tokenStr, err := jwt.NewWithClaims(jwt.SigningMethodHS256, claims).SignedString([]byte(routerTestSecret))
	require.NoError(t, err)
	return tokenStr
}
