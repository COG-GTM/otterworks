# Runbook: legacy-portal decomposition cutover and rollback

`services/legacy-portal` (Java 11 / Spring Boot 2.7) is split into three
Spring Boot 3.3 / Java 17 services, one per bounded context. Each service owns
exactly one schema of the database the monolith already uses, so the cutover
moves ownership, not data.

| Service | Routes | Schema | Port | Chart |
|---|---|---|---|---|
| announcements-service | `/api/announcements/**` | `announcements` | 8092 | `infrastructure/helm/announcements-service` |
| user-preferences-service | `/api/preferences/**` | `user_preferences` | 8093 | `infrastructure/helm/user-preferences-service` |
| feedback-service | `/api/feedback/**` | `feedback` | 8094 | `infrastructure/helm/feedback-service` |

## Gates before a cutover

All of these run locally or on a CI runner; none of them deploy anything.

| Gate | Command | Proves |
|---|---|---|
| Monolith baseline | `make parity-baseline` | the golden transcripts still reproduce against legacy-portal |
| Service parity (H2) | `make parity-verify` | every recorded exchange matches, per context and on `/health`/actuator |
| Service parity (PostgreSQL) | `make parity-postgres` | same, on PostgreSQL, plus the data-lift/rollback drill below |
| Images | `make parity-containers` | the Dockerfiles produce images that pass the same transcripts |
| Helm rollout | `make parity-kind` | the charts install, probes go ready, and traffic through the Services matches |

The `Legacy portal decomposition parity` workflow runs the first four on every
PR that touches the monolith, the services, their charts or the harness.

## Cutover

1. **Hand over the schemas.** Apply `parity/legacy-portal/postgres/10-handover.sql`
   (adjusted for the environment's role names). Each schema and its tables move
   to the service's role; the monolith role keeps DML and sequence grants so it
   can still serve reads and writes during rollback.
2. **Roll out the services.** `scripts/deploy-dev.sh` and the tenant pipeline
   (`scripts/lib/tenant-common.sh`, `.github/workflows/cd-tenant.yml`) build and
   install the three charts like every other backend. On first boot Flyway
   baselines the existing schema (`baseline-on-migrate`); `V1` is
   `CREATE ... IF NOT EXISTS`, so it adopts the tables in place and Hibernate
   only validates.
3. **Move traffic per context.** Point the `/api/announcements`,
   `/api/preferences` and `/api/feedback` prefixes at the new Services one at a
   time. The monolith was never behind the api-gateway (its routes are not
   `/api/v1`), so this is done wherever the portal's traffic enters today --
   the on-prem proxy, or an Ingress by enabling `ingress.enabled` in the
   service's chart.
4. **Retire the monolith** once all three prefixes have moved and the rollback
   window has passed.

## Rollback

Traffic for a context moves back to legacy-portal; nothing else changes. Rows
written by the service are in the same tables the monolith reads, with IDs from
the same sequences, and the monolith role still holds DML on them. The drill in
`make parity-postgres` verifies exactly this: the monolith, rebooted after the
services have written, serves the services' rows unchanged.

## What the data-lift drill checks

`parity/legacy-portal/harness/datalift.py`, driven by `scenarios/datalift.yaml`:

1. Legacy layout; the monolith seeds every context as `legacyportal`.
2. Handover; each service boots as its own role and serves the seeded rows
   byte-for-byte as the monolith did.
3. Each service writes; Flyway history shows a baseline plus `V1`.
4. Each service role is denied access to the other two schemas.
5. The monolith reboots and serves both the seeded and service-written rows.
