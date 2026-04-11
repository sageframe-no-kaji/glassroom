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
    from src.routes.settings import bp as settings_bp
    from src.downloader import (
        DOWNLOADS_DIR,
        _class_folder_slug,
        _make_pdf_filename,
        attachment_type,
    )

    template_dir = str(_PROJECT_ROOT / "src" / "templates")
    static_dir = str(_PROJECT_ROOT / "src" / "static")
    a = Flask(__name__, template_folder=template_dir, static_folder=static_dir)
    a.config["DB_ENGINE"] = engine
    a.register_blueprint(dashboard_bp)
    a.register_blueprint(api_bp)
    a.register_blueprint(setup_bp)
    a.register_blueprint(settings_bp)

    # Mirror Jinja filters/globals from create_app
    a.jinja_env.filters["attachment_type"] = attachment_type

    def _count_attachments(links_str: object) -> int:
        if not links_str:
            return 0
        return len([ln for ln in str(links_str).split("\n") if ln.strip()])

    def _pdf_url_for_assignment(
        class_name: object, posted_date: object, title: object
    ) -> str | None:
        cs = str(class_name or "")
        pd = str(posted_date) if posted_date else None
        t = str(title or "")
        if not cs and not t:
            return None
        filename = _make_pdf_filename(pd, t)
        path = DOWNLOADS_DIR / _class_folder_slug(cs) / filename
        return f"/files/{_class_folder_slug(cs)}/{filename}" if path.exists() else None

    a.jinja_env.globals["count_attachments"] = _count_attachments
    a.jinja_env.globals["pdf_url_for_assignment"] = _pdf_url_for_assignment
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

    def test_shows_file_size(self, client, tmp_path, monkeypatch):
        """Downloads page shows formatted file size for each PDF."""
        class_dir = tmp_path / "math"
        class_dir.mkdir()
        (class_dir / "hw.pdf").write_bytes(b"x" * 2048)
        import src.routes.dashboard as dash_mod
        monkeypatch.setattr(dash_mod, "DOWNLOADS_DIR", tmp_path)
        resp = client.get("/downloads")
        # 2048 bytes → "2 KB" in the page
        assert b"2 KB" in resp.data

    def test_shows_type_column_header(self, client, tmp_path, monkeypatch):
        class_dir = tmp_path / "math"
        class_dir.mkdir()
        (class_dir / "hw.pdf").write_bytes(b"x" * 512)
        import src.routes.dashboard as dash_mod
        monkeypatch.setattr(dash_mod, "DOWNLOADS_DIR", tmp_path)
        resp = client.get("/downloads")
        assert b"Type" in resp.data

    def test_download_button_not_form_post(self, client):
        """Button on downloads page must not be a plain form-POST (raw JSON bug)."""
        resp = client.get("/downloads")
        assert b'action="/api/download"' not in resp.data
        assert b'triggerDownload' in resp.data


# ---------------------------------------------------------------------------
# Ho 5.2 — _fmt_size helper
# ---------------------------------------------------------------------------


class TestFmtSize:
    def test_bytes(self):
        from src.routes.dashboard import _fmt_size
        assert _fmt_size(512) == "512 B"

    def test_kilobytes(self):
        from src.routes.dashboard import _fmt_size
        assert _fmt_size(2048) == "2 KB"

    def test_megabytes(self):
        from src.routes.dashboard import _fmt_size
        result = _fmt_size(2 * 1024 * 1024)
        assert "2.0 MB" in result


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


# ---------------------------------------------------------------------------
# Ho 5.3 — Summary Card Labels (_quality_label + new stats)
# ---------------------------------------------------------------------------


class TestQualityLabel:
    def test_structured(self):
        from src.routes.dashboard import _quality_label
        assert _quality_label(pct_due=80, pct_attach=75, graded=5) == "Structured"

    def test_partial_due_in_range(self):
        from src.routes.dashboard import _quality_label
        assert _quality_label(pct_due=40, pct_attach=10, graded=0) == "Partial"

    def test_partial_some_grading(self):
        from src.routes.dashboard import _quality_label
        assert _quality_label(pct_due=10, pct_attach=5, graded=2) == "Partial"

    def test_minimal(self):
        from src.routes.dashboard import _quality_label
        assert _quality_label(pct_due=10, pct_attach=10, graded=0) == "Minimal"

    def test_empty(self):
        from src.routes.dashboard import _quality_label
        assert _quality_label(pct_due=0, pct_attach=0, graded=0) == "Empty"

    def test_empty_boundary(self):
        from src.routes.dashboard import _quality_label
        # pct_due=4 < 5, pct_attach=9 < 10, graded=0
        assert _quality_label(pct_due=4, pct_attach=9, graded=0) == "Empty"

    def test_not_empty_if_graded(self):
        from src.routes.dashboard import _quality_label
        # graded > 0 means it can't be Empty even if pct_due/pct_attach are very low
        assert _quality_label(pct_due=0, pct_attach=0, graded=1) != "Empty"

    def test_stats_includes_quality_label(self):
        from src.routes.dashboard import _class_stats
        a = Assignment(
            assignment_url="https://example.com/a/ql1",
            class_name="Math",
            title="HW",
            status="Assigned",
            due_date=None,
            attachment_links=None,
        )
        stats = _class_stats([a])
        assert "quality_label" in stats
        assert stats["quality_label"] in ("Structured", "Partial", "Minimal", "Empty")

    def test_stats_no_due_count(self):
        from src.routes.dashboard import _class_stats
        a1 = Assignment(
            assignment_url="https://example.com/a/nd1",
            class_name="Math", title="HW 1", status="Assigned", due_date=None,
        )
        a2 = Assignment(
            assignment_url="https://example.com/a/nd2",
            class_name="Math", title="HW 2", status="Assigned", due_date="2026-05-01",
        )
        stats = _class_stats([a1, a2])
        assert stats["no_due_count"] == 1

    def test_stats_never_graded(self):
        from src.routes.dashboard import _class_stats
        a1 = Assignment(
            assignment_url="https://example.com/a/ng1",
            class_name="Math", title="HW 1", status="Graded",
        )
        a2 = Assignment(
            assignment_url="https://example.com/a/ng2",
            class_name="Math", title="HW 2", status="Assigned",
        )
        stats = _class_stats([a1, a2])
        assert stats["never_graded"] == 1  # 2 total - 1 graded

    def test_dashboard_shows_quality_label(self, client, engine):
        """Dashboard renders quality label badge on stat cards."""
        with get_session(engine) as s:
            _make_selected_class(s)
            _make_assignment(s)
        resp = client.get("/")
        assert resp.status_code == 200
        content = resp.data.decode()
        # One of the four labels must appear
        assert any(label in content for label in ("Structured", "Partial", "Minimal", "Empty"))

    def test_dashboard_shows_no_due_count(self, client, engine):
        """Dashboard stat cards show 'no due date' count."""
        with get_session(engine) as s:
            _make_selected_class(s)
            _make_assignment(s, due_date=None)
        resp = client.get("/")
        assert b"no due date" in resp.data

    def test_dashboard_shows_never_graded(self, client, engine):
        """Dashboard stat cards show 'never graded' count."""
        with get_session(engine) as s:
            _make_selected_class(s)
            _make_assignment(s)
        resp = client.get("/")
        assert b"never graded" in resp.data


# ---------------------------------------------------------------------------
# Ho 5.1 — Attachment Visibility
# ---------------------------------------------------------------------------


class TestAttachVisibility:
    def test_class_stats_attach_count_sums_links(self):
        """_class_stats.attach_count counts individual links across assignments."""
        from src.routes.dashboard import _class_stats

        a1 = Assignment(
            assignment_url="https://example.com/a/v1",
            class_name="Math",
            title="HW 1",
            status="Assigned",
            attachment_links="https://docs.google.com/d1\nhttps://docs.google.com/d2",
        )
        a2 = Assignment(
            assignment_url="https://example.com/a/v2",
            class_name="Math",
            title="HW 2",
            status="Assigned",
            attachment_links="https://docs.google.com/d3",
        )
        a3 = Assignment(
            assignment_url="https://example.com/a/v3",
            class_name="Math",
            title="HW 3",
            status="Assigned",
            attachment_links="",
        )
        stats = _class_stats([a1, a2, a3])
        assert stats["attach_count"] == 3

    def test_class_stats_attach_count_handles_none(self):
        """_class_stats.attach_count treats None attachment_links as 0."""
        from src.routes.dashboard import _class_stats

        a = Assignment(
            assignment_url="https://example.com/a/v4",
            class_name="Math",
            title="HW",
            status="Assigned",
            attachment_links=None,
        )
        stats = _class_stats([a])
        assert stats["attach_count"] == 0

    def test_dashboard_has_attach_column_header(self, client, engine):
        """Dashboard renders the Attach column header."""
        with get_session(engine) as s:
            _make_selected_class(s)
            _make_assignment(s)
        resp = client.get("/")
        assert resp.status_code == 200
        assert b"Attach" in resp.data

    def test_dashboard_shows_attach_toggle_when_links_present(self, client, engine):
        """Dashboard shows paperclip toggle button when assignment has attachments."""
        with get_session(engine) as s:
            _make_selected_class(s)
            _make_assignment(
                s,
                attachment_links="https://docs.google.com/document/d/abc",
                attachment_titles="My Doc",
            )
        resp = client.get("/")
        assert b"attach-toggle" in resp.data

    def test_dashboard_shows_dash_when_no_attachments(self, client, engine):
        """Dashboard shows em-dash in Attach cell when no attachments."""
        with get_session(engine) as s:
            _make_selected_class(s)
            _make_assignment(s, attachment_links="")
        resp = client.get("/")
        assert b"attach-toggle" not in resp.data

    def test_class_detail_has_attach_column_header(self, client, engine):
        """Class detail view renders Attach column header."""
        with get_session(engine) as s:
            _make_assignment(s, class_name="English")
        resp = client.get("/class/English")
        assert resp.status_code == 200
        assert b"Attach" in resp.data

    def test_todo_has_attach_column_header(self, client, engine):
        """To Do view renders Attach column header."""
        with get_session(engine) as s:
            _make_selected_class(s)
            _make_assignment(s, turn_in_required=True, status="Assigned")
        resp = client.get("/todo")
        assert resp.status_code == 200
        assert b"Attach" in resp.data


# ---------------------------------------------------------------------------
# Dashboard — archived classes path (dashboard.py line 90)
# ---------------------------------------------------------------------------


class TestDashboardArchived:
    def test_archived_class_sorted_after_active(self, client, engine):
        """Archived classes appear after active classes in the dashboard."""
        with get_session(engine) as s:
            sc_active = SelectedClass(name="Active Class", course_url="https://classroom.google.com/c/a1", active=True, archived=False)
            sc_archived = SelectedClass(name="Old Class", course_url="https://classroom.google.com/c/a2", active=True, archived=True)
            s.add(sc_active)
            s.add(sc_archived)
            s.commit()
            _make_assignment(s, assignment_url="https://example.com/a/1", class_name="Active Class")
            _make_assignment(s, assignment_url="https://example.com/a/2", class_name="Old Class")
        resp = client.get("/")
        assert resp.status_code == 200
        content = resp.data.decode()
        # Both classes appear
        assert "Active Class" in content
        assert "Old Class" in content
        # Archived badge present for archived class
        assert "archived-badge" in content
        # Active class appears before archived class in rendered output
        assert content.index("Active Class") < content.index("Old Class")


# ---------------------------------------------------------------------------
# API — POST /api/scrape  (trigger endpoint — thread stub)
# ---------------------------------------------------------------------------


class TestScrapeTrigger:
    def test_returns_ok_when_not_running(self, client, monkeypatch):
        """POST /api/scrape enqueues and returns ok: true."""
        import src.routes.api as api_mod
        # Prevent the background thread from actually spawning Playwright
        monkeypatch.setattr(api_mod, "_scrape_state", {
            "running": False,
            "progress": {},
            "auto_download": False,
        })
        spawned = []
        import threading
        monkeypatch.setattr(threading, "Thread", lambda target, daemon=True: type("T", (), {"start": lambda self: spawned.append(1)})())
        resp = client.post("/api/scrape")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True

    def test_returns_409_when_already_running(self, client, monkeypatch):
        import src.routes.api as api_mod
        monkeypatch.setattr(api_mod, "_scrape_state", {
            "running": True,
            "progress": {},
            "auto_download": False,
        })
        resp = client.post("/api/scrape")
        assert resp.status_code == 409


# ---------------------------------------------------------------------------
# API — POST /api/download  (trigger endpoint — no page nav)
# ---------------------------------------------------------------------------


class TestDownloadTrigger:
    def test_returns_json_not_html(self, client, monkeypatch):
        """POST /api/download must return JSON, never a page redirect."""
        import src.routes.api as api_mod
        monkeypatch.setattr(api_mod, "_start_download", lambda: None)
        resp = client.post("/api/download")
        assert resp.status_code == 200
        assert resp.content_type.startswith("application/json")
        data = resp.get_json()
        assert data["ok"] is True

    def test_does_not_set_location_header(self, client, monkeypatch):
        """Ensure no redirect to raw JSON (original bug)."""
        import src.routes.api as api_mod
        monkeypatch.setattr(api_mod, "_start_download", lambda: None)
        resp = client.post("/api/download")
        assert resp.status_code == 200
        assert "Location" not in resp.headers


# ---------------------------------------------------------------------------
# API — GET /api/login/status
# ---------------------------------------------------------------------------


class TestLoginStatus:
    def test_returns_status_key(self, client):
        resp = client.get("/api/login/status")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "status" in data

    def test_initial_status_is_idle(self, client, monkeypatch):
        import src.routes.api as api_mod
        monkeypatch.setattr(api_mod, "_login_state", {"status": "idle", "error": None, "classes": []})
        resp = client.get("/api/login/status")
        assert resp.get_json()["status"] == "idle"


# ---------------------------------------------------------------------------
# API — GET /api/session/status
# ---------------------------------------------------------------------------


class TestSessionStatus:
    def test_returns_valid_false_when_no_session_dir(self, client, tmp_path, monkeypatch):
        import src.routes.api as api_mod
        monkeypatch.setattr(api_mod, "SESSION_DIR", tmp_path / "nonexistent")
        resp = client.get("/api/session/status")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["valid"] is False

    def test_returns_valid_true_when_session_dir_has_files(self, client, tmp_path, monkeypatch):
        session_dir = tmp_path / "session"
        session_dir.mkdir()
        (session_dir / "Default").mkdir()  # non-empty dir
        import src.routes.api as api_mod
        monkeypatch.setattr(api_mod, "SESSION_DIR", session_dir)
        resp = client.get("/api/session/status")
        data = resp.get_json()
        assert data["valid"] is True


# ---------------------------------------------------------------------------
# API — Baserow endpoints return 400 when not configured
# ---------------------------------------------------------------------------


class TestBaserowUnconfigured:
    def test_test_endpoint_400_no_config(self, client, monkeypatch):
        # load_settings is imported locally inside the handler, so patch the source
        monkeypatch.setattr("src.config.load_settings", lambda: {})
        resp = client.post("/api/baserow/test", json={})
        assert resp.status_code == 400

    def test_setup_endpoint_400_no_config(self, client, monkeypatch):
        monkeypatch.setattr("src.config.load_settings", lambda: {})
        resp = client.post("/api/baserow/setup")
        assert resp.status_code == 400

    def test_export_endpoint_400_no_config(self, client, monkeypatch):
        monkeypatch.setattr("src.config.load_settings", lambda: {})
        resp = client.post("/api/baserow/export")
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Ho 5.2 — Download status endpoint + 409 when already running
# ---------------------------------------------------------------------------


class TestDownloadStatus:
    def test_returns_status_key(self, client):
        resp = client.get("/api/download/status")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "status" in data
        assert "running" in data

    def test_initial_status_is_idle(self, client, monkeypatch):
        import src.routes.api as api_mod
        monkeypatch.setattr(api_mod, "_download_state", {
            "running": False,
            "status": "idle",
            "files_done": 0,
            "files_total": 0,
            "downloaded": 0,
            "skipped": 0,
            "classes": 0,
            "completed_at": None,
            "error": None,
        })
        data = client.get("/api/download/status").get_json()
        assert data["status"] == "idle"
        assert data["running"] is False

    def test_trigger_returns_409_when_already_running(self, client, monkeypatch):
        import src.routes.api as api_mod
        monkeypatch.setattr(api_mod, "_download_state", {
            "running": True,
            "status": "running",
            "files_done": 5,
            "files_total": 20,
            "downloaded": 0,
            "skipped": 0,
            "classes": 0,
            "completed_at": None,
            "error": None,
        })
        resp = client.post("/api/download")
        assert resp.status_code == 409

    def test_done_state_has_counts(self, client, monkeypatch):
        import src.routes.api as api_mod
        monkeypatch.setattr(api_mod, "_download_state", {
            "running": False,
            "status": "done",
            "files_done": 10,
            "files_total": 10,
            "downloaded": 8,
            "skipped": 2,
            "classes": 3,
            "completed_at": "2026-04-11T12:00:00Z",
            "error": None,
        })
        data = client.get("/api/download/status").get_json()
        assert data["downloaded"] == 8
        assert data["skipped"] == 2
        assert data["classes"] == 3

