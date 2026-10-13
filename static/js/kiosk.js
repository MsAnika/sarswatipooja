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
    } else if (name === "QUESTION" || name === "HOWTO") tone(590, .2);
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
    if (mode === "IDLE") coach.textContent = "Show an open palm to begin";
    else if (mode === "NAME") coach.textContent = "Please say your name";
    else if (gesture.confidence > 0 && gesture.confidence < .75) coach.textContent = "Hold still";
    else if (fingerValue === null) coach.textContent = "Show one hand clearly";
    else if (progress > 0 && progress < 1) coach.textContent = "Hold still";
    else coach.textContent = "Move closer or show your hands clearly";

    const stateLabels = {IDLE:"WELCOME", NAME:"YOUR NAME", HOWTO:"HOW TO PLAY", QUESTION:"QUESTION", FEEDBACK:"YOUR ANSWER", RESULTS:"YOUR SCORE", PRAYER:"A MOMENT OF PEACE", BLESSING:"A BLESSING FOR YOU"};
    label.textContent = stateLabels[mode] || mode;
    const signature = `${mode}:${JSON.stringify(payload)}`;
    if (signature === previousView) return;
    previousView = signature;
    if (mode === "IDLE") {
      setContent('<h2>Welcome, seeker of wisdom</h2><p>Show an open palm to begin your Navadurga quiz.</p><div class="gesture-help">✋ &nbsp; Hold your open palm</div>');
    } else if (mode === "NAME") {
      setContent(`<h2>${escapeHtml(payload.prompt || "Please say your name")}</h2><p>Speak clearly. Then confirm with one finger or ask to try again with two.</p>${payload.name ? `<div class="gesture-help">1 finger: Yes &nbsp; • &nbsp; 2 fingers: Again</div>` : ""}${payload.voice_error ? `<p class="feedback-reason">${escapeHtml(payload.voice_error)}</p>` : ""}`);
    } else if (mode === "HOWTO") {
      setContent(`<h2>${escapeHtml(payload.prompt || "How to play")}</h2><p>Show 1, 2, 3 or 4 fingers for your answer. Five questions, one joyful journey.</p><div class="gesture-help">① &nbsp; ② &nbsp; ③ &nbsp; ④</div>`);
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
  document.addEventListener("keydown", event => {
    if (audioContext && audioContext.state === "suspended") audioContext.resume();
    if (event.target && ["INPUT","TEXTAREA"].includes(event.target.tagName)) return;
    const key = event.key.toLowerCase();
    if (key === "escape") { event.preventDefault(); action("reset"); }
    else if (["1","2","3","4"].includes(key)) action(key);
    else if (key === "p") action("namaste");
    else if (event.code === "Space") { event.preventDefault(); action("palm"); }
    else if (key === "n") action("skip");
  });
})();
