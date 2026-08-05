---
name: web-chaos-testing
description: How to bring up the OtterWorks web stack locally and exercise chaos scenarios (both the server-side Redis flags and the browser-side `window.otterChaos` dupe) end to end in a browser. Use when testing chaos/degradation behaviour, the admin chaos panel, or anything that toggles `ow_admin_chaos_state` / `chaos:<service>:<scenario>` keys.
---

# Testing chaos scenarios on the OtterWorks web app

## Bring up the stack

```bash
cd ~/repos/otterworks
make infra-up && make up      # postgres, redis, meilisearch, localstack + all services
```

- Gateway/API: `http://localhost:8080`; production web bundle: `http://localhost:3000`.
- Give it a couple of minutes; `:8080` and `:3000` are unreachable until service images finish building.

### Run the Vite dev server when you need module-level access

`vite.config.ts` defaults to `:3000`, which the docker web app already occupies, so start it explicitly and
**read the actual port from the Vite banner** — it silently bumps to the next free port (3001 → 3002 is common):

```bash
cd frontend/client-app && npm run dev -- --port 3001
```

The dev server proxies `/api/v1` → `http://localhost:8080`, so it runs happily alongside the containers.
Use it whenever an API function has **no UI caller** (e.g. `searchApi.suggest`); only on the dev server can you do:

```js
const m = await import('/src/lib/api.ts');
await m.searchApi.suggest('inv');   // impossible in the built bundle
```

That import is also the cleanest way to time latency scenarios:

```js
const t = performance.now(); await m.documentsApi.list();
console.log(Math.round(performance.now() - t) + ' ms');
```

## Signing in / data

Log in with the `DRIVE_EMAIL` / `DRIVE_PASSWORD` secrets. If the database only contains
`admin@otterworks.dev`, generate the RetailCo tenant seed first (see the
`synthetic-testdata-generation` skill) — that creates the drive account plus files and documents.
There is **no public API for creating notifications**; seed them by writing items directly into the
LocalStack DynamoDB notifications table for the signed-in user id.

## Server-side chaos (Redis flags)

Every service reads `chaos:<service>:<scenario>` from Redis with a plain `EXISTS` check, so any value works:

```bash
docker exec otterworks-redis redis-cli set chaos:document-service:slow_queries 1 EX 180
docker exec otterworks-redis redis-cli keys 'chaos:*'
docker exec otterworks-redis redis-cli del chaos:document-service:slow_queries
```

Canonical scenario ids live in `scripts/bug-catalog.yaml`. This is the fastest way to prove that a
browser-side chaos feature has **not** leaked into the backend: with only client flags on,
`keys 'chaos:*'` must stay empty.

## Browser-side chaos (`window.otterChaos`)

Installed at boot from `src/main.tsx`. Toggle surfaces:

```js
otterChaos.enable('file-service')      // or the full redis key
otterChaos.disable('file-service')
otterChaos.active()                    // array of active scenario keys
otterChaos.reset()
```

URL params work too: `?chaos=file-service,document-service`, `?chaos=reset`, `?chaos=off`.
State lives in localStorage in two keys: `ow_client_chaos_state`, everything the client writes
(`{"file-service": {"expiresAt": <epoch ms>, "source": "client"|"admin"}}`, 10-min TTL), and
`ow_admin_chaos_state`, the admin dashboard's own `{"file-service": true}` map, which the client only
**reads** — an admin flag arms the dupe and gets an expiry stamped on first sight under `source: "admin"`.
Craft either key to simulate the admin panel or force a TTL lapse:

```js
localStorage.setItem('ow_admin_chaos_state', '{"file-service":true}');  // admin-panel shape
localStorage.removeItem('ow_client_chaos_state');                       // → lazily stamped
const s = JSON.parse(localStorage.ow_client_chaos_state);
s['file-service'].expiresAt = Date.now() - 1000;                        // force expiry
localStorage.setItem('ow_client_chaos_state', JSON.stringify(s));
```

**Gotcha:** URL-armed flags persist in localStorage after you navigate away from the `?chaos=` URL. Always
clear both keys (or call `otterChaos.reset()`) before asserting on a fresh scenario, otherwise a stale flag
from an earlier step will pollute the result.

## Known pre-existing defects (do NOT "fix" — `main` is the golden app)

- **Notification unread badge never renders.** `notificationsApi.getUnreadCount` reads `data.count` while the
  service returns `{"unreadCount": N}`, so React Query logs "Query data cannot be undefined … `["notifications","unread-count"]`"
  and `notification-bell.tsx` never paints a badge. Any test phrased as "the badge disappears" is
  unverifiable; assert on the network request / thrown chaos error instead.
- **Mark-as-read returns 403** in the local stack with chaos both on and off. Verify chaos behaviour on the
  notifications *list* rather than on mark-as-read.

## UI surfaces worth knowing

- Upload errors: `src/components/files/file-upload-dropzone.tsx` renders a red per-file message under the row.
  The Files page "Upload" button **toggles** the dropzone — a stray click closes it and the next upload silently
  no-ops, so re-open and re-pick the file if nothing seems to happen.
- Latency scenario callers: `pages/documents.tsx`, `pages/document-editor.tsx`, `pages/dashboard.tsx`,
  `pages/recent.tsx`, `pages/starred.tsx`.
- `searchApi.suggest` has no caller in `src` at all — console-only (see above).

## Devin Secrets Needed

- `DRIVE_EMAIL`, `DRIVE_PASSWORD` — seeded drive account login.
- `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `DB_PASSWORD` — used by the seed generation flow.
