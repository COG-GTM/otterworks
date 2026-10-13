"""search_reindex_weekly task logic against an in-memory MeiliSearch / service API fake."""

import pytest

from otterworks_etl.tasks import search as S


class FakeMeili:
    def __init__(self):
        self.indexes: dict[str, list] = {}
        self.settings: dict[str, dict] = {}
        self.swaps: list[tuple[str, str]] = []

    def __call__(self, method, endpoint, body=None, ok_404=False):
        parts = endpoint.strip("/").split("/")
        if method == "GET" and endpoint.startswith("/tasks?"):
            return {"results": [{"uid": i, "status": "succeeded",
                                 "details": {"swaps": [{"indexes": list(pair)}]}}
                                for i, pair in enumerate(self.swaps)]}
        if method == "GET" and parts[0] == "tasks":
            return {"status": "succeeded"}
        if method == "POST" and endpoint == "/indexes":
            self.indexes.setdefault(body["uid"], [])
        elif method == "DELETE":
            self.indexes.pop(parts[1], None)
        elif method == "PATCH":
            self.settings[parts[1]] = body
        elif method == "POST" and parts[-1] == "documents":
            self.indexes[parts[1]].extend(body)
        elif method == "GET" and parts[-1] == "stats":
            return {"numberOfDocuments": len(self.indexes[parts[1]])}
        elif method == "GET":
            return {"uid": parts[1]} if parts[1] in self.indexes else {}
        elif method == "POST" and endpoint == "/swap-indexes":
            a, b = body[0]["indexes"]
            self.indexes[a], self.indexes[b] = self.indexes[b], self.indexes[a]
            self.swaps.append((a, b))
        return {"taskUid": 1}


@pytest.fixture
def meili(monkeypatch):
    fake = FakeMeili()
    monkeypatch.setattr(S, "_call", fake)
    docs = [{"document_id": f"d{i}", "title": f"t{i}"} for i in range(5)]
    monkeypatch.setattr(S, "_fetch_page",
                        lambda kind, page, size: docs[(page - 1) * size: page * size])
    return fake


def test_blue_green_reindex(meili, cfg):
    cfg = dict(cfg, search_api_page_size=2)
    meili.indexes["documents"] = [{"id": "stale"}]
    prepared = S.prepare_staging_index("documents", cfg)
    assert prepared["staging"] == "documents_staging"
    assert meili.settings["documents_staging"] == S.T.INDEX_SETTINGS["documents"]
    assert meili.indexes["documents"] == [{"id": "stale"}]  # live untouched while building
    assert S.index_source("documents", cfg) == 5
    assert S.validate_staging("documents", cfg, 5) == 5
    S.swap_into_live("documents", cfg, prepared["prepared_at"])
    assert [d["id"] for d in meili.indexes["documents"]] == [f"d{i}" for i in range(5)]
    assert meili.indexes["documents_staging"] == [{"id": "stale"}]
    S.drop_previous_index("documents", cfg)
    assert "documents_staging" not in meili.indexes


def test_swap_retry_does_not_swap_back(meili, cfg):
    meili.indexes["documents"] = [{"id": "stale"}]
    prepared = S.prepare_staging_index("documents", cfg)
    S.index_source("documents", cfg)
    S.swap_into_live("documents", cfg, prepared["prepared_at"])
    S.swap_into_live("documents", cfg, prepared["prepared_at"])  # Airflow retry of the same try
    assert len(meili.swaps) == 1
    assert [d["id"] for d in meili.indexes["documents"]] == [f"d{i}" for i in range(5)]


def test_page_size_clamped_to_source_api_limit(meili, cfg, monkeypatch):
    sizes = []
    monkeypatch.setattr(S, "_fetch_page", lambda kind, page, size: sizes.append(size) or [])
    S.prepare_staging_index("files", cfg)
    S.index_source("files", dict(cfg, search_api_page_size=500))
    assert sizes == [S.SOURCE_API_MAX_PAGE_SIZE]


def test_validation_failure_keeps_live_index(meili, cfg):
    meili.indexes["documents"] = [{"id": "live"}]
    S.prepare_staging_index("documents", cfg)
    S.index_source("documents", cfg)
    with pytest.raises(ValueError, match="expected 6"):
        S.validate_staging("documents", cfg, 6)
    assert meili.indexes["documents"] == [{"id": "live"}]


def test_swap_creates_missing_live_index(meili, cfg):
    prepared = S.prepare_staging_index("files", cfg)
    S.swap_into_live("files", cfg, prepared["prepared_at"])
    assert "files" in meili.indexes
