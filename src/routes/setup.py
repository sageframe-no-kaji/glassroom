"""Setup flow routes — first-run experience."""

from __future__ import annotations

from flask import Blueprint, current_app, render_template

from src.db import get_session
from src.models import SelectedClass

bp = Blueprint("setup", __name__)


@bp.route("/setup")
def setup() -> str:
    """Setup / re-run page.

    Always renders — never redirects. When classes are already configured,
    the template skips steps 1–2 and drops the user at step 3 (scrape).
    """
    engine = current_app.config["DB_ENGINE"]
    with get_session(engine) as session:
        selected = session.query(SelectedClass).filter(SelectedClass.active == True).all()  # noqa: E712

    has_classes = len(selected) > 0
    class_names = [sc.name for sc in selected]
    return render_template("setup.html", has_classes=has_classes, class_names=class_names)
