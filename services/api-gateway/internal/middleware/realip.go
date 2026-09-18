package middleware

import (
	"net"
	"net/http"
	"strings"
)

// forwardingHeaders are the client-controllable hints about who the caller is.
// They are only meaningful when the immediate peer is a proxy the deployment
// operates; from anyone else they are attacker-chosen input.
var forwardingHeaders = []string{
	"X-Forwarded-For",
	"X-Real-IP",
	"True-Client-IP",
	"CF-Connecting-IP",
	"Forwarded",
}

// ParseTrustedProxies converts CIDR or bare-IP strings into networks. Entries
// that do not parse are ignored so a typo cannot silently widen trust.
func ParseTrustedProxies(entries []string) []*net.IPNet {
	networks := make([]*net.IPNet, 0, len(entries))
	for _, entry := range entries {
		entry = strings.TrimSpace(entry)
		if entry == "" {
			continue
		}
		if _, network, err := net.ParseCIDR(entry); err == nil {
			networks = append(networks, network)
			continue
		}
		if ip := net.ParseIP(entry); ip != nil {
			bits := 32
			if ip.To4() == nil {
				bits = 128
			}
			networks = append(networks, &net.IPNet{IP: ip, Mask: net.CIDRMask(bits, bits)})
		}
	}
	return networks
}

// RealIP resolves the client address for every downstream handler.
//
// When the immediate peer is one of the trusted proxies, the left-most entry of
// X-Forwarded-For (or X-Real-IP) replaces r.RemoteAddr. Otherwise the peer
// address stands and the forwarding headers are removed from the request, so
// neither the rate limiter nor a backend can be steered by a header the caller
// chose.
func RealIP(trusted []*net.IPNet) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			peer := peerIP(r.RemoteAddr)
			if !isTrustedProxy(peer, trusted) {
				for _, header := range forwardingHeaders {
					r.Header.Del(header)
				}
				next.ServeHTTP(w, r)
				return
			}
			if client := forwardedClient(r); client != "" {
				r.RemoteAddr = net.JoinHostPort(client, "0")
			}
			next.ServeHTTP(w, r)
		})
	}
}

// ClientIP returns the address the request is attributed to.
func ClientIP(r *http.Request) string {
	if host, _, err := net.SplitHostPort(r.RemoteAddr); err == nil {
		return host
	}
	return r.RemoteAddr
}

func peerIP(remoteAddr string) net.IP {
	host, _, err := net.SplitHostPort(remoteAddr)
	if err != nil {
		host = remoteAddr
	}
	return net.ParseIP(strings.Trim(host, "[]"))
}

func isTrustedProxy(ip net.IP, trusted []*net.IPNet) bool {
	if ip == nil {
		return false
	}
	for _, network := range trusted {
		if network.Contains(ip) {
			return true
		}
	}
	return false
}

func forwardedClient(r *http.Request) string {
	if xff := r.Header.Get("X-Forwarded-For"); xff != "" {
		candidate := strings.TrimSpace(strings.Split(xff, ",")[0])
		if net.ParseIP(candidate) != nil {
			return candidate
		}
	}
	candidate := strings.TrimSpace(r.Header.Get("X-Real-IP"))
	if net.ParseIP(candidate) != nil {
		return candidate
	}
	return ""
}
