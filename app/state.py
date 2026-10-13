from __future__ import annotations

import json
import logging
import random
import re
import threading
import time
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from app.content import BlessingPicker, GODDESSES, load_json
from app.db import SessionLocal
from app.models import AppSetting, BlessingLog, GestureTimeout, QuizSession
from app.scoring import leaderboard_order, score_answer
from app.voice import sanitize_name

logger = logging.getLogger(__name__)
DEFAULT_SETTINGS: dict[str, Any] = {
    "confidence_threshold": 0.65,
    "hold_ms": 600,
    "vote_frames": 8,
    "namaste_distance": 0.35,
    "question_seconds": 20,
    "idle_seconds": 60,
    "prayer_seconds": 20,
    "blessing_seconds": 12,
    "sound_enabled": True,
}
DIFFICULTY_SLOTS = ["Moderate", "Easy", "Difficult", "Easy", "Difficult"]


class QuizState:
    def __init__(self, simulate: bool = False):
        self.simulate = simulate
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.timers_paused = False
        self.state = "NAME"
        self.payload: dict[str, Any] = {"prompt": "Please say your name"}
        self.version = 0
        self.last_activity = time.monotonic()
        self.deadline: float | None = None
        self.player = ""
        self.questions: list[dict[str, Any]] = []
        self.question_index = 0
        self.answers: list[dict[str, Any]] = []
        self.answer_started = 0.0
        self.selected_answer: int | None = None
        self.feedback_phase = ""
        self.feedback_deadline: float | None = None
        self.leaderboard_id: int | None = None
        self.player_rank: int | None = None
        self.previous_player_questions: set[str] = set()
        self.blessing_picker = BlessingPicker()
        self.timeout_count = 0
        self._settings_changed = None
        self._question_changed = None
        self._gesture_reset = None
        self._timers_paused_at: float | None = None
        self._leaderboard: list[dict[str, Any]] = []
        self.gesture = {
            "value": None, "confidence": 0.0, "progress": 0.0,
            "locked": False, "awaiting_release": False,
        }
        self._load_settings()
        self._leaderboard = self.get_leaderboard_from_db()
        self._load_blessing_history()
        self._publish()

    def _load_settings(self) -> None:
        with SessionLocal() as db:
            for key, value in DEFAULT_SETTINGS.items():
                if db.get(AppSetting, key) is None:
                    db.add(AppSetting(key=key, value=json.dumps(value)))
            previous_gesture_defaults = {
                "confidence_threshold": 0.75,
                "hold_ms": 800,
                "vote_frames": 15,
            }
            for key, old_value in previous_gesture_defaults.items():
                setting = db.get(AppSetting, key)
                if setting is not None and json.loads(setting.value) == old_value:
                    setting.value = json.dumps(DEFAULT_SETTINGS[key])
            db.commit()
            rows = db.scalars(select(AppSetting)).all()
            self.settings = {row.key: json.loads(row.value) for row in rows}

    def _load_blessing_history(self) -> None:
        with SessionLocal() as db:
            history = db.scalars(select(BlessingLog).order_by(BlessingLog.id.desc()).limit(10)).all()
        self.blessing_picker = BlessingPicker(
            [row.goddess for row in history[:3]],
            [row.slogan_id for row in history],
        )

    def _publish(self) -> None:
        self.version += 1

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "state": self.state,
                "payload": dict(self.payload),
                "version": self.version,
                "gesture": dict(self.gesture),
                "sound_enabled": bool(self.settings.get("sound_enabled", True)),
                "newest_finisher": self.leaderboard_id,
                "leaderboard": list(self._leaderboard),
                "now_playing": {
                    "name": self.player,
                    "question": self.question_index + 1 if self.state in {"QUESTION", "FEEDBACK"} else 0,
                    "total": 5,
                    "active": self.state not in {"NAME", "BLESSING"},
                    "idle": self.state == "NAME",
                },
            }

    def start(self) -> None:
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._run, name="quiz-state-timer", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)

    def set_timers_paused(self, paused: bool) -> None:
        with self._lock:
            now = time.monotonic()
            if paused and not self.timers_paused:
                self._timers_paused_at = now
            elif not paused and self.timers_paused and self._timers_paused_at is not None:
                elapsed = now - self._timers_paused_at
                if self.deadline is not None:
                    self.deadline += elapsed
                if self.feedback_deadline is not None:
                    self.feedback_deadline += elapsed
                if self.state == "QUESTION":
                    self.answer_started += elapsed
                    self.payload["ends_at"] = float(self.payload["ends_at"]) + elapsed
                self.last_activity += elapsed
                self._timers_paused_at = None
            self.timers_paused = paused
            self._publish()

    def _run(self) -> None:
        while not self._stop.wait(0.1):
            self.tick()

    def tick(self, now: float | None = None) -> None:
        with self._lock:
            if self.timers_paused:
                return
            now = time.monotonic() if now is None else now
            if self.state != "NAME" and now - self.last_activity >= self.settings["idle_seconds"]:
                self._timeout("idle_reset")
                self.reset()
            elif self.state == "QUESTION" and self.deadline is not None and now >= self.deadline:
                self._timeout("question_timeout")
                self._record_answer(None, timed_out=True)
            elif self.state == "RESULTS" and self.deadline is not None and now >= self.deadline:
                self.state = "PRAYER"
                self.payload = {"name": self.player, "prompt": "Take a moment. Join your hands in prayer to receive a blessing."}
                self.deadline = now + float(self.settings["prayer_seconds"])
                self.last_activity = now
                self._publish()
            elif self.state == "FEEDBACK" and self.feedback_deadline is not None and now >= self.feedback_deadline:
                if self.feedback_phase == "select":
                    self._show_feedback()
                else:
                    self._advance_after_feedback()
            elif self.state == "PRAYER" and self.deadline is not None and now >= self.deadline:
                self._reveal_blessing()
            elif self.state == "BLESSING" and self.deadline is not None and now >= self.deadline:
                self.reset()
    def set_settings_changed(self, callback) -> None:
        self._settings_changed = callback

    def set_question_changed(self, callback) -> None:
        self._question_changed = callback

    def set_gesture_reset(self, callback) -> None:
        self._gesture_reset = callback

    def _timeout(self, reason: str) -> None:
        self.timeout_count += 1
        with SessionLocal() as db:
            db.add(GestureTimeout(reason=reason))
            db.commit()

    def handle_gesture(
        self,
        event: str,
        *,
        count: int | None = None,
        confidence: float = 1.0,
        progress: float = 1.0,
        locked: bool = True,
        awaiting_release: bool = False,
    ) -> None:
        with self._lock:
            now = time.monotonic()
            self.gesture = {"value": count if event == "count" else event, "confidence": confidence,
                            "progress": progress, "locked": locked, "awaiting_release": awaiting_release}
            if event == "status":
                self._publish()
                return
            if event == "count":
                if self.state == "NAME" and locked:
                    if count == 1:
                        self._confirm_name()
                    elif count == 2:
                        self._retry_name()
                elif self.state == "QUESTION" and locked and count in (1, 2, 3, 4):
                    self._select_answer(count - 1)
            elif event == "namaste" and locked:
                if self.state == "PRAYER":
                    self._reveal_blessing()
            if locked and ((event == "namaste") or (event == "count" and count in (1, 2, 3, 4, 5))):
                self.last_activity = now
            self._publish()

    def accept_name(self, raw_name: str) -> str:
        with self._lock:
            if self.state != "NAME":
                raise ValueError("A name can only be entered while the kiosk is in NAME.")
            try:
                name = sanitize_name(raw_name)
            except ValueError:
                self._retry_name()
                raise
            if not name:
                self._retry_name()
                raise ValueError("Please say your name again.")
            self.player = name
            self.payload = {
                "name": name,
                "prompt": f"Is your name {name}?",
                "confirm_with": "1 = yes, 2 = say it again",
            }
            self.last_activity = time.monotonic()
            self._publish()
            return name

    def _retry_name(self) -> None:
        if self._gesture_reset:
            self._gesture_reset()
        self.player = ""
        self.payload = {"prompt": "Please say your name"}

    def _confirm_name(self) -> None:
        if self.player:
            self._show_question()

    def _choose_questions(self) -> list[dict[str, Any]]:
        questions = [q for q in load_json("questions.json") if q.get("active", True)]
        selected: list[dict[str, Any]] = []
        for difficulty in DIFFICULTY_SLOTS:
            choices = [q for q in questions if q.get("difficulty") == difficulty and q["id"] not in {item["id"] for item in selected}]
            if not choices:
                raise RuntimeError(f"Not enough active {difficulty} questions")
            fresh = [q for q in choices if q["id"] not in self.previous_player_questions]
            selected.append(random.choice(fresh or choices))
        return selected

    def _show_question(self) -> None:
        self.questions = self._choose_questions()
        self.previous_player_questions = {item["id"] for item in self.questions}
        self.question_index = 0
        self._begin_question()

    def _begin_question(self) -> None:
        if self._question_changed:
            self._question_changed()
        question = self.questions[self.question_index]
        self.state = "QUESTION"
        self.answer_started = time.monotonic()
        self.deadline = self.answer_started + float(self.settings["question_seconds"])
        self.feedback_deadline = None
        self.selected_answer = None
        self.payload = {
            "name": self.player, "number": self.question_index + 1, "total": 5,
            "question": question["text"], "options": question["options"],
            "difficulty": question["difficulty"], "seconds": self.settings["question_seconds"],
            "ends_at": time.time() + float(self.settings["question_seconds"]),
        }
        self.gesture.update({"progress": 0.0, "locked": False})
        self.last_activity = time.monotonic()
        self._publish()

    def _select_answer(self, selected: int) -> None:
        if self.state != "QUESTION" or self.selected_answer is not None:
            return
        self.selected_answer = selected
        self._record_answer(selected, timed_out=False, selection_only=True)
        self.state = "FEEDBACK"
        self.feedback_phase = "select"
        self.feedback_deadline = time.monotonic() + 1
        self.payload.update({"selected": selected, "feedback_phase": "select"})
        self.deadline = None
        self.last_activity = time.monotonic()

    def _record_answer(self, selected: int | None, timed_out: bool, selection_only: bool = False) -> None:
        question = self.questions[self.question_index]
        elapsed = min(float(self.settings["question_seconds"]), max(0.0, time.monotonic() - self.answer_started))
        seconds_left = max(0.0, float(self.settings["question_seconds"]) - elapsed)
        correct = selected == question["correct_index"] and not timed_out
        points = score_answer(question["difficulty"], correct, seconds_left, timed_out)
        answer = {"question_id": question["id"], "difficulty": question["difficulty"], "selected": selected,
                  "correct": correct, "timed_out": timed_out, "elapsed": elapsed,
                  "seconds_left": seconds_left, "points": points}
        if not selection_only:
            self.answers.append(answer)
            self._show_feedback(answer, question)
            return
        self.answers.append(answer)

    def _show_feedback(self, answer: dict[str, Any] | None = None, question: dict[str, Any] | None = None) -> None:
        if question is None:
            question = self.questions[self.question_index]
        if answer is None:
            answer = self.answers[-1]
        self.state = "FEEDBACK"
        self.feedback_phase = "feedback"
        self.feedback_deadline = time.monotonic() + 4
        correct = bool(answer["correct"])
        self.payload.update({
            "feedback_phase": "feedback",
            "correct": correct,
            "message": "Correct!" if correct else "Not quite",
            "points": answer["points"],
            "correct_index": question["correct_index"],
            "reason": question["reason"],
            "selected": answer["selected"],
        })
        self.last_activity = time.monotonic()
        self._publish()

    def _advance_after_feedback(self) -> None:
        self.question_index += 1
        if self.question_index < len(self.questions):
            self._begin_question()
        else:
            self._finish_quiz()

    def _finish_quiz(self) -> None:
        if not self.player:
            raise RuntimeError("Cannot save a quiz without a confirmed player name.")
        score = sum(answer["points"] for answer in self.answers)
        answer_time = sum(answer["elapsed"] for answer in self.answers)
        with SessionLocal() as db:
            entry = QuizSession(name=self.player, score=score, answer_time=answer_time, finished_at=datetime.now(timezone.utc))
            db.add(entry)
            db.commit()
            self.leaderboard_id = entry.id
            rows = self._leaderboard_rows(db)
            self._leaderboard = rows[:10]
            self.player_rank = next((i + 1 for i, row in enumerate(rows) if row["id"] == entry.id), len(rows))
        self.state = "RESULTS"
        self.payload = {"name": self.player, "score": score, "rank": self.player_rank, "prompt": f"You are #{self.player_rank}"}
        self.deadline = time.monotonic() + 7
        self.last_activity = time.monotonic()
        self._publish()

    def _reveal_blessing(self) -> None:
        if self.state != "PRAYER":
            return
        goddess, slogan = self.blessing_picker.pick(load_json("slogans.json"))
        image_file = next(filename for filename, label in GODDESSES if label == goddess)
        with SessionLocal() as db:
            db.add(BlessingLog(player_name=self.player, goddess=goddess, slogan_id=slogan["id"]))
            db.commit()
        self.state = "BLESSING"
        self.payload = {
            "name": self.player, "goddess": goddess, "image": f"/goddess/{image_file}",
            "slogan": slogan["text"], "prompt": f"Blessings, {self.player}",
        }
        self.deadline = time.monotonic() + float(self.settings["blessing_seconds"])
        self.last_activity = time.monotonic()
        self._publish()

    def reset(self) -> None:
        with self._lock:
            if self._gesture_reset:
                self._gesture_reset()
            self.state = "NAME"
            self.timers_paused = False
            self.payload = {"prompt": "Please say your name"}
            self.deadline = None
            self.feedback_deadline = None
            self.questions = []
            self.answers = []
            self.player = ""
            self.selected_answer = None
            self.gesture = {
                "value": None, "confidence": 0.0, "progress": 0.0,
                "locked": False, "awaiting_release": False,
            }
            self.last_activity = time.monotonic()
            self._publish()
            logger.info("Kiosk reset; ready to capture the next player's name")

    def skip_question(self) -> None:
        with self._lock:
            if self.state == "QUESTION":
                self._timeout("volunteer_skip")
                self._record_answer(None, timed_out=True)
                self.last_activity = time.monotonic()
                self._publish()

    def _leaderboard_rows(self, db) -> list[dict[str, Any]]:
        entries = db.scalars(select(QuizSession).where(QuizSession.hidden.is_(False))).all()
        return leaderboard_order([
            {"id": item.id, "name": item.name, "score": item.score, "answer_time": item.answer_time,
             "finished_at": item.finished_at.isoformat()} for item in entries
            if item.name.strip() and not re.fullmatch(r"Devotee \d+", item.name)
        ])

    def get_leaderboard_from_db(self) -> list[dict[str, Any]]:
        with SessionLocal() as db:
            return self._leaderboard_rows(db)[:10]

    def get_leaderboard(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._leaderboard)

    def set_settings(self, values: dict[str, Any]) -> None:
        with self._lock, SessionLocal() as db:
            for key, value in values.items():
                if key not in DEFAULT_SETTINGS:
                    raise ValueError(f"Unknown setting: {key}")
                if isinstance(DEFAULT_SETTINGS[key], bool):
                    if not isinstance(value, bool):
                        raise ValueError(f"{key} must be a boolean")
                else:
                    value = float(value)
                    if value <= 0:
                        raise ValueError(f"{key} must be positive")
                    if key in {"confidence_threshold", "namaste_distance"} and value > 1:
                        raise ValueError(f"{key} must not exceed 1")
                    if key == "hold_ms" and value > 5000:
                        raise ValueError("hold_ms must not exceed 5000")
                    if key == "vote_frames":
                        if not value.is_integer() or value > 120:
                            raise ValueError("vote_frames must be a whole number no greater than 120")
                        value = int(value)
                    if key.endswith("_seconds") and value > 3600:
                        raise ValueError(f"{key} must not exceed 3600")
                db.merge(AppSetting(key=key, value=json.dumps(value)))
                self.settings[key] = value
            db.commit()
            if self._settings_changed:
                self._settings_changed(self.settings)
            self._publish()
