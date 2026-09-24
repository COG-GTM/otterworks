"""Tests for the search filter-expression builder and the filter query params."""

from datetime import datetime, timedelta, timezone

import pytest

from app.services.filters import (
    MIME_GROUPS,
    AppliedFilters,
    FilterError,
    build_filter_expression,
    files_only,
    parse_mime,
    parse_modified,
    to_epoch,
)

NOW = datetime(2026, 6, 15, 12, 0, 0, tzinfo=timezone.utc)


def _filter_string(**kwargs) -> str:
    parts, _ = build_filter_expression(**kwargs)
    return " AND ".join(parts)


class TestMimeFilter:
    def test_friendly_group_expands_to_mime_types(self):
        tokens, mime_types = parse_mime("spreadsheets")
        assert tokens == ["spreadsheets"]
        assert mime_types == list(MIME_GROUPS["spreadsheets"])

    def test_raw_mime_type_is_accepted(self):
        _, mime_types = parse_mime("application/pdf")
        assert mime_types == ["application/pdf"]

    def test_comma_list_is_or_ed(self):
        expression = _filter_string(mime="pdf,images")
        assert expression.startswith("(mime_type = ")
        assert " OR " in expression
        assert 'mime_type = "application/pdf"' in expression
        assert 'mime_type = "image/png"' in expression

    def test_unknown_group_is_rejected(self):
        with pytest.raises(FilterError):
            parse_mime("sheets")


class TestOwnerFilter:
    def test_owner_me_uses_caller(self):
        assert _filter_string(caller_id="u1", owner="me") == 'owner_id = "u1"'

    def test_owner_me_without_caller_is_rejected(self):
        with pytest.raises(FilterError):
            build_filter_expression(owner="me")

    def test_owner_shared_excludes_caller(self):
        assert _filter_string(caller_id="u1", owner="shared") == 'owner_id != "u1"'

    def test_explicit_owner_id(self):
        assert _filter_string(caller_id="u1", owner="u2") == 'owner_id = "u2"'

    def test_defaults_to_caller_scope(self):
        assert _filter_string(caller_id="u1") == 'owner_id = "u1"'


class TestModifiedFilter:
    @pytest.mark.parametrize(("preset", "days"), [("7d", 7), ("30d", 30)])
    def test_rolling_presets(self, preset, days):
        date_from, date_to = parse_modified(preset, now=NOW)
        assert date_from == NOW - timedelta(days=days)
        assert date_to is None

    def test_today_starts_at_midnight(self):
        date_from, date_to = parse_modified("today", now=NOW)
        assert date_from == NOW.replace(hour=0, minute=0, second=0, microsecond=0)
        assert date_to is None

    def test_year_starts_in_january(self):
        date_from, date_to = parse_modified("year", now=NOW)
        assert date_from == NOW.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        assert date_to is None

    def test_preset_builds_lower_bound(self):
        expression = _filter_string(modified="30d", now=NOW)
        assert expression == f"updated_at_ts >= {int((NOW - timedelta(days=30)).timestamp())}"

    def test_explicit_range_is_inclusive(self):
        date_from, date_to = parse_modified("2026-01-01..2026-01-31", now=NOW)
        assert date_from == datetime(2026, 1, 1, tzinfo=timezone.utc)
        assert date_to == datetime(2026, 2, 1, tzinfo=timezone.utc) - timedelta(microseconds=1)

    def test_range_accepts_fractional_seconds(self):
        date_from, date_to = parse_modified("2026-01-01T12:30:00.500Z..2026-02-01", now=NOW)
        assert date_from == datetime(2026, 1, 1, 12, 30, 0, 500000, tzinfo=timezone.utc)
        assert date_to == datetime(2026, 2, 2, tzinfo=timezone.utc) - timedelta(microseconds=1)

    def test_open_ended_range(self):
        date_from, date_to = parse_modified("2026-01-01..", now=NOW)
        assert date_from == datetime(2026, 1, 1, tzinfo=timezone.utc)
        assert date_to is None

    def test_reversed_range_is_rejected(self):
        with pytest.raises(FilterError):
            parse_modified("2026-02-01..2026-01-01", now=NOW)

    def test_unparseable_date_is_rejected(self):
        with pytest.raises(FilterError):
            parse_modified("last-tuesday", now=NOW)

    def test_empty_range_is_rejected(self):
        with pytest.raises(FilterError):
            parse_modified("..", now=NOW)


class TestFolderFilter:
    def test_folder_without_descendants(self):
        assert _filter_string(folder="f1") == 'folder_id = "f1"'

    def test_descendants_are_or_ed(self):
        expression = _filter_string(folder="f1", folder_ids=["f1", "f2", "f3"])
        assert expression == '(folder_id = "f1" OR folder_id = "f2" OR folder_id = "f3")'


class TestComposition:
    def test_type_filter_still_applies(self):
        assert _filter_string(doc_type="file") == 'type = "file"'

    def test_filters_are_and_ed(self):
        parts, applied = build_filter_expression(
            doc_type="file",
            caller_id="u1",
            mime="spreadsheets",
            modified="30d",
            folder="f1",
            folder_ids=["f1", "f2"],
            now=NOW,
        )
        assert parts[0] == 'type = "file"'
        assert 'owner_id = "u1"' in parts
        assert any(part.startswith("(mime_type") for part in parts)
        assert any(part.startswith("updated_at_ts >=") for part in parts)
        assert '(folder_id = "f1" OR folder_id = "f2")' in parts
        assert applied.to_dict()["mime"] == ["spreadsheets"]
        assert applied.to_dict()["folder_ids"] == ["f1", "f2"]

    def test_quotes_are_escaped(self):
        assert _filter_string(owner='u"1', caller_id="u1") == 'owner_id = "u\\"1"'

    def test_files_only_for_file_specific_filters(self):
        assert files_only(AppliedFilters(mime_types=["application/pdf"]))
        assert files_only(AppliedFilters(folder="f1"))
        assert not files_only(AppliedFilters(type="document"))


class TestToEpoch:
    def test_parses_iso(self):
        assert to_epoch("2026-06-15T12:00:00Z") == int(NOW.timestamp())

    def test_returns_none_for_garbage(self):
        assert to_epoch("not-a-date") is None
        assert to_epoch(None) is None


class TestFilterApi:
    def test_mime_and_modified_filter_is_sent_to_meilisearch(self, client, mock_meilisearch_client):
        response = client.get("/api/v1/search/?q=budget&mime=spreadsheets&modified=30d")
        assert response.status_code == 200
        params = mock_meilisearch_client.index.return_value.search.call_args[0][1]
        assert "mime_type = " in params["filter"]
        assert "updated_at_ts >= " in params["filter"]
        assert response.get_json()["filters"]["mime"] == ["spreadsheets"]

    def test_owner_shared_excludes_caller(self, client, mock_meilisearch_client):
        response = client.get(
            "/api/v1/search/?q=budget&owner=shared",
            headers={"X-User-ID": "user-1"},
        )
        assert response.status_code == 200
        assert 'owner_id != "user-1"' in mock_meilisearch_client.index.return_value.search.call_args[0][1]["filter"]

    def test_type_filter_still_supported(self, client, mock_meilisearch_client):
        response = client.get("/api/v1/search/?q=budget&type=file")
        assert response.status_code == 200
        assert 'type = "file"' in mock_meilisearch_client.index.return_value.search.call_args[0][1]["filter"]

    def test_invalid_date_range_returns_400(self, client):
        response = client.get("/api/v1/search/?q=budget&modified=2026-02-01..2026-01-01")
        assert response.status_code == 400
        assert "modified" in response.get_json()["error"]

    def test_invalid_mime_group_returns_400(self, client):
        response = client.get("/api/v1/search/?q=budget&mime=sheets")
        assert response.status_code == 400

    def test_response_echoes_applied_filters(self, client):
        response = client.get("/api/v1/search/?q=budget&mime=pdf&modified=today")
        assert response.status_code == 200
        filters = response.get_json()["filters"]
        assert filters["mime"] == ["pdf"]
        assert filters["modified"] == "today"
