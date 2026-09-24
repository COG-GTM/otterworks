"""Folder tree resolution against the file-service.

A ``folder`` search filter includes everything nested under the folder,
so the id has to be expanded into the ids of all its descendants.
"""

from __future__ import annotations

import os
import time

import requests
import structlog

logger = structlog.get_logger()

FILE_SERVICE_URL = os.getenv("FILE_SERVICE_URL", "http://file-service:8082")
FETCH_TIMEOUT = 5
CACHE_TTL_SECONDS = 60
MAX_FOLDERS = 500

_cache: dict[str, tuple[float, list[str]]] = {}


def resolve_folder_ids(folder_id: str, session: requests.Session | None = None) -> list[str]:
    """Return *folder_id* plus the ids of every folder nested under it.

    Falls back to ``[folder_id]`` when the file-service is unreachable so
    a search still returns the folder's own files.
    """
    cached = _cache.get(folder_id)
    now = time.monotonic()
    if cached and now - cached[0] < CACHE_TTL_SECONDS:
        return list(cached[1])

    http = session or requests
    resolved: list[str] = [folder_id]
    seen = {folder_id}
    queue = [folder_id]

    while queue and len(resolved) < MAX_FOLDERS:
        parent = queue.pop(0)
        try:
            response = http.get(
                f"{FILE_SERVICE_URL}/api/v1/folders",
                params={"parent_id": parent},
                timeout=FETCH_TIMEOUT,
            )
        except requests.RequestException:
            logger.warning("folder_resolve_failed", folder_id=folder_id, parent_id=parent)
            return resolved
        if response.status_code != 200:
            logger.warning(
                "folder_resolve_unexpected_status",
                folder_id=folder_id,
                parent_id=parent,
                status=response.status_code,
            )
            return resolved
        for child in response.json().get("folders", []):
            child_id = str(child.get("id", ""))
            if child_id and child_id not in seen:
                seen.add(child_id)
                resolved.append(child_id)
                queue.append(child_id)

    _cache[folder_id] = (now, list(resolved))
    return resolved
