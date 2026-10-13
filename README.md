# Saraswati Puja / Navratri Gesture Quiz Kiosk

A local, hands-free quiz kiosk for the nine Navadurga forms. FastAPI serves the kiosk and second-screen leaderboard, SQLAlchemy stores results and settings in a WAL-mode SQLite database, the camera path uses OpenCV and MediaPipe Hands, and the browser uses its built-in speech recognition for spoken names.

## Requirements

- Python 3.11 for physical hand recognition. This project uses MediaPipe's legacy Hands API and pins a compatible release; newer MediaPipe versions removed that API. If recognition dependencies are missing, the kiosk displays the camera status and the reason.
- A webcam and microphone. On the name screen, select **Enable microphone & say your name** and allow microphone access in the browser prompt. The recognized name is shown for confirmation; show 1 finger to start or 2 fingers to say it again.
- Speech recognition requires a browser with the Web Speech API (Chrome or Edge recommended) and may require internet access. The browser processes audio for speech recognition; only the recognized name text is sent to the kiosk server.

## Setup and run — Windows PowerShell

```powershell
py -3.11 -m venv .venv311
.\.venv311\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
$env:ADMIN_PASSWORD = "choose-a-local-volunteer-password"
python run.py
```

Open `http://localhost:8000/kiosk` on the camera computer and `http://localhost:8000/display` on a second display. The server binds to `0.0.0.0:8000`; keep it on a trusted local network. The admin page at `/admin` uses HTTP Basic authentication and is disabled until `ADMIN_PASSWORD` is set. If the computer has multiple cameras, set `$env:CAMERA_DEVICE = "1"` before starting the app, or pass `--camera-device 1`.

For a phone or tablet on the same network, open `http://<host-computer-LAN-IP>:8000/kiosk`. The responsive page runs on mobile, but hand tracking and spoken-name capture use the webcam and microphone attached to the computer running the server; the phone's own camera and microphone are not used.

If PowerShell blocks virtual-environment activation, use `.\.venv311\Scripts\python.exe -m pip install -r requirements.txt` and `.\.venv311\Scripts\python.exe run.py`.

## Setup and run — Linux

Install the Python package prerequisites and, for physical microphone recognition, PortAudio (for example `sudo apt install portaudio19-dev` on Debian/Ubuntu). Then:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
export ADMIN_PASSWORD='choose-a-local-volunteer-password'
python run.py
```

Open the same kiosk and display URLs in a supported browser. Grant microphone permission when prompted. Browsers may require HTTPS or localhost for microphone access.

## Simulation and volunteer controls

Run `python run.py --simulate` when no camera or microphone is available. The gesture and microphone workers are replaced by volunteer test controls, while the UI still runs through the same server-side state machine.

- The kiosk starts by asking for a spoken name. Show 1 finger to confirm and start the quiz, or 2 fingers to say the name again. After five questions, the kiosk returns to name capture for the next player.
- Kiosk volunteer hotkeys: `1`–`4` answer/confirm; `P` simulates namaste; `N` skips the current question; `Esc` returns to name capture.
- The typed-name test endpoint is `POST /api/dev/name` with JSON such as `{"name":"Asha Rao"}`. Use `POST /api/dev/action` with `{"action":"1"}`, `{"action":"namaste"}`, `{"action":"skip"}` or `{"action":"reset"}` for deterministic driving. These endpoints return 404 unless simulation mode is active.
- Simulation volunteers can pause/resume automatic state timers with `{"action":"pause"}` / `{"action":"resume"}` while taking screenshots; this does not exist in physical mode.
- In physical mode the kiosk hotkeys are volunteer-only and request the admin password; the visitor flow starts with microphone name capture and needs no touch, click or keyboard.

## Content and images

- Edit `data/questions.json` and `data/slogans.json` while the kiosk is stopped, or use the authenticated editors in `/admin`. Questions are randomly selected in the order Moderate, Easy, Difficult, Easy, Difficult. Each starts with `needs_review: true` so local organizers can verify wording against their community's preferred tradition.
- Place your supplied images in `static/goddesses/` with these exact filenames: `01_shailaputri.png`, `02_brahmacharini.png`, `03_chandraghanta.png`, `04_kushmanda.png`, `05_skandamata.png`, `06_katyayani.png`, `07_kalaratri.png`, `08_mahagauri.png`, `09_siddhidatri.png`. When a supplied image is absent, the kiosk serves a locally generated, original illustrated goddess card; it does not download artwork.
- The kiosk's gentle chimes and prayer tones are generated locally with the browser Web Audio API. The volunteer sound toggle mutes/unmutes them.

## Data, settings and privacy

The default database is `data/kiosk.db` (SQLite WAL). Quiz results, settings, blessing logs, and timeout events remain local across restarts. Configure `DATABASE_URL` to use a different SQLAlchemy database URL if needed. Camera frames are processed in memory and exposed only as the local MJPEG preview. Speech recognition runs through the browser's Web Speech service, which may process audio outside this app; only the recognized name text is sent to this server. The app does not record or store microphone audio.

The admin panel at `/admin` edits confidence (0.65 default), hold duration (600 ms), vote window (8 frames), namaste distance ratio (0.35), question/prayer/blessing timers, idle reset, question and slogan data, sound, leaderboard visibility/reset, and recent sessions/timeouts.

## Run tests

```powershell
python -m pytest -q
```

or on Linux:

```bash
python -m pytest -q
```

## Troubleshooting

- **Camera not found / disconnected, or preview is black:** read the status beside the camera preview. Check the physical privacy shutter, Windows Settings → Privacy & security → Camera → allow desktop apps, camera permissions, and lighting. Close other apps using the webcam and try another device index with `CAMERA_DEVICE` or `--camera-device`. The camera attached to the computer running Python must show a live image in the preview; a phone browser does not use the phone's camera in this server-camera setup.
- **Hand tracking unavailable:** use Python 3.11 in a fresh virtual environment and reinstall requirements. This app uses MediaPipe's legacy Hands API, so requirements pin MediaPipe to `>=0.10.20,<0.10.22`. Other Python versions can run the app, but gesture recognition needs a compatible MediaPipe wheel.
- **Name capture unavailable:** use the latest Chrome or Edge, open the kiosk at `http://localhost:8000/kiosk`, press **Enable microphone & say your name**, and allow microphone access. Check Windows Settings → Privacy & security → Microphone → allow desktop apps. Browser speech recognition may need an internet connection. The app server receives only the recognized name text, not microphone audio.
- **Browser has no sound:** allow sound for the kiosk tab and check the admin sound setting. Some browsers require a volunteer to activate audio once; quiz interaction itself is still gesture driven.
- **Admin gives 503:** set `ADMIN_PASSWORD` in the environment of the process running `python run.py`, then restart it.
- **No supplied goddess pictures:** the original illustrated fallback is shown automatically. Install the supplied nine PNGs under the exact names above to use your own artwork.
- **Leaderboard looks empty:** finish a quiz (five answers) and check that the process can write to `data/`. Scores are committed to SQLite at the end of each quiz.
