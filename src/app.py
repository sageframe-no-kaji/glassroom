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

    app.register_blueprint(dashboard_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(setup_bp)

    # Serve downloaded PDFs from the downloads/ folder
    from src.downloader import DOWNLOADS_DIR, attachment_type

    @app.route("/files/<path:filename>")
    def serve_download(filename: str) -> Response:
        return send_from_directory(str(DOWNLOADS_DIR), filename)

    # Jinja filter so templates can call {{ url | attachment_type }}
    app.jinja_env.filters["attachment_type"] = attachment_type

    return app


if __name__ == "__main__":
    create_app().run(host="0.0.0.0", port=3000, debug=True)
