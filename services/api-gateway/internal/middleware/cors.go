package middleware

import (
	"net/http"
	"strconv"
	"strings"
)

// CORSConfig holds configuration for CORS middleware.
type CORSConfig struct {
	AllowedOrigins   []string
	AllowedMethods   []string
	AllowedHeaders   []string
	ExposedHeaders   []string
	AllowCredentials bool
	MaxAge           int
}

// DefaultCORSConfig returns a default CORS configuration.
// https://localhost and capacitor://localhost are the WebView origins of the
// Capacitor mobile app (Android and iOS respectively).
func DefaultCORSConfig() CORSConfig {
	return CORSConfig{
		AllowedOrigins:   []string{"http://localhost:3000", "http://localhost:4200", "https://localhost", "capacitor://localhost"},
		AllowedMethods:   []string{"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"},
		AllowedHeaders:   []string{"Accept", "Authorization", "Content-Type", "X-Request-ID"},
		ExposedHeaders:   []string{"Link", "X-Request-ID"},
		AllowCredentials: true,
		MaxAge:           300,
	}
}

// corsHeaders holds the precomputed header values derived from a CORSConfig.
type corsHeaders struct {
	allowedOrigins   map[string]bool
	origins          []string
	allowCredentials bool
	methods          string
	headers          string
	exposed          string
	maxAge           string
}

func newCORSHeaders(cfg CORSConfig) corsHeaders {
	allowedOrigins := make(map[string]bool, len(cfg.AllowedOrigins))
	for _, o := range cfg.AllowedOrigins {
		allowedOrigins[o] = true
	}

	return corsHeaders{
		allowedOrigins:   allowedOrigins,
		origins:          cfg.AllowedOrigins,
		allowCredentials: cfg.AllowCredentials,
		methods:          strings.Join(cfg.AllowedMethods, ", "),
		headers:          strings.Join(cfg.AllowedHeaders, ", "),
		exposed:          strings.Join(cfg.ExposedHeaders, ", "),
		maxAge:           strconv.Itoa(cfg.MaxAge),
	}
}

func (c corsHeaders) allows(origin string) bool {
	return origin != "" && isOriginAllowed(origin, c.allowedOrigins, c.origins)
}

func (c corsHeaders) writeOriginHeaders(h http.Header, origin string) {
	h.Set("Access-Control-Allow-Origin", origin)
	if c.allowCredentials {
		h.Set("Access-Control-Allow-Credentials", "true")
	}
	if c.exposed != "" {
		h.Set("Access-Control-Expose-Headers", c.exposed)
	}
	h.Set("Vary", "Origin")
}

func (c corsHeaders) writePreflightHeaders(h http.Header) {
	h.Set("Access-Control-Allow-Methods", c.methods)
	h.Set("Access-Control-Allow-Headers", c.headers)
	h.Set("Access-Control-Max-Age", c.maxAge)
}

// CORS returns an HTTP middleware that handles Cross-Origin Resource Sharing.
func CORS(cfg CORSConfig) func(http.Handler) http.Handler {
	c := newCORSHeaders(cfg)

	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			origin := r.Header.Get("Origin")
			if !c.allows(origin) {
				next.ServeHTTP(w, r)
				return
			}

			c.writeOriginHeaders(w.Header(), origin)

			// Handle preflight (only for allowed origins)
			if r.Method == http.MethodOptions {
				c.writePreflightHeaders(w.Header())
				w.WriteHeader(http.StatusNoContent)
				return
			}

			next.ServeHTTP(w, r)
		})
	}
}

func isOriginAllowed(origin string, lookup map[string]bool, origins []string) bool {
	if lookup[origin] {
		return true
	}
	for _, o := range origins {
		if o == "*" {
			return true
		}
	}
	return false
}
