"""kada -- a self-hosted quiz app.

A single FastAPI process serves a static frontend and a small JSON API. Quizzes
are JSON on the data volume (drop a file or POST one); a logged-in user takes a
quiz, the server grades it, and each attempt is saved under that user's id so a
child can see how they have done over time.

Who "a user" is comes from auth.py: a self-declared name behind a cookie by
default, or a Pocket ID / OIDC identity when a trusting proxy sits in front. The
app itself carries no infrastructure -- everything is env, and VERSION is stamped
in at build time.

The app is built by `create_app()`, which reads the environment once and binds
the identity strategy and the store onto `app.state`. Nothing that varies between
deployments is a module global, so a test can stand up an isolated cookie-mode and
proxy-mode app side by side without either leaking into the other.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from .auth import (
    COOKIE_NAME,
    SESSION_TTL,
    CookieIdentity,
    InvalidName,
    ProxyIdentity,
    Sessions,
    User,
)
from .quiz import InvalidQuiz, grade, public_view
from .store import Attempt, Store, now

WEB_DIR = Path(__file__).resolve().parent / "web"

# Endpoints reachable without an identity: the config the frontend boots from and
# the login/logout flow itself. Everything else under /api/ requires one.
PUBLIC_API_PATHS = {"/api/config", "/api/login", "/api/logout"}


def create_app() -> FastAPI:
    data_dir = Path(os.environ.get("DATA_DIR", "/data"))
    # Stamped into the image at build time by the Dockerfile's ARG, from the same
    # version semantic-release tagged the image with. "dev" from a checkout.
    version = os.environ.get("APP_VERSION", "dev")
    # Set SECURE_COOKIE=1 when serving over HTTPS so the session cookie is marked
    # Secure. Off by default: a Secure cookie is silently dropped over plain HTTP,
    # which would make http://localhost unusable.
    secure_cookie = os.environ.get("SECURE_COOKIE") == "1"
    # Take identity from a trusting proxy's headers instead of our own cookie.
    # Safe ONLY where that proxy is the sole thing that can reach this process --
    # read auth.py's module docstring before setting it.
    trusted_proxy_auth = os.environ.get("TRUSTED_PROXY_AUTH") == "1"

    sessions = Sessions()  # unused, and permanently empty, in proxy mode
    identity = ProxyIdentity() if trusted_proxy_auth else CookieIdentity(sessions)
    store = Store(data_dir)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        store.seed_samples()
        yield

    app = FastAPI(title="kada", lifespan=lifespan)
    app.state.identity = identity
    app.state.sessions = sessions
    app.state.store = store
    app.state.version = version
    app.state.secure_cookie = secure_cookie

    @app.middleware("http")
    async def require_identity(request: Request, call_next):
        """Gate the API on an identity, and stash who it is for the handlers.

        Static files and the SPA shell are served freely -- the page loads, asks
        /api/config who it is, and shows a login screen if the answer is nobody.
        """
        request.state.user = identity.identify(request)
        path = request.url.path
        if path.startswith("/api/") and path not in PUBLIC_API_PATHS and request.state.user is None:
            return JSONResponse({"error": "login_required"}, status_code=401)
        return await call_next(request)

    # --- Auth surface -------------------------------------------------------

    @app.get("/api/config")
    async def config(request: Request) -> dict:
        user = identity.identify(request)
        return {
            "version": version,
            "mode": identity.mode,
            "login_enabled": identity.login_enabled,
            "user": {"name": user.name} if user else None,
        }

    @app.post("/api/login")
    async def login(request: Request) -> Response:
        if not identity.login_enabled:
            # In proxy mode there is no login form; the proxy already decided.
            return JSONResponse({"error": "login_disabled"}, status_code=404)
        body = await _json(request)
        try:
            token, user = sessions.login(str(body.get("name", "")))
        except InvalidName as exc:
            return JSONResponse({"error": exc.as_dict()}, status_code=400)
        resp = JSONResponse({"user": {"name": user.name}})
        resp.set_cookie(
            COOKIE_NAME,
            token,
            max_age=SESSION_TTL,
            httponly=True,
            samesite="lax",
            secure=secure_cookie,
        )
        return resp

    @app.post("/api/logout")
    async def logout(request: Request) -> Response:
        sessions.logout(request.cookies.get(COOKIE_NAME))
        resp = JSONResponse({"ok": True})
        resp.delete_cookie(COOKIE_NAME)
        return resp

    # --- Quizzes ------------------------------------------------------------

    @app.get("/api/quizzes")
    async def list_quizzes(request: Request) -> dict:
        return {
            "quizzes": [
                {"id": q.id, "title": q.title, "questions": len(q.questions)}
                for q in store.list_quizzes()
            ]
        }

    @app.get("/api/quizzes/{quiz_id}")
    async def get_quiz(request: Request, quiz_id: str) -> Response:
        quiz = store.load_quiz(quiz_id)
        if quiz is None:
            return JSONResponse({"error": "not_found"}, status_code=404)
        # public_view carries NO answers: served to be taken, not read.
        return JSONResponse(public_view(quiz))

    @app.post("/api/quizzes/{quiz_id}/submit")
    async def submit_quiz(request: Request, quiz_id: str) -> Response:
        user: User = request.state.user
        quiz = store.load_quiz(quiz_id)
        if quiz is None:
            return JSONResponse({"error": "not_found"}, status_code=404)
        body = await _json(request)
        result = grade(quiz, body.get("answers", {}))
        store.record_attempt(
            Attempt(
                quiz_id=quiz.id,
                quiz_title=quiz.title,
                sub=user.sub,
                name=user.name,
                score=result.score,
                total=result.total,
                at=now(),
            )
        )
        return JSONResponse(
            {"score": result.score, "total": result.total, "results": result.per_question}
        )

    @app.post("/api/quizzes")
    async def create_quiz(request: Request) -> Response:
        """Author a quiz by POSTing its JSON. The other way in is dropping a file
        on the volume; both land in the same place."""
        body = await _json(request)
        try:
            quiz = store.save_quiz(body)
        except InvalidQuiz as exc:
            return JSONResponse({"error": str(exc)}, status_code=422)
        return JSONResponse({"id": quiz.id, "title": quiz.title}, status_code=201)

    @app.get("/api/me/attempts")
    async def my_attempts(request: Request) -> dict:
        user: User = request.state.user
        return {
            "attempts": [
                {
                    "quiz_id": a.quiz_id,
                    "quiz_title": a.quiz_title,
                    "score": a.score,
                    "total": a.total,
                    "at": a.at,
                }
                for a in store.attempts_for(user.sub)
            ]
        }

    @app.get("/healthz")
    async def healthz() -> dict:
        return {"ok": True, "version": version}

    # The SPA and its assets. Mounted last so every API route above wins the
    # match; html=True serves index.html at "/".
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
    return app


async def _json(request: Request) -> dict:
    try:
        body = await request.json()
    except (ValueError, TypeError):
        return {}
    return body if isinstance(body, dict) else {}


app = create_app()
