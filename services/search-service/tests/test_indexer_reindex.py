"""Tests for the Indexer's crawl-and-reindex paths and event dispatch."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from app.services.indexer import Indexer


@pytest.fixture()
def indexer() -> Indexer:
    """An Indexer over a mocked MeiliSearchService."""
    return Indexer(MagicMock())


def _response(payload, status: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = payload
    return resp


class TestFetchAllDocuments:
    """Tests for Indexer._fetch_all_documents."""

    def test_pages_until_an_empty_page_is_returned(self):
        """Pagination continues while the service keeps returning documents."""
        pages = [
            _response({"documents": [{"id": "d-1", "title": "One"}]}),
            _response({"documents": []}),
        ]

        with patch("app.services.indexer.requests.get", side_effect=pages) as get:
            docs = Indexer._fetch_all_documents()

        assert [d["id"] for d in docs] == ["d-1"]
        assert docs[0]["type"] == "document"
        assert [c.kwargs["params"]["page"] for c in get.call_args_list] == [1, 2]

    @pytest.mark.parametrize("key", ["documents", "items", "data"])
    def test_accepts_any_of_the_supported_envelope_keys(self, key):
        """The document-service list key varies by version; all are handled."""
        pages = [_response({key: [{"id": "d-1"}]}), _response({key: []})]

        with patch("app.services.indexer.requests.get", side_effect=pages):
            docs = Indexer._fetch_all_documents()

        assert len(docs) == 1

    def test_stops_on_a_non_200_response(self):
        """An error status ends the crawl instead of looping forever."""
        with patch("app.services.indexer.requests.get", return_value=_response({}, 503)):
            assert Indexer._fetch_all_documents() == []

    def test_stops_on_a_network_error(self):
        """A connection failure ends the crawl and yields what was collected."""
        with patch(
            "app.services.indexer.requests.get",
            side_effect=requests.RequestException("unreachable"),
        ):
            assert Indexer._fetch_all_documents() == []


class TestFetchAllFiles:
    """Tests for Indexer._fetch_all_files."""

    def test_maps_camel_case_file_fields(self):
        """file-service camelCase metadata is normalized for the index."""
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

        assert files == [
            {
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
        ]

    def test_stops_on_a_non_200_response(self):
        """An error status ends the file crawl."""
        with patch("app.services.indexer.requests.get", return_value=_response({}, 500)):
            assert Indexer._fetch_all_files() == []

    def test_stops_on_a_network_error(self):
        """A connection failure ends the file crawl."""
        with patch(
            "app.services.indexer.requests.get",
            side_effect=requests.RequestException("unreachable"),
        ):
            assert Indexer._fetch_all_files() == []


class TestReindex:
    """Tests for Indexer.reindex."""

    def test_reindex_feeds_crawled_data_to_meilisearch(self, indexer):
        """Documents and files fetched from source services are bulk-indexed."""
        documents = [{"id": "d-1"}]
        files = [{"id": "f-1"}]
        indexer.search.reindex.return_value = {"status": "reindexed"}

        with patch.object(Indexer, "_fetch_all_documents", return_value=documents), patch.object(
            Indexer, "_fetch_all_files", return_value=files
        ):
            result = indexer.reindex()

        indexer.search.reindex.assert_called_once_with(documents=documents, files=files)
        assert result == {"status": "reindexed"}


class TestProcessEvent:
    """Tests for Indexer.process_event dispatch."""

    def test_index_document_action(self, indexer):
        """index_document events are validated and indexed as documents."""
        result = indexer.process_event(
            {"action": "index_document", "data": {"id": "d-1", "title": "T"}}
        )
        assert result == {"status": "indexed", "id": "d-1", "type": "document"}

    def test_index_file_action(self, indexer):
        """index_file events are validated and indexed as files."""
        result = indexer.process_event(
            {"action": "index_file", "data": {"id": "f-1", "name": "a.txt"}}
        )
        assert result == {"status": "indexed", "id": "f-1", "type": "file"}

    def test_delete_action_defaults_to_the_document_index(self, indexer):
        """A delete event without a type removes a document."""
        indexer.search.delete_document.return_value = True

        result = indexer.process_event({"action": "delete", "data": {"id": "d-1"}})

        indexer.search.delete_document.assert_called_once_with("document", "d-1")
        assert result == {"status": "deleted", "id": "d-1", "type": "document"}

    def test_delete_action_reports_missing_documents(self, indexer):
        """Deleting something absent from the index reports not_found."""
        indexer.search.delete_document.return_value = False

        result = indexer.process_event(
            {"action": "delete", "data": {"id": "f-9", "type": "file"}}
        )

        assert result == {"status": "not_found", "id": "f-9", "type": "file"}

    def test_unknown_action_is_ignored(self, indexer):
        """An unrecognised action is logged and dropped."""
        assert indexer.process_event({"action": "explode", "data": {}}) is None
        indexer.search.index_document.assert_not_called()

    def test_event_without_an_action_is_ignored(self, indexer):
        """An event with no action key is a no-op."""
        assert indexer.process_event({}) is None
