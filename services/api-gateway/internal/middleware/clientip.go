package middleware

import (
	"fmt"
	"net"
	"net/http"
	"strings"
)

// DefaultPrivateProxyCIDRs are the address ranges a cluster-internal proxy
// (ingress-nginx pod, web-app nginx) connects from. Pass them explicitly via
// TRUSTED_PROXY_CIDRS only where a network policy restricts who can reach the
// gateway; they are not trusted by default.
var DefaultPrivateProxyCIDRs = []string{
	"10.0.0.0/8",
	"172.16.0.0/12",
	"192.168.0.0/16",
	"fc00::/7",
}

// spoofableClientIPHeaders are never read: only X-Forwarded-For from a trusted
// peer is. They are dropped so backends cannot be fed a client-chosen value.
var spoofableClientIPHeaders = []string{"True-Client-IP", "Forwarded"}

// ParseTrustedProxies parses CIDRs or bare IPs into networks. Blank entries are
// ignored so an empty TRUSTED_PROXY_CIDRS trusts no proxy.
func ParseTrustedProxies(entries []string) ([]*net.IPNet, error) {
	var nets []*net.IPNet
	for _, entry := range entries {
		entry = strings.TrimSpace(entry)
		if entry == "" {
			continue
		}
		if !strings.Contains(entry, "/") {
			ip := net.ParseIP(entry)
			if ip == nil {
				return nil, fmt.Errorf("invalid trusted proxy %q", entry)
			}
			bits := 128
			if ip.To4() != nil {
				ip, bits = ip.To4(), 32
			}
			nets = append(nets, &net.IPNet{IP: ip, Mask: net.CIDRMask(bits, bits)})
			continue
		}
		_, n, err := net.ParseCIDR(entry)
		if err != nil {
			return nil, fmt.Errorf("invalid trusted proxy CIDR %q: %w", entry, err)
		}
		nets = append(nets, n)
	}
	return nets, nil
}

func isTrusted(ip net.IP, trusted []*net.IPNet) bool {
	for _, n := range trusted {
		if n.Contains(ip) {
			return true
		}
	}
	return false
}

// ClientIP replaces chi's RealIP. r.RemoteAddr is rewritten to the client
// address only when the TCP peer is a trusted proxy, in which case the
// right-most X-Forwarded-For hop that is not itself a trusted proxy is used.
// True-Client-IP and X-Real-IP are never honoured. The forwarding headers are
// then normalised so the reverse proxy sends backends X-Forwarded-For and
// X-Real-IP containing only the resolved client address.
func ClientIP(trusted []*net.IPNet) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			client, port := resolveClientIP(r, trusted)
			if client != "" {
				r.RemoteAddr = net.JoinHostPort(client, port)
				r.Header.Set("X-Real-IP", client)
			} else {
				r.Header.Del("X-Real-IP")
			}
			for _, h := range spoofableClientIPHeaders {
				r.Header.Del(h)
			}
			// httputil.ReverseProxy appends the RemoteAddr host to this header.
			r.Header.Del("X-Forwarded-For")
			next.ServeHTTP(w, r)
		})
	}
}

func resolveClientIP(r *http.Request, trusted []*net.IPNet) (string, string) {
	host, port, err := net.SplitHostPort(r.RemoteAddr)
	if err != nil {
		host, port = r.RemoteAddr, "0"
	}
	peer := net.ParseIP(host)
	if peer == nil {
		return "", port
	}
	if !isTrusted(peer, trusted) {
		return peer.String(), port
	}

	var hops []string
	for _, value := range r.Header.Values("X-Forwarded-For") {
		for _, hop := range strings.Split(value, ",") {
			hops = append(hops, strings.TrimSpace(hop))
		}
	}

	client := peer
	for i := len(hops) - 1; i >= 0; i-- {
		ip := net.ParseIP(hops[i])
		if ip == nil {
			// A malformed hop was not written by a trusted proxy; stop at the
			// last address one of them vouched for.
			break
		}
		client = ip
		if !isTrusted(ip, trusted) {
			break
		}
	}
	return client.String(), port
}
