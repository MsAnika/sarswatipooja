import random

from app.content import BlessingPicker, load_json


def test_blessings_avoid_recent_goddesses_and_slogans():
    picker = BlessingPicker()
    slogans = load_json("slogans.json")
    rng = random.Random(91)
    choices = [picker.pick(slogans, rng) for _ in range(20)]
    for index in range(3, len(choices)):
        assert choices[index][0] not in [goddess for goddess, _ in choices[index - 3:index]]
    for index in range(10, len(choices)):
        assert choices[index][1]["id"] not in [slogan["id"] for _, slogan in choices[index - 10:index]]


def test_question_bank_has_fifteen_per_difficulty_and_five_per_form():
    questions = load_json("questions.json")
    assert len(questions) >= 45
    for difficulty in ("Easy", "Moderate", "Difficult"):
        assert sum(q["difficulty"] == difficulty for q in questions) == 15
    for goddess in {q["goddess"] for q in questions}:
        assert sum(q["goddess"] == goddess for q in questions) == 5
