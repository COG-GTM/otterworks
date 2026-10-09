package middleware

import (
	"net/http"
	"path"
	"strings"
)

// DefaultInternalOnlyPaths lists backend endpoints that only in-cluster
// callers (Grafana, file-service, notification-service) may reach directly.
// They must never be exposed through the public gateway.
func DefaultInternalOnlyPaths() []string {
	return []string{
		"/api/v1/admin/alerts/ingest",
	}
}

// BlockInternalPaths returns 404 for requests to any internal-only path,
// including sub-paths, format suffixes (e.g. `.json`) and case or slash
// variations that a backend router would still resolve to the same endpoint.
func BlockInternalPaths(paths []string) func(http.Handler) http.Handler {
	blocked := make([]string, 0, len(paths))
	for _, p := range paths {
		blocked = append(blocked, strings.ToLower(path.Clean(p)))
	}

	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			reqPath := strings.ToLower(path.Clean("/" + r.URL.Path))
			for _, p := range blocked {
				if strings.HasPrefix(reqPath, p) {
					writeJSONError(w, http.StatusNotFound, "route not found")
					return
				}
			}
			next.ServeHTTP(w, r)
		})
	}
}
