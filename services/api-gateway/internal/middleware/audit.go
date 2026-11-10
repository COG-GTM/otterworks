package middleware

import (
	"context"
	"net/http"
	"path"
	"strconv"
	"strings"

	chimw "github.com/go-chi/chi/v5/middleware"

	"github.com/Cognition-Partner-Workshops/otterworks/services/api-gateway/internal/audit"
)

const (
	ActionTokenRejected = "auth.token.rejected"
	ActionAccessDenied  = "auth.access.denied"

	resourceTypeRoute = "api_route"
	maxPathLen        = 256
	maxUserAgentLen   = 512
)

type auditStateKey struct{}

// auditState lets inner middleware report back to AuditAuthDenials, which
// wraps them and therefore cannot see their derived request contexts.
type auditState struct {
	claims   *JWTClaims
	deniedBy string
}

func getAuditState(ctx context.Context) *auditState {
	s, _ := ctx.Value(auditStateKey{}).(*auditState)
	return s
}

// AuthDenialAuditConfig configures AuditAuthDenials.
type AuthDenialAuditConfig struct {
	Emitter      audit.Emitter
	PathPrefixes []string
}

// DefaultAuthDenialPrefixes are the routes whose 403/429 responses are audited.
func DefaultAuthDenialPrefixes() []string {
	return []string{"/api/v1/auth"}
}

// AuditAuthDenials emits auth.access.denied when a request to an auth route
// ends in 403 (route-level denial) or 429 (rate-limit lockout), whether the
// gateway or the upstream service produced it. Register it outside the rate
// limiter and JWT middleware so it observes their responses.
func AuditAuthDenials(cfg AuthDenialAuditConfig) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		if cfg.Emitter == nil {
			return next
		}
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			if !hasPathPrefix(r.URL.Path, cfg.PathPrefixes) {
				next.ServeHTTP(w, r)
				return
			}
			state := &auditState{}
			ww := chimw.NewWrapResponseWriter(w, r.ProtoMajor)
			next.ServeHTTP(ww, r.WithContext(context.WithValue(r.Context(), auditStateKey{}, state)))

			status := ww.Status()
			if status != http.StatusForbidden && status != http.StatusTooManyRequests {
				return
			}
			reason := "forbidden"
			if status == http.StatusTooManyRequests {
				reason = "rate_limited"
			}
			enforcedBy := state.deniedBy
			if enforcedBy == "" {
				enforcedBy = "upstream"
			}
			e := newRequestEvent(r, ActionAccessDenied, state.claims)
			e.Details["reason"] = reason
			e.Details["status"] = strconv.Itoa(status)
			e.Details["enforcedBy"] = enforcedBy
			cfg.Emitter.Emit(e)
		})
	}
}

// newRequestEvent builds a denied-outcome event carrying who / from where for r.
// It deliberately never reads the Authorization header, query string or body.
func newRequestEvent(r *http.Request, action string, claims *JWTClaims) audit.Event {
	e := audit.Event{
		UserID:       "anonymous",
		ActorType:    audit.ActorAnonymous,
		Action:       action,
		ResourceType: resourceTypeRoute,
		ResourceID:   truncate(r.URL.Path, maxPathLen),
		Outcome:      audit.OutcomeDenied,
		Details:      map[string]string{"method": r.Method},
		IPAddress:    ClientIP(r),
		UserAgent:    truncate(r.UserAgent(), maxUserAgentLen),
		RequestID:    GetRequestID(r.Context()),
	}
	if e.RequestID == "" {
		e.RequestID = r.Header.Get("X-Request-ID")
	}
	if claims != nil {
		if id := claimsUserID(claims); id != "" {
			e.UserID = id
			e.ActorType = audit.ActorUser
			if hasAdminRole(claims.Roles) {
				e.ActorType = audit.ActorAdmin
			}
		}
		e.ActorEmail = claims.Email
	}
	return e
}

func claimsUserID(c *JWTClaims) string {
	if c.Subject != "" {
		return c.Subject
	}
	return c.UserID
}

func hasAdminRole(roles []string) bool {
	for _, r := range roles {
		switch strings.ToUpper(r) {
		case "ADMIN", "ROLE_ADMIN":
			return true
		}
	}
	return false
}

func hasPathPrefix(path string, prefixes []string) bool {
	for _, p := range prefixes {
		if path == p || strings.HasPrefix(path, p+"/") {
			return true
		}
	}
	return false
}

func truncate(s string, n int) string {
	if len(s) <= n {
		return s
	}
	return s[:n]
}

// ActionPermissionDenied is emitted when the gateway refuses a request outright.
const ActionPermissionDenied = "permission.denied"

// AuditIngestPath is audit-service's write endpoint. Services post to it
// directly over the internal network; it is never a client-facing route.
const AuditIngestPath = "/api/v1/audit/events"

// BlockClientAuditIngest rejects client writes to AuditIngestPath with 403 so
// forged events cannot be relayed through the gateway, and audits the attempt
// as permission.denied. Read routes under /api/v1/audit are left untouched.
// Matching is case-insensitive and dot-segment normalised because
// audit-service's ASP.NET routing is.
func BlockClientAuditIngest(emitter audit.Emitter) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			if !isAuditIngest(r) {
				next.ServeHTTP(w, r)
				return
			}
			if emitter != nil {
				e := newRequestEvent(r, ActionPermissionDenied, GetJWTClaims(r.Context()))
				e.Details["reason"] = "client_audit_ingest"
				e.Details["status"] = strconv.Itoa(http.StatusForbidden)
				e.Details["enforcedBy"] = "api-gateway"
				emitter.Emit(e)
			}
			writeJSONError(w, http.StatusForbidden, "audit events cannot be submitted through the gateway")
		})
	}
}

func isAuditIngest(r *http.Request) bool {
	if !strings.EqualFold(r.Method, http.MethodPost) {
		return false
	}
	return strings.EqualFold(strings.TrimSuffix(path.Clean("/"+r.URL.Path), "/"), AuditIngestPath)
}
