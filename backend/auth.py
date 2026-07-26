"""Google sign-in via Authlib's OAuth 2.0 / OIDC client.

Session-based: a successful login stores the user's id in Flask's signed
session cookie. No server-side session store — this app has exactly one
piece of session state to manage (who's signed in), and a signed cookie is
plenty for the traffic it sees.

Enforcement is a single before_request hook keyed on the Blueprint name
(``request.blueprint``), not a decorator on every view. That avoids stacking
an unrelated decorator underneath flask-smorest's own (``@blp.arguments``,
``@blp.response``, ...), which attach spec metadata to the view function —
safer not to find out the hard way whether that metadata survives another
layer of wrapping.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from authlib.integrations.flask_client import OAuth
from flask import Flask, redirect, request, session, url_for
from flask_smorest import abort
from sqlalchemy import select

import db
from models import User

oauth = OAuth()

# Blueprints that require a signed-in user. Checked by name rather than path
# prefix so it stays correct if a protected route ever moves.
_PROTECTED_BLUEPRINTS = {"tasks"}


def init_app(app: Flask) -> None:
    oauth.init_app(app)
    oauth.register(
        "google",
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )

    @app.before_request
    def _require_login() -> None:
        if request.blueprint in _PROTECTED_BLUEPRINTS and current_user() is None:
            abort(401, message="Login required")

    app.add_url_rule("/auth/login", "auth_login", _login)
    app.add_url_rule("/auth/google/callback", "auth_callback", _callback)
    app.add_url_rule("/auth/logout", "auth_logout", _logout, methods=["POST"])
    app.add_url_rule("/auth/me", "auth_me", _me)


def current_user() -> User | None:
    """The signed-in user for this request, or None."""
    user_id = session.get("user_id")
    if user_id is None:
        return None
    return db.session().get(User, user_id)


def _login() -> Any:
    redirect_uri = url_for("auth_callback", _external=True)
    # Without this, Google silently reuses whatever Google account is already
    # signed in in the browser and skips the chooser — logging out of this
    # app and back in always re-authenticates as the same Google account,
    # with no way to pick a different one.
    return oauth.google.authorize_redirect(redirect_uri, prompt="select_account")


def _callback() -> Any:
    token = oauth.google.authorize_access_token()
    claims = token["userinfo"]

    user = _upsert_user(claims)
    # Cleared rather than updated in place: a stale session key from a
    # previous, differently-shaped auth scheme should never carry forward.
    session.clear()
    session["user_id"] = user.id
    return redirect("/")


def _upsert_user(claims: dict[str, Any]) -> User:
    db_session = db.session()
    user = db_session.scalar(select(User).where(User.google_sub == claims["sub"]))
    if user is None:
        user = User(
            google_sub=claims["sub"],
            email=claims["email"],
            name=claims.get("name", claims["email"]),
            picture_url=claims.get("picture"),
            created_at=datetime.now(timezone.utc),
        )
        db_session.add(user)
    else:
        # Google is the source of truth for these; keep them fresh on every
        # login rather than only ever writing them once.
        user.email = claims["email"]
        user.name = claims.get("name", claims["email"])
        user.picture_url = claims.get("picture")
    db_session.commit()
    return user


def _logout() -> Any:
    """A plain <form method=post> target, like _callback above — no fetch()
    needed on the frontend, just a full-page navigation back to /."""
    session.clear()
    return redirect("/")


def _me() -> Any:
    user = current_user()
    if user is None:
        return {"authenticated": False}
    return {
        "authenticated": True,
        "name": user.name,
        "email": user.email,
        "picture_url": user.picture_url,
    }
