"""Tests for the Indexer's reindex crawl of the source-of-truth services.

``requests`` is mocked at the boundary — no HTTP is performed.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from app.services.indexer import Indexer


def _response(payload: dict, status: int = 200) -> MagicMock:
    response = MagicMock()
    response.status_code = status
    response.json.return_value = payload
    return response


@pytest.fixture()
def http_get():
    with patch("app.services.indexer.requests.get") as get:
        yield get


class TestFetchAllDocuments:
    """_fetch_all_documents paginates until an empty page."""

    def test_paginates_and_normalizes_items(self, http_get):
        http_get.side_effect = [
            _response({"documents": [{"id": "d-1", "title": "Plan", "content": "body"}]}),
            _response({"documents": []}),
        ]

        docs = Indexer._fetch_all_documents()

        assert docs == [
            {
                "id": "d-1",
                "title": "Plan",
                "content": "body",
                "owner_id": "",
                "tags": [],
                "created_at": None,
                "updated_at": None,
                "type": "document",
            }
        ]
        assert [call.kwargs["params"]["page"] for call in http_get.call_args_list] == [1, 2]

    @pytest.mark.parametrize("key", ["documents", "items", "data"])
    def test_accepts_each_supported_envelope_key(self, http_get, key):
        http_get.side_effect = [_response({key: [{"id": "d-1"}]}), _response({key: []})]

        docs = Indexer._fetch_all_documents()

        assert [doc["id"] for doc in docs] == ["d-1"]

    def test_stops_on_a_non_200_response(self, http_get):
        http_get.return_value = _response({}, status=503)

        assert Indexer._fetch_all_documents() == []
        assert http_get.call_count == 1

    def test_stops_on_a_transport_error(self, http_get):
        http_get.side_effect = requests.RequestException("connection refused")

        assert Indexer._fetch_all_documents() == []


class TestFetchAllFiles:
    """_fetch_all_files paginates and accepts both naming conventions."""

    def test_camelcase_fields_are_normalized(self, http_get):
        http_get.side_effect = [
            _response(
                {
                    "files": [
                        {
                            "id": "f-1",
                            "name": "report.pdf",
                            "mimeType": "application/pdf",
                            "ownerId": "u-1",
                            "folderId": "fold-1",
                            "sizeBytes": 1024,
                            "createdAt": "2026-01-01",
                            "updatedAt": "2026-01-02",
                        }
                    ]
                }
            ),
            _response({"files": []}),
        ]

        files = Indexer._fetch_all_files()

        assert files == [
            {
                "id": "f-1",
                "name": "report.pdf",
                "mime_type": "application/pdf",
                "owner_id": "u-1",
                "folder_id": "fold-1",
                "tags": [],
                "size": 1024,
                "created_at": "2026-01-01",
                "updated_at": "2026-01-02",
                "type": "file",
            }
        ]

    def test_snake_case_fields_are_preferred_when_present(self, http_get):
        http_get.side_effect = [
            _response(
                {
                    "items": [
                        {
                            "id": "f-2",
                            "name": "notes.txt",
                            "mime_type": "text/plain",
                            "owner_id": "u-2",
                            "folder_id": "fold-2",
                            "size": 12,
                            "tags": ["notes"],
                            "created_at": "2026-03-01",
                            "updated_at": "2026-03-02",
                        }
                    ]
                }
            ),
            _response({"items": []}),
        ]

        files = Indexer._fetch_all_files()

        assert files[0]["mime_type"] == "text/plain"
        assert files[0]["owner_id"] == "u-2"
        assert files[0]["size"] == 12
        assert files[0]["tags"] == ["notes"]

    def test_stops_on_a_non_200_response(self, http_get):
        http_get.return_value = _response({}, status=500)

        assert Indexer._fetch_all_files() == []

    def test_stops_on_a_transport_error(self, http_get):
        http_get.side_effect = requests.RequestException("connection refused")

        assert Indexer._fetch_all_files() == []


class TestReindex:
    """reindex crawls both services and hands the data to MeiliSearch."""

    def test_crawled_data_is_passed_to_meilisearch(self, http_get):
        search_service = MagicMock()
        search_service.reindex.return_value = {"status": "reindexed"}
        http_get.side_effect = [
            _response({"documents": [{"id": "d-1", "title": "Plan"}]}),
            _response({"documents": []}),
            _response({"files": [{"id": "f-1", "name": "report.pdf"}]}),
            _response({"files": []}),
        ]

        result = Indexer(search_service).reindex()

        assert result == {"status": "reindexed"}
        kwargs = search_service.reindex.call_args.kwargs
        assert [doc["id"] for doc in kwargs["documents"]] == ["d-1"]
        assert [file["id"] for file in kwargs["files"]] == ["f-1"]

    def test_unreachable_sources_still_trigger_an_empty_reindex(self, http_get):
        search_service = MagicMock()
        search_service.reindex.return_value = {"status": "reindexed"}
        http_get.side_effect = requests.RequestException("connection refused")

        Indexer(search_service).reindex()

        search_service.reindex.assert_called_once_with(documents=[], files=[])
