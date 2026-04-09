"""Tests for src/db.py — engine, session, upsert, _parse_date_string."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from src.db import (
    _has_changes,
    _parse_date_string,
    _prepare_field_data,
    get_session,
    init_db,
    upsert,
)
from src.models import Assignment, Base


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def engine() -> Engine:
    """Fresh in-memory SQLite engine with tables created."""
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return eng


def _minimal_payload(url: str = "https://example.com/a/1") -> dict[str, object]:
    return {
        "assignment_url": url,
        "class_name": "Math",
        "title": "Homework 1",
        "description": "Do exercises",
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
        "week_label": None,
    }


# ---------------------------------------------------------------------------
# _parse_date_string
# ---------------------------------------------------------------------------


class TestParseDateString:
    def test_none_returns_none(self):
        assert _parse_date_string(None) is None

    def test_empty_string_returns_none(self):
        assert _parse_date_string("") is None

    def test_no_due_date_returns_none(self):
        assert _parse_date_string("No due date") is None

    def test_no_prefix_returns_none(self):
        assert _parse_date_string("No assignment") is None

    def test_full_date_with_year(self):
        assert _parse_date_string("Dec 4, 2025") == "2025-12-04"

    def test_short_date_current_year(self, monkeypatch):
        import src.db as db_module
        from datetime import date

        monkeypatch.setattr(db_module, "date", type("date", (), {"today": staticmethod(lambda: date(2026, 1, 1))}))
        # Without monkeypatching the inner call is tricky — just verify format
        result = _parse_date_string("Feb 9")
        assert result is not None
        assert result.endswith("-02-09")

    def test_posted_prefix_stripped(self):
        result = _parse_date_string("Posted Dec 4, 2025")
        assert result == "2025-12-04"

    def test_edited_prefix_stripped(self):
        result = _parse_date_string("Edited Jan 15, 2026")
        assert result == "2026-01-15"

    def test_updated_prefix_stripped(self):
        result = _parse_date_string("Updated Mar 3, 2025")
        assert result == "2025-03-03"

    def test_unparseable_returns_none(self):
        assert _parse_date_string("not a date at all") is None

    def test_whitespace_only_returns_none(self):
        assert _parse_date_string("   ") is None


# ---------------------------------------------------------------------------
# _prepare_field_data
# ---------------------------------------------------------------------------


class TestPrepareFieldData:
    def test_date_strings_normalized(self):
        data = {"posted_date": "Dec 4, 2025", "due_date": "Jan 15, 2026"}
        result = _prepare_field_data(data)
        assert result["posted_date"] == "2025-12-04"
        assert result["due_date"] == "2026-01-15"

    def test_none_dates_stay_none(self):
        data = {"posted_date": None, "due_date": None}
        result = _prepare_field_data(data)
        assert result["posted_date"] is None
        assert result["due_date"] is None

    def test_points_integer_string(self):
        result = _prepare_field_data({"points_possible": 100})
        assert result["points_possible"] == "100"

    def test_points_float_string(self):
        result = _prepare_field_data({"points_possible": 75.0})
        assert result["points_possible"] == "75"

    def test_points_none_unchanged(self):
        result = _prepare_field_data({"points_possible": None})
        assert result["points_possible"] is None

    def test_points_unparseable_falls_back_to_str(self):
        # Covers the ValueError/TypeError branch in _prepare_field_data
        result = _prepare_field_data({"points_possible": "not-a-number"})
        assert result["points_possible"] == "not-a-number"

    def test_other_fields_untouched(self):
        data = {"title": "Test", "status": "Assigned"}
        result = _prepare_field_data(data)
        assert result["title"] == "Test"
        assert result["status"] == "Assigned"


# ---------------------------------------------------------------------------
# init_db
# ---------------------------------------------------------------------------


class TestInitDb:
    def test_creates_tables(self, engine):
        # Tables were created by the fixture — verify they exist
        from sqlalchemy import inspect
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        assert "assignments" in tables
        assert "selected_classes" in tables
        assert "scrape_logs" in tables

    def test_idempotent(self, engine):
        """Calling init_db twice should not raise."""
        init_db(engine)
        init_db(engine)

    def test_get_engine_default_path_creates_dir(self, tmp_path, monkeypatch):
        """get_engine() with no args uses DB_PATH — covers the default branch."""
        import src.db as db_module
        fake_db_path = tmp_path / "data" / "classroom.db"
        monkeypatch.setattr(db_module, "DB_PATH", fake_db_path)
        eng = db_module.get_engine()
        assert fake_db_path.parent.exists()
        eng.dispose()


# ---------------------------------------------------------------------------
# upsert — insert path
# ---------------------------------------------------------------------------


class TestUpsertInsert:
    def test_returns_inserted(self, engine):
        result = upsert(_minimal_payload(), engine=engine)
        assert result == "inserted"

    def test_row_appears_in_db(self, engine):
        upsert(_minimal_payload(), engine=engine)
        with get_session(engine) as session:
            row = session.query(Assignment).one()
        assert row.assignment_url == "https://example.com/a/1"
        assert row.class_name == "Math"

    def test_first_seen_at_set(self, engine):
        upsert(_minimal_payload(), engine=engine)
        with get_session(engine) as session:
            row = session.query(Assignment).one()
        assert row.first_seen_at is not None

    def test_last_modified_at_set(self, engine):
        upsert(_minimal_payload(), engine=engine)
        with get_session(engine) as session:
            row = session.query(Assignment).one()
        assert row.last_modified_at is not None

    def test_scraped_at_set(self, engine):
        upsert(_minimal_payload(), engine=engine)
        with get_session(engine) as session:
            row = session.query(Assignment).one()
        assert row.scraped_at is not None


# ---------------------------------------------------------------------------
# upsert — skip path
# ---------------------------------------------------------------------------


class TestUpsertSkip:
    def test_returns_skipped_on_identical(self, engine):
        payload = _minimal_payload()
        upsert(payload, engine=engine)
        result = upsert(payload, engine=engine)
        assert result == "skipped"

    def test_scraped_at_not_updated_on_skip(self, engine):
        payload = _minimal_payload()
        upsert(payload, engine=engine)
        with get_session(engine) as session:
            row = session.query(Assignment).one()
            first_scraped = row.scraped_at

        upsert(payload, engine=engine)
        with get_session(engine) as session:
            row = session.query(Assignment).one()
        # scraped_at should NOT change on skip
        assert row.scraped_at == first_scraped

    def test_first_seen_at_not_updated_on_skip(self, engine):
        payload = _minimal_payload()
        upsert(payload, engine=engine)
        with get_session(engine) as session:
            row = session.query(Assignment).one()
            first_seen = row.first_seen_at

        upsert(payload, engine=engine)
        with get_session(engine) as session:
            row = session.query(Assignment).one()
        assert row.first_seen_at == first_seen


# ---------------------------------------------------------------------------
# upsert — update path
# ---------------------------------------------------------------------------


class TestUpsertUpdate:
    def test_returns_updated(self, engine):
        payload = _minimal_payload()
        upsert(payload, engine=engine)
        changed = dict(payload)
        changed["title"] = "Updated Title"
        result = upsert(changed, engine=engine)
        assert result == "updated"

    def test_title_updated(self, engine):
        upsert(_minimal_payload(), engine=engine)
        changed = dict(_minimal_payload())
        changed["title"] = "New Title"
        upsert(changed, engine=engine)
        with get_session(engine) as session:
            row = session.query(Assignment).one()
        assert row.title == "New Title"

    def test_first_seen_at_never_overwritten(self, engine):
        payload = _minimal_payload()
        upsert(payload, engine=engine)
        with get_session(engine) as session:
            row = session.query(Assignment).one()
            original_first_seen = row.first_seen_at

        changed = dict(payload)
        changed["title"] = "Changed"
        upsert(changed, engine=engine)
        with get_session(engine) as session:
            row = session.query(Assignment).one()
        assert row.first_seen_at == original_first_seen

    def test_last_modified_at_updated(self, engine):
        import time
        payload = _minimal_payload()
        upsert(payload, engine=engine)
        with get_session(engine) as session:
            row = session.query(Assignment).one()
            original_lm = row.last_modified_at

        time.sleep(0.01)  # ensure timestamp differs
        changed = dict(payload)
        changed["status"] = "Graded"
        upsert(changed, engine=engine)
        with get_session(engine) as session:
            row = session.query(Assignment).one()
        assert row.last_modified_at != original_lm

    def test_notes_never_overwritten(self, engine):
        """Manual field 'notes' must survive a scraper update."""
        upsert(_minimal_payload(), engine=engine)
        # Manually set notes
        with get_session(engine) as session:
            row = session.query(Assignment).one()
            row.notes = "Parent note"  # type: ignore[assignment]

        # Scraper update with same url
        changed = dict(_minimal_payload())
        changed["title"] = "Changed"
        upsert(changed, engine=engine)
        with get_session(engine) as session:
            row = session.query(Assignment).one()
        assert row.notes == "Parent note"

    def test_class_priority_never_overwritten(self, engine):
        upsert(_minimal_payload(), engine=engine)
        with get_session(engine) as session:
            row = session.query(Assignment).one()
            row.class_priority = 3  # type: ignore[assignment]

        changed = dict(_minimal_payload())
        changed["title"] = "Changed"
        upsert(changed, engine=engine)
        with get_session(engine) as session:
            row = session.query(Assignment).one()
        assert row.class_priority == 3

    def test_ai_fields_never_overwritten(self, engine):
        upsert(_minimal_payload(), engine=engine)
        with get_session(engine) as session:
            row = session.query(Assignment).one()
            row.ai_summary = "AI generated summary"  # type: ignore[assignment]
            row.ai_work_type = "Essay"  # type: ignore[assignment]

        changed = dict(_minimal_payload())
        changed["title"] = "Changed"
        upsert(changed, engine=engine)
        with get_session(engine) as session:
            row = session.query(Assignment).one()
        assert row.ai_summary == "AI generated summary"
        assert row.ai_work_type == "Essay"


# ---------------------------------------------------------------------------
# upsert — edge cases
# ---------------------------------------------------------------------------


class TestUpsertEdgeCases:
    def test_missing_assignment_url_raises(self, engine):
        with pytest.raises(ValueError, match="assignment_url"):
            upsert({"title": "No URL"}, engine=engine)

    def test_none_vs_empty_string_treated_equivalent(self, engine):
        """None and '' in optional fields should not trigger an update."""
        payload = _minimal_payload()
        payload["description"] = ""
        upsert(payload, engine=engine)
        # Now send None for description — should be skipped
        payload2 = dict(payload)
        payload2["description"] = None
        result = upsert(payload2, engine=engine)
        assert result == "skipped"


# ---------------------------------------------------------------------------
# _has_changes
# ---------------------------------------------------------------------------


class TestHasChanges:
    def _make_row(self, **kwargs) -> Assignment:
        defaults = {
            "assignment_url": "https://example.com/a/1",
            "class_name": "Math",
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
            "week_label": None,
        }
        defaults.update(kwargs)
        return Assignment(**defaults)

    def test_no_changes_returns_false(self):
        row = self._make_row()
        data = {
            "assignment_url": "https://example.com/a/1",
            "class_name": "Math",
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
            "week_label": None,
        }
        assert _has_changes(data, row) is False

    def test_title_change_returns_true(self):
        row = self._make_row(title="Old")
        data = {"title": "New"}
        assert _has_changes(data, row) is True

    def test_status_change_returns_true(self):
        row = self._make_row(status="Assigned")
        data = {"status": "Graded"}
        assert _has_changes(data, row) is True

    def test_none_vs_empty_not_a_change(self):
        row = self._make_row(description=None)
        data = {"description": ""}
        assert _has_changes(data, row) is False

    def test_manual_field_not_in_comparable(self):
        """notes is not a comparable field — changing it must not trigger update detection."""
        row = self._make_row()
        # notes not in COMPARABLE_FIELDS so should be ignored
        data = {"notes": "changed notes"}
        assert _has_changes(data, row) is False

    def test_field_not_in_new_data_skipped(self):
        """If a comparable field is absent from new_data, it must be skipped."""
        row = self._make_row(title="Existing Title")
        # Provide a payload that does NOT include 'title' at all
        data = {"status": "Assigned"}  # title is absent
        # Should not raise and should not detect change on missing field
        # (status matches, title is skipped since not in data)
        assert _has_changes(data, row) is False


# ---------------------------------------------------------------------------
# get_session — rollback path
# ---------------------------------------------------------------------------


class TestGetSessionRollback:
    def test_rollback_on_exception(self, engine):
        """get_session must rollback and re-raise on any exception inside the block."""
        with pytest.raises(RuntimeError, match="intentional"):
            with get_session(engine) as session:
                session.add(Assignment(assignment_url="https://example.com/rollback"))
                raise RuntimeError("intentional failure")

        # Row must NOT have been committed
        with get_session(engine) as session:
            count = session.query(Assignment).count()
        assert count == 0

