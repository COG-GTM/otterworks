package middleware

import (
	"net/http"
	"net/http/httptest"
	"testing"

	dto "github.com/prometheus/client_model/go"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestNormalizePath(t *testing.T) {
	tests := map[string]string{
		"/api/v1/auth/login":           "/api/v1/auth",
		"/api/v1/files":                "/api/v1/files",
		"/api/v1/files/123/download":   "/api/v1/files",
		"/api/v1/documents/abc":        "/api/v1/documents",
		"/api/v1/collab/ws":            "/api/v1/collab",
		"/api/v1/notifications/unread": "/api/v1/notifications",
		"/api/v1/search?q=otter":       "/api/v1/search",
		"/api/v1/analytics/dashboard":  "/api/v1/analytics",
		"/api/v1/admin/users":          "/api/v1/admin",
		"/api/v1/audit/events":         "/api/v1/audit",
		"/api/v1/authorize":            "/api/v1/auth",
		"/api/v1/administrators":       "/api/v1/admin",
		"/api/v1/au":                   "other",
		"/api/v2/files":                "other",
		"/health":                      "other",
		"":                             "other",
	}

	for path, want := range tests {
		assert.Equal(t, want, normalizePath(path), "path %q", path)
	}
}

func requestCount(t *testing.T, method, path, status string) float64 {
	t.Helper()
	var m dto.Metric
	require.NoError(t, httpRequestsTotal.WithLabelValues(method, path, status).Write(&m))
	return m.GetCounter().GetValue()
}

func TestMetrics_LabelsRequestsByRoutePrefix(t *testing.T) {
	handler := Metrics(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusTeapot)
	}))

	adminBefore := requestCount(t, http.MethodGet, "/api/v1/admin", "418")
	otherBefore := requestCount(t, http.MethodGet, "other", "418")

	handler.ServeHTTP(httptest.NewRecorder(), httptest.NewRequest(http.MethodGet, "/api/v1/admin/users/42", nil))
	handler.ServeHTTP(httptest.NewRecorder(), httptest.NewRequest(http.MethodGet, "/not-an-api-route", nil))

	assert.Equal(t, adminBefore+1, requestCount(t, http.MethodGet, "/api/v1/admin", "418"))
	assert.Equal(t, otherBefore+1, requestCount(t, http.MethodGet, "other", "418"))
}
