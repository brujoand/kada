"""Persistence: quizzes read from the data volume, attempts written to it.

Layout under DATA_DIR:

    quizzes/<file>.json      -- the quizzes; drop a file here or POST one via the API
    attempts/<user>/<file>   -- one JSON per graded attempt, partitioned by user

`<user>` is a hash of the identity `sub`, never the sub itself: the sub can be an
email-shaped OIDC string, and hashing it means no value a client influences is
ever spliced into a path. The raw sub is stored inside each record instead.

Bundled sample quizzes are seeded into an empty quizzes/ on startup, so a fresh
volume is not a blank app.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import time
from dataclasses import dataclass
from pathlib import Path

from .quiz import InvalidQuiz, Quiz, parse_quiz

SAMPLES_DIR = Path(__file__).resolve().parent / "samples"

# A quiz id is used as a filename component; keep it to characters that are safe
# and portable. Content authored by us, but validated anyway.
_SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


@dataclass(frozen=True)
class Attempt:
    quiz_id: str
    quiz_title: str
    sub: str
    name: str
    score: int
    total: int
    at: float  # unix seconds


def _user_key(sub: str) -> str:
    return hashlib.sha256(sub.encode("utf-8")).hexdigest()[:32]


class Store:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir)
        self.quizzes_dir = self.data_dir / "quizzes"
        self.attempts_dir = self.data_dir / "attempts"

    def ensure_dirs(self) -> None:
        self.quizzes_dir.mkdir(parents=True, exist_ok=True)
        self.attempts_dir.mkdir(parents=True, exist_ok=True)

    def seed_samples(self) -> None:
        """Populate an empty quizzes/ from the bundled samples. Never overwrites."""
        self.ensure_dirs()
        if any(self.quizzes_dir.glob("*.json")):
            return
        for src in sorted(SAMPLES_DIR.glob("*.json")):
            (self.quizzes_dir / src.name).write_text(src.read_text(encoding="utf-8"))

    def list_quizzes(self) -> list[Quiz]:
        """Every quiz that parses, sorted by title. A malformed file is skipped,
        not fatal -- one bad drop must not take the whole list down."""
        out: list[Quiz] = []
        for path in sorted(self.quizzes_dir.glob("*.json")):
            try:
                out.append(parse_quiz(json.loads(path.read_text(encoding="utf-8"))))
            except (InvalidQuiz, json.JSONDecodeError, OSError):
                continue
        out.sort(key=lambda q: q.title.casefold())
        return out

    def load_quiz(self, quiz_id: str) -> Quiz | None:
        """The quiz whose own id matches, found by scanning -- never by building a
        path from the request, so a crafted id cannot escape the directory."""
        if not _SAFE_ID.match(quiz_id):
            return None
        for quiz in self.list_quizzes():
            if quiz.id == quiz_id:
                return quiz
        return None

    def save_quiz(self, raw: dict) -> Quiz:
        """Validate and persist a quiz posted via the API. Raises InvalidQuiz on a
        bad payload or an unusable id."""
        quiz = parse_quiz(raw)
        if not _SAFE_ID.match(quiz.id):
            raise InvalidQuiz(
                "quiz.id must be lowercase alphanumeric with - or _ (used as a filename)"
            )
        self.ensure_dirs()
        (self.quizzes_dir / f"{quiz.id}.json").write_text(
            json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return quiz

    def record_attempt(self, attempt: Attempt) -> None:
        user_dir = self.attempts_dir / _user_key(attempt.sub)
        user_dir.mkdir(parents=True, exist_ok=True)
        name = f"{attempt.quiz_id}-{int(attempt.at)}-{secrets.token_hex(4)}.json"
        (user_dir / name).write_text(
            json.dumps(
                {
                    "quiz_id": attempt.quiz_id,
                    "quiz_title": attempt.quiz_title,
                    "sub": attempt.sub,
                    "name": attempt.name,
                    "score": attempt.score,
                    "total": attempt.total,
                    "at": attempt.at,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def attempts_for(self, sub: str) -> list[Attempt]:
        """This user's attempts, newest first."""
        user_dir = self.attempts_dir / _user_key(sub)
        if not user_dir.is_dir():
            return []
        out: list[Attempt] = []
        for path in user_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                out.append(
                    Attempt(
                        quiz_id=data["quiz_id"],
                        quiz_title=data["quiz_title"],
                        sub=data["sub"],
                        name=data["name"],
                        score=int(data["score"]),
                        total=int(data["total"]),
                        at=float(data["at"]),
                    )
                )
            except (json.JSONDecodeError, KeyError, ValueError, OSError):
                continue
        out.sort(key=lambda a: a.at, reverse=True)
        return out


def now() -> float:
    return time.time()
