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

func captureLog(t *testing.T, handler http.Handler, req *http.Request) (map[string]any, *httptest.ResponseRecorder) {
	t.Helper()

	var buf bytes.Buffer
	logger := zerolog.New(&buf)
	rec := httptest.NewRecorder()

	Logger(logger)(handler).ServeHTTP(rec, req)

	var entry map[string]any
	require.NoError(t, json.Unmarshal(bytes.TrimSpace(buf.Bytes()), &entry), "log output: %q", buf.String())
	return entry, rec
}

func TestLogger_RecordsRequestDetails(t *testing.T) {
	handler := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("hello"))
	})

	req := httptest.NewRequest(http.MethodPost, "/api/v1/files?page=2", nil)
	req.RemoteAddr = "10.1.2.3:5555"
	req.Header.Set("User-Agent", "otter-test/1.0")
	// Logger runs inside RequestID in the real stack, so the ID is already in
	// the context by the time the log line is written.
	req = req.WithContext(context.WithValue(req.Context(), requestIDKey, "req-123"))

	entry, rec := captureLog(t, handler, req)

	assert.Equal(t, http.StatusOK, rec.Code)
	assert.Equal(t, "request completed", entry["message"])
	assert.Equal(t, "info", entry["level"])
	assert.Equal(t, http.MethodPost, entry["method"])
	assert.Equal(t, "/api/v1/files", entry["path"])
	assert.Equal(t, "page=2", entry["query"])
	assert.Equal(t, float64(http.StatusOK), entry["status"])
	assert.Equal(t, float64(len("hello")), entry["bytes"])
	assert.Equal(t, "10.1.2.3:5555", entry["remote_addr"])
	assert.Equal(t, "otter-test/1.0", entry["user_agent"])
	assert.Equal(t, "HTTP/1.1", entry["protocol"])
	assert.Equal(t, "req-123", entry["request_id"])
}

func TestLogger_LevelFollowsStatusClass(t *testing.T) {
	tests := []struct {
		name      string
		status    int
		wantLevel string
	}{
		{name: "success logs at info", status: http.StatusOK, wantLevel: "info"},
		{name: "redirect logs at info", status: http.StatusFound, wantLevel: "info"},
		{name: "client error logs at warn", status: http.StatusNotFound, wantLevel: "warn"},
		{name: "server error logs at error", status: http.StatusBadGateway, wantLevel: "error"},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			handler := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				w.WriteHeader(tt.status)
			})

			entry, rec := captureLog(t, handler, httptest.NewRequest(http.MethodGet, "/x", nil))

			assert.Equal(t, tt.status, rec.Code)
			assert.Equal(t, tt.wantLevel, entry["level"])
			assert.Equal(t, float64(tt.status), entry["status"])
		})
	}
}

func TestLogger_EmptyRequestIDWhenMiddlewareAbsent(t *testing.T) {
	handler := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {})

	entry, _ := captureLog(t, handler, httptest.NewRequest(http.MethodGet, "/x", nil))

	assert.Equal(t, "", entry["request_id"])
}

func TestSetLogLevel(t *testing.T) {
	original := zerolog.GlobalLevel()
	t.Cleanup(func() { zerolog.SetGlobalLevel(original) })

	tests := []struct {
		name  string
		level string
		want  zerolog.Level
	}{
		{name: "debug", level: "debug", want: zerolog.DebugLevel},
		{name: "info", level: "info", want: zerolog.InfoLevel},
		{name: "warn", level: "warn", want: zerolog.WarnLevel},
		{name: "error", level: "error", want: zerolog.ErrorLevel},
		{name: "unrecognised value falls back to info", level: "shout", want: zerolog.InfoLevel},
		{name: "empty value falls back to info", level: "", want: zerolog.InfoLevel},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			// Start from a level none of the cases expect, so a no-op would fail.
			zerolog.SetGlobalLevel(zerolog.PanicLevel)

			SetLogLevel(tt.level)

			assert.Equal(t, tt.want, zerolog.GlobalLevel())
		})
	}
}
