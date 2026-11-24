# OtterWorks Desktop (Windows)

A native **Windows desktop client** for the OtterWorks platform, built with **C#**, **WPF** and
the **MVVM** pattern. It talks to the OtterWorks REST API through the API gateway using
`HttpClient`.

The project is an **SDK-style** `.csproj` that multi-targets **.NET 10**
(`net10.0-windows`) and **.NET Framework 4.8** (`net48`) from the same sources, so the
legacy 4.8 client keeps building alongside the modern one. NuGet dependencies
(`Newtonsoft.Json`) are declared as `PackageReference`s. It mirrors the core flow of the
`frontend/web-app` React client.

## Features

- **Register** — display name, email, password → `POST /auth/register`
- **Login** — email, password → `POST /auth/login`, with a link between the two screens
- **Documents list** — `GET /documents` (Bearer token), with a friendly empty state
- **Create document** — a *New* box → `POST /documents { title }` → list refreshes
- **Files list** — `GET /files` (nice-to-have)
- **Logout** — clears the token and returns to the login screen

The JWT access token is held **in memory**. Optionally it can be persisted between runs,
encrypted with the Windows Data Protection API (**DPAPI**, per-user scope) — see
[Configuration](#configuration). Tokens are never written to disk in plaintext.

## Project layout

```
clients/windows-desktop/
├── OtterWorks.Desktop.sln
├── README.md
├── docs/screenshots/                 # verification screenshots (embedded below)
└── OtterWorks.Desktop/
    ├── OtterWorks.Desktop.csproj      # SDK-style WPF project: net10.0-windows + net48
    ├── app.config                     # .NET Framework 4.8 runtime config
    ├── appsettings.json               # configurable backend base URL
    ├── App.xaml(.cs)                  # DI-free composition root + navigation templates
    ├── Models/                        # Auth (camelCase) + Document/File (snake_case) DTOs
    ├── Mvvm/                          # ObservableObject, RelayCommand, converters
    ├── Services/                      # AppSettings, SessionState (DPAPI), API client
    ├── ViewModels/                    # Login / Register / Documents / Main (shell)
    └── Views/                         # WPF views for each view model
```

## Prerequisites

- **Windows 10/11 or Windows Server 2019/2022**
- **.NET 10 SDK** (`dotnet --list-sdks` shows `10.0.x`). It builds both targets.
  The `net48` reference assemblies are restored from NuGet
  (`Microsoft.NETFramework.ReferenceAssemblies`) when the .NET Framework 4.8 Developer Pack
  is not installed, so neither the Developer Pack nor Visual Studio is required.
- To run: the **.NET 10 Desktop Runtime** for the `net10.0-windows` build, the
  **.NET Framework 4.8 runtime** (preinstalled on current Windows) for the `net48` build.

## Configuration

The backend base URL is read from `appsettings.json` next to the running executable. The
source file `OtterWorks.Desktop/appsettings.json` is copied into each target's output folder
on build (`bin\<Configuration>\net10.0-windows\` and `bin\<Configuration>\net48\`), so change
settings in the source file to apply them to both builds. A copy edited by hand inside an
output folder applies only to that build; a copy left in `bin\<Configuration>\` from a
pre-SDK-style build is no longer read.

```json
{
  "apiBaseUrl": "http://localhost:8080/api/v1",
  "persistTokens": false
}
```

- `apiBaseUrl` — the OtterWorks API gateway base. Default `http://localhost:8080/api/v1`
  (the app runs on the same host as the Docker Compose backend). Point this at any reachable
  gateway if the backend runs elsewhere.
- `persistTokens` — when `true`, the session is saved to
  `%APPDATA%\OtterWorks\session.dat`, DPAPI-encrypted for the current user, and restored on
  next launch.

## Running the backend

From the repository root (LocalStack emulates AWS — no cloud needed):

```bash
make infra-up && make up
# or, without make:
docker compose -f docker-compose.infra.yml -f docker-compose.yml up -d --build
```

Verify it is healthy:

```bash
curl http://localhost:8080/health      # -> {"status":"healthy",...}
```

## Build

From `clients/windows-desktop`, restore and build both targets in Release:

```powershell
dotnet build OtterWorks.Desktop.sln -c Release
```

Build a single target with `-f`:

```powershell
dotnet build OtterWorks.Desktop\OtterWorks.Desktop.csproj -c Release -f net10.0-windows
dotnet build OtterWorks.Desktop\OtterWorks.Desktop.csproj -c Release -f net48
```

Visual Studio needs a version that supports the .NET 10 SDK to open the solution.

## Run

```powershell
# .NET 10
.\OtterWorks.Desktop\bin\Release\net10.0-windows\OtterWorks.Desktop.exe
# .NET Framework 4.8
.\OtterWorks.Desktop\bin\Release\net48\OtterWorks.Desktop.exe
```

Or `dotnet run --project OtterWorks.Desktop -f net10.0-windows`.

## End-to-end flow

1. **Register** a new user (display name, email, password ≥ 8 chars).
2. You land on the **Documents** list — empty for a new account.
3. Type a title and click **New** — the document appears in the list.
4. Click **Log out**, then **Sign in** with the same credentials — the document is still
   there, proving it was persisted by the real backend.

## Verification screenshots

Captured on Windows against the OtterWorks backend (auth-service, document-service and
api-gateway) running locally, base URL `http://localhost:8080/api/v1`.

### 1. Register a new user
![Register](docs/screenshots/01-register.png)

### 2. Documents list — empty for a new account
![Empty documents list](docs/screenshots/02-documents-empty.png)

### 3. Create a document — it appears in the list
![Document created](docs/screenshots/03-document-created.png)

### 4. Log out
![Logged out](docs/screenshots/04-logged-out.png)

### 5. Log back in — the document persists
![Document persists after re-login](docs/screenshots/05-document-persists.png)

## API contract used

Base URL: `http://localhost:8080/api/v1`. All non-auth calls send `Authorization: Bearer
<accessToken>`.

| Method & path        | Request                                             | Response (shape)                                        |
|----------------------|-----------------------------------------------------|---------------------------------------------------------|
| `POST /auth/register`| `{ displayName, email, password }`                  | `{ accessToken, refreshToken, tokenType, expiresIn, user }` (camelCase) |
| `POST /auth/login`   | `{ email, password }`                               | same as register                                        |
| `GET /documents`     | query `page`, `size`                                | `{ items:[…], total, page, size, pages }` (snake_case)  |
| `POST /documents`    | `{ title }`                                         | created document object (snake_case)                    |
| `GET /files`         | query `page`, `page_size`                           | `{ files:[…], total, page, page_size }` (snake_case)    |

Auth payloads are camelCase while document/file payloads are snake_case; each model carries
explicit `[JsonProperty]` attributes so one serializer handles both.
