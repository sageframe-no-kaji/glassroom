"""Tests for Ho 4.6 — Settings page and Baserow export API."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from sqlalchemy import create_engine

from src.db import init_db, get_session
from src.models import Assignment

_PROJECT_ROOT = Path(__file__).parent.parent


# ---------------------------------------------------------------------------
# Fixtures (mirror test_app.py pattern)
# ---------------------------------------------------------------------------


@pytest.fixture()
def engine(tmp_path):
    eng = create_engine("sqlite:///:memory:")
    init_db(eng)
    return eng


@pytest.fixture()
def app(engine, tmp_path, monkeypatch):
    """Flask test app with settings isolated to tmp_path."""
    from src.routes.dashboard import bp as dashboard_bp
    from src.routes.api import bp as api_bp
    from src.routes.setup import bp as setup_bp
    from src.routes.settings import bp as settings_bp

    # Redirect DATA_DIR so settings.json goes to tmp_path
    import src.config as cfg_module
    monkeypatch.setattr(cfg_module, "SETTINGS_PATH", tmp_path / "settings.json")

    template_dir = str(_PROJECT_ROOT / "src" / "templates")
    static_dir = str(_PROJECT_ROOT / "src" / "static")
    a = Flask(__name__, template_folder=template_dir, static_folder=static_dir)
    a.config["TESTING"] = True
    a.config["DB_ENGINE"] = engine
    a.register_blueprint(dashboard_bp)
    a.register_blueprint(api_bp)
    a.register_blueprint(setup_bp)
    a.register_blueprint(settings_bp)
    return a


@pytest.fixture()
def client(app):
    return app.test_client()


def _make_assignment(session, **kwargs):
    defaults = {
        "assignment_url": "https://example.com/a/1",
        "class_name": "Math",
        "title": "HW 1",
        "status": "Assigned",
        "turn_in_required": True,
        "due_date": "2026-04-20",
        "posted_date": "2026-04-10",
    }
    defaults.update(kwargs)
    a = Assignment(**defaults)
    session.add(a)
    session.commit()
    return a


# ---------------------------------------------------------------------------
# Config helpers — load_settings / save_settings
# ---------------------------------------------------------------------------


class TestSettingsConfig:
    def test_load_settings_defaults(self, tmp_path, monkeypatch):
        import src.config as cfg
        monkeypatch.setattr(cfg, "SETTINGS_PATH", tmp_path / "settings.json")
        s = cfg.load_settings()
        assert s["baserow_url"] == ""
        assert s["baserow_token"] == ""
        assert s["auto_export"] is False
        assert s["baserow_table_id"] is None

    def test_save_and_reload(self, tmp_path, monkeypatch):
        import src.config as cfg
        monkeypatch.setattr(cfg, "SETTINGS_PATH", tmp_path / "settings.json")
        cfg.save_settings({"baserow_url": "http://test", "baserow_token": "tok", "auto_export": True})
        s = cfg.load_settings()
        assert s["baserow_url"] == "http://test"
        assert s["baserow_token"] == "tok"
        assert s["auto_export"] is True


# ---------------------------------------------------------------------------
# GET /settings — page renders
# ---------------------------------------------------------------------------


class TestSettingsPage:
    def test_returns_200(self, client):
        resp = client.get("/settings")
        assert resp.status_code == 200

    def test_shows_url_input(self, client):
        resp = client.get("/settings")
        assert b"input-url" in resp.data

    def test_shows_token_input(self, client):
        resp = client.get("/settings")
        assert b"input-token" in resp.data

    def test_shows_export_button(self, client):
        resp = client.get("/settings")
        assert b"Export to Baserow" in resp.data

    def test_shows_setup_button(self, client):
        resp = client.get("/settings")
        assert b"Setup Baserow" in resp.data

    def test_shows_auto_export_checkbox(self, client):
        resp = client.get("/settings")
        assert b"auto-export" in resp.data

    def test_settings_link_in_nav(self, client):
        resp = client.get("/settings")
        assert b"/settings" in resp.data


# ---------------------------------------------------------------------------
# GET /api/baserow/settings
# ---------------------------------------------------------------------------


class TestGetBaserowSettings:
    def test_returns_defaults(self, client):
        resp = client.get("/api/baserow/settings")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["baserow_url"] == ""
        assert data["has_token"] is False
        assert data["auto_export"] is False
        assert data["is_configured"] is False

    def test_reflects_saved_values(self, client, tmp_path, monkeypatch):
        import src.config as cfg
        monkeypatch.setattr(cfg, "SETTINGS_PATH", tmp_path / "settings.json")
        cfg.save_settings({
            "baserow_url": "http://mybaserow",
            "baserow_token": "secret",
            "auto_export": True,
            "baserow_table_id": 42,
        })
        resp = client.get("/api/baserow/settings")
        data = resp.get_json()
        assert data["baserow_url"] == "http://mybaserow"
        assert data["has_token"] is True
        assert data["auto_export"] is True
        assert data["is_configured"] is True


# ---------------------------------------------------------------------------
# POST /api/baserow/settings
# ---------------------------------------------------------------------------


class TestSaveBaserowSettings:
    def test_saves_url_and_token(self, client, tmp_path, monkeypatch):
        import src.config as cfg
        monkeypatch.setattr(cfg, "SETTINGS_PATH", tmp_path / "settings.json")
        resp = client.post(
            "/api/baserow/settings",
            json={"baserow_url": "http://test:8888", "baserow_token": "mytoken"},
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True
        s = cfg.load_settings()
        assert s["baserow_url"] == "http://test:8888"
        assert s["baserow_token"] == "mytoken"

    def test_blank_token_preserves_existing(self, client, tmp_path, monkeypatch):
        import src.config as cfg
        monkeypatch.setattr(cfg, "SETTINGS_PATH", tmp_path / "settings.json")
        cfg.save_settings({"baserow_url": "", "baserow_token": "existing", "auto_export": False})
        client.post(
            "/api/baserow/settings",
            json={"baserow_url": "http://new", "baserow_token": ""},
            content_type="application/json",
        )
        s = cfg.load_settings()
        assert s["baserow_token"] == "existing"
        assert s["baserow_url"] == "http://new"

    def test_saves_auto_export_flag(self, client, tmp_path, monkeypatch):
        import src.config as cfg
        monkeypatch.setattr(cfg, "SETTINGS_PATH", tmp_path / "settings.json")
        client.post(
            "/api/baserow/settings",
            json={"auto_export": True},
            content_type="application/json",
        )
        s = cfg.load_settings()
        assert s["auto_export"] is True


# ---------------------------------------------------------------------------
# POST /api/baserow/test
# ---------------------------------------------------------------------------


class TestTestBaserowConnection:
    def test_missing_url_returns_400(self, client, tmp_path, monkeypatch):
        import src.config as cfg
        monkeypatch.setattr(cfg, "SETTINGS_PATH", tmp_path / "settings.json")
        resp = client.post("/api/baserow/test")
        assert resp.status_code == 400

    def test_success_returns_workspaces(self, client, tmp_path, monkeypatch):
        import src.config as cfg
        monkeypatch.setattr(cfg, "SETTINGS_PATH", tmp_path / "settings.json")
        cfg.save_settings({
            "baserow_url": "http://test:8888",
            "baserow_token": "tok",
            "auto_export": False,
        })

        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.status_code = 200
        mock_resp.json.return_value = [{"id": 1, "name": "My Workspace"}]

        with patch("src.baserow_client.BaserowClient._request", return_value=mock_resp):
            resp = client.post("/api/baserow/test")

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True
        assert data["workspaces"][0]["name"] == "My Workspace"

    def test_http_error_returns_400(self, client, tmp_path, monkeypatch):
        import src.config as cfg
        import requests as _requests
        monkeypatch.setattr(cfg, "SETTINGS_PATH", tmp_path / "settings.json")
        cfg.save_settings({
            "baserow_url": "http://test:8888",
            "baserow_token": "bad",
            "auto_export": False,
        })

        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.reason = "Unauthorized"

        with patch(
            "src.baserow_client.BaserowClient._request",
            side_effect=_requests.HTTPError("401 — token rejected", response=mock_response),
        ):
            resp = client.post("/api/baserow/test")

        assert resp.status_code == 400
        assert resp.get_json()["ok"] is False


# ---------------------------------------------------------------------------
# POST /api/baserow/setup
# ---------------------------------------------------------------------------


class TestSetupBaserow:
    def test_missing_token_returns_400(self, client, tmp_path, monkeypatch):
        import src.config as cfg
        monkeypatch.setattr(cfg, "SETTINGS_PATH", tmp_path / "settings.json")
        resp = client.post("/api/baserow/setup")
        assert resp.status_code == 400

    def test_setup_stores_ids_in_settings(self, client, tmp_path, monkeypatch):
        import src.config as cfg
        monkeypatch.setattr(cfg, "SETTINGS_PATH", tmp_path / "settings.json")
        cfg.save_settings({
            "baserow_url": "http://test:8888",
            "baserow_token": "tok",
            "auto_export": False,
        })

        fake_config: dict[str, Any] = {
            "baserow_workspace_id": 10,
            "baserow_database_id": 20,
            "baserow_table_id": 30,
            "baserow_field_ids": {"assignment_url": 1, "title": 2},
        }

        with patch("src.baserow_client.BaserowClient.setup", return_value=fake_config):
            resp = client.post("/api/baserow/setup")

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True
        assert data["table_id"] == 30
        s = cfg.load_settings()
        assert s["baserow_table_id"] == 30
        assert s["baserow_workspace_id"] == 10


# ---------------------------------------------------------------------------
# POST /api/baserow/export
# ---------------------------------------------------------------------------


class TestExportBaserow:
    def test_not_configured_returns_400(self, client, tmp_path, monkeypatch):
        import src.config as cfg
        monkeypatch.setattr(cfg, "SETTINGS_PATH", tmp_path / "settings.json")
        cfg.save_settings({
            "baserow_url": "http://test",
            "baserow_token": "tok",
            "auto_export": False,
        })
        resp = client.post("/api/baserow/export")
        assert resp.status_code == 400
        assert "Setup" in resp.get_json()["error"]

    def test_exports_assignments(self, client, engine, tmp_path, monkeypatch):
        import src.config as cfg
        monkeypatch.setattr(cfg, "SETTINGS_PATH", tmp_path / "settings.json")
        cfg.save_settings({
            "baserow_url": "http://test",
            "baserow_token": "tok",
            "auto_export": False,
            "baserow_table_id": 99,
            "baserow_field_ids": {"assignment_url": 1, "title": 2, "class_name": 3},
        })

        with get_session(engine) as s:
            _make_assignment(s, title="Essay 1")
            _make_assignment(
                s,
                assignment_url="https://example.com/a/2",
                title="Essay 2",
            )

        upsert_calls: list[dict] = []

        def fake_upsert(self_inner, field_data, table_id, field_ids):
            upsert_calls.append({"field_data": field_data})
            return "inserted"

        with patch("src.baserow_client.BaserowClient.upsert", fake_upsert):
            resp = client.post("/api/baserow/export")

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True
        assert data["total"] == 2
        assert data["inserted"] == 2
        assert len(upsert_calls) == 2

    def test_export_includes_manual_fields(self, client, engine, tmp_path, monkeypatch):
        """notes and class_priority are exported."""
        import src.config as cfg
        monkeypatch.setattr(cfg, "SETTINGS_PATH", tmp_path / "settings.json")
        cfg.save_settings({
            "baserow_url": "http://test",
            "baserow_token": "tok",
            "auto_export": False,
            "baserow_table_id": 99,
            "baserow_field_ids": {"assignment_url": 1},
        })

        with get_session(engine) as s:
            _make_assignment(s, notes="Review this", class_priority=2)

        seen_data: list[dict] = []

        def fake_upsert(self_inner, field_data, table_id, field_ids):
            seen_data.append(field_data)
            return "skipped"

        with patch("src.baserow_client.BaserowClient.upsert", fake_upsert):
            client.post("/api/baserow/export")

        assert seen_data[0]["notes"] == "Review this"
        assert seen_data[0]["class_priority"] == 2

    def test_export_excludes_ai_fields(self, client, engine, tmp_path, monkeypatch):
        """ai_ fields are NOT exported."""
        import src.config as cfg
        monkeypatch.setattr(cfg, "SETTINGS_PATH", tmp_path / "settings.json")
        cfg.save_settings({
            "baserow_url": "http://test",
            "baserow_token": "tok",
            "auto_export": False,
            "baserow_table_id": 99,
            "baserow_field_ids": {"assignment_url": 1},
        })

        with get_session(engine) as s:
            _make_assignment(s)

        seen_data: list[dict] = []

        def fake_upsert(self_inner, field_data, table_id, field_ids):
            seen_data.append(field_data)
            return "skipped"

        with patch("src.baserow_client.BaserowClient.upsert", fake_upsert):
            client.post("/api/baserow/export")

        keys = set(seen_data[0].keys())
        assert not any(k.startswith("ai_") for k in keys)
