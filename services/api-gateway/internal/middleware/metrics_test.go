package middleware

import (
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/prometheus/client_golang/prometheus/testutil"
	"github.com/stretchr/testify/assert"
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
		{"/api/v1/notifications", "/api/v1/notifications"},
		{"/api/v1/search?q=x", "/api/v1/search"},
		{"/api/v1/analytics/dashboard", "/api/v1/analytics"},
		{"/api/v1/admin/users", "/api/v1/admin"},
		{"/api/v1/audit/events", "/api/v1/audit"},
		{"/api/v1/authz", "/api/v1/auth"},
		{"/health", "other"},
		{"/metrics", "other"},
		{"/api/v1", "other"},
		{"/api/v2/auth", "other"},
		{"", "other"},
	}
	for _, tt := range tests {
		t.Run(tt.path, func(t *testing.T) {
			assert.Equal(t, tt.want, normalizePath(tt.path))
		})
	}
}

func TestMetricsRecordsNormalizedPath(t *testing.T) {
	handler := Metrics(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusTeapot)
	}))

	counter := httpRequestsTotal.WithLabelValues(http.MethodGet, "/api/v1/auth", "418")
	before := testutil.ToFloat64(counter)

	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/api/v1/auth/login", nil))

	assert.Equal(t, http.StatusTeapot, rec.Code)
	assert.Equal(t, before+1, testutil.ToFloat64(counter))
}
