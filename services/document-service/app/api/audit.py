"""Per-request audit context and the helper routes use to record audit events."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import Request

from app.api.identity import _extract_user_id, _get_jwt_secret, _jwt_claims
from app.services.audit_client import SERVICE_NAME, get_audit_client, utc_timestamp

_MAX_FIELD = 512


def _clip(value: str | None, limit: int = _MAX_FIELD) -> str:
    return (value or "")[:limit]


def client_ip(request: Request) -> str:
    """First X-Forwarded-For hop, then X-Real-IP, then the socket peer."""
    forwarded = request.headers.get("X-Forwarded-For", "")
    first_hop = forwarded.split(",")[0].strip()
    if first_hop:
        return first_hop
    real_ip = request.headers.get("X-Real-IP", "").strip()
    if real_ip:
        return real_ip
    return request.client.host if request.client else ""


@dataclass(frozen=True)
class AuditContext:
    user_id: str
    actor_email: str | None
    actor_type: str
    ip_address: str
    user_agent: str
    request_id: str


class Auditor:
    """Builds contract-shaped events for one request and hands them to the audit client."""

    def __init__(self, context: AuditContext):
        self.context = context

    def record(
        self,
        action: str,
        resource_type: str,
        resource_id: str,
        outcome: str = "success",
        details: dict[str, str] | None = None,
    ) -> None:
        ctx = self.context
        event = {
            "userId": ctx.user_id,
            "actorType": ctx.actor_type,
            "action": action,
            "resourceType": resource_type,
            "resourceId": _clip(resource_id, 256) or "unknown",
            "outcome": outcome,
            "details": {k: _clip(str(v)) for k, v in (details or {}).items()},
            "ipAddress": ctx.ip_address,
            "userAgent": ctx.user_agent,
            "requestId": ctx.request_id,
            "serviceName": SERVICE_NAME,
            "timestamp": utc_timestamp(),
        }
        if ctx.actor_email:
            event["actorEmail"] = ctx.actor_email
        get_audit_client().submit(event)


def _capture_context(request: Request) -> AuditContext:
    verified = _extract_user_id(request)
    # With JWT verification on, gateway identity headers are trusted only alongside a
    # verified token, so a direct caller cannot attribute events to someone else.
    trust_headers = bool(verified) or not _get_jwt_secret()
    user_id = str(verified) if verified else None
    if not user_id and trust_headers:
        user_id = _clip(request.headers.get("X-User-ID"), 128)
    claims = _jwt_claims(request) or {}
    email = (request.headers.get("X-User-Email") if trust_headers else None) or claims.get("email")
    return AuditContext(
        user_id=user_id or "anonymous",
        actor_email=_clip(str(email), 256) if email else None,
        actor_type="user" if user_id else "anonymous",
        ip_address=client_ip(request),
        user_agent=_clip(request.headers.get("User-Agent")),
        request_id=_clip(request.headers.get("X-Request-ID"), 128) or str(uuid.uuid4()),
    )


def get_auditor(request: Request) -> Auditor:
    """FastAPI dependency: capture actor, IP, user agent and request id once per request."""
    auditor = getattr(request.state, "auditor", None)
    if auditor is None:
        auditor = Auditor(_capture_context(request))
        request.state.auditor = auditor
    return auditor


def record_permission_denied(request: Request, reason: str, attempted: str) -> None:
    route = request.scope.get("route")
    get_auditor(request).record(
        "permission.denied",
        "document",
        str(request.path_params.get("document_id", "")) or request.url.path,
        outcome="denied",
        details={
            "reason": reason,
            "attempted": attempted,
            "method": request.method,
            "route": getattr(route, "path", request.url.path),
        },
    )
