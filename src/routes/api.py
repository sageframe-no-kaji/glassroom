"""JSON API routes for Glassroom."""

from __future__ import annotations

import csv
import io
import threading
from datetime import datetime, timezone
from typing import Any

from flask import Blueprint, Response, current_app, jsonify, request

from src.classroom import SESSION_DIR
from src.db import get_session
from src.models import Assignment, SelectedClass, ScrapeLog

bp = Blueprint("api", __name__, url_prefix="/api")

# ---------------------------------------------------------------------------
# Scrape progress state (in-process for now; replaced by a task queue in Ho 4.3+)
# ---------------------------------------------------------------------------

_scrape_lock = threading.Lock()
_scrape_state: dict[str, Any] = {
    "running": False,
    "progress": None,
    "auto_download": False,
}

# ---------------------------------------------------------------------------
# Login + class discovery state
# ---------------------------------------------------------------------------

_login_lock = threading.Lock()
_login_state: dict[str, Any] = {"status": "idle", "classes": [], "error": None}

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
    data = request.get_json(silent=True) or {}
    auto_download: bool = bool(data.get("auto_download", False))

    with _scrape_lock:
        if _scrape_state["running"]:
            return jsonify({"error": "Scrape already running"}), 409  # type: ignore[return-value]
        _scrape_state["running"] = True
        _scrape_state["auto_download"] = auto_download
        _scrape_state["progress"] = {"status": "starting"}

    engine = current_app.config["DB_ENGINE"]

    def _run() -> None:
        from src.classroom import do_scrape
        import src.db as db

        # Build config from DB so web-selected classes are used, not config.json
        try:
            with db.get_session(engine) as session:
                selected = [
                    {"name": sc.name, "course_url": sc.course_url}
                    for sc in session.query(SelectedClass)
                    .filter(SelectedClass.active == True)  # noqa: E712
                    .all()
                ]

            config = {"selected_classes": selected}
            total = len(selected)

            def _on_progress(class_name: str, done: int, total_: int) -> None:
                _scrape_state["progress"] = {
                    "status": "scraping",
                    "current_class": class_name,
                    "classes_done": done,
                    "classes_total": total_,
                }

            _scrape_state["progress"] = {
                "status": "scraping",
                "current_class": "",
                "classes_done": 0,
                "classes_total": total,
            }
            assignments = do_scrape(config, headless=True, on_progress=_on_progress)

            inserted = updated = skipped = 0
            for a in assignments:
                outcome = db.upsert(a, engine=engine)
                if outcome == "inserted":
                    inserted += 1
                elif outcome == "updated":
                    updated += 1
                else:
                    skipped += 1

            with db.get_session(engine) as session:
                log = ScrapeLog(
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    classes_scraped=total,
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

            # Trigger download if requested
            if _scrape_state.get("auto_download"):
                _start_download()

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
    _start_download()
    return jsonify({"ok": True, "message": "Download started"})


def _start_download() -> None:
    """Spawn the download thread. Safe to call from another background thread."""
    def _run() -> None:
        from src.config import load_config
        from src.downloader import do_download_attachments
        config = load_config()
        do_download_attachments(config)

    threading.Thread(target=_run, daemon=True).start()


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
# POST /api/login — open Playwright headed browser, wait for login, discover
# ---------------------------------------------------------------------------


@bp.route("/login", methods=["POST"])
def trigger_login() -> Response:
    with _login_lock:
        if _login_state["status"] == "running":
            return jsonify({"error": "Login already in progress"}), 409  # type: ignore[return-value]
        _login_state["status"] = "running"
        _login_state["error"] = None
        _login_state["classes"] = []

    def _run() -> None:
        from src.classroom import discover_classes, do_login

        try:
            do_login()
            classes = discover_classes()
            with _login_lock:
                _login_state["classes"] = classes
                _login_state["status"] = "done"
        except Exception as exc:
            with _login_lock:
                _login_state["status"] = "failed"
                _login_state["error"] = str(exc)

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"ok": True, "message": "Login started"})


# ---------------------------------------------------------------------------
# GET /api/login/status — poll login + discovery progress
# ---------------------------------------------------------------------------


@bp.route("/login/status")
def login_status() -> Response:
    with _login_lock:
        state = dict(_login_state)
    return jsonify(state)


# ---------------------------------------------------------------------------
# GET /api/session/status — file-system check for valid Playwright session
# ---------------------------------------------------------------------------


@bp.route("/session/status")
def session_status() -> Response:
    valid = SESSION_DIR.exists() and any(SESSION_DIR.iterdir())
    return jsonify({"valid": valid, "path": str(SESSION_DIR)})


# ---------------------------------------------------------------------------
# GET /api/classes/available — return classes discovered at login time
# ---------------------------------------------------------------------------


@bp.route("/classes/available")
def classes_available() -> Response:
    with _login_lock:
        classes = list(_login_state.get("classes", []))
    return jsonify(classes)


# ---------------------------------------------------------------------------
# POST /api/classes/save — persist selected classes to SelectedClass table
# ---------------------------------------------------------------------------


@bp.route("/classes/save", methods=["POST"])
def save_classes() -> Response:
    engine = current_app.config["DB_ENGINE"]
    data = request.get_json(silent=True) or {}
    classes: list[dict[str, str]] = data.get("classes", [])

    if not classes:
        return jsonify({"error": "No classes provided"}), 400  # type: ignore[return-value]

    with get_session(engine) as session:
        session.query(SelectedClass).delete()
        for c in classes:
            session.add(SelectedClass(
                name=c["name"],
                course_url=c["course_url"],
                active=True,
            ))

    return jsonify({"ok": True, "saved": len(classes)})


# ---------------------------------------------------------------------------
# POST /api/reset — wipe all student data and return to setup state
# ---------------------------------------------------------------------------


@bp.route("/reset", methods=["POST"])
def reset_data() -> Response:
    """Delete all assignments, scrape logs, and selected classes.

    Clears the in-process scrape/login state too so the UI is clean.
    Does NOT delete the Playwright session (user stays logged in to Google).
    """
    import shutil

    engine = current_app.config["DB_ENGINE"]

    with get_session(engine) as session:
        session.query(Assignment).delete()
        session.query(ScrapeLog).delete()
        session.query(SelectedClass).delete()

    # Clear in-process state
    with _scrape_lock:
        _scrape_state["running"] = False
        _scrape_state["progress"] = None
        _scrape_state["auto_download"] = False

    with _login_lock:
        _login_state["status"] = "idle"
        _login_state["classes"] = []
        _login_state["error"] = None

    # Remove downloaded PDFs if present
    from src.downloader import DOWNLOADS_DIR as _DOWNLOADS_DIR

    if _DOWNLOADS_DIR.exists():
        shutil.rmtree(_DOWNLOADS_DIR, ignore_errors=True)

    return jsonify({"ok": True})


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
