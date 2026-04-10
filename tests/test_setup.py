"""Tests for setup routes and login/session/classes API endpoints."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from flask import Flask
from sqlalchemy import create_engine

from src.db import get_session, init_db
from src.models import SelectedClass

_PROJECT_ROOT = Path(__file__).parent.parent


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _make_app(engine: object) -> Flask:
    from src.routes.api import bp as api_bp
    from src.routes.dashboard import bp as dashboard_bp
    from src.routes.setup import bp as setup_bp

    template_dir = str(_PROJECT_ROOT / "src" / "templates")
    static_dir = str(_PROJECT_ROOT / "src" / "static")
    a = Flask(__name__, template_folder=template_dir, static_folder=static_dir)
    a.config["DB_ENGINE"] = engine
    a.register_blueprint(dashboard_bp)
    a.register_blueprint(api_bp)
    a.register_blueprint(setup_bp)
    return a


@pytest.fixture()
def engine(tmp_path: Path):
    eng = create_engine("sqlite:///:memory:")
    init_db(eng)
    return eng


@pytest.fixture()
def app(engine):
    flask_app = _make_app(engine)
    flask_app.config["TESTING"] = True
    return flask_app


@pytest.fixture()
def client(app):
    return app.test_client()


def _add_selected_class(engine, name: str = "Math", url: str = "https://classroom.google.com/c/abc") -> None:
    with get_session(engine) as s:
        s.add(SelectedClass(name=name, course_url=url, active=True))


# ---------------------------------------------------------------------------
# GET /setup
# ---------------------------------------------------------------------------


class TestSetupPage:
    def test_shows_setup_when_no_classes(self, client):
        resp = client.get("/setup")
        assert resp.status_code == 200
        assert b"Step 1" in resp.data

    def test_shows_step3_when_classes_exist(self, client, engine):
        """When classes are already configured, /setup renders step 3 directly."""
        _add_selected_class(engine)
        resp = client.get("/setup")
        assert resp.status_code == 200
        assert b"has_classes" not in resp.data  # Jinja resolved it
        assert b"Scrape assignments" in resp.data

    def test_setup_page_contains_login_button(self, client):
        resp = client.get("/setup")
        assert b"btn-login" in resp.data

    def test_setup_page_contains_step_indicators(self, client):
        resp = client.get("/setup")
        assert b"Select classes" in resp.data
        assert b"First scrape" in resp.data or b"first scrape" in resp.data.lower()


# ---------------------------------------------------------------------------
# GET /api/session/status
# ---------------------------------------------------------------------------


class TestSessionStatus:
    def test_returns_json(self, client):
        resp = client.get("/api/session/status")
        assert resp.status_code == 200
        assert resp.is_json

    def test_valid_false_when_no_session_dir(self, client, tmp_path):
        fake_dir = tmp_path / "nosuch"
        with patch("src.routes.api.SESSION_DIR", fake_dir):
            resp = client.get("/api/session/status")
        data = resp.get_json()
        assert data["valid"] is False

    def test_valid_false_when_session_dir_empty(self, client, tmp_path):
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        with patch("src.routes.api.SESSION_DIR", empty_dir):
            resp = client.get("/api/session/status")
        data = resp.get_json()
        assert data["valid"] is False

    def test_valid_true_when_session_dir_has_files(self, client, tmp_path):
        session_dir = tmp_path / "session"
        session_dir.mkdir()
        (session_dir / "Default").mkdir()  # mimic Chromium profile dir
        with patch("src.routes.api.SESSION_DIR", session_dir):
            resp = client.get("/api/session/status")
        data = resp.get_json()
        assert data["valid"] is True

    def test_returns_path_field(self, client, tmp_path):
        session_dir = tmp_path / "sess"
        with patch("src.routes.api.SESSION_DIR", session_dir):
            resp = client.get("/api/session/status")
        data = resp.get_json()
        assert "path" in data


# ---------------------------------------------------------------------------
# POST /api/login + GET /api/login/status
# ---------------------------------------------------------------------------


class TestLogin:
    def test_login_starts_and_returns_ok(self, client):
        # We mock do_login + discover_classes so no Playwright is launched
        with (
            patch("src.classroom.do_login"),
            patch("src.classroom.discover_classes", return_value=[]),
        ):
            resp = client.post("/api/login")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data.get("ok") is True

    def test_login_status_returns_json(self, client):
        resp = client.get("/api/login/status")
        assert resp.status_code == 200
        assert resp.is_json

    def test_login_status_initial_idle(self, client):
        # Reset the module-level state to idle so tests don't bleed
        import src.routes.api as api_mod

        with api_mod._login_lock:
            api_mod._login_state["status"] = "idle"
            api_mod._login_state["classes"] = []
            api_mod._login_state["error"] = None

        resp = client.get("/api/login/status")
        data = resp.get_json()
        assert data["status"] == "idle"

    def test_login_conflict_when_already_running(self, client):
        import src.routes.api as api_mod

        with api_mod._login_lock:
            api_mod._login_state["status"] = "running"

        try:
            resp = client.post("/api/login")
            assert resp.status_code == 409
        finally:
            with api_mod._login_lock:
                api_mod._login_state["status"] = "idle"

    def test_login_transitions_to_done(self, client):
        """Verify the background thread sets status=done after login + discovery."""
        import time
        import src.routes.api as api_mod

        # Reset state
        with api_mod._login_lock:
            api_mod._login_state["status"] = "idle"
            api_mod._login_state["classes"] = []

        with (
            patch("src.classroom.do_login"),
            patch("src.classroom.discover_classes", return_value=[
                {"name": "Math", "course_url": "https://classroom.google.com/c/1"}
            ]),
        ):
            client.post("/api/login")
            # Small wait for the daemon thread to finish
            for _ in range(20):
                time.sleep(0.1)
                with api_mod._login_lock:
                    if api_mod._login_state["status"] != "running":
                        break

        with api_mod._login_lock:
            assert api_mod._login_state["status"] == "done"
            assert len(api_mod._login_state["classes"]) == 1


# ---------------------------------------------------------------------------
# GET /api/classes/available
# ---------------------------------------------------------------------------


class TestClassesAvailable:
    def test_returns_empty_list_initially(self, client):
        import src.routes.api as api_mod

        with api_mod._login_lock:
            api_mod._login_state["classes"] = []

        resp = client.get("/api/classes/available")
        assert resp.status_code == 200
        assert resp.get_json() == []

    def test_returns_classes_after_login(self, client):
        import src.routes.api as api_mod

        with api_mod._login_lock:
            api_mod._login_state["classes"] = [
                {"name": "Biology", "course_url": "https://classroom.google.com/c/bio"},
            ]

        resp = client.get("/api/classes/available")
        data = resp.get_json()
        assert len(data) == 1
        assert data[0]["name"] == "Biology"


# ---------------------------------------------------------------------------
# POST /api/classes/save
# ---------------------------------------------------------------------------


class TestClassesSave:
    def test_save_returns_ok(self, client, engine):
        payload = {
            "classes": [
                {"name": "Math", "course_url": "https://classroom.google.com/c/1"},
                {"name": "Science", "course_url": "https://classroom.google.com/c/2"},
            ]
        }
        resp = client.post("/api/classes/save", json=payload)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True
        assert data["saved"] == 2

    def test_save_persists_to_db(self, client, engine):
        payload = {
            "classes": [
                {"name": "History", "course_url": "https://classroom.google.com/c/3"},
            ]
        }
        client.post("/api/classes/save", json=payload)
        with get_session(engine) as s:
            count = s.query(SelectedClass).count()
        assert count == 1

    def test_save_replaces_existing(self, client, engine):
        """Saving a new list replaces all prior SelectedClass records."""
        _add_selected_class(engine, name="Old Class")
        payload = {
            "classes": [
                {"name": "New Class", "course_url": "https://classroom.google.com/c/new"},
            ]
        }
        client.post("/api/classes/save", json=payload)
        with get_session(engine) as s:
            names = [r.name for r in s.query(SelectedClass).all()]
        assert names == ["New Class"]

    def test_save_empty_list_returns_400(self, client):
        resp = client.post("/api/classes/save", json={"classes": []})
        assert resp.status_code == 400

    def test_save_no_body_returns_400(self, client):
        resp = client.post(
            "/api/classes/save",
            data="",
            content_type="application/json",
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# POST /api/reset
# ---------------------------------------------------------------------------


class TestReset:
    def test_reset_returns_ok(self, client):
        resp = client.post("/api/reset")
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True

    def test_reset_clears_selected_classes(self, client, engine):
        _add_selected_class(engine)
        client.post("/api/reset")
        with get_session(engine) as s:
            assert s.query(SelectedClass).count() == 0

    def test_reset_clears_scrape_state(self, client):
        import src.routes.api as api_mod

        with api_mod._scrape_lock:
            api_mod._scrape_state["running"] = True
            api_mod._scrape_state["progress"] = {"status": "done"}

        client.post("/api/reset")

        with api_mod._scrape_lock:
            assert api_mod._scrape_state["running"] is False
            assert api_mod._scrape_state["progress"] is None

    def test_reset_clears_login_state(self, client):
        import src.routes.api as api_mod

        with api_mod._login_lock:
            api_mod._login_state["status"] = "done"
            api_mod._login_state["classes"] = [{"name": "Math", "course_url": "x"}]

        client.post("/api/reset")

        with api_mod._login_lock:
            assert api_mod._login_state["status"] == "idle"
            assert api_mod._login_state["classes"] == []

    def test_reset_removes_downloads_dir(self, client, tmp_path):
        from unittest.mock import patch

        dl_dir = tmp_path / "downloads"
        dl_dir.mkdir()
        (dl_dir / "somefile.pdf").write_text("data")

        with patch("src.downloader.DOWNLOADS_DIR", dl_dir):
            resp = client.post("/api/reset")

        assert resp.status_code == 200
        assert not dl_dir.exists()


# ---------------------------------------------------------------------------
# _infer_school_year helper
# ---------------------------------------------------------------------------


class TestInferSchoolYear:
    def _call(self, name: str) -> str:
        from src.classroom import _infer_school_year
        return _infer_school_year(name)

    def test_two_consecutive_years(self):
        assert self._call("ELA 2024-2025") == "2024-2025"

    def test_two_years_not_adjacent_uses_pair(self):
        assert self._call("Science 2023 2024") == "2023-2024"

    def test_single_year_produces_range(self):
        result = self._call("Math 2024")
        assert result == "2024-2025"

    def test_no_year_returns_other(self):
        assert self._call("AP Biology Honors") == "Other"

    def test_parens_year(self):
        result = self._call("US History (2023)")
        assert result == "2023-2024"


# ---------------------------------------------------------------------------
# POST /api/classes/discover-archived  &  GET /api/classes/discover-archived/status
# ---------------------------------------------------------------------------


class TestDiscoverArchived:
    def test_starts_discovery_returns_ok(self, client):
        import src.routes.api as api_mod

        with api_mod._archived_lock:
            api_mod._archived_state["status"] = "idle"

        with patch("src.classroom.discover_archived_classes", return_value=[]):
            resp = client.post("/api/classes/discover-archived")

        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True

    def test_conflict_when_already_running(self, client):
        import src.routes.api as api_mod

        with api_mod._archived_lock:
            api_mod._archived_state["status"] = "running"
        try:
            resp = client.post("/api/classes/discover-archived")
            assert resp.status_code == 409
        finally:
            with api_mod._archived_lock:
                api_mod._archived_state["status"] = "idle"

    def test_status_returns_json(self, client):
        resp = client.get("/api/classes/discover-archived/status")
        assert resp.status_code == 200
        assert resp.is_json

    def test_status_reflects_state(self, client):
        import src.routes.api as api_mod

        with api_mod._archived_lock:
            api_mod._archived_state["status"] = "done"
            api_mod._archived_state["classes"] = [
                {"name": "Old Class", "course_url": "https://classroom.google.com/c/old", "school_year": "2023-2024"}
            ]

        resp = client.get("/api/classes/discover-archived/status")
        data = resp.get_json()
        assert data["status"] == "done"
        assert len(data["classes"]) == 1

    def test_discovery_transitions_to_done(self, client):
        import time
        import src.routes.api as api_mod

        with api_mod._archived_lock:
            api_mod._archived_state["status"] = "idle"
            api_mod._archived_state["classes"] = []

        archived = [{"name": "Old Math", "course_url": "https://classroom.google.com/c/om", "school_year": "2023-2024"}]
        with patch("src.classroom.discover_archived_classes", return_value=archived):
            client.post("/api/classes/discover-archived")
            for _ in range(20):
                time.sleep(0.1)
                with api_mod._archived_lock:
                    if api_mod._archived_state["status"] != "running":
                        break

        with api_mod._archived_lock:
            assert api_mod._archived_state["status"] == "done"
            assert len(api_mod._archived_state["classes"]) == 1

    def test_reset_clears_archived_state(self, client):
        import src.routes.api as api_mod

        with api_mod._archived_lock:
            api_mod._archived_state["status"] = "done"
            api_mod._archived_state["classes"] = [{"name": "Old", "course_url": "x", "school_year": "2023-2024"}]

        client.post("/api/reset")

        with api_mod._archived_lock:
            assert api_mod._archived_state["status"] == "idle"
            assert api_mod._archived_state["classes"] == []


# ---------------------------------------------------------------------------
# POST /api/classes/save — archived flag
# ---------------------------------------------------------------------------


class TestClassesSaveArchived:
    def test_save_persists_archived_flag(self, client, engine):
        payload = {
            "classes": [
                {"name": "Active Math", "course_url": "https://classroom.google.com/c/1"},
                {"name": "Old Science", "course_url": "https://classroom.google.com/c/2", "archived": True},
            ]
        }
        resp = client.post("/api/classes/save", json=payload)
        assert resp.status_code == 200

        with get_session(engine) as s:
            rows = {r.name: r for r in s.query(SelectedClass).all()}
        assert rows["Active Math"].archived is False
        assert rows["Old Science"].archived is True

    def test_save_without_archived_defaults_false(self, client, engine):
        payload = {
            "classes": [
                {"name": "English", "course_url": "https://classroom.google.com/c/eng"},
            ]
        }
        client.post("/api/classes/save", json=payload)
        with get_session(engine) as s:
            row = s.query(SelectedClass).filter_by(name="English").first()
        assert row is not None
        assert row.archived is False
