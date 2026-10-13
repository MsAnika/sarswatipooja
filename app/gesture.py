from __future__ import annotations

import logging
import math
import sys
import threading
import time
from collections import Counter, deque
from dataclasses import dataclass
from typing import Callable, Iterable

logger = logging.getLogger(__name__)

FINGER_JOINTS = ((8, 6), (12, 10), (16, 14), (20, 18))


def distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def frame_is_too_dark(frame) -> bool:
    return float(frame.mean()) < 8


def hand_inside_guide(wrist: tuple[float, float]) -> bool:
    return 0.05 <= wrist[0] <= 0.95 and 0.05 <= wrist[1] <= 0.98


def _joint_alignment(mcp: tuple[float, float], pip: tuple[float, float], tip: tuple[float, float]) -> float:
    proximal = (pip[0] - mcp[0], pip[1] - mcp[1])
    distal = (tip[0] - pip[0], tip[1] - pip[1])
    lengths = math.hypot(*proximal) * math.hypot(*distal)
    if lengths == 0:
        return -1.0
    return (proximal[0] * distal[0] + proximal[1] * distal[1]) / lengths


def count_fingers(points: Iterable[tuple[float, float]]) -> int:
    """Count extended fingers using both fingertip reach and finger-joint alignment."""
    landmarks = list(points)
    if len(landmarks) < 21:
        raise ValueError("At least 21 hand landmarks are required")
    wrist = landmarks[0]
    finger_mcps = (5, 9, 13, 17)
    count = sum(
        _joint_alignment(landmarks[mcp], landmarks[pip], landmarks[tip]) > 0.2
        and distance(landmarks[tip], wrist) > distance(landmarks[pip], wrist) * 1.04
        for (tip, pip), mcp in zip(FINGER_JOINTS, finger_mcps)
    )
    thumb_is_straight = _joint_alignment(landmarks[2], landmarks[3], landmarks[4]) > 0.2
    thumb_is_away_from_palm = distance(landmarks[4], landmarks[5]) > distance(landmarks[3], landmarks[5]) * 1.15
    count += thumb_is_straight and thumb_is_away_from_palm
    return int(count)


def namaste_detected(hands: list[list[tuple[float, float]]], threshold: float = 0.35) -> bool:
    if len(hands) < 2 or any(len(hand) < 21 for hand in hands[:2]):
        return False
    left, right = hands[:2]
    hand_size = max(distance(hand[0], hand[9]) for hand in (left, right))
    if hand_size <= 0:
        return False
    tips_close = distance(left[8], right[8]) < threshold * hand_size
    wrists_close = distance(left[0], right[0]) < threshold * hand_size
    fingers_up = all(hand[8][1] < hand[0][1] for hand in (left, right))
    return tips_close and wrists_close and fingers_up


@dataclass
class LockUpdate:
    value: int | None
    confidence: float
    progress: float
    locked: bool
    awaiting_release: bool = False


class GestureLock:
    def __init__(self, window: int = 15, min_confidence: float = 0.75, hold_seconds: float = 0.8):
        self.window = window
        self.min_confidence = min_confidence
        self.hold_seconds = hold_seconds
        self.votes: deque[tuple[int, float]] = deque(maxlen=window)
        self.candidate: int | None = None
        self.started: float | None = None
        self.locked = False
        self.waiting_for_release = False

    def reset(self) -> None:
        self.votes.clear()
        self.candidate = None
        self.started = None
        self.locked = False
        self.waiting_for_release = False

    def require_release(self) -> None:
        self.reset()
        self.waiting_for_release = True

    def update(
        self,
        value: int | None,
        score: float = 1.0,
        now: float | None = None,
        *,
        hand_present: bool | None = None,
    ) -> LockUpdate:
        now = time.monotonic() if now is None else now
        hand_present = value is not None if hand_present is None else hand_present
        if self.waiting_for_release:
            if not hand_present:
                self.reset()
                return LockUpdate(None, 0.0, 0.0, False)
            return LockUpdate(value, 0.0, 0.0, False, awaiting_release=True)
        if self.locked:
            if value is not None and value == self.candidate:
                return LockUpdate(value, 1.0, 1.0, False)
            self.reset()
        if value is None:
            self.reset()
            return LockUpdate(None, 0.0, 0.0, False)
        self.votes.append((value, max(0.0, min(1.0, score))))
        counts = Counter(vote for vote, _ in self.votes)
        most_common = counts.most_common(1)[0][0]
        agrees = counts[most_common]
        mean_score = sum(conf for _, conf in self.votes) / len(self.votes)
        confidence = agrees / self.window * mean_score
        if most_common != self.candidate or confidence < self.min_confidence:
            self.candidate = most_common if confidence >= self.min_confidence else None
            self.started = now if self.candidate is not None else None
            return LockUpdate(most_common, confidence, 0.0, False)
        if self.started is None:
            self.started = now
        elapsed = max(0.0, now - self.started)
        locked = elapsed + 1e-9 >= self.hold_seconds
        progress = 1.0 if locked else min(1.0, elapsed / self.hold_seconds)
        self.locked = locked
        return LockUpdate(most_common, confidence, progress, locked)


def choose_largest_hand(hand_points: list[list[tuple[float, float]]]) -> list[tuple[float, float]] | None:
    return max(hand_points, key=lambda hand: distance(hand[0], hand[9])) if hand_points else None


class CameraWorker:
    def __init__(self, on_gesture: Callable[..., None], enabled: bool = True, device: int = 0):
        self.on_gesture = on_gesture
        self.enabled = enabled
        self.device = device
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.latest_jpeg: bytes | None = None
        self.status = "Simulation mode" if not enabled else "Starting camera..."
        self.lock = GestureLock(window=8, min_confidence=0.65, hold_seconds=0.6)
        self.namaste_lock = GestureLock(window=8, min_confidence=0.65, hold_seconds=0.6)
        self.namaste_distance = 0.35

    def configure(self, settings: dict[str, float | int]) -> None:
        self.lock = GestureLock(
            window=int(settings["vote_frames"]),
            min_confidence=float(settings["confidence_threshold"]),
            hold_seconds=float(settings["hold_ms"]) / 1000,
        )
        self.namaste_lock = GestureLock(
            window=int(settings["vote_frames"]),
            min_confidence=float(settings["confidence_threshold"]),
            hold_seconds=float(settings["hold_ms"]) / 1000,
        )
        self.namaste_distance = float(settings["namaste_distance"])

    def reset_locks(self) -> None:
        self.lock.require_release()
        self.namaste_lock.require_release()

    def start(self) -> None:
        if self.enabled and (self._thread is None or not self._thread.is_alive()):
            self._thread = threading.Thread(target=self._run, name="camera-worker", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)

    def _run(self) -> None:
        try:
            import cv2
        except ImportError:
            self.status = "Camera unavailable: install the OpenCV dependency."
            logger.exception("OpenCV could not be loaded")
            return
        try:
            import mediapipe as mp
        except ImportError:
            version = f"{sys.version_info.major}.{sys.version_info.minor}"
            self.status = (
                f"Hand tracking unavailable: MediaPipe is not installed for Python {version}. "
                "Use Python 3.11 and install requirements.txt."
            )
            logger.exception("Camera dependencies could not be loaded")
            return
        if not hasattr(mp, "solutions"):
            self.status = (
                f"Hand tracking unavailable: MediaPipe {mp.__version__} does not include the Hands API. "
                "Use Python 3.11 and reinstall requirements.txt."
            )
            logger.error("Incompatible MediaPipe version %s", mp.__version__)
            return

        while not self._stop.is_set():
            capture = self._open_capture(cv2)
            if not capture.isOpened():
                self.status = f"Camera {self.device} not found or unavailable. Retrying..."
                logger.warning("Unable to open camera %s; retrying", self.device)
                capture.release()
                self._stop.wait(2)
                continue
            self.status = "Camera connected — looking for a hand"
            try:
                hands_api = mp.solutions.hands
                with hands_api.Hands(max_num_hands=2, min_detection_confidence=0.6, min_tracking_confidence=0.6) as hands:
                    while not self._stop.is_set():
                        started = time.perf_counter()
                        ok, frame = capture.read()
                        if not ok:
                            self.status = "Camera disconnected. Retrying..."
                            logger.warning("Camera %s stopped returning frames", self.device)
                            break
                        frame = cv2.flip(frame, 1)
                        height, width = frame.shape[:2]
                        if frame_is_too_dark(frame):
                            self.lock.update(None)
                            self.namaste_lock.update(None)
                            self.status = "Camera image is black or too dark. Check its cover, permissions, lighting, or device index."
                            self.on_gesture("count", count=None, confidence=0, progress=0, locked=False)
                        else:
                            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                            results = hands.process(rgb)
                            detected: list[tuple[list[tuple[float, float]], float]] = []
                            if results.multi_hand_landmarks:
                                for index, hand in enumerate(results.multi_hand_landmarks):
                                    points = [(p.x, p.y) for p in hand.landmark]
                                    if hand_inside_guide(points[0]):
                                        score = results.multi_handedness[index].classification[0].score
                                        detected.append((points, score))
                                    mp.solutions.drawing_utils.draw_landmarks(frame, hand, hands_api.HAND_CONNECTIONS)
                            if len(detected) >= 2 and namaste_detected([item[0] for item in detected], self.namaste_distance):
                                self.lock.update(None, hand_present=True)
                                update = self.namaste_lock.update(1, min(item[1] for item in detected))
                                self.status = "Namaste detected — hold still"
                                self.on_gesture("namaste", confidence=update.confidence, progress=update.progress, locked=update.locked,
                                                awaiting_release=update.awaiting_release)
                            elif detected:
                                self.namaste_lock.update(None, hand_present=True)
                                points, score = max(detected, key=lambda item: distance(item[0][0], item[0][9]))
                                count = count_fingers(points)
                                update = self.lock.update(count, score)
                                self.status = f"Hand detected — {count} finger{'s' if count != 1 else ''}"
                                self.on_gesture("count", count=count, confidence=update.confidence, progress=update.progress, locked=update.locked,
                                                awaiting_release=update.awaiting_release)
                            else:
                                self.lock.update(None)
                                self.namaste_lock.update(None)
                                self.status = "Camera connected — show your hand inside the guide"
                                self.on_gesture("count", count=None, confidence=0, progress=0, locked=False)
                        cv2.rectangle(frame, (int(width * 0.05), int(height * 0.05)), (int(width * 0.95), int(height * 0.98)), (0, 190, 255), 2)
                        cv2.putText(
                            frame,
                            self.status,
                            (18, height - 18),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            0.55,
                            (255, 255, 255),
                            2,
                            cv2.LINE_AA,
                        )
                        _, encoded = cv2.imencode(".jpg", frame)
                        self.latest_jpeg = encoded.tobytes()
                        elapsed = time.perf_counter() - started
                        if elapsed < 1 / 30:
                            self._stop.wait(1 / 30 - elapsed)
            except Exception as exc:
                self.status = f"Hand tracking failed: {exc}"
                logger.exception("Camera hand tracking failed")
                self._stop.wait(2)
            finally:
                capture.release()
        self.status = "Camera stopped"

    def _open_capture(self, cv2):
        backends = [None]
        if sys.platform == "win32":
            backends.extend((cv2.CAP_DSHOW, cv2.CAP_MSMF))
        for backend in backends:
            capture = cv2.VideoCapture(self.device) if backend is None else cv2.VideoCapture(self.device, backend)
            if capture.isOpened():
                capture.set(cv2.CAP_PROP_FPS, 30)
                for _ in range(3):
                    ok, _frame = capture.read()
                    if ok:
                        return capture
                    if self._stop.wait(0.1):
                        break
            capture.release()
        logger.warning("Camera %s did not return frames from any available backend", self.device)
        return cv2.VideoCapture()
