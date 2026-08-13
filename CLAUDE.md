# kada

A self-hosted quiz app: a single FastAPI process serves a static frontend and a
small JSON API. Quizzes are JSON on a data volume; a logged-in user takes one, the
server grades it, and each attempt is saved per user. See `README.md` to run it.

## Hard rules (never violate)

- **This is a PUBLIC repo. No secrets, ever.** API keys, tokens, private URLs,
  and internal hostnames come only from environment variables at runtime — never
  a default, a comment, a test fixture, or a commit. `gitleaks` runs in
  pre-commit and CI, but it is a backstop, not a licence to be careless.
- **No knowledge of any private deployment.** Do not reference a specific
  cluster, homelab, network, namespace, internal DNS name, or infrastructure
  repo. Defaults must be generic (`http://localhost:8080`, `/data`), so the app
  reads as a standalone project someone else could pick up. The deploy wiring
  lives in a separate infra repo, never here.
- **Never authenticate on a request header** unless the deployment can guarantee
  the header cannot come from a client. By default a header is set by whoever is
  talking to us, so trusting one (`X-Auth-*`, `X-Forwarded-User`, …) lets anybody
  be anybody. `test_a_forged_identity_header_is_ignored` fails if that is
  reintroduced in the default (cookie) mode — do not delete it. The one sanctioned
  exception is `TRUSTED_PROXY_AUTH=1`, which takes identity from
  `X-Auth-Sub`/`X-Auth-Email`; it is safe **only** behind a proxy that
  authenticates *and* is the sole thing able to reach the process. Only `sub` and
  `email` are trusted — a header backing an *optional* claim is one the client
  still controls.
- **Never push to `main`.** Every change lands via a branch and a PR, CI green
  before merge — **only the human merges**.
- **Conventional Commits decide the release, and a type that releases nothing
  ships nothing.** `feat` → minor, `fix`/`perf`/`revert` → patch, a
  `BREAKING CHANGE:` footer → major. Anything else (`chore`, `docs`, `refactor`,
  `test`, `ci`) mints **no version**, and with no version there is no image. **The
  squash/PR title is what semantic-release reads.** CI fails if a commit touches
  the app (`kada/`, `Dockerfile`, `requirements.txt`) but produces no release.

## Commands

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt pytest httpx

python -m pytest -q            # tests
ruff check . && ruff format --check .
pre-commit run --all-files     # ruff, gitleaks, formatting -- NOT commit-msg
git config core.hooksPath .githooks   # once per clone: makes both gates live
DATA_DIR=./data uvicorn kada.main:app --reload --port 8080
docker build --build-arg VERSION=0.0.0-dev -t kada .
```

## Layout

- `kada/auth.py` — the only source of identity. `CookieIdentity` (default,
  self-claimed name → opaque cookie) and `ProxyIdentity` (Pocket ID / OIDC via
  trusted headers). Read its module docstring before touching either.
- `kada/quiz.py` — the quiz model, `public_view` (the answerless view served to a
  quiz-taker), and `grade`. Pure; no I/O. **The public/graded split is the
  security model** — answers never ship with an in-flight quiz.
- `kada/store.py` — quizzes read from `DATA_DIR/quizzes/`, attempts written to
  `DATA_DIR/attempts/<hash-of-sub>/`. Bundled `samples/` seed an empty volume.
- `kada/main.py` — HTTP endpoints and the middleware that gates `/api/*` on an
  identity. Config is all env; `VERSION` is stamped in at build time.
- `kada/web/` — the frontend SPA (`index.html`, `app.js`, `styles.css`). Boots
  from `/api/config`, which decides whether to show the login screen.
- `tests/` — `test_quiz.py` (grading + the answers-never-leak guard),
  `test_auth.py` (identity units), `test_app.py` (the HTTP surface, incl. the
  forged-header guard).

## Gotchas

- **Answers must never reach the browser before grading.** `public_view` strips
  every answer field; `test_public_view_carries_no_answers` and
  `test_quiz_get_hides_answers` guard it. A quiz served with its answers is a
  lookup, not a test.
- **`VERSION` is build-time, not in the tree.** `pyproject.toml` says `0.0.0` and
  the image defaults to `dev`; semantic-release decides the real version *after*
  the commit and the Dockerfile bakes it in. CI checks the build-arg reaches the
  image. **No `latest` image tag** — deployments pin an exact version.
- **The Store is built from `DATA_DIR` at import.** Tests set `DATA_DIR` and
  reload `kada.main` in `conftest.py` *before* using the app — keep that ordering.
- **Sample quizzes seed only an EMPTY `quizzes/`** (`Store.seed_samples`); they
  never overwrite a volume that already has quizzes.
- **A quiz id is a filename component.** `store` validates it against a strict
  charset and finds quizzes by scanning + matching, never by building a path from
  the request — a crafted id cannot escape the directory.
