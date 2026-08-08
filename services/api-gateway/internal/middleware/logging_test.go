package middleware

import (
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/rs/zerolog"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

// captureLog runs a request through the Logger middleware and returns the
// single JSON log line it emitted.
func captureLog(t *testing.T, req *http.Request, next http.Handler) map[string]interface{} {
	t.Helper()

	var buf bytes.Buffer
	logger := zerolog.New(&buf).Level(zerolog.DebugLevel)

	rec := httptest.NewRecorder()
	Logger(logger)(next).ServeHTTP(rec, req)

	var entry map[string]interface{}
	require.NoError(t, json.Unmarshal(bytes.TrimSpace(buf.Bytes()), &entry))
	return entry
}

func TestLogger_LogLevelPerStatus(t *testing.T) {
	tests := []struct {
		name      string
		status    int
		wantLevel string
	}{
		{name: "2xx logs at info", status: http.StatusOK, wantLevel: "info"},
		{name: "3xx logs at info", status: http.StatusFound, wantLevel: "info"},
		{name: "4xx logs at warn", status: http.StatusNotFound, wantLevel: "warn"},
		{name: "5xx logs at error", status: http.StatusInternalServerError, wantLevel: "error"},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				w.WriteHeader(tt.status)
			})

			entry := captureLog(t, httptest.NewRequest(http.MethodGet, "/api/v1/files", nil), next)

			assert.Equal(t, tt.wantLevel, entry["level"])
			assert.Equal(t, float64(tt.status), entry["status"])
			assert.Equal(t, "request completed", entry["message"])
		})
	}
}

func TestLogger_RecordsRequestDetails(t *testing.T) {
	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("hello"))
	})

	req := httptest.NewRequest(http.MethodPost, "/api/v1/files?limit=10", nil)
	req.Header.Set("User-Agent", "otter-test/1.0")
	req.RemoteAddr = "10.0.0.7:5555"
	req = req.WithContext(context.WithValue(req.Context(), requestIDKey, "req-123"))

	entry := captureLog(t, req, next)

	assert.Equal(t, "req-123", entry["request_id"])
	assert.Equal(t, http.MethodPost, entry["method"])
	assert.Equal(t, "/api/v1/files", entry["path"])
	assert.Equal(t, "limit=10", entry["query"])
	assert.Equal(t, float64(len("hello")), entry["bytes"])
	assert.Equal(t, "10.0.0.7:5555", entry["remote_addr"])
	assert.Equal(t, "otter-test/1.0", entry["user_agent"])
	assert.Equal(t, "HTTP/1.1", entry["protocol"])
	assert.Contains(t, entry, "latency_ms")
}

func TestLogger_MissingRequestIDLogsEmptyString(t *testing.T) {
	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {})

	entry := captureLog(t, httptest.NewRequest(http.MethodGet, "/", nil), next)

	assert.Equal(t, "", entry["request_id"])
	// A handler that writes nothing at all leaves the wrapper's status at 0,
	// which falls through to the info branch.
	assert.Equal(t, float64(0), entry["status"])
	assert.Equal(t, "info", entry["level"])
}

func TestSetLogLevel(t *testing.T) {
	original := zerolog.GlobalLevel()
	t.Cleanup(func() { zerolog.SetGlobalLevel(original) })

	tests := []struct {
		level string
		want  zerolog.Level
	}{
		{level: "debug", want: zerolog.DebugLevel},
		{level: "info", want: zerolog.InfoLevel},
		{level: "warn", want: zerolog.WarnLevel},
		{level: "error", want: zerolog.ErrorLevel},
		{level: "gibberish", want: zerolog.InfoLevel},
		{level: "", want: zerolog.InfoLevel},
	}

	for _, tt := range tests {
		t.Run("level="+tt.level, func(t *testing.T) {
			SetLogLevel(tt.level)
			assert.Equal(t, tt.want, zerolog.GlobalLevel())
		})
	}
}
