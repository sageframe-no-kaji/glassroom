"""Tests for src/baserow_client.py — pure unit tests, no HTTP calls."""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import requests

from src.baserow_client import (
    COMPARABLE_FIELDS,
    BaserowClient,
    _extract_comparable,
    _parse_date_string,
)


# ---------------------------------------------------------------------------
# _parse_date_string (Baserow copy — same contract as db._parse_date_string)
# ---------------------------------------------------------------------------


class TestParseDateString:
    def test_none_returns_none(self):
        assert _parse_date_string(None) is None

    def test_empty_returns_none(self):
        assert _parse_date_string("") is None

    def test_no_due_date(self):
        assert _parse_date_string("No due date") is None

    def test_no_prefix_family(self):
        assert _parse_date_string("No assignment") is None

    def test_year_explicit(self):
        assert _parse_date_string("Dec 4, 2025") == "2025-12-04"

    def test_year_explicit_jan(self):
        assert _parse_date_string("Jan 1, 2026") == "2026-01-01"

    def test_short_date_no_year(self):
        result = _parse_date_string("Feb 9")
        assert result is not None
        assert result.endswith("-02-09")

    def test_posted_prefix(self):
        assert _parse_date_string("Posted Dec 4, 2025") == "2025-12-04"

    def test_edited_prefix(self):
        assert _parse_date_string("Edited Jan 15, 2026") == "2026-01-15"

    def test_updated_prefix(self):
        assert _parse_date_string("Updated Mar 3, 2025") == "2025-03-03"

    def test_unparseable(self):
        assert _parse_date_string("yesterday") is None

    def test_whitespace(self):
        assert _parse_date_string("   ") is None


# ---------------------------------------------------------------------------
# _extract_comparable
# ---------------------------------------------------------------------------


class TestExtractComparable:
    def test_plain_string_unchanged(self):
        assert _extract_comparable("Assigned") == "Assigned"

    def test_single_select_dict_extracts_value(self):
        assert _extract_comparable({"id": 5, "value": "Assignment", "color": "blue"}) == "Assignment"

    def test_integer_string_normalised(self):
        assert _extract_comparable("100") == 100

    def test_float_string_whole_number(self):
        assert _extract_comparable("75.0") == 75

    def test_float_string_fractional_unchanged(self):
        # Non-integer float should be left as-is (can't safely cast to int)
        result = _extract_comparable("75.5")
        assert result == "75.5"

    def test_none_unchanged(self):
        assert _extract_comparable(None) is None

    def test_bool_unchanged(self):
        assert _extract_comparable(True) is True

    def test_non_numeric_string_unchanged(self):
        assert _extract_comparable("Graded") == "Graded"


# ---------------------------------------------------------------------------
# BaserowClient._has_changes
# ---------------------------------------------------------------------------


def _make_existing_row(field_ids: dict[str, int], **overrides: Any) -> dict[str, Any]:
    """Build a fake Baserow row dict using field_{id} keys."""
    defaults: dict[str, Any] = {
        "assignment_url": "https://example.com/a/1",
        "class_name": "Math",
        "week_label": None,
        "title": "HW1",
        "description": "",
        "teacher": "Smith",
        "posted_date": None,
        "due_date": None,
        "points_possible": None,
        "category": None,
        "assignment_type": "Assignment",
        "status": "Assigned",
        "turn_in_required": True,
        "grade": None,
        "attachment_links": "",
        "attachment_titles": "",
    }
    defaults.update(overrides)
    return {f"field_{field_ids[k]}": v for k, v in defaults.items() if k in field_ids}


@pytest.fixture()
def field_ids() -> dict[str, int]:
    """Minimal field_ids mapping for all COMPARABLE_FIELDS + some extras."""
    keys = list(COMPARABLE_FIELDS) + [
        "first_seen_at", "last_modified_at", "scraped_at",
        "notes", "class_priority", "ai_summary",
    ]
    return {k: i + 1 for i, k in enumerate(sorted(keys))}


@pytest.fixture()
def client(monkeypatch) -> BaserowClient:
    """BaserowClient with auth mocked out."""
    with patch.object(BaserowClient, "__init__", lambda self: None):
        c = BaserowClient.__new__(BaserowClient)
    return c


class TestHasChanges:
    def test_identical_returns_false(self, client, field_ids):
        new_data: dict[str, Any] = {
            "assignment_url": "https://example.com/a/1",
            "class_name": "Math",
            "week_label": None,
            "title": "HW1",
            "description": "",
            "teacher": "Smith",
            "posted_date": None,
            "due_date": None,
            "points_possible": None,
            "category": None,
            "assignment_type": "Assignment",
            "status": "Assigned",
            "turn_in_required": True,
            "grade": None,
            "attachment_links": "",
            "attachment_titles": "",
        }
        existing = _make_existing_row(field_ids, **{k: v for k, v in new_data.items()})
        assert client._has_changes(new_data, existing, field_ids) is False

    def test_title_change_returns_true(self, client, field_ids):
        new_data: dict[str, Any] = {"title": "New Title"}
        existing = _make_existing_row(field_ids, title="Old Title")
        assert client._has_changes(new_data, existing, field_ids) is True

    def test_status_change_returns_true(self, client, field_ids):
        new_data: dict[str, Any] = {"status": "Graded"}
        existing = _make_existing_row(field_ids, status="Assigned")
        assert client._has_changes(new_data, existing, field_ids) is True

    def test_none_vs_empty_not_a_change(self, client, field_ids):
        new_data: dict[str, Any] = {"description": None}
        existing = _make_existing_row(field_ids, description="")
        assert client._has_changes(new_data, existing, field_ids) is False

    def test_single_select_dict_compared_by_value(self, client, field_ids):
        """Baserow returns single_select as dict; should compare by .value."""
        new_data: dict[str, Any] = {"assignment_type": "Assignment"}
        fid = field_ids.get("assignment_type")
        existing = {f"field_{fid}": {"id": 5, "value": "Assignment", "color": "blue"}}
        assert client._has_changes(new_data, existing, field_ids) is False

    def test_single_select_value_changed(self, client, field_ids):
        new_data: dict[str, Any] = {"assignment_type": "Quiz"}
        fid = field_ids.get("assignment_type")
        existing = {f"field_{fid}": {"id": 5, "value": "Assignment", "color": "blue"}}
        assert client._has_changes(new_data, existing, field_ids) is True

    def test_notes_not_in_comparable(self, client, field_ids):
        """Manual field 'notes' is not in COMPARABLE_FIELDS — must not trigger change."""
        new_data: dict[str, Any] = {"notes": "changed"}
        existing = _make_existing_row(field_ids)
        # notes is not in COMPARABLE_FIELDS so _has_changes should skip it
        assert client._has_changes(new_data, existing, field_ids) is False


# ---------------------------------------------------------------------------
# BaserowClient._prepare_field_data
# ---------------------------------------------------------------------------


class TestPrepareFieldData:
    def test_date_string_converted(self, client):
        prepared = client._prepare_field_data({
            "posted_date": "Dec 4, 2025",
            "due_date": "Jan 15, 2026",
        })
        assert prepared["posted_date"] == "2025-12-04"
        assert prepared["due_date"] == "2026-01-15"

    def test_no_due_date_becomes_none(self, client):
        prepared = client._prepare_field_data({"due_date": "No due date", "posted_date": None})
        assert prepared["due_date"] is None
        assert prepared["posted_date"] is None

    def test_points_possible_cast_to_int(self, client):
        prepared = client._prepare_field_data({"posted_date": None, "due_date": None, "points_possible": "100"})
        assert prepared["points_possible"] == 100
        assert isinstance(prepared["points_possible"], int)

    def test_points_possible_none_untouched(self, client):
        prepared = client._prepare_field_data({"posted_date": None, "due_date": None, "points_possible": None})
        assert prepared["points_possible"] is None

    def test_other_fields_passed_through(self, client):
        prepared = client._prepare_field_data({
            "posted_date": None,
            "due_date": None,
            "title": "My HW",
            "status": "Assigned",
        })
        assert prepared["title"] == "My HW"
        assert prepared["status"] == "Assigned"

    def test_original_dict_not_mutated(self, client):
        original = {"posted_date": "Dec 4, 2025", "due_date": None}
        client._prepare_field_data(original)
        assert original["posted_date"] == "Dec 4, 2025"


# ---------------------------------------------------------------------------
# BaserowClient._build_payload
# ---------------------------------------------------------------------------


class TestBuildPayload:
    def test_translates_names_to_field_ids(self, client, field_ids):
        payload = client._build_payload(
            {"title": "HW1", "status": "Assigned"},
            field_ids,
        )
        assert f"field_{field_ids['title']}" in payload
        assert f"field_{field_ids['status']}" in payload
        assert payload[f"field_{field_ids['title']}"] == "HW1"

    def test_skips_keys_not_in_field_ids(self, client, field_ids):
        payload = client._build_payload(
            {"title": "HW1", "unknown_key": "ignored"},
            field_ids,
        )
        assert "unknown_key" not in str(payload)
        assert f"field_{field_ids['title']}" in payload

    def test_empty_data_returns_empty_dict(self, client, field_ids):
        assert client._build_payload({}, field_ids) == {}


# ---------------------------------------------------------------------------
# BaserowClient.upsert — mocked HTTP
# ---------------------------------------------------------------------------


class TestUpsertHttp:
    """Test the three upsert paths with a fully mocked _request method."""

    @pytest.fixture()
    def _req(self, client):
        """Patch _request on the client instance and return the mock."""
        with patch.object(client, "_request") as mock_req:
            yield mock_req

    @pytest.fixture()
    def fids(self) -> dict[str, int]:
        keys = [
            "assignment_url", "class_name", "week_label", "title", "description",
            "teacher", "posted_date", "due_date", "points_possible", "category",
            "assignment_type", "status", "turn_in_required", "grade",
            "attachment_links", "attachment_titles", "scraped_at",
            "first_seen_at", "last_modified_at",
        ]
        return {k: i + 1 for i, k in enumerate(keys)}

    def _base_data(self) -> dict[str, Any]:
        return {
            "assignment_url": "https://example.com/a/1",
            "class_name": "Math",
            "week_label": None,
            "title": "HW1",
            "description": "",
            "teacher": "Smith",
            "posted_date": None,
            "due_date": None,
            "points_possible": None,
            "category": None,
            "assignment_type": "Assignment",
            "status": "Assigned",
            "turn_in_required": True,
            "grade": None,
            "attachment_links": "",
            "attachment_titles": "",
        }

    def test_insert_when_no_existing_row(self, client, _req, fids):
        _req.return_value.json.return_value = {"count": 0, "results": []}
        result = client.upsert(self._base_data(), table_id=1, field_ids=fids)
        assert result == "inserted"
        # GET then POST
        assert _req.call_count == 2
        assert _req.call_args_list[1][0][0] == "POST"

    def test_skip_when_no_changes(self, client, _req, fids):
        data = self._base_data()
        existing = {f"field_{fids[k]}": v for k, v in data.items() if k in fids}
        existing["id"] = 42
        _req.return_value.json.return_value = {"count": 1, "results": [existing]}
        result = client.upsert(data, table_id=1, field_ids=fids)
        assert result == "skipped"
        # Only the GET
        assert _req.call_count == 1

    def test_update_when_title_changed(self, client, _req, fids):
        data = self._base_data()
        existing = {f"field_{fids[k]}": v for k, v in data.items() if k in fids}
        existing["id"] = 42
        existing[f"field_{fids['title']}"] = "Old Title"
        _req.return_value.json.return_value = {"count": 1, "results": [existing]}
        result = client.upsert(data, table_id=1, field_ids=fids)
        assert result == "updated"
        # GET then PATCH
        assert _req.call_count == 2
        assert _req.call_args_list[1][0][0] == "PATCH"

    def test_update_does_not_send_first_seen_at(self, client, _req, fids):
        """first_seen_at must never be in the PATCH payload."""
        data = self._base_data()
        existing = {f"field_{fids[k]}": v for k, v in data.items() if k in fids}
        existing["id"] = 42
        existing[f"field_{fids['title']}"] = "Old Title"
        _req.return_value.json.return_value = {"count": 1, "results": [existing]}
        client.upsert(data, table_id=1, field_ids=fids)
        patch_call = _req.call_args_list[1]
        patch_payload = patch_call[1]["json"]
        assert f"field_{fids['first_seen_at']}" not in patch_payload


# ---------------------------------------------------------------------------
# BaserowClient._set_token
# ---------------------------------------------------------------------------


class TestSetToken:
    def test_stores_token_and_sets_header(self, client):
        mock_session = MagicMock()
        client.session = mock_session
        from src.baserow_client import BaserowClient
        BaserowClient._set_token(client, "abc123")
        assert client.token == "abc123"
        mock_session.headers.__setitem__.assert_called_with("Authorization", "JWT abc123")


# ---------------------------------------------------------------------------
# BaserowClient._get_token
# ---------------------------------------------------------------------------


class TestGetToken:
    def test_returns_cached_token_if_present(self, client):
        with patch("src.baserow_client.dotenv_values", return_value={"BASEROW_TOKEN": "cached"}):
            token = client._get_token()
        assert token == "cached"

    def test_falls_back_to_auth_when_no_token(self, client):
        with (
            patch("src.baserow_client.dotenv_values", return_value={}),
            patch.object(client, "_auth_with_credentials", return_value="fresh") as mock_auth,
        ):
            token = client._get_token()
        assert token == "fresh"
        mock_auth.assert_called_once()

    def test_falls_back_to_auth_when_token_empty(self, client):
        with (
            patch("src.baserow_client.dotenv_values", return_value={"BASEROW_TOKEN": "  "}),
            patch.object(client, "_auth_with_credentials", return_value="fresh"),
        ):
            token = client._get_token()
        assert token == "fresh"


# ---------------------------------------------------------------------------
# BaserowClient._request
# ---------------------------------------------------------------------------


@pytest.fixture()
def client_with_session(client):
    """Client fixture with a mocked requests.Session attached."""
    mock_session = MagicMock()
    client.session = mock_session
    return client


class TestRequest:
    def test_returns_response_on_ok(self, client_with_session):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.ok = True
        client_with_session.session.request.return_value = mock_resp
        result = client_with_session._request("GET", "/api/test/")
        assert result is mock_resp

    def test_raises_on_non_ok_response(self, client_with_session):
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.ok = False
        mock_resp.reason = "Not Found"
        mock_resp.text = "row not found"
        client_with_session.session.request.return_value = mock_resp
        import requests as req_lib
        with pytest.raises(req_lib.HTTPError):
            client_with_session._request("GET", "/api/test/")

    def test_retries_on_401_then_succeeds(self, client_with_session):
        unauth = MagicMock()
        unauth.status_code = 401
        unauth.ok = True  # ok check comes after second retry; set False for 2nd if needed

        ok_resp = MagicMock()
        ok_resp.status_code = 200
        ok_resp.ok = True

        client_with_session.session.request.side_effect = [unauth, ok_resp]
        with patch.object(client_with_session, "_auth_with_credentials", return_value="newtoken"):
            with patch.object(client_with_session, "_set_token"):
                result = client_with_session._request("GET", "/api/test/")
        assert result is ok_resp

    def test_exits_on_double_401(self, client_with_session):
        unauth = MagicMock()
        unauth.status_code = 401
        unauth.ok = False

        client_with_session.session.request.return_value = unauth
        with patch.object(client_with_session, "_auth_with_credentials", return_value="newtoken"):
            with patch.object(client_with_session, "_set_token"):
                with pytest.raises(SystemExit):
                    client_with_session._request("GET", "/api/test/")


# ---------------------------------------------------------------------------
# BaserowClient.get_all_rows
# ---------------------------------------------------------------------------


class TestGetAllRows:
    def test_single_page(self, client):
        page_data = {"results": [{"id": 1}, {"id": 2}], "next": None}
        with patch.object(client, "_request") as mock_req:
            mock_req.return_value.json.return_value = page_data
            rows = client.get_all_rows(table_id=5)
        assert rows == [{"id": 1}, {"id": 2}]
        mock_req.assert_called_once()

    def test_multiple_pages(self, client):
        page1 = {"results": [{"id": 1}], "next": "http://example.com/?page=2"}
        page2 = {"results": [{"id": 2}], "next": None}
        with patch.object(client, "_request") as mock_req:
            mock_req.return_value.json.side_effect = [page1, page2]
            rows = client.get_all_rows(table_id=5)
        assert rows == [{"id": 1}, {"id": 2}]
        assert mock_req.call_count == 2


# ---------------------------------------------------------------------------
# BaserowClient.__init__
# ---------------------------------------------------------------------------


class TestInit:
    def test_init_creates_session_and_sets_token(self):
        mock_session = MagicMock()
        with (
            patch("src.baserow_client.requests.Session", return_value=mock_session),
            patch.object(BaserowClient, "_get_token", return_value="mytoken"),
            patch.object(BaserowClient, "_set_token") as mock_set_token,
        ):
            BaserowClient()
        mock_session.headers.update.assert_called_once()
        mock_set_token.assert_called_once_with("mytoken")


# ---------------------------------------------------------------------------
# BaserowClient._auth_with_credentials
# ---------------------------------------------------------------------------


class TestAuthWithCredentials:
    def _make_client(self) -> BaserowClient:
        with patch.object(BaserowClient, "__init__", lambda self: None):
            c = BaserowClient.__new__(BaserowClient)
        c.session = MagicMock()
        return c

    def test_exits_when_no_credentials(self):
        c = self._make_client()
        with (
            patch("src.baserow_client.dotenv_values", return_value={}),
            pytest.raises(SystemExit),
        ):
            c._auth_with_credentials()

    def test_returns_token_on_success(self):
        c = self._make_client()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"token": "jwt_token_abc"}
        with (
            patch("src.baserow_client.dotenv_values", return_value={
                "BASEROW_EMAIL": "user@example.com",
                "BASEROW_PASSWORD": "secret",
            }),
            patch("src.baserow_client.requests.post", return_value=mock_resp),
            patch("src.baserow_client.set_key"),
        ):
            token = c._auth_with_credentials()
        assert token == "jwt_token_abc"

    def test_exits_on_http_error(self):
        c = self._make_client()
        bad_resp = MagicMock()
        bad_resp.status_code = 401
        bad_resp.text = "unauthorized"
        http_err = requests.HTTPError(response=bad_resp)
        mock_post_resp = MagicMock()
        mock_post_resp.raise_for_status.side_effect = http_err
        with (
            patch("src.baserow_client.dotenv_values", return_value={
                "BASEROW_EMAIL": "user@example.com",
                "BASEROW_PASSWORD": "secret",
            }),
            patch("src.baserow_client.requests.post", return_value=mock_post_resp),
            pytest.raises(SystemExit),
        ):
            c._auth_with_credentials()

    def test_exits_on_connection_error(self):
        c = self._make_client()
        with (
            patch("src.baserow_client.dotenv_values", return_value={
                "BASEROW_EMAIL": "user@example.com",
                "BASEROW_PASSWORD": "secret",
            }),
            patch("src.baserow_client.requests.post", side_effect=requests.ConnectionError("refused")),
            pytest.raises(SystemExit),
        ):
            c._auth_with_credentials()
