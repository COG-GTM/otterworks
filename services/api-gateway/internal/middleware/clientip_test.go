package middleware

import (
	"net"
	"net/http"
	"net/http/httptest"
	"net/http/httputil"
	"net/url"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func mustTrusted(t *testing.T, entries ...string) []*net.IPNet {
	t.Helper()
	nets, err := ParseTrustedProxies(entries)
	require.NoError(t, err)
	return nets
}

func TestParseTrustedProxies(t *testing.T) {
	nets, err := ParseTrustedProxies([]string{" 10.0.0.0/8 ", "", "192.0.2.10", "fd00::1"})
	require.NoError(t, err)
	require.Len(t, nets, 3)
	assert.True(t, isTrusted(net.ParseIP("10.1.2.3"), nets))
	assert.True(t, isTrusted(net.ParseIP("192.0.2.10"), nets))
	assert.False(t, isTrusted(net.ParseIP("192.0.2.11"), nets))
	assert.True(t, isTrusted(net.ParseIP("fd00::1"), nets))

	nets, err = ParseTrustedProxies(nil)
	require.NoError(t, err)
	assert.Empty(t, nets)

	_, err = ParseTrustedProxies([]string{"not-an-ip"})
	assert.Error(t, err)
	_, err = ParseTrustedProxies([]string{"10.0.0.0/33"})
	assert.Error(t, err)
}

func TestClientIP_Resolve(t *testing.T) {
	ingress := mustTrusted(t, "10.0.0.0/8")
	tests := []struct {
		name       string
		trusted    []*net.IPNet
		remoteAddr string
		headers    map[string]string
		expected   string
	}{
		{
			name:       "no trusted proxies ignores every forwarding header",
			remoteAddr: "198.51.100.7:4000",
			headers: map[string]string{
				"True-Client-IP":  "203.0.113.1",
				"X-Real-IP":       "203.0.113.2",
				"X-Forwarded-For": "203.0.113.3",
			},
			expected: "198.51.100.7",
		},
		{
			name:       "untrusted peer cannot spoof X-Forwarded-For",
			trusted:    ingress,
			remoteAddr: "198.51.100.7:4000",
			headers:    map[string]string{"X-Forwarded-For": "10.9.0.1"},
			expected:   "198.51.100.7",
		},
		{
			name:       "trusted peer: X-Forwarded-For client used",
			trusted:    ingress,
			remoteAddr: "10.0.1.5:4000",
			headers:    map[string]string{"X-Forwarded-For": "203.0.113.9"},
			expected:   "203.0.113.9",
		},
		{
			name:       "trusted peer: True-Client-IP and X-Real-IP never honoured",
			trusted:    ingress,
			remoteAddr: "10.0.1.5:4000",
			headers: map[string]string{
				"True-Client-IP":  "203.0.113.1",
				"X-Real-IP":       "203.0.113.2",
				"X-Forwarded-For": "203.0.113.9",
			},
			expected: "203.0.113.9",
		},
		{
			name:       "right-most untrusted hop wins over a client-prepended value",
			trusted:    ingress,
			remoteAddr: "10.0.1.5:4000",
			headers:    map[string]string{"X-Forwarded-For": "1.2.3.4, 203.0.113.9, 10.0.2.7"},
			expected:   "203.0.113.9",
		},
		{
			name:       "trusted peer without X-Forwarded-For is the client",
			trusted:    ingress,
			remoteAddr: "10.0.1.5:4000",
			expected:   "10.0.1.5",
		},
		{
			name:       "malformed hop stops the walk at the last vouched address",
			trusted:    ingress,
			remoteAddr: "10.0.1.5:4000",
			headers:    map[string]string{"X-Forwarded-For": "203.0.113.9, garbage"},
			expected:   "10.0.1.5",
		},
		{
			name:       "IPv6 peer",
			remoteAddr: "[2001:db8::1]:4000",
			headers:    map[string]string{"X-Forwarded-For": "203.0.113.9"},
			expected:   "2001:db8::1",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			var seen *http.Request
			handler := ClientIP(tt.trusted)(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				seen = r
			}))
			req := httptest.NewRequest(http.MethodGet, "/", nil)
			req.RemoteAddr = tt.remoteAddr
			for k, v := range tt.headers {
				req.Header.Set(k, v)
			}
			handler.ServeHTTP(httptest.NewRecorder(), req)

			require.NotNil(t, seen)
			assert.Equal(t, tt.expected, extractIP(seen))
			assert.Equal(t, tt.expected, seen.Header.Get("X-Real-IP"))
			assert.Empty(t, seen.Header.Get("True-Client-IP"))
			assert.Empty(t, seen.Header.Get("X-Forwarded-For"))
		})
	}
}

func TestClientIP_BackendSeesOnlyResolvedClient(t *testing.T) {
	var got http.Header
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		got = r.Header.Clone()
	}))
	defer backend.Close()
	target, err := url.Parse(backend.URL)
	require.NoError(t, err)

	handler := ClientIP(nil)(httputil.NewSingleHostReverseProxy(target))
	req := httptest.NewRequest(http.MethodGet, "/api/v1/admin/users", nil)
	req.RemoteAddr = "198.51.100.7:4000"
	req.Header.Set("True-Client-IP", "203.0.113.1")
	req.Header.Set("X-Real-IP", "203.0.113.2")
	req.Header.Set("X-Forwarded-For", "203.0.113.3")
	req.Header.Set("Forwarded", "for=203.0.113.4")
	handler.ServeHTTP(httptest.NewRecorder(), req)

	require.NotNil(t, got)
	assert.Equal(t, "198.51.100.7", got.Get("X-Forwarded-For"))
	assert.Equal(t, "198.51.100.7", got.Get("X-Real-IP"))
	assert.Empty(t, got.Get("True-Client-IP"))
	assert.Empty(t, got.Get("Forwarded"))
}
