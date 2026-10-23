# QA audit: document-service

Scope: `services/document-service` (Python FastAPI). Covers documents CRUD, versions/restore, templates
and create-from-template, pagination, validation, ownership/authz, search, export, share links,
comments, and the Alembic migration. Tested on a local core stack (`/home/ubuntu/otterworks-up.sh`;
gateway `:8080`, web `:3000`) built from `origin/main`.

## Test pyramid

| Layer | Location | Tests | Result |
|---|---|---|---|
| Unit (pytest, SQLite in-memory) | `services/document-service/tests/test_qa_document_service.py` | 111 | 98 passed, 13 xfailed |
| Unit: migrations | `services/document-service/tests/test_qa_alembic.py` | 5 | 4 passed, 1 skipped (live Postgres test, needs `QA_ALEMBIC_DATABASE_URL`; passes locally) |
| Functional / API (via gateway) | `tests/api/test_qa_document_service.py` | 43 | 31 passed, 12 xfailed |
| E2E (Playwright) | `frontend/client-app/e2e/qa-document-service.spec.ts` | 3 | 3 passed |
| E2E (computer use) | testing-agent browser run (recording in the PR) | 1 flow | see PR comment |

Whole service suite: `164 passed, 1 skipped, 13 xfailed`. Every xfail is `strict=True` and its reason names a
finding below, so the suite fails if a defect gets fixed without the test being updated.

How to run:

```bash
cd services/document-service && poetry run pytest                     # unit
QA_ALEMBIC_DATABASE_URL=postgresql+asyncpg://otterworks:otterworks_dev@localhost:5432/<scratch_db> \
  poetry run pytest tests/test_qa_alembic.py                         # live migration up/diff/down
make test-api-flows   # or: python -m pytest tests/api/test_qa_document_service.py
cd frontend/client-app && CI=1 npx playwright test e2e/qa-document-service.spec.ts
```

## Coverage

- **Unit:** `_word_count`, `paginate`, schema defaults and validation (title length, null-patch rejection),
  JWT handling (`user_id`/`sub`, bad signature, expired, malformed, `X-User-ID` fallback only when no
  secret is set), owner-only GET/PUT/PATCH/DELETE/versions/restore/export/share, soft delete, version
  creation and restore, pagination maths and bounds, folder/title/content-type filters, search, export
  formats, share-link mint/verify, templates CRUD and from-template, event publishing on create/update/delete.
- **Migrations:** single linear head `001`; offline upgrade SQL creates all four tables, FKs and indexes; every
  ORM column is in the migration; offline downgrade drops everything. Live run against Postgres 16:
  `downgrade base -> upgrade head` applies cleanly, `compare_metadata` shows **no drift** against the models,
  and re-running down/up works.
- **Functional (gateway):** blank create, edit, rename, reload, delete, then 404 on re-delete; template, then
  from-template; PUT, version list, restore; pagination and 422 bounds; literal `%` search on Postgres;
  export; share-link round trip; validation 422s; gateway 401 with no token and with a spoofed `X-User-ID`;
  non-owner 403 on every per-document route; list scoped to the caller by default.
- **E2E (Playwright):** register, then New document, type in the Tiptap editor, Save (PATCH), reload and check
  the content persisted, rename the title, reload, delete, check the document is gone from the list. Also: a
  from-template document opens with the template content, edit, save, reload. Also: a second user opening
  the URL sees "Document not found".

## Findings

Line numbers are on `origin/main` at the time of the audit. Repros are gateway requests from user B with a valid JWT unless noted.

| ID | Severity | Location | Repro | Expected | Actual |
|---|---|---|---|---|---|
| DOC-QA-01 | High | `app/api/documents.py:291`, `:325` (`effective_owner = owner_id or ...`) | `GET /api/v1/documents/?owner_id=<A>` as B | Only the caller's documents (or 403) | All of A's documents |
| DOC-QA-02 | Medium | `app/api/documents.py:277-305` | Service-level `GET /api/v1/documents/` with no identity | 401 | 200 with every document. The gateway rejects this, so it's only reachable inside the cluster |
| DOC-QA-03 | High | `app/api/documents.py:156-173`, `app/services/document_service.py:258` | `GET /api/v1/documents/search?q=<A's title>` as B | Results from the caller's documents only | A's documents returned (search has no owner filter) |
| DOC-QA-04 | High | `app/api/documents.py:114` | `POST /api/v1/documents/` as B with `{"owner_id": "<A>"}` | Owner set from the JWT, or 403 | 201 with the document owned by A |
| DOC-QA-05 | High | `app/api/documents.py:500-520` | `POST /api/v1/documents/from-template/<id>` with `{"owner_id":"<A>"}` | Owner from the JWT; route checks auth | No auth dependency; `owner_id` is required and trusted from the body |
| DOC-QA-06 | Medium | `app/api/templates.py:15-35` | Service-level `GET/POST /api/v1/templates/` with no identity; `created_by` taken from the body | 401; creator from the JWT | 200/201. The gateway enforces auth, but `created_by` can be spoofed |
| DOC-QA-07 | High | `app/api/comments.py:17-50` | As B: `GET /api/v1/documents/<A doc>/comments`, then `POST` with `{"author_id":"<A>"}` | 403 for non-owners; author from the JWT | 200 / 201 with the comment attributed to A |
| DOC-QA-08 | Critical (OW-SEC-401) | `app/services/document_query_repository.py:49-55`, `:92` | `GET /api/v1/documents/?title=%25') OR 1=1 --` as B | Filter applied as a bound parameter | SQL injection: returns every user's documents |
| DOC-QA-09 | Low | `app/schemas/document.py:12` | `POST` with `{"title":"   "}` | 422 | 201 with a blank title |
| DOC-QA-10 | Critical (OW-SEC-402) | `app/api/documents.py:176-183`, `app/services/export_archive.py:32` | `GET /api/v1/documents/exports?name=../../../../etc/passwd` | 400/404 | 200 with `/etc/passwd` contents (arbitrary file read) |
| DOC-QA-11 | High (OW-SEC-403) | `app/services/share_link.py:23,31` | `md5(f"{doc_id}:otterworks-share")[:16]` then `GET /api/v1/documents/shared?document_id=..&token=..` | Unforgeable (HMAC with a secret) | Token forged from the public default salt; 200 with the document |
| DOC-QA-12 | Medium | `app/schemas/document.py:14` vs `app/models/document.py:26` (`String(50)`) | `POST` with a 51-char `content_type` | 422 | 500 Internal Server Error (DB truncation error) |
| DOC-QA-13 | Medium | `app/api/documents.py:251` | `GET /api/v1/documents/?sort=title;--` | 400 with a generic message | 400 body echoes the raw SQL statement and the asyncpg error |
| DOC-QA-14 | Low (UX gap) | `frontend/client-app/src/pages/documents.tsx` | Look for a template picker in the web app | Create from template in the UI | No template UI. The e2e template flow is seeded via the API and then verified in the editor |
| DOC-QA-15 | Low (contract drift) | `tests/api/test_document_flow.py:66` vs `app/services/document_service.py:210` | `make test-api-flows` | Shared flow test and service agree | Service returns versions newest-first (commit `c0aa96dc`); the existing shared test expects `[1,2,3]` and fails. Not edited (shared file) |

Not a defect: unit-level `%`/`_` search escaping only fails on SQLite, which ignores `\` escapes without
`ESCAPE`. On Postgres (functional test) wildcards are treated literally.

## Could not test / limits

- **Real-time collaboration:** the editor's Yjs websocket (collab-service) is not in the core profile, so the
  editor runs in "Offline" mode. Persistence goes through the REST PATCH save path only.
- **SNS/SQS event fan-out:** disabled locally (`sns_enabled=false`); only checked at unit level with a mocked publisher.
- **Production/Kubernetes migration path:** migrations were checked against local Postgres 16, not RDS.
- **Latency/chaos injection** (`_maybe_inject_latency`) was not exercised.
