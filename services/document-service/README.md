# Document Service

FastAPI service for document CRUD, version history, templates, and document
comment threads. It uses Python 3.12, SQLAlchemy's async API, PostgreSQL, and
Alembic migrations.

## API

Routes are exposed under `/api/v1`:

- `GET|POST /documents/{document_id}/comments`
- `POST /documents/{document_id}/comments/{comment_id}/resolve`
- `POST /documents/{document_id}/comments/{comment_id}/unresolve`
- `DELETE /documents/{document_id}/comments/{comment_id}`

Comment listing includes resolved comments by default; pass
`include_resolved=false` to list open comments only. Resolving a comment emits
the `comment_resolved` domain event for notification delivery.

## Local development

```bash
poetry install
poetry run alembic upgrade head
poetry run uvicorn app.main:app --reload --port 8083
```

## Test and lint

```bash
poetry run pytest
poetry run ruff check .
```
