"""Indexing API endpoints for documents and files."""

from __future__ import annotations

import structlog
from flask import Blueprint, current_app, jsonify, request

from app.api.health import INDEX_COUNT
from app.middleware.auth import current_user_id
from app.services.indexer import Indexer
from app.services.meilisearch_client import MeiliSearchService

logger = structlog.get_logger()

index_bp = Blueprint("index", __name__)


def _scope_to_caller(doc_type: str, data: dict) -> tuple | None:
    """Pin the entry's owner to the authenticated user.

    Service callers (no user identity) may index on behalf of any owner.
    Returns an error response when a user tries to index for someone else
    or to overwrite an entry another user already owns.
    """
    user_id = current_user_id()
    if user_id is None:
        return None
    owner_id = str(data.get("owner_id") or "").strip()
    if owner_id and owner_id != user_id:
        logger.warning("index_owner_mismatch", entry_id=data.get("id"), user_id=user_id)
        return jsonify({"error": "owner_id must match the authenticated user"}), 403
    entry_id = data.get("id")
    if entry_id:
        search_service: MeiliSearchService = current_app.config["SEARCH_SERVICE"]
        existing_owner = search_service.get_owner(doc_type, str(entry_id))
        if existing_owner is not None and existing_owner != user_id:
            logger.warning("index_overwrite_denied", entry_id=entry_id, user_id=user_id)
            return jsonify({"error": "owner_id must match the authenticated user"}), 403
    data["owner_id"] = user_id
    return None


def _get_indexer() -> Indexer:
    """Get an Indexer instance from the current app config."""
    search_service: MeiliSearchService = current_app.config["SEARCH_SERVICE"]
    return Indexer(search_service)


@index_bp.route("/index/document", methods=["POST"])
def index_document() -> tuple:
    """Index a document (called by document-service or SQS)."""
    data = request.get_json()
    if not data:
        return jsonify({"error": "Request body is required"}), 400
    if not isinstance(data, dict):
        return jsonify({"error": "Request body must be a JSON object"}), 400
    denied = _scope_to_caller("document", data)
    if denied:
        return denied

    try:
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
    data = request.get_json()
    if not data:
        return jsonify({"error": "Request body is required"}), 400
    if not isinstance(data, dict):
        return jsonify({"error": "Request body must be a JSON object"}), 400
    denied = _scope_to_caller("file", data)
    if denied:
        return denied

    try:
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
    """Remove a document or file from the search index.

    Users can only remove their own entries; anyone else's reads as 404.
    """
    try:
        indexer = _get_indexer()
        result = indexer.remove(doc_type, doc_id, owner_id=current_user_id())
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
    """Reindex all data (service-token callers only; see app.middleware.auth)."""
    try:
        indexer = _get_indexer()
        result = indexer.reindex()
        logger.info("api_reindex_triggered")
        return jsonify(result), 200
    except Exception:
        logger.exception("api_reindex_failed")
        return jsonify({"error": "Failed to reindex"}), 500
