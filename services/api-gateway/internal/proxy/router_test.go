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

func TestProxyOmitsEmailHeaderWhenClaimAbsent(t *testing.T) {
	var emailPresent bool
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, emailPresent = r.Header["X-User-Email"]
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
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	assert.Equal(t, http.StatusOK, rec.Code)
	assert.False(t, emailPresent)
}
