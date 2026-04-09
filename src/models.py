"""SQLAlchemy ORM models for Glassroom — SQLite backend."""

from sqlalchemy import Boolean, Column, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class Assignment(Base):
    __tablename__ = "assignments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    assignment_url = Column(String, unique=True, nullable=False, index=True)
    class_name = Column(String, nullable=True)
    week_label = Column(String, nullable=True)
    title = Column(String, nullable=True)
    description = Column(Text, default="")
    teacher = Column(String, nullable=True)
    posted_date = Column(String, nullable=True)
    due_date = Column(String, nullable=True)
    points_possible = Column(String, nullable=True)
    category = Column(String, nullable=True)
    assignment_type = Column(String, default="Unknown")
    status = Column(String, default="Unknown")
    turn_in_required = Column(Boolean, default=False)
    grade = Column(String, nullable=True)
    attachment_links = Column(Text, default="")
    attachment_titles = Column(Text, default="")
    scraped_at = Column(String, nullable=True)
    first_seen_at = Column(String, nullable=True)
    last_modified_at = Column(String, nullable=True)
    # Manual fields — never written by the scraper
    class_priority = Column(Integer, nullable=True)
    notes = Column(Text, nullable=True)
    # AI fields — populated separately, never written by scraper
    ai_work_type = Column(String, nullable=True)
    ai_effort_estimate = Column(String, nullable=True)
    ai_summary = Column(String, nullable=True)
    ai_notes = Column(Text, nullable=True)


class SelectedClass(Base):
    __tablename__ = "selected_classes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)
    course_url = Column(String, nullable=False)
    active = Column(Boolean, default=True)


class ScrapeLog(Base):
    __tablename__ = "scrape_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(String, nullable=False)
    classes_scraped = Column(Integer, default=0)
    assignments_inserted = Column(Integer, default=0)
    assignments_updated = Column(Integer, default=0)
    assignments_unchanged = Column(Integer, default=0)
