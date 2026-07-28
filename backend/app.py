"""Application factory and wiring for the Task API.

The OpenAPI document is *derived* from the marshmallow schemas and the
registered Blueprint routes — it is never hand-written, so it cannot drift
away from the implementation. Serve it at ``/openapi.json`` or write it to
disk explicitly with ``python app.py --dump-openapi``.
"""

from __future__ import annotations

import os
from typing import Any

from flask import Flask
from flask_smorest import Api
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

import auth
import db
import otel
from views import blp


def create_app(database_url: str | None = None) -> Flask:
    """
    Create and configure a Flask application instance.
    
    Parameters:
        database_url (str | None): Optional database URL that overrides the
            `DATABASE_URL` environment variable.
    
    Returns:
        Flask: The configured application instance.
    """
    # static/ lives at the project root, not under backend/: it is the handoff
    # point between the two halves — the frontend build writes into it and the
    # backend serves from it.
    app = Flask(__name__, static_folder="../static", static_url_path="/static")

    # Signs the session cookie. Dev fallback is fine for local testing and
    # CI — nothing sensitive lives behind it until a real SECRET_KEY is set
    # in Render's dashboard, same treatment as DATABASE_URL.
    app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key-not-for-production")
    app.config["GOOGLE_CLIENT_ID"] = os.environ.get("GOOGLE_CLIENT_ID", "dev-client-id")
    app.config["GOOGLE_CLIENT_SECRET"] = os.environ.get("GOOGLE_CLIENT_SECRET", "dev-client-secret")
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    # Defaults to secure-only. Local dev over plain http needs this off, via
    # SESSION_COOKIE_SECURE=false in .env, or the browser will never send the
    # cookie back and login will appear to silently fail.
    app.config["SESSION_COOKIE_SECURE"] = (
        os.environ.get("SESSION_COOKIE_SECURE", "true").lower() == "true"
    )

    app.config["API_TITLE"] = "Task API"
    app.config["API_VERSION"] = "1.0.0"
    app.config["OPENAPI_VERSION"] = "3.0.3"
    # Serve the generated document at /openapi.json and interactive docs at /docs.
    app.config["OPENAPI_URL_PREFIX"] = "/"
    app.config["OPENAPI_JSON_PATH"] = "openapi.json"
    app.config["OPENAPI_SWAGGER_UI_PATH"] = "/docs"
    app.config["OPENAPI_SWAGGER_UI_URL"] = "https://cdn.jsdelivr.net/npm/swagger-ui-dist/"
    app.config["API_SPEC_OPTIONS"] = {
        "info": {
            "title": "Task API",
            "version": "1.0.0",
            "description": "A simple task management API with CRUD operations.",
        },
        "servers": [{"url": "/"}],
    }

    db.init_app(app, database_url)
    # Needs the engine that init_app just attached, to instrument SQLAlchemy;
    # a no-op if OTEL_EXPORTER_OTLP_ENDPOINT isn't set (local dev, CI, tests).
    otel.init_app(app)
    auth.init_app(app)

    api = Api(app)
    api.register_blueprint(blp)
    # Kept for the --dump-openapi entry point below.
    app.extensions["smorest_api"] = api

    # flask-smorest registers a JSON error handler for HTTPException at Api()
    # init, so routing-level errors (GET /tasks/abc, PATCH /tasks/1) return
    # JSON rather than Werkzeug's HTML. No handler of our own is needed.

    @app.route("/")
    def index() -> Any:
        """Serve the Alpine.js demo front end.

        Deliberately outside the API Blueprint — it is a page, not an endpoint,
        so it is excluded from the OpenAPI document (see UNDOCUMENTED_ENDPOINTS
        in the tests).
        """
        return app.send_static_file("index.html")

    @app.get("/favicon.ico")
    def favicon() -> Any:
        """Serve the site's favicon to browser requests."""
        return app.send_static_file("favicon.ico")

    @app.get("/healthz")
    def healthz() -> Any:
        """Liveness: this process is running.

        Deliberately does *not* touch the database. A liveness probe that
        depends on Postgres would have the orchestrator kill and restart every
        container during a database blip, turning a brief outage into a
        restart storm.
        """
        return {"status": "ok"}

    @app.get("/readyz")
    def readyz() -> Any:
        """Readiness: dependencies are reachable, so send traffic here.

        This one *does* check the database, because a container that cannot
        reach Postgres should be pulled from the load balancer without being
        restarted.
        """
        session = db.session()
        try:
            session.execute(text("SELECT 1"))
        except SQLAlchemyError as exc:
            session.rollback()
            app.logger.warning("readiness check failed: %s", exc)
            return {"status": "unavailable", "detail": "database unreachable"}, 503
        return {"status": "ready"}

    return app


# Module-level instance for `gunicorn app:app` and `python app.py`.
app = create_app()


def _dump_openapi(path: str) -> None:
    """Write the generated OpenAPI document to *path*.

    Called only from the CLI — never at import time. Needs no database: the
    spec comes from the schemas and routes alone.
    """
    import json

    application = create_app()
    with application.app_context():
        spec = application.extensions["smorest_api"].spec.to_dict()

    with open(path, "w", encoding="utf-8") as handle:
        json.dump(spec, handle, indent=2)
        handle.write("\n")
    print(f"Wrote {path}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Task API")
    parser.add_argument(
        "--dump-openapi",
        metavar="PATH",
        nargs="?",
        const="openapi.json",
        help="Write the OpenAPI document to PATH (default: openapi.json) and exit.",
    )
    args = parser.parse_args()

    if args.dump_openapi:
        _dump_openapi(args.dump_openapi)
    else:
        app.run(debug=True)
