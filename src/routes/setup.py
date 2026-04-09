"""Setup flow routes — first-run experience."""

from __future__ import annotations

from flask import Blueprint, current_app, redirect, render_template, url_for

from src.db import get_session
from src.models import SelectedClass

bp = Blueprint("setup", __name__)


@bp.route("/setup")
def setup() -> str:
    """Multi-step first-run setup page.

    If selected classes already exist, redirect straight to the dashboard —
    the user has already completed setup.
    """
    engine = current_app.config["DB_ENGINE"]
    with get_session(engine) as session:
        has_classes = session.query(SelectedClass).count() > 0

    if has_classes:
        return redirect(url_for("dashboard.dashboard"))  # type: ignore[return-value]

    return render_template("setup.html")
