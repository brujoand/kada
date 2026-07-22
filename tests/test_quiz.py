"""The grading core and its answerless public view -- the security-critical part."""

from __future__ import annotations

import pytest

from kada.quiz import InvalidQuiz, grade, parse_quiz, public_view

QUIZ = {
    "id": "mix",
    "title": "Mix",
    "questions": [
        {
            "id": "mc",
            "type": "multiple_choice",
            "prompt": "2+2?",
            "choices": ["3", "4", "5"],
            "answer": 1,
        },
        {"id": "tf", "type": "true_false", "prompt": "sky is blue", "answer": True},
        {"id": "num", "type": "numeric", "prompt": "pi-ish", "answer": 3.14, "tolerance": 0.01},
        {"id": "txt", "type": "free_text", "prompt": "capital", "accept": ["Oslo", "OSLO by"]},
    ],
}


def test_public_view_carries_no_answers():
    view = public_view(parse_quiz(QUIZ))
    serialized = repr(view)
    # None of the answer keys, and no accepted string, may appear in what the
    # browser is handed before grading.
    assert "answer" not in serialized
    assert "accept" not in serialized
    assert "tolerance" not in serialized
    assert "Oslo" not in serialized
    mc = next(q for q in view["questions"] if q["id"] == "mc")
    assert mc["choices"] == ["3", "4", "5"]  # choices are shown; the index is not


def test_all_correct():
    result = grade(parse_quiz(QUIZ), {"mc": 1, "tf": True, "num": 3.145, "txt": "  oslo "})
    assert result.score == 4
    assert result.total == 4
    assert all(r["correct"] for r in result.per_question.values())


def test_all_wrong_or_missing():
    result = grade(parse_quiz(QUIZ), {"mc": 0, "tf": False, "num": 3.2})  # txt omitted
    assert result.score == 0
    assert result.per_question["txt"]["correct"] is False


def test_numeric_tolerance_edge():
    q = parse_quiz(QUIZ)
    assert grade(q, {"num": 3.15}).per_question["num"]["correct"] is True  # exactly at tolerance
    assert grade(q, {"num": 3.16}).per_question["num"]["correct"] is False


def test_free_text_is_forgiving_but_bounded():
    q = parse_quiz(QUIZ)
    assert grade(q, {"txt": "OSLO BY"}).per_question["txt"]["correct"] is True
    assert grade(q, {"txt": "Bergen"}).per_question["txt"]["correct"] is False


def test_true_false_rejects_non_bool():
    # A "1" is not a True: multiple_choice and true_false must not be confusable.
    q = parse_quiz(QUIZ)
    assert grade(q, {"tf": 1}).per_question["tf"]["correct"] is False


def test_multiple_choice_rejects_bool():
    q = parse_quiz(QUIZ)
    assert grade(q, {"mc": True}).per_question["mc"]["correct"] is False


def test_correct_answer_disclosed_only_in_result():
    result = grade(parse_quiz(QUIZ), {})
    assert result.per_question["mc"]["correct_answer"] == 1
    assert result.per_question["txt"]["correct_answer"] == ["Oslo", "OSLO by"]


@pytest.mark.parametrize(
    "bad",
    [
        {
            "id": "",
            "title": "t",
            "questions": [{"type": "true_false", "prompt": "p", "answer": True}],
        },
        {"id": "x", "title": "t", "questions": []},
        {"id": "x", "title": "t", "questions": [{"type": "bogus", "prompt": "p"}]},
        {
            "id": "x",
            "title": "t",
            "questions": [
                {"type": "multiple_choice", "prompt": "p", "choices": ["a"], "answer": 0}
            ],
        },
        {
            "id": "x",
            "title": "t",
            "questions": [
                {"type": "multiple_choice", "prompt": "p", "choices": ["a", "b"], "answer": 5}
            ],
        },
        {
            "id": "x",
            "title": "t",
            "questions": [{"type": "numeric", "prompt": "p", "answer": "nope"}],
        },
        {
            "id": "x",
            "title": "t",
            "questions": [{"type": "free_text", "prompt": "p", "accept": []}],
        },
    ],
)
def test_malformed_quizzes_are_rejected(bad):
    with pytest.raises(InvalidQuiz):
        parse_quiz(bad)


def test_duplicate_question_ids_rejected():
    with pytest.raises(InvalidQuiz):
        parse_quiz(
            {
                "id": "x",
                "title": "t",
                "questions": [
                    {"id": "same", "type": "true_false", "prompt": "a", "answer": True},
                    {"id": "same", "type": "true_false", "prompt": "b", "answer": False},
                ],
            }
        )
