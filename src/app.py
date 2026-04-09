"""Flask application factory for Glassroom."""

from flask import Flask

from src.db import get_engine, init_db


def create_app() -> Flask:
    app = Flask(__name__, template_folder="templates", static_folder="static")

    # Initialise database on first run (idempotent)
    engine = get_engine()
    init_db(engine)
    app.config["DB_ENGINE"] = engine

    from src.routes.dashboard import bp as dashboard_bp
    from src.routes.api import bp as api_bp

    app.register_blueprint(dashboard_bp)
    app.register_blueprint(api_bp)

    return app


if __name__ == "__main__":
    create_app().run(host="0.0.0.0", port=3000, debug=True)
