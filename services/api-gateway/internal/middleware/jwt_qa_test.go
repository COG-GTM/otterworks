package middleware

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/golang-jwt/jwt/v5"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

// gatewayJWTConfig mirrors the JWT wiring in cmd/server/main.go.
func gatewayJWTConfig() JWTConfig {
	return JWTConfig{
		Secret:     testSecret,
		PublicPath: DefaultPublicPaths(),
		PrefixPath: DefaultPrefixPaths(),
		ProtectedPrefixPath: []string{
			"/api/v1/auth", "/api/v1/files", "/api/v1/folders", "/api/v1/documents",
			"/api/v1/templates", "/api/v1/collab", "/socket.io", "/api/v1/notifications",
			"/api/v1/preferences", "/api/v1/search", "/api/v1/analytics", "/api/v1/admin",
			"/api/v1/audit", "/api/v1/reports", "/api/v1/settings",
		},
	}
}

func serveJWT(t *testing.T, cfg JWTConfig, path, authHeader string) (*httptest.ResponseRecorder, *JWTClaims) {
	t.Helper()
	var seen *JWTClaims
	h := JWTAuth(cfg)(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		seen = GetJWTClaims(r.Context())
		w.WriteHeader(http.StatusOK)
	}))
	req := httptest.NewRequest(http.MethodGet, path, nil)
	if authHeader != "" {
		req.Header.Set("Authorization", authHeader)
	}
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	return rec, seen
}

func signWith(t *testing.T, method jwt.SigningMethod, key interface{}, claims jwt.Claims) string {
	t.Helper()
	s, err := jwt.NewWithClaims(method, claims).SignedString(key)
	require.NoError(t, err)
	return s
}

func validClaims() JWTClaims {
	return JWTClaims{
		Email: "qa@otterworks.test",
		Roles: []string{"USER"},
		RegisteredClaims: jwt.RegisteredClaims{
			Subject:   "8b0f6c1e-0000-4000-8000-000000000001",
			ExpiresAt: jwt.NewNumericDate(time.Now().Add(time.Hour)),
			IssuedAt:  jwt.NewNumericDate(time.Now()),
		},
	}
}

func TestQAJWT_EveryRoutedPrefixRequiresToken(t *testing.T) {
	cfg := gatewayJWTConfig()
	for _, prefix := range cfg.ProtectedPrefixPath {
		if prefix == "/socket.io" {
			continue // public prefix; collab-service authenticates the socket handshake itself
		}
		for _, path := range []string{prefix, prefix + "/", prefix + "/some/id"} {
			rec, _ := serveJWT(t, cfg, path, "")
			assert.Equal(t, http.StatusUnauthorized, rec.Code, "%s must require a token", path)
			assert.Contains(t, rec.Header().Get("Content-Type"), "application/json")
			assert.Contains(t, rec.Body.String(), `"error"`)
		}
	}
}

func TestQAJWT_PublicExactPathsDoNotMatchVariants(t *testing.T) {
	cfg := gatewayJWTConfig()
	for _, path := range []string{"/api/v1/auth/login/", "/api/v1/auth/loginx", "/api/v1/auth/register/extra", "/api/v1/auth/LOGIN"} {
		rec, _ := serveJWT(t, cfg, path, "")
		assert.Equal(t, http.StatusUnauthorized, rec.Code, "%s must not be treated as public", path)
	}
}

func TestQAJWT_OperationalPrefixesHonourSegmentBoundary(t *testing.T) {
	cfg := gatewayJWTConfig()
	for _, path := range []string{"/health", "/health/live", "/metrics", "/socket.io/", "/socket.io/?EIO=4"} {
		rec, _ := serveJWT(t, cfg, path, "")
		assert.Equal(t, http.StatusOK, rec.Code, "%s should be public", path)
	}
	// Prefix match must stop at a path segment: /api/v1/healthcheck is not /health.
	assert.False(t, isPublicPath("/healthz", map[string]bool{}, DefaultPrefixPaths()))
	assert.False(t, isPublicPath("/metricsfoo", map[string]bool{}, DefaultPrefixPaths()))
}

func TestQAJWT_UnroutedPathsPassThroughToNotFound(t *testing.T) {
	rec, _ := serveJWT(t, gatewayJWTConfig(), "/api/v2/files", "")
	assert.Equal(t, http.StatusOK, rec.Code, "non-routed paths are left to the router's 404")
}

func TestQAJWT_ValidTokenPutsClaimsInContext(t *testing.T) {
	tok := generateTestToken(t, testSecret, validClaims())
	rec, claims := serveJWT(t, gatewayJWTConfig(), "/api/v1/files/abc", "Bearer "+tok)
	require.Equal(t, http.StatusOK, rec.Code)
	require.NotNil(t, claims)
	assert.Equal(t, "8b0f6c1e-0000-4000-8000-000000000001", claims.Subject)
	assert.Equal(t, "qa@otterworks.test", claims.Email)
	assert.Equal(t, []string{"USER"}, claims.Roles)
}

func TestQAJWT_SchemeIsCaseInsensitive(t *testing.T) {
	tok := generateTestToken(t, testSecret, validClaims())
	for _, scheme := range []string{"Bearer", "bearer", "BEARER"} {
		rec, _ := serveJWT(t, gatewayJWTConfig(), "/api/v1/documents", scheme+" "+tok)
		assert.Equal(t, http.StatusOK, rec.Code, scheme)
	}
}

func TestQAJWT_RejectsBadCredentials(t *testing.T) {
	expired := validClaims()
	expired.ExpiresAt = jwt.NewNumericDate(time.Now().Add(-time.Minute))
	notYet := validClaims()
	notYet.NotBefore = jwt.NewNumericDate(time.Now().Add(time.Hour))
	good := generateTestToken(t, testSecret, validClaims())
	parts := strings.Split(good, ".")

	unsigned := signWith(t, jwt.SigningMethodNone, jwt.UnsafeAllowNoneSignatureType, validClaims())
	// alg=none token with the payload of a valid one.
	noneHeaderOnly := strings.Split(unsigned, ".")[0] + "." + parts[1] + "."

	cases := map[string]string{
		"expired":           "Bearer " + generateTestToken(t, testSecret, expired),
		"not before":        "Bearer " + generateTestToken(t, testSecret, notYet),
		"wrong secret":      "Bearer " + generateTestToken(t, "another-secret", validClaims()),
		"alg none":          "Bearer " + unsigned,
		"alg none spliced":  "Bearer " + noneHeaderOnly,
		"tampered payload":  "Bearer " + parts[0] + "." + parts[1] + "x." + parts[2],
		"garbage":           "Bearer not-a-jwt",
		"empty bearer":      "Bearer ",
		"basic scheme":      "Basic dXNlcjpwYXNz",
		"token without sch": good,
	}
	for name, header := range cases {
		t.Run(name, func(t *testing.T) {
			rec, claims := serveJWT(t, gatewayJWTConfig(), "/api/v1/files", header)
			assert.Equal(t, http.StatusUnauthorized, rec.Code)
			assert.Nil(t, claims)
			assert.NotContains(t, rec.Body.String(), testSecret, "error body must not leak the secret")
		})
	}
}

func TestQAJWT_AcceptsOtherHMACAlgorithms(t *testing.T) {
	tok := signWith(t, jwt.SigningMethodHS512, []byte(testSecret), validClaims())
	rec, _ := serveJWT(t, gatewayJWTConfig(), "/api/v1/files", "Bearer "+tok)
	assert.Equal(t, http.StatusOK, rec.Code, "auth-service signs with HS256/384/512 depending on key size")
}

// QA-GW-01: auth-service issues refresh tokens signed with the same key but
// with "type":"refresh". The gateway never checks the type claim, so a
// long-lived refresh token is accepted as an access token on every route.
func TestQAJWT_RefreshTokenRejectedAsAccessToken(t *testing.T) {
	t.Skip("xfail QA-GW-01: gateway accepts type=refresh tokens as access tokens (internal/middleware/jwt.go validateToken)")
	refresh := jwt.MapClaims{
		"sub":  "8b0f6c1e-0000-4000-8000-000000000001",
		"type": "refresh",
		"exp":  time.Now().Add(7 * 24 * time.Hour).Unix(),
	}
	tok := signWith(t, jwt.SigningMethodHS256, []byte(testSecret), refresh)
	rec, _ := serveJWT(t, gatewayJWTConfig(), "/api/v1/files", "Bearer "+tok)
	assert.Equal(t, http.StatusUnauthorized, rec.Code)
}

// Characterises current behaviour backing QA-GW-01.
func TestQAJWT_RefreshTokenCurrentlyAccepted(t *testing.T) {
	refresh := jwt.MapClaims{"sub": "u1", "type": "refresh", "exp": time.Now().Add(time.Hour).Unix()}
	tok := signWith(t, jwt.SigningMethodHS256, []byte(testSecret), refresh)
	rec, _ := serveJWT(t, gatewayJWTConfig(), "/api/v1/files", "Bearer "+tok)
	assert.Equal(t, http.StatusOK, rec.Code)
}

// QA-GW-02: tokens with no exp claim are accepted and never expire.
func TestQAJWT_TokenWithoutExpiryRejected(t *testing.T) {
	t.Skip("xfail QA-GW-02: gateway accepts JWTs without an exp claim (jwt.ParseWithClaims without jwt.WithExpirationRequired)")
	tok := signWith(t, jwt.SigningMethodHS256, []byte(testSecret), jwt.MapClaims{"sub": "u1"})
	rec, _ := serveJWT(t, gatewayJWTConfig(), "/api/v1/files", "Bearer "+tok)
	assert.Equal(t, http.StatusUnauthorized, rec.Code)
}
