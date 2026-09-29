# legacy-portal decomposition parity

`services/legacy-portal` (Spring Boot 2.7 / Java 11) is split into three
independently deployable Spring Boot 3 / Java 17 services, one per bounded
context. The monolith is the behavioral oracle: this harness records its HTTP
responses once, then replays the same requests against each extracted service
and fails on any divergence.

| context | service | routes | schema | local parity port | container port |
|---|---|---|---|---:|---:|
| announcements | `announcements-service` | `/api/announcements/**` | `announcements` | 18092 | 8092 |
| user-preferences | `user-preferences-service` | `/api/preferences/**` | `user_preferences` | 18093 | 8093 |
| feedback | `feedback-service` | `/api/feedback/**` | `feedback` | 18094 | 8094 |
| _monolith_ | `legacy-portal` | all of the above | all three | 18095 | 8095 |

`contexts.yaml` is the machine-readable version of this table.

## What is compared

Every exchange in `transcripts/*.json` pins: HTTP status, media type, and the
full JSON body (key order ignored, list order and JSON types significant --
`true` is not `1`, `0.0` is not `0`). ISO-8601 instants are the only values
normalised (to `<instant>`), since wall-clock time differs between any two runs.
Identity values are *not* normalised: every run starts on an empty database, so
ids `1, 2, 3...` are part of the contract.

`scenarios/platform.yaml` is fanned out to every service: `/health` (the
convention the gateway and Helm probes use), the Actuator liveness/readiness
groups, and the default error envelope for unrouted paths. Its `service` field
is ignored -- it is expected to change from `legacy-portal` to the service name.

## Running it

```bash
make parity-tests                  # unit-test the harness itself
make parity-build                  # package the monolith + every extracted service
make parity-baseline               # replay the transcripts against a fresh monolith (determinism)
make parity-verify                 # boot every service jar locally and replay
make parity-verify CONTEXT=feedback
make parity-verify TARGETS="announcements=http://localhost:8092 user-preferences=http://localhost:8093 feedback=http://localhost:8094"
make parity-record                 # re-record from the monolith (only if the oracle changed)
```

`parity-verify` refuses to run if the monolith's `src/main` no longer matches the
fingerprint the transcripts were recorded from, so a stale oracle cannot pass
silently. Reports land in `reports/` (git-ignored).

JDKs are located via `JAVA_HOME_11` / `JAVA_HOME_17`, falling back to the Ubuntu
OpenJDK paths and then `java` on `PATH`.

## PostgreSQL, data lift and rollback

```bash
make parity-postgres     # needs Docker; everything runs against a throwaway local postgres:15
make parity-containers   # builds the three images locally (never pushed) and replays against them
```

`parity-postgres` runs three passes against one local PostgreSQL:

1. **postgres-monolith** - the transcripts replay against the monolith on its
   `postgres` profile (legacy layout: all three schemas owned by `legacyportal`).
2. **postgres-services** - the database is reset to the post-handover layout
   (`postgres/10-handover.sql`: each schema owned by its service role) and the
   transcripts replay against the three services.
3. **datalift** (`scenarios/datalift.yaml`) - the cutover drill on shared data:
   seed through the monolith, stop it, hand the schemas over, boot the services
   and read the monolith's rows back unchanged, write through the services
   (Flyway must *baseline* the pre-existing tables, not recreate them), confirm
   each service role cannot read the other contexts' schemas, then stop the
   services and boot the monolith again as the rollback path and confirm it
   reads the rows the services wrote.

Service images pick up `$HOME/.m2/settings.xml` (or `MAVEN_SETTINGS=`) as a
BuildKit secret, so a local Maven mirror works without landing in a layer.
