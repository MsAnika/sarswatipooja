from __future__ import annotations

import logging
import os
import re
import threading

logger = logging.getLogger(__name__)
PROFANITY = {"fuck", "shit", "bitch", "asshole", "cunt"}


def sanitize_name(text: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9 ]", "", text)
    cleaned = " ".join(cleaned.split())[:20].strip()
    words = cleaned.title()
    if any(word.lower() in PROFANITY for word in words.split()):
        raise ValueError("Please choose a respectful name.")
    return words


class VoiceCapture:
    def __init__(self, simulate: bool = False):
        self.simulate = simulate
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def capture(self, seconds: int = 4) -> str:
        if self.simulate:
            raise RuntimeError("Voice capture is disabled in simulation; use /api/dev/name.")
        model_path = os.getenv("VOSK_MODEL_PATH")
        if not model_path:
            raise RuntimeError("Set VOSK_MODEL_PATH to an installed offline Vosk English model.")
        try:
            import json
            import sounddevice as sd
            from vosk import KaldiRecognizer, Model
        except ImportError as exc:
            raise RuntimeError("Voice capture requires vosk and sounddevice.") from exc
        model = Model(model_path)
        recognizer = KaldiRecognizer(model, 16000)
        audio = sd.rec(int(seconds * 16000), samplerate=16000, channels=1, dtype="int16")
        sd.wait()
        recognizer.AcceptWaveform(audio.tobytes())
        result = json.loads(recognizer.FinalResult()).get("text", "")
        if not result:
            raise RuntimeError("No spoken name was recognized.")
        return sanitize_name(result)
