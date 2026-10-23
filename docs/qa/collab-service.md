# QA audit: collab-service

Scope: `services/collab-service` (Node 20 / TypeScript, Socket.IO + y-websocket + Yjs, Redis via ioredis).
Audited on the local docker-compose core profile plus `collab-service`, with the gateway at `http://localhost:8080` and the web app at `http://localhost:3000`.

## What was exercised

- **WebSocket auth.** Socket.IO JWT middleware: missing, malformed, wrong-secret, expired, `alg=none`, header fallback, refresh tokens and tokens with no `sub`. The y-websocket upgrade path: missing/invalid token → 401, valid token → sync step 1.
- **Rooms.** `join-document` ack, `sync-document`, `user-joined`, `user-left`, room switching, `leave-document`, disconnect, and the last member leaving (persist to Redis, then evict the in-memory doc).
- **Presence.** `presence-update` broadcasts, per-socket/tab counting, `GET /api/v1/collab/documents[/:id/presence]` through the gateway (401 without a JWT) and directly on :8084, idle cleanup (`session-expired`), and color assignment.
- **CRDT fan-out.** Real Yjs updates are applied server-side, fanned out with no echo to the sender, concurrent edits converge, corrupt updates get `document-update-error` and no fan-out, and updates to unloaded docs are ignored.
- **Reconnect and Redis state.** A rejoining socket gets the merged state. State reloads from Redis after eviction. Concurrent first joins share one Y.Doc. Redis failures are handled on join, persist, snapshot and history. The periodic persist loop runs, and `stop()` flushes everything.
- **Cursor, typing, comments, snapshots, history.** Identity is taken from the token (a spoofed `author` is overwritten). Non-members' cursor/typing events are dropped.
- **Invalid messages.** Missing or `null` payloads on every handler, and a non-string `documentId`.
- **Config and Redis adapter.** Env defaults and overrides, key prefixing, TTL `SETEX` vs `SET`, ping, pub/sub channel filtering, disconnect.
- **UI (Playwright and computer use).** The same document open in two browser windows, with edits and collaboration cursors propagating both ways. Navigate-away/reconnect catch-up and offline/online recovery.

## Test pyramid

| Layer | Location | Tests | Pass | xfail / skip |
|---|---|---|---|---|
| Unit (Jest) | `services/collab-service/src/__tests__/qa-*.test.ts` (6 new suites + helpers) | 86 new (131 in the suite with the 45 existing) | 68 new + 45 existing | 18 `it.failing` (COLLAB-01 ×10, -02 ×3, -03, -04 ×2, -05, -09) |
| Functional / API (pytest) | `tests/api/test_qa_collab_service.py` | 33 | 24 | 8 xfail (strict) + 1 skip (COLLAB-01, destructive) |
| E2E (Playwright) | `frontend/client-app/e2e/qa-collab-service.spec.ts` | 4 | 4 | 0 |
| E2E (computer use) | Testing-agent recording (linked in the PR) | 1 flow | see PR comment | – |

How to run:

```bash
cd services/collab-service && npm test
python -m pytest tests/api/test_qa_collab_service.py -rxXs   # stack + collab-service up
OTTERWORKS_QA_DESTRUCTIVE=1 python -m pytest tests/api/test_qa_collab_service.py -k payloadless  # crashes the container
cd frontend/client-app && BASE_URL=http://localhost:3000 npx playwright test e2e/qa-collab-service.spec.ts
```

## Findings

| ID | Severity | Location | Repro | Expected | Actual |
|---|---|---|---|---|---|
| COLLAB-01 | **High** | `src/handlers/collaboration.ts:109` (join), `:183` (leave), `:208` (update), `:272` (cursor), `:301`/`:319`/`:343`/`:367`/`:383`/`:421` | Any authenticated client: `socket.emit('join-document')` with no payload (or `null` for `document-update`) | Event is rejected or ignored | `TypeError: Cannot destructure property 'documentId' of 'data' as it is undefined` escapes the listener → Node process exits. The container exits with code 1 and has no restart policy, so collaboration goes down for every user (verified through the gateway). |
| COLLAB-06 | **High** | `src/handlers/collaboration.ts:104` (Socket.IO join), `src/index.ts:158` (y-websocket upgrade) | User B, who gets 403 from `GET /api/v1/documents/{id}`, joins the doc over Socket.IO, or opens `ws://:8084/document-{id}?token=…` | Join is refused for anyone without access to the document | Join succeeds. B receives the full CRDT state in `sync-document` and can edit live. The only check is a valid JWT. |
| COLLAB-02 | **High** | `src/handlers/collaboration.ts:242` (`document-update`), `:272`, `:301`, `:319`–`:367` | Socket that never joined `doc:X` emits `document-update` / `comment-add` / `comment-delete` / `cursor-update` with `documentId: X` | Ignored (sender is not a member of the room) | Fanned out to every member of `doc:X`, and the Yjs update is applied and persisted. Cursor and typing events go to the client-supplied room even when the sender joined a different doc. |
| COLLAB-03 | Medium | `src/handlers/collaboration.ts:421` | Non-member emits `request-history {documentId: X}` | Refused | Returns snapshot list with base64 `state` of document X |
| COLLAB-04 | Medium | `src/middleware/auth.ts:40-43` | Connect Socket.IO with the auth-service **refresh** token, or a signed token with no `sub` | Rejected (`type` must be `access`, `sub` is required) | Accepted. With no `sub`, `userId` is `undefined`, and presence, comments and `lastModifiedBy` record `undefined`. |
| COLLAB-07 | Medium | `src/index.ts:72`, `:79` | `curl http://localhost:8084/api/v1/collab/documents/{id}/presence` with no auth | 401 (defense in depth; the gateway already enforces JWT) | 200, with `userId`, `email` and `displayName` of everyone in the doc and a list of all active doc ids |
| COLLAB-08 | Medium | `src/index.ts:133` (`setupWSConnection`) | Open the doc in the web editor (y-websocket), then query presence | Web editors appear in presence, and their state is persisted to Redis | The y-websocket path keeps a separate in-memory Y.Doc (no `YPERSISTENCE`, no Redis). It bypasses `AwarenessService`, metrics and snapshots, so presence shows 0 while two people edit, and live CRDT state is lost on restart. |
| COLLAB-05 | Low | `src/handlers/collaboration.ts:109` | `join-document {documentId: {"$ne": null}}`, or `""` | Rejected | Object or empty ids create rooms, Y.Docs and Redis keys (`doc:state:[object Object]`) |
| COLLAB-09 | Low | `src/config.ts:43` | Start without `JWT_SECRET` | Startup fails | Falls back silently to the hard-coded `otterworks-dev-secret` |

Other observations (outside this unit, not tested as findings):

- The web editor's `CollaborationCursor` sometimes labels the remote caret "Anonymous". The extension is configured before the auth user has loaded (`frontend/client-app/src/components/editor/collaborative-editor.tsx`).
- The frontend defaults `VITE_COLLAB_WS_URL` to `ws://localhost:8085`, but the service listens on 8084. docker-compose passes 8084 as a build arg, so the container works, but `npm run dev` without the env var does not connect.
- y-websocket takes the JWT in the query string (`?token=`), so it can end up in proxy and access logs.

## Not tested, and why

- **Two different users on one document in the UI.** document-service has no edit-sharing for documents (`/share` only mints a read-only link, and `GET /documents/{id}` is owner-only), so the UI flow uses one user in two browser windows/contexts. The cross-user path is covered at the API layer, where it is COLLAB-06.
- **Horizontal scale-out / Redis pub/sub across replicas.** `RedisAdapter.publish/subscribe` is unit-tested, but `CollaborationManager` never uses it and Socket.IO has no Redis adapter. Running more than one replica would split rooms; that was not exercised.
- **Real Redis outage at runtime** (the degradation marker) is covered only with mocks in unit tests. Stopping the shared Redis would disturb the rest of the stack.
- **Presence idle cleanup at real timescales** (60 s interval / 5 min idle) is covered only in unit tests with injected timestamps.
- **COLLAB-01 in CI.** The API test is skipped by default because it kills the container. Enable it with `OTTERWORKS_QA_DESTRUCTIVE=1`.

## Environment notes

- On this VM, a system `mono-xsp4` service listened on host port 8084 and blocked collab-service from binding it. It was stopped with `sudo systemctl stop mono-xsp4`.
- If the core stack is re-created after `collab-service` starts, the collab container can be left with no network attached (`EAI_AGAIN redis`). Fix: `docker compose ... up -d --no-deps --force-recreate collab-service`.
