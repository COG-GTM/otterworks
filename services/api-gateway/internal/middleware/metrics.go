package middleware

import (
	"net/http"
	"strconv"
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

// normalizePath reduces cardinality by collapsing path parameters.
func normalizePath(path string) string {
	// Keep top-level route prefix for grouping
	switch {
	case len(path) >= len("/api/v1/auth") && path[:len("/api/v1/auth")] == "/api/v1/auth":
		return "/api/v1/auth"
	case len(path) >= len("/api/v1/folder-share-links") && path[:len("/api/v1/folder-share-links")] == "/api/v1/folder-share-links":
		return "/api/v1/folder-share-links"
	case len(path) >= len("/api/v1/files") && path[:len("/api/v1/files")] == "/api/v1/files":
		return "/api/v1/files"
	case len(path) >= len("/api/v1/documents") && path[:len("/api/v1/documents")] == "/api/v1/documents":
		return "/api/v1/documents"
	case len(path) >= len("/api/v1/collab") && path[:len("/api/v1/collab")] == "/api/v1/collab":
		return "/api/v1/collab"
	case len(path) >= len("/api/v1/notifications") && path[:len("/api/v1/notifications")] == "/api/v1/notifications":
		return "/api/v1/notifications"
	case len(path) >= len("/api/v1/search") && path[:len("/api/v1/search")] == "/api/v1/search":
		return "/api/v1/search"
	case len(path) >= len("/api/v1/analytics") && path[:len("/api/v1/analytics")] == "/api/v1/analytics":
		return "/api/v1/analytics"
	case len(path) >= len("/api/v1/admin") && path[:len("/api/v1/admin")] == "/api/v1/admin":
		return "/api/v1/admin"
	case len(path) >= len("/api/v1/audit") && path[:len("/api/v1/audit")] == "/api/v1/audit":
		return "/api/v1/audit"
	default:
		return "other"
	}
}
