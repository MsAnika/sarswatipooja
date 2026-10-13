from __future__ import annotations

import time

from app.state import QuizState


def test_simulated_session_transitions_through_blessing(isolated_db):
    state = QuizState(simulate=True)
    state.handle_gesture("count", count=5)
    assert state.state == "NAME"
    assert state.accept_name("Test Visitor") == "Test Visitor"
    state.handle_gesture("count", count=1)
    assert state.state == "HOWTO"

    state._show_question()
    assert state.state == "QUESTION"
    for _ in range(5):
        current = state.questions[state.question_index]
        state.handle_gesture("count", count=current["correct_index"] + 1)
        assert state.state == "FEEDBACK"
        state.tick(state.feedback_deadline + 0.01)
        assert state.state == "FEEDBACK"
        state.tick(state.feedback_deadline + 4.01)
    assert state.state == "RESULTS"
    state.tick(state.deadline + 0.01)
    assert state.state == "PRAYER"
    state.handle_gesture("namaste")
    assert state.state == "BLESSING"
    assert state.payload["name"] == "Test Visitor"
    state.tick(state.deadline + 0.01)
    assert state.state == "IDLE"


def test_name_is_sanitized_and_idle_resets(isolated_db):
    state = QuizState(simulate=True)
    state.handle_gesture("count", count=5)
    assert state.accept_name("  maya! kumari  ") == "Maya Kumari"
    state.last_activity = time.monotonic() - 61
    state.tick()
    assert state.state == "IDLE"
