"""The quiz model, its answerless public view, and grading.

A quiz is plain JSON (see README for the schema). This module is the only thing
that ever sees the correct answers: `public_view` is what the browser is allowed
to know, and `grade` is what turns a set of submitted answers into a score. The
split is the whole security model -- if the answers were in the payload the page
renders, the quiz would be a lookup, not a test. `test_quiz.py` guards it.

Everything here is pure: no I/O, no time, no globals. Persistence lives in
store.py, the HTTP surface in main.py.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import Any

QUESTION_TYPES = {"multiple_choice", "true_false", "numeric", "free_text"}
MAX_CHOICES = 12


class InvalidQuiz(Exception):
    """A quiz file that cannot be trusted to grade. Message names what is wrong."""


@dataclass(frozen=True)
class Question:
    id: str
    type: str
    prompt: str
    # Only one of these is meaningful, decided by `type`. Kept as plain fields so a
    # question is a value, not a class hierarchy -- there are four types and they
    # will not grow into forty.
    choices: tuple[str, ...] = ()
    answer: Any = None
    accept: tuple[str, ...] = ()
    tolerance: float = 0.0


@dataclass(frozen=True)
class Quiz:
    id: str
    title: str
    questions: tuple[Question, ...]


def _norm(text: str) -> str:
    """Fold a free-text answer to compare it forgivingly.

    Case, surrounding and repeated whitespace, and Unicode form are noise when a
    child types "  Oslo " for "Oslo". Nothing else is stripped -- accents and
    punctuation can be meaningful, so the quiz's `accept` list carries any
    variants that should also pass.
    """
    return " ".join(unicodedata.normalize("NFC", str(text)).split()).casefold()


def parse_quiz(raw: dict) -> Quiz:
    """Validate a decoded JSON object into a Quiz, or raise InvalidQuiz.

    Strict on load so a malformed file dropped on the volume fails loudly here,
    once, rather than grading wrongly on every attempt.
    """
    if not isinstance(raw, dict):
        raise InvalidQuiz("quiz is not an object")

    quiz_id = raw.get("id")
    title = raw.get("title")
    if not isinstance(quiz_id, str) or not quiz_id.strip():
        raise InvalidQuiz("quiz.id must be a non-empty string")
    if not isinstance(title, str) or not title.strip():
        raise InvalidQuiz("quiz.title must be a non-empty string")

    raw_questions = raw.get("questions")
    if not isinstance(raw_questions, list) or not raw_questions:
        raise InvalidQuiz("quiz.questions must be a non-empty list")

    questions = tuple(_parse_question(q, i) for i, q in enumerate(raw_questions))
    seen: set[str] = set()
    for q in questions:
        if q.id in seen:
            raise InvalidQuiz(f"duplicate question id: {q.id}")
        seen.add(q.id)

    return Quiz(id=quiz_id, title=title, questions=questions)


def _parse_question(raw: Any, index: int) -> Question:
    where = f"questions[{index}]"
    if not isinstance(raw, dict):
        raise InvalidQuiz(f"{where} is not an object")

    qtype = raw.get("type")
    if qtype not in QUESTION_TYPES:
        raise InvalidQuiz(f"{where}.type must be one of {sorted(QUESTION_TYPES)}")

    prompt = raw.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise InvalidQuiz(f"{where}.prompt must be a non-empty string")

    # id defaults to the position, so a hand-written quiz need not number itself,
    # but a given id must be a string we can key answers by.
    qid = raw.get("id", str(index))
    if not isinstance(qid, str) or not qid.strip():
        raise InvalidQuiz(f"{where}.id must be a non-empty string")

    if qtype == "multiple_choice":
        return _parse_multiple_choice(raw, qid, prompt, where)
    if qtype == "true_false":
        if not isinstance(raw.get("answer"), bool):
            raise InvalidQuiz(f"{where}.answer must be true or false")
        return Question(id=qid, type=qtype, prompt=prompt, answer=raw["answer"])
    if qtype == "numeric":
        return _parse_numeric(raw, qid, prompt, where)
    return _parse_free_text(raw, qid, prompt, where)


def _parse_multiple_choice(raw: dict, qid: str, prompt: str, where: str) -> Question:
    choices = raw.get("choices")
    if not isinstance(choices, list) or not (2 <= len(choices) <= MAX_CHOICES):
        raise InvalidQuiz(f"{where}.choices must be a list of 2..{MAX_CHOICES} options")
    if not all(isinstance(c, str) and c.strip() for c in choices):
        raise InvalidQuiz(f"{where}.choices must all be non-empty strings")
    answer = raw.get("answer")
    if not isinstance(answer, int) or isinstance(answer, bool) or not 0 <= answer < len(choices):
        raise InvalidQuiz(f"{where}.answer must be a choice index 0..{len(choices) - 1}")
    return Question(
        id=qid, type="multiple_choice", prompt=prompt, choices=tuple(choices), answer=answer
    )


def _parse_numeric(raw: dict, qid: str, prompt: str, where: str) -> Question:
    answer = raw.get("answer")
    if isinstance(answer, bool) or not isinstance(answer, (int, float)):
        raise InvalidQuiz(f"{where}.answer must be a number")
    tolerance = raw.get("tolerance", 0)
    if isinstance(tolerance, bool) or not isinstance(tolerance, (int, float)) or tolerance < 0:
        raise InvalidQuiz(f"{where}.tolerance must be a number >= 0")
    return Question(
        id=qid, type="numeric", prompt=prompt, answer=float(answer), tolerance=float(tolerance)
    )


def _parse_free_text(raw: dict, qid: str, prompt: str, where: str) -> Question:
    accept = raw.get("accept")
    if not isinstance(accept, list) or not accept:
        raise InvalidQuiz(f"{where}.accept must be a non-empty list of accepted answers")
    if not all(isinstance(a, str) and a.strip() for a in accept):
        raise InvalidQuiz(f"{where}.accept must all be non-empty strings")
    return Question(id=qid, type="free_text", prompt=prompt, accept=tuple(accept))


def public_view(quiz: Quiz) -> dict:
    """What the browser may know about a quiz it is ABOUT to take: no answers.

    The correct index, the accepted strings, the target number -- none of it goes
    on the wire before grading. This is the answerless view, and it is the only
    one an in-flight quiz is served through.
    """
    return {
        "id": quiz.id,
        "title": quiz.title,
        "questions": [_public_question(q) for q in quiz.questions],
    }


def _public_question(q: Question) -> dict:
    out: dict[str, Any] = {"id": q.id, "type": q.type, "prompt": q.prompt}
    if q.type == "multiple_choice":
        out["choices"] = list(q.choices)
    return out


@dataclass(frozen=True)
class Result:
    score: int
    total: int
    # Per question id: whether it was right, and the correct answer -- disclosed
    # only NOW, in the graded response, never in public_view.
    per_question: dict[str, dict]


def _is_correct(q: Question, given: Any) -> bool:
    if given is None:
        return False
    if q.type == "multiple_choice":
        return isinstance(given, int) and not isinstance(given, bool) and given == q.answer
    if q.type == "true_false":
        return isinstance(given, bool) and given == q.answer
    if q.type == "numeric":
        if isinstance(given, bool) or not isinstance(given, (int, float)):
            return False
        return abs(float(given) - float(q.answer)) <= q.tolerance
    if q.type == "free_text":
        if not isinstance(given, str):
            return False
        return _norm(given) in {_norm(a) for a in q.accept}
    return False


def _correct_answer(q: Question) -> Any:
    """The answer to show as feedback after grading -- shape mirrors the input."""
    if q.type == "free_text":
        return list(q.accept)
    return q.answer


def grade(quiz: Quiz, answers: dict) -> Result:
    """Score submitted answers. `answers` maps question id -> the given value.

    A missing or ill-typed answer is simply wrong, never an error: a child who
    skips a question gets it marked wrong, not a 500.
    """
    if not isinstance(answers, dict):
        answers = {}
    per_question: dict[str, dict] = {}
    score = 0
    for q in quiz.questions:
        correct = _is_correct(q, answers.get(q.id))
        score += int(correct)
        per_question[q.id] = {"correct": correct, "correct_answer": _correct_answer(q)}
    return Result(score=score, total=len(quiz.questions), per_question=per_question)
