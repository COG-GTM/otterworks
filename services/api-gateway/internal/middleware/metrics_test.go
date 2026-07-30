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
		{path: "/api/v1/auth/login", want: "/api/v1/auth"},
		{path: "/api/v1/auth", want: "/api/v1/auth"},
		{path: "/api/v1/files/abc-123/download", want: "/api/v1/files"},
		{path: "/api/v1/documents/42", want: "/api/v1/documents"},
		{path: "/api/v1/collab/rooms/9", want: "/api/v1/collab"},
		{path: "/api/v1/notifications/unread", want: "/api/v1/notifications"},
		{path: "/api/v1/search?q=x", want: "/api/v1/search"},
		{path: "/api/v1/analytics/events", want: "/api/v1/analytics"},
		{path: "/api/v1/admin/users", want: "/api/v1/admin"},
		{path: "/api/v1/audit/logs", want: "/api/v1/audit"},
		// Prefixes the collapser does not know about fall into the catch-all
		// bucket, which is what keeps label cardinality bounded.
		{path: "/api/v1/reports/monthly", want: "other"},
		{path: "/api/v1/folders/7", want: "other"},
		{path: "/health", want: "other"},
		{path: "/api", want: "other"},
		{path: "", want: "other"},
	}

	for _, tt := range tests {
		t.Run(tt.path, func(t *testing.T) {
			assert.Equal(t, tt.want, normalizePath(tt.path))
		})
	}
}

func TestMetrics_RecordsRequestCountAndDuration(t *testing.T) {
	const (
		method = http.MethodGet
		path   = "/api/v1/audit"
		status = "201"
	)

	before := testutil.ToFloat64(httpRequestsTotal.WithLabelValues(method, path, status))
	beforeDuration := testutil.CollectAndCount(httpRequestDuration)

	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusCreated)
	})

	rec := httptest.NewRecorder()
	Metrics(next).ServeHTTP(rec, httptest.NewRequest(method, path+"/logs/1", nil))

	assert.Equal(t, http.StatusCreated, rec.Code)
	assert.Equal(t, before+1,
		testutil.ToFloat64(httpRequestsTotal.WithLabelValues(method, path, status)),
		"the request counter is incremented for the normalized path")
	assert.GreaterOrEqual(t, testutil.CollectAndCount(httpRequestDuration), beforeDuration,
		"a duration observation is recorded")
}

func TestMetrics_ActiveConnectionsGaugeIsBalanced(t *testing.T) {
	before := testutil.ToFloat64(httpActiveConnections)

	var inFlight float64
	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		inFlight = testutil.ToFloat64(httpActiveConnections)
		w.WriteHeader(http.StatusOK)
	})

	Metrics(next).ServeHTTP(httptest.NewRecorder(), httptest.NewRequest(http.MethodGet, "/whatever", nil))

	assert.Equal(t, before+1, inFlight, "the gauge is incremented while the handler runs")
	assert.Equal(t, before, testutil.ToFloat64(httpActiveConnections), "and decremented afterwards")
}

func TestMetrics_UnknownPathUsesOtherLabel(t *testing.T) {
	before := testutil.ToFloat64(httpRequestsTotal.WithLabelValues(http.MethodPost, "other", "500"))

	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusInternalServerError)
	})

	Metrics(next).ServeHTTP(httptest.NewRecorder(), httptest.NewRequest(http.MethodPost, "/nope", nil))

	assert.Equal(t, before+1, testutil.ToFloat64(httpRequestsTotal.WithLabelValues(http.MethodPost, "other", "500")))
}
