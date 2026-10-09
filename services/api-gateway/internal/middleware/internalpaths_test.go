package middleware

import (
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/stretchr/testify/assert"
)

func TestBlockInternalPaths(t *testing.T) {
	handler := BlockInternalPaths(DefaultInternalOnlyPaths())(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusOK)
	}))

	cases := map[string]int{
		"/api/v1/admin/alerts/ingest":          http.StatusNotFound,
		"/api/v1/admin/alerts/ingest/":         http.StatusNotFound,
		"/api/v1/admin/alerts/ingest.json":     http.StatusNotFound,
		"/API/v1/Admin/Alerts/Ingest":          http.StatusNotFound,
		"//api/v1/admin//alerts/ingest":        http.StatusNotFound,
		"/api/v1/admin/../admin/alerts/ingest": http.StatusNotFound,
		"/api/v1/admin/alerts":                 http.StatusOK,
		"/api/v1/admin/incidents":              http.StatusOK,
		"/api/v1/files/upload":                 http.StatusOK,
	}
	for p, want := range cases {
		req := httptest.NewRequest(http.MethodPost, "/", nil)
		req.URL.Path = p
		rec := httptest.NewRecorder()
		handler.ServeHTTP(rec, req)
		assert.Equal(t, want, rec.Code, p)
	}
}
