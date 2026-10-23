package proxy

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/go-chi/chi/v5"
	chimw "github.com/go-chi/chi/v5/middleware"
	"github.com/golang-jwt/jwt/v5"
	"github.com/rs/zerolog"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/Cognition-Partner-Workshops/otterworks/services/api-gateway/internal/health"
	"github.com/Cognition-Partner-Workshops/otterworks/services/api-gateway/internal/middleware"
)

type seenRequest struct {
	Method, Path, RawQuery, Auth, UserID, Email, Roles string
	Host                                               string
}

func recordingBackend(t *testing.T, status int) (*httptest.Server, *[]seenRequest) {
	t.Helper()
	var seen []seenRequest
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		seen = append(seen, seenRequest{
			Method: r.Method, Path: r.URL.Path, RawQuery: r.URL.RawQuery,
			Auth: r.Header.Get("Authorization"), UserID: r.Header.Get("X-User-ID"),
			Email: r.Header.Get("X-User-Email"), Host: r.Host,
		})
		w.WriteHeader(status)
		_, _ = w.Write([]byte(`{"ok":true}`))
	}))
	t.Cleanup(srv.Close)
	return srv, &seen
}

// gatewayHandler mirrors the middleware stack and mounting order in cmd/server/main.go.
func gatewayHandler(t *testing.T, routes []Route, rps int, cb CircuitBreakerConfig) http.Handler {
	t.Helper()
	prefixes := make([]string, 0, len(routes))
	for _, rt := range routes {
		prefixes = append(prefixes, rt.Prefix)
	}
	r := chi.NewRouter()
	r.Use(middleware.RequestID)
	r.Use(chimw.RealIP)
	r.Use(middleware.Metrics)
	r.Use(chimw.Recoverer)
	r.Use(middleware.NewRateLimiter(rps).Handler)
	r.Use(middleware.CORS(middleware.DefaultCORSConfig()))
	r.Use(middleware.JWTAuth(middleware.JWTConfig{
		Secret:              routerTestSecret,
		PublicPath:          middleware.DefaultPublicPaths(),
		PrefixPath:          middleware.DefaultPrefixPaths(),
		ProtectedPrefixPath: prefixes,
	}))
	r.Get("/health", health.Handler())
	r.Mount("/", NewRouter(RouterConfig{Routes: routes, CBManager: NewCircuitBreakerManager(cb), Logger: zerolog.Nop()}))
	return r
}

func lenientCB() CircuitBreakerConfig {
	return CircuitBreakerConfig{MaxRequests: 1, Interval: time.Minute, Timeout: time.Minute, FailureRatio: 1.1}
}

func bearer(t *testing.T, claims jwt.Claims) string {
	t.Helper()
	s, err := jwt.NewWithClaims(jwt.SigningMethodHS256, claims).SignedString([]byte(routerTestSecret))
	require.NoError(t, err)
	return "Bearer " + s
}

func userClaims(sub, email string) middleware.JWTClaims {
	return middleware.JWTClaims{Email: email, RegisteredClaims: jwt.RegisteredClaims{
		Subject: sub, ExpiresAt: jwt.NewNumericDate(time.Now().Add(time.Hour)),
	}}
}

func do(h http.Handler, method, path string, headers map[string]string) *httptest.ResponseRecorder {
	req := httptest.NewRequest(method, path, nil)
	req.RemoteAddr = "198.51.100.7:40000"
	for k, v := range headers {
		req.Header.Set(k, v)
	}
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	return rec
}

func decode(t *testing.T, rec *httptest.ResponseRecorder) map[string]string {
	t.Helper()
	var m map[string]string
	require.NoError(t, json.Unmarshal(rec.Body.Bytes(), &m), rec.Body.String())
	return m
}

func TestQAProxy_PreservesPathQueryAndAuthorization(t *testing.T) {
	backend, seen := recordingBackend(t, http.StatusOK)
	h := gatewayHandler(t, []Route{{Prefix: "/api/v1/documents", TargetURL: backend.URL}}, 1000, lenientCB())
	auth := bearer(t, userClaims("u-1", "u1@otterworks.test"))

	rec := do(h, http.MethodPatch, "/api/v1/documents/42/content?version=3&x=a%20b", map[string]string{"Authorization": auth})
	require.Equal(t, http.StatusOK, rec.Code)
	require.Len(t, *seen, 1)
	got := (*seen)[0]
	assert.Equal(t, http.MethodPatch, got.Method)
	assert.Equal(t, "/api/v1/documents/42/content", got.Path, "full path must reach the backend unchanged")
	assert.Equal(t, "version=3&x=a%20b", got.RawQuery)
	assert.Equal(t, auth, got.Auth, "Authorization is forwarded for backends that re-validate")
	assert.Equal(t, "u-1", got.UserID)
	assert.Equal(t, "u1@otterworks.test", got.Email)
	assert.NotEmpty(t, rec.Header().Get("X-Request-ID"))
}

func TestQAProxy_PrefixRootIsRouted(t *testing.T) {
	backend, seen := recordingBackend(t, http.StatusOK)
	h := gatewayHandler(t, []Route{{Prefix: "/api/v1/documents", TargetURL: backend.URL}}, 1000, lenientCB())
	auth := bearer(t, userClaims("u-1", ""))
	assert.Equal(t, http.StatusOK, do(h, http.MethodGet, "/api/v1/documents", map[string]string{"Authorization": auth}).Code)
	assert.Equal(t, http.StatusOK, do(h, http.MethodPost, "/api/v1/documents/", map[string]string{"Authorization": auth}).Code)
	require.Len(t, *seen, 2)
	assert.Equal(t, "/api/v1/documents", (*seen)[0].Path)
	assert.Equal(t, "/api/v1/documents/", (*seen)[1].Path)
}

func TestQAProxy_FallsBackToUserIDClaimWhenSubMissing(t *testing.T) {
	backend, seen := recordingBackend(t, http.StatusOK)
	h := gatewayHandler(t, []Route{{Prefix: "/api/v1/files", TargetURL: backend.URL}}, 1000, lenientCB())
	claims := middleware.JWTClaims{UserID: "legacy-id", RegisteredClaims: jwt.RegisteredClaims{ExpiresAt: jwt.NewNumericDate(time.Now().Add(time.Hour))}}
	require.Equal(t, http.StatusOK, do(h, http.MethodGet, "/api/v1/files", map[string]string{"Authorization": bearer(t, claims)}).Code)
	assert.Equal(t, "legacy-id", (*seen)[0].UserID)
	assert.Empty(t, (*seen)[0].Email)
}

func TestQAProxy_StripsSpoofedIdentityOnPublicRoutes(t *testing.T) {
	backend, seen := recordingBackend(t, http.StatusOK)
	h := gatewayHandler(t, []Route{{Prefix: "/api/v1/auth", TargetURL: backend.URL}}, 1000, lenientCB())
	rec := do(h, http.MethodPost, "/api/v1/auth/login", map[string]string{
		"X-User-ID": "attacker-chosen", "X-User-Email": "admin@otterworks.test",
	})
	require.Equal(t, http.StatusOK, rec.Code)
	assert.Empty(t, (*seen)[0].UserID, "anonymous requests must not carry any X-User-ID")
	assert.Empty(t, (*seen)[0].Email)
}

func TestQAProxy_SpoofedIdentityReplacedByTokenSubject(t *testing.T) {
	backend, seen := recordingBackend(t, http.StatusOK)
	h := gatewayHandler(t, []Route{{Prefix: "/api/v1/files", TargetURL: backend.URL}}, 1000, lenientCB())
	req := httptest.NewRequest(http.MethodGet, "/api/v1/files", nil)
	req.Header.Set("Authorization", bearer(t, userClaims("real-user", "real@otterworks.test")))
	req.Header.Add("X-User-ID", "victim-1")
	req.Header.Add("X-User-ID", "victim-2")
	req.Header["x-user-email"] = []string{"victim@otterworks.test"} // non-canonical key
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	require.Equal(t, http.StatusOK, rec.Code)
	assert.Equal(t, "real-user", (*seen)[0].UserID)
	assert.Equal(t, "real@otterworks.test", (*seen)[0].Email)
}

func TestQAProxy_UpstreamDownReturns502JSON(t *testing.T) {
	dead := httptest.NewServer(http.NotFoundHandler())
	deadURL := dead.URL
	dead.Close()
	h := gatewayHandler(t, []Route{{Prefix: "/api/v1/search", TargetURL: deadURL}}, 1000, lenientCB())

	rec := do(h, http.MethodGet, "/api/v1/search?q=otter", map[string]string{"Authorization": bearer(t, userClaims("u", ""))})
	assert.Equal(t, http.StatusBadGateway, rec.Code)
	assert.Contains(t, rec.Header().Get("Content-Type"), "application/json")
	body := decode(t, rec)
	assert.Equal(t, "service unavailable", body["error"])
	assert.Equal(t, "/api/v1/search", body["target"])
	assert.NotContains(t, rec.Body.String(), deadURL, "internal upstream address must not leak")
}

func TestQAProxy_CircuitOpensAfterRepeatedUpstreamFailures(t *testing.T) {
	dead := httptest.NewServer(http.NotFoundHandler())
	deadURL := dead.URL
	dead.Close()
	cb := CircuitBreakerConfig{MaxRequests: 1, Interval: time.Minute, Timeout: time.Minute, FailureRatio: 0.6}
	h := gatewayHandler(t, []Route{{Prefix: "/api/v1/search", TargetURL: deadURL}}, 1000, cb)
	auth := map[string]string{"Authorization": bearer(t, userClaims("u", ""))}

	for i := 0; i < 5; i++ {
		require.Equal(t, http.StatusBadGateway, do(h, http.MethodGet, "/api/v1/search", auth).Code, "attempt %d", i)
	}
	rec := do(h, http.MethodGet, "/api/v1/search", auth)
	assert.Equal(t, http.StatusServiceUnavailable, rec.Code)
	body := decode(t, rec)
	assert.Equal(t, "circuit breaker open", body["reason"])
	assert.Equal(t, "/api/v1/search", body["service"])
}

func TestQAProxy_CircuitsAreIsolatedPerRoute(t *testing.T) {
	dead := httptest.NewServer(http.NotFoundHandler())
	deadURL := dead.URL
	dead.Close()
	live, _ := recordingBackend(t, http.StatusOK)
	cb := CircuitBreakerConfig{MaxRequests: 1, Interval: time.Minute, Timeout: time.Minute, FailureRatio: 0.6}
	h := gatewayHandler(t, []Route{
		{Prefix: "/api/v1/search", TargetURL: deadURL},
		{Prefix: "/api/v1/files", TargetURL: live.URL},
	}, 1000, cb)
	auth := map[string]string{"Authorization": bearer(t, userClaims("u", ""))}
	for i := 0; i < 6; i++ {
		do(h, http.MethodGet, "/api/v1/search", auth)
	}
	assert.Equal(t, http.StatusServiceUnavailable, do(h, http.MethodGet, "/api/v1/search", auth).Code)
	assert.Equal(t, http.StatusOK, do(h, http.MethodGet, "/api/v1/files", auth).Code)
}

func TestQAProxy_Backend4xxDoesNotTripCircuit(t *testing.T) {
	backend, _ := recordingBackend(t, http.StatusNotFound)
	cb := CircuitBreakerConfig{MaxRequests: 1, Interval: time.Minute, Timeout: time.Minute, FailureRatio: 0.6}
	h := gatewayHandler(t, []Route{{Prefix: "/api/v1/files", TargetURL: backend.URL}}, 1000, cb)
	auth := map[string]string{"Authorization": bearer(t, userClaims("u", ""))}
	for i := 0; i < 10; i++ {
		assert.Equal(t, http.StatusNotFound, do(h, http.MethodGet, "/api/v1/files/missing", auth).Code)
	}
}

func TestQAProxy_UnknownRouteReturns404JSON(t *testing.T) {
	h := gatewayHandler(t, []Route{{Prefix: "/api/v1/files", TargetURL: "http://127.0.0.1:1"}}, 1000, lenientCB())
	rec := do(h, http.MethodGet, "/api/v1/unknown", nil)
	assert.Equal(t, http.StatusNotFound, rec.Code)
	assert.Equal(t, "route not found", decode(t, rec)["error"])
}

func TestQAProxy_HealthIsPublic(t *testing.T) {
	h := gatewayHandler(t, nil, 1000, lenientCB())
	rec := do(h, http.MethodGet, "/health", nil)
	assert.Equal(t, http.StatusOK, rec.Code)
	assert.Equal(t, "healthy", decode(t, rec)["status"])
}

func TestQAProxy_MissingTokenNeverReachesBackend(t *testing.T) {
	backend, seen := recordingBackend(t, http.StatusOK)
	h := gatewayHandler(t, []Route{{Prefix: "/api/v1/files", TargetURL: backend.URL}}, 1000, lenientCB())
	for _, p := range []string{"/api/v1/files", "/api/v1/files/", "/api/v1/files/abc/download"} {
		assert.Equal(t, http.StatusUnauthorized, do(h, http.MethodGet, p, nil).Code, p)
	}
	assert.Empty(t, *seen)
}

func TestQAProxy_PreflightAnsweredWithoutToken(t *testing.T) {
	backend, seen := recordingBackend(t, http.StatusOK)
	h := gatewayHandler(t, []Route{{Prefix: "/api/v1/files", TargetURL: backend.URL}}, 1000, lenientCB())
	rec := do(h, http.MethodOptions, "/api/v1/files", map[string]string{
		"Origin": "http://localhost:3000", "Access-Control-Request-Method": "DELETE",
	})
	assert.Equal(t, http.StatusNoContent, rec.Code)
	assert.Empty(t, *seen)
}

func TestQAProxy_401CarriesCORSHeadersForAllowedOrigin(t *testing.T) {
	h := gatewayHandler(t, []Route{{Prefix: "/api/v1/files", TargetURL: "http://127.0.0.1:1"}}, 1000, lenientCB())
	rec := do(h, http.MethodGet, "/api/v1/files", map[string]string{"Origin": "http://localhost:3000"})
	assert.Equal(t, http.StatusUnauthorized, rec.Code)
	assert.Equal(t, "http://localhost:3000", rec.Header().Get("Access-Control-Allow-Origin"),
		"browser must be able to read the 401 to redirect to /login")
}

// QA-GW-01: the JWT middleware matches protected prefixes on the raw path
// but the router resolves // and dot-segments differently.
func TestQAProxy_DoubleSlashDoesNotBypassAuth(t *testing.T) {
	backend, seen := recordingBackend(t, http.StatusOK)
	h := gatewayHandler(t, []Route{{Prefix: "/api/v1/files", TargetURL: backend.URL}}, 1000, lenientCB())
	for _, p := range []string{"//api/v1/files", "/api//v1/files", "/api/v1//files", "/./api/v1/files", "/health/../api/v1/files"} {
		rec := do(h, http.MethodGet, p, nil)
		assert.NotEqual(t, http.StatusOK, rec.Code, "%s must not reach the backend unauthenticated", p)
	}
	assert.Empty(t, *seen, "no unauthenticated request may reach a protected backend")
}

// QA-GW-03: chimw.RealIP trusts X-Forwarded-For / X-Real-IP from any
// client, so rotating the header gives every request a fresh bucket.
func TestQAProxy_RateLimitCannotBeBypassedWithForwardedFor(t *testing.T) {
	t.Skip("xfail QA-GW-03: chimw.RealIP trusts client X-Forwarded-For/X-Real-IP, rate limit keyed on spoofable IP (cmd/server/main.go)")
	h := gatewayHandler(t, nil, 2, lenientCB())
	limited := 0
	for i := 0; i < 20; i++ {
		rec := do(h, http.MethodGet, "/health", map[string]string{"X-Forwarded-For": "203.0.113." + string(rune('0'+i%10))})
		if rec.Code == http.StatusTooManyRequests {
			limited++
		}
	}
	assert.Greater(t, limited, 0)
}

func TestQAProxy_RateLimitCurrentlyBypassedWithRealIP(t *testing.T) {
	h := gatewayHandler(t, nil, 1, lenientCB())
	codes := []int{}
	for _, ip := range []string{"203.0.113.1", "203.0.113.2", "203.0.113.3"} {
		codes = append(codes, do(h, http.MethodGet, "/health", map[string]string{"X-Real-IP": ip}).Code)
	}
	assert.Equal(t, []int{200, 200, 200}, codes, "characterises QA-GW-03")
	assert.Equal(t, http.StatusOK, do(h, http.MethodGet, "/health", nil).Code)
	assert.Equal(t, http.StatusTooManyRequests, do(h, http.MethodGet, "/health", nil).Code)
}

// QA-GW-05: rate limiter runs before CORS, so 429s carry no
// Access-Control-Allow-Origin and the browser hides the status from the SPA.
func TestQAProxy_429CarriesCORSHeaders(t *testing.T) {
	t.Skip("xfail QA-GW-05: 429 from rate limiter lacks CORS headers (middleware order in cmd/server/main.go)")
	h := gatewayHandler(t, nil, 1, lenientCB())
	hdr := map[string]string{"Origin": "http://localhost:3000"}
	do(h, http.MethodGet, "/health", hdr)
	rec := do(h, http.MethodGet, "/health", hdr)
	require.Equal(t, http.StatusTooManyRequests, rec.Code)
	assert.Equal(t, "http://localhost:3000", rec.Header().Get("Access-Control-Allow-Origin"))
}
