from __future__ import annotations

import builtins
from types import SimpleNamespace

from app.gesture import CameraWorker, GestureLock, count_fingers, frame_is_too_dark, hand_inside_guide, namaste_detected


def make_hand(extended: int) -> list[tuple[float, float]]:
    points = [(0.5, 0.5)] * 21
    points[17] = (0.7, 0.5)
    for number, (mcp, pip, tip) in enumerate(((5, 6, 8), (9, 10, 12), (13, 14, 16), (17, 18, 20))):
        x = 0.35 + number * 0.08
        points[mcp] = (x, 0.55)
        if number < extended:
            points[pip] = (x, 0.65)
            points[tip] = (x, 0.8)
        else:
            points[pip] = (x, 0.54)
            points[tip] = (x, 0.53)
    if extended == 5:
        points[2], points[3], points[4] = (0.39, 0.58), (0.32, 0.55), (0.25, 0.52)
    else:
        points[2], points[3], points[4] = (0.4, 0.55), (0.43, 0.53), (0.44, 0.54)
    return points


def test_count_fingers_from_zero_through_five():
    for count in range(6):
        assert count_fingers(make_hand(count)) == count


def test_dark_camera_frames_are_reported():
    class Frame:
        def __init__(self, brightness):
            self.brightness = brightness

        def mean(self):
            return self.brightness

    assert frame_is_too_dark(Frame(0.1))
    assert not frame_is_too_dark(Frame(24))


def test_hand_guide_includes_wrist_near_camera_frame_edges():
    assert hand_inside_guide((0.5, 0.95))
    assert hand_inside_guide((0.94, 0.5))
    assert not hand_inside_guide((0.97, 0.5))


def test_finger_count_is_rotation_robust():
    points = make_hand(3)
    rotated = []
    for x, y in points:
        dx, dy = x - 0.5, y - 0.5
        rotated.append((0.5 - dy, 0.5 + dx))
    assert count_fingers(rotated) == 3


def test_namaste_requires_two_close_upward_hands():
    left = [(0.48, 0.72)] * 21
    right = [(0.52, 0.72)] * 21
    for hand, x in ((left, 0.48), (right, 0.52)):
        hand[9] = (x, 0.52)
        hand[8] = (x, 0.3)
    assert namaste_detected([left, right])
    assert not namaste_detected([left])
    far_hand = [((x + 0.4), y) for x, y in right]
    assert not namaste_detected([left, far_hand])


def test_lock_requires_stable_hold_and_resets_below_confidence():
    lock = GestureLock(window=15, min_confidence=0.75, hold_seconds=0.8)
    for frame in range(12):
        result = lock.update(1, now=frame * 0.05)
    assert result.confidence >= 0.75
    for frame in range(12, 16):
        result = lock.update(2, now=frame * 0.05)
    assert result.confidence < 0.75
    assert result.progress == 0
    assert not result.locked

    locked_once = False
    for frame in range(40):
        result = lock.update(1, now=1.0 + frame * 0.05)
        locked_once = locked_once or result.locked
    assert locked_once


def test_locked_gesture_rearms_immediately_when_finger_count_changes():
    lock = GestureLock(window=1, min_confidence=0.5, hold_seconds=0.1)
    assert not lock.update(5, score=1, now=0).locked
    assert lock.update(5, score=1, now=0.1).locked

    changed = lock.update(1, score=1, now=0.2)

    assert changed.value == 1
    assert not changed.locked
    assert changed.progress == 0
    assert lock.candidate == 1
    assert lock.update(1, score=1, now=0.3).locked


def test_palm_lock_does_not_prevent_name_confirmation_with_one_finger():
    lock = GestureLock(window=1, min_confidence=0.5, hold_seconds=0.1)
    assert not lock.update(5, score=1, now=0).locked
    assert lock.update(5, score=1, now=0.1).locked

    assert not lock.update(1, score=1, now=0.2).locked
    assert lock.candidate == 1
    assert lock.update(1, score=1, now=0.3).locked


def test_transition_requires_hand_release_before_next_gesture():
    lock = GestureLock(window=1, min_confidence=0.5, hold_seconds=0.1)
    assert not lock.update(1, score=1, now=0).locked
    assert lock.update(1, score=1, now=0.1).locked
    lock.require_release()

    held = lock.update(2, score=1, now=0.2)
    assert held.awaiting_release
    assert not held.locked
    still_held_but_other_detection = lock.update(None, now=0.3, hand_present=True)
    assert still_held_but_other_detection.awaiting_release
    assert not still_held_but_other_detection.locked

    released = lock.update(None, now=0.4, hand_present=False)
    assert not released.awaiting_release
    assert lock.update(2, score=1, now=0.5).progress == 0
    assert lock.update(2, score=1, now=0.6).locked


def test_camera_reports_missing_mediapipe(monkeypatch):
    original_import = builtins.__import__

    def without_mediapipe(name, *args, **kwargs):
        if name == "mediapipe":
            raise ModuleNotFoundError("No module named 'mediapipe'", name="mediapipe")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_mediapipe)
    worker = CameraWorker(lambda *_args, **_kwargs: None)

    worker._run()

    assert "MediaPipe is not installed" in worker.status


def test_camera_reports_mediapipe_without_legacy_hands(monkeypatch):
    original_import = builtins.__import__

    def without_hands_api(name, *args, **kwargs):
        if name == "mediapipe":
            return SimpleNamespace(__version__="1.1.0")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_hands_api)
    worker = CameraWorker(lambda *_args, **_kwargs: None)

    worker._run()

    assert "does not include the Hands API" in worker.status


def test_camera_skips_open_backend_that_returns_no_frames(monkeypatch):
    import app.gesture as gesture

    captures = []

    class Capture:
        def __init__(self, backend):
            self.backend = backend
            self.released = False
            captures.append(self)

        def isOpened(self):
            return True

        def set(self, *_args):
            return True

        def read(self):
            return self.backend == 700, object()

        def release(self):
            self.released = True

    class FakeCV:
        CAP_DSHOW = 700
        CAP_MSMF = 1400
        CAP_PROP_FPS = 5

        @staticmethod
        def VideoCapture(*args):
            return Capture(args[-1] if len(args) > 1 else None)

    monkeypatch.setattr(gesture.sys, "platform", "win32")
    capture = CameraWorker(lambda *_args, **_kwargs: None)._open_capture(FakeCV)

    assert capture is captures[1]
    assert captures[0].released
    assert not capture.released


def test_camera_gestures_lock_quickly_with_defaults(isolated_db):
    from app.state import QuizState

    state = QuizState(simulate=True)
    worker = CameraWorker(state.handle_gesture)
    worker.configure(state.settings)
    locked = False
    for frame in range(35):
        update = worker.lock.update(5, score=0.98, now=frame / 30)
        locked = locked or update.locked

    assert state.settings["vote_frames"] == 8
    assert state.settings["hold_ms"] == 600
    assert locked
