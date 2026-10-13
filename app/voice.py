from __future__ import annotations

import re

PROFANITY = {"fuck", "shit", "bitch", "asshole", "cunt"}


def sanitize_name(text: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9 ]", "", text)
    cleaned = " ".join(cleaned.split())[:20].strip()
    words = cleaned.title()
    if any(word.lower() in PROFANITY for word in words.split()):
        raise ValueError("Please choose a respectful name.")
    return words
