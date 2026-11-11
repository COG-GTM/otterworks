package middleware

import (
	"net"
	"net/http"
	"strings"
)

// ParseCIDRs parses CIDRs or bare IPs into networks, skipping invalid entries.
func ParseCIDRs(values []string) []*net.IPNet {
	var nets []*net.IPNet
	for _, v := range values {
		v = strings.TrimSpace(v)
		if v == "" {
			continue
		}
		if !strings.Contains(v, "/") {
			ip := net.ParseIP(v)
			if ip == nil {
				continue
			}
			bits := 128
			if ip.To4() != nil {
				ip = ip.To4()
				bits = 32
			}
			nets = append(nets, &net.IPNet{IP: ip, Mask: net.CIDRMask(bits, bits)})
			continue
		}
		if _, n, err := net.ParseCIDR(v); err == nil {
			nets = append(nets, n)
		}
	}
	return nets
}

// RealIP sets r.RemoteAddr to the client IP. Forwarding headers are honoured
// only when the immediate peer is a trusted proxy, and X-Forwarded-For is
// walked right to left so a client cannot prepend its own entries to pick
// a rate-limit bucket.
func RealIP(trusted []*net.IPNet) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			if ip := clientIP(r, trusted); ip != "" {
				r.RemoteAddr = ip
			}
			next.ServeHTTP(w, r)
		})
	}
}

func clientIP(r *http.Request, trusted []*net.IPNet) string {
	peer := peerIP(r.RemoteAddr)
	if peer == nil || !isTrusted(peer, trusted) {
		return ""
	}

	var hops []net.IP
	for _, xff := range r.Header.Values("X-Forwarded-For") {
		for _, part := range strings.Split(xff, ",") {
			if ip := net.ParseIP(strings.TrimSpace(part)); ip != nil {
				hops = append(hops, ip)
			}
		}
	}
	for i := len(hops) - 1; i >= 0; i-- {
		if !isTrusted(hops[i], trusted) {
			return hops[i].String()
		}
	}
	if len(hops) > 0 {
		return hops[0].String()
	}
	if ip := net.ParseIP(strings.TrimSpace(r.Header.Get("X-Real-IP"))); ip != nil {
		return ip.String()
	}
	return ""
}

func peerIP(remoteAddr string) net.IP {
	host, _, err := net.SplitHostPort(remoteAddr)
	if err != nil {
		host = remoteAddr
	}
	return net.ParseIP(host)
}

func isTrusted(ip net.IP, trusted []*net.IPNet) bool {
	for _, n := range trusted {
		if n.Contains(ip) {
			return true
		}
	}
	return false
}
