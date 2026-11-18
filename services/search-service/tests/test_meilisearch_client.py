"""Tests for MeiliSearchService edge and error paths."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.services import meilisearch_client as mc
from tests.helpers import meili_api_error


def _task(uid: int = 1) -> MagicMock:
    task = MagicMock()
    task.task_uid = uid
    return task


def _status(status: str, error=None) -> MagicMock:
    result = MagicMock()
    result.status = status
    result.error = error
    return result


class TestAnalytics:
    def test_queries_trimmed_to_max(self, monkeypatch):
        monkeypatch.setattr(mc, "MAX_ANALYTICS_ENTRIES", 2)
        monkeypatch.setitem(mc._search_analytics, "queries", [])
        monkeypatch.setitem(mc._search_analytics, "total_searches", 0)
        monkeypatch.setitem(mc._search_analytics, "total_results", 0)
        for q in ("a", "b", "c"):
            mc.record_search_analytics(q, 0)
        assert [e["query"] for e in mc._search_analytics["queries"]] == ["b", "c"]
        assert mc._search_analytics["total_searches"] == 3

    def test_empty_analytics(self, monkeypatch):
        monkeypatch.setitem(mc._search_analytics, "queries", [])
        monkeypatch.setitem(mc._search_analytics, "total_searches", 0)
        monkeypatch.setitem(mc._search_analytics, "total_results", 0)
        data = mc.get_search_analytics()
        assert data.total_searches == 0
        assert data.avg_results_per_query == 0.0


class TestEnsureIndices:
    def test_creates_missing_indices(self, meilisearch_service, mock_meilisearch_client):
        mock_meilisearch_client.get_index.side_effect = meili_api_error()
        mock_meilisearch_client.create_index.reset_mock()
        meilisearch_service.ensure_indices()
        names = [c.args[0] for c in mock_meilisearch_client.create_index.call_args_list]
        assert names == ["test-otterworks-documents", "test-otterworks-files"]
        assert mock_meilisearch_client.create_index.call_args.args[1] == {"primaryKey": "id"}

    def test_ping_false_on_error(self, meilisearch_service, mock_meilisearch_client):
        mock_meilisearch_client.health.side_effect = ConnectionError()
        assert meilisearch_service.ping() is False


class TestSearch:
    def test_filters_escaped_and_combined(self, meilisearch_service, mock_meilisearch_client):
        index = mock_meilisearch_client.index.return_value
        meilisearch_service.search("q", doc_type='file"x', owner_id="u\\1")
        params = index.search.call_args.args[1]
        assert params["filter"] == 'type = "file\\"x" AND owner_id = "u\\\\1"'

    def test_owner_scoping(self, meilisearch_service, mock_meilisearch_client):
        index = mock_meilisearch_client.index.return_value
        meilisearch_service.search("q", owner_id="user-1")
        assert index.search.call_args.args[1]["filter"] == 'owner_id = "user-1"'

    def test_single_index_uses_offset(self, meilisearch_service, mock_meilisearch_client):
        index = mock_meilisearch_client.index.return_value
        meilisearch_service.search("q", doc_type="document", page=3, page_size=10)
        params = index.search.call_args.args[1]
        assert (params["offset"], params["limit"]) == (20, 10)

    def test_multi_index_fetches_and_slices(self, meilisearch_service, mock_meilisearch_client):
        index = mock_meilisearch_client.index.return_value
        index.search.return_value = {
            "estimatedTotalHits": 3,
            "hits": [{"id": f"h{i}", "title": f"T{i}", "name": f"N{i}"} for i in range(3)],
        }
        result = meilisearch_service.search("q", page=2, page_size=2)
        params = index.search.call_args.args[1]
        assert (params["offset"], params["limit"]) == (0, 4)
        assert result.total == 6
        assert [h.id for h in result.results] == ["h2", "h0"]
        assert result.results[1].type == "file"

    def test_invalid_filter_raises_value_error(self, meilisearch_service, mock_meilisearch_client):
        mock_meilisearch_client.index.return_value.search.side_effect = meili_api_error(400, "invalid_search_filter")
        with pytest.raises(ValueError, match="Invalid search filter"):
            meilisearch_service.search("q")


class TestAdvancedSearch:
    def test_all_filters(self, meilisearch_service, mock_meilisearch_client):
        index = mock_meilisearch_client.index.return_value
        index.search.return_value = {
            "estimatedTotalHits": 1,
            "hits": [{"id": "d1", "title": "Doc", "_formatted": {"title": "<em>Doc</em>", "content": "x"}}],
        }
        result = meilisearch_service.advanced_search(
            query="doc", doc_type="document", owner_id="u1", tags=["a", "b"],
            date_from="2026-01-01", date_to="2026-02-01",
        )
        assert index.search.call_args.args[1]["filter"] == (
            'type = "document" AND owner_id = "u1" AND (tags = "a" OR tags = "b") '
            'AND created_at >= "2026-01-01" AND created_at <= "2026-02-01"'
        )
        assert result.total == 1
        assert result.results[0].highlights == {"title": ["<em>Doc</em>"]}
        assert result.query == "doc"

    def test_empty_query_reported_as_wildcard(self, meilisearch_service, mock_meilisearch_client):
        result = meilisearch_service.advanced_search()
        assert result.query == "*"
        assert mock_meilisearch_client.index.return_value.search.call_args.args[0] == ""


class TestSuggest:
    def test_stops_at_size_and_dedupes(self, meilisearch_service, mock_meilisearch_client):
        index = mock_meilisearch_client.index.return_value
        index.search.return_value = {
            "hits": [{"title": "Alpha"}, {"title": "Alpha"}, {"name": "Beta"}, {"title": ""}, {"name": "Gamma"}]
        }
        assert meilisearch_service.suggest("al", size=2) == ["Alpha", "Beta"]
        assert index.search.call_count == 1

    def test_collects_across_indices(self, meilisearch_service, mock_meilisearch_client):
        index = mock_meilisearch_client.index.return_value
        index.search.side_effect = [{"hits": [{"title": "Doc"}]}, {"hits": [{"name": "File"}, {"title": "Doc"}]}]
        assert meilisearch_service.suggest("do") == ["Doc", "File"]


class TestWaitAndCheck:
    def test_failed_task_object(self, meilisearch_service, mock_meilisearch_client):
        mock_meilisearch_client.wait_for_task.return_value = _status("failed", {"code": "x"})
        with pytest.raises(RuntimeError, match="task 7 failed"):
            meilisearch_service._wait_and_check(7)

    def test_failed_task_dict(self, meilisearch_service, mock_meilisearch_client):
        mock_meilisearch_client.wait_for_task.return_value = {"status": "canceled", "error": "stop"}
        with pytest.raises(RuntimeError, match="canceled: stop"):
            meilisearch_service._wait_and_check(1)

    def test_unknown_status_shape_is_ignored(self, meilisearch_service, mock_meilisearch_client):
        mock_meilisearch_client.wait_for_task.return_value = object()
        meilisearch_service._wait_and_check(1)


class TestIndexFile:
    def test_mdb_keyexist_retries_after_delete(self, meilisearch_service, mock_meilisearch_client):
        index = mock_meilisearch_client.index.return_value
        index.add_documents.side_effect = [_task(1), _task(3)]
        index.delete_document.return_value = _task(2)
        mock_meilisearch_client.wait_for_task.side_effect = [
            _status("failed", "MDB_KEYEXIST: key exists"),
            _status("succeeded"),
            _status("succeeded"),
        ]
        meilisearch_service.index_file({"id": "f1", "name": "a"})
        index.delete_document.assert_called_once_with("f1")
        assert index.add_documents.call_count == 2
        assert index.add_documents.call_args.args[0] == [{"id": "f1", "name": "a", "type": "file"}]

    def test_other_failures_propagate(self, meilisearch_service, mock_meilisearch_client):
        mock_meilisearch_client.wait_for_task.return_value = _status("failed", "disk full")
        with pytest.raises(RuntimeError, match="disk full"):
            meilisearch_service.index_file({"id": "f1", "name": "a"})
        mock_meilisearch_client.index.return_value.delete_document.assert_not_called()


class TestDeleteDocument:
    def test_not_found_returns_false(self, meilisearch_service, mock_meilisearch_client):
        index = mock_meilisearch_client.index.return_value
        index.get_document.side_effect = meili_api_error(404, "document_not_found")
        assert meilisearch_service.delete_document("file", "missing") is False
        index.delete_document.assert_not_called()
        mock_meilisearch_client.index.assert_called_with("test-otterworks-files")

    def test_found_is_deleted(self, meilisearch_service, mock_meilisearch_client):
        assert meilisearch_service.delete_document("document", "d1") is True
        mock_meilisearch_client.index.return_value.delete_document.assert_called_once_with("d1")


class TestReindex:
    def test_delete_errors_ignored_and_batches_added(self, meilisearch_service, mock_meilisearch_client):
        mock_meilisearch_client.delete_index.side_effect = [meili_api_error(), _task()]
        mock_meilisearch_client.wait_for_task.side_effect = [_status("failed", "x")] + [_status("succeeded")] * 10
        index = mock_meilisearch_client.index.return_value
        index.add_documents.reset_mock()
        docs = [{"id": f"d{i}"} for i in range(501)]
        files = [{"id": "f1"}]

        result = meilisearch_service.reindex(documents=docs, files=files)

        sizes = [len(c.args[0]) for c in index.add_documents.call_args_list]
        assert sizes == [500, 1, 1]
        assert result == {
            "status": "reindexed",
            "indices": ["test-otterworks-documents", "test-otterworks-files"],
            "indexed_counts": {"documents": 501, "files": 1},
        }

    def test_without_data_leaves_indices_empty(self, meilisearch_service, mock_meilisearch_client):
        index = mock_meilisearch_client.index.return_value
        index.add_documents.reset_mock()
        result = meilisearch_service.reindex()
        index.add_documents.assert_not_called()
        assert result["indexed_counts"] == {"documents": 0, "files": 0}
