package config

import (
	"os"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

// clearEnv unsets every variable Load consults so a test starts from a known
// state. getEnv uses os.LookupEnv, so an *empty* variable still beats the
// default -- unsetting is the only way to exercise the fallbacks.
func clearEnv(t *testing.T) {
	t.Helper()
	for _, key := range []string{
		"PORT", "LOG_LEVEL",
		"AUTH_SERVICE_URL", "FILE_SERVICE_URL", "DOCUMENT_SERVICE_URL",
		"COLLAB_SERVICE_URL", "NOTIFICATION_SERVICE_URL", "SEARCH_SERVICE_URL",
		"ANALYTICS_SERVICE_URL", "ADMIN_SERVICE_URL", "AUDIT_SERVICE_URL",
		"REPORT_SERVICE_URL",
		"RATE_LIMIT_RPS", "JWT_SECRET",
		"CORS_ALLOWED_ORIGINS", "CORS_ALLOWED_METHODS", "CORS_ALLOWED_HEADERS",
		"CORS_MAX_AGE", "SHUTDOWN_TIMEOUT_SECONDS",
		"CB_MAX_REQUESTS", "CB_INTERVAL_SECONDS", "CB_TIMEOUT_SECONDS", "CB_FAILURE_RATIO",
	} {
		// t.Setenv registers the restore hook, then Unsetenv produces the
		// "absent" state the fallback branches need.
		t.Setenv(key, "")
		require.NoError(t, os.Unsetenv(key))
	}
}

func TestLoad_Defaults(t *testing.T) {
	clearEnv(t)

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
	assert.InDelta(t, 0.6, cfg.CBFailureRatio, 1e-9)
}

func TestLoad_EnvOverrides(t *testing.T) {
	clearEnv(t)

	t.Setenv("PORT", "9999")
	t.Setenv("LOG_LEVEL", "debug")
	t.Setenv("AUTH_SERVICE_URL", "http://auth.test:1")
	t.Setenv("FILE_SERVICE_URL", "http://file.test:2")
	t.Setenv("DOCUMENT_SERVICE_URL", "http://doc.test:3")
	t.Setenv("COLLAB_SERVICE_URL", "http://collab.test:4")
	t.Setenv("NOTIFICATION_SERVICE_URL", "http://notify.test:5")
	t.Setenv("SEARCH_SERVICE_URL", "http://search.test:6")
	t.Setenv("ANALYTICS_SERVICE_URL", "http://analytics.test:7")
	t.Setenv("ADMIN_SERVICE_URL", "http://admin.test:8")
	t.Setenv("AUDIT_SERVICE_URL", "http://audit.test:9")
	t.Setenv("REPORT_SERVICE_URL", "http://report.test:10")
	t.Setenv("RATE_LIMIT_RPS", "7")
	t.Setenv("JWT_SECRET", "s3cret")
	t.Setenv("CORS_ALLOWED_ORIGINS", "http://a.test,http://b.test")
	t.Setenv("CORS_ALLOWED_METHODS", "GET,POST")
	t.Setenv("CORS_ALLOWED_HEADERS", "Authorization")
	t.Setenv("CORS_MAX_AGE", "60")
	t.Setenv("SHUTDOWN_TIMEOUT_SECONDS", "5")
	t.Setenv("CB_MAX_REQUESTS", "3")
	t.Setenv("CB_INTERVAL_SECONDS", "11")
	t.Setenv("CB_TIMEOUT_SECONDS", "12")
	t.Setenv("CB_FAILURE_RATIO", "0.25")

	cfg := Load()

	assert.Equal(t, "9999", cfg.Port)
	assert.Equal(t, "debug", cfg.LogLevel)
	assert.Equal(t, "http://auth.test:1", cfg.AuthServiceURL)
	assert.Equal(t, "http://file.test:2", cfg.FileServiceURL)
	assert.Equal(t, "http://doc.test:3", cfg.DocumentServiceURL)
	assert.Equal(t, "http://collab.test:4", cfg.CollabServiceURL)
	assert.Equal(t, "http://notify.test:5", cfg.NotificationServiceURL)
	assert.Equal(t, "http://search.test:6", cfg.SearchServiceURL)
	assert.Equal(t, "http://analytics.test:7", cfg.AnalyticsServiceURL)
	assert.Equal(t, "http://admin.test:8", cfg.AdminServiceURL)
	assert.Equal(t, "http://audit.test:9", cfg.AuditServiceURL)
	assert.Equal(t, "http://report.test:10", cfg.ReportServiceURL)
	assert.Equal(t, 7, cfg.RateLimitRPS)
	assert.Equal(t, "s3cret", cfg.JWTSecret)
	assert.Equal(t, []string{"http://a.test", "http://b.test"}, cfg.CORSAllowedOrigins)
	assert.Equal(t, []string{"GET", "POST"}, cfg.CORSAllowedMethods)
	assert.Equal(t, []string{"Authorization"}, cfg.CORSAllowedHeaders)
	assert.Equal(t, 60, cfg.CORSMaxAge)
	assert.Equal(t, 5*time.Second, cfg.ShutdownTimeout)
	assert.Equal(t, uint32(3), cfg.CBMaxRequests)
	assert.Equal(t, 11*time.Second, cfg.CBInterval)
	assert.Equal(t, 12*time.Second, cfg.CBTimeout)
	assert.InDelta(t, 0.25, cfg.CBFailureRatio, 1e-9)
}

func TestLoad_MalformedNumbersFallBackToDefaults(t *testing.T) {
	clearEnv(t)

	t.Setenv("RATE_LIMIT_RPS", "not-a-number")
	t.Setenv("CORS_MAX_AGE", "12.5")
	t.Setenv("CB_FAILURE_RATIO", "not-a-float")

	cfg := Load()

	assert.Equal(t, 100, cfg.RateLimitRPS)
	assert.Equal(t, 300, cfg.CORSMaxAge)
	assert.InDelta(t, 0.6, cfg.CBFailureRatio, 1e-9)
}

func TestLoad_EmptySliceVarFallsBackToDefault(t *testing.T) {
	clearEnv(t)

	// getEnvSlice treats "" as absent so an accidentally blank variable does
	// not produce a one-element slice containing the empty string.
	t.Setenv("CORS_ALLOWED_ORIGINS", "")

	cfg := Load()

	assert.Equal(t, []string{"http://localhost:3000", "http://localhost:4200", "https://localhost", "capacitor://localhost"}, cfg.CORSAllowedOrigins)
}

func TestLoad_EmptyStringVarBeatsDefault(t *testing.T) {
	clearEnv(t)

	// getEnv uses LookupEnv, so a set-but-empty variable wins over the default.
	t.Setenv("PORT", "")

	cfg := Load()

	assert.Equal(t, "", cfg.Port)
}

func TestValidate(t *testing.T) {
	tests := []struct {
		name    string
		secret  string
		wantErr string
	}{
		{name: "missing secret is rejected", secret: "", wantErr: "JWT_SECRET"},
		{name: "present secret is accepted", secret: "s3cret"},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			err := (&Config{JWTSecret: tt.secret}).Validate()

			if tt.wantErr == "" {
				require.NoError(t, err)
				return
			}
			require.Error(t, err)
			assert.Contains(t, err.Error(), tt.wantErr)
		})
	}
}

func TestServiceRoutes(t *testing.T) {
	cfg := &Config{
		AuthServiceURL:         "http://auth:1",
		FileServiceURL:         "http://file:2",
		DocumentServiceURL:     "http://doc:3",
		CollabServiceURL:       "http://collab:4",
		NotificationServiceURL: "http://notify:5",
		SearchServiceURL:       "http://search:6",
		AnalyticsServiceURL:    "http://analytics:7",
		AdminServiceURL:        "http://admin:8",
		AuditServiceURL:        "http://audit:9",
		ReportServiceURL:       "http://report:10",
	}

	routes := cfg.ServiceRoutes()

	assert.Equal(t, map[string]string{
		"/api/v1/auth":          "http://auth:1",
		"/api/v1/files":         "http://file:2",
		"/api/v1/folders":       "http://file:2",
		"/api/v1/documents":     "http://doc:3",
		"/api/v1/templates":     "http://doc:3",
		"/api/v1/collab":        "http://collab:4",
		"/socket.io":            "http://collab:4",
		"/api/v1/notifications": "http://notify:5",
		"/api/v1/preferences":   "http://notify:5",
		"/api/v1/search":        "http://search:6",
		"/api/v1/analytics":     "http://analytics:7",
		"/api/v1/admin":         "http://admin:8",
		"/api/v1/audit":         "http://audit:9",
		"/api/v1/reports":       "http://report:10",
		"/api/v1/settings":      "http://auth:1",
	}, routes)
}
