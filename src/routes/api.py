"""JSON API routes for Glassroom."""

from __future__ import annotations

import csv
import io
import threading
from datetime import datetime, timezone
from typing import Any

from flask import Blueprint, Response, current_app, jsonify, request

from src.db import get_session
from src.models import Assignment, ScrapeLog

bp = Blueprint("api", __name__, url_prefix="/api")

# ---------------------------------------------------------------------------
# Scrape progress state (in-process for now; replaced by a task queue in Ho 4.3+)
# ---------------------------------------------------------------------------

_scrape_lock = threading.Lock()
_scrape_state: dict[str, Any] = {"running": False, "progress": None}

_DONE_STATUSES = frozenset({"Turned in", "Graded", "Done"})
_URGENT_STATUSES = frozenset({"Missing"})
_ATTENTION_STATUSES = frozenset({"Assigned"})

# ---------------------------------------------------------------------------
# PATCH /api/assignment/<id>  — update manual fields
# ---------------------------------------------------------------------------


@bp.route("/assignment/<int:assignment_id>", methods=["PATCH"])
def patch_assignment(assignment_id: int) -> Response:
    engine = current_app.config["DB_ENGINE"]
    data = request.get_json(silent=True) or {}

    # Only allow updating manual fields
    allowed = {"notes", "class_priority"}
    updates = {k: v for k, v in data.items() if k in allowed}
    if not updates:
        return jsonify({"error": "No valid fields to update"}), 400  # type: ignore[return-value]

    with get_session(engine) as session:
        row = session.get(Assignment, assignment_id)
        if row is None:
            return jsonify({"error": "Not found"}), 404  # type: ignore[return-value]
        for field, value in updates.items():
            setattr(row, field, value)

    return jsonify({"ok": True, "id": assignment_id})


# ---------------------------------------------------------------------------
# GET /api/assignments — filtered JSON list
# ---------------------------------------------------------------------------


@bp.route("/assignments")
def get_assignments() -> Response:
    engine = current_app.config["DB_ENGINE"]
    class_filter = request.args.get("class")
    status_filter = request.args.get("status")

    with get_session(engine) as session:
        q = session.query(Assignment)
        if class_filter:
            q = q.filter(Assignment.class_name == class_filter)
        if status_filter:
            q = q.filter(Assignment.status == status_filter)
        rows = q.all()

    return jsonify([_assignment_dict(r) for r in rows])


# ---------------------------------------------------------------------------
# POST /api/scrape — trigger scrape in background thread
# ---------------------------------------------------------------------------


@bp.route("/scrape", methods=["POST"])
def trigger_scrape() -> Response:
    with _scrape_lock:
        if _scrape_state["running"]:
            return jsonify({"error": "Scrape already running"}), 409  # type: ignore[return-value]
        _scrape_state["running"] = True
        _scrape_state["progress"] = {"status": "starting"}

    engine = current_app.config["DB_ENGINE"]

    def _run() -> None:
        from src.config import load_config
        from src.classroom import do_scrape
        import src.db as db

        try:
            config = load_config()
            _scrape_state["progress"] = {"status": "scraping"}
            assignments = do_scrape(config)

            inserted = updated = skipped = 0
            for a in assignments:
                outcome = db.upsert(a, engine=engine)
                if outcome == "inserted":
                    inserted += 1
                elif outcome == "updated":
                    updated += 1
                else:
                    skipped += 1

            # Write scrape log
            with db.get_session(engine) as session:
                log = ScrapeLog(
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    classes_scraped=len(config.get("selected_classes", [])),
                    assignments_inserted=inserted,
                    assignments_updated=updated,
                    assignments_unchanged=skipped,
                )
                session.add(log)

            _scrape_state["progress"] = {
                "status": "done",
                "inserted": inserted,
                "updated": updated,
                "skipped": skipped,
            }
        except Exception as exc:
            _scrape_state["progress"] = {"status": "error", "message": str(exc)}
        finally:
            with _scrape_lock:
                _scrape_state["running"] = False

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"ok": True, "message": "Scrape started"})


# ---------------------------------------------------------------------------
# GET /api/scrape/status
# ---------------------------------------------------------------------------


@bp.route("/scrape/status")
def scrape_status() -> Response:
    with _scrape_lock:
        state = dict(_scrape_state)
    return jsonify(state)


# ---------------------------------------------------------------------------
# POST /api/download — trigger PDF download in background thread
# ---------------------------------------------------------------------------


@bp.route("/download", methods=["POST"])
def trigger_download() -> Response:
    def _run() -> None:
        from src.config import load_config
        from src.downloader import do_download_attachments
        config = load_config()
        do_download_attachments(config)

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"ok": True, "message": "Download started"})


# ---------------------------------------------------------------------------
# GET /api/stats — summary statistics by class
# ---------------------------------------------------------------------------


@bp.route("/stats")
def stats() -> Response:
    engine = current_app.config["DB_ENGINE"]
    with get_session(engine) as session:
        assignments = session.query(Assignment).all()

    by_class: dict[str, list[Assignment]] = {}
    for a in assignments:
        key = str(a.class_name or "Unknown")
        by_class.setdefault(key, []).append(a)

    result = {}
    for class_name, rows in sorted(by_class.items()):
        result[class_name] = {
            "total": len(rows),
            "done": sum(1 for r in rows if r.status in _DONE_STATUSES),
            "missing": sum(1 for r in rows if r.status in _URGENT_STATUSES),
            "needs_attention": sum(1 for r in rows if r.status in _ATTENTION_STATUSES),
        }
    return jsonify(result)


# ---------------------------------------------------------------------------
# GET /api/export/csv — download assignments as CSV
# ---------------------------------------------------------------------------


@bp.route("/export/csv")
def export_csv() -> Response:
    engine = current_app.config["DB_ENGINE"]
    view = request.args.get("view")
    class_filter = request.args.get("class")
    status_filter = request.args.get("status")

    with get_session(engine) as session:
        q = session.query(Assignment)

        if view == "todo":
            q = q.filter(
                Assignment.status.notin_(["Turned in", "Graded", "Done"]),
                Assignment.turn_in_required == True,  # noqa: E712
            )
        if class_filter:
            q = q.filter(Assignment.class_name == class_filter)
        if status_filter:
            q = q.filter(Assignment.status == status_filter)

        rows = q.order_by(Assignment.class_name, Assignment.due_date).all()

    columns = [
        "id", "assignment_url", "class_name", "week_label", "title",
        "description", "teacher", "posted_date", "due_date", "points_possible",
        "category", "assignment_type", "status", "turn_in_required", "grade",
        "attachment_links", "attachment_titles", "scraped_at", "first_seen_at",
        "last_modified_at", "class_priority", "notes",
    ]

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({col: getattr(row, col, "") for col in columns})

    filename = "assignments-todo.csv" if view == "todo" else "assignments.csv"
    return Response(
        buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _assignment_dict(a: Assignment) -> dict[str, Any]:
    return {
        "id": a.id,
        "assignment_url": a.assignment_url,
        "class_name": a.class_name,
        "week_label": a.week_label,
        "title": a.title,
        "description": a.description,
        "teacher": a.teacher,
        "posted_date": a.posted_date,
        "due_date": a.due_date,
        "points_possible": a.points_possible,
        "category": a.category,
        "assignment_type": a.assignment_type,
        "status": a.status,
        "turn_in_required": a.turn_in_required,
        "grade": a.grade,
        "attachment_links": a.attachment_links,
        "attachment_titles": a.attachment_titles,
        "scraped_at": a.scraped_at,
        "first_seen_at": a.first_seen_at,
        "last_modified_at": a.last_modified_at,
        "class_priority": a.class_priority,
        "notes": a.notes,
    }
