package middleware

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/golang-jwt/jwt/v5"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

// newDenialChain mirrors the production ordering: denial audit wraps the rate
// limiter and JWT middleware, and the final handler stands in for the upstream.
func newDenialChain(t *testing.T, emitter *recordingEmitter, rps int, upstream http.HandlerFunc) http.Handler {
	t.Helper()
	trust, err := NewProxyTrust(nil)
	require.NoError(t, err)
	rl := NewRateLimiter(rps)
	jwtMW := JWTAuth(JWTConfig{
		Secret:     testSecret,
		PublicPath: DefaultPublicPaths(),
		PrefixPath: DefaultPrefixPaths(),
	})
	auditMW := AuditAuthDenials(AuthDenialAuditConfig{Emitter: emitter, PathPrefixes: DefaultAuthDenialPrefixes()})
	return RequestID(ClientOriginMiddleware(trust)(auditMW(rl.Handler(jwtMW(upstream)))))
}

func TestAuditAuthDenials_Upstream403EmitsAccessDeniedWithActor(t *testing.T) {
	emitter := &recordingEmitter{}
	handler := newDenialChain(t, emitter, 100, func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusForbidden)
		_, _ = w.Write([]byte(`{"error":"forbidden"}`))
	})

	token := generateTestToken(t, testSecret, JWTClaims{
		Email: "otter@otterworks.dev",
		Roles: []string{"ROLE_ADMIN"},
		RegisteredClaims: jwt.RegisteredClaims{
			Subject:   "user-123",
			ExpiresAt: jwt.NewNumericDate(time.Now().Add(time.Hour)),
		},
	})
	req := httptest.NewRequest(http.MethodPut, "/api/v1/auth/users/42/roles", nil)
	req.RemoteAddr = "203.0.113.9:4000"
	req.Header.Set("Authorization", "Bearer "+token)
	req.Header.Set("User-Agent", "otter-test/1.0")
	req.Header.Set("X-Request-ID", "req-403")
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	assert.Equal(t, http.StatusForbidden, rec.Code)
	assert.JSONEq(t, `{"error":"forbidden"}`, rec.Body.String(), "response is passed through unchanged")

	events := emitter.all()
	require.Len(t, events, 1)
	e := events[0]
	assert.Equal(t, "auth.access.denied", e.Action)
	assert.Equal(t, "user-123", e.UserID)
	assert.Equal(t, "otter@otterworks.dev", e.ActorEmail)
	assert.Equal(t, "admin", e.ActorType)
	assert.Equal(t, "api_route", e.ResourceType)
	assert.Equal(t, "/api/v1/auth/users/42/roles", e.ResourceID)
	assert.Equal(t, "denied", e.Outcome)
	assert.Equal(t, "203.0.113.9", e.IPAddress)
	assert.Equal(t, "otter-test/1.0", e.UserAgent)
	assert.Equal(t, "req-403", e.RequestID)
	assert.Equal(t, map[string]string{"method": "PUT", "reason": "forbidden", "status": "403", "enforcedBy": "upstream"}, e.Details)

	raw, _ := json.Marshal(e)
	assert.NotContains(t, string(raw), token)
}

func TestAuditAuthDenials_GatewayRateLimitLockoutEmitsAccessDenied(t *testing.T) {
	emitter := &recordingEmitter{}
	handler := newDenialChain(t, emitter, 1, func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusUnauthorized) // bad credentials: auth-service's event, not ours
	})

	send := func() int {
		req := httptest.NewRequest(http.MethodPost, "/api/v1/auth/login", nil)
		req.RemoteAddr = "198.51.100.4:1111"
		req.Header.Set("X-Request-ID", "req-429")
		rec := httptest.NewRecorder()
		handler.ServeHTTP(rec, req)
		return rec.Code
	}
	assert.Equal(t, http.StatusUnauthorized, send())
	assert.Equal(t, http.StatusTooManyRequests, send())

	events := emitter.all()
	require.Len(t, events, 1)
	e := events[0]
	assert.Equal(t, "auth.access.denied", e.Action)
	assert.Equal(t, "anonymous", e.UserID)
	assert.Equal(t, "anonymous", e.ActorType)
	assert.Equal(t, "/api/v1/auth/login", e.ResourceID)
	assert.Equal(t, "denied", e.Outcome)
	assert.Equal(t, "198.51.100.4", e.IPAddress)
	assert.Equal(t, "req-429", e.RequestID)
	assert.Equal(t, "rate_limited", e.Details["reason"])
	assert.Equal(t, "429", e.Details["status"])
	assert.Equal(t, "api-gateway", e.Details["enforcedBy"])
}

func TestAuditAuthDenials_Upstream429Lockout(t *testing.T) {
	emitter := &recordingEmitter{}
	handler := newDenialChain(t, emitter, 100, func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusTooManyRequests)
	})
	req := httptest.NewRequest(http.MethodPost, "/api/v1/auth/login", nil)
	handler.ServeHTTP(httptest.NewRecorder(), req)

	require.Len(t, emitter.all(), 1)
	assert.Equal(t, "upstream", emitter.all()[0].Details["enforcedBy"])
}

func TestAuditAuthDenials_IgnoresOtherRoutesAndStatuses(t *testing.T) {
	emitter := &recordingEmitter{}
	status := http.StatusForbidden
	handler := newDenialChain(t, emitter, 100, func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(status)
	})
	token := generateTestToken(t, testSecret, JWTClaims{
		RegisteredClaims: jwt.RegisteredClaims{Subject: "u", ExpiresAt: jwt.NewNumericDate(time.Now().Add(time.Hour))},
	})

	req := httptest.NewRequest(http.MethodGet, "/api/v1/files/1", nil)
	req.Header.Set("Authorization", "Bearer "+token)
	handler.ServeHTTP(httptest.NewRecorder(), req)

	status = http.StatusOK
	req = httptest.NewRequest(http.MethodPost, "/api/v1/auth/login", nil)
	handler.ServeHTTP(httptest.NewRecorder(), req)

	req = httptest.NewRequest(http.MethodGet, "/api/v1/authority", nil)
	req.Header.Set("Authorization", "Bearer "+token)
	status = http.StatusForbidden
	handler.ServeHTTP(httptest.NewRecorder(), req)

	assert.Empty(t, emitter.all())
}
