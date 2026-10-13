from __future__ import annotations

import time

import pytest

from app.models import AppSetting, QuizSession
from app.state import QuizState


def test_simulated_session_transitions_through_blessing(isolated_db):
    state = QuizState(simulate=True)
    assert state.state == "NAME"
    state.handle_gesture("count", count=5)
    assert state.state == "NAME"
    assert state.accept_name("Test Visitor") == "Test Visitor"
    state.handle_gesture("count", count=1)
    assert state.state == "QUESTION"
    for _ in range(5):
        current = state.questions[state.question_index]
        state.handle_gesture("count", count=current["correct_index"] + 1)
        assert state.state == "FEEDBACK"
        state.tick(state.feedback_deadline + 0.01)
        assert state.state == "FEEDBACK"
        state.tick(state.feedback_deadline + 4.01)
    assert state.state == "RESULTS"
    assert len(state.answers) == 5
    assert state.payload["score"] == sum(answer["points"] for answer in state.answers)
    assert state.get_leaderboard()[0]["name"] == "Test Visitor"
    state.tick(state.deadline + 0.01)
    assert state.state == "PRAYER"
    state.handle_gesture("namaste")
    assert state.state == "BLESSING"
    assert state.payload["name"] == "Test Visitor"
    state.tick(state.deadline + 0.01)
    assert state.state == "NAME"


def test_name_confirmation_starts_quiz_and_two_fingers_restarts_name_capture(isolated_db):
    state = QuizState(simulate=True)
    state.accept_name("Test Visitor")
    state.handle_gesture("count", count=2)

    assert state.state == "NAME"
    assert state.player == ""
    assert state.payload["prompt"] == "Please say your name"

    state.accept_name("Test Visitor")
    state.handle_gesture("count", count=1)

    assert state.state == "QUESTION"
    assert state.payload["number"] == 1


def test_name_gesture_callback_publishes_release_guidance_and_retries_reset_lock(isolated_db):
    state = QuizState(simulate=True)
    reset_count = 0

    def reset_gesture_lock():
        nonlocal reset_count
        reset_count += 1

    state.set_gesture_reset(reset_gesture_lock)
    state.accept_name("Test Visitor")
    state.handle_gesture("count", count=5, locked=True)
    assert state.state == "NAME"

    state.handle_gesture("count", count=2, locked=True)
    assert reset_count == 1
    assert state.state == "NAME"
    assert state.player == ""

    state.handle_gesture("count", count=2, locked=False, awaiting_release=True)
    assert state.snapshot()["gesture"]["awaiting_release"]


def test_name_is_sanitized_and_idle_resets(isolated_db):
    state = QuizState(simulate=True)
    assert state.accept_name("  maya! kumari  ") == "Maya Kumari"
    state.last_activity = time.monotonic() - 61
    state.tick()
    assert state.state == "NAME"


def test_name_retry_never_invents_a_player(isolated_db):
    state = QuizState(simulate=True)

    for _ in range(3):
        state._retry_name()

    assert state.state == "NAME"
    assert state.player == ""
    assert "Devotee" not in state.payload.get("name", "")
    with pytest.raises(RuntimeError, match="confirmed player name"):
        state._finish_quiz()
    assert state.get_leaderboard() == []


def test_physical_name_screen_waits_for_browser_microphone_input(isolated_db):
    state = QuizState(simulate=False)
    state.tick()

    assert state.state == "NAME"
    assert state.player == ""
    assert "listening" not in state.payload


def test_legacy_generated_names_are_not_shown_on_leaderboard(isolated_db):
    with isolated_db() as db:
        db.add(QuizSession(name="Devotee 1", score=20, answer_time=12))
        db.commit()

    state = QuizState(simulate=True)

    assert state.get_leaderboard() == []


def test_old_default_gesture_settings_migrate_to_responsive_defaults(isolated_db):
    with isolated_db() as db:
        db.add_all(
            [
                AppSetting(key="confidence_threshold", value="0.75"),
                AppSetting(key="hold_ms", value="800"),
                AppSetting(key="vote_frames", value="15"),
            ]
        )
        db.commit()

    state = QuizState(simulate=True)

    assert state.settings["confidence_threshold"] == 0.65
    assert state.settings["hold_ms"] == 600
    assert state.settings["vote_frames"] == 8
