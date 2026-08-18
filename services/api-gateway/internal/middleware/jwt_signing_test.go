package middleware

import (
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/golang-jwt/jwt/v5"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestValidateToken_RejectsNonHMACSigningMethod(t *testing.T) {
	// "alg: none" is the classic JWT downgrade attack: the token parses, but
	// the key function must refuse anything that is not HMAC.
	token, err := jwt.NewWithClaims(jwt.SigningMethodNone, &JWTClaims{
		UserID:           "attacker",
		RegisteredClaims: jwt.RegisteredClaims{ExpiresAt: jwt.NewNumericDate(time.Now().Add(time.Hour))},
	}).SignedString(jwt.UnsafeAllowNoneSignatureType)
	require.NoError(t, err)

	claims, err := validateToken(token, "test-secret")

	require.Error(t, err)
	assert.Contains(t, err.Error(), "unexpected signing method")
	assert.Nil(t, claims)
}

func TestJWTAuth_RejectsNonHMACSignedToken(t *testing.T) {
	token, err := jwt.NewWithClaims(jwt.SigningMethodNone, &JWTClaims{
		UserID:           "attacker",
		RegisteredClaims: jwt.RegisteredClaims{ExpiresAt: jwt.NewNumericDate(time.Now().Add(time.Hour))},
	}).SignedString(jwt.UnsafeAllowNoneSignatureType)
	require.NoError(t, err)

	called := false
	handler := JWTAuth(JWTConfig{Secret: "test-secret"})(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		called = true
	}))

	req := httptest.NewRequest(http.MethodGet, "/api/v1/files", nil)
	req.Header.Set("Authorization", "Bearer "+token)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	assert.False(t, called, "the downstream handler must never see an unsigned token")
	assert.Equal(t, http.StatusUnauthorized, rec.Code)
	assert.Contains(t, rec.Body.String(), "unexpected signing method")
}

func TestValidateToken_AcceptsHMACTokenWithoutExpiry(t *testing.T) {
	token, err := jwt.NewWithClaims(jwt.SigningMethodHS256, &JWTClaims{
		UserID: "user-1",
		Email:  "user@example.test",
		Roles:  []string{"admin"},
	}).SignedString([]byte("test-secret"))
	require.NoError(t, err)

	claims, err := validateToken(token, "test-secret")

	require.NoError(t, err)
	require.NotNil(t, claims)
	assert.Equal(t, "user-1", claims.UserID)
	assert.Equal(t, "user@example.test", claims.Email)
	assert.Equal(t, []string{"admin"}, claims.Roles)
	assert.Nil(t, claims.ExpiresAt)
}

func TestIsProtectedPath(t *testing.T) {
	tests := []struct {
		name     string
		path     string
		prefixes []string
		want     bool
	}{
		{name: "no configured prefixes protects everything", path: "/anything", want: true},
		{name: "exact prefix match", path: "/api/v1/files", prefixes: []string{"/api/v1/files"}, want: true},
		{name: "sub-path of prefix", path: "/api/v1/files/1", prefixes: []string{"/api/v1/files"}, want: true},
		{name: "prefix must end at a segment boundary", path: "/api/v1/filesystem", prefixes: []string{"/api/v1/files"}, want: false},
		{name: "unrelated path", path: "/other", prefixes: []string{"/api/v1/files"}, want: false},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			assert.Equal(t, tt.want, isProtectedPath(tt.path, tt.prefixes))
		})
	}
}

func TestIsPublicPath(t *testing.T) {
	exact := map[string]bool{"/api/v1/auth/login": true}
	prefixes := []string{"/health", "/metrics"}

	tests := []struct {
		name string
		path string
		want bool
	}{
		{name: "exact public path", path: "/api/v1/auth/login", want: true},
		{name: "sub-path of an exact public path is not public", path: "/api/v1/auth/login/extra", want: false},
		{name: "prefix path itself", path: "/health", want: true},
		{name: "sub-path of a prefix path", path: "/health/ready", want: true},
		{name: "prefix must end at a segment boundary", path: "/healthz", want: false},
		{name: "unknown path", path: "/api/v1/files", want: false},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			assert.Equal(t, tt.want, isPublicPath(tt.path, exact, prefixes))
		})
	}
}

func TestDefaultPathSets(t *testing.T) {
	assert.Equal(t, []string{"/api/v1/auth/login", "/api/v1/auth/register"}, DefaultPublicPaths())
	assert.Equal(t, []string{"/health", "/metrics", "/socket.io"}, DefaultPrefixPaths())
}
