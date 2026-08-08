package middleware

import (
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/golang-jwt/jwt/v5"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

// A token signed with a non-HMAC algorithm must be rejected by the keyfunc
// rather than accepted: this is the "alg=none" downgrade attack.
func TestValidateToken_RejectsNonHMACSigningMethod(t *testing.T) {
	token := jwt.NewWithClaims(jwt.SigningMethodNone, &JWTClaims{UserID: "u-1"})
	signed, err := token.SignedString(jwt.UnsafeAllowNoneSignatureType)
	require.NoError(t, err)

	claims, err := validateToken(signed, "s3cret")

	require.Error(t, err)
	assert.Nil(t, claims)
	assert.Contains(t, err.Error(), "unexpected signing method")
}

func TestJWTAuth_RejectsNonHMACSigningMethod(t *testing.T) {
	token := jwt.NewWithClaims(jwt.SigningMethodNone, &JWTClaims{UserID: "u-1"})
	signed, err := token.SignedString(jwt.UnsafeAllowNoneSignatureType)
	require.NoError(t, err)

	handler := JWTAuth(JWTConfig{Secret: "s3cret"})(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		t.Fatal("handler must not be reached")
	}))

	req := httptest.NewRequest(http.MethodGet, "/api/v1/files", nil)
	req.Header.Set("Authorization", "Bearer "+signed)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	assert.Equal(t, http.StatusUnauthorized, rec.Code)
	assert.Equal(t, "application/json", rec.Header().Get("Content-Type"))
	assert.Contains(t, rec.Body.String(), "unexpected signing method")
}

func TestDefaultPublicAndPrefixPaths(t *testing.T) {
	assert.Equal(t, []string{"/api/v1/auth/login", "/api/v1/auth/register"}, DefaultPublicPaths())
	assert.Equal(t, []string{"/health", "/metrics", "/socket.io"}, DefaultPrefixPaths())
}

func TestIsPublicPath(t *testing.T) {
	exact := map[string]bool{"/api/v1/auth/login": true}
	prefixes := DefaultPrefixPaths()

	tests := []struct {
		path string
		want bool
	}{
		{path: "/api/v1/auth/login", want: true},
		{path: "/health", want: true},
		{path: "/health/live", want: true},
		{path: "/metrics", want: true},
		{path: "/socket.io", want: true},
		{path: "/socket.io/abc", want: true},
		{path: "/socket.iox", want: false},
		{path: "/healthz", want: false},
		{path: "/api/v1/auth/logins", want: false},
		{path: "/api/v1/files", want: false},
	}

	for _, tt := range tests {
		t.Run(tt.path, func(t *testing.T) {
			assert.Equal(t, tt.want, isPublicPath(tt.path, exact, prefixes))
		})
	}
}

func TestIsProtectedPath(t *testing.T) {
	t.Run("no prefixes protects everything", func(t *testing.T) {
		assert.True(t, isProtectedPath("/anything", nil))
	})

	protected := []string{"/api/v1/files", "/api/v1/admin"}
	tests := []struct {
		path string
		want bool
	}{
		{path: "/api/v1/files", want: true},
		{path: "/api/v1/files/1", want: true},
		{path: "/api/v1/admin/users", want: true},
		{path: "/api/v1/filesystem", want: false},
		{path: "/public", want: false},
	}

	for _, tt := range tests {
		t.Run(tt.path, func(t *testing.T) {
			assert.Equal(t, tt.want, isProtectedPath(tt.path, protected))
		})
	}
}
