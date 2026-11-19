# OtterWorks Desktop — QA flow catalog

The main user flows of the Windows desktop client. Each one is run and recorded on `main`
(the classic .NET Framework 4.8 build) as the baseline, then re-run on every desktop
migration PR and release candidate; a run is a regression only when it differs from the
`main` baseline in a way a user would notice.

**Setup for every run:** backend from the repo root
(`docker compose -f docker-compose.infra.yml -f docker-compose.yml up -d`; at minimum
api-gateway, auth-service, document-service, file-service and their infra), `curl
http://localhost:8080/health` returns `healthy`, `appsettings.json` at its defaults
(`apiBaseUrl` `http://localhost:8080/api/v1`, `persistTokens` `false`) unless a flow says
otherwise. Use a fresh email per run (e.g. `qa+<timestamp>@otterworks.test`). Flows run in order D1→D11 on one account.

| # | Flow | Steps | Baseline on `main` (net48, observed 2026-11-19 at `cc23bf19`) |
|---|------|-------|---------------------------------|
| D1 | Register a new account | Launch → **Create one** → display name, email, password (≥ 8 chars) → **Create account** | Pass. Lands on **Documents**; header `Signed in as <display name>`; `No documents yet` / `Create your first document using the box above.`; status `0 document(s).` |
| D2 | Register validation | On **Create account**, enter a 7-character password → submit; then register an email that already exists | Short password: inline red `Password must be at least 8 characters.`, no request sent. Duplicate email: **known baseline bug**, shows `Registration succeeded but the server returned an empty response.` and stays on the form (see below) |
| D3 | Switch between Sign in and Create account | **Create one** → **Sign in** link → back | Pass. Screens swap in place (`Sign in` / `Welcome back to OtterWorks.`, `Create account` / `Get started with OtterWorks.`); fields empty; no error carried over |
| D4 | Create a document | On **Documents**, type a title → **New** (disabled while the box is empty) | Pass. Box clears; the list shows the title with `0 words · v 1` (space before the number) and an updated-at time like `11/19/2026 10:50 AM`; status ends at `1 document(s).` |
| D5 | Log out | **Log out** | Pass. Returns to **Sign in** with empty fields; `Signed in as` disappears from the header |
| D6 | Sign in and see persisted data | **Sign in** with the D1 account | Pass. Lands on **Documents**; the D4 document is still listed; `1 document(s).` |
| D7 | Sign in with a wrong password | **Sign in** with a valid email and a wrong password | **Known baseline bug**: shows `Login succeeded but the server returned an empty response.`; stays signed out on **Sign in** (see below) |
| D8 | Refresh the documents list | Create a document for the same account through the API (`POST /api/v1/documents` with the user's Bearer token), then **Refresh** | Pass. The new document appears next to the desktop one; `2 document(s).` |
| D9 | Files list | **Files** | Pass. Status `0 file(s).` with no error. The heading stays `Documents` and the document rows stay visible (baseline layout, not a regression) |
| D10 | Backend unreachable | Stop api-gateway (or point `apiBaseUrl` at a closed port) → **Sign in** | Pass. Inline error `Could not reach the OtterWorks backend. Verify it is running and that the API base URL is correct.`, a blank line, then `An error occurred while sending the request.` |
| D11 | Persisted session (DPAPI) | Set `persistTokens: true` in `bin\Release\appsettings.json` → sign in → close → relaunch | Pass. `%APPDATA%\OtterWorks\session.dat` is written (no plaintext token or email); relaunch opens **Documents** as the same user; **Log out** deletes the file |

### Known baseline bug: D2 / D7 error text through the gateway

The .NET Framework `HttpClient` sends `Expect: 100-continue` on POSTs. With that header the
api-gateway answers `200 OK` with the auth-service's 400 body
(`{"status":400,"message":"Invalid credentials"}` / `"Email already registered"`), so the
client sees a success with no `accessToken`. auth-service on :8081 returns 400 correctly with
the same header. The likely cause is the gateway's `otelhttp` (v0.49.0) response-writer wrapper,
which keeps the first status it sees (the `100`) and drops the real `400`. The .NET 8
`HttpClient` does not send `Expect: 100-continue`, so net8 builds will show the server's real
message (`Invalid credentials`, `Email already registered`). That difference is expected and
is not a migration regression.

Reproduce: `curl -i -X POST http://localhost:8080/api/v1/auth/login -H "Content-Type:
application/json" -H "Expect: 100-continue" -d "{\"email\":\"x@y.z\",\"password\":\"wrongpass1\"}"`
returns `HTTP/1.1 200 OK` with a 400 body.

## Running locally on Windows

- Build with NuGet restore plus full Visual Studio 2022 MSBuild (not `dotnet build`) on `main`.
- Minimal backend: `docker compose -f docker-compose.infra.yml -f docker-compose.yml up -d --build api-gateway auth-service document-service file-service redis` (pulls in postgres and localstack).
- On a CRLF checkout, LocalStack can report healthy while its init script failed to run
  (`[Errno 2] No such file or directory` in its logs). Run it with CRs stripped:
  `docker exec otterworks-localstack bash -c "sed 's/
$//' /etc/localstack/init/ready.d/init.sh | bash"`.

## What counts as a regression

- A flow that fails, crashes, hangs, or lands on a different screen than the baseline.
- Different user-visible text in an error, status or empty state (for example D10's error text
  differing between net48 and net8 builds). D2/D7 showing the server's real message on net8 is
  the one known, expected difference (see above).
- Visual changes are regressions only when the PR does not set out to make them (e.g. a
  visual-refresh PR is expected to change layout, not the flows).
