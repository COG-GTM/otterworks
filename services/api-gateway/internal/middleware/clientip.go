package middleware

import (
	"net"
	"net/http"
	"net/netip"
	"strings"
)

// ParseTrustedProxies parses a list of CIDRs or bare IPs.
func ParseTrustedProxies(entries []string) ([]netip.Prefix, error) {
	var prefixes []netip.Prefix
	for _, e := range entries {
		e = strings.TrimSpace(e)
		if e == "" {
			continue
		}
		if !strings.Contains(e, "/") {
			addr, err := netip.ParseAddr(e)
			if err != nil {
				return nil, err
			}
			prefixes = append(prefixes, netip.PrefixFrom(addr.Unmap(), addr.Unmap().BitLen()))
			continue
		}
		p, err := netip.ParsePrefix(e)
		if err != nil {
			return nil, err
		}
		if p.Addr().Is4In6() && p.Bits() >= 96 {
			p = netip.PrefixFrom(p.Addr().Unmap(), p.Bits()-96)
		}
		prefixes = append(prefixes, p.Masked())
	}
	return prefixes, nil
}

// ClientIP replaces chimw.RealIP. It rewrites r.RemoteAddr from X-Real-IP or
// X-Forwarded-For only when the TCP peer is a trusted proxy, and then takes the
// right-most X-Forwarded-For hop (the one that proxy appended), so a client
// cannot choose the address the rate limiter keys on. A single proxy layer
// (ingress-nginx) is assumed. True-Client-IP is never honoured.
func ClientIP(trusted []netip.Prefix) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			if ip, ok := resolveClientIP(r, trusted); ok {
				r.RemoteAddr = ip
			}
			next.ServeHTTP(w, r)
		})
	}
}

func resolveClientIP(r *http.Request, trusted []netip.Prefix) (string, bool) {
	peer, ok := parseAddr(r.RemoteAddr)
	if !ok || !isTrusted(peer, trusted) {
		return "", false
	}

	// Only the immediate proxy is trusted, so only the hop it appended (the
	// right-most) is used; anything to its left is client-supplied.
	if xff := r.Header.Values("X-Forwarded-For"); len(xff) > 0 {
		hops := strings.Split(strings.Join(xff, ","), ",")
		hop, ok := parseAddr(strings.TrimSpace(hops[len(hops)-1]))
		if !ok {
			return "", false
		}
		return hop.String(), true
	}

	if xrip, ok := parseAddr(strings.TrimSpace(r.Header.Get("X-Real-IP"))); ok {
		return xrip.String(), true
	}
	return "", false
}

func parseAddr(s string) (netip.Addr, bool) {
	if s == "" {
		return netip.Addr{}, false
	}
	if host, _, err := net.SplitHostPort(s); err == nil {
		s = host
	}
	addr, err := netip.ParseAddr(s)
	if err != nil {
		return netip.Addr{}, false
	}
	return addr.Unmap(), true
}

func isTrusted(addr netip.Addr, trusted []netip.Prefix) bool {
	for _, p := range trusted {
		if p.Contains(addr) {
			return true
		}
	}
	return false
}
