package middleware

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestRequestID_GeneratesUUID(t *testing.T) {
	handler := RequestID(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		id := GetRequestID(r.Context())
		require.NotEmpty(t, id)
		w.WriteHeader(http.StatusOK)
	}))

	req := httptest.NewRequest(http.MethodGet, "/", nil)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	assert.Equal(t, http.StatusOK, rec.Code)
	assert.NotEmpty(t, rec.Header().Get("X-Request-ID"))
}

func TestRequestID_PropagatesExisting(t *testing.T) {
	existingID := "existing-request-id-123"

	var capturedID string
	handler := RequestID(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		capturedID = GetRequestID(r.Context())
		w.WriteHeader(http.StatusOK)
	}))

	req := httptest.NewRequest(http.MethodGet, "/", nil)
	req.Header.Set("X-Request-ID", existingID)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	assert.Equal(t, existingID, capturedID)
	assert.Equal(t, existingID, rec.Header().Get("X-Request-ID"))
}

func TestGetRequestID_EmptyContext(t *testing.T) {
	req := httptest.NewRequest(http.MethodGet, "/", nil)
	id := GetRequestID(req.Context())
	assert.Empty(t, id)
}

func TestRequestID_ReplacesMalformedID(t *testing.T) {
	for _, bad := range []string{"has space", "line\nbreak", strings.Repeat("a", 129)} {
		var capturedID string
		handler := RequestID(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			capturedID = GetRequestID(r.Context())
		}))
		req := httptest.NewRequest(http.MethodGet, "/", nil)
		req.Header["X-Request-Id"] = []string{bad}
		handler.ServeHTTP(httptest.NewRecorder(), req)

		assert.NotEqual(t, bad, capturedID)
		assert.Regexp(t, `^[0-9a-f-]{36}$`, capturedID)
	}
}
