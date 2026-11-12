package middleware

import "testing"

func TestNormalizePath(t *testing.T) {
	tests := []struct {
		path string
		want string
	}{
		{"/api/v1/auth/login", "/api/v1/auth"},
		{"/api/v1/files", "/api/v1/files"},
		{"/api/v1/files/123/download", "/api/v1/files"},
		{"/api/v1/documents/abc", "/api/v1/documents"},
		{"/api/v1/collab/ws", "/api/v1/collab"},
		{"/api/v1/notifications/unread", "/api/v1/notifications"},
		{"/api/v1/search?q=x", "/api/v1/search"},
		{"/api/v1/analytics/dashboard", "/api/v1/analytics"},
		{"/api/v1/admin/users", "/api/v1/admin"},
		{"/api/v1/audit", "/api/v1/audit"},
		{"/api/v1/audit/events/42", "/api/v1/audit"},
		{"/api/v1/auditlog", "/api/v1/audit"},
		{"/api/v1/aud", "other"},
		{"/health", "other"},
		{"/metrics", "other"},
		{"", "other"},
	}
	for _, tt := range tests {
		if got := normalizePath(tt.path); got != tt.want {
			t.Errorf("normalizePath(%q) = %q, want %q", tt.path, got, tt.want)
		}
	}
}
