# Saraswati Puja / Navratri Gesture Quiz Kiosk

A local, hands-free quiz kiosk for the nine Navadurga forms. FastAPI serves the kiosk and second-screen leaderboard, SQLAlchemy stores results and settings in a WAL-mode SQLite database, and the camera path uses OpenCV and MediaPipe Hands. All pages, styles, scripts, question data and slogan data are local; there are no CDNs, analytics, frame uploads or saved audio recordings.

## Requirements

- Python 3.11 or newer.
- A webcam and microphone for physical recognition.
- For offline spoken-name recognition, download a Vosk small English model separately and set `VOSK_MODEL_PATH` to its local folder. The model is not bundled or fetched by the app.
- MediaPipe currently publishes wheels for a narrower Python range than the app itself. Python 3.11–3.13 is recommended for physical hand recognition. On a newer Python version the dependency is skipped and the app remains usable in simulation; check MediaPipe's wheel availability before choosing a newer interpreter.

## Setup and run — Windows PowerShell

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
$env:ADMIN_PASSWORD = "choose-a-local-volunteer-password"
$env:VOSK_MODEL_PATH = "C:\models\vosk-model-small-en-us"
python run.py
```

Open `http://localhost:8000/kiosk` on the camera computer and `http://localhost:8000/display` on a second display. The server binds to `0.0.0.0:8000`; keep it on a trusted local network. The admin page at `/admin` uses HTTP Basic authentication and is disabled until `ADMIN_PASSWORD` is set.

If PowerShell blocks virtual-environment activation, use `.\.venv\Scripts\python.exe -m pip install -r requirements.txt` and `.\.venv\Scripts\python.exe run.py`.

## Setup and run — Linux

Install the Python package prerequisites and, for physical microphone recognition, PortAudio (for example `sudo apt install portaudio19-dev` on Debian/Ubuntu). Then:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
export ADMIN_PASSWORD='choose-a-local-volunteer-password'
export VOSK_MODEL_PATH="$HOME/models/vosk-model-small-en-us"
python run.py
```

Open the same kiosk and display URLs in a browser. For a system without a desktop, serve the kiosk/display from the same local network and grant camera/microphone permission to the browser origin. HTTPS or localhost may be required by browsers for camera/microphone permissions.

## Simulation and volunteer controls

Run `python run.py --simulate` when no camera or microphone is available. The gesture and microphone workers are replaced by volunteer test controls, while the UI still runs through the same server-side state machine.

- Kiosk volunteer hotkeys: `Space` starts with an open palm; `1`–`4` answer/confirm; `P` simulates namaste; `N` skips the current question; `Esc` resets to idle.
- The typed-name test endpoint is `POST /api/dev/name` with JSON such as `{"name":"Asha Rao"}`. Use `POST /api/dev/action` with `{"action":"palm"}`, `{"action":"1"}`, `{"action":"namaste"}`, `{"action":"skip"}` or `{"action":"reset"}` for deterministic driving. These endpoints return 404 unless simulation mode is active.
- Simulation volunteers can pause/resume automatic state timers with `{"action":"pause"}` / `{"action":"resume"}` while taking screenshots; this does not exist in physical mode.
- In physical mode the same kiosk hotkeys are volunteer-only and request the admin password; visitor flow itself needs no touch, click or keyboard.

## Content and images

- Edit `data/questions.json` and `data/slogans.json` while the kiosk is stopped, or use the authenticated editors in `/admin`. Questions are randomly selected in the order Moderate, Easy, Difficult, Easy, Difficult. Each starts with `needs_review: true` so local organizers can verify wording against their community's preferred tradition.
- Place your supplied images in `static/goddesses/` with these exact filenames: `01_shailaputri.png`, `02_brahmacharini.png`, `03_chandraghanta.png`, `04_kushmanda.png`, `05_skandamata.png`, `06_katyayani.png`, `07_kalaratri.png`, `08_mahagauri.png`, `09_siddhidatri.png`. Missing images are replaced by a clean generated name card; the project does not download or create goddess artwork.
- The kiosk's gentle chimes and prayer tones are generated locally with the browser Web Audio API. The volunteer sound toggle mutes/unmutes them.

## Data, settings and privacy

The default database is `data/kiosk.db` (SQLite WAL). Quiz results, settings, blessing logs, and timeout events remain local across restarts. Configure `DATABASE_URL` to use a different SQLAlchemy database URL if needed. Camera frames are processed in memory and exposed only as the local MJPEG preview. Microphone samples are processed in memory for Vosk and discarded; no frame or audio recording is created or sent to a third party.

The admin panel at `/admin` edits confidence (0.75 default), hold duration (800 ms), vote window (15 frames), namaste distance ratio (0.35), question/prayer/blessing timers, idle reset, question and slogan data, sound, leaderboard visibility/reset, and recent sessions/timeouts.

## Run tests

```powershell
python -m pytest -q
```

or on Linux:

```bash
python -m pytest -q
```

## Troubleshooting

- **Camera not found / disconnected:** the camera worker reports a friendly retry message and reopens the selected camera. Check OS/browser camera permissions, close other apps using the webcam, and try setting `CAMERA_DEVICE` only if you extend `run.py` to select a different index.
- **No MediaPipe wheel:** use Python 3.11–3.13 in a fresh virtual environment, reinstall requirements, and confirm `import mediapipe` succeeds. Simulation remains available without it.
- **Name capture unavailable:** install PortAudio/sounddevice, download a Vosk small English model once, and set `VOSK_MODEL_PATH` to its extracted directory. Name recognition remains offline.
- **Browser has no sound:** allow sound for the kiosk tab and check the admin sound setting. Some browsers require a volunteer to activate audio once; quiz interaction itself is still gesture driven.
- **Admin gives 503:** set `ADMIN_PASSWORD` in the environment of the process running `python run.py`, then restart it.
- **No goddess pictures:** install the supplied nine PNGs under the exact names above; placeholders are expected until then.
- **Leaderboard looks empty:** finish a quiz (five answers) and check that the process can write to `data/`. Scores are committed to SQLite at the end of each quiz.
