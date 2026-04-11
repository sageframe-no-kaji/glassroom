"""Dashboard routes — main views for the Glassroom web app."""

from __future__ import annotations

from collections import defaultdict
from typing import Optional, cast

from flask import Blueprint, current_app, redirect, render_template, url_for

from src.db import get_session
from src.downloader import DOWNLOADS_DIR
from src.models import Assignment, SelectedClass
from src.classroom import SESSION_DIR

bp = Blueprint("dashboard", __name__)

# Statuses that count as "done" for summary stats
_DONE_STATUSES = frozenset({"Turned in", "Graded", "Done"})
_URGENT_STATUSES = frozenset({"Missing"})
_ATTENTION_STATUSES = frozenset({"Assigned"})


def _class_stats(assignments: list[Assignment]) -> dict[str, int]:
    """Return summary counts for a list of assignments from a single class."""
    total = len(assignments)
    done = sum(1 for a in assignments if a.status in _DONE_STATUSES)
    missing = sum(1 for a in assignments if a.status in _URGENT_STATUSES)
    needs_attention = sum(1 for a in assignments if a.status in _ATTENTION_STATUSES)
    graded = sum(1 for a in assignments if cast(str, a.status) == "Graded")
    pct_due = round(100 * sum(1 for a in assignments if cast(Optional[str], a.due_date)) / total) if total else 0
    pct_attach = (
        round(100 * sum(1 for a in assignments if cast(Optional[str], a.attachment_links)) / total)
        if total
        else 0
    )
    attach_count = sum(
        len([ln for ln in (str(a.attachment_links) if a.attachment_links else "").split("\n") if ln.strip()])
        for a in assignments
    )
    return {
        "total": total,
        "done": done,
        "missing": missing,
        "needs_attention": needs_attention,
        "graded": graded,
        "pct_due": pct_due,
        "pct_attach": pct_attach,
        "attach_count": attach_count,
    }


def _sort_key(a: Assignment) -> tuple[str, str]:
    """Sort assignments: soonest due_date first, then posted_date."""
    return (str(a.due_date or "9999-99-99"), str(a.posted_date or "9999-99-99"))


@bp.route("/")
def dashboard() -> str:
    engine = current_app.config["DB_ENGINE"]
    with get_session(engine) as session:
        has_classes = session.query(SelectedClass).count() > 0
        if not has_classes:
            return redirect(url_for("setup.setup"))  # type: ignore[return-value]
        assignments = session.query(Assignment).order_by(Assignment.class_name).all()
        # Build lookup: class_name → archived flag
        selected_classes = session.query(SelectedClass).all()

    # Session validity — quick file-system check, no Playwright overhead
    session_valid = SESSION_DIR.exists() and any(SESSION_DIR.iterdir())

    # Map class name → archived flag
    archived_names: set[str] = {cast(str, sc.name) for sc in selected_classes if cast(bool, sc.archived)}

    # Group by class and sort within each class
    by_class: dict[str, list[Assignment]] = defaultdict(list)
    for a in assignments:
        by_class[str(a.class_name or "Unknown")].append(a)

    active_classes = []
    archived_classes = []
    for class_name in sorted(by_class.keys()):
        rows = sorted(by_class[class_name], key=_sort_key)
        entry = {
            "name": class_name,
            "assignments": rows,
            "stats": _class_stats(rows),
            "archived": class_name in archived_names,
        }
        if class_name in archived_names:
            archived_classes.append(entry)
        else:
            active_classes.append(entry)

    classes = active_classes + archived_classes

    return render_template("dashboard.html", classes=classes, session_valid=session_valid)


@bp.route("/class/<path:class_name>")
def class_detail(class_name: str) -> str:
    engine = current_app.config["DB_ENGINE"]
    with get_session(engine) as session:
        assignments = (
            session.query(Assignment)
            .filter(Assignment.class_name == class_name)
            .all()
        )

    rows = sorted(assignments, key=_sort_key)
    stats = _class_stats(rows)
    return render_template(
        "class_detail.html",
        class_name=class_name,
        assignments=rows,
        stats=stats,
    )


@bp.route("/todo")
def todo() -> str:
    engine = current_app.config["DB_ENGINE"]
    with get_session(engine) as session:
        assignments = (
            session.query(Assignment)
            .filter(
                Assignment.status.notin_(["Turned in", "Graded", "Done"]),
                Assignment.turn_in_required == True,  # noqa: E712
            )
            .all()
        )

    by_class: dict[str, list[Assignment]] = defaultdict(list)
    for a in assignments:
        by_class[str(a.class_name or "Unknown")].append(a)

    classes = []
    for class_name in sorted(by_class.keys()):
        rows = sorted(by_class[class_name], key=_sort_key)
        classes.append({
            "name": class_name,
            "assignments": rows,
            "stats": _class_stats(rows),
        })

    return render_template("todo.html", classes=classes)


@bp.route("/downloads")
def downloads() -> str:
    """List downloaded PDFs organised by class folder."""
    from src.downloader import _load_manifest

    pdf_tree: dict[str, list[dict[str, str]]] = {}

    if DOWNLOADS_DIR.is_dir():
        for class_dir in sorted(DOWNLOADS_DIR.iterdir()):
            if not class_dir.is_dir():
                continue
            pdfs = sorted(
                [
                    {"name": f.name, "url": f"/files/{class_dir.name}/{f.name}"}
                    for f in class_dir.iterdir()
                    if f.suffix.lower() == ".pdf"
                ],
                key=lambda x: x["name"],
            )
            if pdfs:
                pdf_tree[class_dir.name] = pdfs

    manifest = _load_manifest(DOWNLOADS_DIR) if DOWNLOADS_DIR.is_dir() else {}
    return render_template("downloads.html", pdf_tree=pdf_tree, manifest=manifest)
