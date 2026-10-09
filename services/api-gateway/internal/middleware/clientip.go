package middleware

import (
	"fmt"
	"net"
	"net/http"
	"strings"
)

// ParseTrustedProxies parses a list of CIDRs or bare IPs naming the proxy hops
// whose X-Forwarded-For entries the gateway may believe.
func ParseTrustedProxies(entries []string) ([]*net.IPNet, error) {
	var nets []*net.IPNet
	for _, raw := range entries {
		entry := strings.TrimSpace(raw)
		if entry == "" {
			continue
		}
		if !strings.Contains(entry, "/") {
			ip := net.ParseIP(entry)
			if ip == nil {
				return nil, fmt.Errorf("invalid trusted proxy %q", entry)
			}
			bits := 8 * net.IPv6len
			if ip4 := ip.To4(); ip4 != nil {
				ip, bits = ip4, 8*net.IPv4len
			}
			nets = append(nets, &net.IPNet{IP: ip, Mask: net.CIDRMask(bits, bits)})
			continue
		}
		_, n, err := net.ParseCIDR(entry)
		if err != nil {
			return nil, fmt.Errorf("invalid trusted proxy %q: %w", entry, err)
		}
		nets = append(nets, n)
	}
	return nets, nil
}

// ClientIP replaces the host in r.RemoteAddr with the address of the real client.
//
// X-Forwarded-For is only consulted when the immediate peer is a trusted proxy,
// and is then walked right to left: each hop was appended by the proxy to its
// right, so the first address that is not itself a trusted proxy is the client.
// Entries left of that point were supplied by the client and are ignored. If
// every hop is trusted (or the header is missing or malformed), the peer is
// used. X-Real-IP and True-Client-IP are never honoured: any client can set them.
func ClientIP(trusted []*net.IPNet) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			ip := resolveClientIP(r, trusted)
			// Keep the host:port form so httputil.ReverseProxy still derives
			// X-Forwarded-For from RemoteAddr.
			if _, port, err := net.SplitHostPort(r.RemoteAddr); err == nil {
				r.RemoteAddr = net.JoinHostPort(ip, port)
			} else {
				r.RemoteAddr = ip
			}
			next.ServeHTTP(w, r)
		})
	}
}

func resolveClientIP(r *http.Request, trusted []*net.IPNet) string {
	peer := extractIP(r)
	peerIP := net.ParseIP(peer)
	if peerIP == nil || !isTrusted(peerIP, trusted) {
		return peer
	}

	var hops []string
	for _, header := range r.Header.Values("X-Forwarded-For") {
		hops = append(hops, strings.Split(header, ",")...)
	}
	for i := len(hops) - 1; i >= 0; i-- {
		ip := net.ParseIP(strings.TrimSpace(hops[i]))
		if ip == nil {
			return peer
		}
		if !isTrusted(ip, trusted) {
			return ip.String()
		}
	}
	return peer
}

func isTrusted(ip net.IP, trusted []*net.IPNet) bool {
	for _, n := range trusted {
		if n.Contains(ip) {
			return true
		}
	}
	return false
}
