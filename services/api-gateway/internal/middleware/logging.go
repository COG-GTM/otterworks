package middleware

import (
	"net/http"
	"net/url"
	"strings"
	"time"

	"github.com/go-chi/chi/v5/middleware"
	"github.com/rs/zerolog"
	"github.com/rs/zerolog/log"
)

// Logger returns an HTTP middleware that logs each request using zerolog.
func Logger(logger zerolog.Logger) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			start := time.Now()
			ww := middleware.NewWrapResponseWriter(w, r.ProtoMajor)

			next.ServeHTTP(ww, r)

			duration := time.Since(start)
			requestID := GetRequestID(r.Context())

			var event *zerolog.Event
			status := ww.Status()
			switch {
			case status >= 500:
				event = logger.Error()
			case status >= 400:
				event = logger.Warn()
			default:
				event = logger.Info()
			}

			event.
				Str("request_id", requestID).
				Str("method", r.Method).
				Str("path", r.URL.Path).
				Str("query", RedactQuery(r.URL.RawQuery)).
				Int("status", status).
				Int("bytes", ww.BytesWritten()).
				Dur("latency_ms", duration).
				Str("remote_addr", r.RemoteAddr).
				Str("user_agent", r.UserAgent()).
				Str("protocol", r.Proto).
				Msg("request completed")
		})
	}
}

// credentialQueryParams are query parameters whose values are bearer
// credentials (e.g. WebSocket clients that put a JWT in the URL).
var credentialQueryParams = map[string]struct{}{
	"token":         {},
	"access_token":  {},
	"refresh_token": {},
	"id_token":      {},
	"jwt":           {},
}

// RedactQuery replaces the values of credential query parameters so request
// logs never contain tokens. Parameter order and other values are preserved.
func RedactQuery(rawQuery string) string {
	if rawQuery == "" {
		return rawQuery
	}
	pairs := strings.Split(rawQuery, "&")
	for i, pair := range pairs {
		key, _, hasValue := strings.Cut(pair, "=")
		name, err := url.QueryUnescape(key)
		if err != nil {
			name = key
		}
		if _, sensitive := credentialQueryParams[strings.ToLower(name)]; sensitive && hasValue {
			pairs[i] = key + "=REDACTED"
		}
	}
	return strings.Join(pairs, "&")
}

// SetLogLevel configures the global zerolog level.
func SetLogLevel(level string) {
	switch level {
	case "debug":
		zerolog.SetGlobalLevel(zerolog.DebugLevel)
	case "info":
		zerolog.SetGlobalLevel(zerolog.InfoLevel)
	case "warn":
		zerolog.SetGlobalLevel(zerolog.WarnLevel)
	case "error":
		zerolog.SetGlobalLevel(zerolog.ErrorLevel)
	default:
		zerolog.SetGlobalLevel(zerolog.InfoLevel)
	}
	log.Debug().Str("level", level).Msg("log level set")
}
