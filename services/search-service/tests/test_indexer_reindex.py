"""Tests for Indexer full-reindex source fetching."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from app.services import indexer as indexer_module
from app.services.indexer import Indexer


def _resp(status: int = 200, payload: dict | None = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = payload or {}
    return resp


class TestFetchAllDocuments:
    def test_paginates_until_empty_page(self):
        pages = [
            _resp(payload={"documents": [{"id": "d1", "title": "One", "content": "c", "owner_id": "u",
                                          "tags": ["t"], "created_at": "c1", "updated_at": "u1"}]}),
            _resp(payload={"items": [{"id": "d2"}]}),
            _resp(payload={"data": []}),
        ]
        with patch.object(indexer_module.requests, "get", side_effect=pages) as get:
            docs = Indexer._fetch_all_documents()

        assert docs == [
            {"id": "d1", "title": "One", "content": "c", "owner_id": "u", "tags": ["t"],
             "created_at": "c1", "updated_at": "u1", "type": "document"},
            {"id": "d2", "title": "", "content": "", "owner_id": "", "tags": [],
             "created_at": None, "updated_at": None, "type": "document"},
        ]
        assert [c.kwargs["params"]["page"] for c in get.call_args_list] == [1, 2, 3]
        assert get.call_args.args[0] == "http://document-service:8083/api/v1/documents/"
        assert get.call_args.kwargs["timeout"] == indexer_module.FETCH_TIMEOUT

    def test_accepts_data_key(self):
        pages = [_resp(payload={"data": [{"id": "d1"}]}), _resp(payload={})]
        with patch.object(indexer_module.requests, "get", side_effect=pages):
            assert [d["id"] for d in Indexer._fetch_all_documents()] == ["d1"]

    def test_non_200_stops(self):
        pages = [_resp(payload={"documents": [{"id": "d1"}]}), _resp(status=503)]
        with patch.object(indexer_module.requests, "get", side_effect=pages):
            assert [d["id"] for d in Indexer._fetch_all_documents()] == ["d1"]

    def test_request_exception_stops(self):
        with patch.object(indexer_module.requests, "get", side_effect=requests.ConnectionError("down")):
            assert Indexer._fetch_all_documents() == []


class TestFetchAllFiles:
    def test_maps_camel_case_fields(self):
        pages = [
            _resp(payload={"files": [{"id": "f1", "name": "a.pdf", "mimeType": "application/pdf",
                                      "ownerId": "u", "folderId": "fo", "sizeBytes": 5,
                                      "createdAt": "c", "updatedAt": "u2"}]}),
            _resp(payload={"items": [{"id": "f2", "name": "b", "mime_type": "text/plain", "owner_id": "u",
                                      "folder_id": "fo", "size_bytes": 7, "tags": ["x"],
                                      "created_at": "c", "updated_at": "u"}]}),
            _resp(payload={"data": [{"id": "f3", "size": 9}]}),
            _resp(payload={"files": []}),
        ]
        with patch.object(indexer_module.requests, "get", side_effect=pages) as get:
            files = Indexer._fetch_all_files()

        assert files[0] == {"id": "f1", "name": "a.pdf", "mime_type": "application/pdf", "owner_id": "u",
                            "folder_id": "fo", "tags": [], "size": 5, "created_at": "c",
                            "updated_at": "u2", "type": "file"}
        assert files[1]["size"] == 7
        assert files[1]["mime_type"] == "text/plain"
        assert files[1]["tags"] == ["x"]
        assert files[2]["size"] == 9
        assert files[2]["name"] == ""
        assert get.call_args.args[0] == "http://file-service:8082/api/v1/files"

    def test_non_200_stops(self):
        with patch.object(indexer_module.requests, "get", return_value=_resp(status=401)):
            assert Indexer._fetch_all_files() == []

    def test_request_exception_stops(self):
        with patch.object(indexer_module.requests, "get", side_effect=requests.Timeout("slow")):
            assert Indexer._fetch_all_files() == []


class TestReindex:
    @pytest.fixture()
    def search(self) -> MagicMock:
        mock = MagicMock()
        mock.reindex.return_value = {"status": "reindexed"}
        return mock

    def test_passes_fetched_data_to_search(self, search):
        docs = [{"id": "d1"}]
        files = [{"id": "f1"}, {"id": "f2"}]
        with patch.object(Indexer, "_fetch_all_documents", return_value=docs), \
                patch.object(Indexer, "_fetch_all_files", return_value=files):
            result = Indexer(search).reindex()
        search.reindex.assert_called_once_with(documents=docs, files=files)
        assert result == {"status": "reindexed"}

    def test_process_event_delete_defaults_to_document(self, search):
        search.delete_document.return_value = True
        result = Indexer(search).process_event({"action": "delete", "data": {"id": "x"}})
        search.delete_document.assert_called_once_with("document", "x")
        assert result["status"] == "deleted"

    def test_remove_not_found(self, search):
        search.delete_document.return_value = False
        assert Indexer(search).remove("file", "missing")["status"] == "not_found"
