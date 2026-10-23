# QA audit: file-service

Scope: `services/file-service` (Rust/actix-web). Covers upload/download, ranged reads, folders, rename/move, star, share,
trash/restore/permanent delete, size/type validation, and ownership (IDOR) checks on every route.
Run against: the local core stack (`/home/ubuntu/otterworks-up.sh`) with the gateway at `http://localhost:8080` and the web app at `http://localhost:3000`.

## Test pyramid

| Layer | Location | New tests | Pass | xfail |
|---|---|---|---|---|
| Unit (`cargo test`) | `services/file-service/src/tests/` | 60 | 37 | 23 (`#[ignore]`, run with `cargo test -- --ignored`: all 23 fail as expected) |
| Functional / API (pytest through the gateway) | `tests/api/test_qa_file_service.py` | 43 | 25 | 18 (`xfail(strict=True)`) |
| E2E (Playwright) | `frontend/client-app/e2e/qa-file-service.spec.ts` | 4 | 2 | 2 (`test.fail`) |
| E2E (computer use) | Recording linked in the PR | 1 run | 12 steps pass | FS-14 reproduced; FS-15 found; move not tested in the UI (no move control) |

The 24 unit tests that already existed (parsers, config, alerts, events, health) still pass. Before this audit the service
had no tests that called a handler through its route.

**How the unit tests work.** The handlers run through their real actix routes. `configure_routes` was pulled out of
`main.rs` so the tests can mount the same route table. They use the real AWS SDK clients, wired to an in-memory HTTP
fake (`src/tests/fakes.rs`) that implements the DynamoDB, S3 and SNS operations the service calls, plus a small RESP
fake for the Redis chaos flag. Nothing reaches LocalStack, AWS, admin-service or Slack: the alert URL is empty in the
test config. The only production-code change is that route extraction plus a `#[cfg(test)]` constructor on
`EventPublisher`; the service's behaviour is unchanged.

Commands:
```
cd services/file-service && cargo test                  # 61 passed, 23 ignored
cd services/file-service && cargo test -- --ignored     # the 23 findings, all fail
python -m pytest tests/api/test_qa_file_service.py      # 25 passed, 18 xfailed
cd frontend/client-app && npx playwright test e2e/qa-file-service.spec.ts   # 4 passed (2 expected-fail)
```

## What was exercised

- **Upload:** owner comes from the gateway's `X-User-ID`, and a spoofed multipart `owner_id` is ignored. The multipart
  owner is only used when the header is missing. Also covered: empty file, missing file part, bad owner/folder ids, the
  size limit at exactly `max_upload_bytes` and one byte over (413), 413 through the gateway at 100 MB + 1, the
  default MIME type, the S3 key layout, writing the first version, the `file_uploaded` event, and both failure
  switches (`FILE_UPLOAD_ALWAYS_FAIL` and the Redis `chaos:file-service:upload_s3_error` flag): they return 500 and
  write no metadata.
- **Download:** the presigned URL contains the bucket/key, signature and 3600 s expiry. The bytes behind it match the
  upload. A ranged GET on the presigned URL returns `206` with `Content-Range: bytes 2-5/16`.
- **Metadata, versions and activity:** `shared_with` on the detail view, 400 for bad ids and 404 for unknown ids on
  every ID route, the activity feed (needs a user, mixes upload and share items, caps `limit`), pagination clamping
  (`page>=1`, `page_size<=100`).
- **Folders:** create, get, list (root and by parent), rename, reparent, delete. Listing is scoped to the gateway user.
- **Rename/move:** rename trims the name and rejects blank or whitespace names. Move works into a folder and back to
  root (removes `folder_id`).
- **Trash/restore/delete:** a trashed file is hidden from the listing and appears in Trash. Restore brings it back.
  Unknown ids return 404 via the DynamoDB condition. Permanent delete removes both the metadata and the S3 object.
- **Share:** a new share returns 201. Re-sharing is idempotent (200, same id). A permission change updates the
  existing record. One `file_shared` event is sent per new share. Covered: invalid role, no recipient, unknown email,
  the share-notify failure switch (500 `event_error`, share still saved), revoke followed by a second revoke (404),
  and "shared with me" (hides trashed files, dedupes).
- **Star:** there is no file-service route. Stars are kept in browser `localStorage` (`otter_starred_items`), so they
  were tested only in the UI (star on the Files page, then check the Starred page).
- **Gateway:** every file/folder route returns 401 without a JWT. A client-supplied `X-User-ID` is replaced by the
  gateway.

## Findings

| ID | Severity | Route / location | Repro | Expected | Actual | Test(s) |
|---|---|---|---|---|---|---|
| FS-01 | Critical | `GET /files/{id}`, `/download`, `/versions`. `handlers.rs` `get_file_metadata`, `download_file`, `list_versions` | User B calls these routes with user A's file id | 403/404 unless B owns the file or it is shared with B | 200. B gets A's metadata and a working presigned download URL | `authz::idor_get_metadata/download/versions`, API `test_non_owner_is_denied[FS-01-*]`, e2e `FS-01` |
| FS-02 | Critical | `PATCH /rename`, `PUT /move`, `POST /trash`, `POST /restore`, `DELETE /files/{id}`. `metadata.rs` updates are keyed on `id` only | Same as FS-01 with the mutating routes | 403/404 | 200/204. B can rename, move, trash or **permanently delete** A's file | `authz::idor_*`, `authz::current_non_owner_can_read_and_mutate_any_file` (pins today's behaviour), API `[FS-02-*]` |
| FS-03 | High | `POST /files/{id}/share`, `DELETE /files/{id}/share/{user}`. `share_file` / `remove_share` | B shares A's file with B as editor, or revokes A's shares. `shared_by` comes from the request body | Only the owner can share or revoke. `shared_by` = authenticated user | Any user can share or revoke. `shared_by` can be set to anyone | `authz::idor_share`, `idor_remove_share`, `share_records_authenticated_sharer`, API `[FS-03-*]`, `test_non_owner_cannot_revoke_share` |
| FS-04 | High | `GET/PUT/DELETE /folders/{id}`, `POST /folders` (`owner_id` from body) | B reads, renames or deletes A's folder, or creates a folder with `owner_id = A` | 403/404. Owner = authenticated user | All succeed | `authz::idor_*folder*`, `create_folder_uses_authenticated_owner`, API `[FS-04-*]` |
| FS-05 | Low | `GET /files/{id}/download` | Send `Range: bytes=0-3` to the API | Ranged/streaming download, or a documented contract | The service always returns a JSON presigned URL and ignores Range. Ranged reads only work against S3 directly (works, 206) | API `test_download_endpoint_honours_range_header` |
| FS-06 | Medium | `POST /files/upload` | Upload `x.html` with `text/html` (or SVG) | Reject active content, or store/serve it as `application/octet-stream` / attachment | Stored with the MIME type the client declared; S3 serves it inline | `files::finding_fs06_*`, API `test_active_content_upload_is_rejected_or_neutralised` |
| FS-07 | Low | `DELETE /files/{id}` | Share a file, then permanently delete it | Share rows removed | Share rows are left behind, and the owner's activity keeps "Shared a file" entries | `shares::finding_fs07_*` |
| FS-08 | Medium | `DELETE /folders/{id}` | Delete a folder that contains files | Refuse (409), or move the contents to root/trash | The folder is deleted and its files keep a `folder_id` that points to it (orphans) | `folders::finding_fs08_*` |
| FS-09 | Low | `DELETE /folders/{id}` | Delete a random UUID | 404 | 204 | `folders::finding_fs09_*`, API `test_delete_unknown_folder_is_404` |
| FS-10 | Low | `PUT /files/{id}/move` | Move to a random folder UUID | 400/404 | 200; the file disappears into a folder that does not exist | `folders::finding_fs10_*`, API `test_move_into_unknown_folder_is_rejected` |
| FS-11 | Low | `POST /folders`, `PUT /folders/{id}` | Blank name, or `parent_id = self` | 400 | Both accepted (blank names, parent cycles) | `folders::finding_fs11_*` |
| FS-12 | Low | trash state | Trash a file, then download it | Trashed files are read-only/hidden until restored | Still downloadable, renamable and shareable | `files::finding_fs12_*` |
| FS-13 | Low | `GET /files/{id}/versions` | Random UUID | 404 | `200 {"versions":[]}` | `files::finding_fs13_*` |
| FS-14 | Medium | `storage.rs` `presigned_download_url` | Click **Download** on the file detail page | The browser saves the file | The presigned URL has no `response-content-disposition=attachment`, and the `download` attribute is ignored across origins, so the app tab navigates to the raw object (and renders HTML inline; see FS-06) | e2e `FS-14` |

| FS-15 | Low | web-app `pages/file-detail.tsx` (not file-service) | The share recipient opens a file shared with them | Owner shows the sharer | Owner is shown as "You" | computer-use run (screenshot in the PR) |

Notes (not defects in this unit):

- **Star:** there is no server-side star. Stars are per-browser `localStorage`, so they don't follow the user to
  another device and can't be checked through the API.
- **Move:** the web app has no "move" UI (no menu item and no drag-and-drop). The e2e test moves the file through the
  gateway API.

## Not tested, and why

- **Real AWS behaviour** (IAM, KMS, real S3 Range/checksum semantics) was not tested. The rules say no real AWS calls.
  Ranged reads were checked against LocalStack only.
- **Alert delivery to admin-service/Slack:** the unit tests check that the failure paths return the right errors with
  alerts disabled. Real delivery was not triggered, per the rules.
- **Concurrency/races** (for example two people sharing at the same time, which can leave duplicate share rows that
  the listing dedupes) are not covered.
- **Demo-doc seeding** (`FILE_SEED_DEMO_DOCS`) is disabled in the unit tests and not exercised.
