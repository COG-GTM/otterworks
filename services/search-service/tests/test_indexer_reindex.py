"""Tests for the Indexer's full-reindex crawl of the source services."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from app.services.indexer import Indexer


def _response(payload: dict, status_code: int = 200) -> MagicMock:
    """Build a stub requests.Response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = payload
    return resp


@pytest.fixture()
def indexer() -> Indexer:
    """An Indexer over a mock MeiliSearchService."""
    return Indexer(MagicMock())


class TestFetchAllDocuments:
    """Tests for Indexer._fetch_all_documents."""

    def test_paginates_until_an_empty_page(self):
        """Pages are fetched until the service returns no more items."""
        pages = [
            _response({"documents": [{"id": "d-1", "title": "One"}]}),
            _response({"documents": [{"id": "d-2", "title": "Two"}]}),
            _response({"documents": []}),
        ]

        with patch("app.services.indexer.requests.get", side_effect=pages) as get:
            docs = Indexer._fetch_all_documents()

        assert [d["id"] for d in docs] == ["d-1", "d-2"]
        assert all(d["type"] == "document" for d in docs)
        assert [call.kwargs["params"]["page"] for call in get.call_args_list] == [1, 2, 3]

    @pytest.mark.parametrize("key", ["documents", "items", "data"])
    def test_accepts_each_supported_list_key(self, key):
        """The document-service list may be keyed documents/items/data."""
        pages = [_response({key: [{"id": "d-1", "title": "One"}]}), _response({key: []})]

        with patch("app.services.indexer.requests.get", side_effect=pages):
            docs = Indexer._fetch_all_documents()

        assert len(docs) == 1

    def test_defaults_missing_fields(self):
        """Sparse upstream records are normalized to the index schema."""
        pages = [_response({"documents": [{}]}), _response({"documents": []})]

        with patch("app.services.indexer.requests.get", side_effect=pages):
            docs = Indexer._fetch_all_documents()

        assert docs == [
            {
                "id": "",
                "title": "",
                "content": "",
                "owner_id": "",
                "tags": [],
                "created_at": None,
                "updated_at": None,
                "type": "document",
            }
        ]

    def test_non_200_response_stops_the_crawl(self):
        """An error status ends the crawl instead of looping forever."""
        with patch("app.services.indexer.requests.get", return_value=_response({}, 503)):
            assert Indexer._fetch_all_documents() == []

    def test_request_exception_stops_the_crawl(self):
        """A network failure ends the crawl with whatever was collected."""
        pages = [
            _response({"documents": [{"id": "d-1", "title": "One"}]}),
            requests.RequestException("connection refused"),
        ]

        with patch("app.services.indexer.requests.get", side_effect=pages):
            docs = Indexer._fetch_all_documents()

        assert [d["id"] for d in docs] == ["d-1"]


class TestFetchAllFiles:
    """Tests for Indexer._fetch_all_files."""

    def test_paginates_until_an_empty_page(self):
        pages = [
            _response({"files": [{"id": "f-1", "name": "a.txt"}]}),
            _response({"files": []}),
        ]

        with patch("app.services.indexer.requests.get", side_effect=pages) as get:
            files = Indexer._fetch_all_files()

        assert [f["id"] for f in files] == ["f-1"]
        assert files[0]["type"] == "file"
        assert [call.kwargs["params"]["page"] for call in get.call_args_list] == [1, 2]

    def test_camel_case_upstream_fields_are_normalized(self):
        """file-service camelCase keys map onto the index schema."""
        pages = [
            _response(
                {
                    "files": [
                        {
                            "id": "f-1",
                            "name": "a.txt",
                            "mimeType": "text/plain",
                            "ownerId": "u-1",
                            "folderId": "fold-1",
                            "sizeBytes": 12,
                            "createdAt": "2026-01-01",
                            "updatedAt": "2026-01-02",
                        }
                    ]
                }
            ),
            _response({"files": []}),
        ]

        with patch("app.services.indexer.requests.get", side_effect=pages):
            files = Indexer._fetch_all_files()

        assert files[0] == {
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
        }

    def test_non_200_response_stops_the_crawl(self):
        with patch("app.services.indexer.requests.get", return_value=_response({}, 500)):
            assert Indexer._fetch_all_files() == []

    def test_request_exception_stops_the_crawl(self):
        with patch(
            "app.services.indexer.requests.get",
            side_effect=requests.RequestException("timeout"),
        ):
            assert Indexer._fetch_all_files() == []


class TestReindex:
    """Tests for Indexer.reindex."""

    def test_reindex_passes_crawled_data_to_meilisearch(self, indexer):
        """Documents and files are crawled once and handed to the search service."""
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
