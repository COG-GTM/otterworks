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

func TestLogger_LevelPerStatus(t *testing.T) {
	tests := []struct {
		name      string
		status    int
		wantLevel string
	}{
		{name: "success logs info", status: http.StatusOK, wantLevel: "info"},
		{name: "client error logs warn", status: http.StatusNotFound, wantLevel: "warn"},
		{name: "server error logs error", status: http.StatusInternalServerError, wantLevel: "error"},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			var buf bytes.Buffer
			logger := zerolog.New(&buf).Level(zerolog.DebugLevel)

			handler := Logger(logger)(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
				w.WriteHeader(tt.status)
				_, _ = w.Write([]byte("body"))
			}))

			req := httptest.NewRequest(http.MethodPost, "/api/v1/files/1?page=2", nil)
			req.Header.Set("User-Agent", "coverage-test")
			req.RemoteAddr = "10.0.0.7:5555"
			rec := httptest.NewRecorder()

			handler.ServeHTTP(rec, req)

			require.Equal(t, tt.status, rec.Code)

			var entry map[string]any
			require.NoError(t, json.Unmarshal(buf.Bytes(), &entry))
			assert.Equal(t, tt.wantLevel, entry["level"])
			assert.Equal(t, "request completed", entry["message"])
			assert.Equal(t, http.MethodPost, entry["method"])
			assert.Equal(t, "/api/v1/files/1", entry["path"])
			assert.Equal(t, "page=2", entry["query"])
			assert.Equal(t, float64(tt.status), entry["status"])
			assert.Equal(t, float64(4), entry["bytes"])
			assert.Equal(t, "10.0.0.7:5555", entry["remote_addr"])
			assert.Equal(t, "coverage-test", entry["user_agent"])
			assert.Equal(t, "HTTP/1.1", entry["protocol"])
			assert.Empty(t, entry["request_id"])
		})
	}
}

func TestLogger_IncludesRequestID(t *testing.T) {
	var buf bytes.Buffer
	handler := RequestID(Logger(zerolog.New(&buf))(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusOK)
	})))

	req := httptest.NewRequest(http.MethodGet, "/health", nil)
	req.Header.Set("X-Request-ID", "req-42")
	rec := httptest.NewRecorder()

	handler.ServeHTTP(rec, req)

	var entry map[string]any
	require.NoError(t, json.Unmarshal(buf.Bytes(), &entry))
	assert.Equal(t, "req-42", entry["request_id"])
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
	}

	for _, tt := range tests {
		t.Run(tt.level, func(t *testing.T) {
			SetLogLevel(tt.level)
			assert.Equal(t, tt.want, zerolog.GlobalLevel())
		})
	}
}
