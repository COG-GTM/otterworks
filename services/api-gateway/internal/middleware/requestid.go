package middleware

import (
	"context"
	"net/http"
	"regexp"

	"github.com/google/uuid"
)

type contextKey string

const requestIDKey contextKey = "request_id"

// validRequestID bounds client-supplied IDs so they are safe to log and forward.
var validRequestID = regexp.MustCompile(`^[A-Za-z0-9._:\-]{1,128}$`)

// RequestID generates a unique UUID for each request and propagates it
// via the X-Request-ID header and request context. A client-supplied ID is
// kept only if it is well-formed; otherwise a new one is generated.
func RequestID(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		id := r.Header.Get("X-Request-ID")
		if !validRequestID.MatchString(id) {
			id = uuid.New().String()
		}

		ctx := context.WithValue(r.Context(), requestIDKey, id)
		w.Header().Set("X-Request-ID", id)
		next.ServeHTTP(w, r.WithContext(ctx))
	})
}

// GetRequestID retrieves the request ID from the context.
func GetRequestID(ctx context.Context) string {
	if id, ok := ctx.Value(requestIDKey).(string); ok {
		return id
	}
	return ""
}
