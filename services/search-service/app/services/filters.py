"""Search filter parsing and MeiliSearch filter-expression building.

Translates the user-facing query parameters (``owner``, ``mime``,
``modified``, ``folder``, ``type``) into a MeiliSearch ``filter``
expression plus a description of what was applied, so the API can echo
the active filters back to the client.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

# Friendly MIME group -> concrete MIME types. MeiliSearch 1.6 has no
# prefix matching in filters, so every group is expanded to an explicit
# list of equality terms.
MIME_GROUPS: dict[str, tuple[str, ...]] = {
    "documents": (
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.oasis.opendocument.text",
        "application/vnd.ms-powerpoint",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/vnd.oasis.opendocument.presentation",
        "application/rtf",
        "text/plain",
        "text/markdown",
        "text/html",
    ),
    "spreadsheets": (
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.oasis.opendocument.spreadsheet",
        "text/csv",
    ),
    "pdf": ("application/pdf",),
    "images": (
        "image/png",
        "image/jpeg",
        "image/gif",
        "image/webp",
        "image/svg+xml",
        "image/bmp",
        "image/tiff",
        "image/heic",
    ),
    "video": (
        "video/mp4",
        "video/quicktime",
        "video/webm",
        "video/x-msvideo",
        "video/x-matroska",
        "video/mpeg",
    ),
    "archives": (
        "application/zip",
        "application/x-tar",
        "application/gzip",
        "application/x-7z-compressed",
        "application/vnd.rar",
    ),
}

# "today" and "year" are calendar-anchored (start of day / start of year in
# UTC); "7d" and "30d" are rolling windows, as their labels say.
ROLLING_PRESETS: dict[str, timedelta] = {
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}

MODIFIED_PRESETS: tuple[str, ...] = ("today", "7d", "30d", "year")

OWNER_ME = "me"
OWNER_SHARED = "shared"

# Descendant folders are resolved recursively; cap the expansion so one
# request can never build an unbounded filter expression.
MAX_FOLDER_IDS = 500

_DATE_RANGE_RE = re.compile(r"^(?P<from>.*?)\.\.(?P<to>.*)$")


class FilterError(ValueError):
    """Raised when a filter parameter cannot be parsed. Maps to HTTP 400."""


@dataclass
class AppliedFilters:
    """The filters resolved from a request, echoed back in the response."""

    type: str | None = None
    owner: str | None = None
    mime: list[str] = field(default_factory=list)
    mime_types: list[str] = field(default_factory=list)
    modified: str | None = None
    modified_from: str | None = None
    modified_to: str | None = None
    folder: str | None = None
    folder_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        applied: dict[str, Any] = {}
        if self.type:
            applied["type"] = self.type
        if self.owner:
            applied["owner"] = self.owner
        if self.mime:
            applied["mime"] = self.mime
            applied["mime_types"] = self.mime_types
        if self.modified:
            applied["modified"] = self.modified
            applied["modified_from"] = self.modified_from
            if self.modified_to:
                applied["modified_to"] = self.modified_to
        if self.folder:
            applied["folder"] = self.folder
            applied["folder_ids"] = self.folder_ids
        return applied


def parse_mime(mime: str | None) -> tuple[list[str], list[str]]:
    """Expand a comma-separated ``mime`` parameter.

    Accepts friendly group names (``spreadsheets``) and raw MIME types
    (``application/pdf``). Returns the requested tokens and the concrete
    MIME types they expand to.
    """
    if not mime:
        return [], []

    tokens = [token.strip() for token in mime.split(",") if token.strip()]
    if not tokens:
        return [], []

    mime_types: list[str] = []
    for token in tokens:
        key = token.lower()
        if key in MIME_GROUPS:
            values: tuple[str, ...] | tuple[str] = MIME_GROUPS[key]
        elif "/" in key:
            values = (key,)
        else:
            raise FilterError(
                f"Unknown mime filter '{token}'. Use a MIME type or one of: "
                + ", ".join(sorted(MIME_GROUPS))
            )
        for value in values:
            if value not in mime_types:
                mime_types.append(value)

    return tokens, mime_types


def parse_modified(modified: str | None, now: datetime | None = None) -> tuple[datetime | None, datetime | None]:
    """Resolve a ``modified`` parameter into an inclusive datetime range.

    Supports the presets ``today|7d|30d|year`` and explicit
    ``<from>..<to>`` ranges of ISO-8601 dates (either bound may be empty).
    """
    if not modified:
        return None, None

    value = modified.strip()
    if not value:
        return None, None

    reference = now or datetime.now(timezone.utc)
    key = value.lower()
    rolling = ROLLING_PRESETS.get(key)
    if rolling is not None:
        return reference - rolling, None
    if key == "today":
        return reference.replace(hour=0, minute=0, second=0, microsecond=0), None
    if key == "year":
        return reference.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0), None

    match = _DATE_RANGE_RE.match(value)
    if not match:
        raise FilterError(
            f"Invalid modified filter '{modified}'. Use one of "
            f"{'|'.join(MODIFIED_PRESETS)} or '<from>..<to>' ISO dates."
        )

    date_from = _parse_iso(match.group("from"), modified)
    date_to = _parse_iso(match.group("to"), modified, end_of_day=True)
    if date_from is None and date_to is None:
        raise FilterError(f"Invalid modified filter '{modified}': range has no bounds.")
    if date_from is not None and date_to is not None and date_from > date_to:
        raise FilterError(f"Invalid modified filter '{modified}': start is after end.")
    return date_from, date_to


def _parse_iso(raw: str, original: str, end_of_day: bool = False) -> datetime | None:
    """Parse one bound of a ``<from>..<to>`` range; empty means unbounded."""
    text = raw.strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise FilterError(f"Invalid date '{text}' in modified filter '{original}'.") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    if end_of_day and len(text) == 10:
        parsed = parsed + timedelta(days=1) - timedelta(microseconds=1)
    return parsed


def escape(value: str) -> str:
    """Escape a value for use inside a MeiliSearch filter expression."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _or_group(attribute: str, values: list[str]) -> str:
    terms = [f'{attribute} = "{escape(value)}"' for value in values]
    if len(terms) == 1:
        return terms[0]
    return "(" + " OR ".join(terms) + ")"


def build_filter_expression(
    doc_type: str | None = None,
    caller_id: str | None = None,
    owner: str | None = None,
    mime: str | None = None,
    modified: str | None = None,
    folder: str | None = None,
    folder_ids: list[str] | None = None,
    now: datetime | None = None,
) -> tuple[list[str], AppliedFilters]:
    """Build the MeiliSearch filter parts for a search request.

    Values within one filter are OR-ed, and the filters are AND-ed
    together by the caller. Returns the parts plus the applied filters.
    """
    parts: list[str] = []
    applied = AppliedFilters()

    if doc_type:
        parts.append(f'type = "{escape(doc_type)}"')
        applied.type = doc_type

    owner_value = (owner or "").strip()
    if owner_value:
        applied.owner = owner_value
        if owner_value == OWNER_SHARED:
            if caller_id:
                parts.append(f'owner_id != "{escape(caller_id)}"')
        elif owner_value == OWNER_ME:
            if not caller_id:
                raise FilterError("owner=me requires an authenticated user")
            parts.append(f'owner_id = "{escape(caller_id)}"')
        else:
            parts.append(_or_group("owner_id", [owner_value]))
    elif caller_id:
        parts.append(f'owner_id = "{escape(caller_id)}"')

    mime_tokens, mime_types = parse_mime(mime)
    if mime_types:
        parts.append(_or_group("mime_type", mime_types))
        applied.mime = mime_tokens
        applied.mime_types = mime_types

    date_from, date_to = parse_modified(modified, now=now)
    if date_from is not None or date_to is not None:
        applied.modified = modified.strip() if modified else None
        if date_from is not None:
            parts.append(f"updated_at_ts >= {int(date_from.timestamp())}")
            applied.modified_from = date_from.isoformat()
        if date_to is not None:
            parts.append(f"updated_at_ts <= {int(date_to.timestamp())}")
            applied.modified_to = date_to.isoformat()

    folder_value = (folder or "").strip()
    if folder_value:
        ids = folder_ids if folder_ids is not None else [folder_value]
        ids = ids[:MAX_FOLDER_IDS]
        parts.append(_or_group("folder_id", ids))
        applied.folder = folder_value
        applied.folder_ids = ids

    return parts, applied


def files_only(applied: AppliedFilters) -> bool:
    """Whether the applied filters can only ever match files.

    ``mime_type`` and ``folder_id`` exist on the files index alone, so
    filtering on either makes the documents index both pointless and an
    invalid filter target.
    """
    return bool(applied.mime_types or applied.folder)


def to_epoch(value: Any) -> int | None:
    """Convert an ISO-8601 timestamp to epoch seconds (None when unparseable)."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp())
