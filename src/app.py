"""Flask application factory for Glassroom."""

from __future__ import annotations

from flask import Flask, Response, send_from_directory

from src.db import get_engine, init_db


def create_app() -> Flask:
    app = Flask(__name__, template_folder="templates", static_folder="static")

    # Initialise database on first run (idempotent)
    engine = get_engine()
    init_db(engine)
    app.config["DB_ENGINE"] = engine

    from src.routes.dashboard import bp as dashboard_bp
    from src.routes.api import bp as api_bp
    from src.routes.setup import bp as setup_bp
    from src.routes.settings import bp as settings_bp

    app.register_blueprint(dashboard_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(setup_bp)
    app.register_blueprint(settings_bp)

    # Serve downloaded PDFs from the downloads/ folder
    from src.downloader import (
        DOWNLOADS_DIR,
        _class_folder_slug,
        _make_pdf_filename,
        attachment_type,
    )

    @app.route("/files/<path:filename>")
    def serve_download(filename: str) -> Response:
        return send_from_directory(str(DOWNLOADS_DIR), filename)

    # Jinja filter so templates can call {{ url | attachment_type }}
    app.jinja_env.filters["attachment_type"] = attachment_type

    # Jinja global: count non-empty attachment links in a newline-separated string
    def _count_attachments(links_str: object) -> int:
        if not links_str:
            return 0
        return len([ln for ln in str(links_str).split("\n") if ln.strip()])

    app.jinja_env.globals["count_attachments"] = _count_attachments

    # Jinja global: return /files/ URL for a downloaded assignment PDF, or None
    def _pdf_url_for_assignment(
        class_name: object, posted_date: object, title: object
    ) -> str | None:
        cs = str(class_name or "")
        pd = str(posted_date) if posted_date else None
        t = str(title or "")
        if not cs and not t:
            return None
        filename = _make_pdf_filename(pd, t)
        path = DOWNLOADS_DIR / _class_folder_slug(cs) / filename
        return f"/files/{_class_folder_slug(cs)}/{filename}" if path.exists() else None

    app.jinja_env.globals["pdf_url_for_assignment"] = _pdf_url_for_assignment

    return app


if __name__ == "__main__":
    create_app().run(host="0.0.0.0", port=3000, debug=True)
