package middleware

import (
	"fmt"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/stretchr/testify/assert"
)

func clientIPFrom(t *testing.T, trusted []string, remoteAddr string, headers map[string]string) (string, *http.Request) {
	t.Helper()
	req := httptest.NewRequest(http.MethodGet, "/health", nil)
	req.RemoteAddr = remoteAddr
	for name, value := range headers {
		req.Header.Set(name, value)
	}

	var seen string
	var forwarded *http.Request
	networks, _ := ParseTrustedProxies(trusted)
	handler := RealIP(networks)(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		seen = ClientIP(r)
		forwarded = r
	}))
	handler.ServeHTTP(httptest.NewRecorder(), req)
	return seen, forwarded
}

func TestRealIP_UntrustedPeerCannotChooseItsAddress(t *testing.T) {
	ip, forwarded := clientIPFrom(t, nil, "203.0.113.9:4321", map[string]string{
		"X-Forwarded-For": "10.9.0.1",
		"X-Real-IP":       "10.9.0.2",
	})

	assert.Equal(t, "203.0.113.9", ip)
	assert.Empty(t, forwarded.Header.Get("X-Forwarded-For"), "spoofed header must not reach the backends")
	assert.Empty(t, forwarded.Header.Get("X-Real-IP"))
}

func TestRealIP_TrustedProxyIsBelieved(t *testing.T) {
	ip, _ := clientIPFrom(t, []string{"192.168.0.0/16"}, "192.168.5.5:4321", map[string]string{
		"X-Forwarded-For": "198.51.100.7, 192.168.5.5",
	})

	assert.Equal(t, "198.51.100.7", ip)
}

func TestRealIP_CallerPrependedHopsAreIgnored(t *testing.T) {
	// A proxy appends the peer to whatever X-Forwarded-For the caller sent, so
	// only the right-most entry outside the trusted set is attributable.
	ip, _ := clientIPFrom(t, []string{"192.168.0.0/16"}, "192.168.5.5:4321", map[string]string{
		"X-Forwarded-For": "10.9.0.1, 198.51.100.7, 192.168.5.5",
	})

	assert.Equal(t, "198.51.100.7", ip)
}

func TestRealIP_UntrustedPeerCannotClaimHTTPS(t *testing.T) {
	_, forwarded := clientIPFrom(t, nil, "203.0.113.9:4321", map[string]string{
		"X-Forwarded-Proto": "https",
	})

	assert.Empty(t, forwarded.Header.Get("X-Forwarded-Proto"))
}

func TestParseTrustedProxies_ReportsUnparseableEntries(t *testing.T) {
	networks, invalid := ParseTrustedProxies([]string{"10.0.0.0/8", " ", "10.0.0.0/33", "nonsense"})

	assert.Len(t, networks, 1)
	assert.Equal(t, []string{"10.0.0.0/33", "nonsense"}, invalid)
}

func TestRealIP_TrustedProxyWithGarbageHeaderFallsBackToPeer(t *testing.T) {
	ip, _ := clientIPFrom(t, []string{"192.168.5.5"}, "192.168.5.5:4321", map[string]string{
		"X-Forwarded-For": "not-an-ip",
	})

	assert.Equal(t, "192.168.5.5", ip)
}

func TestRateLimiter_SpoofedForwardingHeaderSharesOneBucket(t *testing.T) {
	rl := NewRateLimiter(2)
	handler := RealIP(nil)(rl.Handler(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	})))

	statuses := make([]int, 0, 3)
	for i := 0; i < 3; i++ {
		req := httptest.NewRequest(http.MethodGet, "/health", nil)
		req.RemoteAddr = "203.0.113.9:4321"
		req.Header.Set("X-Forwarded-For", fmt.Sprintf("10.9.0.%d", i+1))
		rec := httptest.NewRecorder()
		handler.ServeHTTP(rec, req)
		statuses = append(statuses, rec.Code)
	}

	assert.Equal(t, []int{http.StatusOK, http.StatusOK, http.StatusTooManyRequests}, statuses)
}
