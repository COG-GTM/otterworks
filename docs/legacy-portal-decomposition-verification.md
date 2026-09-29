# Legacy-portal decomposition: verification record

Verification of every commit on `devin/legacy-portal-decomposition` (23 commits on top of `origin/main`
`cc23bf19`, plus this record), run locally from a fresh clone. Nothing was pushed to a registry or
deployed anywhere; Helm was exercised only on a throwaway local kind cluster that was deleted afterwards.

Golden transcripts (`tests/parity/legacy_portal/golden/*.json`, combined sha256 prefix
`932a1671680c`) were checked before and after every stage and never changed.

## Staged verification (per commit)

Command: `git rebase --exec <stage-command> origin/main`. `scripts/legacy-portal/verify-stage.sh` only
exists from commit 4 on, so commits 1-3 ran the monolith's own verify (and, from commit 3, the parity
suite against the monolith). Parity per stage follows the routing each commit has: H2 and PostgreSQL
from commit 4, plus the compose stack once the portal services are in the root compose file (commit 17).

Image-build exception: Maven Central returns HTTP 429 on the verification VM, so commits 17-23 ran
`verify-stage.sh --skip-image-build`, with the portal images prebuilt for that commit by
`docker buildx bake` (context `services/`, local Maven repository and settings as named build
contexts, as `verify-kind.sh` does). No Maven mirror is committed.

| # | Commit | Stage | Subject | Command | Result | Evidence |
|---|---|---|---|---|---|---|
| 1 | `68852302` | baseline | roll back full-context test writes so verify is green | `cd services/legacy-portal && ./mvnw -B verify` (JDK 11) | **PASS** (7s) | legacy-portal 16 tests, 0 failures, 1 skipped; no `verify-stage.sh` yet at this commit; no golden set yet |
| 2 | `c7add4f4` | baseline | inventory bounded contexts in DECOMPOSITION.md | `cd services/legacy-portal && ./mvnw -B verify` (JDK 11) | **PASS** (6s) | legacy-portal 16 tests, 0 failures, 1 skipped; no `verify-stage.sh` yet at this commit; no golden set yet |
| 3 | `70075218` | parity | record the monolith as a golden HTTP parity suite | `cd services/legacy-portal && ./mvnw -B verify` (JDK 11) + parity suite x2 against the monolith on H2 | **PASS** (15s) | legacy-portal 16 tests, 0 failures, 1 skipped; parity h2 2/2 (21, 21 passed); no `verify-stage.sh` yet at this commit; golden `932a1671680c` |
| 4 | `a5ab8d86` | verify | add verify-stage.sh to build, test and replay parity per profile | `scripts/legacy-portal/verify-stage.sh` | **PASS** (52s) | legacy-portal verify (JDK 11): 1 module(s), 16 tests, 0 failures, 1 skipped; parity h2 2/2, postgres 2/2 (21 passed each); golden `932a1671680c` |
| 5 | `602654b3` | jdk17 | build, test and run the monolith on JDK 17 | `scripts/legacy-portal/verify-stage.sh` | **PASS** (37s) | legacy-portal verify (JDK 17): 1 module(s), 16 tests, 0 failures, 1 skipped; parity h2 2/2, postgres 2/2 (21 passed each); golden `932a1671680c` |
| 6 | `7547857b` | boot3 | migrate the monolith to Spring Boot 3.5 | `scripts/legacy-portal/verify-stage.sh` | **PASS** (41s) | legacy-portal verify (JDK 17): 1 module(s), 17 tests, 0 failures, 1 skipped; parity h2 2/2, postgres 2/2 (21 passed each); golden `932a1671680c` |
| 7 | `a0fe0fc2` | common | record the dependency re-check on Boot 3 / JDK 17 | `scripts/legacy-portal/verify-stage.sh` | **PASS** (40s) | legacy-portal verify (JDK 17): 1 module(s), 17 tests, 0 failures, 1 skipped; parity h2 2/2, postgres 2/2 (21 passed each); golden `932a1671680c` |
| 8 | `5b60b887` | common | build the portal as a Maven reactor under services/portal-parent | `scripts/legacy-portal/verify-stage.sh` | **PASS** (40s) | reactor verify (JDK 17): 1 module(s), 17 tests, 0 failures, 1 skipped; parity h2 2/2, postgres 2/2 (21 passed each); golden `932a1671680c` |
| 9 | `76f24969` | common | extract the portal-common Boot 3 auto-configuration library | `scripts/legacy-portal/verify-stage.sh` | **PASS** (44s) | reactor verify (JDK 17): 2 module(s), 39 tests, 0 failures, 1 skipped; parity h2 2/2, postgres 2/2 (21 passed each); golden `932a1671680c` |
| 10 | `f17cffaf` | announcements | extract announcements-service and cut it from the monolith | `scripts/legacy-portal/verify-stage.sh` | **PASS** (55s) | reactor verify (JDK 17): 3 module(s), 45 tests, 0 failures, 1 skipped; parity h2 2/2, postgres 2/2 (21 passed each); golden `932a1671680c` |
| 11 | `0585aa84` | announcements | document the extracted-service template | `scripts/legacy-portal/verify-stage.sh` | **PASS** (69s) | reactor verify (JDK 17): 3 module(s), 45 tests, 0 failures, 1 skipped; parity h2 2/2, postgres 2/2 (21 passed each); golden `932a1671680c` |
| 12 | `1e2fa2ee` | announcements | copy every reactor module POM into each image build | `scripts/legacy-portal/verify-stage.sh` | **PASS** (62s) | reactor verify (JDK 17): 3 module(s), 45 tests, 0 failures, 1 skipped; parity h2 2/2, postgres 2/2 (21 passed each); golden `932a1671680c` |
| 13 | `83d77c5d` | preferences | extract preferences-service and cut it from the monolith | `scripts/legacy-portal/verify-stage.sh` | **PASS** (72s) | reactor verify (JDK 17): 4 module(s), 51 tests, 0 failures, 1 skipped; parity h2 2/2, postgres 2/2 (21 passed each); golden `932a1671680c` |
| 14 | `de098a69` | preferences | document the preferences-service extraction | `scripts/legacy-portal/verify-stage.sh` | **PASS** (73s) | reactor verify (JDK 17): 4 module(s), 51 tests, 0 failures, 1 skipped; parity h2 2/2, postgres 2/2 (21 passed each); golden `932a1671680c` |
| 15 | `b396de83` | feedback | extract feedback-service and cut it from the monolith | `scripts/legacy-portal/verify-stage.sh` | **PASS** (88s) | reactor verify (JDK 17): 5 module(s), 58 tests, 0 failures, 1 skipped; parity h2 2/2, postgres 2/2 (21 passed each); golden `932a1671680c` |
| 16 | `bce11476` | feedback | document feedback-service and the fully extracted state | `scripts/legacy-portal/verify-stage.sh` | **PASS** (88s) | reactor verify (JDK 17): 5 module(s), 58 tests, 0 failures, 1 skipped; parity h2 2/2, postgres 2/2 (21 passed each); golden `932a1671680c` |
| 17 | `ff4d3c04` | compose | run the three portal services from the root compose stack | `scripts/legacy-portal/verify-stage.sh --skip-image-build` (images prebuilt with `docker buildx bake`, Maven cache as named context) | **PASS** (174s) | reactor verify (JDK 17): 5 module(s), 58 tests, 0 failures, 1 skipped; parity h2 2/2, postgres 2/2, compose 2/2 (21 passed each); golden `932a1671680c` |
| 18 | `c99bd15c` | compose | retire the legacy-portal module and its on-prem artifacts | `scripts/legacy-portal/verify-stage.sh --skip-image-build` (images prebuilt with `docker buildx bake`, Maven cache as named context) | **PASS** (161s) | reactor verify (JDK 17): 4 module(s), 55 tests, 0 failures, 1 skipped; parity h2 2/2, postgres 2/2, compose 2/2 (21 passed each); golden `932a1671680c` |
| 19 | `f30db189` | helm | add Helm charts for the three portal services | `scripts/legacy-portal/verify-stage.sh --skip-image-build` (images prebuilt with `docker buildx bake`, Maven cache as named context) | **PASS** (124s) | reactor verify (JDK 17): 4 module(s), 55 tests, 0 failures, 1 skipped; parity h2 2/2, postgres 2/2, compose 2/2 (21 passed each); golden `932a1671680c` |
| 20 | `56457a45` | tooling | deploy the portal services with the full tenant profile | `scripts/legacy-portal/verify-stage.sh --skip-image-build` (images prebuilt with `docker buildx bake`, Maven cache as named context) | **PASS** (124s) | reactor verify (JDK 17): 4 module(s), 55 tests, 0 failures, 1 skipped; parity h2 2/2, postgres 2/2, compose 2/2 (21 passed each); golden `932a1671680c` |
| 21 | `12997040` | tooling | build the portal service images in cd-tenant and the release matrix | `scripts/legacy-portal/verify-stage.sh --skip-image-build` (images prebuilt with `docker buildx bake`, Maven cache as named context) | **PASS** (123s) | reactor verify (JDK 17): 4 module(s), 55 tests, 0 failures, 1 skipped; parity h2 2/2, postgres 2/2, compose 2/2 (21 passed each); golden `932a1671680c` |
| 22 | `f0ed55e2` | tooling | document the tenant and CI wiring of the portal services | `scripts/legacy-portal/verify-stage.sh --skip-image-build` (images prebuilt with `docker buildx bake`, Maven cache as named context) | **PASS** (122s) | reactor verify (JDK 17): 4 module(s), 55 tests, 0 failures, 1 skipped; parity h2 2/2, postgres 2/2, compose 2/2 (21 passed each); golden `932a1671680c` |
| 23 | `b926d05f` | helm | verify the portal charts on a local kind cluster | `scripts/legacy-portal/verify-stage.sh --skip-image-build` (images prebuilt with `docker buildx bake`, Maven cache as named context) | **PASS** (123s) | reactor verify (JDK 17): 4 module(s), 55 tests, 0 failures, 1 skipped; parity h2 2/2, postgres 2/2, compose 2/2 (21 passed each); golden `932a1671680c` |

## Tip checks (`b926d05f`)

| Check | Command | Result |
|---|---|---|
| Reactor verify | `cd services/portal-parent && ./mvnw -B clean verify` (JDK 17) | **PASS** - BUILD SUCCESS; portal-common, announcements-service, preferences-service, feedback-service, 0 failures/errors |
| Golden parity, compose stack | `make portal-up && make parity-legacy-portal && make portal-down` | **PASS** - 21 passed. First attempt rebuilt the images and failed on Maven Central HTTP 429; rerun with the images prebuilt via `docker buildx bake` (Maven cache as named context) |
| Helm on kind | `scripts/legacy-portal/verify-kind.sh` | **PASS** - images bake, kind cluster `otterworks-portal-verify` (v1.32.5), helm install x2, per-service schema/role ownership x2, parity x2 through port-forward (21 passed each), cluster deleted. Script refuses any context other than `kind-*` and unsets AWS credentials |
| Golden hash | before/after all tip checks | `932a1671680c` unchanged |

## Repo-wide checks (tip vs `origin/main`)

| Check | Command | `origin/main` | Tip | Verdict |
|---|---|---|---|---|
| `make lint` | per-target steps of `make lint` | api-gateway staticcheck 1, auth-service wrapper jar missing (`GradleWrapperMain`), search-service ruff 1, `frontend/web-app` absent, admin-dashboard no ESLint builder; file, document, collab clean | identical | No regression; none of these paths are touched by the stack |
| ShellCheck | `shellcheck` over tracked `*.sh` | 26 findings in pre-existing scripts | identical 26; new portal scripts only SC1091 (info, sourced file not followed) | No regression |
| actionlint | `actionlint` | SC2016 `cd-tenant.yml:292` | SC2016 `cd-tenant.yml:303` (same line, moved by the portal image steps) | **Baseline** |
| Dependency inventory | `security/deps` harness `inventory` | rc 0 | rc 0; new modules `portal-common`, `announcements-service`, `preferences-service`, `feedback-service` registered and measured | PASS |
| Dependency module tests | harness `tests` for the four new modules | - | rc 0 for each | PASS |
| Advisory gate | harness `gate` | FAIL: commons-text 1.9 (CVE-2022-42889) via report-service, notification-service, legacy-portal (`commons-configuration2:2.8.0`) | FAIL: same artifact via report-service, notification-service and the four portal modules (same `commons-configuration2:2.8.0` path inherited from legacy-portal) | **Baseline** - carried over unchanged, remediation out of scope |
| `make test-api-flows` | core stack from each tree's compose files, then `make test-api-flows` | 2 failed, 19 passed, 3 skipped | 2 failed, 19 passed, 3 skipped | **Baseline** - same two tests fail with the same assertions on both (document version order `[3, 2, 1] != [1, 2, 3]`; notification preferences returns 200 where 400 is expected); no regression |

Core-stack note: fluent-bit and otel-collector report unhealthy on both stacks (observability only). This VM already has host listeners on 6379, 8084 and 9090, so both stacks were started
with a local-only override remapping the host ports of redis (16379) and collab-service (18084);
prometheus/grafana and the two frontends were not started. Containers talk on the compose network, so
service behaviour is unaffected. No service exercised by `tests/api` is changed by this stack.

## Fixes made during verification (autosquashed)

- Commit 1 (`68852302`): the existing test-isolation fix (roll back full-context test writes) moved ahead
  of the documentation commit - commit 2 failed on a shared H2 database left with a `Release` row.
- `verify-stage.sh` (commit 4): SC2155 - declaration split from command substitution; image builds use
  the Maven cache as a named context.
- `verify-helm.sh` (commit 19): SC2317 suppressions on functions invoked indirectly.
- Commit 14 (`de098a69`): empty subject reworded to
  `legacy-portal(preferences): document the preferences-service extraction` with a `Verified-by:` trailer.
