package middleware

import (
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/prometheus/client_golang/prometheus/testutil"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestMetrics_RecordsRequest(t *testing.T) {
	// The collectors are package-level globals shared with every other test, so
	// assert on deltas rather than absolute values.
	before := testutil.ToFloat64(httpRequestsTotal.WithLabelValues(http.MethodGet, "/api/v1/files", "201"))
	beforeDuration := testutil.CollectAndCount(httpRequestDuration)

	handler := Metrics(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		assert.Equal(t, float64(1), testutil.ToFloat64(httpActiveConnections), "connection is counted while in flight")
		w.WriteHeader(http.StatusCreated)
	}))

	req := httptest.NewRequest(http.MethodGet, "/api/v1/files/abc/versions", nil)
	rec := httptest.NewRecorder()

	handler.ServeHTTP(rec, req)

	require.Equal(t, http.StatusCreated, rec.Code)
	assert.Equal(t, before+1,
		testutil.ToFloat64(httpRequestsTotal.WithLabelValues(http.MethodGet, "/api/v1/files", "201")))
	assert.GreaterOrEqual(t, testutil.CollectAndCount(httpRequestDuration), beforeDuration+1)
	assert.Equal(t, float64(0), testutil.ToFloat64(httpActiveConnections), "gauge is released after the request")
}

func TestNormalizePath(t *testing.T) {
	tests := []struct {
		path string
		want string
	}{
		{path: "/api/v1/auth/login", want: "/api/v1/auth"},
		{path: "/api/v1/files/123/download", want: "/api/v1/files"},
		{path: "/api/v1/documents/9", want: "/api/v1/documents"},
		{path: "/api/v1/collab/rooms/1", want: "/api/v1/collab"},
		{path: "/api/v1/notifications", want: "/api/v1/notifications"},
		{path: "/api/v1/search/all", want: "/api/v1/search"},
		{path: "/api/v1/analytics/events", want: "/api/v1/analytics"},
		{path: "/api/v1/admin/tenants", want: "/api/v1/admin"},
		{path: "/api/v1/audit/logs", want: "/api/v1/audit"},
		{path: "/health", want: "other"},
		{path: "/api/v1/reports/daily", want: "other"},
		{path: "/", want: "other"},
		{path: "", want: "other"},
	}

	for _, tt := range tests {
		t.Run(tt.path, func(t *testing.T) {
			assert.Equal(t, tt.want, normalizePath(tt.path))
		})
	}
}
