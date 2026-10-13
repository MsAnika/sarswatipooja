from __future__ import annotations

import hmac
import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, Response, StreamingResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from sqlalchemy import delete, select

from app.content import DATA_DIR, GODDESSES, load_json, save_json
from app.db import ROOT, SessionLocal, initialize_database
from app.models import BlessingLog, GestureTimeout, QuizSession

logger = logging.getLogger(__name__)
state = None
camera = None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if state is not None:
        if not state.simulate and camera is not None:
            camera.start()
        state.start()
    yield
    if state is not None:
        state.stop()
    if camera is not None:
        camera.stop()


app = FastAPI(title="Saraswati Puja Gesture Quiz", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
templates = Jinja2Templates(directory=ROOT / "templates")
security = HTTPBasic()


def configure_runtime(quiz_state, camera_worker) -> None:
    global state, camera
    state, camera = quiz_state, camera_worker
    camera.configure(state.settings)
    state.set_settings_changed(camera.configure)
    state.set_question_changed(camera.reset_locks)
    state.set_gesture_reset(camera.reset_locks)


def require_admin(credentials: HTTPBasicCredentials = Depends(security)) -> str:
    expected = os.getenv("ADMIN_PASSWORD")
    if not expected:
        raise HTTPException(status_code=503, detail="Admin page is disabled: set ADMIN_PASSWORD first.")
    if not hmac.compare_digest(credentials.password.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="Incorrect admin password", headers={"WWW-Authenticate": "Basic"})
    return credentials.username


def current_state():
    if state is None:
        raise HTTPException(status_code=503, detail="Kiosk is still starting.")
    return state


@app.get("/", response_class=HTMLResponse)
async def home() -> HTMLResponse:
    return HTMLResponse('<meta http-equiv="refresh" content="0;url=/kiosk">')


@app.get("/kiosk", response_class=HTMLResponse)
async def kiosk(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "kiosk.html", {"simulate": bool(state and state.simulate)})


@app.get("/display", response_class=HTMLResponse)
async def display(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "display.html", {})


@app.get("/admin", response_class=HTMLResponse)
async def admin(request: Request, _username: str = Depends(require_admin)) -> HTMLResponse:
    return templates.TemplateResponse(request, "admin.html", {})


@app.get("/api/state")
async def get_state() -> dict[str, Any]:
    return current_state().snapshot()


@app.get("/api/camera/status")
async def camera_status() -> dict[str, str]:
    if camera is None:
        raise HTTPException(status_code=503, detail="Camera worker is not configured.")
    return {"status": camera.status}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    try:
        previous_version = -1
        while True:
            snapshot = current_state().snapshot()
            if snapshot["version"] != previous_version:
                await websocket.send_json(snapshot)
                previous_version = snapshot["version"]
            await __import__("asyncio").sleep(0.05)
    except WebSocketDisconnect:
        logger.debug("WebSocket client disconnected")


@app.get("/video")
async def video() -> StreamingResponse:
    def frames():
        import cv2

        while True:
            frame = camera.latest_jpeg if camera else None
            if frame is None:
                placeholder = __import__("numpy").zeros((360, 640, 3), dtype="uint8")
                cv2.rectangle(placeholder, (115, 36), (525, 324), (0, 150, 230), 2)
                cv2.putText(placeholder, camera.status if camera else "Camera starting", (45, 190),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.65, (240, 220, 195), 2)
                frame = cv2.imencode(".jpg", placeholder)[1].tobytes()
            yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
            __import__("time").sleep(1 / 15)

    return StreamingResponse(frames(), media_type="multipart/x-mixed-replace; boundary=frame")


@app.get("/goddess/{filename}")
async def goddess_image(filename: str) -> Response:
    known = {path: name for path, name in GODDESSES}
    if filename not in known:
        raise HTTPException(status_code=404)
    path = ROOT / "static" / "goddesses" / filename
    if path.is_file():
        return Response(path.read_bytes(), media_type="image/png")
    goddess_name = known[filename]
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="900" height="900" viewBox="0 0 900 900" role="img" aria-labelledby="title description">
    <title id="title">Goddess {goddess_name}</title>
    <desc id="description">A warm, original illustration of a goddess seated on a lotus beneath a radiant halo.</desc>
    <defs>
      <radialGradient id="background"><stop stop-color="#fff9e9"/><stop offset="1" stop-color="#efd49a"/></radialGradient>
      <linearGradient id="sari" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#b52d47"/><stop offset="1" stop-color="#e77c42"/></linearGradient>
      <linearGradient id="gold" x1="0" y1="0" x2="0" y2="1"><stop stop-color="#ffe89a"/><stop offset="1" stop-color="#d99c32"/></linearGradient>
    </defs>
    <rect width="900" height="900" rx="44" fill="url(#background)"/>
    <circle cx="450" cy="382" r="292" fill="#f5cf69" opacity=".34"/>
    <circle cx="450" cy="382" r="246" fill="none" stroke="#d39b36" stroke-width="5" stroke-dasharray="3 18"/>
    <path d="M450 106v48m0 456v48M174 382h48m456 0h48M255 187l34 34m322 322 34 34m0-390-34 34m-322 322-34 34" stroke="#d39b36" stroke-width="7" stroke-linecap="round" opacity=".72"/>
    <path d="M280 690q-90-64-118 6 68 40 118-6m340 0q90-64 118 6-68 40-118-6" fill="#d95671" stroke="#9e2945" stroke-width="7"/>
    <path d="M340 701q-83-105-112-36 57 67 112 36m220 0q83-105 112-36-57 67-112 36" fill="#ef9aa0" stroke="#b63b50" stroke-width="7"/>
    <path d="M450 704q-82-126 0-162 82 36 0 162" fill="#ffe4a2" stroke="#bf8431" stroke-width="7"/>
    <path d="M337 555q-58-55-97 7l108 142m215-149q58-55 97 7L552 704" fill="none" stroke="#bd7e54" stroke-width="32" stroke-linecap="round"/>
    <path d="M290 578q-25 22-41 45m361-45q25 22 41 45" fill="none" stroke="#f4c596" stroke-width="25" stroke-linecap="round"/>
    <path d="M329 548q121-102 242 0l74 207q-195 104-390 0z" fill="url(#sari)" stroke="#8f263e" stroke-width="8"/>
    <path d="M350 573q100 78 200 0m-190 68q90 55 180 0m-160 67q70 38 140 0" fill="none" stroke="#f8d779" stroke-width="8" opacity=".9"/>
    <path d="M419 473h62v70h-62z" fill="#efbd8d"/>
    <path d="M373 347q-12-102 77-114 91 17 77 114l-16 98q-61 76-122 0z" fill="#38222a"/>
    <ellipse cx="450" cy="357" rx="69" ry="86" fill="#f4c99b"/>
    <path d="M385 337q6-104 65-104t65 104q-26-39-65-44-39 5-65 44" fill="#38222a"/>
    <path d="M393 272l57-94 57 94q-56-24-114 0" fill="url(#gold)" stroke="#a76e25" stroke-width="8"/>
    <circle cx="450" cy="198" r="16" fill="#a92542"/><circle cx="450" cy="357" r="7" fill="#a92542"/>
    <path d="M418 357q13-13 26 0m13 0q13-13 26 0" fill="none" stroke="#542a2d" stroke-width="5" stroke-linecap="round"/>
    <path d="M444 391q6 5 12 0" fill="none" stroke="#a54b4d" stroke-width="5" stroke-linecap="round"/>
    <path d="M386 447q64 46 128 0" fill="none" stroke="url(#gold)" stroke-width="12"/>
    <circle cx="411" cy="464" r="10" fill="#f8dc82"/><circle cx="489" cy="464" r="10" fill="#f8dc82"/>
    <text x="450" y="838" text-anchor="middle" font-family="Georgia,serif" font-size="43" font-weight="bold" fill="#7b2936">{goddess_name}</text>
    <text x="450" y="878" text-anchor="middle" font-family="sans-serif" font-size="20" letter-spacing="5" fill="#765135">NAVADURGA • WISDOM • GRACE</text>
    </svg>"""
    return Response(svg, media_type="image/svg+xml")


class PlayerName(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class DevAction(BaseModel):
    action: str


def require_simulation() -> Any:
    quiz_state = current_state()
    if not quiz_state.simulate:
        raise HTTPException(status_code=404, detail="Simulation endpoints are disabled.")
    return quiz_state


@app.post("/api/dev/name")
async def dev_name(body: PlayerName, quiz_state=Depends(require_simulation)) -> dict[str, str]:
    try:
        name = quiz_state.accept_name(body.name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"name": name}


@app.post("/api/name")
async def capture_player_name(body: PlayerName) -> dict[str, str]:
    quiz_state = current_state()
    try:
        name = quiz_state.accept_name(body.name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"name": name}


@app.post("/api/dev/action")
async def dev_action(body: DevAction, quiz_state=Depends(require_simulation)) -> dict[str, str]:
    return apply_volunteer_action(body.action, quiz_state)


def apply_volunteer_action(action_value: str, quiz_state) -> dict[str, str]:
    action = action_value.lower()
    if action == "pause" and quiz_state.simulate:
        quiz_state.set_timers_paused(True)
    elif action == "resume" and quiz_state.simulate:
        quiz_state.set_timers_paused(False)
    elif action == "reset":
        quiz_state.reset()
    elif action in {"1", "2", "3", "4"}:
        quiz_state.handle_gesture("count", count=int(action), confidence=1, progress=1, locked=True)
    elif action == "namaste":
        quiz_state.handle_gesture("namaste", confidence=1, progress=1, locked=True)
    elif action == "skip":
        quiz_state.skip_question()
    else:
        raise HTTPException(status_code=400, detail="Unsupported volunteer action.")
    return {"state": quiz_state.state}


@app.post("/api/volunteer/action")
async def volunteer_action(body: DevAction, _username: str = Depends(require_admin)) -> dict[str, str]:
    return apply_volunteer_action(body.action, current_state())


@app.get("/api/dev/answer")
async def dev_answer(quiz_state=Depends(require_simulation)) -> dict[str, Any]:
    if quiz_state.state != "QUESTION":
        raise HTTPException(status_code=409, detail="No question is currently accepting an answer.")
    question = quiz_state.questions[quiz_state.question_index]
    return {
        "number": quiz_state.question_index + 1,
        "question_id": question["id"],
        "correct_index": question["correct_index"],
    }


class SettingsUpdate(BaseModel):
    values: dict[str, Any]


@app.get("/api/admin/settings")
async def admin_settings(_username: str = Depends(require_admin)) -> dict[str, Any]:
    return current_state().settings


@app.put("/api/admin/settings")
async def update_settings(body: SettingsUpdate, _username: str = Depends(require_admin)) -> dict[str, Any]:
    try:
        current_state().set_settings(body.values)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return current_state().settings


@app.get("/api/admin/content/{kind}")
async def get_content(kind: str, _username: str = Depends(require_admin)) -> list[dict[str, Any]]:
    filename = {"questions": "questions.json", "slogans": "slogans.json"}.get(kind)
    if filename is None:
        raise HTTPException(status_code=404)
    return load_json(filename)


@app.put("/api/admin/content/{kind}")
async def update_content(kind: str, request: Request, _username: str = Depends(require_admin)) -> dict[str, int]:
    filename = {"questions": "questions.json", "slogans": "slogans.json"}.get(kind)
    if filename is None:
        raise HTTPException(status_code=404)
    try:
        content = await request.json()
        if not isinstance(content, list):
            raise ValueError("Content must be a JSON array.")
        if kind == "questions":
            if len(content) < 45:
                raise ValueError("Keep at least 45 questions in the question bank.")
            active_counts = {difficulty: 0 for difficulty in ("Easy", "Moderate", "Difficult")}
            for item in content:
                if len(item["options"]) != 4 or len(item["text"]) > 140 or len(item["reason"]) > 120:
                    raise ValueError("Every question needs four options, text <=140 chars and reason <=120 chars.")
                if any(len(option) > 40 for option in item["options"]):
                    raise ValueError("Option text must be 40 characters or fewer.")
                if item["difficulty"] not in {"Easy", "Moderate", "Difficult"} or not 0 <= int(item["correct_index"]) <= 3:
                    raise ValueError("Invalid difficulty or correct_index.")
                if item.get("active", True):
                    active_counts[item["difficulty"]] += 1
            if active_counts["Easy"] < 2 or active_counts["Moderate"] < 1 or active_counts["Difficult"] < 2:
                raise ValueError("Active questions must cover the quiz's 2 Easy, 1 Moderate and 2 Difficult slots.")
        else:
            if not content or not any(item.get("active", True) for item in content):
                raise ValueError("Keep at least one active slogan.")
            if any(len(item["text"]) > 90 for item in content):
                raise ValueError("Slogans must be 90 characters or fewer.")
        save_json(filename, content)
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"saved": len(content)}


@app.get("/api/admin/overview")
async def admin_overview(_username: str = Depends(require_admin)) -> dict[str, Any]:
    with SessionLocal() as db:
        sessions = db.scalars(select(QuizSession).order_by(QuizSession.finished_at.desc()).limit(20)).all()
        timeouts = db.scalars(select(GestureTimeout).order_by(GestureTimeout.created_at.desc()).limit(30)).all()
        blessings = db.scalars(select(BlessingLog).order_by(BlessingLog.created_at.desc()).limit(15)).all()
        return {
            "sessions": [{"id": row.id, "name": row.name, "score": row.score, "hidden": row.hidden,
                          "finished_at": row.finished_at.isoformat()} for row in sessions],
            "timeouts": [{"reason": row.reason, "created_at": row.created_at.isoformat()} for row in timeouts],
            "blessings": [{"name": row.player_name, "goddess": row.goddess, "slogan_id": row.slogan_id} for row in blessings],
        }


class HideEntry(BaseModel):
    hidden: bool = True


@app.put("/api/admin/leaderboard/{entry_id}")
async def hide_entry(entry_id: int, body: HideEntry, _username: str = Depends(require_admin)) -> dict[str, bool]:
    with SessionLocal() as db:
        entry = db.get(QuizSession, entry_id)
        if entry is None:
            raise HTTPException(status_code=404, detail="Leaderboard entry not found.")
        entry.hidden = body.hidden
        db.commit()
    quiz_state = current_state()
    quiz_state._leaderboard = quiz_state.get_leaderboard_from_db()
    quiz_state._publish()
    return {"hidden": body.hidden}


@app.delete("/api/admin/leaderboard")
async def reset_leaderboard(_username: str = Depends(require_admin)) -> dict[str, int]:
    with SessionLocal() as db:
        result = db.execute(delete(QuizSession))
        db.commit()
    quiz_state = current_state()
    quiz_state._leaderboard = []
    quiz_state._publish()
    return {"deleted": result.rowcount or 0}


@app.post("/api/admin/sound")
async def toggle_sound(request: Request, _username: str = Depends(require_admin)) -> dict[str, bool]:
    body = await request.json()
    current_state().set_settings({"sound_enabled": bool(body.get("enabled"))})
    return {"sound_enabled": current_state().settings["sound_enabled"]}
