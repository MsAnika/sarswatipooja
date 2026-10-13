from __future__ import annotations

import logging
import math
import threading
import time
from collections import Counter, deque
from dataclasses import dataclass
from typing import Callable, Iterable

logger = logging.getLogger(__name__)

FINGER_JOINTS = ((8, 6), (12, 10), (16, 14), (20, 18))


def distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def count_fingers(points: Iterable[tuple[float, float]]) -> int:
    """Count fingers by radial joint distances, independent of hand rotation."""
    landmarks = list(points)
    if len(landmarks) < 21:
        raise ValueError("At least 21 hand landmarks are required")
    wrist = landmarks[0]
    count = sum(distance(landmarks[tip], wrist) > distance(landmarks[pip], wrist) for tip, pip in FINGER_JOINTS)
    pinky_mcp = landmarks[17]
    count += distance(landmarks[4], pinky_mcp) > distance(landmarks[3], pinky_mcp)
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


class GestureLock:
    def __init__(self, window: int = 15, min_confidence: float = 0.75, hold_seconds: float = 0.8):
        self.window = window
        self.min_confidence = min_confidence
        self.hold_seconds = hold_seconds
        self.votes: deque[tuple[int, float]] = deque(maxlen=window)
        self.candidate: int | None = None
        self.started: float | None = None
        self.locked = False

    def reset(self) -> None:
        self.votes.clear()
        self.candidate = None
        self.started = None
        self.locked = False

    def update(self, value: int | None, score: float = 1.0, now: float | None = None) -> LockUpdate:
        now = time.monotonic() if now is None else now
        if self.locked:
            return LockUpdate(value, 0.0, 1.0, False)
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
        progress = min(1.0, max(0.0, (now - self.started) / self.hold_seconds))
        locked = progress >= 1.0
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
        self.lock = GestureLock()
        self.namaste_lock = GestureLock()
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
        self.lock.reset()
        self.namaste_lock.reset()

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
            import mediapipe as mp
        except ImportError:
            self.status = "Camera recognition unavailable. Install OpenCV and MediaPipe."
            logger.exception("Camera dependencies could not be loaded")
            return

        while not self._stop.is_set():
            capture = cv2.VideoCapture(self.device)
            capture.set(cv2.CAP_PROP_FPS, 30)
            if not capture.isOpened():
                self.status = "Camera not found. Retrying..."
                logger.warning("Unable to open camera %s; retrying", self.device)
                capture.release()
                self._stop.wait(2)
                continue
            self.status = "Camera connected"
            hands_api = mp.solutions.hands
            with hands_api.Hands(max_num_hands=2, min_detection_confidence=0.6, min_tracking_confidence=0.6) as hands:
                while not self._stop.is_set():
                    started = time.perf_counter()
                    ok, frame = capture.read()
                    if not ok:
                        self.status = "Camera disconnected. Retrying..."
                        break
                    frame = cv2.flip(frame, 1)
                    height, width = frame.shape[:2]
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    results = hands.process(rgb)
                    detected: list[tuple[list[tuple[float, float]], float]] = []
                    if results.multi_hand_landmarks:
                        for index, hand in enumerate(results.multi_hand_landmarks):
                            points = [(p.x, p.y) for p in hand.landmark]
                            if 0.18 <= points[0][0] <= 0.82 and 0.10 <= points[0][1] <= 0.90:
                                score = results.multi_handedness[index].classification[0].score
                                detected.append((points, score))
                            mp.solutions.drawing_utils.draw_landmarks(frame, hand, hands_api.HAND_CONNECTIONS)
                    cv2.rectangle(frame, (int(width * 0.18), int(height * 0.1)), (int(width * 0.82), int(height * 0.9)), (0, 190, 255), 2)
                    if len(detected) >= 2 and namaste_detected([item[0] for item in detected], self.namaste_distance):
                        self.lock.update(None)
                        update = self.namaste_lock.update(1, min(item[1] for item in detected))
                        self.on_gesture("namaste", confidence=update.confidence, progress=update.progress, locked=update.locked)
                    elif detected:
                        self.namaste_lock.update(None)
                        points, score = max(detected, key=lambda item: distance(item[0][0], item[0][9]))
                        count = count_fingers(points)
                        update = self.lock.update(count, score)
                        self.on_gesture("count", count=count, confidence=update.confidence, progress=update.progress, locked=update.locked)
                    else:
                        self.lock.update(None)
                        self.namaste_lock.update(None)
                        self.on_gesture("count", count=None, confidence=0, progress=0, locked=False)
                    _, encoded = cv2.imencode(".jpg", frame)
                    self.latest_jpeg = encoded.tobytes()
                    elapsed = time.perf_counter() - started
                    if elapsed < 1 / 30:
                        self._stop.wait(1 / 30 - elapsed)
            capture.release()
        self.status = "Camera stopped"
