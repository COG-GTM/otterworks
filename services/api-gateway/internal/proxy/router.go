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

	// Rewrite replaces the Director hook deprecated in Go 1.26. It runs after
	// hop-by-hop headers are removed, so a client cannot use the Connection
	// header to strip the identity headers injected below.
	proxy := &httputil.ReverseProxy{
		Rewrite: func(pr *httputil.ProxyRequest) {
			pr.SetURL(target)
			// Keep the inbound Host, as NewSingleHostReverseProxy did.
			pr.Out.Host = pr.In.Host
			forwardClientHeaders(pr)
			setIdentityHeaders(pr)
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

// forwardingHeaders are stripped by ReverseProxy before Rewrite runs; they are
// copied from the inbound request so values set by the ingress still reach
// the backends.
var forwardingHeaders = []string{"Forwarded", "X-Forwarded-For", "X-Forwarded-Host", "X-Forwarded-Proto"}

func forwardClientHeaders(pr *httputil.ProxyRequest) {
	for _, h := range forwardingHeaders {
		if v, ok := pr.In.Header[h]; ok {
			pr.Out.Header[h] = v
		}
	}
	if clientIP, _, err := net.SplitHostPort(pr.In.RemoteAddr); err == nil {
		if prior := pr.Out.Header["X-Forwarded-For"]; len(prior) > 0 {
			clientIP = strings.Join(prior, ", ") + ", " + clientIP
		}
		pr.Out.Header.Set("X-Forwarded-For", clientIP)
	}
}

// setIdentityHeaders forwards the authenticated user identity. The auth-service
// issues JWTs with the user ID in the standard "sub" claim (claims.Subject);
// the custom "user_id" claim is a fallback for compatibility. Identity headers
// are derived from the validated JWT only; client-supplied values must never
// reach the backends.
func setIdentityHeaders(pr *httputil.ProxyRequest) {
	pr.Out.Header.Del("X-User-ID")
	pr.Out.Header.Del("X-User-Email")
	claims := middleware.GetJWTClaims(pr.In.Context())
	if claims == nil {
		return
	}
	userID := claims.Subject
	if userID == "" {
		userID = claims.UserID
	}
	if userID != "" {
		pr.Out.Header.Set("X-User-ID", userID)
	}
	if claims.Email != "" {
		pr.Out.Header.Set("X-User-Email", claims.Email)
	}
}
