from __future__ import annotations

import argparse
import logging
import os

import uvicorn

from app.db import initialize_database
from app.gesture import CameraWorker
from app.main import app, configure_runtime
from app.state import QuizState


def main() -> None:
    parser = argparse.ArgumentParser(description="Saraswati Puja gesture quiz kiosk")
    parser.add_argument("--simulate", action="store_true", help="Use volunteer hotkeys and the typed-name endpoint")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--camera-device", type=int, default=int(os.getenv("CAMERA_DEVICE", "0")))
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    initialize_database()
    state = QuizState(simulate=args.simulate)
    camera = CameraWorker(state.handle_gesture, enabled=not args.simulate, device=args.camera_device)
    configure_runtime(state, camera)

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
