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
	"X-Forwarded-Proto",
	"True-Client-IP",
	"CF-Connecting-IP",
	"Forwarded",
}

// ParseTrustedProxies converts CIDR or bare-IP strings into networks, and
// returns the entries that did not parse so the caller can report them: an
// unparseable entry is dropped rather than silently widening trust.
func ParseTrustedProxies(entries []string) ([]*net.IPNet, []string) {
	networks := make([]*net.IPNet, 0, len(entries))
	var invalid []string
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
			continue
		}
		invalid = append(invalid, entry)
	}
	return networks, invalid
}

// RealIP resolves the client address for every downstream handler.
//
// When the immediate peer is one of the trusted proxies, the right-most
// X-Forwarded-For entry that is not itself a trusted proxy replaces
// r.RemoteAddr: every entry to its left was appended by — or forged upstream of
// — that caller. Otherwise the peer address stands and the forwarding headers
// are removed from the request, so neither the rate limiter nor a backend can
// be steered by a header the caller chose.
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
			if client := forwardedClient(r, trusted); client != "" {
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

func forwardedClient(r *http.Request, trusted []*net.IPNet) string {
	if xff := r.Header.Get("X-Forwarded-For"); xff != "" {
		hops := strings.Split(xff, ",")
		for i := len(hops) - 1; i >= 0; i-- {
			candidate := strings.TrimSpace(hops[i])
			ip := net.ParseIP(candidate)
			if ip == nil {
				break
			}
			if !isTrustedProxy(ip, trusted) {
				return candidate
			}
		}
	}
	candidate := strings.TrimSpace(r.Header.Get("X-Real-IP"))
	if net.ParseIP(candidate) != nil {
		return candidate
	}
	return ""
}
