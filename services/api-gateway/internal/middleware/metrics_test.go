package middleware

import (
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/prometheus/client_golang/prometheus/testutil"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestNormalizePath(t *testing.T) {
	tests := []struct {
		name string
		path string
		want string
	}{
		{name: "auth sub-path collapses to prefix", path: "/api/v1/auth/login", want: "/api/v1/auth"},
		{name: "auth prefix itself", path: "/api/v1/auth", want: "/api/v1/auth"},
		{name: "files with an id", path: "/api/v1/files/2f1c/download", want: "/api/v1/files"},
		{name: "documents", path: "/api/v1/documents/42", want: "/api/v1/documents"},
		{name: "collab", path: "/api/v1/collab/rooms/9", want: "/api/v1/collab"},
		{name: "notifications", path: "/api/v1/notifications/unread", want: "/api/v1/notifications"},
		{name: "search", path: "/api/v1/search/results", want: "/api/v1/search"},
		{name: "analytics", path: "/api/v1/analytics/usage", want: "/api/v1/analytics"},
		{name: "admin", path: "/api/v1/admin/tenants", want: "/api/v1/admin"},
		{name: "audit", path: "/api/v1/audit/events", want: "/api/v1/audit"},
		{name: "unmapped prefix is bucketed as other", path: "/api/v1/reports/monthly", want: "other"},
		{name: "operational path is bucketed as other", path: "/health", want: "other"},
		{name: "root is bucketed as other", path: "/", want: "other"},
		{name: "empty path is bucketed as other", path: "", want: "other"},
		{name: "short path shorter than any prefix", path: "/api", want: "other"},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			assert.Equal(t, tt.want, normalizePath(tt.path))
		})
	}
}

func TestMetrics_RecordsRequestCountAndDuration(t *testing.T) {
	const path = "/api/v1/analytics/usage"

	counter, err := httpRequestsTotal.GetMetricWithLabelValues(http.MethodGet, "/api/v1/analytics", "418")
	require.NoError(t, err)

	before := testutil.ToFloat64(counter)
	durationsBefore := testutil.CollectAndCount(httpRequestDuration)

	handler := Metrics(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusTeapot)
		_, _ = w.Write([]byte("brewing"))
	}))

	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, path, nil))

	assert.Equal(t, http.StatusTeapot, rec.Code)
	assert.Equal(t, "brewing", rec.Body.String())
	assert.Equal(t, before+1, testutil.ToFloat64(counter), "one request must be counted under the normalized path and status")
	assert.GreaterOrEqual(t, testutil.CollectAndCount(httpRequestDuration), durationsBefore+1)
}

func TestMetrics_ReleasesActiveConnectionGauge(t *testing.T) {
	idle := testutil.ToFloat64(httpActiveConnections)

	var inFlight float64
	handler := Metrics(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		inFlight = testutil.ToFloat64(httpActiveConnections)
		w.WriteHeader(http.StatusOK)
	}))
	handler.ServeHTTP(httptest.NewRecorder(), httptest.NewRequest(http.MethodGet, "/api/v1/files", nil))

	assert.Equal(t, idle+1, inFlight, "the gauge is incremented for the duration of the request")
	assert.Equal(t, idle, testutil.ToFloat64(httpActiveConnections), "and released once the handler returns")
}

func TestMetrics_ImplicitOKAndUnmappedPathLabels(t *testing.T) {
	counter, err := httpRequestsTotal.GetMetricWithLabelValues(http.MethodDelete, "other", "200")
	require.NoError(t, err)
	before := testutil.ToFloat64(counter)

	// No explicit WriteHeader: the wrapped writer reports the implicit 200,
	// and an unrouted path is bucketed as "other" to bound label cardinality.
	handler := Metrics(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte("ok"))
	}))
	handler.ServeHTTP(httptest.NewRecorder(), httptest.NewRequest(http.MethodDelete, "/nowhere", nil))

	assert.Equal(t, before+1, testutil.ToFloat64(counter))
}
