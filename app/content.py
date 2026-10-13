from __future__ import annotations

import json
import random
from collections import deque
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
GODDESSES = [
    ("01_shailaputri.png", "Shailaputri"),
    ("02_brahmacharini.png", "Brahmacharini"),
    ("03_chandraghanta.png", "Chandraghanta"),
    ("04_kushmanda.png", "Kushmanda"),
    ("05_skandamata.png", "Skandamata"),
    ("06_katyayani.png", "Katyayani"),
    ("07_kalaratri.png", "Kalaratri"),
    ("08_mahagauri.png", "Mahagauri"),
    ("09_siddhidatri.png", "Siddhidatri"),
]


def load_json(filename: str) -> list[dict[str, Any]]:
    path = DATA_DIR / filename
    with path.open(encoding="utf-8") as source:
        content = json.load(source)
    if not isinstance(content, list):
        raise ValueError(f"{path} must contain a JSON array")
    return content


def save_json(filename: str, entries: list[dict[str, Any]]) -> None:
    (DATA_DIR / filename).write_text(json.dumps(entries, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


class BlessingPicker:
    def __init__(self, recent_goddesses: list[str] | None = None, recent_slogans: list[str] | None = None):
        self.recent_goddesses = deque(recent_goddesses or [], maxlen=3)
        self.recent_slogans = deque(recent_slogans or [], maxlen=10)

    def pick(self, slogans: list[dict[str, Any]], rng: random.Random | None = None) -> tuple[str, dict[str, Any]]:
        rng = rng or random.SystemRandom()
        goddess_names = [name for _, name in GODDESSES]
        available_goddesses = [name for name in goddess_names if name not in self.recent_goddesses]
        goddess = rng.choice(available_goddesses or goddess_names)
        active_slogans = [item for item in slogans if item.get("active", True)]
        available_slogans = [item for item in active_slogans if item["id"] not in self.recent_slogans]
        slogan = rng.choice(available_slogans or active_slogans)
        self.recent_goddesses.append(goddess)
        self.recent_slogans.append(slogan["id"])
        return goddess, slogan
