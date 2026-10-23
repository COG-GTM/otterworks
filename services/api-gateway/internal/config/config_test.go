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

// clearConfigEnv makes Load() see only the defaults, restoring the env afterwards.
func clearConfigEnv(t *testing.T) {
	t.Helper()
	for _, k := range configEnvKeys {
		t.Setenv(k, "") // registers restore of the original value
		unsetEnv(t, k)
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
	assert.Empty(t, cfg.JWTSecret, "JWT secret must have no baked-in default")
	assert.ElementsMatch(t, []string{"http://localhost:3000", "http://localhost:4200", "https://localhost", "capacitor://localhost"}, cfg.CORSAllowedOrigins)
	assert.NotContains(t, cfg.CORSAllowedOrigins, "*", "default CORS config must not allow every origin")
	assert.Contains(t, cfg.CORSAllowedHeaders, "Authorization")
	assert.Equal(t, 300, cfg.CORSMaxAge)
	assert.Equal(t, 30*time.Second, cfg.ShutdownTimeout)
	assert.Equal(t, uint32(5), cfg.CBMaxRequests)
	assert.Equal(t, 60*time.Second, cfg.CBInterval)
	assert.Equal(t, 30*time.Second, cfg.CBTimeout)
	assert.InDelta(t, 0.6, cfg.CBFailureRatio, 1e-9)
}

func TestLoad_EnvOverrides(t *testing.T) {
	clearConfigEnv(t)
	t.Setenv("PORT", "9999")
	t.Setenv("FILE_SERVICE_URL", "http://files.internal:1234")
	t.Setenv("RATE_LIMIT_RPS", "7")
	t.Setenv("JWT_SECRET", "s3cret")
	t.Setenv("CORS_ALLOWED_ORIGINS", "https://a.example,https://b.example")
	t.Setenv("CB_FAILURE_RATIO", "0.25")
	t.Setenv("CB_TIMEOUT_SECONDS", "3")

	cfg := Load()
	assert.Equal(t, "9999", cfg.Port)
	assert.Equal(t, "http://files.internal:1234", cfg.FileServiceURL)
	assert.Equal(t, 7, cfg.RateLimitRPS)
	assert.Equal(t, "s3cret", cfg.JWTSecret)
	assert.Equal(t, []string{"https://a.example", "https://b.example"}, cfg.CORSAllowedOrigins)
	assert.InDelta(t, 0.25, cfg.CBFailureRatio, 1e-9)
	assert.Equal(t, 3*time.Second, cfg.CBTimeout)
}

func TestLoad_InvalidNumbersFallBackToDefaults(t *testing.T) {
	clearConfigEnv(t)
	t.Setenv("RATE_LIMIT_RPS", "lots")
	t.Setenv("CB_FAILURE_RATIO", "most")
	t.Setenv("CORS_MAX_AGE", "")

	cfg := Load()
	assert.Equal(t, 100, cfg.RateLimitRPS)
	assert.InDelta(t, 0.6, cfg.CBFailureRatio, 1e-9)
	assert.Equal(t, 300, cfg.CORSMaxAge)
}

func TestLoad_EmptySliceEnvFallsBackToDefault(t *testing.T) {
	clearConfigEnv(t)
	t.Setenv("CORS_ALLOWED_ORIGINS", "")
	assert.Len(t, Load().CORSAllowedOrigins, 4)
}

func TestValidate(t *testing.T) {
	assert.Error(t, (&Config{}).Validate(), "missing JWT secret must fail fast")
	assert.NoError(t, (&Config{JWTSecret: "x"}).Validate())
}

func TestServiceRoutes_MapsEveryPrefixToItsBackend(t *testing.T) {
	cfg := &Config{
		AuthServiceURL: "auth", FileServiceURL: "file", DocumentServiceURL: "doc",
		CollabServiceURL: "collab", NotificationServiceURL: "notif", SearchServiceURL: "search",
		AnalyticsServiceURL: "analytics", AdminServiceURL: "admin", AuditServiceURL: "audit",
		ReportServiceURL: "report",
	}
	expected := map[string]string{
		"/api/v1/auth":          "auth",
		"/api/v1/settings":      "auth",
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
	}
	assert.Equal(t, expected, cfg.ServiceRoutes())
}

func TestServiceRoutes_CoversEveryPrefixTheWebClientCalls(t *testing.T) {
	// Top-level prefixes used by frontend/client-app/src (apiClient baseURL is /api/v1).
	clientPrefixes := []string{"auth", "files", "folders", "documents", "notifications", "search", "settings", "analytics"}
	routes := Load().ServiceRoutes()
	for _, p := range clientPrefixes {
		_, ok := routes["/api/v1/"+p]
		assert.True(t, ok, "web client calls /api/v1/%s but the gateway has no route for it", p)
	}
}

func TestServiceRoutes_PrefixesAreWellFormed(t *testing.T) {
	for prefix, target := range Load().ServiceRoutes() {
		require.NotEmpty(t, target, prefix)
		assert.True(t, prefix[0] == '/', "prefix %q must be absolute", prefix)
		assert.NotEqual(t, '/', prefix[len(prefix)-1], "prefix %q must not end in a slash", prefix)
	}
}

func unsetEnv(t *testing.T, key string) {
	t.Helper()
	if err := os.Unsetenv(key); err != nil {
		t.Fatalf("unsetenv %s: %v", key, err)
	}
}
