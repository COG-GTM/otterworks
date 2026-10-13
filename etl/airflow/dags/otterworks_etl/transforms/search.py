"""Pure helpers for the weekly MeiliSearch reindex."""

from __future__ import annotations

RANKING_RULES = ["words", "typo", "proximity", "attribute", "sort", "exactness"]

INDEX_SETTINGS = {
    "documents": {
        "searchableAttributes": ["title", "content", "tags"],
        "filterableAttributes": ["type", "owner_id", "tags", "created_at", "updated_at"],
        "sortableAttributes": ["updated_at", "created_at"],
        "rankingRules": RANKING_RULES,
    },
    "files": {
        "searchableAttributes": ["name", "tags", "mime_type"],
        "filterableAttributes": ["type", "owner_id", "mime_type", "folder_id", "tags",
                                 "created_at", "updated_at"],
        "sortableAttributes": ["updated_at", "created_at", "size"],
        "rankingRules": RANKING_RULES,
    },
}


def staging_index(live: str) -> str:
    return f"{live}_staging"


def map_document(doc: dict) -> dict:
    return {
        "id": doc.get("document_id", doc.get("id", "")),
        "title": doc.get("title", ""),
        "content": doc.get("content", ""),
        "owner_id": doc.get("owner_id", ""),
        "tags": doc.get("tags", []),
        "type": "document",
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
    }


def map_file(f: dict) -> dict:
    return {
        "id": f.get("file_id", f.get("id", "")),
        "name": f.get("file_name", f.get("name", "")),
        "owner_id": f.get("owner_id", ""),
        "mime_type": f.get("mime_type", ""),
        "folder_id": f.get("folder_id", ""),
        "size": f.get("size_bytes", f.get("size", 0)),
        "tags": f.get("tags", []),
        "type": "file",
        "created_at": f.get("created_at"),
        "updated_at": f.get("updated_at"),
    }


def page_items(payload: dict | list, *keys: str) -> list:
    if isinstance(payload, list):
        return payload
    for k in keys:
        if isinstance(payload.get(k), list):
            return payload[k]
    return []
