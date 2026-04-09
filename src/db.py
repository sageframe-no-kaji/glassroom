"""SQLite/SQLAlchemy database layer for Glassroom.

Provides engine setup, session factory, table init, and the upsert helper
that mirrors the Baserow upsert contract:
- INSERT on new assignment_url (sets first_seen_at, last_modified_at, scraped_at)
- UPDATE on changed scraped fields (sets last_modified_at, scraped_at;
  never touches first_seen_at, notes, class_priority, ai_* fields)
- SKIP when no comparable field has changed
"""

import re
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Generator, Literal

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from src.models import Assignment, Base

DB_PATH = Path(__file__).parent.parent / "data" / "classroom.db"

# Fields compared to detect real changes. Housekeeping timestamps and
# manual/ai fields are excluded — they must never trigger spurious updates.
COMPARABLE_FIELDS = frozenset(
    {
        "assignment_url",
        "class_name",
        "week_label",
        "title",
        "description",
        "teacher",
        "posted_date",
        "due_date",
        "points_possible",
        "category",
        "assignment_type",
        "status",
        "turn_in_required",
        "grade",
        "attachment_links",
        "attachment_titles",
    }
)

# Scraper-owned fields that may be overwritten on UPDATE.
# Excludes: first_seen_at, class_priority, notes, ai_* fields.
_SCRAPER_FIELDS = frozenset(
    {
        "assignment_url",
        "class_name",
        "week_label",
        "title",
        "description",
        "teacher",
        "posted_date",
        "due_date",
        "points_possible",
        "category",
        "assignment_type",
        "status",
        "turn_in_required",
        "grade",
        "attachment_links",
        "attachment_titles",
        "scraped_at",
        "last_modified_at",
    }
)

def _parse_date_string(s: str | None) -> str | None:
    """Convert a Google Classroom display date string to ISO YYYY-MM-DD.

    Classroom shows dates in two formats:
      - "Feb 9"        (current year — no year suffix)
      - "Dec 4, 2025"  (prior year — explicit year)

    The "Posted"/"Edited" prefix is stripped if present.
    Returns None if the string is empty, unparseable, or is "No due date".
    """
    if not s:
        return None
    s = re.sub(r"^(Posted|Edited|Updated)\s+", "", s.strip())
    if not s or s.lower().startswith("no "):
        return None
    for fmt in ("%b %d, %Y", "%b %d"):
        try:
            dt = datetime.strptime(s, fmt)
            if fmt == "%b %d":
                dt = dt.replace(year=date.today().year)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _prepare_field_data(field_data: dict[str, Any]) -> dict[str, Any]:
    """Normalize scraped values before writing to SQLite.

    Mirrors BaserowClient._prepare_field_data so both storage backends
    receive the same normalized data.
    """
    prepared = dict(field_data)
    for date_field in ("posted_date", "due_date"):
        raw = prepared.get(date_field)
        prepared[date_field] = _parse_date_string(raw if isinstance(raw, str) else None)
    pts = prepared.get("points_possible")
    if pts is not None:
        try:
            prepared["points_possible"] = str(int(float(str(pts))))
        except (ValueError, TypeError):
            prepared["points_possible"] = str(pts)
    return prepared


def _has_changes(new_data: dict[str, Any], existing: Assignment) -> bool:
    """Return True if any comparable field differs from the stored row."""
    for field_name in COMPARABLE_FIELDS:
        if field_name not in new_data:
            continue
        existing_val = getattr(existing, field_name, None)
        new_val = new_data[field_name]
        # Treat None and "" as equivalent so optional fields don't trigger spurious updates.
        if existing_val in (None, "") and new_val in (None, ""):
            continue
        if existing_val != new_val:
            return True
    return False


def get_engine(db_path: Path | None = None) -> Engine:
    """Return a SQLAlchemy engine pointed at the SQLite database.

    Creates the data/ directory if it doesn't exist.
    """
    path = db_path if db_path is not None else DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    return create_engine(f"sqlite:///{path}", echo=False)


def init_db(engine: Engine | None = None) -> Engine:
    """Create all tables. Safe to call repeatedly — uses CREATE IF NOT EXISTS."""
    eng = engine if engine is not None else get_engine()
    Base.metadata.create_all(eng)
    return eng


@contextmanager
def get_session(engine: Engine | None = None) -> Generator[Session, None, None]:
    """Context manager that yields a SQLAlchemy session and commits on exit.

    expire_on_commit=False keeps instance attributes accessible after the
    session closes — required for callers that read attributes outside the
    context block.
    """
    eng = engine if engine is not None else get_engine()
    factory = sessionmaker(bind=eng, expire_on_commit=False)
    session: Session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def upsert(
    field_data: dict[str, Any],
    engine: Engine | None = None,
) -> Literal["inserted", "updated", "skipped"]:
    """Insert or update an Assignment row keyed on assignment_url.

    field_data should contain all scraper fields. This function manages
    first_seen_at, last_modified_at, and scraped_at internally.

    Returns 'inserted', 'updated', or 'skipped'.
    """
    field_data = _prepare_field_data(field_data)
    assignment_url = field_data.get("assignment_url")
    if not assignment_url:
        raise ValueError("field_data must include assignment_url")

    now = datetime.now(timezone.utc).isoformat()
    eng = engine if engine is not None else get_engine()

    with get_session(eng) as session:
        existing = (
            session.query(Assignment)
            .filter(Assignment.assignment_url == assignment_url)
            .first()
        )

        if existing is None:
            row = Assignment(
                first_seen_at=now,
                last_modified_at=now,
                scraped_at=now,
                **{k: v for k, v in field_data.items() if hasattr(Assignment, k)},
            )
            session.add(row)
            return "inserted"

        if not _has_changes(field_data, existing):
            return "skipped"

        # Update only scraper-owned fields; never touch first_seen_at, notes,
        # class_priority, or ai_* fields.
        for field_name in _SCRAPER_FIELDS - {"scraped_at", "last_modified_at"}:
            if field_name in field_data and hasattr(existing, field_name):
                setattr(existing, field_name, field_data[field_name])
        existing.scraped_at = now  # type: ignore[assignment]
        existing.last_modified_at = now  # type: ignore[assignment]
        return "updated"
