package middleware

import "net/http"

// SecurityHeadersConfig holds the response headers applied at the edge.
type SecurityHeadersConfig struct {
	ContentSecurityPolicy   string
	FrameOptions            string
	ReferrerPolicy          string
	StrictTransportSecurity string
}

// DefaultSecurityHeadersConfig returns the baseline policy for a JSON API edge:
// nothing is embeddable, nothing is loadable, and referrers never leak.
func DefaultSecurityHeadersConfig() SecurityHeadersConfig {
	return SecurityHeadersConfig{
		ContentSecurityPolicy:   "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
		FrameOptions:            "DENY",
		ReferrerPolicy:          "no-referrer",
		StrictTransportSecurity: "max-age=31536000; includeSubDomains",
	}
}

// SecurityHeaders sets baseline browser security headers on every response,
// including the ones written by middleware that rejects the request.
func SecurityHeaders(cfg SecurityHeadersConfig) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			h := w.Header()
			h.Set("X-Content-Type-Options", "nosniff")
			if cfg.FrameOptions != "" {
				h.Set("X-Frame-Options", cfg.FrameOptions)
			}
			if cfg.ContentSecurityPolicy != "" {
				h.Set("Content-Security-Policy", cfg.ContentSecurityPolicy)
			}
			if cfg.ReferrerPolicy != "" {
				h.Set("Referrer-Policy", cfg.ReferrerPolicy)
			}
			if cfg.StrictTransportSecurity != "" && (r.TLS != nil || r.Header.Get("X-Forwarded-Proto") == "https") {
				h.Set("Strict-Transport-Security", cfg.StrictTransportSecurity)
			}
			next.ServeHTTP(w, r)
		})
	}
}
