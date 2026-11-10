# Audit events (contract v2)

Every OtterWorks service reports sensitive actions (logins, permission changes, shares,
exports, deletes) to `audit-service`, which stores them in DynamoDB
(`otterworks-audit-events`) and archives them to S3. This page is the contract emitters
code against. The machine-readable version is
[`schemas/audit-event.v2.schema.json`](schemas/audit-event.v2.schema.json).

## Sending an event

```http
POST {AUDIT_SERVICE_URL}/api/v1/audit/events
Content-Type: application/json
X-Audit-Token: {AUDIT_SERVICE_TOKEN}
X-Request-ID: {forwarded request id}
```

| Where | Variable | Value |
|---|---|---|
| Emitting service | `AUDIT_SERVICE_URL` | `http://audit-service:8090` in docker-compose |
| Emitting service | `AUDIT_SERVICE_TOKEN` | `otterworks-audit-dev-token` in docker-compose |
| audit-service | `AUDIT_INGEST_TOKENS` | Comma-separated allow-list of accepted tokens |

- When `AUDIT_INGEST_TOKENS` is set, a missing or wrong `X-Audit-Token` gets `401` and
  increments `audit_ingest_rejected_total`.
- When it is unset, audit-service logs a startup warning and accepts writes. This keeps
  tenants deployed from the upstream Helm chart (which has no token yet) working.
- Responses: `201` with the stored event, `400` with `errors[]` if the body breaks the
  contract, `401` as above.

## Body

camelCase JSON. Existing field names are kept for backward compatibility.

| Field | Required | Notes |
|---|---|---|
| `userId` | yes | Actor id, or `"anonymous"`. Missing → `400`. |
| `actorEmail` | | |
| `actorType` | | `user`, `admin`, `service` or `anonymous` |
| `tenantId` | | |
| `action` | yes | Must match `^[a-z]+(\.[a-z_]+)+$`, or be `export` / `delete`. Anything else → `400`. |
| `resourceType` | yes | `file`, `document`, `folder`, `user`, `role`, `share_link`, `export_archive`, ... |
| `resourceId` | | |
| `outcome` | yes | `success`, `failure` or `denied` |
| `details` | | Flat `string → string` map of non-sensitive context |
| `ipAddress` | | Client IP (see below) |
| `sourceIp` | | Alias of `ipAddress`; `ipAddress` wins if both are sent. Responses return both. |
| `userAgent` | | |
| `requestId` | | `X-Request-ID` value |
| `serviceName` | yes | Emitting service, e.g. `auth-service` |
| `timestamp` | | UTC ISO-8601, e.g. `2026-11-10T16:00:00Z`. Defaults to receive time. |

Example:

```json
{
  "userId": "8f6c...",
  "actorEmail": "owner@example.com",
  "actorType": "user",
  "action": "share.create",
  "resourceType": "file",
  "resourceId": "file-123",
  "outcome": "success",
  "details": { "sharedWithUserId": "user-456", "permission": "viewer" },
  "ipAddress": "203.0.113.7",
  "userAgent": "Mozilla/5.0",
  "requestId": "3d1f...",
  "serviceName": "file-service",
  "timestamp": "2026-11-10T16:00:00Z"
}
```

### Actions

There is no fixed enum, so new actions need no audit-service change. Common ones:

- `auth.login.success`, `auth.login.failure`, `auth.logout`, `auth.token.refresh`,
  `auth.token.refresh_denied`, `auth.token.rejected`, `auth.user.register`, `auth.credential.change`
- `permission.change`, `permission.denied`
- `share.create`, `share.revoke`, `share.access`
- `export`, `delete`

Audit failure and denied paths too, not only success.

### Who and from where

- **Who:** the gateway-injected `X-User-ID` / `X-User-Email` headers, or the service's own JWT.
- **From where:** the first entry of `X-Forwarded-For`, then `X-Real-IP`, then the socket
  remote address. The api-gateway is responsible for setting these headers correctly.

### Never send

Passwords, JWTs, refresh tokens, share-link tokens, credentials or file/document contents,
in any field. As defence in depth, audit-service replaces any `details` value whose key
looks like a secret (`password`, `secret`, `token`, `credential`, `authorization`,
`cookie`, `api_key`, `private_key`) with `[REDACTED]` before storing it.

## Emitter rules

- Non-blocking: short timeout (about 2 s), bounded retry, no effect on the user's response.
- Failures are logged and counted in `audit_emit_failures_total`.

## Reading events

All read endpoints require an auth-service **access** JWT (signed with `JWT_SECRET`) whose
`roles` claim contains `ADMIN`. No token → `401`; a non-admin or refresh token → `403`.

| Endpoint | Notes |
|---|---|
| `GET /api/v1/audit/events` | Filters: `userId`/`user_id`, `action`, `outcome`, `serviceName`/`service_name`, `tenantId`/`tenant_id`, `resourceType`/`resource_type`, `resource`/`resourceId`, `from`, `to`, `page`, `size` (max 100) |
| `GET /api/v1/audit/events/{id}` | |
| `GET /api/v1/audit/resources/{resourceId}/history` | |
| `GET /api/v1/audit/reports/user/{userId}` | Self-audited |
| `GET /api/v1/audit/reports/compliance` | |
| `GET /api/v1/audit/export` | Self-audited |
| `POST /api/v1/audit/archive` | Self-audited |

## Self-auditing

audit-service records its own sensitive operations with `serviceName: "audit-service"`,
including `failure` and `denied` (401/403) attempts:

| Operation | `action` | `resourceType` | `resourceId` |
|---|---|---|---|
| `GET /export` | `export` | `export_archive` | Export location, without the presigned query string |
| `POST /archive` (events moved out of the hot store) | `delete` | `audit_log` | S3 archive location |
| `GET /reports/user/{userId}` | `audit.report.read` | `user` | `{userId}` |

These writes go straight to the store with a 2 s timeout and one retry. If they fail, the
operation still succeeds and `audit_emit_failures_total{action=...}` is incremented.

## Legacy SNS message

Until file-service migrates, the SNS/SQS consumer still accepts the old `file_shared`
message (`eventType`, `fileId`, `ownerId`, `sharedWithUserId`, `timestamp`). It is stored as
`action: share.create`, `resourceType: file`, `outcome: success`, `serviceName: file-service`,
with `details.legacyEventType = file_shared`. Other SNS messages use the v2 body above.
