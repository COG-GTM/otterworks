package middleware

import (
	"crypto/rand"
	"crypto/rsa"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/golang-jwt/jwt/v5"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func protectedHandler(t *testing.T) http.Handler {
	t.Helper()
	return JWTAuth(JWTConfig{Secret: testSecret})(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		t.Error("handler must not be reached")
	}))
}

func assertRejected(t *testing.T, token, wantSubstr string) {
	t.Helper()
	req := httptest.NewRequest(http.MethodGet, "/api/v1/files", nil)
	req.Header.Set("Authorization", "Bearer "+token)
	rec := httptest.NewRecorder()
	protectedHandler(t).ServeHTTP(rec, req)
	assert.Equal(t, http.StatusUnauthorized, rec.Code)
	assert.Contains(t, rec.Body.String(), wantSubstr)
}

func validClaims() JWTClaims {
	return JWTClaims{
		UserID: "u1",
		RegisteredClaims: jwt.RegisteredClaims{
			Subject:   "u1",
			ExpiresAt: jwt.NewNumericDate(time.Now().Add(time.Hour)),
		},
	}
}

func TestJWTAuth_RejectsNoneAlgorithm(t *testing.T) {
	tok, err := jwt.NewWithClaims(jwt.SigningMethodNone, validClaims()).SignedString(jwt.UnsafeAllowNoneSignatureType)
	require.NoError(t, err)
	assertRejected(t, tok, "unexpected signing method: none")
}

func TestJWTAuth_RejectsRS256(t *testing.T) {
	key, err := rsa.GenerateKey(rand.Reader, 2048)
	require.NoError(t, err)
	tok, err := jwt.NewWithClaims(jwt.SigningMethodRS256, validClaims()).SignedString(key)
	require.NoError(t, err)
	assertRejected(t, tok, "unexpected signing method: RS256")
}

func TestJWTAuth_RejectsNotYetValid(t *testing.T) {
	c := validClaims()
	c.NotBefore = jwt.NewNumericDate(time.Now().Add(time.Hour))
	assertRejected(t, generateTestToken(t, testSecret, c), "not valid yet")
}

func TestValidateToken_ExpiredViaLibrary(t *testing.T) {
	c := validClaims()
	c.ExpiresAt = jwt.NewNumericDate(time.Now().Add(-time.Minute))
	_, err := validateToken(generateTestToken(t, testSecret, c), testSecret)
	require.Error(t, err)
	assert.ErrorIs(t, err, jwt.ErrTokenExpired)
}

func TestValidateToken_AcceptsTokenWithoutExpiry(t *testing.T) {
	c := validClaims()
	c.ExpiresAt = nil
	claims, err := validateToken(generateTestToken(t, testSecret, c), testSecret)
	require.NoError(t, err)
	assert.Equal(t, "u1", claims.Subject)
}
