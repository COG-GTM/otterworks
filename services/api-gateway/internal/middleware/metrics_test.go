package middleware

import (
	"net/http"
	"net/http/httptest"
	"testing"

	dto "github.com/prometheus/client_model/go"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func counterValue(t *testing.T, method, path, status string) float64 {
	t.Helper()
	m := &dto.Metric{}
	require.NoError(t, httpRequestsTotal.WithLabelValues(method, path, status).Write(m))
	return m.GetCounter().GetValue()
}

func histogramCount(t *testing.T, method, path string) uint64 {
	t.Helper()
	m := &dto.Metric{}
	obs, err := httpRequestDuration.GetMetricWithLabelValues(method, path)
	require.NoError(t, err)
	require.NoError(t, obs.(interface{ Write(*dto.Metric) error }).Write(m))
	return m.GetHistogram().GetSampleCount()
}

func gaugeValue(t *testing.T) float64 {
	t.Helper()
	m := &dto.Metric{}
	require.NoError(t, httpActiveConnections.Write(m))
	return m.GetGauge().GetValue()
}

func TestMetrics_RecordsRequest(t *testing.T) {
	beforeCount := counterValue(t, http.MethodGet, "/api/v1/files", "418")
	beforeHist := histogramCount(t, http.MethodGet, "/api/v1/files")
	var inFlight float64

	h := Metrics(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		inFlight = gaugeValue(t)
		w.WriteHeader(http.StatusTeapot)
	}))
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/api/v1/files/abc-123/download", nil))

	assert.Equal(t, http.StatusTeapot, rec.Code)
	assert.Equal(t, beforeCount+1, counterValue(t, http.MethodGet, "/api/v1/files", "418"))
	assert.Equal(t, beforeHist+1, histogramCount(t, http.MethodGet, "/api/v1/files"))
	assert.GreaterOrEqual(t, inFlight, float64(1))
	assert.Equal(t, inFlight-1, gaugeValue(t))
}

func TestMetrics_DefaultStatusIsOK(t *testing.T) {
	before := counterValue(t, http.MethodDelete, "other", "200")
	h := Metrics(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte("ok"))
	}))
	h.ServeHTTP(httptest.NewRecorder(), httptest.NewRequest(http.MethodDelete, "/unknown", nil))
	assert.Equal(t, before+1, counterValue(t, http.MethodDelete, "other", "200"))
}

func TestNormalizePath(t *testing.T) {
	cases := map[string]string{
		"/api/v1/auth":                    "/api/v1/auth",
		"/api/v1/auth/login":              "/api/v1/auth",
		"/api/v1/files/123/download":      "/api/v1/files",
		"/api/v1/documents/9":             "/api/v1/documents",
		"/api/v1/collab/rooms/1":          "/api/v1/collab",
		"/api/v1/notifications/unread":    "/api/v1/notifications",
		"/api/v1/search?q=x":              "/api/v1/search",
		"/api/v1/analytics/events":        "/api/v1/analytics",
		"/api/v1/admin/users/5":           "/api/v1/admin",
		"/api/v1/audit/logs":              "/api/v1/audit",
		"/health":                         "other",
		"/":                               "other",
		"":                                "other",
		"/random/user-supplied/123456789": "other",
	}
	for in, want := range cases {
		assert.Equal(t, want, normalizePath(in), in)
	}
}
