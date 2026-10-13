import pytest

from app.scoring import score_answer


@pytest.mark.parametrize(
    ("difficulty", "correct", "seconds_left", "timed_out", "expected"),
    [
        ("Easy", True, 0, False, 10),
        ("Moderate", True, 20, False, 25),
        ("Difficult", True, 19.9, False, 34),
        ("Easy", True, 12, False, 13),
        ("Difficult", False, 20, False, 0),
        ("Moderate", True, 20, True, 0),
    ],
)
def test_server_scoring_cases(difficulty, correct, seconds_left, timed_out, expected):
    assert score_answer(difficulty, correct, seconds_left, timed_out) == expected


def test_unknown_difficulty_is_rejected():
    with pytest.raises(ValueError):
        score_answer("Expert", True, 20)
