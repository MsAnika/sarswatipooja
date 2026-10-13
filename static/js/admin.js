(() => {
  const notice = document.getElementById("notice");
  const $ = selector => document.querySelector(selector);
  async function request(url, options = {}) {
    const response = await fetch(url, {headers:{"Content-Type":"application/json",...(options.headers || {})},...options});
    if (!response.ok) throw new Error((await response.json()).detail || response.statusText);
    return response.json();
  }
  function announce(message, error = false) {
    notice.textContent = message;
    notice.style.color = error ? "#a51c30" : "#287544";
  }
  const titles = {confidence_threshold:"Confidence threshold",hold_ms:"Hold duration (ms)",vote_frames:"Voting frames",namaste_distance:"Namaste distance ratio",question_seconds:"Question timer (seconds)",idle_seconds:"Idle reset (seconds)",prayer_seconds:"Prayer timeout (seconds)",blessing_seconds:"Blessing display (seconds)",sound_enabled:"Sound enabled"};
  function settingForm(settings) {
    $("#settings").innerHTML = Object.entries(settings).map(([key,value]) => `<label>${titles[key] || key}<input data-key="${key}" type="${typeof value === "boolean" ? "checkbox" : "number"}" ${typeof value === "boolean" ? (value ? "checked" : "") : `step="${key.includes("threshold") || key.includes("distance") ? ".05" : "1"}" value="${value}"`}></label>`).join("");
  }
  async function load() {
    try {
      const [settings, questions, slogans, overview] = await Promise.all([
        request("/api/admin/settings"),request("/api/admin/content/questions"),request("/api/admin/content/slogans"),request("/api/admin/overview")
      ]);
      settingForm(settings);
      $("#questions").value = JSON.stringify(questions,null,2);
      $("#slogans").value = JSON.stringify(slogans,null,2);
      $("#activity").innerHTML = `<h3>Recent sessions</h3>${overview.sessions.map(x => `<article>${x.name} — ${x.score} pts${x.hidden ? " (hidden)" : ""} • ${new Date(x.finished_at).toLocaleString()}</article>`).join("")}<h3>Recent blessings</h3>${overview.blessings.map(x => `<article>${x.name} received ${x.goddess} (${x.slogan_id})</article>`).join("")}<h3>Gesture timeouts</h3>${overview.timeouts.map(x => `<article>${x.reason} • ${new Date(x.created_at).toLocaleString()}</article>`).join("")}`;
      $("#entries").innerHTML = overview.sessions.map(x => `<div class="entry">${x.name} — ${x.score} pts ${!x.hidden ? `<button data-hide="${x.id}">Hide entry</button>` : ""}</div>`).join("");
    } catch (error) { announce(error.message, true); }
  }
  $("#save-settings").addEventListener("click", async () => {
    try {
      const values = {};
      document.querySelectorAll("#settings input").forEach(input => {values[input.dataset.key] = input.type === "checkbox" ? input.checked : Number(input.value);});
      await request("/api/admin/settings",{method:"PUT",body:JSON.stringify({values})});
      announce("Settings saved.");
    } catch (error) { announce(error.message,true); }
  });
  document.querySelectorAll("[data-save]").forEach(button => button.addEventListener("click", async () => {
    try {
      const kind = button.dataset.save;
      await request(`/api/admin/content/${kind}`,{method:"PUT",body:$("#"+kind).value});
      announce(`${kind} saved.`);
    } catch (error) { announce(error.message,true); }
  }));
  $("#sound-toggle").addEventListener("click", async () => {
    try {
      const settings = await request("/api/admin/settings");
      const result = await request("/api/admin/sound",{method:"POST",body:JSON.stringify({enabled:!settings.sound_enabled})});
      announce(`Sound ${result.sound_enabled ? "enabled" : "disabled"}.`);
      await load();
    } catch (error) { announce(error.message,true); }
  });
  $("#entries").addEventListener("click", async event => {
    const id = event.target.dataset.hide;
    if (!id) return;
    try { await request(`/api/admin/leaderboard/${id}`,{method:"PUT",body:JSON.stringify({hidden:true})}); announce("Leaderboard entry hidden."); await load(); }
    catch (error) { announce(error.message,true); }
  });
  $("#reset-board").addEventListener("click", async () => {
    if (!confirm("Permanently remove all leaderboard entries?")) return;
    try { await request("/api/admin/leaderboard",{method:"DELETE"}); announce("Leaderboard cleared."); await load(); }
    catch (error) { announce(error.message,true); }
  });
  load();
})();
