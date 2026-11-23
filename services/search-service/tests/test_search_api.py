"""Tests for search API endpoints."""

from __future__ import annotations

import pytest


class TestSearchEndpoint:
    """Tests for GET /api/v1/search/."""

    def test_search_requires_query(self, client):
        """Search without 'q' returns 400."""
        response = client.get("/api/v1/search/")
        assert response.status_code == 400
        data = response.get_json()
        assert "error" in data

    def test_search_with_query(self, client, mock_meilisearch_client):
        """Search with a valid query returns results."""
        mock_index = mock_meilisearch_client.index.return_value
        mock_index.search.return_value = {
            "estimatedTotalHits": 1,
            "hits": [
                {
                    "id": "doc-1",
                    "title": "Test Document",
                    "content": "Some content here",
                    "type": "document",
                    "owner_id": "user-1",
                    "tags": ["test"],
                    "_formatted": {
                        "title": "Test Document",
                        "content": "Some <em>content</em> here",
                    },
                }
            ],
        }

        response = client.get("/api/v1/search/?q=test")
        assert response.status_code == 200
        data = response.get_json()
        assert data["total"] >= 1
        assert len(data["results"]) >= 1
        assert data["query"] == "test"

    def test_search_with_type_filter(self, client, mock_meilisearch_client):
        """Search with type filter."""
        mock_index = mock_meilisearch_client.index.return_value
        mock_index.search.return_value = {
            "estimatedTotalHits": 0,
            "hits": [],
        }

        response = client.get("/api/v1/search/?q=test&type=file")
        assert response.status_code == 200

    def test_search_pagination(self, client, mock_meilisearch_client):
        """Search with pagination params."""
        mock_index = mock_meilisearch_client.index.return_value
        mock_index.search.return_value = {
            "estimatedTotalHits": 0,
            "hits": [],
        }

        response = client.get("/api/v1/search/?q=test&page=2&size=10")
        assert response.status_code == 200
        data = response.get_json()
        assert data["page"] == 2
        assert data["page_size"] == 10

    def test_search_invalid_page(self, client):
        """Search with non-numeric page returns 400."""
        response = client.get("/api/v1/search/?q=test&page=not-a-number")
        assert response.status_code == 400


class TestSuggestEndpoint:
    """Tests for GET /api/v1/search/suggest."""

    def test_suggest_short_query(self, client):
        """Suggest with query shorter than 2 chars returns empty."""
        response = client.get("/api/v1/search/suggest?q=a")
        assert response.status_code == 200
        data = response.get_json()
        assert data["suggestions"] == []

    def test_suggest_with_prefix(self, client, mock_meilisearch_client):
        """Suggest with valid prefix returns suggestions."""
        mock_index = mock_meilisearch_client.index.return_value
        mock_index.search.return_value = {
            "estimatedTotalHits": 2,
            "hits": [
                {"title": "Test Doc 1"},
                {"title": "Test Doc 2"},
            ],
        }

        response = client.get("/api/v1/search/suggest?q=te", headers={"X-User-ID": "user-1"})
        assert response.status_code == 200
        data = response.get_json()
        assert len(data["suggestions"]) >= 1

    def test_suggest_filters_both_indices_by_caller(self, client, mock_meilisearch_client):
        """Every index queried for suggestions is filtered to the caller's owner_id."""
        mock_index = mock_meilisearch_client.index.return_value
        mock_index.search.return_value = {"estimatedTotalHits": 0, "hits": []}

        response = client.get("/api/v1/search/suggest?q=te", headers={"X-User-ID": "user-1"})
        assert response.status_code == 200
        assert mock_index.search.call_count == 2
        for call in mock_index.search.call_args_list:
            assert call.args[1]["filter"] == 'owner_id = "user-1"'

    def test_suggest_excludes_other_tenants(self, client, mock_meilisearch_client):
        """Another user's titles and file names never appear in the caller's suggestions."""
        records = [
            {"title": "Alice Roadmap", "owner_id": "alice"},
            {"name": "alice-roster.csv", "owner_id": "alice"},
            {"title": "Bob Acquisition Roadmap", "owner_id": "bob"},
            {"name": "bob-layoffs.xlsx", "owner_id": "bob"},
        ]

        def fake_search(prefix, params):
            owner = params["filter"].split('"')[1]
            hits = [{k: v for k, v in r.items() if k != "owner_id"} for r in records if r["owner_id"] == owner]
            return {"estimatedTotalHits": len(hits), "hits": hits}

        mock_meilisearch_client.index.return_value.search.side_effect = fake_search

        response = client.get("/api/v1/search/suggest?q=ro", headers={"X-User-ID": "alice"})
        assert response.status_code == 200
        suggestions = response.get_json()["suggestions"]
        assert "Bob Acquisition Roadmap" not in suggestions
        assert "bob-layoffs.xlsx" not in suggestions
        assert "Alice Roadmap" in suggestions

    def test_suggest_without_identity_returns_empty(self, client, mock_meilisearch_client):
        """Without X-User-ID the index is never queried and nothing is returned."""
        mock_index = mock_meilisearch_client.index.return_value
        mock_index.search.return_value = {"estimatedTotalHits": 1, "hits": [{"title": "Someone Else"}]}

        response = client.get("/api/v1/search/suggest?q=so")
        assert response.status_code == 200
        assert response.get_json()["suggestions"] == []
        mock_index.search.assert_not_called()

    def test_suggest_empty_query(self, client):
        """Suggest with empty query returns empty list."""
        response = client.get("/api/v1/search/suggest?q=")
        assert response.status_code == 200
        data = response.get_json()
        assert data["suggestions"] == []


class TestSuggestService:
    """MeiliSearchService.suggest owner scoping."""

    def test_suggest_without_owner_skips_search(self, meilisearch_service, mock_meilisearch_client):
        assert meilisearch_service.suggest("te", None) == []
        assert meilisearch_service.suggest("te", "   ") == []
        mock_meilisearch_client.index.return_value.search.assert_not_called()

    def test_suggest_escapes_owner_filter(self, meilisearch_service, mock_meilisearch_client):
        mock_index = mock_meilisearch_client.index.return_value
        meilisearch_service.suggest("te", 'x" OR owner_id != "y')
        for call in mock_index.search.call_args_list:
            assert call.args[1]["filter"] == 'owner_id = "x\\" OR owner_id != \\"y"'


class TestAdvancedSearchEndpoint:
    """Tests for POST /api/v1/search/advanced."""

    def test_advanced_search_with_filters(self, client, mock_meilisearch_client):
        """Advanced search with multiple filters."""
        mock_index = mock_meilisearch_client.index.return_value
        mock_index.search.return_value = {
            "estimatedTotalHits": 0,
            "hits": [],
        }

        response = client.post(
            "/api/v1/search/advanced",
            json={
                "q": "report",
                "type": "document",
                "owner_id": "user-1",
                "tags": ["finance"],
                "date_from": "2024-01-01",
                "date_to": "2024-12-31",
                "page": 1,
                "size": 10,
            },
        )
        assert response.status_code == 200
        data = response.get_json()
        assert "results" in data
        assert "total" in data

    def test_advanced_search_empty_body(self, client, mock_meilisearch_client):
        """Advanced search with empty body still works (match_all)."""
        mock_index = mock_meilisearch_client.index.return_value
        mock_index.search.return_value = {
            "estimatedTotalHits": 0,
            "hits": [],
        }

        response = client.post("/api/v1/search/advanced", json={})
        assert response.status_code == 200


class TestAnalyticsEndpoint:
    """Tests for GET /api/v1/search/analytics."""

    SERVICE_TOKEN = "svc-token-for-tests"

    @pytest.fixture(autouse=True)
    def _reset_analytics(self):
        from app.services import meilisearch_client as mc

        def clear():
            mc._search_analytics["queries"] = []
            mc._search_analytics["total_searches"] = 0
            mc._search_analytics["total_results"] = 0
            mc._owner_totals.clear()

        clear()
        yield
        clear()

    @pytest.fixture()
    def token_client(self, app):
        import dataclasses

        from app.config import AuthConfig

        app.config["APP_CONFIG"] = dataclasses.replace(
            app.config["APP_CONFIG"],
            auth=AuthConfig(service_token=self.SERVICE_TOKEN, require_auth=False),
        )
        return app.test_client()

    @staticmethod
    def _search(client, user_id, query, hits):
        from unittest.mock import patch as _patch

        service = client.application.config["SEARCH_SERVICE"]
        index = service.client.index.return_value
        with _patch.object(index, "search", return_value={"hits": [], "estimatedTotalHits": hits}):
            resp = client.get(f"/api/v1/search/?q={query}&type=document", headers={"X-User-ID": user_id})
        assert resp.status_code == 200

    def test_analytics_returns_data(self, client):
        """Analytics endpoint returns analytics data for an authenticated user."""
        response = client.get("/api/v1/search/analytics", headers={"X-User-ID": "user-1"})
        assert response.status_code == 200
        data = response.get_json()
        assert "popular_queries" in data
        assert "zero_result_queries" in data
        assert "total_searches" in data
        assert "avg_results_per_query" in data

    def test_analytics_rejects_anonymous_even_when_auth_disabled(self, client):
        """No service token and no gateway identity -> 403."""
        response = client.get("/api/v1/search/analytics")
        assert response.status_code == 403
        assert response.get_json() == {"error": "forbidden"}

    def test_user_only_sees_own_queries(self, client):
        """Another user's raw query strings and totals are never returned."""
        self._search(client, "victim", "acquisition-target-acme", 0)
        self._search(client, "victim", "q3-layoffs", 3)
        self._search(client, "attacker", "budget", 2)

        data = client.get("/api/v1/search/analytics", headers={"X-User-ID": "attacker"}).get_json()
        assert data["popular_queries"] == [{"query": "budget", "count": 1}]
        assert data["zero_result_queries"] == []
        assert data["total_searches"] == 1
        assert data["avg_results_per_query"] == 2.0
        body = str(data)
        assert "acquisition-target-acme" not in body
        assert "q3-layoffs" not in body

        victim = client.get("/api/v1/search/analytics", headers={"X-User-ID": "victim"}).get_json()
        assert {q["query"] for q in victim["popular_queries"]} == {"acquisition-target-acme", "q3-layoffs"}
        assert victim["zero_result_queries"] == [{"query": "acquisition-target-acme", "count": 1}]
        assert victim["total_searches"] == 2

    def test_advanced_search_is_scoped_too(self, client):
        """Queries recorded by /advanced are attributed to the caller."""
        client.post("/api/v1/search/advanced", json={"q": "secret-merger"}, headers={"X-User-ID": "victim"})
        data = client.get("/api/v1/search/analytics", headers={"X-User-ID": "attacker"}).get_json()
        assert data["total_searches"] == 0
        assert "secret-merger" not in str(data)

    def test_user_totals_survive_query_list_eviction(self, monkeypatch):
        """Other users' searches evicting old entries don't shrink a user's totals."""
        from app.services import meilisearch_client as mc

        monkeypatch.setattr(mc, "MAX_ANALYTICS_ENTRIES", 3)
        mc.record_search_analytics("mine", 4, "user-a")
        for i in range(5):
            mc.record_search_analytics(f"other-{i}", 1, "user-b")

        data = mc.get_search_analytics(owner_id="user-a")
        assert data.total_searches == 1
        assert data.avg_results_per_query == 4.0
        assert data.popular_queries == []

    def test_owner_counters_are_bounded(self, monkeypatch):
        from app.services import meilisearch_client as mc

        monkeypatch.setattr(mc, "MAX_ANALYTICS_OWNERS", 2)
        for owner in ("a", "b", "c"):
            mc.record_search_analytics("q", 1, owner)
        assert list(mc._owner_totals) == ["b", "c"]
        assert mc.get_search_analytics(owner_id="a").total_searches == 0

    def test_service_token_gets_global_analytics(self, token_client):
        """The internal service token still sees aggregate analytics across users."""
        self._search(token_client, "victim", "q3-layoffs", 0)
        self._search(token_client, "attacker", "budget", 2)

        resp = token_client.get(
            "/api/v1/search/analytics", headers={"Authorization": f"Bearer {self.SERVICE_TOKEN}"}
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["total_searches"] == 2
        assert {q["query"] for q in data["popular_queries"]} == {"q3-layoffs", "budget"}

    def test_wrong_service_token_is_scoped_to_user(self, token_client):
        """A bad bearer token falls back to the caller's own scope."""
        self._search(token_client, "victim", "q3-layoffs", 0)
        resp = token_client.get(
            "/api/v1/search/analytics",
            headers={"Authorization": "Bearer nope", "X-User-ID": "attacker"},
        )
        assert resp.status_code == 200
        assert resp.get_json()["total_searches"] == 0

    def test_wrong_service_token_without_user_is_rejected(self, token_client):
        resp = token_client.get("/api/v1/search/analytics", headers={"Authorization": "Bearer nope"})
        assert resp.status_code == 403
