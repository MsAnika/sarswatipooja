(() => {
  const board = document.getElementById("leaderboard");
  const podium = document.getElementById("podium");
  let lastVersion = -1;
  let boardSignature = "";
  let animatedFinisher = null;
  const html = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  function update(snapshot) {
    if (snapshot.version === lastVersion) return;
    lastVersion = snapshot.version;
    const rows = snapshot.leaderboard || [];
    const nextSignature = JSON.stringify(rows);
    if (nextSignature !== boardSignature) {
      board.innerHTML = rows.map((row, index) => {
        const animate = row.id === snapshot.newest_finisher && row.id !== animatedFinisher;
        return `<li class="${animate ? "new-finisher" : ""}"><span class="rank">#${index + 1}</span><span>${html(row.name)}</span><span class="score">${row.score} pts</span></li>`;
      }).join("");
      if (rows.some(row => row.id === snapshot.newest_finisher)) animatedFinisher = snapshot.newest_finisher;
      boardSignature = nextSignature;
      document.getElementById("empty-board").hidden = rows.length > 0;
      const top = rows.slice(0,3);
      const positions = [top[1], top[0], top[2]];
      const classes = ["second","first","third"];
      const medals = ["🥈","🥇","🥉"];
      podium.innerHTML = positions.map((entry, index) => entry ? `<div class="podium-item ${classes[index]}"><div class="medal">${medals[index]}</div><div class="podium-name">${html(entry.name)}</div><div class="podium-score">${entry.score} pts</div></div>` : "").join("");
    }
    const now = snapshot.now_playing || {};
    const playing = now.active ? html(now.name) : "Welcome! Show an open palm to begin";
    document.getElementById("playing-text").textContent = playing;
    document.getElementById("playing-progress").textContent = now.active ? `Question ${now.question || 0} / ${now.total || 5}` : "";
    podium.hidden = !now.idle;
  }
  function connect() {
    const socket = new WebSocket(`${location.protocol === "https:" ? "wss:" : "ws:"}//${location.host}/ws`);
    socket.onmessage = event => update(JSON.parse(event.data));
    socket.onclose = () => setTimeout(connect, 1000);
  }
  connect();
})();
