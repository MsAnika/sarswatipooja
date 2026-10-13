(() => {
  const content = document.getElementById("content");
  const label = document.getElementById("state-label");
  const ring = document.getElementById("gesture-ring");
  const countIcon = document.getElementById("gesture-count");
  const coach = document.getElementById("coach");
  let previousState = "";
  let previousView = "";
  let soundEnabled = true;
  let prayerAudio = null;
  const audioContext = window.AudioContext ? new AudioContext() : null;
  let currentSnapshot = null;
  let speechRecognition = null;
  let speechRecognitionActive = false;
  let speechRecognitionRequested = false;
  let namePostPending = false;
  let micStatusText = "";
  let micErrorText = "";
  let microphonePermissionGranted = false;

  function updateMicStatus(message, isError = false) {
    micStatusText = isError ? "" : message;
    micErrorText = isError ? message : "";
    const status = document.getElementById("voice-status");
    const button = document.getElementById("mic-start");
    if (status) {
      status.textContent = message;
      status.setAttribute("role", isError ? "alert" : "status");
    }
    if (button && !speechRecognitionActive) button.disabled = false;
  }

  function stopSpeechRecognition() {
    speechRecognitionRequested = false;
    namePostPending = false;
    if (speechRecognitionActive && speechRecognition) speechRecognition.stop();
    speechRecognitionActive = false;
  }

  async function submitRecognizedName(transcript) {
    if (namePostPending || currentSnapshot?.state !== "NAME" || currentSnapshot.payload?.name) return;
    namePostPending = true;
    updateMicStatus(`I heard “${transcript}”. Checking your name…`);
    try {
      const response = await fetch("/api/name", {
        method: "POST",
        headers: {"Content-Type":"application/json"},
        body: JSON.stringify({name: transcript})
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || "Could not use that name. Please say it again.");
      stopSpeechRecognition();
      updateMicStatus(`I heard ${result.name}. Show 1 finger to confirm, or 2 fingers to say it again.`);
    } catch (error) {
      namePostPending = false;
      updateMicStatus(error.message || "Could not submit the recognized name. Please try again.", true);
    }
  }

  async function startSpeechRecognition() {
    if (speechRecognitionRequested) return;
    const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!Recognition) {
      updateMicStatus("Speech recognition is not supported in this browser. Please use the latest Chrome or Edge.", true);
      return;
    }
    if (!navigator.mediaDevices?.getUserMedia) {
      updateMicStatus("This page cannot access a microphone. Open the kiosk on localhost or a secure HTTPS connection.", true);
      return;
    }
    speechRecognitionRequested = true;
    updateMicStatus("Requesting microphone permission…");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({audio:true});
      stream.getTracks().forEach(track => track.stop());
      microphonePermissionGranted = true;
    } catch (error) {
      speechRecognitionRequested = false;
      const messages = {
        NotAllowedError: "Microphone access is blocked. Allow microphone access for this site in your browser settings, then try again.",
        NotFoundError: "No microphone was found. Connect or enable a microphone, then try again.",
        NotReadableError: "The microphone is busy in another app. Close that app and try again."
      };
      updateMicStatus(messages[error.name] || `Could not access the microphone: ${error.message || error.name}`, true);
      return;
    }
    const recognition = new Recognition();
    speechRecognition = recognition;
    recognition.lang = "en-IN";
    recognition.continuous = true;
    recognition.interimResults = false;
    recognition.onstart = () => {
      speechRecognitionActive = true;
      updateMicStatus("Microphone on. Speak your name clearly.");
      const button = document.getElementById("mic-start");
      if (button) {
        button.disabled = true;
        button.textContent = "Microphone on — say your name";
      }
    };
    recognition.onresult = event => {
      for (let index = event.resultIndex; index < event.results.length; index += 1) {
        const result = event.results[index];
        if (result.isFinal && result[0]?.transcript.trim()) {
          submitRecognizedName(result[0].transcript.trim());
          break;
        }
      }
    };
    recognition.onerror = event => {
      const messages = {
        "not-allowed": "Microphone permission is blocked. Allow it for this site, then try again.",
        "service-not-allowed": "The browser speech service is blocked. Check browser settings or try Chrome/Edge.",
        "audio-capture": "No working microphone was found. Check the microphone connection and Windows input settings.",
        network: "The browser speech service needs an internet connection. Check the connection and try again.",
        "no-speech": "I didn't hear speech. Say your name clearly after the microphone is ready.",
        "language-not-supported": "The browser does not support English (India) speech recognition."
      };
      const message = messages[event.error] || `Speech recognition failed: ${event.error}.`;
      if (!["no-speech", "aborted"].includes(event.error)) speechRecognitionRequested = false;
      updateMicStatus(message, !["no-speech", "aborted"].includes(event.error));
    };
    recognition.onend = () => {
      speechRecognitionActive = false;
      if (!speechRecognitionRequested || currentSnapshot?.state !== "NAME") {
        const button = document.getElementById("mic-start");
        if (button) {
          button.disabled = false;
          button.textContent = "Enable microphone & say your name";
        }
        return;
      }
      window.setTimeout(() => {
        if (!speechRecognitionRequested || currentSnapshot?.state !== "NAME") return;
        try {
          recognition.start();
        } catch (error) {
          speechRecognitionRequested = false;
          updateMicStatus(`Could not restart speech recognition: ${error.message}`, true);
        }
      }, 300);
    };
    try {
      recognition.start();
    } catch (error) {
      speechRecognitionRequested = false;
      updateMicStatus(`Could not start speech recognition: ${error.message}`, true);
    }
  }

  function tone(frequency = 660, duration = .16, volume = .07) {
    if (!audioContext) return;
    if (audioContext.state === "suspended") audioContext.resume();
    const oscillator = audioContext.createOscillator();
    const gain = audioContext.createGain();
    oscillator.type = "sine";
    oscillator.frequency.value = frequency;
    gain.gain.setValueAtTime(volume, audioContext.currentTime);
    gain.gain.exponentialRampToValueAtTime(.001, audioContext.currentTime + duration);
    oscillator.connect(gain).connect(audioContext.destination);
    oscillator.start();
    oscillator.stop(audioContext.currentTime + duration);
  }

  function stopPrayerMusic() {
    if (prayerAudio) {
      clearInterval(prayerAudio);
      prayerAudio = null;
    }
  }

  function playCue(name) {
    if (!soundEnabled) { stopPrayerMusic(); return; }
    if (name === "IDLE") { tone(523, .24, .035); return; }
    if (name === "PRAYER") {
      if (!prayerAudio) {
        let beat = 0;
        prayerAudio = setInterval(() => tone([440, 554, 659][beat++ % 3], .75, .018), 1150);
      }
      return;
    }
    stopPrayerMusic();
    if (name === "BLESSING") {
      tone(740, .35, .09);
      setTimeout(() => tone(988, .55, .07), 180);
    } else if (name === "QUESTION") tone(590, .2);
    else if (name === "FEEDBACK") tone(720, .25);
    else if (name === "NAME") tone(470, .22);
    else if (name === "RESULTS") tone(880, .4);
  }

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char]));
  }

  function setContent(html) {
    content.innerHTML = html;
  }

  function render(state) {
    const {state: mode, payload = {}, gesture = {}} = state;
    const previousSnapshot = currentSnapshot;
    currentSnapshot = state;
    if (mode !== "NAME") stopSpeechRecognition();
    else if (previousSnapshot?.state === "NAME" && previousSnapshot.payload?.name && !payload.name) {
      namePostPending = false;
      if (microphonePermissionGranted) window.setTimeout(startSpeechRecognition, 0);
    }
    else if (previousSnapshot && previousSnapshot.state !== "NAME" && microphonePermissionGranted) {
      window.setTimeout(startSpeechRecognition, 0);
    }
    soundEnabled = state.sound_enabled !== false;
    if (mode !== previousState) {
      playCue(mode);
      if (mode === "BLESSING" && soundEnabled && "speechSynthesis" in window) {
        window.speechSynthesis.cancel();
        window.speechSynthesis.speak(new SpeechSynthesisUtterance("Thank you for celebrating with us."));
      }
      previousState = mode;
    }
    const progress = Math.max(0, Math.min(1, Number(gesture.progress) || 0));
    ring.style.setProperty("--progress", `${progress * 100}%`);
    ring.style.opacity = mode === "IDLE" || mode === "QUESTION" || mode === "NAME" || mode === "PRAYER" ? ".95" : ".45";
    const fingerValue = gesture.value;
    countIcon.textContent = fingerValue === "namaste" ? "🙏" : fingerValue === 5 ? "✋" : Number.isInteger(fingerValue) ? `${fingerValue} ☝` : "✋";
    if (mode === "IDLE") coach.textContent = "Say your name to begin";
    else if (gesture.awaiting_release) coach.textContent = mode === "NAME"
      ? payload.name
        ? "Lower your hand briefly, then show 1 finger to confirm or 2 to retry"
        : "Lower your hand briefly, then show it again"
      : "Lower your hand briefly, then show your answer again";
    else if (mode === "NAME") coach.textContent = speechRecognitionActive
      ? "Microphone on — say your name"
      : payload.name
      ? "Show 1 finger to confirm, or 2 to say it again"
      : "Enable the microphone and say your name";
    else if (Number.isInteger(fingerValue)) coach.textContent = fingerValue === 5
      ? "5 fingers detected — hold steady"
      : `${fingerValue} finger${fingerValue === 1 ? "" : "s"} detected — hold steady`;
    else if (gesture.confidence > 0 && gesture.confidence < .75) coach.textContent = "Hold still";
    else if (fingerValue === null) coach.textContent = "Show one hand clearly";
    else if (progress > 0 && progress < 1) coach.textContent = "Hold still";
    else coach.textContent = "Move closer or show your hands clearly";

    const stateLabels = {IDLE:"YOUR NAME", NAME:"YOUR NAME", QUESTION:"QUESTION", FEEDBACK:"YOUR ANSWER", RESULTS:"YOUR SCORE", PRAYER:"A MOMENT OF PEACE", BLESSING:"A BLESSING FOR YOU"};
    label.textContent = stateLabels[mode] || mode;
    const signature = `${mode}:${JSON.stringify(payload)}`;
    if (signature === previousView) return;
    previousView = signature;
    if (mode === "IDLE") {
      setContent('<h2>Welcome, seeker of wisdom</h2><p>Say your name to begin your Navadurga quiz.</p><div class="gesture-help">🎙️ &nbsp; Speak your name</div>');
    } else if (mode === "NAME") {
      const message = window.KIOSK_SIMULATE
        ? '<p id="voice-status" class="feedback-reason" role="status">Microphone capture is disabled in simulation. Run the app normally to use the microphone.</p>'
        : `<p id="voice-status" class="voice-status" role="${micErrorText ? "alert" : "status"}">${escapeHtml(payload.name ? `I heard ${payload.name}. Show 1 finger to confirm, or 2 to say it again.` : micErrorText || micStatusText || "The microphone is off. Enable it to say your name.")}</p>`;
      const startButton = window.KIOSK_SIMULATE ? "" : `<button class="mic-retry" id="mic-start" type="button"${speechRecognitionActive ? " disabled" : ""}>${speechRecognitionActive ? "Microphone on — say your name" : "Enable microphone & say your name"}</button>`;
      setContent(`<div class="microphone-icon" aria-hidden="true">${speechRecognitionActive ? "🔴" : "🎙️"}</div><h2>${escapeHtml(payload.prompt || "Please say your name")}</h2>${message}${startButton}<p class="gesture-help">${window.KIOSK_SIMULATE ? "Use the simulation test endpoint to provide a test name." : payload.name ? "Show 1 finger to confirm and start, or 2 fingers to say your name again" : "Allow microphone access, then say your name. Speech recognition may use your browser's online speech service."}</p>`);
    } else if (mode === "QUESTION") {
      const seconds = Number(payload.seconds) || 20;
      const options = (payload.options || []).map((option, index) => `<div class="option"><span class="number">${index + 1}</span>${escapeHtml(option)}</div>`).join("");
      setContent(`<p class="timer">Question ${payload.number} of ${payload.total} &nbsp; • &nbsp; ${escapeHtml(payload.difficulty)}</p><div class="countdown-ring" id="countdown-ring" data-duration="${seconds}" data-ends="${payload.ends_at || ""}" style="--timer-progress:100%"><span>${seconds}</span></div><p class="question">${escapeHtml(payload.question)}</p><div class="options">${options}</div><p class="timer">Raise 1–4 fingers</p>`);
    } else if (mode === "FEEDBACK") {
      const selected = payload.selected;
      const options = (payload.options || []).map((option, index) => {
        const classes = ["option", index === selected ? "selected" : "", payload.feedback_phase === "feedback" && index === payload.correct_index ? "correct" : ""].filter(Boolean).join(" ");
        return `<div class="${classes}"><span class="number">${index + 1}</span>${escapeHtml(option)}</div>`;
      }).join("");
      if (payload.feedback_phase === "select") {
        setContent(`<h2>Your answer</h2><p class="question">${escapeHtml((payload.options || [])[selected] || "")}</p><div class="options">${options}</div>`);
      } else {
        setContent(`<h2>${escapeHtml(payload.message || "Not quite")}</h2><p>${payload.correct ? `+${payload.points} points` : "The correct answer is highlighted."}</p><div class="options">${options}</div><p class="feedback-reason">${escapeHtml(payload.reason || "")}</p>`);
      }
    } else if (mode === "RESULTS") {
      setContent(`<h2>Well done, ${escapeHtml(payload.name)}!</h2><p class="result-score">${Number(payload.score) || 0} points</p><p>${escapeHtml(payload.prompt || "")}</p><p>Your score is now on the community leaderboard.</p>`);
    } else if (mode === "PRAYER") {
      setContent(`<div class="prayer-hands">🙏</div><h2>Take a moment</h2><p>${escapeHtml(payload.prompt || "Join your hands in prayer to receive a blessing.")}</p>`);
    } else if (mode === "BLESSING") {
      setContent(`<img class="blessing-image" src="${escapeHtml(payload.image)}" alt="${escapeHtml(payload.goddess)}"><h2>${escapeHtml(payload.goddess)}</h2><p class="blessing-slogan">${escapeHtml(payload.slogan)}</p><p>${escapeHtml(payload.prompt)}</p><p class="gesture-help">Thank you for celebrating with us</p>`);
    }
  }

  function connect() {
    const protocol = location.protocol === "https:" ? "wss:" : "ws:";
    const socket = new WebSocket(`${protocol}//${location.host}/ws`);
    socket.onmessage = event => {
      try { render(JSON.parse(event.data)); } catch (error) { console.error("Could not render kiosk state", error); }
    };
    socket.onclose = () => setTimeout(connect, 1000);
  }
  connect();
  const cameraStatus = document.getElementById("camera-status");
  async function refreshCameraStatus() {
    try {
      const response = await fetch("/api/camera/status");
      if (!response.ok) throw new Error(`Camera status request failed (${response.status})`);
      const result = await response.json();
      cameraStatus.textContent = result.status;
      cameraStatus.classList.toggle("camera-error", /unavailable|failed|not found|disconnected|black|dark/i.test(result.status));
    } catch (error) {
      cameraStatus.textContent = "Camera status unavailable";
      cameraStatus.classList.add("camera-error");
      console.error("Could not read camera status", error);
    }
  }
  refreshCameraStatus();
  setInterval(refreshCameraStatus, 2000);
  setInterval(() => {
    const countdown = document.getElementById("countdown-ring");
    if (!countdown) return;
    const secondsLeft = Math.max(0, Number(countdown.dataset.ends) - Date.now() / 1000);
    countdown.style.setProperty("--timer-progress", `${secondsLeft / Number(countdown.dataset.duration) * 100}%`);
    countdown.firstElementChild.textContent = String(Math.ceil(secondsLeft));
  }, 100);

  async function action(value) {
    const url = window.KIOSK_SIMULATE ? "/api/dev/action" : "/api/volunteer/action";
    try {
      const response = await fetch(url, {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({action:value})});
      if (!response.ok) console.warn("Volunteer hotkey was not accepted", response.status);
    } catch (error) { console.error("Volunteer action failed", error); }
  }
  content.addEventListener("click", async event => {
    if (event.target.id !== "mic-start") return;
    const button = event.target;
    button.disabled = true;
    await startSpeechRecognition();
    if (!speechRecognitionActive) button.disabled = false;
  });
  document.addEventListener("keydown", event => {
    if (audioContext && audioContext.state === "suspended") audioContext.resume();
    if (event.target && ["INPUT","TEXTAREA"].includes(event.target.tagName)) return;
    const key = event.key.toLowerCase();
    if (key === "escape") { event.preventDefault(); action("reset"); }
    else if (["1","2","3","4"].includes(key)) action(key);
    else if (key === "p") action("namaste");
    else if (key === "n") action("skip");
  });
})();
