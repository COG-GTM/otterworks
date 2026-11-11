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

func signedTestToken(t *testing.T, claims middleware.JWTClaims) string {
	t.Helper()
	claims.ExpiresAt = jwt.NewNumericDate(time.Now().Add(time.Hour))
	tokenStr, err := jwt.NewWithClaims(jwt.SigningMethodHS256, claims).SignedString([]byte(routerTestSecret))
	require.NoError(t, err)
	return tokenStr
}

func TestProxyIdentityHeadersSurviveConnectionHeaderStripping(t *testing.T) {
	var gotUserID, gotEmail string
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotUserID = r.Header.Get("X-User-ID")
		gotEmail = r.Header.Get("X-User-Email")
		w.WriteHeader(http.StatusOK)
	}))
	defer backend.Close()

	handler := newTestRouter(t, backend.URL)
	tokenStr := signedTestToken(t, middleware.JWTClaims{
		Email:            "test@otterworks.dev",
		RegisteredClaims: jwt.RegisteredClaims{Subject: "user-123"},
	})

	req := httptest.NewRequest(http.MethodGet, "/api/v1/files/list?owner_id=victim", nil)
	req.Header.Set("Authorization", "Bearer "+tokenStr)
	req.Header.Set("Connection", "X-User-ID, X-User-Email")
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	assert.Equal(t, http.StatusOK, rec.Code)
	assert.Equal(t, "user-123", gotUserID, "a client Connection header must not strip X-User-ID")
	assert.Equal(t, "test@otterworks.dev", gotEmail, "a client Connection header must not strip X-User-Email")
}

func TestProxyPreservesHostAndForwardingHeaders(t *testing.T) {
	var gotHost, gotXFF, gotXFProto, gotXFHost, gotPath, gotQuery string
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotHost = r.Host
		gotXFF = r.Header.Get("X-Forwarded-For")
		gotXFProto = r.Header.Get("X-Forwarded-Proto")
		gotXFHost = r.Header.Get("X-Forwarded-Host")
		gotPath = r.URL.Path
		gotQuery = r.URL.RawQuery
		w.WriteHeader(http.StatusOK)
	}))
	defer backend.Close()

	handler := newTestRouter(t, backend.URL)
	tokenStr := signedTestToken(t, middleware.JWTClaims{
		RegisteredClaims: jwt.RegisteredClaims{Subject: "user-123"},
	})

	req := httptest.NewRequest(http.MethodGet, "http://api.otterworks.test/api/v1/files/list?q=red;blue&page=2", nil)
	req.RemoteAddr = "10.0.0.7:5555"
	req.Header.Set("Authorization", "Bearer "+tokenStr)
	req.Header.Set("X-Forwarded-For", "203.0.113.9")
	req.Header.Set("X-Forwarded-Proto", "https")
	req.Header.Set("X-Forwarded-Host", "app.otterworks.test")
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	assert.Equal(t, http.StatusOK, rec.Code)
	assert.Equal(t, "api.otterworks.test", gotHost)
	assert.Equal(t, "203.0.113.9, 10.0.0.7", gotXFF)
	assert.Equal(t, "https", gotXFProto)
	assert.Equal(t, "app.otterworks.test", gotXFHost)
	assert.Equal(t, "/api/v1/files/list", gotPath)
	assert.Equal(t, "q=red;blue&page=2", gotQuery, "query must be forwarded verbatim")
}
