# Document Service

The document service owns document metadata, versions, templates, and comment
threads for OtterWorks. It is a Python 3.12 / FastAPI service using asynchronous
SQLAlchemy against PostgreSQL, with Alembic migrations for schema changes.

The container listens on port `8083`. The API gateway routes
`/api/v1/documents` to this service.

## API surface

The main route groups are:

- **Documents** — create, list, search, retrieve, update, patch, and soft-delete
  documents.
- **Versions and export** — list versions, restore a version, and export a
  document as Markdown, HTML, or PDF text.
- **Templates** — list and create templates, plus create a document from a
  template.
- **Comments** — add, list, resolve, unresolve, and delete comments.

The application also exposes `/health` and `/metrics`. Templates are mounted
under `/api/v1/templates`; the gateway's document-service route is
`/api/v1/documents`.

## Comment resolution

Comment resolution is represented by three columns on `comments`:

- `is_resolved` — non-null Boolean, defaulting to `false`.
- `resolved_by` — nullable UUID of the user who resolved the comment.
- `resolved_at` — nullable timezone-aware timestamp.

These columns are added by Alembic revision `002_comment_resolution` (revision
`002`, after `001`).

The resolution endpoints are mounted below the document gateway prefix:

- `POST /api/v1/documents/{document_id}/comments/{comment_id}/resolve`
  accepts `{"resolved_by": "<uuid>"}` and returns `CommentResponse`.
- `POST /api/v1/documents/{document_id}/comments/{comment_id}/unresolve`
  accepts no body and returns `CommentResponse`.

Both endpoints return `404` when the comment does not exist for the supplied
document. Resolving an already-resolved comment short-circuits; unresolving is
idempotent in its observable result but still issues a commit (SQLAlchemy emits
no `UPDATE` when values are unchanged). Unresolving clears `is_resolved`,
`resolved_by`, and `resolved_at`. Only the unresolved-to-resolved transition
publishes an event: repeated resolves and unresolve publish nothing.

`GET /api/v1/documents/{document_id}/comments` accepts the
`include_resolved` query parameter, which defaults to `true` to preserve the
existing behavior. When it is `false`, resolved comments are excluded. Results
remain ordered by `created_at` ascending.

On the unresolved-to-resolved transition, the service publishes a
`comment_resolved` event through its SNS event publisher when SNS publishing is
enabled. Its payload contains:

```json
{
  "comment_id": "<uuid>",
  "document_id": "<uuid>",
  "author_id": "<uuid>",
  "resolved_by": "<uuid>",
  "resolved_at": "<timestamp>"
}
```

`author_id` is the comment author, i.e. the user the notification-service is
meant to target. A repeated resolve returns the current state without
publishing another event.

**Known cross-service gap (pre-existing, applies to `comment_added` too):** this
publisher wraps payloads as `{event_type, timestamp, payload: {...snake_case}}`
and sets the SNS message attribute `event_type`, while notification-service
expects a flat camelCase body with a top-level `eventType` and the notifications
SNS subscription filters on an `eventType` attribute. Until one side is aligned
(search-service normalizes both shapes in `app/services/sqs_consumer.py` and is
the natural reference), document-service comment events do not reach the
notification queue.

## Local development and tests

The CI workflow runs these commands from this directory:

```bash
pip install poetry==1.8.2
poetry install
poetry run ruff check .
poetry run pytest --cov=app
```

To run the service locally:

```bash
poetry run uvicorn app.main:app --reload --port 8083
```

Alembic uses the service's configured database URL. Apply all migrations or
roll back one revision with:

```bash
poetry run alembic upgrade head
poetry run alembic downgrade -1
```
