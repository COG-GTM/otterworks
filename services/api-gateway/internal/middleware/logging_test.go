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

func TestLogger_LevelByStatus(t *testing.T) {
	cases := []struct {
		status int
		level  string
	}{
		{http.StatusOK, "info"},
		{http.StatusNotFound, "warn"},
		{http.StatusBadGateway, "error"},
	}
	for _, tc := range cases {
		t.Run(tc.level, func(t *testing.T) {
			var buf bytes.Buffer
			logger := zerolog.New(&buf)
			h := RequestID(Logger(logger)(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				w.WriteHeader(tc.status)
				_, _ = w.Write([]byte("hello"))
			})))

			req := httptest.NewRequest(http.MethodPost, "/api/v1/files/x?a=b", nil)
			req.Header.Set("User-Agent", "otter-test")
			rec := httptest.NewRecorder()
			h.ServeHTTP(rec, req)

			var entry map[string]interface{}
			require.NoError(t, json.Unmarshal(buf.Bytes(), &entry))
			assert.Equal(t, tc.level, entry["level"])
			assert.Equal(t, "request completed", entry["message"])
			assert.Equal(t, "POST", entry["method"])
			assert.Equal(t, "/api/v1/files/x", entry["path"])
			assert.Equal(t, "a=b", entry["query"])
			assert.Equal(t, float64(tc.status), entry["status"])
			assert.Equal(t, float64(5), entry["bytes"])
			assert.Equal(t, "otter-test", entry["user_agent"])
			assert.Equal(t, rec.Header().Get("X-Request-ID"), entry["request_id"])
			assert.NotEmpty(t, entry["request_id"])
		})
	}
}

func TestSetLogLevel(t *testing.T) {
	orig := zerolog.GlobalLevel()
	t.Cleanup(func() { zerolog.SetGlobalLevel(orig) })

	cases := map[string]zerolog.Level{
		"debug":   zerolog.DebugLevel,
		"info":    zerolog.InfoLevel,
		"warn":    zerolog.WarnLevel,
		"error":   zerolog.ErrorLevel,
		"verbose": zerolog.InfoLevel,
	}
	for in, want := range cases {
		SetLogLevel(in)
		assert.Equal(t, want, zerolog.GlobalLevel(), in)
	}
}
