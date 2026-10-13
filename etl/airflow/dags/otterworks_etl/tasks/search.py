"""search_reindex_weekly: blue/green MeiliSearch reindex from document-service and file-service.

The legacy script deleted the live index and rebuilt it in place (search was empty for the
duration and stayed empty on failure). Here every run rebuilds ``<index>_staging``, validates
it, then atomically swaps it with the live index, so a failed or partial run never touches
what users query and a re-run just rebuilds staging again.
"""

from __future__ import annotations

import json
import logging
import time

from otterworks_etl import settings
from otterworks_etl.json_logging import log_event
from otterworks_etl.transforms import search as T

logger = logging.getLogger(__name__)

SOURCES = {
    "documents": {"conn": settings.DOCUMENT_SERVICE_CONN_ID, "endpoint": "/api/v1/documents",
                  "size_param": "size", "keys": ("documents", "items"), "mapper": T.map_document},
    "files": {"conn": settings.FILE_SERVICE_CONN_ID, "endpoint": "/api/v1/files",
              "size_param": "page_size", "keys": ("files", "items"), "mapper": T.map_file},
}


def _meili(method: str):
    from airflow.hooks.base import BaseHook
    from airflow.providers.http.hooks.http import HttpHook

    conn = BaseHook.get_connection(settings.MEILISEARCH_CONN_ID)
    headers = {"Content-Type": "application/json"}
    if conn.password:
        headers["Authorization"] = f"Bearer {conn.password}"
    return HttpHook(method=method, http_conn_id=settings.MEILISEARCH_CONN_ID), headers


def _call(method: str, endpoint: str, body=None, ok_404: bool = False) -> dict:
    hook, headers = _meili(method)
    resp = hook.run(endpoint, data=json.dumps(body) if body is not None else None,
                    headers=headers, extra_options={"check_response": not ok_404, "timeout": 60})
    if ok_404 and resp.status_code == 404:
        return {}
    if resp.status_code >= 400:
        raise RuntimeError(f"MeiliSearch {method} {endpoint} -> {resp.status_code}: {resp.text}")
    return resp.json() if resp.content else {}


def wait_task(task: dict, timeout_s: float = 300, poll_s: float = 0.5) -> dict:
    uid = task.get("taskUid")
    if uid is None:
        return task
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        status = _call("GET", f"/tasks/{uid}")
        if status.get("status") == "succeeded":
            return status
        if status.get("status") in ("failed", "canceled"):
            raise RuntimeError(f"MeiliSearch task {uid} {status.get('status')}: {status.get('error')}")
        time.sleep(poll_s)
    raise TimeoutError(f"MeiliSearch task {uid} did not finish within {timeout_s}s")


def _index_name(cfg: dict, kind: str) -> str:
    return cfg[f"search_{kind}_index"]


def prepare_staging_index(kind: str, cfg: dict) -> str:
    staging = T.staging_index(_index_name(cfg, kind))
    wait_task(_call("DELETE", f"/indexes/{staging}", ok_404=True))
    wait_task(_call("POST", "/indexes", {"uid": staging, "primaryKey": "id"}))
    wait_task(_call("PATCH", f"/indexes/{staging}/settings", T.INDEX_SETTINGS[kind]))
    log_event(logger, "staging_index_ready", index=staging)
    return staging


def _fetch_page(kind: str, page: int, size: int) -> list[dict]:
    from airflow.providers.http.hooks.http import HttpHook

    src = SOURCES[kind]
    resp = HttpHook(method="GET", http_conn_id=src["conn"]).run(
        src["endpoint"], data={"page": page, src["size_param"]: size},
        extra_options={"timeout": 30})
    return T.page_items(resp.json(), *src["keys"])


def index_source(kind: str, cfg: dict) -> int:
    """Extract (paged API) -> transform (map) -> load (bulk add to staging), page by page."""
    staging, size = T.staging_index(_index_name(cfg, kind)), int(cfg["search_api_page_size"])
    mapper, page, total = SOURCES[kind]["mapper"], 1, 0
    while True:
        items = _fetch_page(kind, page, size)
        if not items:
            break
        wait_task(_call("POST", f"/indexes/{staging}/documents", [mapper(i) for i in items]))
        total += len(items)
        if len(items) < size:
            break
        page += 1
    log_event(logger, "source_indexed", kind=kind, documents=total, index=staging)
    return total


def validate_staging(kind: str, cfg: dict, expected: int) -> int:
    staging = T.staging_index(_index_name(cfg, kind))
    actual = int(_call("GET", f"/indexes/{staging}/stats").get("numberOfDocuments", -1))
    if actual != expected:
        raise ValueError(f"{staging}: indexed {actual} documents, expected {expected}")
    log_event(logger, "staging_validated", index=staging, documents=actual)
    return actual


def swap_into_live(kind: str, cfg: dict) -> str:
    live = _index_name(cfg, kind)
    staging = T.staging_index(live)
    if not _call("GET", f"/indexes/{live}", ok_404=True):
        wait_task(_call("POST", "/indexes", {"uid": live, "primaryKey": "id"}))
    wait_task(_call("POST", "/swap-indexes", [{"indexes": [live, staging]}]))
    wait_task(_call("DELETE", f"/indexes/{staging}", ok_404=True))
    log_event(logger, "index_swapped", index=live)
    return live
