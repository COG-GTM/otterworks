package middleware

import (
	"net"
	"net/http"
	"net/http/httptest"
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
	nets, err := ParseTrustedProxies([]string{" 10.0.0.0/8 ", "", "192.0.2.10", "::1", "fc00::/7"})
	require.NoError(t, err)
	require.Len(t, nets, 4)
	assert.True(t, isTrusted(net.ParseIP("10.200.3.4"), nets))
	assert.True(t, isTrusted(net.ParseIP("192.0.2.10"), nets))
	assert.False(t, isTrusted(net.ParseIP("192.0.2.11"), nets))
	assert.True(t, isTrusted(net.ParseIP("::1"), nets))
	assert.True(t, isTrusted(net.ParseIP("fd12::5"), nets))

	_, err = ParseTrustedProxies([]string{"not-an-ip"})
	assert.Error(t, err)
	_, err = ParseTrustedProxies([]string{"10.0.0.0/33"})
	assert.Error(t, err)
}

func TestResolveClientIP(t *testing.T) {
	podCIDRs := []string{"10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"}

	tests := []struct {
		name       string
		trusted    []string
		remoteAddr string
		xff        []string
		realIP     string
		trueClient string
		expected   string
	}{
		{
			name:       "no trusted proxies: forwarding headers are ignored",
			remoteAddr: "172.18.0.1:5000",
			xff:        []string{"203.0.113.9"},
			realIP:     "203.0.113.9",
			expected:   "172.18.0.1",
		},
		{
			name:       "untrusted peer cannot choose its address",
			trusted:    podCIDRs,
			remoteAddr: "198.51.100.7:5000",
			xff:        []string{"203.0.113.9"},
			expected:   "198.51.100.7",
		},
		{
			name:       "web host: browser -> ingress -> web-app nginx -> gateway",
			trusted:    podCIDRs,
			remoteAddr: "10.0.12.40:5000",
			xff:        []string{"203.0.113.9, 10.0.3.15"},
			expected:   "203.0.113.9",
		},
		{
			name:       "api host: browser -> ingress -> gateway",
			trusted:    podCIDRs,
			remoteAddr: "10.0.3.15:5000",
			xff:        []string{"198.51.100.23"},
			expected:   "198.51.100.23",
		},
		{
			name:       "client-supplied entries left of the real client are ignored",
			trusted:    podCIDRs,
			remoteAddr: "10.0.12.40:5000",
			xff:        []string{"1.2.3.4, 5.6.7.8", "203.0.113.9, 10.0.3.15"},
			expected:   "203.0.113.9",
		},
		{
			name:       "spoofed private hops fall back to the peer",
			trusted:    podCIDRs,
			remoteAddr: "172.18.0.1:5000",
			xff:        []string{"10.9.0.7"},
			expected:   "172.18.0.1",
		},
		{
			name:       "malformed hop falls back to the peer",
			trusted:    podCIDRs,
			remoteAddr: "10.0.12.40:5000",
			xff:        []string{"203.0.113.9, garbage, 10.0.3.15"},
			expected:   "10.0.12.40",
		},
		{
			name:       "X-Real-IP and True-Client-IP are never honoured",
			trusted:    podCIDRs,
			remoteAddr: "10.0.12.40:5000",
			realIP:     "203.0.113.50",
			trueClient: "203.0.113.51",
			expected:   "10.0.12.40",
		},
		{
			name:       "IPv6 client behind trusted proxy",
			trusted:    append(podCIDRs, "fc00::/7"),
			remoteAddr: "[fd00::2]:5000",
			xff:        []string{"2001:db8::1, fd00::3"},
			expected:   "2001:db8::1",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			req := httptest.NewRequest(http.MethodGet, "/", nil)
			req.RemoteAddr = tt.remoteAddr
			for _, v := range tt.xff {
				req.Header.Add("X-Forwarded-For", v)
			}
			if tt.realIP != "" {
				req.Header.Set("X-Real-IP", tt.realIP)
			}
			if tt.trueClient != "" {
				req.Header.Set("True-Client-IP", tt.trueClient)
			}
			assert.Equal(t, tt.expected, resolveClientIP(req, mustTrusted(t, tt.trusted...)))
		})
	}
}

func TestClientIP_DistinctUsersBehindProxyGetDistinctBuckets(t *testing.T) {
	rl := NewRateLimiter(2)
	handler := ClientIP(mustTrusted(t, "10.0.0.0/8"))(rl.Handler(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	})))

	send := func(client string) int {
		req := httptest.NewRequest(http.MethodGet, "/api/v1/anything", nil)
		req.RemoteAddr = "10.0.12.40:5000" // web-app nginx pod
		req.Header.Set("X-Forwarded-For", client+", 10.0.3.15")
		rec := httptest.NewRecorder()
		handler.ServeHTTP(rec, req)
		return rec.Code
	}

	for i := 0; i < 5; i++ {
		send("198.51.100.66")
	}
	assert.Equal(t, http.StatusTooManyRequests, send("198.51.100.66"), "flooding client is throttled")
	assert.Equal(t, http.StatusOK, send("203.0.113.9"), "other users behind the same proxy are not")
}
