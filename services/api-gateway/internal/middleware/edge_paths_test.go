package middleware

import (
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/stretchr/testify/assert"
)

func TestCORS_OptionsWithoutOriginPassesThrough(t *testing.T) {
	called := false
	h := CORS(CORSConfig{AllowedOrigins: []string{"*"}, AllowedMethods: []string{"GET"}})(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		called = true
		w.WriteHeader(http.StatusOK)
	}))
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, httptest.NewRequest(http.MethodOptions, "/api/v1/files", nil))
	assert.True(t, called)
	assert.Equal(t, http.StatusOK, rec.Code)
	assert.Empty(t, rec.Header().Get("Access-Control-Allow-Methods"))
}

func TestJWTAuth_ExactProtectedPrefixRequiresAuth(t *testing.T) {
	h := JWTAuth(JWTConfig{Secret: testSecret, ProtectedPrefixPath: []string{"/api/v1/files"}})(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		t.Error("handler must not be reached")
	}))
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/api/v1/files", nil))
	assert.Equal(t, http.StatusUnauthorized, rec.Code)
}
