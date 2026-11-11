package middleware

import (
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestClientIP(t *testing.T) {
	trusted, err := ParseTrustedProxies([]string{"10.0.0.0/8", "127.0.0.1", "::ffff:192.168.0.0/112"})
	require.NoError(t, err)

	tests := []struct {
		name       string
		remoteAddr string
		headers    map[string]string
		expected   string
	}{
		{
			name:       "untrusted peer ignores True-Client-IP",
			remoteAddr: "203.0.113.7:4000",
			headers:    map[string]string{"True-Client-IP": "1.2.3.4"},
			expected:   "203.0.113.7:4000",
		},
		{
			name:       "untrusted peer ignores X-Forwarded-For and X-Real-IP",
			remoteAddr: "203.0.113.7:4000",
			headers:    map[string]string{"X-Forwarded-For": "1.2.3.4", "X-Real-IP": "5.6.7.8"},
			expected:   "203.0.113.7:4000",
		},
		{
			name:       "trusted peer never honours True-Client-IP",
			remoteAddr: "10.1.2.3:4000",
			headers:    map[string]string{"True-Client-IP": "1.2.3.4"},
			expected:   "10.1.2.3:4000",
		},
		{
			name:       "trusted peer uses X-Real-IP",
			remoteAddr: "10.1.2.3:4000",
			headers:    map[string]string{"X-Real-IP": "198.51.100.9"},
			expected:   "198.51.100.9",
		},
		{
			name:       "trusted peer takes right-most X-Forwarded-For hop",
			remoteAddr: "10.1.2.3:4000",
			headers:    map[string]string{"X-Forwarded-For": "6.6.6.6, 198.51.100.9"},
			expected:   "198.51.100.9",
		},
		{
			name:       "private client appended by proxy is not skipped for a forged hop",
			remoteAddr: "10.1.2.3:4000",
			headers:    map[string]string{"X-Forwarded-For": "6.6.6.6, 10.4.4.4"},
			expected:   "10.4.4.4",
		},
		{
			name:       "X-Forwarded-For takes precedence over X-Real-IP",
			remoteAddr: "10.1.2.3:4000",
			headers:    map[string]string{"X-Forwarded-For": "198.51.100.9", "X-Real-IP": "6.6.6.6"},
			expected:   "198.51.100.9",
		},
		{
			name:       "garbage X-Forwarded-For hop leaves peer address",
			remoteAddr: "10.1.2.3:4000",
			headers:    map[string]string{"X-Forwarded-For": "198.51.100.9, not-an-ip"},
			expected:   "10.1.2.3:4000",
		},
		{
			name:       "IPv4-mapped trusted CIDR matches IPv4 peer",
			remoteAddr: "192.168.5.5:4000",
			headers:    map[string]string{"X-Real-IP": "198.51.100.9"},
			expected:   "198.51.100.9",
		},
		{
			name:       "bare trusted IP entry",
			remoteAddr: "127.0.0.1:4000",
			headers:    map[string]string{"X-Real-IP": "198.51.100.9"},
			expected:   "198.51.100.9",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			var got string
			h := ClientIP(trusted)(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				got = r.RemoteAddr
			}))
			req := httptest.NewRequest(http.MethodGet, "/", nil)
			req.RemoteAddr = tt.remoteAddr
			for k, v := range tt.headers {
				req.Header.Set(k, v)
			}
			h.ServeHTTP(httptest.NewRecorder(), req)
			assert.Equal(t, tt.expected, got)
		})
	}
}

func TestClientIP_NoTrustedProxies(t *testing.T) {
	var got string
	h := ClientIP(nil)(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		got = r.RemoteAddr
	}))
	req := httptest.NewRequest(http.MethodGet, "/", nil)
	req.RemoteAddr = "127.0.0.1:4000"
	req.Header.Set("X-Forwarded-For", "1.2.3.4")
	req.Header.Set("X-Real-IP", "1.2.3.4")
	req.Header.Set("True-Client-IP", "1.2.3.4")
	h.ServeHTTP(httptest.NewRecorder(), req)
	assert.Equal(t, "127.0.0.1:4000", got)
}

func TestParseTrustedProxies_Invalid(t *testing.T) {
	_, err := ParseTrustedProxies([]string{"not-a-cidr"})
	assert.Error(t, err)
}

func TestRateLimiter_SpoofedHeadersShareOneBucket(t *testing.T) {
	rl := NewRateLimiter(3)
	h := ClientIP(nil)(rl.Handler(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	})))

	limited := 0
	for i := 0; i < 20; i++ {
		req := httptest.NewRequest(http.MethodGet, "/", nil)
		req.RemoteAddr = "203.0.113.7:4000"
		req.Header.Set("True-Client-IP", "1.1.1."+string(rune('0'+i%10)))
		req.Header.Set("X-Forwarded-For", "2.2.2."+string(rune('0'+i%10)))
		rec := httptest.NewRecorder()
		h.ServeHTTP(rec, req)
		if rec.Code == http.StatusTooManyRequests {
			limited++
		}
	}
	assert.Equal(t, 17, limited)
	assert.Len(t, rl.buckets, 1)
}
