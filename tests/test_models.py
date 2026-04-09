"""Tests for SQLAlchemy ORM models."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from src.models import Assignment, Base, SelectedClass, ScrapeLog


@pytest.fixture()
def session():
    """In-memory SQLite session for each test."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    s = factory()
    yield s
    s.close()


class TestAssignment:
    def test_minimal_insert(self, session):
        row = Assignment(assignment_url="https://classroom.google.com/c/1/a/2/details")
        session.add(row)
        session.commit()
        fetched = session.query(Assignment).one()
        assert fetched.assignment_url == "https://classroom.google.com/c/1/a/2/details"

    def test_defaults(self, session):
        row = Assignment(assignment_url="https://example.com/a/1")
        session.add(row)
        session.commit()
        assert row.assignment_type == "Unknown"
        assert row.status == "Unknown"
        assert row.turn_in_required == False  # noqa: E712
        assert row.description == ""
        assert row.attachment_links == ""
        assert row.attachment_titles == ""

    def test_all_fields_round_trip(self, session):
        row = Assignment(
            assignment_url="https://example.com/a/2",
            class_name="Math",
            week_label="Week 3",
            title="Homework 1",
            description="Do exercises 1-5",
            teacher="Smith",
            posted_date="2026-01-10",
            due_date="2026-01-15",
            points_possible="100",
            category="Homework",
            assignment_type="Assignment",
            status="Assigned",
            turn_in_required=True,
            grade="A",
            attachment_links="https://docs.google.com/doc/1",
            attachment_titles="Worksheet",
            scraped_at="2026-01-10T12:00:00+00:00",
            first_seen_at="2026-01-10T12:00:00+00:00",
            last_modified_at="2026-01-10T12:00:00+00:00",
            class_priority=2,
            notes="Important",
            ai_work_type="Essay",
            ai_effort_estimate="Medium (15-45 min)",
            ai_summary="Summary",
            ai_notes="AI notes",
        )
        session.add(row)
        session.commit()
        fetched = session.query(Assignment).filter_by(assignment_url="https://example.com/a/2").one()
        assert fetched.class_name == "Math"
        assert fetched.title == "Homework 1"
        assert fetched.turn_in_required is True
        assert fetched.grade == "A"
        assert fetched.ai_summary == "Summary"
        assert fetched.class_priority == 2

    def test_assignment_url_unique_constraint(self, session):
        url = "https://example.com/a/3"
        session.add(Assignment(assignment_url=url))
        session.commit()
        session.add(Assignment(assignment_url=url))
        with pytest.raises(IntegrityError):
            session.commit()

    def test_nullable_fields(self, session):
        row = Assignment(assignment_url="https://example.com/a/4")
        session.add(row)
        session.commit()
        assert row.class_name is None
        assert row.week_label is None
        assert row.posted_date is None
        assert row.due_date is None
        assert row.grade is None
        assert row.notes is None
        assert row.ai_work_type is None


class TestSelectedClass:
    def test_insert(self, session):
        row = SelectedClass(
            name="Science Heumann",
            course_url="https://classroom.google.com/c/abc123",
        )
        session.add(row)
        session.commit()
        fetched = session.query(SelectedClass).one()
        assert fetched.name == "Science Heumann"
        assert fetched.active is True

    def test_inactive(self, session):
        row = SelectedClass(
            name="Art",
            course_url="https://classroom.google.com/c/xyz",
            active=False,
        )
        session.add(row)
        session.commit()
        assert session.query(SelectedClass).filter_by(active=False).count() == 1


class TestScrapeLog:
    def test_insert(self, session):
        row = ScrapeLog(
            timestamp="2026-01-10T12:00:00+00:00",
            classes_scraped=4,
            assignments_inserted=10,
            assignments_updated=2,
            assignments_unchanged=30,
        )
        session.add(row)
        session.commit()
        fetched = session.query(ScrapeLog).one()
        assert fetched.classes_scraped == 4
        assert fetched.assignments_inserted == 10
        assert fetched.assignments_unchanged == 30

    def test_defaults(self, session):
        row = ScrapeLog(timestamp="2026-01-10T12:00:00+00:00")
        session.add(row)
        session.commit()
        assert row.classes_scraped == 0
        assert row.assignments_inserted == 0
        assert row.assignments_updated == 0
        assert row.assignments_unchanged == 0
