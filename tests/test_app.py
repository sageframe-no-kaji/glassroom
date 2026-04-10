"""Tests for Flask app, dashboard routes, and API routes."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine

from src.app import create_app
from src.db import init_db, get_session
from src.models import Assignment, SelectedClass

_PROJECT_ROOT = Path(__file__).parent.parent


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def engine(tmp_path):
    """In-memory SQLite engine with schema created."""
    eng = create_engine("sqlite:///:memory:")
    init_db(eng)
    return eng


@pytest.fixture()
def app(engine):
    """Flask test app wired to an in-memory DB."""
    flask_app = create_app.__wrapped__(engine) if hasattr(create_app, "__wrapped__") else _make_app(engine)
    flask_app.config["TESTING"] = True
    return flask_app


def _make_app(engine):
    """Build a test Flask app without calling init_db again."""
    from flask import Flask
    from src.routes.dashboard import bp as dashboard_bp
    from src.routes.api import bp as api_bp
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
def client(app):
    return app.test_client()


def _make_assignment(session, **kwargs):
    """Insert a minimal Assignment and return it."""
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


def _make_selected_class(session, name="Math", course_url="https://classroom.google.com/c/abc"):
    """Insert a minimal SelectedClass and return it."""
    sc = SelectedClass(name=name, course_url=course_url, active=True)
    session.add(sc)
    session.commit()
    return sc


# ---------------------------------------------------------------------------
# Dashboard — GET /
# ---------------------------------------------------------------------------


class TestDashboard:
    def test_returns_200(self, client, engine):
        with get_session(engine) as s:
            _make_selected_class(s)
            _make_assignment(s)
        resp = client.get("/")
        assert resp.status_code == 200

    def test_shows_class_name(self, client, engine):
        with get_session(engine) as s:
            _make_selected_class(s, name="Science")
            _make_assignment(s, class_name="Science")
        resp = client.get("/")
        assert b"Science" in resp.data

    def test_shows_assignment_title(self, client, engine):
        with get_session(engine) as s:
            _make_selected_class(s)
            _make_assignment(s, title="My Essay")
        resp = client.get("/")
        assert b"My Essay" in resp.data

    def test_empty_state_redirects_to_setup(self, client):
        """No SelectedClass records → redirect to /setup."""
        resp = client.get("/")
        assert resp.status_code == 302
        assert "/setup" in resp.headers.get("Location", "")

    def test_empty_assignments_shows_empty_state(self, client, engine):
        """SelectedClass exists but no assignments → empty state message."""
        with get_session(engine) as s:
            _make_selected_class(s)
        resp = client.get("/")
        assert resp.status_code == 200
        assert b"No assignments" in resp.data


# ---------------------------------------------------------------------------
# Dashboard — GET /class/<name>
# ---------------------------------------------------------------------------


class TestClassDetail:
    def test_returns_200(self, client, engine):
        with get_session(engine) as s:
            _make_assignment(s, class_name="English")
        resp = client.get("/class/English")
        assert resp.status_code == 200

    def test_shows_assignment(self, client, engine):
        with get_session(engine) as s:
            _make_assignment(s, class_name="English", title="Essay Draft")
        resp = client.get("/class/English")
        assert b"Essay Draft" in resp.data

    def test_notes_textarea_present(self, client, engine):
        with get_session(engine) as s:
            _make_assignment(s, class_name="English")
        resp = client.get("/class/English")
        assert b"notes-field" in resp.data

    def test_priority_select_present(self, client, engine):
        with get_session(engine) as s:
            _make_assignment(s, class_name="English")
        resp = client.get("/class/English")
        assert b"priority-field" in resp.data


# ---------------------------------------------------------------------------
# Dashboard — GET /todo
# ---------------------------------------------------------------------------


class TestTodo:
    def test_returns_200(self, client):
        resp = client.get("/todo")
        assert resp.status_code == 200

    def test_filters_to_turn_in_required_and_not_done(self, client, engine):
        with get_session(engine) as s:
            _make_assignment(s, title="Need to Submit", status="Assigned", turn_in_required=True)
            _make_assignment(
                s, assignment_url="https://example.com/a/2",
                title="Already Done", status="Graded", turn_in_required=True
            )
            _make_assignment(
                s, assignment_url="https://example.com/a/3",
                title="No Turn In", status="Assigned", turn_in_required=False
            )
        resp = client.get("/todo")
        assert b"Need to Submit" in resp.data
        assert b"Already Done" not in resp.data
        assert b"No Turn In" not in resp.data

    def test_empty_state(self, client):
        resp = client.get("/todo")
        assert b"Nothing to do" in resp.data


# ---------------------------------------------------------------------------
# Dashboard — GET /downloads
# ---------------------------------------------------------------------------


class TestDownloads:
    def test_returns_200(self, client):
        resp = client.get("/downloads")
        assert resp.status_code == 200

    def test_empty_state_when_no_dir(self, client, tmp_path, monkeypatch):
        import src.routes.dashboard as dash_mod
        monkeypatch.setattr(dash_mod, "DOWNLOADS_DIR", tmp_path / "nonexistent")
        resp = client.get("/downloads")
        assert b"No PDFs downloaded" in resp.data

    def test_shows_pdfs(self, client, tmp_path, monkeypatch):
        class_dir = tmp_path / "math"
        class_dir.mkdir()
        (class_dir / "essay.pdf").write_text("fake")
        import src.routes.dashboard as dash_mod
        monkeypatch.setattr(dash_mod, "DOWNLOADS_DIR", tmp_path)
        resp = client.get("/downloads")
        assert b"essay.pdf" in resp.data

    def test_skips_non_directory_entries(self, client, tmp_path, monkeypatch):
        """Files directly in the downloads dir (not in a class folder) are ignored."""
        (tmp_path / "stray-file.pdf").write_text("fake")
        class_dir = tmp_path / "math"
        class_dir.mkdir()
        (class_dir / "homework.pdf").write_text("fake")
        import src.routes.dashboard as dash_mod
        monkeypatch.setattr(dash_mod, "DOWNLOADS_DIR", tmp_path)
        resp = client.get("/downloads")
        assert b"homework.pdf" in resp.data
        assert b"stray-file.pdf" not in resp.data


# ---------------------------------------------------------------------------
# API — PATCH /api/assignment/<id>
# ---------------------------------------------------------------------------


class TestPatchAssignment:
    def test_updates_notes(self, client, engine):
        with get_session(engine) as s:
            a = _make_assignment(s)
            aid = a.id

        resp = client.patch(f"/api/assignment/{aid}", json={"notes": "important"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True

        with get_session(engine) as s:
            updated = s.get(Assignment, aid)
            assert updated is not None
            assert updated.notes == "important"

    def test_updates_class_priority(self, client, engine):
        with get_session(engine) as s:
            a = _make_assignment(s)
            aid = a.id

        resp = client.patch(f"/api/assignment/{aid}", json={"class_priority": 3})
        assert resp.status_code == 200

        with get_session(engine) as s:
            updated = s.get(Assignment, aid)
            assert updated is not None
            assert updated.class_priority == 3

    def test_rejects_scraper_fields(self, client, engine):
        with get_session(engine) as s:
            a = _make_assignment(s)
            aid = a.id

        resp = client.patch(f"/api/assignment/{aid}", json={"title": "hacked"})
        assert resp.status_code == 400

    def test_404_on_missing_id(self, client):
        resp = client.patch("/api/assignment/9999", json={"notes": "x"})
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# API — GET /api/assignments
# ---------------------------------------------------------------------------


class TestGetAssignments:
    def test_returns_all_by_default(self, client, engine):
        with get_session(engine) as s:
            _make_assignment(s, assignment_url="https://example.com/a/1", class_name="Math")
            _make_assignment(s, assignment_url="https://example.com/a/2", class_name="English")
        resp = client.get("/api/assignments")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) == 2

    def test_filters_by_class(self, client, engine):
        with get_session(engine) as s:
            _make_assignment(s, assignment_url="https://example.com/a/1", class_name="Math")
            _make_assignment(s, assignment_url="https://example.com/a/2", class_name="English")
        resp = client.get("/api/assignments?class=Math")
        data = resp.get_json()
        assert len(data) == 1
        assert data[0]["class_name"] == "Math"

    def test_filters_by_status(self, client, engine):
        with get_session(engine) as s:
            _make_assignment(s, assignment_url="https://example.com/a/1", status="Assigned")
            _make_assignment(s, assignment_url="https://example.com/a/2", status="Graded")
        resp = client.get("/api/assignments?status=Graded")
        data = resp.get_json()
        assert len(data) == 1
        assert data[0]["status"] == "Graded"


# ---------------------------------------------------------------------------
# API — GET /api/stats
# ---------------------------------------------------------------------------


class TestStats:
    def test_returns_class_breakdown(self, client, engine):
        with get_session(engine) as s:
            _make_assignment(s, assignment_url="https://example.com/a/1",
                             class_name="Math", status="Assigned")
            _make_assignment(s, assignment_url="https://example.com/a/2",
                             class_name="Math", status="Graded")
            _make_assignment(s, assignment_url="https://example.com/a/3",
                             class_name="Math", status="Missing")
        resp = client.get("/api/stats")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "Math" in data
        assert data["Math"]["total"] == 3
        assert data["Math"]["done"] == 1
        assert data["Math"]["missing"] == 1
        assert data["Math"]["needs_attention"] == 1


# ---------------------------------------------------------------------------
# API — GET /api/scrape/status
# ---------------------------------------------------------------------------


class TestScrapeStatus:
    def test_returns_running_false_initially(self, client):
        resp = client.get("/api/scrape/status")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["running"] is False


# ---------------------------------------------------------------------------
# API — GET /api/export/csv
# ---------------------------------------------------------------------------


class TestExportCsv:
    def test_returns_csv_content_type(self, client, engine):
        with get_session(engine) as s:
            _make_assignment(s)
        resp = client.get("/api/export/csv")
        assert resp.status_code == 200
        assert "text/csv" in resp.content_type

    def test_csv_contains_header(self, client, engine):
        with get_session(engine) as s:
            _make_assignment(s)
        resp = client.get("/api/export/csv")
        text = resp.data.decode()
        assert "assignment_url" in text
        assert "class_name" in text

    def test_csv_contains_row_data(self, client, engine):
        with get_session(engine) as s:
            _make_assignment(s, title="Big Project", class_name="Science")
        resp = client.get("/api/export/csv")
        text = resp.data.decode()
        assert "Big Project" in text
        assert "Science" in text

    def test_todo_view_filters(self, client, engine):
        with get_session(engine) as s:
            _make_assignment(s, assignment_url="https://example.com/a/1",
                             title="Pending", status="Assigned", turn_in_required=True)
            _make_assignment(s, assignment_url="https://example.com/a/2",
                             title="Done", status="Graded", turn_in_required=True)
        resp = client.get("/api/export/csv?view=todo")
        text = resp.data.decode()
        assert "Pending" in text
        assert "Done" not in text

    def test_csv_disposition_header(self, client):
        resp = client.get("/api/export/csv")
        assert "attachment" in resp.headers.get("Content-Disposition", "")

    def test_todo_filename(self, client):
        resp = client.get("/api/export/csv?view=todo")
        assert "todo" in resp.headers.get("Content-Disposition", "")

    def test_todo_view_with_class_filter(self, client, engine):
        """view=todo combined with class filter should only return matching class."""
        with get_session(engine) as s:
            _make_assignment(s, assignment_url="https://example.com/a/1",
                             title="Math Pending", class_name="Math",
                             status="Assigned", turn_in_required=True)
            _make_assignment(s, assignment_url="https://example.com/a/2",
                             title="English Pending", class_name="English",
                             status="Assigned", turn_in_required=True)
        resp = client.get("/api/export/csv?view=todo&class=Math")
        text = resp.data.decode()
        assert "Math Pending" in text
        assert "English Pending" not in text

    def test_todo_view_with_status_filter(self, client, engine):
        """view=todo combined with status filter narrows results further."""
        with get_session(engine) as s:
            _make_assignment(s, assignment_url="https://example.com/a/1",
                             title="Assigned HW", status="Assigned", turn_in_required=True)
            _make_assignment(s, assignment_url="https://example.com/a/2",
                             title="Missing HW", status="Missing", turn_in_required=True)
        resp = client.get("/api/export/csv?view=todo&status=Missing")
        text = resp.data.decode()
        assert "Missing HW" in text
        assert "Assigned HW" not in text
