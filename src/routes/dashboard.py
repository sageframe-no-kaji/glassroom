"""Dashboard routes — main views for the Glassroom web app."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Optional, cast

from flask import Blueprint, current_app, redirect, render_template, url_for

from src.db import get_session
from src.downloader import DOWNLOADS_DIR, attachment_type
from src.models import Assignment, SelectedClass
from src.classroom import SESSION_DIR

bp = Blueprint("dashboard", __name__)

# Statuses that count as "done" for summary stats
_DONE_STATUSES = frozenset({"Turned in", "Graded", "Done"})
_URGENT_STATUSES = frozenset({"Missing"})
_ATTENTION_STATUSES = frozenset({"Assigned"})


def _quality_label(pct_due: int, pct_attach: int, graded: int) -> str:
    """Classify a class's implementation quality based on combined metrics."""
    if pct_due < 5 and pct_attach < 10 and graded == 0:
        return "Empty"
    if pct_due > 60 and pct_attach > 60 and graded > 0:
        return "Structured"
    if pct_due < 20 and pct_attach < 20 and graded == 0:
        return "Minimal"
    return "Partial"


def _back_post_flag(posted_date: Optional[str], due_date: Optional[str]) -> str:
    """Return posting-timing flag: 'after' | 'same' | ''.

    'after' — posted_date strictly later than due_date (student had no warning).
    'same'  — posted_date equals due_date (posted the day it was due).
    ''      — either date is absent, or posted before the due date.
    """
    if not posted_date or not due_date:
        return ""
    if posted_date > due_date:
        return "after"
    if posted_date == due_date:
        return "same"
    return ""


def _class_stats(assignments: list[Assignment]) -> dict[str, int | str]:
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
    no_due_count = sum(1 for a in assignments if not cast(Optional[str], a.due_date))
    never_graded = total - graded
    back_posted = sum(
        1 for a in assignments
        if _back_post_flag(cast(Optional[str], a.posted_date), cast(Optional[str], a.due_date)) == "after"
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
        "no_due_count": no_due_count,
        "never_graded": never_graded,
        "back_posted": back_posted,
        "quality_label": _quality_label(pct_due, pct_attach, graded),
    }


def _sort_key(a: Assignment) -> tuple[str, str]:
    """Sort assignments: soonest due_date first, then posted_date."""
    return (str(a.due_date or "9999-99-99"), str(a.posted_date or "9999-99-99"))


def _fmt_size(size_bytes: int) -> str:
    """Format byte count as human-readable string."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.0f} KB"
    return f"{size_bytes / (1024 * 1024):.1f} MB"


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

    manifest = _load_manifest(DOWNLOADS_DIR) if DOWNLOADS_DIR.is_dir() else {}

    # Build manifest lookup: class_slug → filename → file_entry
    manifest_lookup: dict[str, dict[str, Any]] = {}
    for cls_slug, cls_data in manifest.get("classes", {}).items():
        manifest_lookup[cls_slug] = {
            f["filename"]: f
            for f in cls_data.get("files", [])
            if f.get("filename")
        }

    pdf_tree: dict[str, list[dict[str, Any]]] = {}

    if DOWNLOADS_DIR.is_dir():
        for class_dir in sorted(DOWNLOADS_DIR.iterdir()):
            if not class_dir.is_dir():
                continue
            cls_mf = manifest_lookup.get(class_dir.name, {})
            pdfs = sorted(
                [
                    _enrich_pdf_entry(f, cls_mf.get(f.name, {}))
                    for f in class_dir.iterdir()
                    if f.suffix.lower() == ".pdf"
                ],
                key=lambda x: x["name"],
            )
            if pdfs:
                pdf_tree[class_dir.name] = pdfs

    return render_template("downloads.html", pdf_tree=pdf_tree, manifest=manifest)


def _enrich_pdf_entry(f: Any, mf: dict[str, Any]) -> dict[str, Any]:
    """Build a rich dict for one downloaded PDF from filesystem + manifest data."""
    size_bytes = int(cast(Any, f).stat().st_size)
    source_url: str = mf.get("source_url", "")
    label: str = (
        mf.get("attachment_title")
        or mf.get("assignment_title")
        or cast(Any, f).stem
    ) or cast(Any, f).name
    return {
        "name": cast(Any, f).name,
        "url": f"/files/{cast(Any, f).parent.name}/{cast(Any, f).name}",
        "size_str": _fmt_size(size_bytes),
        "source_url": source_url,
        "label": label,
        "file_type": attachment_type(source_url) if source_url else "",
        "assignment_url": mf.get("assignment_url", ""),
    }
