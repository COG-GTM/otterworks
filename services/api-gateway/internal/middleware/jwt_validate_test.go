package middleware

import (
	"crypto/rand"
	"crypto/rsa"
	"testing"
	"time"

	"github.com/golang-jwt/jwt/v5"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestValidateToken_ValidTokenReturnsClaims(t *testing.T) {
	claims := JWTClaims{
		UserID: "user-123",
		Email:  "test@otterworks.dev",
		Roles:  []string{"USER", "ADMIN"},
		RegisteredClaims: jwt.RegisteredClaims{
			Subject:   "11111111-1111-1111-1111-111111111111",
			ExpiresAt: jwt.NewNumericDate(time.Now().Add(time.Hour)),
			IssuedAt:  jwt.NewNumericDate(time.Now()),
		},
	}
	tokenStr := generateTestToken(t, testSecret, claims)

	got, err := validateToken(tokenStr, testSecret)

	require.NoError(t, err)
	assert.Equal(t, "11111111-1111-1111-1111-111111111111", got.Subject)
	assert.Equal(t, "user-123", got.UserID)
	assert.Equal(t, "test@otterworks.dev", got.Email)
	assert.Equal(t, []string{"USER", "ADMIN"}, got.Roles)
}

func TestValidateToken_AcceptsOtherHMACSizes(t *testing.T) {
	for _, method := range []*jwt.SigningMethodHMAC{jwt.SigningMethodHS384, jwt.SigningMethodHS512} {
		t.Run(method.Alg(), func(t *testing.T) {
			token := jwt.NewWithClaims(method, JWTClaims{
				RegisteredClaims: jwt.RegisteredClaims{
					Subject:   "user-123",
					ExpiresAt: jwt.NewNumericDate(time.Now().Add(time.Hour)),
				},
			})
			tokenStr, err := token.SignedString([]byte(testSecret))
			require.NoError(t, err)

			got, err := validateToken(tokenStr, testSecret)

			require.NoError(t, err)
			assert.Equal(t, "user-123", got.Subject)
		})
	}
}

func TestValidateToken_ExpiredToken(t *testing.T) {
	claims := JWTClaims{
		RegisteredClaims: jwt.RegisteredClaims{
			Subject:   "user-123",
			ExpiresAt: jwt.NewNumericDate(time.Now().Add(-time.Minute)),
			IssuedAt:  jwt.NewNumericDate(time.Now().Add(-time.Hour)),
		},
	}
	tokenStr := generateTestToken(t, testSecret, claims)

	_, err := validateToken(tokenStr, testSecret)

	require.Error(t, err)
	assert.ErrorIs(t, err, jwt.ErrTokenExpired)
}

func TestValidateToken_TokenWithoutExpiryIsAccepted(t *testing.T) {
	tokenStr := generateTestToken(t, testSecret, JWTClaims{
		RegisteredClaims: jwt.RegisteredClaims{Subject: "user-123"},
	})

	got, err := validateToken(tokenStr, testSecret)

	require.NoError(t, err)
	assert.Equal(t, "user-123", got.Subject)
}

func TestValidateToken_RejectsNonHMACSigningMethods(t *testing.T) {
	key, err := rsa.GenerateKey(rand.Reader, 2048)
	require.NoError(t, err)

	rsaToken := jwt.NewWithClaims(jwt.SigningMethodRS256, JWTClaims{
		RegisteredClaims: jwt.RegisteredClaims{
			Subject:   "attacker",
			ExpiresAt: jwt.NewNumericDate(time.Now().Add(time.Hour)),
		},
	})
	rsaTokenStr, err := rsaToken.SignedString(key)
	require.NoError(t, err)

	noneToken := jwt.NewWithClaims(jwt.SigningMethodNone, JWTClaims{
		RegisteredClaims: jwt.RegisteredClaims{
			Subject:   "attacker",
			ExpiresAt: jwt.NewNumericDate(time.Now().Add(time.Hour)),
		},
	})
	noneTokenStr, err := noneToken.SignedString(jwt.UnsafeAllowNoneSignatureType)
	require.NoError(t, err)

	for name, tokenStr := range map[string]string{"RS256": rsaTokenStr, "none": noneTokenStr} {
		t.Run(name, func(t *testing.T) {
			_, err := validateToken(tokenStr, testSecret)

			require.Error(t, err)
			assert.Contains(t, err.Error(), "unexpected signing method")
		})
	}
}

func TestValidateToken_RejectsInvalidSignature(t *testing.T) {
	claims := JWTClaims{
		RegisteredClaims: jwt.RegisteredClaims{
			Subject:   "user-123",
			ExpiresAt: jwt.NewNumericDate(time.Now().Add(time.Hour)),
		},
	}

	tests := map[string]string{
		"signed with another secret": generateTestToken(t, "some-other-secret", claims),
		"tampered signature":         generateTestToken(t, testSecret, claims) + "tampered",
		"malformed token":            "not-a-jwt",
		"empty token":                "",
	}

	for name, tokenStr := range tests {
		t.Run(name, func(t *testing.T) {
			_, err := validateToken(tokenStr, testSecret)
			require.Error(t, err)
		})
	}
}

func TestIsPublicPath(t *testing.T) {
	exact := map[string]bool{}
	for _, p := range DefaultPublicPaths() {
		exact[p] = true
	}
	prefixes := DefaultPrefixPaths()

	tests := map[string]bool{
		"/api/v1/auth/login":     true,
		"/api/v1/auth/register":  true,
		"/health":                true,
		"/health/ready":          true,
		"/metrics":               true,
		"/socket.io/connect":     true,
		"/api/v1/auth/refresh":   false,
		"/api/v1/auth/login/foo": false,
		"/healthcheck":           false,
		"/api/v1/documents":      false,
	}

	for path, want := range tests {
		t.Run(path, func(t *testing.T) {
			assert.Equal(t, want, isPublicPath(path, exact, prefixes))
		})
	}
}

func TestIsProtectedPath(t *testing.T) {
	assert.True(t, isProtectedPath("/anything", nil), "empty prefix list protects every path")

	prefixes := []string{"/api/v1/files", "/api/v1/documents"}
	tests := map[string]bool{
		"/api/v1/files":         true,
		"/api/v1/files/list":    true,
		"/api/v1/documents/1":   true,
		"/api/v1/filesystem":    false,
		"/api/v1/search":        false,
		"/internal/debug/pprof": false,
	}

	for path, want := range tests {
		t.Run(path, func(t *testing.T) {
			assert.Equal(t, want, isProtectedPath(path, prefixes))
		})
	}
}
