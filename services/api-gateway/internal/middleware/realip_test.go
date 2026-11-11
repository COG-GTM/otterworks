package middleware

import (
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

var testTrustedProxies = []string{"10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "127.0.0.0/8", "::1/128"}

func TestParseCIDRs(t *testing.T) {
	nets := ParseCIDRs([]string{"10.0.0.0/8", " 192.0.2.7 ", "::1", "", "not-an-ip", "300.0.0.0/8"})
	require.Len(t, nets, 3)
	assert.Equal(t, "10.0.0.0/8", nets[0].String())
	assert.Equal(t, "192.0.2.7/32", nets[1].String())
	assert.Equal(t, "::1/128", nets[2].String())
}

func TestRealIP(t *testing.T) {
	trusted := ParseCIDRs(testTrustedProxies)

	tests := []struct {
		name       string
		remoteAddr string
		headers    map[string][]string
		expected   string
	}{
		{
			name:       "untrusted peer keeps its own address and ignores XFF",
			remoteAddr: "203.0.113.9:4321",
			headers:    map[string][]string{"X-Forwarded-For": {"198.51.100.1"}},
			expected:   "203.0.113.9:4321",
		},
		{
			name:       "untrusted peer ignores X-Real-IP and True-Client-IP",
			remoteAddr: "203.0.113.9:4321",
			headers: map[string][]string{
				"X-Real-Ip":      {"198.51.100.1"},
				"True-Client-Ip": {"198.51.100.2"},
			},
			expected: "203.0.113.9:4321",
		},
		{
			name:       "trusted proxy chain resolves to the client behind ingress and web-app",
			remoteAddr: "10.1.2.3:5555",
			headers:    map[string][]string{"X-Forwarded-For": {"198.51.100.1, 10.1.9.9"}},
			expected:   "198.51.100.1",
		},
		{
			name:       "client-prepended XFF entries are ignored",
			remoteAddr: "10.1.2.3:5555",
			headers:    map[string][]string{"X-Forwarded-For": {"1.2.3.4, 198.51.100.1"}},
			expected:   "198.51.100.1",
		},
		{
			name:       "multiple XFF headers are treated as one list",
			remoteAddr: "10.1.2.3:5555",
			headers:    map[string][]string{"X-Forwarded-For": {"1.2.3.4", "198.51.100.1, 10.0.0.5"}},
			expected:   "198.51.100.1",
		},
		{
			name:       "all hops trusted falls back to the leftmost hop",
			remoteAddr: "10.1.2.3:5555",
			headers:    map[string][]string{"X-Forwarded-For": {"192.168.1.20, 10.0.0.5"}},
			expected:   "192.168.1.20",
		},
		{
			name:       "trusted peer without XFF uses X-Real-IP",
			remoteAddr: "172.18.0.4:5555",
			headers:    map[string][]string{"X-Real-Ip": {"198.51.100.7"}},
			expected:   "198.51.100.7",
		},
		{
			name:       "trusted peer with garbage headers keeps peer address",
			remoteAddr: "172.18.0.4:5555",
			headers: map[string][]string{
				"X-Forwarded-For": {"garbage"},
				"X-Real-Ip":       {"also-garbage"},
			},
			expected: "172.18.0.4:5555",
		},
		{
			name:       "True-Client-IP is never honoured",
			remoteAddr: "10.1.2.3:5555",
			headers:    map[string][]string{"True-Client-Ip": {"198.51.100.2"}},
			expected:   "10.1.2.3:5555",
		},
		{
			name:       "IPv6 client behind trusted proxy",
			remoteAddr: "[::1]:5555",
			headers:    map[string][]string{"X-Forwarded-For": {"2001:db8::1"}},
			expected:   "2001:db8::1",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			var got string
			h := RealIP(trusted)(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				got = r.RemoteAddr
			}))
			req := httptest.NewRequest(http.MethodGet, "/", nil)
			req.RemoteAddr = tt.remoteAddr
			for k, vs := range tt.headers {
				for _, v := range vs {
					req.Header.Add(k, v)
				}
			}
			h.ServeHTTP(httptest.NewRecorder(), req)
			assert.Equal(t, tt.expected, got)
		})
	}
}

func TestRealIP_SeparatesProxiedClientsIntoOwnBuckets(t *testing.T) {
	rl := NewRateLimiter(2)
	handler := RealIP(ParseCIDRs(testTrustedProxies))(rl.Handler(
		http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(http.StatusOK) }),
	))

	send := func(client string) int {
		req := httptest.NewRequest(http.MethodGet, "/api/v1/anything", nil)
		req.RemoteAddr = "10.244.0.12:40000" // web-app nginx pod
		req.Header.Set("X-Forwarded-For", client)
		req.Header.Set("X-Real-IP", client)
		rec := httptest.NewRecorder()
		handler.ServeHTTP(rec, req)
		return rec.Code
	}

	for i := 0; i < 5; i++ {
		send("198.51.100.66")
	}
	assert.Equal(t, http.StatusTooManyRequests, send("198.51.100.66"), "flooding client is throttled")
	assert.Equal(t, http.StatusOK, send("203.0.113.10"), "other client behind the same proxy is unaffected")
}
