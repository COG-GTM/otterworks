# Angular upgrade parity report — admin-dashboard

Same Playwright specs (`parity/specs`) run against two projects:

| Project | URL | Source |
| --- | --- | --- |
| `baseline` | http://localhost:4000 | `main` before the upgrade (Angular 17.3), served from a separate worktree |
| `upgraded` | http://localhost:4200 | this branch |

Both apps talk to the same local `admin-service` (`API_GATEWAY_URL=http://localhost:8089`) seeded with `scripts/seed.py`.

## Baseline run (Angular 17.3, before any `ng update`)

19 passed, 0 failed (`npx playwright test --project=baseline`).


## Final run (baseline Angular 17.3.12 vs upgraded Angular 21.2.26)

`npx playwright test` (both projects, same specs): **38 passed, 0 failed** — baseline 19/19, upgraded 19/19.

| Page / flow | Baseline | Upgraded |
| --- | --- | --- |
| announcements — create, publish and delete an announcement | passed | passed |
| auth — login page renders and validates empty submit | passed | passed |
| auth — password visibility toggle | passed | passed |
| auth — protected routes redirect to login when signed out | passed | passed |
| auth — sign in, persist across reload, and sign out | passed | passed |
| dashboard — dashboard shows the four stat cards and charts | passed | passed |
| incidents — incident form validation | passed | passed |
| lists — audit logs paginate and filter | passed | passed |
| lists — feature flags search and toggle | passed | passed |
| lists — system health summary and refresh | passed | passed |
| lists — storage quotas list and search | passed | passed |
| lists — analytics renders all charts | passed | passed |
| navigation — sidebar lists every section and navigates to each page | passed | passed |
| navigation — sidebar collapses and expands | passed | passed |
| navigation — unknown route redirects to dashboard | passed | passed |
| users — users list paginates | passed | passed |
| users — users search, role and status filters | passed | passed |
| users — user detail, suspend and restore | passed | passed |
| users — unknown user never renders a profile | passed | passed |

## Screenshot pixel diff

`node compose-report.mjs` pads both shots to the same size, runs `pixelmatch` (threshold 0.1) and writes a
baseline | upgraded | diff composite per screen to `compare/`. Every screen is the same size on both sides and
under 0.7 % changed pixels. The remaining diffs are data and text anti-aliasing, not layout: the suite writes audit
events while it runs, so the dashboard "Document Activity" bars and the audit / user-detail activity rows differ
between the baseline pass and the upgraded pass a minute later.

| Screen | Baseline / upgraded size | Changed pixels | Diff % |
| --- | --- | --- | --- |
| [01-login.png](compare/01-login.png) | 1440x900 / 1440x900 | 0 | 0.000% |
| [02-login-validation.png](compare/02-login-validation.png) | 1440x900 / 1440x900 | 0 | 0.000% |
| [03-dashboard.png](compare/03-dashboard.png) | 1440x900 / 1440x900 | 2672 | 0.206% |
| [04-users.png](compare/04-users.png) | 1440x900 / 1440x900 | 2468 | 0.190% |
| [05-user-detail.png](compare/05-user-detail.png) | 1440x976 / 1440x976 | 9037 | 0.643% |
| [06-audit.png](compare/06-audit.png) | 1440x1694 / 1440x1694 | 12274 | 0.503% |
| [07-features.png](compare/07-features.png) | 1440x900 / 1440x900 | 609 | 0.047% |
| [08-health.png](compare/08-health.png) | 1440x1003 / 1440x1003 | 470 | 0.033% |
| [09-announcements.png](compare/09-announcements.png) | 1440x900 / 1440x900 | 24 | 0.002% |
| [10-quotas.png](compare/10-quotas.png) | 1440x900 / 1440x900 | 58 | 0.004% |
| [11-incidents.png](compare/11-incidents.png) | 1440x973 / 1440x973 | 197 | 0.014% |
| [12-analytics.png](compare/12-analytics.png) | 1440x2697 / 1440x2697 | 88 | 0.002% |
| [13-announcement-form.png](compare/13-announcement-form.png) | 1440x1071 / 1440x1071 | 762 | 0.049% |
| [14-incident-form.png](compare/14-incident-form.png) | 1440x1425 / 1440x1425 | 394 | 0.019% |

## Build (production `ng build`)

| | Angular 17.3 (baseline) | Angular 21.2 (upgraded) |
| --- | --- | --- |
| Initial bundle (raw) | 949.12 kB | 803.00 kB |
| `dist/admin-dashboard/browser` size | 1,523,094 B | 1,546,109 B |
| Build time (wall clock, warm cache) | 6.99 s | 4.69 s |

## Reproduce

```bash
# backend shared by both apps (admin-service on :8089 + Postgres), then seed it
docker compose -f docker-compose.infra.yml -f docker-compose.yml up -d --build postgres redis localstack admin-service
uv run scripts/seed.py

# baseline: main before the upgrade, in a separate worktree, on :4000
git worktree add ../otterworks-baseline main
cd ../otterworks-baseline/frontend/admin-dashboard && npm ci
API_GATEWAY_URL=http://localhost:8089 npx ng serve --port 4000

# upgraded: this branch on :4200 (Node >= 20.19)
cd frontend/admin-dashboard && npm ci
API_GATEWAY_URL=http://localhost:8089 npx ng serve --port 4200

# parity suite + report
cd parity && npm ci && npx playwright install chromium
npx playwright test          # or --project=baseline / --project=upgraded
node compose-report.mjs
```
