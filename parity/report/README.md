# Angular upgrade parity report — admin-dashboard

Same Playwright specs (`parity/specs`) run against two projects:

| Project | URL | Source |
| --- | --- | --- |
| `baseline` | http://localhost:4000 | `main` before the upgrade (Angular 17.3), served from a separate worktree |
| `upgraded` | http://localhost:4200 | this branch |

Both apps talk to the same local `admin-service` (`API_GATEWAY_URL=http://localhost:8089`) seeded with `scripts/seed.py`.

## Baseline run (Angular 17.3, before any `ng update`)

19 passed, 0 failed (`npx playwright test --project=baseline`).

Results for later hops and the final side-by-side comparison are added below as the upgrade proceeds.
