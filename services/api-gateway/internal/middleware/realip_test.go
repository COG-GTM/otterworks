package middleware

import (
	"fmt"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestParseTrustedProxies(t *testing.T) {
	tp, err := ParseTrustedProxies([]string{"10.0.0.0/8", " 192.168.1.10 ", ""})
	require.NoError(t, err)

	assert.True(t, tp.Contains("10.1.2.3"))
	assert.True(t, tp.Contains("192.168.1.10"))
	assert.False(t, tp.Contains("192.168.1.11"))
	assert.False(t, tp.Contains("203.0.113.5"))
	assert.False(t, tp.Contains("not-an-ip"))

	_, err = ParseTrustedProxies([]string{"nonsense"})
	require.Error(t, err)
}

func TestClientIP(t *testing.T) {
	trusted, err := ParseTrustedProxies([]string{"10.0.0.0/8"})
	require.NoError(t, err)

	tests := []struct {
		name       string
		remoteAddr string
		headers    map[string]string
		trusted    *TrustedProxies
		expected   string
	}{
		{
			name:       "untrusted peer keeps its socket address",
			remoteAddr: "203.0.113.9:4321",
			headers:    map[string]string{"X-Forwarded-For": "10.9.0.1"},
			trusted:    trusted,
			expected:   "203.0.113.9",
		},
		{
			name:       "no trusted proxies configured ignores forwarding headers",
			remoteAddr: "10.0.0.1:4321",
			headers:    map[string]string{"X-Forwarded-For": "10.9.0.1"},
			trusted:    nil,
			expected:   "10.0.0.1",
		},
		{
			name:       "trusted peer honours the rightmost untrusted hop",
			remoteAddr: "10.0.0.1:4321",
			headers:    map[string]string{"X-Forwarded-For": "1.2.3.4, 203.0.113.9, 10.0.0.2"},
			trusted:    trusted,
			expected:   "203.0.113.9",
		},
		{
			name:       "trusted peer falls back to the socket when every hop is trusted",
			remoteAddr: "10.0.0.1:4321",
			headers:    map[string]string{"X-Forwarded-For": "10.0.0.2, 10.0.0.3"},
			trusted:    trusted,
			expected:   "10.0.0.1",
		},
		{
			name:       "trusted peer skips malformed hops",
			remoteAddr: "10.0.0.1:4321",
			headers:    map[string]string{"X-Forwarded-For": "203.0.113.9, unknown"},
			trusted:    trusted,
			expected:   "203.0.113.9",
		},
		{
			name:       "trusted peer uses X-Real-IP when no X-Forwarded-For is present",
			remoteAddr: "10.0.0.1:4321",
			headers:    map[string]string{"X-Real-IP": "198.51.100.7"},
			trusted:    trusted,
			expected:   "198.51.100.7",
		},
		{
			name:       "untrusted peer without headers keeps its socket address",
			remoteAddr: "[2001:db8::1]:4321",
			trusted:    trusted,
			expected:   "2001:db8::1",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			req := httptest.NewRequest(http.MethodGet, "/", nil)
			req.RemoteAddr = tt.remoteAddr
			for k, v := range tt.headers {
				req.Header.Set(k, v)
			}
			require.Equal(t, tt.expected, ClientIP(req, tt.trusted))
		})
	}
}

func TestRealIP_RewritesRemoteAddr(t *testing.T) {
	trusted, err := ParseTrustedProxies([]string{"10.0.0.0/8"})
	require.NoError(t, err)

	var seen string
	handler := RealIP(trusted)(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		seen = r.RemoteAddr
	}))

	req := httptest.NewRequest(http.MethodGet, "/", nil)
	req.RemoteAddr = "10.0.0.1:4321"
	req.Header.Set("X-Forwarded-For", "198.51.100.7")
	handler.ServeHTTP(httptest.NewRecorder(), req)
	assert.Equal(t, "198.51.100.7", seen)

	req = httptest.NewRequest(http.MethodGet, "/", nil)
	req.RemoteAddr = "203.0.113.9:4321"
	req.Header.Set("X-Forwarded-For", "198.51.100.7")
	handler.ServeHTTP(httptest.NewRecorder(), req)
	assert.Equal(t, "203.0.113.9", seen)
}

// A spoofed forwarding header from an untrusted peer must not hand the caller a
// fresh token bucket for every request.
func TestRateLimiter_SpoofedForwardedForCannotBypass(t *testing.T) {
	trusted, err := ParseTrustedProxies(nil)
	require.NoError(t, err)

	rl := NewRateLimiter(2)
	handler := RealIP(trusted)(rl.Handler(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	})))

	statuses := make([]int, 0, 4)
	for i := 0; i < 4; i++ {
		req := httptest.NewRequest(http.MethodGet, "/test", nil)
		req.RemoteAddr = "203.0.113.9:4321"
		req.Header.Set("X-Forwarded-For", fmt.Sprintf("10.9.0.%d", i+1))
		rec := httptest.NewRecorder()
		handler.ServeHTTP(rec, req)
		statuses = append(statuses, rec.Code)
	}

	assert.Equal(t, []int{http.StatusOK, http.StatusOK, http.StatusTooManyRequests, http.StatusTooManyRequests}, statuses)
}
