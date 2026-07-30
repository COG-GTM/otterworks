"""Tests for MeiliSearchService and the in-memory search analytics store.

The meilisearch client is mocked at the boundary; nothing talks to a server.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import meilisearch
import pytest
from requests import Response

import app.services.meilisearch_client as ms
from app.config import MeiliSearchConfig
from app.services.meilisearch_client import (
    MeiliSearchService,
    get_search_analytics,
    record_search_analytics,
)

DOCS_INDEX = "test-docs"
FILES_INDEX = "test-files"


def _api_error(message: str = "index not found", status: int = 404):
    response = Response()
    response.status_code = status
    response._content = b""
    return meilisearch.errors.MeilisearchApiError(message, response)


def _succeeded_task(task_uid: int = 1) -> MagicMock:
    task = MagicMock()
    task.task_uid = task_uid
    return task


@pytest.fixture(autouse=True)
def reset_analytics():
    """Keep the module-level analytics store from leaking between tests."""
    original = {
        "queries": list(ms._search_analytics["queries"]),
        "total_searches": ms._search_analytics["total_searches"],
        "total_results": ms._search_analytics["total_results"],
    }
    ms._search_analytics["queries"] = []
    ms._search_analytics["total_searches"] = 0
    ms._search_analytics["total_results"] = 0
    yield
    ms._search_analytics.update(original)


@pytest.fixture()
def indices() -> dict[str, MagicMock]:
    """One mock index per configured index name."""
    built: dict[str, MagicMock] = {}
    for name in (DOCS_INDEX, FILES_INDEX):
        index = MagicMock(name=name)
        index.search.return_value = {"hits": [], "estimatedTotalHits": 0}
        index.add_documents.return_value = _succeeded_task()
        index.delete_document.return_value = _succeeded_task()
        index.get_document.return_value = {"id": "d-1"}
        built[name] = index
    return built


@pytest.fixture()
def client(indices: dict[str, MagicMock]) -> MagicMock:
    mock_client = MagicMock()
    mock_client.index.side_effect = lambda name: indices[name]
    mock_client.create_index.return_value = _succeeded_task()
    mock_client.delete_index.return_value = _succeeded_task()
    result = MagicMock()
    result.status = "succeeded"
    mock_client.wait_for_task.return_value = result
    return mock_client


@pytest.fixture()
def service(client: MagicMock) -> MeiliSearchService:
    with patch("app.services.meilisearch_client.meilisearch.Client", return_value=client):
        return MeiliSearchService(
            MeiliSearchConfig(documents_index=DOCS_INDEX, files_index=FILES_INDEX)
        )


class TestAnalyticsStore:
    """record_search_analytics / get_search_analytics."""

    def test_empty_store_reports_zeroes(self):
        analytics = get_search_analytics()

        assert analytics.total_searches == 0
        assert analytics.avg_results_per_query == 0.0
        assert analytics.popular_queries == []
        assert analytics.zero_result_queries == []

    def test_popular_and_zero_result_queries_are_ranked(self):
        record_search_analytics("report", 3)
        record_search_analytics("report", 3)
        record_search_analytics("missing", 0)

        analytics = get_search_analytics()

        assert analytics.total_searches == 3
        assert analytics.popular_queries[0] == {"query": "report", "count": 2}
        assert analytics.zero_result_queries == [{"query": "missing", "count": 1}]
        assert analytics.avg_results_per_query == 2.0

    def test_query_log_is_trimmed_to_the_maximum(self, monkeypatch):
        monkeypatch.setattr(ms, "MAX_ANALYTICS_ENTRIES", 2)

        for i in range(4):
            record_search_analytics(f"q-{i}", 1)

        assert [entry["query"] for entry in ms._search_analytics["queries"]] == ["q-2", "q-3"]
        assert get_search_analytics().total_searches == 4


class TestEnsureIndices:
    """ensure_indices creates missing indices and applies settings."""

    def test_existing_indices_are_not_recreated(self, service, client, indices):
        service.ensure_indices()

        client.create_index.assert_not_called()
        indices[DOCS_INDEX].update_searchable_attributes.assert_called_once_with(
            ["title", "content", "tags"]
        )
        indices[FILES_INDEX].update_searchable_attributes.assert_called_once_with(
            ["name", "tags", "mime_type"]
        )

    def test_missing_index_is_created_with_a_primary_key(self, service, client):
        client.get_index.side_effect = [_api_error(), None]

        service.ensure_indices()

        client.create_index.assert_called_once_with(DOCS_INDEX, {"primaryKey": "id"})
        client.wait_for_task.assert_called_once_with(1, timeout_in_ms=30000)


class TestPing:
    """ping reflects MeiliSearch reachability."""

    def test_true_when_healthy(self, service, client):
        client.health.return_value = {"status": "available"}
        assert service.ping() is True

    def test_false_when_unreachable(self, service, client):
        client.health.side_effect = ConnectionError("refused")
        assert service.ping() is False


class TestSearch:
    """search builds filters, aggregates indices and records analytics."""

    def test_type_and_owner_filters_are_applied_to_a_single_index(self, service, indices):
        service.search("report", doc_type="document", owner_id="u-1")

        params = indices[DOCS_INDEX].search.call_args.args[1]
        assert params["filter"] == 'type = "document" AND owner_id = "u-1"'
        assert params["offset"] == 0
        assert params["limit"] == 20
        indices[FILES_INDEX].search.assert_not_called()

    def test_quotes_and_backslashes_in_filters_are_escaped(self, service, indices):
        service.search("report", doc_type="document", owner_id='u"1\\2')

        params = indices[DOCS_INDEX].search.call_args.args[1]
        assert params["filter"] == 'type = "document" AND owner_id = "u\\"1\\\\2"'

    def test_untyped_search_spans_both_indices_and_sums_totals(self, service, indices):
        indices[DOCS_INDEX].search.return_value = {
            "hits": [{"id": "d-1", "title": "Plan"}],
            "estimatedTotalHits": 1,
        }
        indices[FILES_INDEX].search.return_value = {
            "hits": [{"id": "f-1", "name": "report.pdf"}],
            "estimatedTotalHits": 2,
        }

        response = service.search("report")

        assert response.total == 3
        assert [hit.id for hit in response.results] == ["d-1", "f-1"]
        assert [hit.type for hit in response.results] == ["document", "file"]

    def test_multi_index_pagination_slices_the_merged_hits(self, service, indices):
        indices[DOCS_INDEX].search.return_value = {
            "hits": [{"id": "d-1"}, {"id": "d-2"}],
            "estimatedTotalHits": 2,
        }
        indices[FILES_INDEX].search.return_value = {"hits": [{"id": "f-1"}], "estimatedTotalHits": 1}

        response = service.search("report", page=2, page_size=1)

        params = indices[DOCS_INDEX].search.call_args.args[1]
        assert (params["offset"], params["limit"]) == (0, 2)
        assert [hit.id for hit in response.results] == ["d-2"]

    def test_single_index_pagination_uses_an_offset(self, service, indices):
        service.search("report", doc_type="file", page=3, page_size=10)

        params = indices[FILES_INDEX].search.call_args.args[1]
        assert (params["offset"], params["limit"]) == (20, 10)

    def test_an_invalid_filter_is_surfaced_as_a_value_error(self, service, indices):
        indices[DOCS_INDEX].search.side_effect = _api_error("Attribute `nope` is not filterable")

        with pytest.raises(ValueError, match="Invalid search filter"):
            service.search("report", doc_type="document")

    def test_the_query_is_recorded_for_analytics(self, service, indices):
        indices[DOCS_INDEX].search.return_value = {"hits": [], "estimatedTotalHits": 4}

        service.search("report", doc_type="document")

        assert get_search_analytics().total_searches == 1
        assert get_search_analytics().avg_results_per_query == 4.0

    def test_highlights_and_snippets_are_extracted_from_formatted_fields(self, service, indices):
        indices[DOCS_INDEX].search.return_value = {
            "hits": [
                {
                    "id": "d-1",
                    "title": "Plan",
                    "owner_id": "u-1",
                    "tags": ["finance"],
                    "_formatted": {
                        "title": "<em>Plan</em>",
                        "content": "a <em>report</em> body",
                        "name": "no highlight here",
                    },
                }
            ],
            "estimatedTotalHits": 1,
        }

        hit = service.search("plan", doc_type="document").results[0]

        assert hit.title == "Plan"
        assert hit.highlights == {
            "title": ["<em>Plan</em>"],
            "content": ["a <em>report</em> body"],
        }
        assert hit.content_snippet == "a <em>report</em> body"

    def test_file_hits_take_their_title_from_the_name(self, service, indices):
        indices[FILES_INDEX].search.return_value = {
            "hits": [
                {
                    "id": "f-1",
                    "name": "report.pdf",
                    "mime_type": "application/pdf",
                    "folder_id": "fold-1",
                    "size": 10,
                }
            ],
            "estimatedTotalHits": 1,
        }

        hit = service.search("report", doc_type="file").results[0]

        assert hit.title == "report.pdf"
        assert hit.content_snippet == ""
        assert hit.mime_type == "application/pdf"
        assert hit.size == 10


class TestAdvancedSearch:
    """advanced_search adds tag and date filters."""

    def test_all_filters_are_combined(self, service, indices):
        service.advanced_search(
            query="report",
            doc_type="document",
            owner_id="u-1",
            tags=["finance", "q3"],
            date_from="2026-01-01",
            date_to="2026-02-01",
        )

        params = indices[DOCS_INDEX].search.call_args.args[1]
        assert params["filter"] == (
            'type = "document" AND owner_id = "u-1" '
            'AND (tags = "finance" OR tags = "q3") '
            'AND created_at >= "2026-01-01" AND created_at <= "2026-02-01"'
        )

    def test_a_missing_query_is_recorded_as_a_wildcard(self, service, indices):
        response = service.advanced_search()

        assert indices[DOCS_INDEX].search.call_args.args[0] == ""
        assert response.query == "*"
        assert get_search_analytics().popular_queries == [{"query": "*", "count": 1}]

    def test_hits_from_both_indices_are_merged(self, service, indices):
        indices[DOCS_INDEX].search.return_value = {"hits": [{"id": "d-1"}], "estimatedTotalHits": 1}
        indices[FILES_INDEX].search.return_value = {"hits": [{"id": "f-1"}], "estimatedTotalHits": 1}

        response = service.advanced_search(query="report")

        assert response.total == 2
        assert [hit.id for hit in response.results] == ["d-1", "f-1"]


class TestSuggest:
    """suggest de-duplicates titles across both indices and honours the limit."""

    def test_titles_and_names_are_merged_and_deduplicated(self, service, indices):
        indices[DOCS_INDEX].search.return_value = {
            "hits": [{"title": "Plan"}, {"title": "Plan"}, {"title": ""}]
        }
        indices[FILES_INDEX].search.return_value = {"hits": [{"name": "plan.pdf"}]}

        assert service.suggest("pl") == ["Plan", "plan.pdf"]

    def test_the_size_limit_stops_the_crawl_at_the_first_index(self, service, indices):
        indices[DOCS_INDEX].search.return_value = {
            "hits": [{"title": "Plan A"}, {"title": "Plan B"}, {"title": "Plan C"}]
        }

        assert service.suggest("pl", size=2) == ["Plan A", "Plan B"]
        indices[FILES_INDEX].search.assert_not_called()

    def test_prefix_search_requests_only_title_and_name(self, service, indices):
        service.suggest("pl", size=5)

        assert indices[DOCS_INDEX].search.call_args.args == (
            "pl",
            {"limit": 5, "attributesToRetrieve": ["title", "name"]},
        )


class TestTaskHandling:
    """_wait_and_check raises when MeiliSearch reports a failed task."""

    def test_a_failed_object_task_raises(self, service, client):
        failed = MagicMock()
        failed.status = "failed"
        failed.error = {"code": "internal"}
        client.wait_for_task.return_value = failed

        with pytest.raises(RuntimeError, match="failed"):
            service._wait_and_check(7)

    def test_a_failed_dict_task_raises(self, service, client):
        client.wait_for_task.return_value = {"status": "failed", "error": {"code": "internal"}}

        with pytest.raises(RuntimeError, match="failed"):
            service._wait_and_check(7)

    def test_a_succeeded_dict_task_is_accepted(self, service, client):
        client.wait_for_task.return_value = {"status": "succeeded"}

        service._wait_and_check(7)


class TestIndexing:
    """index_document / index_file / delete_document."""

    def test_documents_are_tagged_with_their_type(self, service, indices):
        service.index_document({"id": "d-1", "title": "Plan"})

        indices[DOCS_INDEX].add_documents.assert_called_once_with(
            [{"id": "d-1", "title": "Plan", "type": "document"}]
        )

    def test_files_are_tagged_with_their_type(self, service, indices):
        service.index_file({"id": "f-1", "name": "report.pdf"})

        indices[FILES_INDEX].add_documents.assert_called_once_with(
            [{"id": "f-1", "name": "report.pdf", "type": "file"}]
        )

    def test_lmdb_key_conflict_is_retried_after_an_explicit_delete(self, service, client, indices):
        failed = MagicMock()
        failed.status = "failed"
        failed.error = {"message": "MDB_KEYEXIST: key/data pair already exists"}
        succeeded = MagicMock()
        succeeded.status = "succeeded"
        client.wait_for_task.side_effect = [failed, succeeded, succeeded]

        service.index_file({"id": "f-1", "name": "report.pdf"})

        indices[FILES_INDEX].delete_document.assert_called_once_with("f-1")
        assert indices[FILES_INDEX].add_documents.call_count == 2

    def test_other_task_failures_are_propagated(self, service, client, indices):
        failed = MagicMock()
        failed.status = "failed"
        failed.error = {"message": "index_primary_key_multiple_candidates"}
        client.wait_for_task.return_value = failed

        with pytest.raises(RuntimeError, match="index_primary_key_multiple_candidates"):
            service.index_file({"id": "f-1", "name": "report.pdf"})

        indices[FILES_INDEX].delete_document.assert_not_called()

    def test_deleting_an_indexed_document_returns_true(self, service, indices):
        assert service.delete_document("document", "d-1") is True
        indices[DOCS_INDEX].delete_document.assert_called_once_with("d-1")

    def test_deleting_an_unknown_document_returns_false(self, service, indices):
        indices[DOCS_INDEX].get_document.side_effect = _api_error()

        assert service.delete_document("document", "d-9") is False
        indices[DOCS_INDEX].delete_document.assert_not_called()

    def test_non_document_types_are_deleted_from_the_files_index(self, service, indices):
        assert service.delete_document("file", "f-1") is True
        indices[FILES_INDEX].delete_document.assert_called_once_with("f-1")


class TestReindex:
    """reindex drops, recreates and optionally repopulates the indices."""

    def test_without_data_the_indices_are_left_empty(self, service, client):
        result = service.reindex()

        assert client.delete_index.call_count == 2
        assert result == {
            "status": "reindexed",
            "indices": [DOCS_INDEX, FILES_INDEX],
            "indexed_counts": {"documents": 0, "files": 0},
        }

    def test_a_missing_index_does_not_abort_the_reindex(self, service, client):
        client.delete_index.side_effect = _api_error()

        result = service.reindex()

        assert result["status"] == "reindexed"

    def test_documents_and_files_are_bulk_indexed_in_batches(self, service, indices):
        documents = [{"id": f"d-{i}"} for i in range(501)]
        files = [{"id": "f-1"}]

        result = service.reindex(documents=documents, files=files)

        assert indices[DOCS_INDEX].add_documents.call_count == 2
        assert len(indices[DOCS_INDEX].add_documents.call_args_list[0].args[0]) == 500
        assert len(indices[DOCS_INDEX].add_documents.call_args_list[1].args[0]) == 1
        indices[FILES_INDEX].add_documents.assert_called_once_with(files)
        assert result["indexed_counts"] == {"documents": 501, "files": 1}
