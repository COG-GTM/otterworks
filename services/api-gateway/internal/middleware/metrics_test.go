package middleware

import (
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/prometheus/client_golang/prometheus/testutil"
)

func TestNormalizePath(t *testing.T) {
	tests := []struct {
		path string
		want string
	}{
		{"/api/v1/auth", "/api/v1/auth"},
		{"/api/v1/auth/login", "/api/v1/auth"},
		{"/api/v1/files/123/download", "/api/v1/files"},
		{"/api/v1/documents", "/api/v1/documents"},
		{"/api/v1/documents/abc/share", "/api/v1/documents"},
		{"/api/v1/collab/ws", "/api/v1/collab"},
		{"/api/v1/notifications/unread", "/api/v1/notifications"},
		{"/api/v1/search?q=x", "/api/v1/search"},
		{"/api/v1/analytics/dashboard", "/api/v1/analytics"},
		{"/api/v1/admin/users", "/api/v1/admin"},
		{"/api/v1/audit/events", "/api/v1/audit"},
		{"/api/v1/documentsX", "/api/v1/documents"},
		{"/api/v1/doc", "other"},
		{"/api/v1", "other"},
		{"/health", "other"},
		{"/metrics", "other"},
		{"", "other"},
		{"/API/V1/DOCUMENTS", "other"},
	}
	for _, tt := range tests {
		if got := normalizePath(tt.path); got != tt.want {
			t.Errorf("normalizePath(%q) = %q, want %q", tt.path, got, tt.want)
		}
	}
}

func TestMetricsRecordsNormalizedPath(t *testing.T) {
	handler := Metrics(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusOK)
	}))

	counter := httpRequestsTotal.WithLabelValues(http.MethodGet, "/api/v1/documents", "200")
	before := testutil.ToFloat64(counter)

	req := httptest.NewRequest(http.MethodGet, "/api/v1/documents/42", nil)
	handler.ServeHTTP(httptest.NewRecorder(), req)

	if got := testutil.ToFloat64(counter) - before; got != 1 {
		t.Fatalf("expected documents counter to increase by 1, got %v", got)
	}
}
