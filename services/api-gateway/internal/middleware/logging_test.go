package middleware

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/rs/zerolog"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func decodeLogLine(t *testing.T, buf *bytes.Buffer) map[string]interface{} {
	t.Helper()
	var entry map[string]interface{}
	require.NoError(t, json.Unmarshal(buf.Bytes(), &entry))
	return entry
}

func TestLogger_LevelPerStatusClass(t *testing.T) {
	tests := []struct {
		name      string
		status    int
		wantLevel string
	}{
		{name: "2xx logs at info", status: http.StatusOK, wantLevel: "info"},
		{name: "3xx logs at info", status: http.StatusFound, wantLevel: "info"},
		{name: "4xx logs at warn", status: http.StatusNotFound, wantLevel: "warn"},
		{name: "5xx logs at error", status: http.StatusBadGateway, wantLevel: "error"},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			var buf bytes.Buffer
			logger := zerolog.New(&buf)

			handler := Logger(logger)(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
				w.WriteHeader(tt.status)
				_, _ = w.Write([]byte("body"))
			}))

			req := httptest.NewRequest(http.MethodPost, "/api/v1/files/1?a=b", nil)
			req.RemoteAddr = "10.0.0.9:5555"
			req.Header.Set("User-Agent", "otter-test/1.0")
			rec := httptest.NewRecorder()
			handler.ServeHTTP(rec, req)

			require.Equal(t, tt.status, rec.Code)
			entry := decodeLogLine(t, &buf)
			assert.Equal(t, tt.wantLevel, entry["level"])
			assert.Equal(t, "request completed", entry["message"])
			assert.Equal(t, http.MethodPost, entry["method"])
			assert.Equal(t, "/api/v1/files/1", entry["path"])
			assert.Equal(t, "a=b", entry["query"])
			assert.Equal(t, float64(tt.status), entry["status"])
			assert.Equal(t, float64(4), entry["bytes"])
			assert.Equal(t, "10.0.0.9:5555", entry["remote_addr"])
			assert.Equal(t, "otter-test/1.0", entry["user_agent"])
			assert.Equal(t, "HTTP/1.1", entry["protocol"])
			assert.Contains(t, entry, "latency_ms")
		})
	}
}

func TestLogger_ImplicitStatusIsLoggedAsOK(t *testing.T) {
	var buf bytes.Buffer

	handler := Logger(zerolog.New(&buf))(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		_, _ = w.Write([]byte("implicit"))
	}))
	handler.ServeHTTP(httptest.NewRecorder(), httptest.NewRequest(http.MethodGet, "/health", nil))

	entry := decodeLogLine(t, &buf)
	assert.Equal(t, "info", entry["level"])
	assert.Equal(t, float64(http.StatusOK), entry["status"])
	assert.Equal(t, float64(len("implicit")), entry["bytes"])
}

func TestLogger_IncludesRequestIDFromContext(t *testing.T) {
	var buf bytes.Buffer

	handler := RequestID(Logger(zerolog.New(&buf))(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusOK)
	})))

	req := httptest.NewRequest(http.MethodGet, "/api/v1/auth/me", nil)
	req.Header.Set("X-Request-ID", "req-abc-123")
	handler.ServeHTTP(httptest.NewRecorder(), req)

	assert.Equal(t, "req-abc-123", decodeLogLine(t, &buf)["request_id"])
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
		{level: "nonsense", want: zerolog.InfoLevel},
		{level: "", want: zerolog.InfoLevel},
	}

	for _, tt := range tests {
		t.Run("level="+tt.level, func(t *testing.T) {
			// Start from a level that is never the expected result so the
			// assertion cannot pass by accident.
			zerolog.SetGlobalLevel(zerolog.PanicLevel)

			SetLogLevel(tt.level)

			assert.Equal(t, tt.want, zerolog.GlobalLevel())
		})
	}
}
