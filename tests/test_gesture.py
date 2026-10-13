from __future__ import annotations

from app.gesture import GestureLock, count_fingers, namaste_detected


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
        points[3], points[4] = (0.64, 0.52), (0.4, 0.5)
    else:
        points[3], points[4] = (0.4, 0.5), (0.64, 0.52)
    return points


def test_count_fingers_from_zero_through_five():
    for count in range(6):
        assert count_fingers(make_hand(count)) == count


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
