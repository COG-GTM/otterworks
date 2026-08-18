# Document Service

Python 3.12 / FastAPI service that owns document metadata, content snapshots,
version history, templates, and document comments. Persists to PostgreSQL via
async SQLAlchemy with Alembic migrations, and publishes domain events to SNS
via the shared `event_publisher`.

## Comments & comment resolution

Comments live on documents (`POST/GET/DELETE /api/v1/documents/{document_id}/comments[...]`).
Comment threads can additionally be **resolved** and **unresolved**, e.g. when
the feedback in a comment has been addressed.

### Data model

The `comments` table carries three resolution columns (added by an Alembic
migration):

| column        | type        | notes                                  |
|---------------|-------------|----------------------------------------|
| `is_resolved` | boolean     | not null, default `false`              |
| `resolved_by` | uuid        | nullable — user who resolved the thread |
| `resolved_at` | timestamptz | nullable — when it was resolved        |

`CommentResponse` includes the same three fields.

### Endpoints

Base path: `/api/v1/documents`

| Method | Path                                            | Description |
|--------|-------------------------------------------------|-------------|
| POST   | `/{document_id}/comments`                       | Add a comment |
| GET    | `/{document_id}/comments`                       | List comments. Supports `?include_resolved=true\|false` (default `true`); `false` filters out resolved comments |
| DELETE | `/{document_id}/comments/{comment_id}`          | Delete a comment |
| POST   | `/{document_id}/comments/{comment_id}/resolve`  | Mark the comment resolved; returns the updated `CommentResponse` |
| POST   | `/{document_id}/comments/{comment_id}/unresolve`| Clear the resolved state; returns the updated `CommentResponse` |

### Events

On resolve, the service publishes a `comment_resolved` domain event to SNS via
the existing `event_publisher` (`app/services/event_publisher.py`):

As with all events from this publisher, the message is an envelope of the
form `{"event_type": ..., "timestamp": ..., "payload": {...}}`:

```json
{
  "event_type": "comment_resolved",
  "timestamp": "<ISO-8601>",
  "payload": {
    "documentId": "<uuid>",
    "commentId": "<uuid>",
    "resolvedBy": "<uuid of resolving user>",
    "authorId": "<uuid of the comment's author>",
    "timestamp": "<ISO-8601>"
  }
}
```

The notification-service consumes this event and notifies the comment's author
(`authorId`) that their comment was resolved.

## Development

- Run migrations: `alembic upgrade head` (config in `alembic.ini`,
  migrations in `alembic/`)
- Dependencies: Poetry (`pyproject.toml`)
- Tests: `pytest` (`tests/`)
