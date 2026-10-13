from __future__ import annotations

import math
from typing import Any

POINTS = {"Easy": 10, "Moderate": 20, "Difficult": 30}


def score_answer(difficulty: str, correct: bool, seconds_left: float, timed_out: bool = False) -> int:
    if not correct or timed_out:
        return 0
    if difficulty not in POINTS:
        raise ValueError(f"Unknown difficulty: {difficulty}")
    speed_bonus = min(5, math.floor(max(0.0, seconds_left) / 4.0))
    return POINTS[difficulty] + speed_bonus


def score_session(answers: list[dict[str, Any]]) -> tuple[int, float]:
    total = 0
    elapsed = 0.0
    for answer in answers:
        elapsed += float(answer.get("elapsed", 0.0))
        total += score_answer(
            str(answer["difficulty"]),
            bool(answer.get("correct", False)),
            float(answer.get("seconds_left", 0.0)),
            bool(answer.get("timed_out", False)),
        )
    return total, elapsed


def leaderboard_order(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(entries, key=lambda row: (-int(row["score"]), float(row["answer_time"]), row["finished_at"]))
