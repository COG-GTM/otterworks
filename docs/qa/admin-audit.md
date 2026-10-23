# QA audit — admin-audit unit

Scope: `services/admin-service` (Rails, `/api/v1/admin`), `frontend/admin-dashboard` (Angular 17)
and `services/audit-service` (.NET 8, `/api/v1/audit`). Exercised on the local docker-compose
stack (core profile + admin-service, audit-service, admin-dashboard) with `scripts/seed.py`
data. Devin and Slack integrations were left unconfigured; unit tests stub
`DevinSessionService`/`SlackNotifierService`, and functional tests only hit authz/validation
rejections on incident/settings routes, so no Devin session or Slack post was ever attempted.

## What was exercised

- **admin-service**: user list/search/show, role update, suspend/activate/delete and their audit
  records (actor id/email, timestamps, changes); role gate for `admin`/`super_admin`/`owner` vs
  `editor`/`viewer`/`user`/no role; audit-log filters (actor, action, resource, since/until,
  invalid dates, 404); quotas authz; incidents (create, severity validation, transitions,
  Devin-session conflict, viewer forbidden); settings (Slack webhook SSRF host check, empty
  updates, credential non-echo, viewer forbidden); feature-flag CRUD + audit + validation;
  alert-ingest / chaos shared-secret gates.
- **audit-service**: event write/read, validation of required fields, user/action/resource/
  resource-type/from/to filters, page-size clamp, bad dates, 404, gateway JWT requirement,
  DynamoDB scan pagination/sorting, SNS consumer path for client-app file uploads.
- **admin-dashboard**: `AdminApiService` mapping (users, audit events, action normalisation),
  suspend/restore/delete calls, `AuthService` login/logout, `JwtInterceptor` (Bearer header,
  401 logout, 403 no logout), login → users → search → detail → suspend → restore → audit log.

## Pyramid

| Layer | Location | Tests | Pass | xfail / pending |
|---|---|---|---|---|
| Unit — RSpec | `services/admin-service/spec/controllers/api/v1/admin/qa_*_spec.rb` | 47 | 44 | 3 (QA-AA-2, -3, -5) |
| Unit — xUnit | `services/audit-service/tests/AuditService.Tests/QaAdminAuditTests.cs` | 11 | 11 | 0 |
| Unit — Karma/Jasmine | `frontend/admin-dashboard/src/app/core/services/qa-admin-audit.spec.ts` | 14 | 12 | 2 (QA-AA-1, -8) |
| Functional — pytest via gateway | `tests/api/test_qa_admin_audit_flow.py` | 17 | 13 | 4 (QA-AA-2, -4, -6, -7) |
| E2E — Playwright | `frontend/client-app/e2e/qa-admin-audit.spec.ts` | 3 | 2 | 1 `test.fail` (QA-AA-1) |
| E2E — computer use | testing-agent recording (linked in PR) | 1 flow | see PR comment | |

Full suites with the new tests: RSpec 234 examples / 0 failures / 3 pending; xUnit 35/35;
Karma 69 pass / 2 pending / **7 pre-existing failures** (`AuthService getToken`, `DashboardComponent` ×2,
`HealthComponent`, `UsersComponent` ×3 — they fail identically on `main` without the QA spec,
and CI runs `npm test || true`).

Run:
```bash
# RSpec (no host Ruby: ruby:3.3 container + postgres)
bundle exec rspec spec/controllers/api/v1/admin/qa_users_audit_controller_spec.rb spec/controllers/api/v1/admin/qa_incidents_settings_controller_spec.rb
~/.dotnet/dotnet test services/audit-service/tests/AuditService.Tests --filter QaAdminAuditTests
cd frontend/admin-dashboard && npx ng test --watch=false --browsers=ChromeHeadless
uv run --with-requirements tests/api/requirements.txt python -m pytest tests/api/test_qa_admin_audit_flow.py -rxX
cd frontend/client-app && CI=1 npx playwright test e2e/qa-admin-audit.spec.ts   # ADMIN_DASHBOARD_URL defaults to :4200
```
Functional + e2e need admin data: `DB_HOST=localhost DB_PORT=5432 DB_USER=otterworks DB_PASSWORD=otterworks_dev uv run scripts/seed.py`.

## Findings

| ID | Sev | Service | Location | Repro | Expected | Actual |
|---|---|---|---|---|---|---|
| QA-AA-1 | High | admin-dashboard | `src/app/core/services/auth.service.ts:44,72` | Log in with any email + any non-empty password | Credentials verified by auth-service; JWT for that user | `mockLogin()` returns a hard-coded, 2030-expiring `admin` JWT (`admin@otterworks.dev`) shipped in the bundle and valid against the gateway's dev secret; every dashboard action is audited under that one actor, not the signed-in person |
| QA-AA-2 | High | admin-service | `app/controllers/api/v1/admin/audit_logs_controller.rb:4-12` | `GET /api/v1/admin/audit-logs` with a `viewer` JWT | 403 (admin-only, like `/users`) | 200 with full admin audit trail (actor emails, IPs, changes) |
| QA-AA-3 | Medium | admin-service | `app/controllers/api/v1/admin/quotas_controller.rb:5,9` | `GET /api/v1/admin/quotas/<other user id>` as non-admin | 403 unless admin or owner | Quota returned (IDOR); only `update` is guarded |
| QA-AA-4 | High | audit-service | `src/Controllers/AuditController.cs` (`POST events`) | Any logged-in user posts `{"userId":"ceo",...}` | Actor taken from JWT, or 403 on mismatch | 201, event stored as `ceo`. Service also has no auth of its own: port 8090 answers unauthenticated queries (gateway is the only guard) |
| QA-AA-5 | Medium | admin-service | `app/models/admin_user.rb:24` (`activate!`), `users_controller#activate` | `DELETE /users/:id` then `PUT /users/:id/activate` | 422 — deleted users stay deleted | User revived to `active` |
| QA-AA-6 | High | audit-service | `src/Services/SnsConsumer.cs:107,129-150` | Upload a file via the client app, query `/api/v1/audit/events?user_id=<uploader>` | `upload` event attributed to the uploader | Only `file_shared` is mapped; `file_uploaded`/`file_deleted`/… deserialize into the generic shape and are stored as `userId=system, action=unknown, resourceType=unknown, resourceId=""` — client-app actions never show with their actor |
| QA-AA-7 | Low | audit-service | `src/Controllers/AuditController.cs:75` | `GET /api/v1/audit/events?page=0` | 400 or clamp to 1 | 200, `page: 0` echoed. SNS-sourced timestamps are stored as `+00:00` while API ones use `Z`, which the string-based `from`/`to` scan filter compares lexically |
| QA-AA-8 | Low | admin-dashboard | `src/app/core/services/admin-api.service.ts:63` | Open a user's detail → activity | Actions performed *on* the user (`resource_id`) | Queries `actor_id`, so admin actions on that user (suspend/role change) never appear |

Observations (not tested as defects): the dashboard has no role-change UI (role changes only via
API); dashboard models omit backend role `super_admin` and status `deleted`; admins can suspend
or demote themselves; incident/feature-flag reads are open to any authenticated role.

## Not tested and why

- **Real Devin / Slack incident triage**: deliberately not exercised (no credentials; must never
  trigger). Only stubbed unit tests and authz/validation rejections.
- **Admin incident creation through the gateway**: skipped to avoid any chance of a Devin call;
  covered by stubbed RSpec.
- **S3 audit archiver / retention jobs** against LocalStack: existing xUnit tests only; no new coverage.
- **Document-service-originated audit events**: document-service returned 502 on the local stack
  during the run.
- **Real dashboard authentication**: impossible — login is mocked (QA-AA-1).
