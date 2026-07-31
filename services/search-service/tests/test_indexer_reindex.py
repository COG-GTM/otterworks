"""Tests for the Indexer's source-service crawl used by reindex."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from app.services.indexer import (
    DOCUMENT_SERVICE_URL,
    FETCH_TIMEOUT,
    FILE_SERVICE_URL,
    Indexer,
)


def _response(status_code: int = 200, payload: dict | None = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = payload if payload is not None else {}
    return resp


@pytest.fixture()
def indexer() -> Indexer:
    """Indexer over a mocked MeiliSearch service."""
    return Indexer(MagicMock())


class TestFetchAllDocuments:
    """Tests for _fetch_all_documents pagination and mapping."""

    def test_paginates_until_an_empty_page(self, indexer):
        """Pages are requested in order until the service returns nothing."""
        with patch("app.services.indexer.requests.get") as get:
            get.side_effect = [
                _response(payload={"documents": [{"id": "d-1", "title": "One"}]}),
                _response(payload={"documents": [{"id": "d-2", "title": "Two"}]}),
                _response(payload={"documents": []}),
            ]
            docs = Indexer._fetch_all_documents()

        assert [d["id"] for d in docs] == ["d-1", "d-2"]
        assert [call.kwargs["params"]["page"] for call in get.call_args_list] == [1, 2, 3]
        assert get.call_args_list[0].args[0] == f"{DOCUMENT_SERVICE_URL}/api/v1/documents/"
        assert get.call_args_list[0].kwargs["timeout"] == FETCH_TIMEOUT

    @pytest.mark.parametrize("key", ["documents", "items", "data"])
    def test_accepts_each_supported_envelope_key(self, indexer, key):
        """The document-service list may arrive under any of three keys."""
        with patch("app.services.indexer.requests.get") as get:
            get.side_effect = [
                _response(payload={key: [{"id": "d-1", "title": "One"}]}),
                _response(payload={key: []}),
            ]
            docs = Indexer._fetch_all_documents()

        assert len(docs) == 1

    def test_maps_fields_and_defaults_missing_ones(self, indexer):
        """Each document is normalised to the indexer's document shape."""
        with patch("app.services.indexer.requests.get") as get:
            get.side_effect = [
                _response(payload={"documents": [{"id": "d-1"}]}),
                _response(payload={"documents": []}),
            ]
            docs = Indexer._fetch_all_documents()

        assert docs == [{
            "id": "d-1",
            "title": "",
            "content": "",
            "owner_id": "",
            "tags": [],
            "created_at": None,
            "updated_at": None,
            "type": "document",
        }]

    def test_stops_on_a_non_200_response(self, indexer):
        """An error status ends the crawl with whatever was collected."""
        with patch("app.services.indexer.requests.get") as get:
            get.side_effect = [
                _response(payload={"documents": [{"id": "d-1", "title": "One"}]}),
                _response(status_code=503),
            ]
            docs = Indexer._fetch_all_documents()

        assert [d["id"] for d in docs] == ["d-1"]

    def test_stops_when_the_service_is_unreachable(self, indexer):
        """A connection failure ends the crawl instead of propagating."""
        with patch(
            "app.services.indexer.requests.get",
            side_effect=requests.RequestException("connection refused"),
        ):
            assert Indexer._fetch_all_documents() == []


class TestFetchAllFiles:
    """Tests for _fetch_all_files pagination and mapping."""

    def test_paginates_until_an_empty_page(self, indexer):
        """Pages are requested in order until the service returns nothing."""
        with patch("app.services.indexer.requests.get") as get:
            get.side_effect = [
                _response(payload={"files": [{"id": "f-1", "name": "a.txt"}]}),
                _response(payload={"files": []}),
            ]
            files = Indexer._fetch_all_files()

        assert [f["id"] for f in files] == ["f-1"]
        assert get.call_args_list[0].args[0] == f"{FILE_SERVICE_URL}/api/v1/files"

    @pytest.mark.parametrize("key", ["files", "items", "data"])
    def test_accepts_each_supported_envelope_key(self, indexer, key):
        """The file-service list may arrive under any of three keys."""
        with patch("app.services.indexer.requests.get") as get:
            get.side_effect = [
                _response(payload={key: [{"id": "f-1", "name": "a.txt"}]}),
                _response(payload={key: []}),
            ]
            assert len(Indexer._fetch_all_files()) == 1

    def test_accepts_camel_case_file_metadata(self, indexer):
        """file-service camelCase fields are mapped to snake_case."""
        with patch("app.services.indexer.requests.get") as get:
            get.side_effect = [
                _response(payload={"files": [{
                    "id": "f-1",
                    "name": "a.txt",
                    "mimeType": "text/plain",
                    "ownerId": "u-1",
                    "folderId": "fold-1",
                    "sizeBytes": 12,
                    "createdAt": "2026-01-01",
                    "updatedAt": "2026-01-02",
                }]}),
                _response(payload={"files": []}),
            ]
            files = Indexer._fetch_all_files()

        assert files == [{
            "id": "f-1",
            "name": "a.txt",
            "mime_type": "text/plain",
            "owner_id": "u-1",
            "folder_id": "fold-1",
            "tags": [],
            "size": 12,
            "created_at": "2026-01-01",
            "updated_at": "2026-01-02",
            "type": "file",
        }]

    def test_stops_on_a_non_200_response(self, indexer):
        """An error status ends the crawl with whatever was collected."""
        with patch("app.services.indexer.requests.get") as get:
            get.side_effect = [_response(status_code=500)]
            assert Indexer._fetch_all_files() == []

    def test_stops_when_the_service_is_unreachable(self, indexer):
        """A connection failure ends the crawl instead of propagating."""
        with patch(
            "app.services.indexer.requests.get",
            side_effect=requests.RequestException("connection refused"),
        ):
            assert Indexer._fetch_all_files() == []


class TestReindex:
    """Tests for the full reindex orchestration."""

    def test_crawls_both_services_and_hands_the_data_to_meilisearch(self, indexer):
        """Documents and files are fetched, then bulk-reindexed."""
        documents = [{"id": "d-1"}]
        files = [{"id": "f-1"}]
        indexer.search.reindex.return_value = {"status": "reindexed"}

        with (
            patch.object(Indexer, "_fetch_all_documents", return_value=documents),
            patch.object(Indexer, "_fetch_all_files", return_value=files),
        ):
            result = indexer.reindex()

        indexer.search.reindex.assert_called_once_with(documents=documents, files=files)
        assert result == {"status": "reindexed"}
