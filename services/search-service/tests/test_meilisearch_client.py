"""Tests for MeiliSearchService and the in-memory analytics store."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import meilisearch
import pytest
from requests import Response

from app.config import MeiliSearchConfig
from app.services import meilisearch_client as ms_module
from app.services.meilisearch_client import (
    MeiliSearchService,
    get_search_analytics,
    record_search_analytics,
)


def _api_error(message: str = "index not found") -> meilisearch.errors.MeilisearchApiError:
    """Build a MeilisearchApiError the way the client library raises one."""
    response = Response()
    response.status_code = 404
    response._content = b""
    return meilisearch.errors.MeilisearchApiError(message, response)


def _hit(**overrides):
    hit = {
        "id": "doc-1",
        "title": "Quarterly Plan",
        "type": "document",
        "owner_id": "user-1",
        "tags": ["plan"],
    }
    hit.update(overrides)
    return hit


@pytest.fixture()
def mock_client() -> MagicMock:
    """A mock meilisearch.Client whose tasks always succeed."""
    client = MagicMock()
    task = MagicMock()
    task.task_uid = 7
    result = MagicMock()
    result.status = "succeeded"
    client.wait_for_task.return_value = result

    index = MagicMock()
    index.add_documents.return_value = task
    index.delete_document.return_value = task
    index.search.return_value = {"hits": [], "estimatedTotalHits": 0}
    client.index.return_value = index
    client.create_index.return_value = task
    client.delete_index.return_value = task
    return client


@pytest.fixture()
def service(mock_client: MagicMock) -> MeiliSearchService:
    """A MeiliSearchService bound to the mock client."""
    with patch("app.services.meilisearch_client.meilisearch.Client", return_value=mock_client):
        return MeiliSearchService(
            MeiliSearchConfig(documents_index="docs", files_index="files")
        )


@pytest.fixture(autouse=True)
def reset_analytics():
    """Keep the module-level analytics store isolated per test."""
    original = {
        "queries": list(ms_module._search_analytics["queries"]),
        "total_searches": ms_module._search_analytics["total_searches"],
        "total_results": ms_module._search_analytics["total_results"],
    }
    ms_module._search_analytics["queries"] = []
    ms_module._search_analytics["total_searches"] = 0
    ms_module._search_analytics["total_results"] = 0
    yield
    ms_module._search_analytics.update(original)


class TestAnalytics:
    """Tests for record_search_analytics / get_search_analytics."""

    def test_analytics_rank_popular_and_zero_result_queries(self):
        """Queries are counted, and zero-hit queries tracked separately."""
        record_search_analytics("budget", 3)
        record_search_analytics("budget", 5)
        record_search_analytics("nothing", 0)

        analytics = get_search_analytics()

        assert analytics.popular_queries[0] == {"query": "budget", "count": 2}
        assert analytics.zero_result_queries == [{"query": "nothing", "count": 1}]
        assert analytics.total_searches == 3
        assert analytics.avg_results_per_query == pytest.approx(8 / 3, abs=0.01)

    def test_analytics_with_no_searches_reports_zero_average(self):
        """An empty store yields zeroed analytics rather than dividing by zero."""
        analytics = get_search_analytics()
        assert analytics.total_searches == 0
        assert analytics.avg_results_per_query == 0.0
        assert analytics.popular_queries == []

    def test_analytics_store_is_trimmed_to_the_entry_cap(self, monkeypatch):
        """The query log is bounded so the store cannot grow without limit."""
        monkeypatch.setattr(ms_module, "MAX_ANALYTICS_ENTRIES", 3)

        for i in range(5):
            record_search_analytics(f"q{i}", 1)

        assert [e["query"] for e in ms_module._search_analytics["queries"]] == [
            "q2",
            "q3",
            "q4",
        ]


class TestEnsureIndices:
    """Tests for index bootstrap."""

    def test_existing_indices_are_not_recreated(self, service, mock_client):
        """When get_index succeeds no index is created."""
        service.ensure_indices()
        mock_client.create_index.assert_not_called()
        mock_client.index.return_value.update_searchable_attributes.assert_any_call(
            ["title", "content", "tags"]
        )

    def test_missing_indices_are_created_with_the_id_primary_key(self, service, mock_client):
        """A 404 from get_index triggers creation of both indices."""
        mock_client.get_index.side_effect = _api_error()

        service.ensure_indices()

        assert [c.args[0] for c in mock_client.create_index.call_args_list] == [
            "docs",
            "files",
        ]
        assert mock_client.create_index.call_args.args[1] == {"primaryKey": "id"}


class TestPing:
    """Tests for the readiness probe helper."""

    def test_ping_is_true_when_meilisearch_answers(self, service, mock_client):
        """A successful health call means the backend is reachable."""
        mock_client.health.return_value = {"status": "available"}
        assert service.ping() is True

    def test_ping_is_false_when_meilisearch_is_down(self, service, mock_client):
        """Any error from health is swallowed and reported as not ready."""
        mock_client.health.side_effect = RuntimeError("connection refused")
        assert service.ping() is False


class TestSearch:
    """Tests for search / advanced_search."""

    def test_search_filters_by_type_and_owner_and_parses_hits(self, service, mock_client):
        """Type and owner scoping become a MeiliSearch filter expression."""
        mock_client.index.return_value.search.return_value = {
            "estimatedTotalHits": 1,
            "hits": [
                _hit(
                    _formatted={"title": "Quarterly <em>Plan</em>", "content": "body"},
                    created_at="2026-01-01",
                )
            ],
        }

        response = service.search("plan", doc_type="document", owner_id="user-1")

        params = mock_client.index.return_value.search.call_args.args[1]
        assert params["filter"] == 'type = "document" AND owner_id = "user-1"'
        assert params["offset"] == 0
        assert response.total == 1
        assert response.results[0].highlights == {"title": ["Quarterly <em>Plan</em>"]}

    def test_search_escapes_quotes_in_filter_values(self, service, mock_client):
        """Filter values are escaped so a quote cannot break the expression."""
        service.search("x", doc_type='doc"ument')
        params = mock_client.index.return_value.search.call_args.args[1]
        assert params["filter"] == 'type = "doc\\"ument"'

    def test_search_without_type_queries_both_indices(self, service, mock_client):
        """An untyped search fans out over documents and files."""
        mock_client.index.return_value.search.return_value = {
            "estimatedTotalHits": 2,
            "hits": [_hit()],
        }

        response = service.search("plan", page=1, page_size=20)

        assert [c.args[0] for c in mock_client.index.call_args_list] == ["docs", "files"]
        assert response.total == 4  # 2 per index

    def test_search_paginates_a_single_index_with_an_offset(self, service, mock_client):
        """Single-index searches push pagination down to MeiliSearch."""
        service.search("plan", doc_type="file", page=3, page_size=10)
        params = mock_client.index.return_value.search.call_args.args[1]
        assert params["offset"] == 20
        assert params["limit"] == 10

    def test_search_translates_filter_errors_into_value_errors(self, service, mock_client):
        """An API error on search surfaces as a 400-able ValueError."""
        mock_client.index.return_value.search.side_effect = _api_error("bad filter")

        with pytest.raises(ValueError, match="Invalid search filter"):
            service.search("plan", doc_type="document")

    def test_file_hits_use_the_name_field_as_the_title(self, service, mock_client):
        """Hits from the files index are rendered with their file name."""
        mock_client.index.return_value.search.return_value = {
            "estimatedTotalHits": 1,
            "hits": [{"id": "f-1", "name": "budget.xlsx", "mime_type": "text/csv"}],
        }

        response = service.search("budget", doc_type="file")

        assert response.results[0].title == "budget.xlsx"
        assert response.results[0].type == "file"
        assert response.results[0].content_snippet == ""

    def test_advanced_search_builds_every_filter_clause(self, service, mock_client):
        """Tags and date bounds are combined into one filter expression."""
        response = service.advanced_search(
            query=None,
            doc_type="document",
            owner_id="user-1",
            tags=["a", "b"],
            date_from="2026-01-01",
            date_to="2026-02-01",
        )

        params = mock_client.index.return_value.search.call_args.args[1]
        assert params["filter"] == (
            'type = "document" AND owner_id = "user-1" AND (tags = "a" OR tags = "b") '
            'AND created_at >= "2026-01-01" AND created_at <= "2026-02-01"'
        )
        assert response.query == "*"

    def test_advanced_search_returns_parsed_hits(self, service, mock_client):
        """Hits from an advanced search are converted to SearchHit models."""
        mock_client.index.return_value.search.return_value = {
            "estimatedTotalHits": 1,
            "hits": [_hit()],
        }

        response = service.advanced_search(query="plan", doc_type="document")

        assert [h.id for h in response.results] == ["doc-1"]
        assert response.query == "plan"


class TestSuggest:
    """Tests for prefix autocomplete."""

    def test_suggest_deduplicates_titles_across_indices(self, service, mock_client):
        """The same text from both indices is only suggested once."""
        docs_index = MagicMock()
        docs_index.search.return_value = {"hits": [{"title": "Plan"}, {"title": ""}]}
        files_index = MagicMock()
        files_index.search.return_value = {"hits": [{"name": "Plan"}, {"name": "Plan B"}]}
        mock_client.index.side_effect = lambda name: (
            docs_index if name == "docs" else files_index
        )

        assert service.suggest("pl") == ["Plan", "Plan B"]

    def test_suggest_stops_once_the_size_limit_is_reached(self, service, mock_client):
        """Collection stops at *size* results without querying further."""
        docs_index = MagicMock()
        docs_index.search.return_value = {
            "hits": [{"title": "a"}, {"title": "b"}, {"title": "c"}]
        }
        files_index = MagicMock()
        mock_client.index.side_effect = lambda name: (
            docs_index if name == "docs" else files_index
        )

        assert service.suggest("a", size=2) == ["a", "b"]
        files_index.search.assert_not_called()


class TestWriteOperations:
    """Tests for index/delete/reindex."""

    def test_index_document_tags_the_payload_as_a_document(self, service, mock_client):
        """Documents are stored with an explicit type discriminator."""
        service.index_document({"id": "d-1", "title": "T"})
        added = mock_client.index.return_value.add_documents.call_args.args[0]
        assert added == [{"id": "d-1", "title": "T", "type": "document"}]

    def test_failed_task_raises_a_runtime_error(self, service, mock_client):
        """A non-succeeded MeiliSearch task is reported as a failure."""
        failed = MagicMock()
        failed.status = "failed"
        failed.error = "disk full"
        mock_client.wait_for_task.return_value = failed

        with pytest.raises(RuntimeError, match="failed: disk full"):
            service.index_document({"id": "d-1"})

    def test_dict_task_results_are_understood(self, service, mock_client):
        """wait_for_task results returned as dicts are handled too."""
        mock_client.wait_for_task.return_value = {"status": "failed", "error": "boom"}

        with pytest.raises(RuntimeError, match="boom"):
            service.index_document({"id": "d-1"})

    def test_index_file_retries_once_after_an_lmdb_key_conflict(self, service, mock_client):
        """The known MDB_KEYEXIST bug triggers a delete-then-re-add retry."""
        index = mock_client.index.return_value
        failed = MagicMock()
        failed.status = "failed"
        failed.error = "MDB_KEYEXIST: key/data pair already exists"
        succeeded = MagicMock()
        succeeded.status = "succeeded"
        mock_client.wait_for_task.side_effect = [failed, succeeded, succeeded]

        service.index_file({"id": "f-1", "name": "a.txt"})

        index.delete_document.assert_called_once_with("f-1")
        assert index.add_documents.call_count == 2

    def test_index_file_propagates_other_task_failures(self, service, mock_client):
        """A failure unrelated to LMDB is not retried."""
        failed = MagicMock()
        failed.status = "failed"
        failed.error = "invalid document"
        mock_client.wait_for_task.return_value = failed

        with pytest.raises(RuntimeError, match="invalid document"):
            service.index_file({"id": "f-1", "name": "a.txt"})

        mock_client.index.return_value.delete_document.assert_not_called()

    def test_delete_document_returns_true_when_the_document_exists(self, service, mock_client):
        """An existing document is deleted and reported as removed."""
        index = mock_client.index.return_value
        index.get_document.return_value = {"id": "d-1"}

        assert service.delete_document("document", "d-1") is True
        index.delete_document.assert_called_once_with("d-1")

    def test_delete_document_returns_false_when_missing(self, service, mock_client):
        """A 404 from get_document means there is nothing to delete."""
        index = mock_client.index.return_value
        index.get_document.side_effect = _api_error()

        assert service.delete_document("file", "f-404") is False
        index.delete_document.assert_not_called()

    def test_reindex_recreates_empty_indices(self, service, mock_client):
        """Reindexing with no data drops and recreates both indices."""
        result = service.reindex()

        assert [c.args[0] for c in mock_client.delete_index.call_args_list] == [
            "docs",
            "files",
        ]
        assert result == {
            "status": "reindexed",
            "indices": ["docs", "files"],
            "indexed_counts": {"documents": 0, "files": 0},
        }

    def test_reindex_tolerates_indices_that_do_not_exist_yet(self, service, mock_client):
        """Deleting an absent index is not an error during reindex."""
        mock_client.delete_index.side_effect = _api_error()

        result = service.reindex()

        assert result["status"] == "reindexed"

    def test_reindex_bulk_indexes_documents_and_files_in_batches(self, service, mock_client):
        """Payloads larger than the batch size are split into several adds."""
        documents = [{"id": f"d-{i}"} for i in range(501)]
        files = [{"id": "f-1"}]

        result = service.reindex(documents=documents, files=files)

        assert result["indexed_counts"] == {"documents": 501, "files": 1}
        # 2 batches for documents + 1 for files
        assert mock_client.index.return_value.add_documents.call_count == 3
