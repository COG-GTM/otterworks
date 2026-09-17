package middleware

import (
	"net/http"
	"net/http/httptest"
	"testing"
)

func securityHeadersHandler(cfg SecurityHeadersConfig) http.Handler {
	return SecurityHeaders(cfg)(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	}))
}

func TestSecurityHeadersSetsBaselineHeaders(t *testing.T) {
	req := httptest.NewRequest(http.MethodGet, "/api/v1/documents/", nil)
	rec := httptest.NewRecorder()

	securityHeadersHandler(DefaultSecurityHeadersConfig()).ServeHTTP(rec, req)

	expected := map[string]string{
		"X-Content-Type-Options": "nosniff",
		"X-Frame-Options":        "DENY",
		"Referrer-Policy":        "no-referrer",
	}
	for header, want := range expected {
		if got := rec.Header().Get(header); got != want {
			t.Errorf("%s = %q, want %q", header, got, want)
		}
	}
	if rec.Header().Get("Content-Security-Policy") == "" {
		t.Error("Content-Security-Policy not set")
	}
}

func TestSecurityHeadersSetsHeadersOnRejection(t *testing.T) {
	handler := SecurityHeaders(DefaultSecurityHeadersConfig())(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Error(w, "unauthorized", http.StatusUnauthorized)
	}))

	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/api/v1/documents/", nil))

	if rec.Code != http.StatusUnauthorized {
		t.Fatalf("status = %d, want %d", rec.Code, http.StatusUnauthorized)
	}
	if rec.Header().Get("X-Content-Type-Options") != "nosniff" {
		t.Error("security headers missing on a rejected request")
	}
}

func TestSecurityHeadersHSTSOnlyOverTLS(t *testing.T) {
	handler := securityHeadersHandler(DefaultSecurityHeadersConfig())

	plain := httptest.NewRecorder()
	handler.ServeHTTP(plain, httptest.NewRequest(http.MethodGet, "/health", nil))
	if got := plain.Header().Get("Strict-Transport-Security"); got != "" {
		t.Errorf("HSTS set on a plaintext request: %q", got)
	}

	forwarded := httptest.NewRequest(http.MethodGet, "/health", nil)
	forwarded.Header.Set("X-Forwarded-Proto", "https")
	tls := httptest.NewRecorder()
	handler.ServeHTTP(tls, forwarded)
	if got := tls.Header().Get("Strict-Transport-Security"); got != "max-age=31536000; includeSubDomains" {
		t.Errorf("Strict-Transport-Security = %q", got)
	}
}

func TestSecurityHeadersEmptyValueDisablesHeader(t *testing.T) {
	rec := httptest.NewRecorder()
	securityHeadersHandler(SecurityHeadersConfig{ContentTypeOptions: "nosniff"}).
		ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/health", nil))

	if got := rec.Header().Get("Content-Security-Policy"); got != "" {
		t.Errorf("Content-Security-Policy = %q, want unset", got)
	}
	if got := rec.Header().Get("X-Content-Type-Options"); got != "nosniff" {
		t.Errorf("X-Content-Type-Options = %q", got)
	}
}
