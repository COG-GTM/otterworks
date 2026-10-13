# Shared Protocol Buffers

Typed contracts for OtterWorks internal service interactions, checked by [buf](https://buf.build).
Services talk over REST and SNS/SQS today; these files pin the request/response and event shapes so
changes are reviewed for compatibility, and they are the starting point for any gRPC transport.
Nothing is generated into services yet.

| Package | Contract | Mirrors |
| --- | --- | --- |
| `otterworks.common.v1` | shared enums (`ResourceType`, `SharePermission`), pagination | enums in `shared/events/schemas/*.json` |
| `otterworks.auth.v1` | `UserDirectoryService` | auth-service `/api/v1/auth/users/lookup`, `/users/by-id/{id}` (used by file-service sharing) |
| `otterworks.audit.v1` | `AuditService` | audit-service `/api/v1/audit/events` |
| `otterworks.search.v1` | `SearchIndexService` | search-service `/api/v1/search/index/*`, SQS indexing consumer |
| `otterworks.notification.v1` | `NotificationService` | notification fan-out from share/comment/mention events |
| `otterworks.events.v1` | `DomainEvent` + file/document events | `shared/events/schemas/file-events.json`, `document-events.json` |

```bash
buf format --diff --exit-code shared/proto
buf lint shared/proto
buf breaking shared/proto --against '.git#branch=main,subdir=shared/proto'
```

CI: `.github/workflows/contracts.yml`. Field numbers are permanent: never reuse or renumber them;
reserve removed fields instead.
