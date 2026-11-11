package proxy

import (
	"encoding/json"
	"net"
	"net/http"
	"net/http/httputil"
	"net/url"
	"strings"

	"github.com/go-chi/chi/v5"
	"github.com/rs/zerolog"
	"go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp"

	"github.com/Cognition-Partner-Workshops/otterworks/services/api-gateway/internal/middleware"
)

// Route defines a mapping from a URL prefix to a backend service.
type Route struct {
	Prefix    string
	TargetURL string
}

// RouterConfig holds configuration for the reverse proxy router.
type RouterConfig struct {
	Routes         []Route
	CBManager      *CircuitBreakerManager
	Logger         zerolog.Logger
	EnableTracing  bool
}

// NewRouter creates a chi router with all service routes mounted.
func NewRouter(cfg RouterConfig) chi.Router {
	r := chi.NewRouter()

	for _, route := range cfg.Routes {
		route := route // capture loop var
		r.Route(route.Prefix, func(sub chi.Router) {
			handler := newProxyHandler(route, cfg)
			sub.HandleFunc("/*", handler)
			sub.HandleFunc("/", handler)
		})
	}
	r.NotFound(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusNotFound)
		json.NewEncoder(w).Encode(map[string]string{
			"error": "route not found",
		})
	})

	return r
}

func newProxyHandler(route Route, cfg RouterConfig) http.HandlerFunc {
	// The full request path (e.g. /api/v1/auth/register) is preserved in
	// req.URL.Path, so the target URL should be just the backend host.
	// httputil.ReverseProxy joins the target path with req.URL.Path.
	target, err := url.Parse(route.TargetURL)
	if err != nil {
		cfg.Logger.Fatal().Err(err).Str("target", route.TargetURL).Msg("invalid proxy target URL")
	}

	// Rewrite (not the deprecated Director) runs after hop-by-hop header
	// removal, so a client cannot strip the identity headers set here by
	// naming them in its Connection header.
	proxy := &httputil.ReverseProxy{
		Rewrite: func(pr *httputil.ProxyRequest) {
			pr.SetURL(target)
			pr.Out.Host = pr.In.Host
			preserveForwardedHeaders(pr)
			setIdentityHeaders(pr.Out)
		},
	}

	proxy.ErrorHandler = func(w http.ResponseWriter, r *http.Request, err error) {
		cfg.Logger.Error().
			Err(err).
			Str("target", route.TargetURL).
			Str("path", r.URL.Path).
			Str("method", r.Method).
			Msg("proxy error")

		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusBadGateway)
		json.NewEncoder(w).Encode(map[string]string{
			"error":  "service unavailable",
			"target": route.Prefix,
		})
	}

	var handler http.Handler = proxy
	if cfg.EnableTracing {
		handler = otelhttp.NewHandler(proxy, "proxy:"+route.Prefix)
	}

	cb := cfg.CBManager.Get(route.Prefix)

	return func(w http.ResponseWriter, r *http.Request) {
		if err := cb.Execute(handler, w, r); err != nil {
			cfg.Logger.Warn().
				Str("circuit_breaker", route.Prefix).
				Str("state", cb.State().String()).
				Msg("circuit breaker rejected request")

			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(http.StatusServiceUnavailable)
			json.NewEncoder(w).Encode(map[string]string{
				"error":   "service temporarily unavailable",
				"service": route.Prefix,
				"reason":  "circuit breaker open",
			})
		}
	}
}

// preserveForwardedHeaders keeps the forwarding headers of upstream proxies and
// appends the client IP to X-Forwarded-For, as the Director-based proxy did.
func preserveForwardedHeaders(pr *httputil.ProxyRequest) {
	for _, h := range []string{"Forwarded", "X-Forwarded-Host", "X-Forwarded-Proto"} {
		if v, ok := pr.In.Header[h]; ok {
			pr.Out.Header[h] = v
		}
	}
	if clientIP, _, err := net.SplitHostPort(pr.In.RemoteAddr); err == nil {
		if prior := pr.In.Header.Values("X-Forwarded-For"); len(prior) > 0 {
			clientIP = strings.Join(prior, ", ") + ", " + clientIP
		}
		pr.Out.Header.Set("X-Forwarded-For", clientIP)
	}
}

// setIdentityHeaders forwards the authenticated user identity derived from the
// validated JWT only; client-supplied values must never reach the backends.
// The auth-service issues JWTs with the user ID in the standard "sub" claim
// (claims.Subject). Fall back to the custom "user_id" claim for compatibility.
func setIdentityHeaders(out *http.Request) {
	out.Header.Del("X-User-ID")
	out.Header.Del("X-User-Email")
	claims := middleware.GetJWTClaims(out.Context())
	if claims == nil {
		return
	}
	userID := claims.Subject
	if userID == "" {
		userID = claims.UserID
	}
	if userID != "" {
		out.Header.Set("X-User-ID", userID)
	}
	if claims.Email != "" {
		out.Header.Set("X-User-Email", claims.Email)
	}
}
