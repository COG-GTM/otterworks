package middleware

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/golang-jwt/jwt/v5"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

const testSecret = "test-secret-key-for-jwt-signing"

func generateTestToken(t *testing.T, secret string, claims JWTClaims) string {
	t.Helper()
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

func newAuditedJWTChain(t *testing.T, emitter *recordingEmitter, trustedCIDRs ...string) http.Handler {
	t.Helper()
	trust, err := NewProxyTrust(trustedCIDRs)
	require.NoError(t, err)
	jwtMW := JWTAuth(JWTConfig{
		Secret:     testSecret,
		PublicPath: DefaultPublicPaths(),
		PrefixPath: DefaultPrefixPaths(),
		Audit:      emitter,
	})
	inner := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(http.StatusOK) })
	return RequestID(ClientOriginMiddleware(trust)(jwtMW(inner)))
}

func TestJWTAuth_401EmitsTokenRejected(t *testing.T) {
	cases := []struct {
		name   string
		header string
		reason string
	}{
		{"missing", "", "missing_token"},
		{"malformed", "Bearer not-a-jwt", "malformed_token"},
		{"bad_signature", "Bearer " + generateTestToken(t, "wrong-secret", JWTClaims{
			RegisteredClaims: jwt.RegisteredClaims{Subject: "user-1", ExpiresAt: jwt.NewNumericDate(time.Now().Add(time.Hour))},
		}), "invalid_signature"},
		{"expired", "Bearer " + generateTestToken(t, testSecret, JWTClaims{
			RegisteredClaims: jwt.RegisteredClaims{Subject: "user-1", ExpiresAt: jwt.NewNumericDate(time.Now().Add(-time.Hour))},
		}), "expired_token"},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			emitter := &recordingEmitter{}
			handler := newAuditedJWTChain(t, emitter)

			req := httptest.NewRequest(http.MethodGet, "/api/v1/files/abc?share_token=s3cr3t", nil)
			req.RemoteAddr = "203.0.113.7:51234"
			req.Header.Set("User-Agent", "otter-test/1.0")
			req.Header.Set("X-Request-ID", "req-401")
			if tc.header != "" {
				req.Header.Set("Authorization", tc.header)
			}
			rec := httptest.NewRecorder()
			handler.ServeHTTP(rec, req)

			assert.Equal(t, http.StatusUnauthorized, rec.Code)
			events := emitter.all()
			require.Len(t, events, 1)
			e := events[0]
			assert.Equal(t, "auth.token.rejected", e.Action)
			assert.Equal(t, "anonymous", e.UserID)
			assert.Equal(t, "anonymous", e.ActorType)
			assert.Equal(t, "api_route", e.ResourceType)
			assert.Equal(t, "/api/v1/files/abc", e.ResourceID)
			assert.Equal(t, "denied", e.Outcome)
			assert.Equal(t, "203.0.113.7", e.IPAddress)
			assert.Equal(t, "otter-test/1.0", e.UserAgent)
			assert.Equal(t, "req-401", e.RequestID)
			assert.Equal(t, tc.reason, e.Details["reason"])
			assert.Equal(t, "GET", e.Details["method"])
		})
	}
}

func TestJWTAuth_TokenRejectedUsesTrustedForwardedClientIP(t *testing.T) {
	emitter := &recordingEmitter{}
	handler := newAuditedJWTChain(t, emitter, "10.0.0.0/8")

	req := httptest.NewRequest(http.MethodGet, "/api/v1/files", nil)
	req.RemoteAddr = "10.1.2.3:443"
	req.Header.Set("X-Forwarded-For", "198.51.100.20")
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	require.Len(t, emitter.all(), 1)
	assert.Equal(t, "198.51.100.20", emitter.all()[0].IPAddress)
	assert.NotEmpty(t, emitter.all()[0].RequestID, "a generated request ID is attached")
}

func TestJWTAuth_ValidTokenAndPublicPathsEmitNothing(t *testing.T) {
	emitter := &recordingEmitter{}
	handler := newAuditedJWTChain(t, emitter)

	token := generateTestToken(t, testSecret, JWTClaims{
		RegisteredClaims: jwt.RegisteredClaims{Subject: "user-1", ExpiresAt: jwt.NewNumericDate(time.Now().Add(time.Hour))},
	})
	for _, path := range []string{"/health", "/metrics", "/api/v1/auth/login"} {
		req := httptest.NewRequest(http.MethodGet, path, nil)
		handler.ServeHTTP(httptest.NewRecorder(), req)
	}
	req := httptest.NewRequest(http.MethodGet, "/api/v1/files", nil)
	req.Header.Set("Authorization", "Bearer "+token)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	assert.Equal(t, http.StatusOK, rec.Code)
	assert.Empty(t, emitter.all())
}

func TestJWTAuth_TokenRejectedEventCarriesNoSecrets(t *testing.T) {
	emitter := &recordingEmitter{}
	handler := newAuditedJWTChain(t, emitter)

	// Correctly signed for another secret, so the full token reaches validation and is rejected.
	token := generateTestToken(t, "attacker-secret", JWTClaims{
		Email:            "victim@example.com",
		RegisteredClaims: jwt.RegisteredClaims{Subject: "user-1", ExpiresAt: jwt.NewNumericDate(time.Now().Add(time.Hour))},
	})
	req := httptest.NewRequest(http.MethodPost, "/api/v1/files/upload?token=share-tok-123&password=hunter2",
		strings.NewReader(`{"password":"hunter2","refreshToken":"refresh-tok-456"}`))
	req.Header.Set("Authorization", "Bearer "+token)
	req.Header.Set("Cookie", "session=cookie-secret")
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	require.Len(t, emitter.all(), 1)
	raw, err := json.Marshal(emitter.all()[0])
	require.NoError(t, err)
	payload := string(raw)
	for _, secret := range []string{token, strings.Split(token, ".")[1], "hunter2", "share-tok-123", "refresh-tok-456", "cookie-secret", "attacker-secret", testSecret, "victim@example.com"} {
		assert.NotContains(t, payload, secret)
	}
	var fields map[string]any
	require.NoError(t, json.Unmarshal(raw, &fields))
	for _, forbidden := range []string{"password", "token", "authorization", "refreshToken", "body"} {
		assert.NotContains(t, fields, forbidden)
	}
}
