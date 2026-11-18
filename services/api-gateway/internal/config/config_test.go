package config

import (
	"os"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

var configEnvKeys = []string{
	"PORT", "LOG_LEVEL", "AUTH_SERVICE_URL", "FILE_SERVICE_URL", "DOCUMENT_SERVICE_URL",
	"COLLAB_SERVICE_URL", "NOTIFICATION_SERVICE_URL", "SEARCH_SERVICE_URL", "ANALYTICS_SERVICE_URL",
	"ADMIN_SERVICE_URL", "AUDIT_SERVICE_URL", "REPORT_SERVICE_URL", "RATE_LIMIT_RPS", "JWT_SECRET",
	"CORS_ALLOWED_ORIGINS", "CORS_ALLOWED_METHODS", "CORS_ALLOWED_HEADERS", "CORS_MAX_AGE",
	"SHUTDOWN_TIMEOUT_SECONDS", "CB_MAX_REQUESTS", "CB_INTERVAL_SECONDS", "CB_TIMEOUT_SECONDS",
	"CB_FAILURE_RATIO",
}

func clearConfigEnv(t *testing.T) {
	t.Helper()
	for _, k := range configEnvKeys {
		t.Setenv(k, "")
	}
	for _, k := range configEnvKeys {
		require.NoError(t, os.Unsetenv(k))
	}
}

func TestLoad_Defaults(t *testing.T) {
	clearConfigEnv(t)
	cfg := Load()

	assert.Equal(t, "8080", cfg.Port)
	assert.Equal(t, "info", cfg.LogLevel)
	assert.Equal(t, "http://auth-service:8081", cfg.AuthServiceURL)
	assert.Equal(t, "http://file-service:8082", cfg.FileServiceURL)
	assert.Equal(t, "http://document-service:8083", cfg.DocumentServiceURL)
	assert.Equal(t, "http://collab-service:8084", cfg.CollabServiceURL)
	assert.Equal(t, "http://notification-service:8086", cfg.NotificationServiceURL)
	assert.Equal(t, "http://search-service:8087", cfg.SearchServiceURL)
	assert.Equal(t, "http://analytics-service:8088", cfg.AnalyticsServiceURL)
	assert.Equal(t, "http://admin-service:8089", cfg.AdminServiceURL)
	assert.Equal(t, "http://audit-service:8090", cfg.AuditServiceURL)
	assert.Equal(t, "http://report-service:8091", cfg.ReportServiceURL)
	assert.Equal(t, 100, cfg.RateLimitRPS)
	assert.Equal(t, "", cfg.JWTSecret)
	assert.Equal(t, []string{"http://localhost:3000", "http://localhost:4200", "https://localhost", "capacitor://localhost"}, cfg.CORSAllowedOrigins)
	assert.Equal(t, []string{"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"}, cfg.CORSAllowedMethods)
	assert.Equal(t, []string{"Accept", "Authorization", "Content-Type", "X-Request-ID"}, cfg.CORSAllowedHeaders)
	assert.Equal(t, 300, cfg.CORSMaxAge)
	assert.Equal(t, 30*time.Second, cfg.ShutdownTimeout)
	assert.Equal(t, uint32(5), cfg.CBMaxRequests)
	assert.Equal(t, 60*time.Second, cfg.CBInterval)
	assert.Equal(t, 30*time.Second, cfg.CBTimeout)
	assert.Equal(t, 0.6, cfg.CBFailureRatio)
}

func TestLoad_FromEnv(t *testing.T) {
	clearConfigEnv(t)
	t.Setenv("PORT", "9999")
	t.Setenv("LOG_LEVEL", "debug")
	t.Setenv("AUTH_SERVICE_URL", "http://auth:1")
	t.Setenv("REPORT_SERVICE_URL", "http://report:2")
	t.Setenv("RATE_LIMIT_RPS", "7")
	t.Setenv("JWT_SECRET", "s3cret")
	t.Setenv("CORS_ALLOWED_ORIGINS", "https://a.example,https://b.example")
	t.Setenv("CORS_ALLOWED_METHODS", "GET")
	t.Setenv("CORS_ALLOWED_HEADERS", "X-One,X-Two")
	t.Setenv("CORS_MAX_AGE", "10")
	t.Setenv("SHUTDOWN_TIMEOUT_SECONDS", "3")
	t.Setenv("CB_MAX_REQUESTS", "9")
	t.Setenv("CB_INTERVAL_SECONDS", "11")
	t.Setenv("CB_TIMEOUT_SECONDS", "12")
	t.Setenv("CB_FAILURE_RATIO", "0.25")

	cfg := Load()

	assert.Equal(t, "9999", cfg.Port)
	assert.Equal(t, "debug", cfg.LogLevel)
	assert.Equal(t, "http://auth:1", cfg.AuthServiceURL)
	assert.Equal(t, "http://report:2", cfg.ReportServiceURL)
	assert.Equal(t, 7, cfg.RateLimitRPS)
	assert.Equal(t, "s3cret", cfg.JWTSecret)
	assert.Equal(t, []string{"https://a.example", "https://b.example"}, cfg.CORSAllowedOrigins)
	assert.Equal(t, []string{"GET"}, cfg.CORSAllowedMethods)
	assert.Equal(t, []string{"X-One", "X-Two"}, cfg.CORSAllowedHeaders)
	assert.Equal(t, 10, cfg.CORSMaxAge)
	assert.Equal(t, 3*time.Second, cfg.ShutdownTimeout)
	assert.Equal(t, uint32(9), cfg.CBMaxRequests)
	assert.Equal(t, 11*time.Second, cfg.CBInterval)
	assert.Equal(t, 12*time.Second, cfg.CBTimeout)
	assert.Equal(t, 0.25, cfg.CBFailureRatio)
}

func TestLoad_InvalidNumbersFallBack(t *testing.T) {
	clearConfigEnv(t)
	t.Setenv("RATE_LIMIT_RPS", "lots")
	t.Setenv("CB_FAILURE_RATIO", "most")
	t.Setenv("CORS_ALLOWED_ORIGINS", "")

	cfg := Load()

	assert.Equal(t, 100, cfg.RateLimitRPS)
	assert.Equal(t, 0.6, cfg.CBFailureRatio)
	assert.Len(t, cfg.CORSAllowedOrigins, 4, "empty slice env should use defaults")
}

func TestLoad_EmptyStringEnvIsKept(t *testing.T) {
	clearConfigEnv(t)
	t.Setenv("PORT", "")
	assert.Equal(t, "", Load().Port)
}

func TestValidate(t *testing.T) {
	err := (&Config{}).Validate()
	require.Error(t, err)
	assert.Contains(t, err.Error(), "JWT_SECRET")

	assert.NoError(t, (&Config{JWTSecret: "x"}).Validate())
}

func TestServiceRoutes(t *testing.T) {
	cfg := &Config{
		AuthServiceURL:         "auth",
		FileServiceURL:         "file",
		DocumentServiceURL:     "doc",
		CollabServiceURL:       "collab",
		NotificationServiceURL: "notif",
		SearchServiceURL:       "search",
		AnalyticsServiceURL:    "analytics",
		AdminServiceURL:        "admin",
		AuditServiceURL:        "audit",
		ReportServiceURL:       "report",
	}

	assert.Equal(t, map[string]string{
		"/api/v1/auth":          "auth",
		"/api/v1/files":         "file",
		"/api/v1/folders":       "file",
		"/api/v1/documents":     "doc",
		"/api/v1/templates":     "doc",
		"/api/v1/collab":        "collab",
		"/socket.io":            "collab",
		"/api/v1/notifications": "notif",
		"/api/v1/preferences":   "notif",
		"/api/v1/search":        "search",
		"/api/v1/analytics":     "analytics",
		"/api/v1/admin":         "admin",
		"/api/v1/audit":         "audit",
		"/api/v1/reports":       "report",
		"/api/v1/settings":      "auth",
	}, cfg.ServiceRoutes())
}
