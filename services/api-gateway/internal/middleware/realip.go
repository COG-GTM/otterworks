package middleware

import (
	"fmt"
	"net"
	"net/http"
	"strings"
)

// TrustedProxies is the set of networks whose forwarding headers may be believed.
type TrustedProxies struct {
	nets []*net.IPNet
}

// ParseTrustedProxies builds a trusted set from CIDR blocks or bare IP addresses.
func ParseTrustedProxies(entries []string) (*TrustedProxies, error) {
	tp := &TrustedProxies{}
	for _, entry := range entries {
		entry = strings.TrimSpace(entry)
		if entry == "" {
			continue
		}
		if _, network, err := net.ParseCIDR(entry); err == nil {
			tp.nets = append(tp.nets, network)
			continue
		}
		ip := net.ParseIP(entry)
		if ip == nil {
			return nil, fmt.Errorf("trusted proxy %q is neither a CIDR block nor an IP address", entry)
		}
		bits := 8 * net.IPv6len
		if ip.To4() != nil {
			bits = 8 * net.IPv4len
		}
		tp.nets = append(tp.nets, &net.IPNet{IP: ip, Mask: net.CIDRMask(bits, bits)})
	}
	return tp, nil
}

// Contains reports whether addr is one of the trusted proxy hops.
func (tp *TrustedProxies) Contains(addr string) bool {
	if tp == nil {
		return false
	}
	ip := net.ParseIP(addr)
	if ip == nil {
		return false
	}
	for _, network := range tp.nets {
		if network.Contains(ip) {
			return true
		}
	}
	return false
}

// RealIP resolves the client address and rewrites r.RemoteAddr with it. Forwarding
// headers are only read when the peer itself is a trusted proxy, so a client cannot
// choose the address every downstream control is keyed on.
func RealIP(trusted *TrustedProxies) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			r.RemoteAddr = ClientIP(r, trusted)
			next.ServeHTTP(w, r)
		})
	}
}

// ClientIP returns the rightmost forwarded address that is not itself a trusted
// proxy, falling back to the socket peer address.
func ClientIP(r *http.Request, trusted *TrustedProxies) string {
	peer := hostOnly(r.RemoteAddr)
	if !trusted.Contains(peer) {
		return peer
	}

	for _, hop := range reversedHops(r) {
		if net.ParseIP(hop) == nil || trusted.Contains(hop) {
			continue
		}
		return hop
	}
	return peer
}

// reversedHops returns the forwarded chain closest-hop first.
func reversedHops(r *http.Request) []string {
	var hops []string
	for _, header := range r.Header.Values("X-Forwarded-For") {
		for _, hop := range strings.Split(header, ",") {
			hops = append(hops, hostOnly(strings.TrimSpace(hop)))
		}
	}
	if len(hops) == 0 {
		if realIP := strings.TrimSpace(r.Header.Get("X-Real-IP")); realIP != "" {
			hops = append(hops, hostOnly(realIP))
		}
	}

	for i, j := 0, len(hops)-1; i < j; i, j = i+1, j-1 {
		hops[i], hops[j] = hops[j], hops[i]
	}
	return hops
}

func hostOnly(addr string) string {
	addr = strings.TrimSpace(addr)
	if host, _, err := net.SplitHostPort(addr); err == nil {
		return host
	}
	return strings.Trim(addr, "[]")
}
