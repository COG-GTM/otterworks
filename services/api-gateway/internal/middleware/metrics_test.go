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
		{"/api/v1/documents/abc", "/api/v1/documents"},
		{"/api/v1/collab/ws", "/api/v1/collab"},
		{"/api/v1/notifications/unread", "/api/v1/notifications"},
		{"/api/v1/search?q=otter", "/api/v1/search"},
		{"/api/v1/analytics", "/api/v1/analytics"},
		{"/api/v1/analytics/users/42/activity", "/api/v1/analytics"},
		{"/api/v1/analyticsextra", "/api/v1/analytics"},
		{"/api/v1/admin/users", "/api/v1/admin"},
		{"/api/v1/audit/events", "/api/v1/audit"},
		{"/api/v1/analytic", "other"},
		{"/api/v2/analytics", "other"},
		{"/health", "other"},
		{"/metrics", "other"},
		{"", "other"},
	}
	for _, tt := range tests {
		t.Run(tt.path, func(t *testing.T) {
			if got := normalizePath(tt.path); got != tt.want {
				t.Errorf("normalizePath(%q) = %q, want %q", tt.path, got, tt.want)
			}
		})
	}
}

func TestMetricsRecordsNormalizedPath(t *testing.T) {
	handler := Metrics(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusTeapot)
	}))
	counter := httpRequestsTotal.WithLabelValues(http.MethodGet, "/api/v1/analytics", "418")
	before := testutil.ToFloat64(counter)

	req := httptest.NewRequest(http.MethodGet, "/api/v1/analytics/dashboard", nil)
	handler.ServeHTTP(httptest.NewRecorder(), req)

	if got := testutil.ToFloat64(counter) - before; got != 1 {
		t.Fatalf("expected analytics counter to increase by 1, got %v", got)
	}
}
