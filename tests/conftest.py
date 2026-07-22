"""Shared fixtures. `create_app()` reads the environment once, so a cookie-mode
and a proxy-mode app can be stood up side by side with no shared state."""

from __future__ import annotations

import os
from pathlib import Path

import pytest


def _build(tmp_path: Path, **env: str):
    from fastapi.testclient import TestClient

    from kada.main import create_app

    os.environ["DATA_DIR"] = str(tmp_path)
    for key in ("TRUSTED_PROXY_AUTH", "SECURE_COOKIE", "APP_VERSION"):
        os.environ.pop(key, None)
    os.environ.update(env)

    app = create_app()
    app.state.store.seed_samples()
    return TestClient(app)


@pytest.fixture
def cookie_app(tmp_path):
    """The default deployment: cookie identity."""
    return _build(tmp_path)


@pytest.fixture
def proxy_app(tmp_path):
    """The clustered deployment: identity from trusted proxy headers."""
    return _build(tmp_path / "proxy", TRUSTED_PROXY_AUTH="1")
