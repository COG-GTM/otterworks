package middleware

import (
	"context"
	"fmt"
	"net"
	"net/http"
	"strings"
)

type clientOriginKey struct{}

// ClientOrigin is the resolved "from where" of a request.
type ClientOrigin struct {
	// IP is the real client address.
	IP string
	// Forwarded is the trusted X-Forwarded-For chain starting at IP, excluding
	// the directly connected peer. Empty when the peer is not a trusted proxy.
	Forwarded []string
}

// ProxyTrust holds the CIDRs whose forwarding headers are believed.
type ProxyTrust struct {
	nets []*net.IPNet
}

// NewProxyTrust parses CIDRs (bare IPs are accepted as single hosts).
func NewProxyTrust(cidrs []string) (*ProxyTrust, error) {
	t := &ProxyTrust{}
	for _, c := range cidrs {
		c = strings.TrimSpace(c)
		if c == "" {
			continue
		}
		if !strings.Contains(c, "/") {
			ip := net.ParseIP(c)
			if ip == nil {
				return nil, fmt.Errorf("invalid trusted proxy %q", c)
			}
			bits := 128
			if ip.To4() != nil {
				bits = 32
			}
			c = fmt.Sprintf("%s/%d", c, bits)
		}
		_, n, err := net.ParseCIDR(c)
		if err != nil {
			return nil, fmt.Errorf("invalid trusted proxy CIDR %q: %w", c, err)
		}
		t.nets = append(t.nets, n)
	}
	return t, nil
}

func (t *ProxyTrust) trusts(ip string) bool {
	if t == nil {
		return false
	}
	parsed := net.ParseIP(ip)
	if parsed == nil {
		return false
	}
	for _, n := range t.nets {
		if n.Contains(parsed) {
			return true
		}
	}
	return false
}

// ResolveClientOrigin determines the client address. X-Forwarded-For and
// X-Real-IP are only believed when the directly connected peer is trusted;
// the XFF chain is then walked right to left, skipping trusted proxies.
func ResolveClientOrigin(r *http.Request, trust *ProxyTrust) ClientOrigin {
	peer := peerIP(r)
	if !trust.trusts(peer) {
		return ClientOrigin{IP: peer}
	}

	hops := forwardedHops(r)
	if len(hops) == 0 {
		if real := strings.TrimSpace(r.Header.Get("X-Real-IP")); net.ParseIP(real) != nil {
			return ClientOrigin{IP: real, Forwarded: []string{real}}
		}
		return ClientOrigin{IP: peer}
	}

	idx := -1
	for i := len(hops) - 1; i >= 0; i-- {
		if net.ParseIP(hops[i]) == nil {
			break
		}
		idx = i
		if !trust.trusts(hops[i]) {
			break
		}
	}
	if idx < 0 {
		return ClientOrigin{IP: peer}
	}
	return ClientOrigin{IP: hops[idx], Forwarded: append([]string(nil), hops[idx:]...)}
}

// ClientOriginMiddleware resolves the client origin once and stores it on the
// request context. It replaces chi's RealIP, which trusts headers from anyone.
func ClientOriginMiddleware(trust *ProxyTrust) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			origin := ResolveClientOrigin(r, trust)
			ctx := context.WithValue(r.Context(), clientOriginKey{}, origin)
			next.ServeHTTP(w, r.WithContext(ctx))
		})
	}
}

// GetClientOrigin returns the origin resolved by ClientOriginMiddleware, or
// the untrusted peer address when the middleware did not run.
func GetClientOrigin(r *http.Request) ClientOrigin {
	if o, ok := r.Context().Value(clientOriginKey{}).(ClientOrigin); ok {
		return o
	}
	return ClientOrigin{IP: peerIP(r)}
}

// ClientIP returns the resolved client IP for r.
func ClientIP(r *http.Request) string {
	return GetClientOrigin(r).IP
}

func peerIP(r *http.Request) string {
	host, _, err := net.SplitHostPort(r.RemoteAddr)
	if err != nil {
		return r.RemoteAddr
	}
	return host
}

func forwardedHops(r *http.Request) []string {
	var hops []string
	for _, v := range r.Header.Values("X-Forwarded-For") {
		for _, h := range strings.Split(v, ",") {
			if h = strings.TrimSpace(h); h != "" {
				hops = append(hops, h)
			}
		}
	}
	return hops
}
