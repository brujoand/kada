# kada

A small self-hosted quiz app. Feed it quizzes as JSON; a logged-in user picks
one, answers, and gets a score. Each attempt is saved per user, so you can see
how you have done over time.

A single FastAPI process serves a static frontend and a JSON API. No database —
quizzes and attempts are JSON files under a data directory.

## Run it

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
DATA_DIR=./data uvicorn kada.main:app --reload --port 8080
```

Open <http://localhost:8080>, type a name to log in, and take the bundled sample
quiz. On first start an empty `DATA_DIR/quizzes/` is seeded from the bundled
samples.

With Docker:

```bash
docker build --build-arg VERSION=0.0.0-dev -t kada .
docker run --rm -p 8080:8080 -v "$PWD/data:/data" kada
```

## Quizzes

A quiz is a JSON file in `DATA_DIR/quizzes/`. Drop one in, or `POST` it to
`/api/quizzes`. Four question types:

```json
{
  "id": "blandet",
  "title": "Blandet quiz",
  "questions": [
    {
      "type": "multiple_choice",
      "prompt": "Hva er 7 × 8?",
      "choices": ["54", "56", "63", "48"],
      "answer": 1
    },
    { "type": "true_false", "prompt": "12 er et partall.", "answer": true },
    { "type": "numeric", "prompt": "Hvor mange bein har en edderkopp?", "answer": 8, "tolerance": 0 },
    { "type": "free_text", "prompt": "Hovedstaden i Norge?", "accept": ["Oslo"] }
  ]
}
```

- **`id`** — lowercase letters, digits, `-`, `_`. Used as the filename. A question
  without its own `id` is numbered by position.
- **`multiple_choice`** — `answer` is the 0-based index of the correct `choice`.
- **`true_false`** — `answer` is `true` or `false`.
- **`numeric`** — `answer` is a number; an optional `tolerance` (default `0`)
  accepts anything within `± tolerance`.
- **`free_text`** — `accept` is a list of accepted answers. Matching ignores case
  and surrounding/repeated whitespace; add variants to the list for anything else.

The correct answers **never leave the server for a quiz you are about to take** —
they are disclosed only in the graded response, as feedback, after you submit.

## Authentication

Two modes, chosen by env:

- **Cookie (default).** Claim a display name, get an opaque session cookie. No
  accounts, no passwords — the right amount for a family quiz toy, and what you
  want locally.
- **Trusted proxy (`TRUSTED_PROXY_AUTH=1`).** Identity comes from `X-Auth-Sub`
  and `X-Auth-Email`, set by an OIDC-terminating proxy in front. Safe **only**
  where that proxy is the sole thing that can reach the process. See the docstring
  in `kada/auth.py`.

## Configuration

| Env | Default | Meaning |
|---|---|---|
| `DATA_DIR` | `/data` | Where quizzes and attempts live |
| `TRUSTED_PROXY_AUTH` | unset | `1` to trust proxy identity headers |
| `SECURE_COOKIE` | unset | `1` to mark the session cookie Secure (HTTPS) |
| `APP_VERSION` | `dev` | Stamped in at build time; do not set by hand |

## Releases

Merging to `main` runs semantic-release, which reads the Conventional Commits and
decides the version. Only if it publishes a release does the image get built and
pushed to GHCR, tagged with that exact version. There is deliberately no `latest`
tag.
