"""Indexing API endpoints for documents and files.

These endpoints write to or wipe the tenant-wide index, so they are internal:
every one requires the service token (see ``require_service_token``).
"""

from __future__ import annotations

import structlog
from flask import Blueprint, jsonify, request

from app.api.health import INDEX_COUNT
from app.middleware.auth import require_service_token
from app.services.indexer import Indexer, ReindexSourceError
from app.services.meilisearch_client import MeiliSearchService

logger = structlog.get_logger()

index_bp = Blueprint("index", __name__)


def _get_indexer() -> Indexer:
    """Get an Indexer instance from the current app config."""
    from flask import current_app

    search_service: MeiliSearchService = current_app.config["SEARCH_SERVICE"]
    return Indexer(search_service)


@index_bp.route("/index/document", methods=["POST"])
@require_service_token
def index_document() -> tuple:
    """Index a document (called by document-service or SQS)."""
    data = request.get_json()
    if not data:
        return jsonify({"error": "Request body is required"}), 400

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
@require_service_token
def index_file() -> tuple:
    """Index a file (called by file-service or SQS)."""
    data = request.get_json()
    if not data:
        return jsonify({"error": "Request body is required"}), 400

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
@require_service_token
def remove_from_index(doc_type: str, doc_id: str) -> tuple:
    """Remove a document or file from the search index."""
    try:
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
@require_service_token
def reindex() -> tuple:
    """Reindex all data (internal admin operation)."""
    try:
        indexer = _get_indexer()
        result = indexer.reindex()
        logger.info("api_reindex_triggered")
        return jsonify(result), 200
    except ReindexSourceError:
        logger.exception("api_reindex_source_unavailable")
        return jsonify({"error": "Reindex aborted: source service unavailable"}), 502
    except Exception:
        logger.exception("api_reindex_failed")
        return jsonify({"error": "Failed to reindex"}), 500
