"""Settings page route."""

from __future__ import annotations

from flask import Blueprint, render_template

from src.config import load_settings

bp = Blueprint("settings", __name__)


@bp.route("/settings")
def settings_page() -> str:
    s = load_settings()
    has_token = bool(s.get("baserow_token"))
    is_configured = bool(s.get("baserow_table_id"))
    return render_template(
        "settings.html",
        settings=s,
        has_token=has_token,
        is_configured=is_configured,
    )
