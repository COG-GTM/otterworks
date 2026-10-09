"""Indexing API endpoints for documents and files.

Every endpoint here authorizes its caller even when ``REQUIRE_AUTH`` is off:

* A service-token caller (SQS indexer, admin jobs) may index or remove any
  entry and trigger a reindex.
* A gateway user (``X-User-ID``) may only index entries owned by themselves
  and only remove entries they own; ``owner_id`` is bound to the caller.
* Reindex rebuilds the whole tenant index and requires the service token.
"""

from __future__ import annotations

from typing import Any

import structlog
from flask import Blueprint, jsonify, request

from app.api.health import INDEX_COUNT
from app.middleware.auth import Caller, get_caller
from app.services.indexer import Indexer, ReindexSourceError
from app.services.meilisearch_client import MeiliSearchService

logger = structlog.get_logger()

index_bp = Blueprint("index", __name__)

DOC_TYPES = ("document", "file")


def _get_search_service() -> MeiliSearchService:
    from flask import current_app

    return current_app.config["SEARCH_SERVICE"]


def _get_indexer() -> Indexer:
    """Get an Indexer instance from the current app config."""
    return Indexer(_get_search_service())


def _unauthorized() -> tuple:
    logger.warning("index_auth_rejected", path=request.path)
    return jsonify({"error": "unauthorized"}), 401


def _forbidden(message: str) -> tuple:
    logger.warning("index_access_denied", path=request.path, reason=message)
    return jsonify({"error": message}), 403


def _owned_by(entry: dict[str, Any] | None, user_id: str) -> bool:
    return entry is not None and str(entry.get("owner_id") or "") == user_id


def _bind_owner(
    data: dict[str, Any], doc_type: str, caller: Caller
) -> tuple[dict[str, Any] | None, tuple | None]:
    """Bind ``owner_id`` to a user caller and refuse to overwrite foreign entries."""
    if caller.is_service:
        return data, None

    owner_id = data.get("owner_id")
    if owner_id not in (None, "") and str(owner_id) != caller.user_id:
        return None, _forbidden("owner_id must match the authenticated user")

    doc_id = data.get("id")
    if doc_id:
        existing = _get_search_service().get_entry(doc_type, str(doc_id))
        if existing is not None and not _owned_by(existing, caller.user_id):
            return None, _forbidden(f"{doc_type} is owned by another user")

    return {**data, "owner_id": caller.user_id}, None


@index_bp.route("/index/document", methods=["POST"])
def index_document() -> tuple:
    """Index a document (called by document-service or SQS)."""
    caller = get_caller()
    if caller is None:
        return _unauthorized()

    data = request.get_json()
    if not data:
        return jsonify({"error": "Request body is required"}), 400

    try:
        data, denied = _bind_owner(data, "document", caller)
        if denied:
            return denied
        indexer = _get_indexer()
        result = indexer.index_document(data)
        INDEX_COUNT.labels(operation="index", type="document").inc()
        logger.info("api_document_indexed", document_id=data.get("id"))
        return jsonify(result), 201
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception:
        logger.exception("api_index_document_failed")
        return jsonify({"error": "Failed to index document"}), 500


@index_bp.route("/index/file", methods=["POST"])
def index_file() -> tuple:
    """Index a file (called by file-service or SQS)."""
    caller = get_caller()
    if caller is None:
        return _unauthorized()

    data = request.get_json()
    if not data:
        return jsonify({"error": "Request body is required"}), 400

    try:
        data, denied = _bind_owner(data, "file", caller)
        if denied:
            return denied
        indexer = _get_indexer()
        result = indexer.index_file(data)
        INDEX_COUNT.labels(operation="index", type="file").inc()
        logger.info("api_file_indexed", file_id=data.get("id"))
        return jsonify(result), 201
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception:
        logger.exception("api_index_file_failed")
        return jsonify({"error": "Failed to index file"}), 500


@index_bp.route("/index/<doc_type>/<doc_id>", methods=["DELETE"])
def remove_from_index(doc_type: str, doc_id: str) -> tuple:
    """Remove a document or file from the search index."""
    caller = get_caller()
    if caller is None:
        return _unauthorized()

    try:
        if doc_type not in DOC_TYPES:
            raise ValueError(f"Invalid type '{doc_type}'. Must be 'document' or 'file'.")
        if not caller.is_service:
            entry = _get_search_service().get_entry(doc_type, doc_id)
            if not _owned_by(entry, caller.user_id):
                # Same response as a missing entry, so ids of other users' entries are not confirmed.
                return jsonify({"status": "not_found", "id": doc_id, "type": doc_type}), 404
        indexer = _get_indexer()
        result = indexer.remove(doc_type, doc_id)
        if result["status"] == "not_found":
            return jsonify(result), 404
        INDEX_COUNT.labels(operation="delete", type=doc_type).inc()
        logger.info("api_document_removed", doc_type=doc_type, doc_id=doc_id)
        return jsonify(result), 200
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception:
        logger.exception("api_remove_from_index_failed")
        return jsonify({"error": "Failed to remove from index"}), 500


@index_bp.route("/reindex", methods=["POST"])
def reindex() -> tuple:
    """Reindex all data (admin operation, service token only)."""
    caller = get_caller()
    if caller is None:
        return _unauthorized()
    if not caller.is_service:
        return _forbidden("reindex requires the service token")

    try:
        indexer = _get_indexer()
        result = indexer.reindex()
        logger.info("api_reindex_triggered")
        return jsonify(result), 200
    except ReindexSourceError:
        logger.exception("api_reindex_source_unavailable")
        return jsonify({"error": "Reindex aborted: a source service could not be crawled"}), 502
    except Exception:
        logger.exception("api_reindex_failed")
        return jsonify({"error": "Failed to reindex"}), 500
