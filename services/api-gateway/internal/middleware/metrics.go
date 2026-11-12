package middleware

import (
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/go-chi/chi/v5/middleware"
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promauto"
)

var (
	httpRequestsTotal = promauto.NewCounterVec(
		prometheus.CounterOpts{
			Namespace: "api_gateway",
			Name:      "http_requests_total",
			Help:      "Total number of HTTP requests.",
		},
		[]string{"method", "path", "status"},
	)

	httpRequestDuration = promauto.NewHistogramVec(
		prometheus.HistogramOpts{
			Namespace: "api_gateway",
			Name:      "http_request_duration_seconds",
			Help:      "HTTP request latency in seconds.",
			Buckets:   prometheus.DefBuckets,
		},
		[]string{"method", "path"},
	)

	httpActiveConnections = promauto.NewGauge(
		prometheus.GaugeOpts{
			Namespace: "api_gateway",
			Name:      "http_active_connections",
			Help:      "Number of active HTTP connections.",
		},
	)
)

// Metrics returns HTTP middleware that records Prometheus metrics for each request.
func Metrics(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		start := time.Now()
		ww := middleware.NewWrapResponseWriter(w, r.ProtoMajor)

		httpActiveConnections.Inc()
		defer httpActiveConnections.Dec()

		next.ServeHTTP(ww, r)

		duration := time.Since(start).Seconds()
		status := strconv.Itoa(ww.Status())
		path := normalizePath(r.URL.Path)

		httpRequestsTotal.WithLabelValues(r.Method, path, status).Inc()
		httpRequestDuration.WithLabelValues(r.Method, path).Observe(duration)
	})
}

// Top-level route prefixes used as the "path" label on request metrics.
const (
	authRoutePrefix          = "/api/v1/auth"
	filesRoutePrefix         = "/api/v1/files"
	documentsRoutePrefix     = "/api/v1/documents"
	collabRoutePrefix        = "/api/v1/collab"
	notificationsRoutePrefix = "/api/v1/notifications"
	searchRoutePrefix        = "/api/v1/search"
	analyticsRoutePrefix     = "/api/v1/analytics"
	adminRoutePrefix         = "/api/v1/admin"
	auditRoutePrefix         = "/api/v1/audit"

	otherRouteLabel = "other"
)

var metricRoutePrefixes = []string{
	authRoutePrefix,
	filesRoutePrefix,
	documentsRoutePrefix,
	collabRoutePrefix,
	notificationsRoutePrefix,
	searchRoutePrefix,
	analyticsRoutePrefix,
	adminRoutePrefix,
	auditRoutePrefix,
}

// normalizePath reduces cardinality by collapsing a request path to its
// top-level route prefix.
func normalizePath(path string) string {
	for _, prefix := range metricRoutePrefixes {
		if strings.HasPrefix(path, prefix) {
			return prefix
		}
	}
	return otherRouteLabel
}
