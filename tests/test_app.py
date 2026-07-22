"""The HTTP surface: the identity gate, the take-a-quiz flow, and persistence."""

from __future__ import annotations

PROXY = {"X-Auth-Sub": "kid1", "X-Auth-Email": "kari@home.no"}


def test_healthz_is_open(cookie_app):
    r = cookie_app.get("/healthz")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_api_requires_login(cookie_app):
    assert cookie_app.get("/api/quizzes").status_code == 401


def test_config_reports_mode(cookie_app, proxy_app):
    assert cookie_app.get("/api/config").json()["mode"] == "cookie"
    assert proxy_app.get("/api/config").json()["mode"] == "proxy"


def test_a_forged_identity_header_is_ignored(cookie_app):
    # In the default (cookie) deployment, X-Auth-* headers must buy nothing. If
    # this ever passes, header auth has leaked into cookie mode -- do not delete.
    assert cookie_app.get("/api/quizzes", headers=PROXY).status_code == 401


def test_cookie_login_then_use(cookie_app):
    assert cookie_app.post("/api/login", json={"name": "Ada"}).status_code == 200
    r = cookie_app.get("/api/quizzes")
    assert r.status_code == 200
    assert any(q["id"] == "blandet" for q in r.json()["quizzes"])


def test_proxy_header_grants_access(proxy_app):
    r = proxy_app.get("/api/quizzes", headers=PROXY)
    assert r.status_code == 200


def test_quiz_get_hides_answers(proxy_app):
    r = proxy_app.get("/api/quizzes/blandet", headers=PROXY)
    assert r.status_code == 200
    body = r.text
    assert "answer" not in body
    assert "accept" not in body
    assert "Oslo" not in body  # the free-text answer must not ship with the quiz


def test_submit_grades_and_persists(proxy_app):
    answers = {"q1": 1, "q2": True, "q3": 8, "q4": "Oslo"}
    r = proxy_app.post("/api/quizzes/blandet/submit", headers=PROXY, json={"answers": answers})
    assert r.status_code == 200
    body = r.json()
    assert body["score"] == 4
    assert body["total"] == 4

    hist = proxy_app.get("/api/me/attempts", headers=PROXY).json()["attempts"]
    assert len(hist) == 1
    assert hist[0]["quiz_id"] == "blandet"
    assert hist[0]["score"] == 4


def test_attempts_are_per_user(proxy_app):
    proxy_app.post("/api/quizzes/blandet/submit", headers=PROXY, json={"answers": {}})
    other = {"X-Auth-Sub": "kid2", "X-Auth-Email": "per@home.no"}
    assert proxy_app.get("/api/me/attempts", headers=other).json()["attempts"] == []


def test_submit_unknown_quiz_is_404(proxy_app):
    r = proxy_app.post("/api/quizzes/nope/submit", headers=PROXY, json={"answers": {}})
    assert r.status_code == 404


def test_create_quiz_via_api(proxy_app):
    quiz = {
        "id": "created",
        "title": "Created",
        "questions": [{"id": "a", "type": "true_false", "prompt": "ok?", "answer": True}],
    }
    assert proxy_app.post("/api/quizzes", headers=PROXY, json=quiz).status_code == 201
    assert proxy_app.get("/api/quizzes/created", headers=PROXY).status_code == 200


def test_create_quiz_rejects_bad_id(proxy_app):
    quiz = {
        "id": "../escape",
        "title": "Bad",
        "questions": [{"id": "a", "type": "true_false", "prompt": "ok?", "answer": True}],
    }
    assert proxy_app.post("/api/quizzes", headers=PROXY, json=quiz).status_code == 422


def test_spa_is_served(cookie_app):
    r = cookie_app.get("/")
    assert r.status_code == 200
    assert "kada" in r.text
