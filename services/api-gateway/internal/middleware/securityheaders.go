package middleware

import (
	"net/http"
	"strconv"
)

// SecurityHeadersConfig holds configuration for the security headers middleware.
// An empty value disables the corresponding header.
type SecurityHeadersConfig struct {
	ContentSecurityPolicy string
	ReferrerPolicy        string
	FrameOptions          string
	ContentTypeOptions    string
	// HSTSMaxAge is the max-age, in seconds, of Strict-Transport-Security. The
	// header is only sent on requests that reached the gateway over TLS.
	HSTSMaxAge int
}

// DefaultSecurityHeadersConfig returns the baseline header policy for an API
// edge that serves JSON only: no document is meant to be loaded, framed or
// embedded from it.
func DefaultSecurityHeadersConfig() SecurityHeadersConfig {
	return SecurityHeadersConfig{
		ContentSecurityPolicy: "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
		ReferrerPolicy:        "no-referrer",
		FrameOptions:          "DENY",
		ContentTypeOptions:    "nosniff",
		HSTSMaxAge:            31536000,
	}
}

// SecurityHeaders returns an HTTP middleware that sets baseline browser
// security headers on every response, including error responses written by
// middleware further down the stack.
func SecurityHeaders(cfg SecurityHeadersConfig) func(http.Handler) http.Handler {
	hsts := ""
	if cfg.HSTSMaxAge > 0 {
		hsts = "max-age=" + strconv.Itoa(cfg.HSTSMaxAge) + "; includeSubDomains"
	}

	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			h := w.Header()
			setIfNotEmpty(h, "Content-Security-Policy", cfg.ContentSecurityPolicy)
			setIfNotEmpty(h, "Referrer-Policy", cfg.ReferrerPolicy)
			setIfNotEmpty(h, "X-Frame-Options", cfg.FrameOptions)
			setIfNotEmpty(h, "X-Content-Type-Options", cfg.ContentTypeOptions)
			if isTLS(r) {
				setIfNotEmpty(h, "Strict-Transport-Security", hsts)
			}

			next.ServeHTTP(w, r)
		})
	}
}

func setIfNotEmpty(h http.Header, name, value string) {
	if value != "" {
		h.Set(name, value)
	}
}

// isTLS reports whether the client reached the edge over TLS, either directly
// or through a TLS-terminating proxy.
func isTLS(r *http.Request) bool {
	return r.TLS != nil || r.Header.Get("X-Forwarded-Proto") == "https"
}
