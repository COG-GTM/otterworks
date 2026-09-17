"""Tests for the MeiliSearch client wrapper and analytics store."""

from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch

import meilisearch
import pytest

from app.config import MeiliSearchConfig
from app.services import meilisearch_client as ms
from app.services.meilisearch_client import MeiliSearchService


def _api_error(message: str = "not found", status_code: int = 404):
    """Build a MeilisearchApiError without touching the network."""
    response = MagicMock()
    response.status_code = status_code
    response.text = ""
    return meilisearch.errors.MeilisearchApiError(message, response)


@pytest.fixture()
def fresh_analytics(monkeypatch):
    """Isolate the module-level analytics store from other tests."""
    monkeypatch.setattr(
        ms,
        "_search_analytics",
        {"queries": [], "total_searches": 0, "total_results": 0},
    )
    monkeypatch.setattr(ms, "_analytics_lock", threading.Lock())


@pytest.fixture()
def service(mock_meilisearch_client: MagicMock) -> MeiliSearchService:
    """Service backed by the shared mock meilisearch client."""
    with patch("app.services.meilisearch_client.meilisearch.Client") as mock_cls:
        mock_cls.return_value = mock_meilisearch_client
        return MeiliSearchService(
            MeiliSearchConfig(
                url="http://localhost:7700",
                api_key="",
                documents_index="test-documents",
                files_index="test-files",
            )
        )


class TestAnalytics:
    """Tests for the in-memory search analytics store."""

    def test_aggregates_popular_and_zero_result_queries(self, fresh_analytics):
        """Queries are counted, and empty ones tracked separately."""
        ms.record_search_analytics("budget", 3)
        ms.record_search_analytics("budget", 2)
        ms.record_search_analytics("nothing", 0)

        analytics = ms.get_search_analytics()

        assert analytics.total_searches == 3
        assert analytics.popular_queries[0] == {"query": "budget", "count": 2}
        assert analytics.zero_result_queries == [{"query": "nothing", "count": 1}]
        assert analytics.avg_results_per_query == round(5 / 3, 2)

    def test_average_is_zero_without_any_searches(self, fresh_analytics):
        """An untouched service reports a zero average rather than dividing by zero."""
        analytics = ms.get_search_analytics()

        assert analytics.total_searches == 0
        assert analytics.avg_results_per_query == 0.0
        assert analytics.popular_queries == []

    def test_query_history_is_trimmed_to_the_maximum(self, fresh_analytics, monkeypatch):
        """The history ring keeps only the most recent entries."""
        monkeypatch.setattr(ms, "MAX_ANALYTICS_ENTRIES", 2)

        for i in range(4):
            ms.record_search_analytics(f"q-{i}", 1)

        assert [e["query"] for e in ms._search_analytics["queries"]] == ["q-2", "q-3"]
        assert ms.get_search_analytics().total_searches == 4


class TestEnsureIndices:
    """Tests for index bootstrapping."""

    def test_existing_indices_are_not_recreated(self, service, mock_meilisearch_client):
        """An index that already exists is only reconfigured."""
        service.ensure_indices()

        mock_meilisearch_client.create_index.assert_not_called()
        assert mock_meilisearch_client.index.return_value.update_searchable_attributes.called

    def test_missing_indices_are_created_with_an_id_primary_key(
        self, service, mock_meilisearch_client
    ):
        """A 404 from get_index triggers creation and a task wait."""
        mock_meilisearch_client.get_index.side_effect = _api_error("index_not_found")

        service.ensure_indices()

        assert mock_meilisearch_client.create_index.call_args_list[0].args == (
            "test-documents",
            {"primaryKey": "id"},
        )
        assert mock_meilisearch_client.create_index.call_count == 2
        mock_meilisearch_client.wait_for_task.assert_called_with(1, timeout_in_ms=30000)


class TestPing:
    """Tests for the readiness probe."""

    def test_ping_is_true_when_meilisearch_answers(self, service):
        """A successful health call means the backend is reachable."""
        assert service.ping() is True

    def test_ping_is_false_when_meilisearch_is_down(self, service, mock_meilisearch_client):
        """A failing health call is reported as unhealthy, not raised."""
        mock_meilisearch_client.health.side_effect = ConnectionError("refused")

        assert service.ping() is False


class TestSearch:
    """Tests for search filtering, pagination and error mapping."""

    def test_owner_and_type_filters_are_escaped_and_combined(
        self, service, mock_meilisearch_client
    ):
        """Filters are ANDed together with quotes escaped."""
        index = mock_meilisearch_client.index.return_value

        service.search(query="q", doc_type="document", owner_id='u"1')

        params = index.search.call_args.args[1]
        assert params["filter"] == 'type = "document" AND owner_id = "u\\"1"'

    def test_single_index_search_uses_offset_pagination(self, service, mock_meilisearch_client):
        """A type-scoped search pages inside MeiliSearch."""
        index = mock_meilisearch_client.index.return_value

        service.search(query="q", doc_type="file", page=3, page_size=10)

        params = index.search.call_args.args[1]
        assert params["offset"] == 20
        assert params["limit"] == 10

    def test_multi_index_search_overfetches_and_slices_locally(
        self, service, mock_meilisearch_client
    ):
        """Searching both indices fetches page*size and slices the merged hits."""
        index = mock_meilisearch_client.index.return_value
        index.search.return_value = {
            "estimatedTotalHits": 2,
            "hits": [{"id": "a"}, {"id": "b"}],
        }

        response = service.search(query="q", page=2, page_size=1)

        params = index.search.call_args.args[1]
        assert (params["offset"], params["limit"]) == (0, 2)
        assert response.total == 4
        assert [hit.id for hit in response.results] == ["b"]

    def test_filter_errors_are_translated_to_value_errors(self, service, mock_meilisearch_client):
        """An API error on search becomes a ValueError the API layer maps to 400."""
        mock_meilisearch_client.index.return_value.search.side_effect = _api_error(
            "invalid_search_filter", status_code=400
        )

        with pytest.raises(ValueError, match="Invalid search filter"):
            service.search(query="q")

    def test_hits_are_parsed_into_search_hits(self, service, mock_meilisearch_client):
        """Documents keep title/content; files map name and file metadata."""
        docs_index = MagicMock()
        docs_index.search.return_value = {
            "estimatedTotalHits": 1,
            "hits": [{
                "id": "d-1",
                "title": "Budget",
                "owner_id": "u-1",
                "tags": ["finance"],
                "_formatted": {"title": "Budget", "content": "a <em>budget</em> doc"},
            }],
        }
        files_index = MagicMock()
        files_index.search.return_value = {
            "estimatedTotalHits": 1,
            "hits": [{
                "id": "f-1",
                "name": "budget.xlsx",
                "mime_type": "application/vnd.ms-excel",
                "folder_id": "fold-1",
                "size": 10,
                "_formatted": {"name": "budget.xlsx"},
            }],
        }
        mock_meilisearch_client.index.side_effect = lambda name: (
            docs_index if name == "test-documents" else files_index
        )

        response = service.search(query="budget")

        document, file_hit = response.results
        assert (document.title, document.type) == ("Budget", "document")
        assert document.content_snippet == "a <em>budget</em> doc"
        assert document.highlights == {"content": ["a <em>budget</em> doc"]}
        assert (file_hit.title, file_hit.type, file_hit.size) == ("budget.xlsx", "file", 10)
        assert file_hit.highlights == {}


class TestAdvancedSearch:
    """Tests for the advanced filter builder."""

    def test_all_filters_are_combined(self, service, mock_meilisearch_client):
        """Tags are ORed inside a group and dates become range filters."""
        index = mock_meilisearch_client.index.return_value

        service.advanced_search(
            query=None,
            doc_type="document",
            owner_id="u-1",
            tags=["finance", "q3"],
            date_from="2026-01-01",
            date_to="2026-12-31",
        )

        params = index.search.call_args.args[1]
        assert params["filter"] == (
            'type = "document" AND owner_id = "u-1" '
            'AND (tags = "finance" OR tags = "q3") '
            'AND created_at >= "2026-01-01" AND created_at <= "2026-12-31"'
        )

    def test_missing_query_is_recorded_as_a_wildcard(self, service, mock_meilisearch_client):
        """A filter-only search reports itself as '*'."""
        index = mock_meilisearch_client.index.return_value
        index.search.return_value = {"estimatedTotalHits": 1, "hits": [{"id": "d-1"}]}

        response = service.advanced_search(query=None, doc_type="document")

        assert index.search.call_args.args[0] == ""
        assert response.query == "*"
        assert [hit.id for hit in response.results] == ["d-1"]


class TestSuggest:
    """Tests for autocomplete."""

    def test_deduplicates_titles_across_indices(self, service, mock_meilisearch_client):
        """The same text from both indices is only suggested once."""
        docs_index = MagicMock()
        docs_index.search.return_value = {"hits": [{"title": "Budget"}, {"title": ""}]}
        files_index = MagicMock()
        files_index.search.return_value = {
            "hits": [{"name": "Budget"}, {"name": "budget.xlsx"}]
        }
        mock_meilisearch_client.index.side_effect = lambda name: (
            docs_index if name == "test-documents" else files_index
        )

        assert service.suggest("bud") == ["Budget", "budget.xlsx"]

    def test_stops_once_the_size_limit_is_reached(self, service, mock_meilisearch_client):
        """The files index is never queried once enough suggestions exist."""
        docs_index = MagicMock()
        docs_index.search.return_value = {"hits": [{"title": "a"}, {"title": "b"}]}
        files_index = MagicMock()
        mock_meilisearch_client.index.side_effect = lambda name: (
            docs_index if name == "test-documents" else files_index
        )

        assert service.suggest("a", size=2) == ["a", "b"]
        files_index.search.assert_not_called()


class TestWaitAndCheck:
    """Tests for MeiliSearch task result handling."""

    def test_dict_task_results_are_supported(self, service, mock_meilisearch_client):
        """Older client versions return a dict, which is handled the same way."""
        mock_meilisearch_client.wait_for_task.return_value = {"status": "succeeded"}

        service._wait_and_check(7)

        mock_meilisearch_client.wait_for_task.assert_called_once_with(7, timeout_in_ms=10000)

    def test_failed_task_raises_with_the_meilisearch_error(
        self, service, mock_meilisearch_client
    ):
        """A failed task surfaces as a RuntimeError carrying the backend error."""
        mock_meilisearch_client.wait_for_task.return_value = {
            "status": "failed",
            "error": {"code": "index_primary_key_no_candidate_found"},
        }

        with pytest.raises(RuntimeError, match="index_primary_key_no_candidate_found"):
            service._wait_and_check(7)


class TestIndexWrites:
    """Tests for document/file writes and deletes."""

    def test_document_is_tagged_with_its_type(self, service, mock_meilisearch_client):
        """Indexed documents carry type=document for filtering."""
        index = mock_meilisearch_client.index.return_value

        service.index_document({"id": "d-1", "title": "Budget"})

        assert index.add_documents.call_args.args[0] == [
            {"id": "d-1", "title": "Budget", "type": "document"}
        ]

    def test_file_is_tagged_with_its_type(self, service, mock_meilisearch_client):
        """Indexed files carry type=file for filtering."""
        index = mock_meilisearch_client.index.return_value

        service.index_file({"id": "f-1", "name": "a.txt"})

        assert index.add_documents.call_args.args[0] == [
            {"id": "f-1", "name": "a.txt", "type": "file"}
        ]

    def test_lmdb_key_exists_is_retried_after_an_explicit_delete(
        self, service, mock_meilisearch_client
    ):
        """The known MDB_KEYEXIST bug is worked around by delete-then-re-add."""
        index = mock_meilisearch_client.index.return_value
        failed = {"status": "failed", "error": "MDB_KEYEXIST: key/data pair already exists"}
        succeeded = {"status": "succeeded"}
        mock_meilisearch_client.wait_for_task.side_effect = [failed, succeeded, succeeded]

        service.index_file({"id": "f-1", "name": "a.txt"})

        index.delete_document.assert_called_once_with("f-1")
        assert index.add_documents.call_count == 2

    def test_other_index_failures_are_raised(self, service, mock_meilisearch_client):
        """A failure unrelated to MDB_KEYEXIST is not retried."""
        index = mock_meilisearch_client.index.return_value
        mock_meilisearch_client.wait_for_task.return_value = {
            "status": "failed",
            "error": "disk full",
        }

        with pytest.raises(RuntimeError, match="disk full"):
            service.index_file({"id": "f-1", "name": "a.txt"})

        index.delete_document.assert_not_called()

    def test_delete_removes_an_existing_document(self, service, mock_meilisearch_client):
        """A known id is deleted from the documents index."""
        index = mock_meilisearch_client.index.return_value
        index.get_document.return_value = {"id": "d-1"}

        assert service.delete_document("document", "d-1") is True
        index.delete_document.assert_called_once_with("d-1")

    def test_delete_reports_missing_documents(self, service, mock_meilisearch_client):
        """An unknown id returns False instead of raising."""
        index = mock_meilisearch_client.index.return_value
        index.get_document.side_effect = _api_error("document_not_found")

        assert service.delete_document("file", "f-404") is False
        index.delete_document.assert_not_called()


class TestReindex:
    """Tests for index recreation and bulk loading."""

    def test_recreates_empty_indices_when_no_data_is_supplied(
        self, service, mock_meilisearch_client
    ):
        """Both indices are dropped, recreated and left empty."""
        result = service.reindex()

        assert mock_meilisearch_client.delete_index.call_count == 2
        assert result == {
            "status": "reindexed",
            "indices": ["test-documents", "test-files"],
            "indexed_counts": {"documents": 0, "files": 0},
        }

    def test_missing_indices_do_not_break_the_drop(self, service, mock_meilisearch_client):
        """Deleting an index that does not exist is ignored."""
        mock_meilisearch_client.delete_index.side_effect = _api_error("index_not_found")

        result = service.reindex()

        assert result["status"] == "reindexed"

    def test_bulk_loads_documents_and_files_in_batches_of_500(
        self, service, mock_meilisearch_client
    ):
        """Large payloads are chunked so MeiliSearch is not sent one huge request."""
        index = mock_meilisearch_client.index.return_value
        documents = [{"id": f"d-{i}"} for i in range(501)]
        files = [{"id": "f-1"}]

        result = service.reindex(documents=documents, files=files)

        batch_sizes = [
            len(call.args[0])
            for call in index.add_documents.call_args_list
            if isinstance(call.args[0], list)
        ]
        assert batch_sizes == [500, 1, 1]
        assert result["indexed_counts"] == {"documents": 501, "files": 1}


class TestResolveIndices:
    """Tests for index selection."""

    @pytest.mark.parametrize(
        ("doc_type", "expected"),
        [
            ("document", ["test-documents"]),
            ("file", ["test-files"]),
            (None, ["test-documents", "test-files"]),
            ("unknown", ["test-documents", "test-files"]),
        ],
    )
    def test_index_selection(self, service, doc_type, expected):
        """A type filter narrows the search to a single index."""
        assert service._resolve_indices(doc_type) == expected
