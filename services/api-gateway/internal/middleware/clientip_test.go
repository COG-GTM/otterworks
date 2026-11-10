package middleware

import (
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestResolveClientOrigin(t *testing.T) {
	trust, err := NewProxyTrust([]string{"10.0.0.0/8", "192.168.1.1"})
	require.NoError(t, err)

	cases := []struct {
		name      string
		peer      string
		xff       []string
		realIP    string
		wantIP    string
		wantChain []string
	}{
		{"untrusted peer ignores spoofed headers", "203.0.113.7:1", []string{"1.2.3.4"}, "5.6.7.8", "203.0.113.7", nil},
		{"trusted peer without headers", "10.0.0.5:1", nil, "", "10.0.0.5", nil},
		{"trusted peer with X-Real-IP only", "10.0.0.5:1", nil, "198.51.100.2", "198.51.100.2", []string{"198.51.100.2"}},
		{"trusted peer single hop", "10.0.0.5:1", []string{"198.51.100.2"}, "", "198.51.100.2", []string{"198.51.100.2"}},
		{"client-prepended spoof is skipped", "10.0.0.5:1", []string{"1.2.3.4, 198.51.100.2, 10.0.0.9"}, "", "198.51.100.2", []string{"198.51.100.2", "10.0.0.9"}},
		{"multiple XFF headers", "192.168.1.1:1", []string{"1.2.3.4", "198.51.100.2"}, "", "198.51.100.2", []string{"198.51.100.2"}},
		{"all hops trusted", "10.0.0.5:1", []string{"10.0.0.7, 10.0.0.8"}, "", "10.0.0.7", []string{"10.0.0.7", "10.0.0.8"}},
		{"garbage hop stops the walk", "10.0.0.5:1", []string{"198.51.100.2, not-an-ip"}, "", "10.0.0.5", nil},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			req := httptest.NewRequest(http.MethodGet, "/", nil)
			req.RemoteAddr = tc.peer
			for _, v := range tc.xff {
				req.Header.Add("X-Forwarded-For", v)
			}
			if tc.realIP != "" {
				req.Header.Set("X-Real-IP", tc.realIP)
			}
			got := ResolveClientOrigin(req, trust)
			assert.Equal(t, tc.wantIP, got.IP)
			assert.Equal(t, tc.wantChain, got.Forwarded)
		})
	}
}

func TestNewProxyTrust_RejectsInvalid(t *testing.T) {
	_, err := NewProxyTrust([]string{"not-a-cidr"})
	assert.Error(t, err)
	_, err = NewProxyTrust([]string{"10.0.0.0/99"})
	assert.Error(t, err)
}

func TestRateLimiter_KeysOnResolvedClientIP(t *testing.T) {
	trust, err := NewProxyTrust([]string{"10.0.0.0/8"})
	require.NoError(t, err)
	rl := NewRateLimiter(1)
	handler := ClientOriginMiddleware(trust)(rl.Handler(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	})))

	send := func(client string) int {
		req := httptest.NewRequest(http.MethodGet, "/", nil)
		req.RemoteAddr = "10.0.0.5:1"
		req.Header.Set("X-Forwarded-For", client)
		rec := httptest.NewRecorder()
		handler.ServeHTTP(rec, req)
		return rec.Code
	}
	assert.Equal(t, http.StatusOK, send("198.51.100.1"))
	assert.Equal(t, http.StatusOK, send("198.51.100.2"), "clients behind the same proxy get separate buckets")
	assert.Equal(t, http.StatusTooManyRequests, send("198.51.100.1"))
}
