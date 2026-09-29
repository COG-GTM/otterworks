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
