# QA audit: auth-service

Scope: `services/auth-service` (Java 17 / Spring Boot 3.2, JJWT, Flyway) — register, login,
JWT issue/refresh/expiry, password rules, duplicate email, `/api/v1/auth/profile`,
`/api/v1/settings`, lockout/rate limiting. No product code was changed; every defect found is
pinned by a skipped/xfail test that references its finding ID.

## What was exercised

- **Registration**: happy path, BCrypt hashing, default `USER` role, validation (email format,
  blank fields, password `@Size(min=8)`, display name 1–100), duplicate email (exact and case
  variants), malformed JSON.
- **Login**: success + `lastLoginAt`, wrong password vs unknown email (same 400
  `Invalid credentials`, no enumeration), missing fields, repeated failures (lockout).
- **JWT**: access vs refresh `type` claim, refresh-as-access and access-as-refresh rejection,
  configured lifetimes, expiry, wrong signing key, payload tampering, unsigned (`alg:none`)
  tokens, garbage tokens, weak-secret rejection, unique refresh `jti`.
- **Refresh/logout**: rotation, replay of a rotated token, revoked/expired stored tokens,
  deleted user, logout revoking refresh tokens, access token after logout.
- **Password change**: wrong current password, short new password, old password rejected and
  refresh tokens revoked after change.
- **Profile**: GET/PUT, partial updates, length validation, per-token ownership, PATCH (the
  verb the web client uses), admin-only `/users` listing, email lookup.
- **Settings**: defaults, partial PATCH persistence, per-user isolation, `theme`/`language`
  validation.
- **UI** (Playwright + recorded computer-use run): register → sign out → sign in, wrong-password
  error, duplicate-email error, notification toggle persistence after reload, profile name edit
  persistence after reload.

## Pyramid

| Layer | Location | Added | Pass | xfail / skipped |
|---|---|---:|---:|---:|
| Unit (JUnit 5 + Mockito) | `services/auth-service/src/test/java/.../{service,security,dto,exception}` | 57 | 57 | 0 |
| Unit-layer Spring/MockMvc (H2) | `.../controller/AuthQaIntegrationTest.java` | 27 | 17 | 10 `@Disabled` |
| Functional / API (pytest via gateway :8080) | `tests/api/test_qa_auth_service.py` | 35 | 27 | 8 xfail (strict) |
| E2E (Playwright) | `frontend/client-app/e2e/qa-auth-service.spec.ts` | 5 | 4 | 1 `test.fail` |
| E2E (computer use) | testing-agent recording, linked in the PR | 1 run | see PR | — |

The pre-existing 29 auth-service tests still pass; `gradle check` (Spotless + tests + JaCoCo) is green.

Run:

```bash
cd services/auth-service && gradle check          # unit layer
python -m pytest tests/api/test_qa_auth_service.py # needs the core stack (otterworks-up.sh)
cd frontend/client-app && CI=1 npx playwright test e2e/qa-auth-service.spec.ts
```

## Findings

| ID | Sev | Location | Repro | Expected | Actual |
|---|---|---|---|---|---|
| QA-AUTH-01 | High | `AuthController.java:54` (`@PutMapping("/profile")`) vs `frontend/client-app/src/lib/api.ts:107` (`apiClient.patch("/auth/profile")`) | Settings → change Full name → Save changes (or `PATCH /api/v1/auth/profile`) | 200, name saved | 500 `Internal server error`; profile edits from the web app never persist |
| QA-AUTH-02 | Medium | `AuthService.java:45` (`existsByEmail`, case-sensitive), `users.email` unique index | Register `a@x.test`, then `A@X.TEST` | 400 already registered | 201 — two accounts for the same mailbox |
| QA-AUTH-03 | Medium | `AuthService.login` (`AuthService.java:62-68`) | 12 wrong-password logins, then the right one | Lockout/throttle (423/429) after N failures | Always 400, then 200; only the gateway's generic per-IP limiter applies |
| QA-AUTH-04 | Medium | `GlobalExceptionHandler.java:46` (`@ExceptionHandler(Exception.class)`) | `POST /auth/register` with body `{"email":`; `POST /auth/refresh` with no `Authorization` header (direct to :8081); any unsupported method | 400/401/405 | 500 for client errors (`HttpMessageNotReadableException`, `MissingRequestHeaderException`, `HttpRequestMethodNotSupportedException`) |
| QA-AUTH-05 | Medium | `UpdateSettingsRequest.java:13-14` (no constraints) vs `V4__create_user_settings_table.sql:6-7` (`VARCHAR(10)`) | `PATCH /api/v1/settings {"theme":"midnight-blue-hc"}`; `{"theme":"neon"}` | 400 validation error | 500 for >10 chars; arbitrary values accepted otherwise |
| QA-AUTH-06 | Low | `SecurityConfig.java` (no `authenticationEntryPoint`) | `GET :8081/api/v1/auth/profile` without a token | 401 | 403 (masked by the gateway, which returns 401 first) |
| QA-AUTH-07 | Low | `AuthService.logout` (`AuthService.java:124`) | Logout, then reuse the access token on `/auth/profile` | 401 | 200 until the 1h access-token expiry (refresh tokens are revoked correctly) |
| QA-AUTH-08 | Low | `UserService.java:64` | `GET /api/v1/auth/users/lookup?email=<unknown>` | 404 | 400 with the email echoed in the message |

Observation (not a separate test): the Settings form lets users edit **Email**, but
`UpdateProfileRequest` has no `email` field, so even with QA-AUTH-01 fixed an email change would
be silently dropped.

## Not tested / limits

- **Rate limiting** beyond lockout: the gateway's per-IP limiter is shared by all parallel QA
  sessions on this box; hammering it would be flaky and disrupt others, so only per-account
  lockout was asserted.
- **Access-token expiry end to end**: lifetime is 1h in compose; expiry is covered in unit tests
  with short-lived tokens instead of waiting in the API/UI layers.
- **Email verification / password reset**: no such endpoints exist in auth-service.
- **Admin flows** (`/auth/users` as ADMIN): no seeded admin credential in the core profile
  (`admin@otterworks.dev` login returns 400); the 403 for regular users is covered via API and
  the ADMIN path via MockMvc only.
- **`./gradlew`**: the committed wrapper jar is missing (`GradleWrapperMain` not found); tests
  were run with a locally cached Gradle 8.7.
