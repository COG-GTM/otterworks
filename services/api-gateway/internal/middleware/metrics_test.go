package middleware

import (
	"testing"

	"github.com/stretchr/testify/assert"
)

func TestNormalizePath(t *testing.T) {
	tests := map[string]string{
		"/api/v1/auth":                 "/api/v1/auth",
		"/api/v1/auth/login":           "/api/v1/auth",
		"/api/v1/files/123/download":   "/api/v1/files",
		"/api/v1/documents/abc":        "/api/v1/documents",
		"/api/v1/collab/ws":            "/api/v1/collab",
		"/api/v1/notifications/unread": "/api/v1/notifications",
		"/api/v1/search?q=otter":       "/api/v1/search",
		"/api/v1/analytics/events":     "/api/v1/analytics",
		"/api/v1/admin/users":          "/api/v1/admin",
		"/api/v1/audit/logs":           "/api/v1/audit",
		"/api/v1/authorize":            "/api/v1/auth",
		"/api/v1/au":                   "other",
		"/api/v1/unknown":              "other",
		"/health":                      "other",
		"":                             "other",
	}
	for path, want := range tests {
		assert.Equal(t, want, normalizePath(path), "path %q", path)
	}
}
