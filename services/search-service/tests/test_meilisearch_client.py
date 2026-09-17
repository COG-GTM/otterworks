"""Tests for the MeiliSearch client wrapper and the analytics store."""

from __future__ import annotations

from unittest.mock import MagicMock

import meilisearch
import pytest

import app.services.meilisearch_client as mod
from app.config import MeiliSearchConfig
from app.services.meilisearch_client import (
    MeiliSearchService,
    get_search_analytics,
    record_search_analytics,
)

DOCS_INDEX = "test-documents"
FILES_INDEX = "test-files"


def _api_error(message: str = "not found") -> meilisearch.errors.MeilisearchApiError:
    """Build a MeilisearchApiError without going through HTTP."""
    response = MagicMock()
    response.status_code = 404
    response.text = ""
    return meilisearch.errors.MeilisearchApiError(message, response)


def _task(uid: int = 1) -> MagicMock:
    task = MagicMock()
    task.task_uid = uid
    return task


@pytest.fixture()
def indices() -> dict[str, MagicMock]:
    """Separate mock indices so per-index behaviour can be asserted."""
    built = {}
    for name in (DOCS_INDEX, FILES_INDEX):
        index = MagicMock(name=name)
        index.search.return_value = {"hits": [], "estimatedTotalHits": 0}
        index.add_documents.return_value = _task()
        index.delete_document.return_value = _task()
        built[name] = index
    return built


@pytest.fixture()
def meili(indices) -> MagicMock:
    """A mock meilisearch.Client whose tasks always succeed."""
    client = MagicMock()
    client.index.side_effect = lambda name: indices[name]
    succeeded = MagicMock()
    succeeded.status = "succeeded"
    client.wait_for_task.return_value = succeeded
    client.create_index.return_value = _task()
    client.delete_index.return_value = _task()
    return client


@pytest.fixture()
def service(meili, monkeypatch) -> MeiliSearchService:
    """A MeiliSearchService bound to the mock client."""
    monkeypatch.setattr(mod.meilisearch, "Client", MagicMock(return_value=meili))
    return MeiliSearchService(
        MeiliSearchConfig(
            url="http://meili.test",
            api_key="key",
            documents_index=DOCS_INDEX,
            files_index=FILES_INDEX,
        )
    )


@pytest.fixture(autouse=True)
def isolated_analytics(monkeypatch):
    """Keep the module-level analytics store out of other tests."""
    monkeypatch.setattr(
        mod,
        "_search_analytics",
        {"queries": [], "total_searches": 0, "total_results": 0},
    )


class TestAnalytics:
    """Tests for the in-memory analytics store."""

    def test_popular_and_zero_result_queries_are_ranked(self):
        record_search_analytics("budget", 3)
        record_search_analytics("budget", 2)
        record_search_analytics("nothing", 0)

        analytics = get_search_analytics()

        assert analytics.popular_queries[0] == {"query": "budget", "count": 2}
        assert analytics.zero_result_queries == [{"query": "nothing", "count": 1}]
        assert analytics.total_searches == 3
        assert analytics.avg_results_per_query == round(5 / 3, 2)

    def test_empty_store_reports_zero_average(self):
        analytics = get_search_analytics()

        assert analytics.total_searches == 0
        assert analytics.avg_results_per_query == 0.0

    def test_query_log_is_trimmed_to_the_cap(self, monkeypatch):
        """The rolling log keeps only the most recent MAX_ANALYTICS_ENTRIES."""
        monkeypatch.setattr(mod, "MAX_ANALYTICS_ENTRIES", 2)

        for i in range(4):
            record_search_analytics(f"q-{i}", 1)

        assert [e["query"] for e in mod._search_analytics["queries"]] == ["q-2", "q-3"]
        assert mod._search_analytics["total_searches"] == 4


class TestEnsureIndices:
    """Tests for index bootstrapping."""

    def test_existing_indices_are_not_recreated(self, service, meili):
        service.ensure_indices()

        meili.create_index.assert_not_called()

    def test_missing_indices_are_created_and_awaited(self, service, meili):
        meili.get_index.side_effect = _api_error()

        service.ensure_indices()

        assert meili.create_index.call_count == 2
        meili.create_index.assert_any_call(DOCS_INDEX, {"primaryKey": "id"})
        assert meili.wait_for_task.call_count == 2

    def test_searchable_attributes_are_configured_per_index(self, service, indices):
        service.ensure_indices()

        indices[DOCS_INDEX].update_searchable_attributes.assert_called_once_with(
            ["title", "content", "tags"]
        )
        indices[FILES_INDEX].update_searchable_attributes.assert_called_once_with(
            ["name", "tags", "mime_type"]
        )


class TestPing:
    """Tests for the readiness probe helper."""

    def test_healthy_client_pings_true(self, service):
        assert service.ping() is True

    def test_unreachable_client_pings_false(self, service, meili):
        meili.health.side_effect = ConnectionError("down")

        assert service.ping() is False


class TestSearch:
    """Tests for the search entry points."""

    def test_owner_and_type_filters_are_applied_to_a_single_index(self, service, indices):
        service.search(query="budget", doc_type="document", owner_id="user-1")

        indices[FILES_INDEX].search.assert_not_called()
        params = indices[DOCS_INDEX].search.call_args[0][1]
        assert params["filter"] == 'type = "document" AND owner_id = "user-1"'
        assert params["offset"] == 0
        assert params["limit"] == 20

    def test_quotes_in_filter_values_are_escaped(self, service, indices):
        service.search(query="q", doc_type="document", owner_id='us"er\\1')

        params = indices[DOCS_INDEX].search.call_args[0][1]
        assert params["filter"] == 'type = "document" AND owner_id = "us\\"er\\\\1"'

    def test_multi_index_search_fetches_enough_rows_to_paginate(self, service, indices):
        service.search(query="budget", page=3, page_size=10)

        params = indices[DOCS_INDEX].search.call_args[0][1]
        assert params["offset"] == 0
        assert params["limit"] == 30

    def test_hits_from_both_indices_are_merged_and_parsed(self, service, indices):
        indices[DOCS_INDEX].search.return_value = {
            "hits": [
                {
                    "id": "d-1",
                    "title": "Budget",
                    "owner_id": "u-1",
                    "_formatted": {"content": "a <em>budget</em> line", "title": "Budget"},
                }
            ],
            "estimatedTotalHits": 1,
        }
        indices[FILES_INDEX].search.return_value = {
            "hits": [{"id": "f-1", "name": "budget.xlsx", "mime_type": "text/csv"}],
            "estimatedTotalHits": 1,
        }

        response = service.search(query="budget")

        assert response.total == 2
        assert [hit.id for hit in response.results] == ["d-1", "f-1"]
        assert response.results[0].content_snippet == "a <em>budget</em> line"
        assert response.results[0].highlights == {"content": ["a <em>budget</em> line"]}
        assert response.results[1].title == "budget.xlsx"
        assert response.results[1].type == "file"

    def test_rejected_filter_becomes_a_value_error(self, service, indices):
        indices[DOCS_INDEX].search.side_effect = _api_error("invalid filter")

        with pytest.raises(ValueError, match="Invalid search filter"):
            service.search(query="budget", doc_type="document")

    def test_advanced_search_builds_every_filter(self, service, indices):
        indices[FILES_INDEX].search.return_value = {
            "hits": [{"id": "f-1", "name": "q3.xlsx"}],
            "estimatedTotalHits": 1,
        }

        response = service.advanced_search(
            doc_type="file",
            owner_id="u-1",
            tags=["finance", "q3"],
            date_from="2026-01-01",
            date_to="2026-02-01",
        )

        params = indices[FILES_INDEX].search.call_args[0][1]
        assert params["filter"] == (
            'type = "file" AND owner_id = "u-1" '
            'AND (tags = "finance" OR tags = "q3") '
            'AND created_at >= "2026-01-01" AND created_at <= "2026-02-01"'
        )
        assert response.query == "*"
        assert [hit.id for hit in response.results] == ["f-1"]


class TestSuggest:
    """Tests for the autocomplete helper."""

    def test_duplicate_titles_are_only_suggested_once(self, service, indices):
        indices[DOCS_INDEX].search.return_value = {
            "hits": [{"title": "Budget"}, {"title": "Budget"}, {"title": ""}]
        }
        indices[FILES_INDEX].search.return_value = {"hits": [{"name": "budget.xlsx"}]}

        assert service.suggest("bud") == ["Budget", "budget.xlsx"]

    def test_suggestions_stop_at_the_requested_size(self, service, indices):
        indices[DOCS_INDEX].search.return_value = {
            "hits": [{"title": "a"}, {"title": "b"}, {"title": "c"}]
        }

        assert service.suggest("x", size=2) == ["a", "b"]
        indices[FILES_INDEX].search.assert_not_called()


class TestWriteOperations:
    """Tests for indexing, deletion and task-failure handling."""

    def test_index_document_tags_the_payload_as_a_document(self, service, indices):
        service.index_document({"id": "d-1", "title": "One"})

        indices[DOCS_INDEX].add_documents.assert_called_once_with(
            [{"id": "d-1", "title": "One", "type": "document"}]
        )

    def test_failed_task_raises(self, service, meili):
        failed = MagicMock()
        failed.status = "failed"
        failed.error = "index full"
        meili.wait_for_task.return_value = failed

        with pytest.raises(RuntimeError, match="failed: index full"):
            service.index_document({"id": "d-1", "title": "One"})

    def test_dict_task_result_is_understood(self, service, meili):
        """wait_for_task may return a plain dict depending on the client version."""
        meili.wait_for_task.return_value = {"status": "failed", "error": "boom"}

        with pytest.raises(RuntimeError, match="failed: boom"):
            service.index_document({"id": "d-1", "title": "One"})

    def test_index_file_retries_once_after_an_lmdb_key_collision(
        self, service, meili, indices
    ):
        """A known Meilisearch LMDB bug is worked around by delete-then-re-add."""
        failed = MagicMock()
        failed.status = "failed"
        failed.error = "MDB_KEYEXIST: key/data pair already exists"
        succeeded = MagicMock()
        succeeded.status = "succeeded"
        meili.wait_for_task.side_effect = [failed, succeeded, succeeded]

        service.index_file({"id": "f-1", "name": "a.txt"})

        indices[FILES_INDEX].delete_document.assert_called_once_with("f-1")
        assert indices[FILES_INDEX].add_documents.call_count == 2

    def test_index_file_propagates_other_task_failures(self, service, meili, indices):
        failed = MagicMock()
        failed.status = "failed"
        failed.error = "disk full"
        meili.wait_for_task.return_value = failed

        with pytest.raises(RuntimeError, match="disk full"):
            service.index_file({"id": "f-1", "name": "a.txt"})

        indices[FILES_INDEX].delete_document.assert_not_called()

    def test_delete_document_removes_an_existing_document(self, service, indices):
        assert service.delete_document("document", "d-1") is True
        indices[DOCS_INDEX].delete_document.assert_called_once_with("d-1")

    def test_delete_document_returns_false_when_absent(self, service, indices):
        indices[FILES_INDEX].get_document.side_effect = _api_error()

        assert service.delete_document("file", "f-1") is False
        indices[FILES_INDEX].delete_document.assert_not_called()


class TestReindex:
    """Tests for the destructive full reindex."""

    def test_indices_are_dropped_recreated_and_repopulated(self, service, meili, indices):
        meili.get_index.side_effect = _api_error()

        result = service.reindex(
            documents=[{"id": f"d-{i}"} for i in range(501)],
            files=[{"id": "f-1"}],
        )

        assert meili.delete_index.call_count == 2
        assert result["indexed_counts"] == {"documents": 501, "files": 1}
        assert result["indices"] == [DOCS_INDEX, FILES_INDEX]
        # 501 documents are written in two batches of at most 500.
        assert indices[DOCS_INDEX].add_documents.call_count == 2
        assert indices[FILES_INDEX].add_documents.call_count == 1

    def test_missing_indices_are_tolerated_when_dropping(self, service, meili):
        meili.delete_index.side_effect = _api_error()

        result = service.reindex()

        assert result["indexed_counts"] == {"documents": 0, "files": 0}
