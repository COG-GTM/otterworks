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
		{"/api/v1/auth", routeAuth},
		{"/api/v1/auth/login", routeAuth},
		{"/api/v1/files/123/download", routeFiles},
		{"/api/v1/documents", routeDocuments},
		{"/api/v1/documents/abc/share", routeDocuments},
		{"/api/v1/collab/ws", routeCollab},
		{"/api/v1/notifications/unread", routeNotifications},
		{"/api/v1/search", routeSearch},
		{"/api/v1/search/analytics", routeSearch},
		{"/api/v1/searchsuggest", routeSearch},
		{"/api/v1/analytics/dashboard", routeAnalytics},
		{"/api/v1/admin/users", routeAdmin},
		{"/api/v1/audit/events", routeAudit},
		{"/api/v1/aut", routeOther},
		{"/api/v1/unknown", routeOther},
		{"/health", routeOther},
		{"", routeOther},
		{"/API/V1/SEARCH", routeOther},
	}

	for _, tt := range tests {
		if got := normalizePath(tt.path); got != tt.want {
			t.Errorf("normalizePath(%q) = %q, want %q", tt.path, got, tt.want)
		}
	}
}

func TestMetricsRecordsNormalizedPathLabel(t *testing.T) {
	handler := Metrics(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusTeapot)
	}))

	counter := httpRequestsTotal.WithLabelValues(http.MethodGet, routeSearch, "418")
	before := testutil.ToFloat64(counter)

	req := httptest.NewRequest(http.MethodGet, "/api/v1/search/query?q=otter", nil)
	handler.ServeHTTP(httptest.NewRecorder(), req)

	if got := testutil.ToFloat64(counter) - before; got != 1 {
		t.Fatalf("expected search request counter to increase by 1, got %v", got)
	}
}
