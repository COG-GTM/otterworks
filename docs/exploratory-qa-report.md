# OtterWorks Exploratory QA Report

Test date: May 1, 2026  
Scope: Local app running via `make up`  
Web app: `http://localhost:3000`  
Admin dashboard: `http://localhost:4200`

## Summary

The app is functional for a local Google Drive-style replacement prototype. Auth, file upload, folder creation, file sharing, shared-with-me, trash, document creation/editing, search, mobile smoke checks, and admin login all worked during exploratory testing.

No code fixes were made during this pass. This document captures bugs, UI jank, and UX/product opportunities.

## Overall Assessment

### Working well

- **Auth:** Registration and login succeeded.
- **Files:** Upload, list, detail page, sharing, shared-with-me, and trash all worked.
- **Documents:** Document creation, editor load, typing, autosave/list return all worked.
- **Search:** Search found the uploaded file and the test document.
- **Admin dashboard:** Admin login succeeded.
- **Mobile basics:** No horizontal overflow found on dashboard, files, documents, search, or settings.

### Main concerns

- **Notifications:** Notification endpoints return `400 Bad Request` across authenticated pages.
- **Settings:** Settings page calls a missing `/api/v1/settings` endpoint.
- **Observability:** `fluent-bit` and `otel-collector` are running but unhealthy.
- **Preview UX:** Uploaded text file detail page loaded, but file contents were not visible inline.
- **Drive parity:** Key Drive-like workflows are still missing or underdeveloped.

## Confirmed Bugs

### High Priority

#### Notifications API returns `400` everywhere

Every authenticated route repeatedly calls:

```text
GET /api/v1/notifications/unread-count
```

This returns `400 Bad Request`.

The notifications page also calls:

```text
GET /api/v1/notifications?page=1&pageSize=20
```

This also returns `400 Bad Request`.

**Impact:**

- **Notification badge/system is unreliable.**
- **Browser console is noisy across the app.**
- **The notifications page renders an empty state even while its data calls fail.**

**Evidence:**

- API gateway logs showed repeated `400` responses for `/api/v1/notifications/unread-count`.
- Browser network sweep reproduced this on:
  - `/dashboard`
  - `/files`
  - `/documents`
  - `/search`
  - `/shared`
  - `/trash`
  - `/notifications`
  - `/settings`

#### Settings endpoint is missing

The settings page loads visually, but calls:

```text
GET /api/v1/settings
```

This returns `404 Not Found`.

**Impact:**

- **Settings are likely not loaded from or saved to the backend.**
- **The form appears functional, but persistence is missing or unrouted.**

#### Observability sidecars are unhealthy

These containers are running but unhealthy:

- **`otterworks-fluent-bit`**
- **`otterworks-otel-collector`**

The core app services are healthy, but the local setup is not fully healthy from an operations perspective.

### Medium Priority

#### Text file preview does not visibly show file contents

Uploaded `.txt` file detail page loaded correctly and showed Preview/Details sections. However, the page body did not include the uploaded text content.

**Impact:**

- **Inline preview is a core expectation for a Google Drive replacement.**
- **Users may need to download simple text files just to inspect them.**

#### Download action has no visible feedback

The Download button exists on the file detail page. There is no visible confirmation, progress, or failure/success state after clicking.

**Impact:**

- **If download silently fails, the user has no clear signal.**
- **Large file downloads will feel opaque.**

#### RSC navigation console errors

Several page transitions logged errors similar to:

```text
Failed to fetch RSC payload ... Falling back to browser navigation
```

The app still navigated, but this indicates Next.js client navigation instability or aborted prefetches.

**Impact:**

- **May cause janky route transitions.**
- **Adds noisy console output during normal use.**

#### Trash delete flow lacks confirmation

Moving a file to Trash worked. The Trash page shows Restore and Delete actions, but destructive permanent deletion should be confirmed.

**Impact:**

- **Users may permanently delete content accidentally.**
- **Trash semantics should be clearer.**

## UI Jank / UX Issues

### Navigation and layout

- **Sidebar is dense:** The nav works, but Drive-like grouping would be clearer.
- **Mobile layout fits but is not optimized:** No horizontal overflow was detected, but the sidebar-heavy IA may feel cramped on real mobile devices.
- **Breadcrumb/heading duplication:** Several pages show repeated page names, e.g. Files/Files or Documents/Documents.

### File management

- **Upload panel stays open after upload:** Useful for batches, but can feel cluttered after a single successful upload.
- **File card overflow menu is hover-dependent:** This can be hard to discover on touch devices.
- **No clear upload progress:** Upload status appears, but not rich progress, speed, retry, or cancellation UX.
- **No obvious folder upload:** Google Drive users expect folder uploads with nested structure preservation.

### Sharing

- **Sharing works but permissions are basic:** File sharing to another registered user worked.
- **Missing permission controls:** No obvious controls for restricted vs anyone-with-link, remove access, change access after sharing, owner transfer, or expiration.
- **Potentially misleading link copy:** The Get link tab says “Anyone with the link can view this file,” but link access behavior was not validated.

### Documents

- **Document title/snippet hierarchy is confusing:** The document list showed typed content and `Untitled document`, making it unclear what is title vs preview.
- **Save state could be clearer:** The editor should clearly show `Saving...`, `Saved`, `Offline`, and reconnect/conflict states.
- **Document sharing appears less robust than file sharing:** File sharing was validated; document sharing needs deeper testing and likely stronger permission UX.

## Product Gaps vs Google Drive Replacement

### Must-have Drive replacement features

- **Recent:** Dashboard has recent files/docs, but there is no dedicated Recent route.
- **Starred/Favorites:** No starred items flow found.
- **Shared drives/team spaces:** Current model appears user-centric only.
- **Advanced search filters:** Missing owner, date modified, MIME/file type, location/folder, shared status, trash inclusion, and exact phrase/content controls.
- **File preview breadth:** Needs strong previews for PDF, images, text/code, Office docs, CSV/spreadsheets, audio, and video.
- **Version history:** File detail has version-related UI, but uploaded test file did not show meaningful versions.
- **Per-file activity timeline:** Need uploaded, renamed, moved, shared, downloaded, deleted, and restored history.
- **Move/copy operations:** No obvious Move to folder, Copy, Make a copy, drag-to-move, or multi-select move flows were found.
- **Storage quota UX:** Dashboard shows storage, but Drive-like apps usually show persistent quota in the sidebar and quota controls.

## Easy Win Features

- **Add Recent and Starred pages:** High familiarity and likely moderate complexity.
- **Add visible toast/error details for failed APIs:** Especially settings and notifications.
- **Add visible document save status:** Show `Saving...`, `Saved`, and offline/reconnect states.
- **Add confirm dialogs:** Permanent delete, empty trash, and delete folder with contents.
- **Add quick actions to file cards:** Download, Share, Star, More; keep visible on mobile.
- **Improve upload UX:** Collapse upload tray after success, add retry, progress/count, and folder upload.
- **Improve share dialog:** Add restricted/anyone-with-link selector, accurate copy-link status, remove access, and change access controls.
- **Fix settings persistence or hide nonfunctional settings:** Since `/api/v1/settings` is missing, implement it or clearly disable backend-backed controls.

## Tested Flows

- **Auth:** Register and login.
- **Files:** Upload text file, create folder, list files/folders, open file detail, share file, verify shared-with-me, delete to trash.
- **Documents:** Create document, load editor, type content, return to list.
- **Search:** Search uploaded filename/content token and document token.
- **Trash:** Confirm deleted file appears in Trash.
- **Settings:** Confirm page renders and detect backend settings API failure.
- **Notifications:** Confirm page renders empty state and detect notification API failures.
- **Admin:** Login with seeded admin credentials.
- **Responsive:** Check dashboard, files, documents, search, and settings at `390x844` viewport.

## Service Health Snapshot

Core app services returned healthy responses:

- **Web app:** `200`
- **Admin dashboard:** `200`
- **API gateway:** healthy
- **Auth service:** healthy
- **File service:** healthy
- **Document service:** healthy
- **Collab service:** healthy
- **Notification service:** healthy endpoint, but functional notification API returns `400`
- **Search service:** alive
- **Analytics service:** healthy
- **Admin service:** healthy
- **Audit service:** healthy
- **Report service:** healthy

Unhealthy containers:

- **`otterworks-fluent-bit`**
- **`otterworks-otel-collector`**

## Test Artifacts

Throwaway users created during local testing:

- **User A:** `drive-tester-a-1777664932516@otterworks.test`
- **User B:** `drive-tester-b-1777664932516@otterworks.test`

Sample uploaded file:

- **`otterworks-sample-1777664932516.txt`**

Screenshots were saved under `/tmp/` during the exploratory pass, with filenames beginning with:

```text
/tmp/otterworks-1777664932516-
```

## Completion Status

Exploratory testing is complete. The app was exercised end-to-end through core Google Drive-like workflows, backend/API behavior was checked, and bugs plus UX/product opportunities were documented. No application code was modified.
