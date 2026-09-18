package middleware

import (
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/stretchr/testify/assert"
)

func TestSecurityHeaders_SetOnEveryResponse(t *testing.T) {
	handler := SecurityHeaders(DefaultSecurityHeadersConfig())(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusUnauthorized)
	}))

	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/api/v1/documents/", nil))

	assert.Equal(t, http.StatusUnauthorized, rec.Code)
	assert.Equal(t, "nosniff", rec.Header().Get("X-Content-Type-Options"))
	assert.Equal(t, "DENY", rec.Header().Get("X-Frame-Options"))
	assert.Contains(t, rec.Header().Get("Content-Security-Policy"), "frame-ancestors 'none'")
	assert.Equal(t, "no-referrer", rec.Header().Get("Referrer-Policy"))
	assert.Empty(t, rec.Header().Get("Strict-Transport-Security"), "HSTS is only meaningful over TLS")
}

func TestSecurityHeaders_HSTSOnTLSRequests(t *testing.T) {
	handler := SecurityHeaders(DefaultSecurityHeadersConfig())(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {}))

	req := httptest.NewRequest(http.MethodGet, "/api/v1/documents/", nil)
	req.Header.Set("X-Forwarded-Proto", "https")
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	assert.Contains(t, rec.Header().Get("Strict-Transport-Security"), "max-age=31536000")
}
