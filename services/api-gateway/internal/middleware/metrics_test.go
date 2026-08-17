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
		path string
		want string
	}{
		{path: "/api/v1/auth/login", want: "/api/v1/auth"},
		{path: "/api/v1/auth", want: "/api/v1/auth"},
		{path: "/api/v1/files/9f3c/download", want: "/api/v1/files"},
		{path: "/api/v1/documents/42", want: "/api/v1/documents"},
		{path: "/api/v1/collab/rooms/1", want: "/api/v1/collab"},
		{path: "/api/v1/notifications/unread", want: "/api/v1/notifications"},
		{path: "/api/v1/search?q=otter", want: "/api/v1/search"},
		{path: "/api/v1/analytics/usage", want: "/api/v1/analytics"},
		{path: "/api/v1/admin/users/7", want: "/api/v1/admin"},
		{path: "/api/v1/audit/events", want: "/api/v1/audit"},
		{path: "/api/v1/reports/monthly", want: "other"},
		{path: "/health", want: "other"},
		{path: "/", want: "other"},
		{path: "", want: "other"},
	}

	for _, tt := range tests {
		t.Run(tt.path, func(t *testing.T) {
			assert.Equal(t, tt.want, normalizePath(tt.path))
		})
	}
}

func TestMetrics_RecordsRequestCountAndDuration(t *testing.T) {
	// The collectors are package-level globals shared with other tests, so
	// assert on deltas for this label set rather than absolute values.
	const method, path, status = http.MethodGet, "/api/v1/search", "201"
	before := testutil.ToFloat64(httpRequestsTotal.WithLabelValues(method, path, status))
	durationBefore := testutil.CollectAndCount(httpRequestDuration)

	handler := Metrics(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusCreated)
	}))

	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, httptest.NewRequest(method, "/api/v1/search/docs?q=otter", nil))

	require.Equal(t, http.StatusCreated, rec.Code)
	assert.Equal(t, before+1, testutil.ToFloat64(httpRequestsTotal.WithLabelValues(method, path, status)))
	assert.GreaterOrEqual(t, testutil.CollectAndCount(httpRequestDuration), durationBefore)
}

func TestMetrics_CollapsesPathCardinality(t *testing.T) {
	const method, path, status = http.MethodGet, "/api/v1/files", "200"
	before := testutil.ToFloat64(httpRequestsTotal.WithLabelValues(method, path, status))

	handler := Metrics(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusOK)
	}))

	for _, target := range []string{"/api/v1/files/1", "/api/v1/files/2", "/api/v1/files/3/download"} {
		handler.ServeHTTP(httptest.NewRecorder(), httptest.NewRequest(method, target, nil))
	}

	assert.Equal(t, before+3, testutil.ToFloat64(httpRequestsTotal.WithLabelValues(method, path, status)),
		"per-resource paths must collapse onto one label value")
}

func TestMetrics_ActiveConnectionsReturnToBaseline(t *testing.T) {
	before := testutil.ToFloat64(httpActiveConnections)
	var during float64

	handler := Metrics(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		during = testutil.ToFloat64(httpActiveConnections)
		w.WriteHeader(http.StatusOK)
	}))
	handler.ServeHTTP(httptest.NewRecorder(), httptest.NewRequest(http.MethodGet, "/api/v1/admin/x", nil))

	assert.Equal(t, before+1, during, "gauge is incremented for the duration of the request")
	assert.Equal(t, before, testutil.ToFloat64(httpActiveConnections))
}

func TestMetrics_HandlerThatWritesNothingRecordsStatusZero(t *testing.T) {
	// chi's wrapped writer only learns a status once the handler writes, so a
	// silent handler is recorded as "0" under the catch-all path label.
	const method, path, status = http.MethodDelete, "other", "0"
	before := testutil.ToFloat64(httpRequestsTotal.WithLabelValues(method, path, status))

	handler := Metrics(http.HandlerFunc(func(http.ResponseWriter, *http.Request) {}))
	handler.ServeHTTP(httptest.NewRecorder(), httptest.NewRequest(method, "/unknown/route", nil))

	assert.Equal(t, before+1, testutil.ToFloat64(httpRequestsTotal.WithLabelValues(method, path, status)))
}
