"""Identity units, independent of the HTTP surface."""

from __future__ import annotations

import pytest
from starlette.requests import Request

from kada.auth import (
    EMAIL_HEADER,
    SUB_HEADER,
    CookieIdentity,
    InvalidName,
    ProxyIdentity,
    Sessions,
    clean_name,
    display_name,
)


def _conn(headers=None, cookies=None):
    raw = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    if cookies:
        jar = "; ".join(f"{k}={v}" for k, v in cookies.items())
        raw.append((b"cookie", jar.encode()))
    return Request({"type": "http", "headers": raw})


def test_cookie_login_roundtrip():
    sessions = Sessions()
    token, user = sessions.login("Ada")
    assert user.name == "Ada"
    ident = CookieIdentity(sessions)
    assert ident.identify(_conn(cookies={"kada_session": token})).name == "Ada"
    assert ident.identify(_conn(cookies={"kada_session": "nope"})) is None
    assert ident.identify(_conn()) is None


def test_cookie_mode_ignores_identity_headers():
    # The whole point: in cookie mode a header proves nothing.
    ident = CookieIdentity(Sessions())
    conn = _conn(headers={SUB_HEADER: "attacker", EMAIL_HEADER: "a@b.c"})
    assert ident.identify(conn) is None


def test_proxy_trusts_both_headers():
    ident = ProxyIdentity()
    user = ident.identify(_conn(headers={SUB_HEADER: "abc", EMAIL_HEADER: "kid@home.no"}))
    assert user.sub == "oidc:abc"
    assert user.name == "kid"


def test_proxy_needs_both_headers():
    ident = ProxyIdentity()
    assert ident.identify(_conn(headers={SUB_HEADER: "abc"})) is None
    assert ident.identify(_conn(headers={EMAIL_HEADER: "kid@home.no"})) is None
    assert ident.identify(_conn()) is None


def test_proxy_rejects_folded_headers():
    # A comma means two values were folded into one -- do not guess.
    ident = ProxyIdentity()
    assert ident.identify(_conn(headers={SUB_HEADER: "a,b", EMAIL_HEADER: "kid@home.no"})) is None


def test_names_are_cleaned_and_bounded():
    assert clean_name("  Ada  Lovelace ") == "Ada Lovelace"
    with pytest.raises(InvalidName):
        clean_name("")
    with pytest.raises(InvalidName):
        clean_name("x" * 100)


def test_display_name_never_raises():
    assert display_name("weird@example.com") == "weird"
    assert display_name("@") == "friend"
