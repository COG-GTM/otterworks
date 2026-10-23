# QA audit — billing unit

Scope: `services/legacy-billing` (Flask + PostgreSQL stored procedures), `services/billing-service`
(FastAPI extraction target for the plans module) and `services/legacy-portal` (Spring Boot 2.7
modular monolith). None of these are routed through the API gateway, so functional and E2E tests
hit the service ports directly.

## How to run

```bash
make procs-up NS=dev                              # legacy :8109, billing-service :12109
(cd services/legacy-portal && ./mvnw -B -DskipTests package && java -jar target/legacy-portal.jar &)  # :8095

cd services/billing-service && uv sync && uv run pytest                      # unit
cd services/legacy-billing && uv run --with-requirements app/requirements.txt --with pytest pytest tests
cd services/legacy-portal && ./mvnw -B verify
uv run --with-requirements tests/api/requirements.txt python -m pytest tests/api/test_qa_billing_flow.py tests/api/test_qa_billing_portal.py
cd frontend/client-app && npx playwright test e2e/qa-billing.spec.ts
make procs-parity NS=dev                                                       # PASS=5 FAIL=0 SKIP=19
```

The legacy billing DB password comes from `DB_PASSWORD` in the compose file; the stored-procedure
tests read `LEGACY_BILLING_DB_PASSWORD`, then `DB_PASSWORD`, then `billing`. Every stored-procedure
test runs in a rolled-back transaction. URLs are overridable with `QA_LEGACY_BILLING_URL`,
`QA_BILLING_SERVICE_URL`, `QA_LEGACY_PORTAL_URL`; tests skip when a backend is unreachable.

## What was exercised

- **Plans** (legacy procs, legacy Flask routes, billing-service domain + HTTP): catalog ordering and
  active filter, entitlement date boundaries/tenant scoping/suspended status, plan change closing the
  prior subscription, deterministic UUID5 ids, duplicate change → 409, unknown plan → 400, input
  validation (422), internal reset gating, health/503. Legacy ⇄ billing-service parity for catalog,
  entitlement (tenants 1–3) and the unknown-tenant contract.
- **Rating**: rollover cap, first/second tier boundary (201/202 units), premium tier price,
  suspension proration, usage summary, idempotent finalize.
- **Invoicing**: preview line layout, tax-exempt tenants, issue totals = sum of persisted lines,
  credit-note consumption never driving totals negative, tax rounding.
- **Dunning**: overdue listing, weekend → Monday scheduling, 14-day grace, suspension notification
  written once on repeat runs.
- **Legacy portal**: announcements (create/validate/publish/404/draft visibility), feedback
  (rating bounds, per-user listing newest first, average), user preferences (defaults, round trip,
  per-user isolation, validation), health banner interpolation.
- **Browser**: client-app billing fixture pages (`/billing/plans`, `/billing/entitlement/:id`,
  `/billing/change/:id`) against billing-service, compared with the legacy JSON API; legacy
  server-rendered index; legacy change-plan form post + redirect; invoice preview → issue; portal
  announcement publish flow.

## Pyramid

| Layer | Location | Tests | Pass | xfail | skip |
|---|---|---|---|---|---|
| Unit — billing-service | `services/billing-service/tests/test_qa_{domain,api}.py` | 37 | 36 | 1 | 0 |
| Unit — legacy-billing (Flask + procs) | `services/legacy-billing/tests/` | 50 | 43 | 7 | 0 |
| Unit — legacy-portal (MockMvc) | `services/legacy-portal/src/test/java/.../qa/QaPortalApiTest.java` | 30 | 29 | 0 | 1 (`@Disabled`, QA-BILL-09) |
| **Unit total** | | **117** | **108** | **8** | **1** |
| Functional / API | `tests/api/test_qa_billing_{flow,portal}.py` | 34 | 27 | 6 | 1 (QA-BILL-01) |
| E2E — Playwright | `frontend/client-app/e2e/qa-billing.spec.ts` | 8 | 8 | 0 | 0 |
| E2E — computer use | testing-agent recording (see PR comment) | 1 run | | | |

Pre-existing suites still green: billing-service (8 existing), legacy-portal `./mvnw verify`
(46 run, 2 skipped incl. 1 pre-existing), `make procs-parity` (PASS=5).

## Findings

| ID | Severity | Service | Location | Repro | Expected | Actual |
|---|---|---|---|---|---|---|
| QA-BILL-01 | Medium | billing-service | `app/main.py` lifespan (only `migrate()`) | Fresh `make procs-up`, `GET :12109/api/plans` | Seeded catalog (STARTER/GROWTH/SCALE) | `[]`, every entitlement 404 until `POST /internal/reset` |
| QA-BILL-02 | Medium | legacy-billing | `app/app.py` `entitlement`, `rating_preview` (no input validation / error handler) | `GET :8109/plans/not-a-uuid/entitlement`; `POST /api/rating/preview {"tenant_id":…}` | 400 | 500 (psycopg `InvalidTextRepresentation` / `KeyError`) |
| QA-BILL-03 | Low | legacy-billing ⇄ billing-service | `app/app.py` `entitlement` vs `billing-service/app/main.py` | Entitlement for `…0ff` | Same status on both | legacy 200 `[]`, target 404 (contract divergence for parity) |
| QA-BILL-04 | High | legacy-billing | `db/procs/invoicing.sql` (tax split into regional/local halves) | Preview tenant 6; issue a GROWTH tenant with no usage | Lines in cents; tax = round(149 × 0.0825, 2) = 12.29 (as in seeded invoices, total 161.29) | Preview tax lines `2.2506000000000000`; issued tax 12.30 (each half rounded separately → penny drift) |
| QA-BILL-05 | Low | legacy-billing | `db/procs/invoicing.sql` `fn_invoice_preview` | `GET /api/invoices/…0ff/preview` | 404 / empty | 200 with plan/usage/tax lines whose amounts are `null` |
| QA-BILL-06 | Medium | legacy-billing | `db/procs/rating.sql` `fn_usage_rating` (proration block) | Rate tenant 2 (suspended 2026-02-15) for Feb | `first_tier + second_tier = billable` | billable prorated to 100 but tiers stay 101 + 99 |
| QA-BILL-07 | Low (test infra) | legacy-portal | `AnnouncementServiceTest` | `./mvnw verify` on `main` | Green | Fails: `@SpringBootTest` commits a "Release" row into the shared named H2 DB that leaks into `@DataJpaTest`. Fixed in the test (`@BeforeEach deleteAll`, rolled back) |
| QA-BILL-08 | Info | legacy-portal | all controllers | `PUT /api/preferences/{anyUser}` | Caller can only modify own data | No authentication/ownership checks anywhere (by design for the legacy fixture; flag before exposing) |
| QA-BILL-09 | Low | legacy-portal | `AnnouncementController#get` | Create draft, `GET /api/announcements/{id}` | 404 for unpublished | Draft returned to any caller |
| QA-BILL-10 | Info | legacy-billing | `app/templates/index.html` | Browse `:8109` | Server-rendered entitlement / change-plan / invoice pages | Only the plan list is server-rendered; other flows are JSON / form-post endpoints, so E2E drives them via the JSON pages and form posts |

Notes: the first rating tier is 101 units (`LEAST(billable, 101)`); this matches the recorded
transcripts (RATING-004/005), so it is treated as the legacy contract, not a finding.
`sp_schedule_dunning` adds a new attempt on every call (no per-day idempotency) — consistent with
DUNNING-003, not flagged.

## Not tested / limits

- Gateway path: billing and portal are not routed through `api-gateway` (:8080), so the functional
  tests hit service ports directly; the core stack was not needed.
- QA-BILL-01 needs a freshly created billing-service container, so its API test is `skip` (the
  unit-level xfail covers it).
- Legacy portal PostgreSQL profile (`SPRING_PROFILES_ACTIVE=postgres`) — only H2 was exercised.
- Rating/invoicing/dunning have no billing-service endpoints yet (`procs/routes.yaml` pending), so
  parity is limited to plans.
- Load, concurrency (parallel plan changes) and timezone edge cases were out of scope.
