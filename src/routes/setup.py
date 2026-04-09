"""Setup flow routes — first-run experience."""

from __future__ import annotations

from flask import Blueprint, current_app, render_template

from src.db import get_session
from src.models import SelectedClass

bp = Blueprint("setup", __name__)


@bp.route("/setup")
def setup() -> str:
    """Setup / re-run page.

    Always renders. When classes are already configured, passes the current
    selection so the user can edit it before re-scraping. Also pulls any
    previously discovered (but not-yet-selected) classes from the login
    state so the full list is available without re-logging in.
    """
    engine = current_app.config["DB_ENGINE"]
    with get_session(engine) as session:
        selected = session.query(SelectedClass).filter(SelectedClass.active == True).all()  # noqa: E712

    has_classes = len(selected) > 0
    selected_classes = [{"name": sc.name, "course_url": sc.course_url} for sc in selected]

    # Merge with any classes discovered at login that aren't currently selected
    from src.routes.api import _login_lock, _login_state

    with _login_lock:
        discovered = list(_login_state.get("classes", []))

    selected_urls = {sc["course_url"] for sc in selected_classes}
    extra = [c for c in discovered if c["course_url"] not in selected_urls]
    available_classes = selected_classes + extra

    return render_template(
        "setup.html",
        has_classes=has_classes,
        selected_classes=selected_classes,
        available_classes=available_classes,
    )
