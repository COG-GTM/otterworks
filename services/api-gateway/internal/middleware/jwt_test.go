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

const testSecret = "test-secret-key-for-jwt-signing"

// generateTestToken signs claims the way auth-service does, defaulting iss/aud
// to the gateway defaults when the caller leaves them empty.
func generateTestToken(t *testing.T, secret string, claims JWTClaims) string {
	t.Helper()
	if claims.Issuer == "" {
		claims.Issuer = DefaultJWTIssuer
	}
	if claims.Audience == nil {
		claims.Audience = jwt.ClaimStrings{DefaultJWTAudience}
	}
	token := jwt.NewWithClaims(jwt.SigningMethodHS256, claims)
	tokenStr, err := token.SignedString([]byte(secret))
	require.NoError(t, err)
	return tokenStr
}

func TestJWTAuth_PublicPathsSkipValidation(t *testing.T) {
	cfg := JWTConfig{
		Secret:     testSecret,
		PublicPath: DefaultPublicPaths(),
		PrefixPath: DefaultPrefixPaths(),
	}

	handler := JWTAuth(cfg)(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	}))

	publicPaths := []string{
		"/health",
		"/metrics",
		"/api/v1/auth/login",
		"/api/v1/auth/register",
	}

	for _, path := range publicPaths {
		t.Run("public_"+path, func(t *testing.T) {
			req := httptest.NewRequest(http.MethodGet, path, nil)
			rec := httptest.NewRecorder()
			handler.ServeHTTP(rec, req)
			assert.Equal(t, http.StatusOK, rec.Code, "public path %s should not require auth", path)
		})
	}
}

func TestJWTAuth_SubPathsOfExactMatchRequireAuth(t *testing.T) {
	cfg := JWTConfig{
		Secret:     testSecret,
		PublicPath: DefaultPublicPaths(),
		PrefixPath: DefaultPrefixPaths(),
	}

	handler := JWTAuth(cfg)(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	}))

	// Sub-paths of exact-match public paths should require auth
	protectedSubPaths := []string{
		"/api/v1/auth/login/callback",
		"/api/v1/auth/register/verify",
	}

	for _, path := range protectedSubPaths {
		t.Run("protected_"+path, func(t *testing.T) {
			req := httptest.NewRequest(http.MethodGet, path, nil)
			rec := httptest.NewRecorder()
			handler.ServeHTTP(rec, req)
			assert.Equal(t, http.StatusUnauthorized, rec.Code, "sub-path %s should require auth", path)
		})
	}

	// Sub-paths of prefix-match paths should skip auth
	prefixSubPaths := []string{
		"/health/ready",
		"/metrics/prometheus",
	}

	for _, path := range prefixSubPaths {
		t.Run("prefix_public_"+path, func(t *testing.T) {
			req := httptest.NewRequest(http.MethodGet, path, nil)
			rec := httptest.NewRecorder()
			handler.ServeHTTP(rec, req)
			assert.Equal(t, http.StatusOK, rec.Code, "prefix path %s should not require auth", path)
		})
	}
}

func TestJWTAuth_MissingToken(t *testing.T) {
	cfg := JWTConfig{
		Secret:     testSecret,
		PublicPath: DefaultPublicPaths(),
		PrefixPath: DefaultPrefixPaths(),
	}

	handler := JWTAuth(cfg)(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	}))

	req := httptest.NewRequest(http.MethodGet, "/api/v1/files/list", nil)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	assert.Equal(t, http.StatusUnauthorized, rec.Code)
}

func TestJWTAuth_UnmatchedProtectedPrefixSkipsValidation(t *testing.T) {
	cfg := JWTConfig{
		Secret:              testSecret,
		PublicPath:          DefaultPublicPaths(),
		PrefixPath:          DefaultPrefixPaths(),
		ProtectedPrefixPath: []string{"/api/v1/files"},
	}

	handler := JWTAuth(cfg)(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusNotFound)
	}))

	req := httptest.NewRequest(http.MethodGet, "/api/v1/does-not-exist", nil)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	assert.Equal(t, http.StatusNotFound, rec.Code)
}

func TestJWTAuth_MatchedProtectedPrefixRequiresAuth(t *testing.T) {
	cfg := JWTConfig{
		Secret:              testSecret,
		PublicPath:          DefaultPublicPaths(),
		PrefixPath:          DefaultPrefixPaths(),
		ProtectedPrefixPath: []string{"/api/v1/files"},
	}

	handler := JWTAuth(cfg)(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	}))

	req := httptest.NewRequest(http.MethodGet, "/api/v1/files/list", nil)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	assert.Equal(t, http.StatusUnauthorized, rec.Code)
}

func TestJWTAuth_InvalidToken(t *testing.T) {
	cfg := JWTConfig{
		Secret:     testSecret,
		PublicPath: DefaultPublicPaths(),
		PrefixPath: DefaultPrefixPaths(),
	}

	handler := JWTAuth(cfg)(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	}))

	req := httptest.NewRequest(http.MethodGet, "/api/v1/files/list", nil)
	req.Header.Set("Authorization", "Bearer invalid-token-string")
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	assert.Equal(t, http.StatusUnauthorized, rec.Code)
}

func TestJWTAuth_ValidToken(t *testing.T) {
	cfg := JWTConfig{
		Secret:     testSecret,
		PublicPath: DefaultPublicPaths(),
		PrefixPath: DefaultPrefixPaths(),
	}

	claims := JWTClaims{
		UserID: "user-123",
		Email:  "test@otterworks.dev",
		Roles:  []string{"user"},
		RegisteredClaims: jwt.RegisteredClaims{
			ExpiresAt: jwt.NewNumericDate(time.Now().Add(1 * time.Hour)),
			IssuedAt:  jwt.NewNumericDate(time.Now()),
			Subject:   "user-123",
		},
	}

	tokenStr := generateTestToken(t, testSecret, claims)

	var capturedClaims *JWTClaims
	handler := JWTAuth(cfg)(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		capturedClaims = GetJWTClaims(r.Context())
		w.WriteHeader(http.StatusOK)
	}))

	req := httptest.NewRequest(http.MethodGet, "/api/v1/files/list", nil)
	req.Header.Set("Authorization", "Bearer "+tokenStr)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	assert.Equal(t, http.StatusOK, rec.Code)
	require.NotNil(t, capturedClaims)
	assert.Equal(t, "user-123", capturedClaims.UserID)
	assert.Equal(t, "test@otterworks.dev", capturedClaims.Email)
}

func TestJWTAuth_ExpiredToken(t *testing.T) {
	cfg := JWTConfig{
		Secret:     testSecret,
		PublicPath: DefaultPublicPaths(),
		PrefixPath: DefaultPrefixPaths(),
	}

	claims := JWTClaims{
		UserID: "user-123",
		RegisteredClaims: jwt.RegisteredClaims{
			ExpiresAt: jwt.NewNumericDate(time.Now().Add(-1 * time.Hour)),
			IssuedAt:  jwt.NewNumericDate(time.Now().Add(-2 * time.Hour)),
		},
	}

	tokenStr := generateTestToken(t, testSecret, claims)

	handler := JWTAuth(cfg)(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	}))

	req := httptest.NewRequest(http.MethodGet, "/api/v1/files/list", nil)
	req.Header.Set("Authorization", "Bearer "+tokenStr)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	assert.Equal(t, http.StatusUnauthorized, rec.Code)
}

func TestJWTAuth_WrongSecret(t *testing.T) {
	cfg := JWTConfig{
		Secret:     testSecret,
		PublicPath: DefaultPublicPaths(),
		PrefixPath: DefaultPrefixPaths(),
	}

	claims := JWTClaims{
		UserID: "user-123",
		RegisteredClaims: jwt.RegisteredClaims{
			ExpiresAt: jwt.NewNumericDate(time.Now().Add(1 * time.Hour)),
		},
	}

	tokenStr := generateTestToken(t, "wrong-secret", claims)

	handler := JWTAuth(cfg)(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	}))

	req := httptest.NewRequest(http.MethodGet, "/api/v1/files/list", nil)
	req.Header.Set("Authorization", "Bearer "+tokenStr)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	assert.Equal(t, http.StatusUnauthorized, rec.Code)
}

func TestJWTAuth_MalformedAuthHeader(t *testing.T) {
	cfg := JWTConfig{
		Secret:     testSecret,
		PublicPath: DefaultPublicPaths(),
		PrefixPath: DefaultPrefixPaths(),
	}

	handler := JWTAuth(cfg)(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	}))

	tests := []struct {
		name   string
		header string
	}{
		{"no Bearer prefix", "token-without-bearer"},
		{"Basic auth", "Basic dXNlcjpwYXNz"},
		{"empty Bearer", "Bearer "},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			req := httptest.NewRequest(http.MethodGet, "/api/v1/files/list", nil)
			req.Header.Set("Authorization", tt.header)
			rec := httptest.NewRecorder()
			handler.ServeHTTP(rec, req)
			assert.Equal(t, http.StatusUnauthorized, rec.Code)
		})
	}
}

func TestExtractBearerToken(t *testing.T) {
	tests := []struct {
		name     string
		header   string
		expected string
	}{
		{"valid Bearer", "Bearer abc123", "abc123"},
		{"case insensitive", "bearer abc123", "abc123"},
		{"no header", "", ""},
		{"no Bearer prefix", "abc123", ""},
		{"Basic auth", "Basic dXNlcjpwYXNz", ""},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			req := httptest.NewRequest(http.MethodGet, "/", nil)
			if tt.header != "" {
				req.Header.Set("Authorization", tt.header)
			}
			result := extractBearerToken(req)
			assert.Equal(t, tt.expected, result)
		})
	}
}

func TestGetJWTClaims_NilContext(t *testing.T) {
	req := httptest.NewRequest(http.MethodGet, "/", nil)
	claims := GetJWTClaims(req.Context())
	assert.Nil(t, claims)
}

func TestJWTAuth_RejectsTokensNotBoundToThisTenant(t *testing.T) {
	cfg := JWTConfig{
		Secret:     testSecret,
		Issuer:     DefaultJWTIssuer,
		Audience:   "otterworks-tenant-a",
		PublicPath: DefaultPublicPaths(),
		PrefixPath: DefaultPrefixPaths(),
	}
	handler := JWTAuth(cfg)(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	}))

	sign := func(issuer string, audience jwt.ClaimStrings) string {
		claims := jwt.MapClaims{
			"sub":   "attacker",
			"roles": []string{"OWNER"},
			"exp":   time.Now().Add(time.Hour).Unix(),
		}
		if issuer != "" {
			claims["iss"] = issuer
		}
		if audience != nil {
			claims["aud"] = audience
		}
		tokenStr, err := jwt.NewWithClaims(jwt.SigningMethodHS512, claims).SignedString([]byte(testSecret))
		require.NoError(t, err)
		return tokenStr
	}

	cases := map[string]struct {
		token string
		want  int
	}{
		"own tenant":     {sign(DefaultJWTIssuer, jwt.ClaimStrings{"otterworks-tenant-a"}), http.StatusOK},
		"other tenant":   {sign(DefaultJWTIssuer, jwt.ClaimStrings{"otterworks-tenant-b"}), http.StatusUnauthorized},
		"foreign issuer": {sign("evil-issuer", jwt.ClaimStrings{"otterworks-tenant-a"}), http.StatusUnauthorized},
		"no audience":    {sign(DefaultJWTIssuer, nil), http.StatusUnauthorized},
		"no issuer":      {sign("", jwt.ClaimStrings{"otterworks-tenant-a"}), http.StatusUnauthorized},
	}
	for name, tc := range cases {
		t.Run(name, func(t *testing.T) {
			req := httptest.NewRequest(http.MethodGet, "/api/v1/admin/config", nil)
			req.Header.Set("Authorization", "Bearer "+tc.token)
			rec := httptest.NewRecorder()
			handler.ServeHTTP(rec, req)
			assert.Equal(t, tc.want, rec.Code)
		})
	}
}

func TestJWTAuth_EmptyIssuerAudienceUseDefaults(t *testing.T) {
	cfg := JWTConfig{Secret: testSecret}
	handler := JWTAuth(cfg)(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	}))

	tokenStr, err := jwt.NewWithClaims(jwt.SigningMethodHS256, jwt.MapClaims{
		"sub": "user-123",
		"exp": time.Now().Add(time.Hour).Unix(),
	}).SignedString([]byte(testSecret))
	require.NoError(t, err)

	req := httptest.NewRequest(http.MethodGet, "/api/v1/files/list", nil)
	req.Header.Set("Authorization", "Bearer "+tokenStr)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)
	assert.Equal(t, http.StatusUnauthorized, rec.Code, "unbound tokens must be rejected even without explicit config")
}
