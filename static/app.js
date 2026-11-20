// Mystiq - 解答画面クライアント
const API = "";
let currentPuzzle = null;
let player = JSON.parse(localStorage.getItem("mystiq_player") || "null");
let currentStage = null;
let cdTimer = null;
let competitionStarted = true;
let resultRank = "-";
let resultCardData = "";
let resultCardFile = null;
let resultCardKey = "";

const el = (id) => document.getElementById(id);

// ---------- 初期化 ----------
async function init() {
  await loadPuzzle();
  if (player) {
    el("playerName").value = player.name;
    const ok = await refreshPlayer();
    if (!ok) { player = null; localStorage.removeItem("mystiq_player"); }
  }
  updateUIState();
  await loadAnnouncement();
  setInterval(loadAnnouncement, 8000);
  setInterval(syncStatus, 8000);
}

// ---------- API ----------
async function loadPuzzle() {
  const r = await fetch(API + "/api/puzzle");
  currentPuzzle = await r.json();
  el("title").textContent = currentPuzzle.title;
  competitionStarted = currentPuzzle.competition_started;
}

async function refreshPlayer() {
  if (!player) return false;
  const r = await fetch(API + "/api/player?id=" + encodeURIComponent(player.id));
  if (!r.ok) return false;
  const data = await r.json();
  player = data.player;
  player._progress = data.progress;
  player._cooldown = data.cooldown;
  localStorage.setItem("mystiq_player", JSON.stringify(player));
  return true;
}

async function syncStatus() {
  try {
    const r = await fetch(API + "/api/status");
    const d = await r.json();
    competitionStarted = d.config.competition_started;
    // ヒントが裏で更新された可能性があるためパズル再読込
    await loadPuzzle();
    if (player) await refreshPlayer();
    updateUIState();
  } catch(e) {}
}

// ---------- UI状態遷移 ----------
function updateUIState() {
  el("bannerClosed").style.display = competitionStarted ? "none" : "block";

  if (!player) {
    el("secRegister").style.display = "block";
    el("secPlayer").style.display = "none";
    el("secStage").style.display = "none";
    el("secClear").style.display = "none";
    return;
  }

  el("secRegister").style.display = "none";
  el("secPlayer").style.display = "block";
  el("dispName").textContent = player.name;

  const prog = player._progress;
  if (!prog || !currentPuzzle) return;

  const total = currentPuzzle.stages.length;
  const cleared = prog.cleared_stages.length;
  el("dispProgress").textContent = `${cleared} / ${total} ステージクリア`;
  el("pBar").style.width = (cleared / (total || 1)) * 100 + "%";

  // ステージタブ
  const tabs = el("stageTabs");
  tabs.innerHTML = "";
  currentPuzzle.stages.forEach(st => {
    const b = document.createElement("button");
    const isCleared = prog.cleared_stages.includes(st.id);
    const isCurrent = prog.current_stage_id === st.id;
    b.className = "stage-tab" + (isCleared ? " cleared" : "") + (isCurrent ? " current" : "");
    b.textContent = (isCleared ? "✓ " : "") + st.name;
    if (isCleared) b.title = "クリア済み";
    tabs.appendChild(b);
  });

  if (prog.finished) {
    showClearScreen();
    return;
  }

  showStage(prog.current_stage_id);
}

function showStage(stageId) {
  const stage = currentPuzzle.stages.find(s => s.id === stageId);
  if (!stage) return;
  currentStage = stage;

  el("secStage").style.display = competitionStarted ? "block" : "none";
  el("secClear").style.display = "none";
  el("stBadge").textContent = stage.name;
  el("ansNote").textContent = stage.answerNote ? `※ ${stage.answerNote}` : "";

  // ヒント描画
  const list = el("hintList");
  list.innerHTML = "";
  const unlockedCount = stage.hints.filter(Boolean).length;
  el("hintCount").textContent = `${unlockedCount} / ${stage.hintsTotal} 個公開中`;
  stage.hints.forEach((h, i) => {
    const it = document.createElement("div");
    if (h) {
      it.className = "hint-item";
      it.textContent = `ヒント${i + 1}: ${h}`;
    } else {
      it.className = "hint-item locked";
      it.textContent = `ヒント${i + 1} はまだ非公開です（随時追加されます）`;
    }
    list.appendChild(it);
  });

  // クールダウン反映
  const cd = (player._cooldown && player._cooldown.seconds) || 0;
  applyCooldown(cd);

  hideBanner();
}

function showClearScreen() {
  el("secStage").style.display = "none";
  el("secClear").style.display = "block";
  el("clearMsg").textContent = currentPuzzle.clearMessage || "全ステージクリア！";
  loadResultStats();
}

// ---------- イベント ----------
el("btnStart").addEventListener("click", register);
el("playerName").addEventListener("keydown", (e) => { if (e.key === "Enter") register(); });

async function register() {
  const name = el("playerName").value.trim();
  if (!name) return toast("名前を入力してください");
  const r = await fetch(API + "/api/player/register", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name })
  });
  const d = await r.json();
  if (!d.ok) return toast(d.error);
  player = d.player;
  localStorage.setItem("mystiq_player", JSON.stringify(player));
  await refreshPlayer();
  updateUIState();
  toast(`ようこそ、${name} さん！`);
}

el("ansForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!player || !currentStage) return;
  const input = el("ansInput");
  const ans = input.value.trim();
  if (!ans) return toast("回答を入力してください");

  el("ansBtn").disabled = true;
  try {
    const r = await fetch(API + "/api/answer", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ player_id: player.id, stage_id: currentStage.id, answer: ans })
    });
    const d = await r.json();
    if (d.reason === "cooldown") {
      showBanner("wrong", d.message);
      applyCooldown(d.cooldown);
      return;
    }
    if (!d.ok) { showBanner("wrong", d.message || d.error); return; }

    if (d.result === "correct") {
      showBanner("correct", "🎉 " + d.message);
      playSfx("correct");
      // confettiBurst();
      input.value = "";
      player._progress = d.progress;
      setTimeout(updateUIState, 900);
    } else if (d.result === "already") {
      toast(d.message);
      await refreshPlayer();
      updateUIState();
    } else {
      const cls = d.reason === "near" ? "near" : "wrong";
      const icon = d.reason === "near" ? "🤔 " : "❌ ";
      showBanner(cls, icon + d.message);
      playSfx("wrong");
      if (d.cooldown) applyCooldown(d.cooldown);
      // shake(input);
    }
  } finally {
    if (!el("ansInput").disabled) el("ansBtn").disabled = false;
  }
});

function showBanner(type, msg) {
  const b = el("resultBanner");
  b.className = "result-banner " + type;
  b.textContent = msg;
}
function hideBanner() { const b = el("resultBanner"); b.className = "result-banner"; }

function applyCooldown(seconds) {
  clearInterval(cdTimer);
  const box = el("cooldownBox");
  const sec = el("cdSec");
  const input = el("ansInput");
  const btn = el("ansBtn");
  if (!seconds || seconds <= 0) { box.style.display = "none"; input.disabled = false; btn.disabled = false; return; }
  let rem = seconds;
  box.style.display = "block";
  sec.textContent = rem;
  input.disabled = true;
  btn.disabled = true;
  cdTimer = setInterval(() => {
    rem -= 1;
    sec.textContent = rem;
    if (rem <= 0) { clearInterval(cdTimer); box.style.display = "none"; input.disabled = false; btn.disabled = false; }
  }, 1000);
}

// ---------- クリア結果（順位一覧は別画面） ----------
async function loadResultStats() {
  try {
    const r = await fetch(API + "/api/ranking");
    const d = await r.json();
    if (player) {
      const me = d.ranking.find(x => x.id === player.id);
      if (me) {
        resultRank = `第${me.rank}位`;
        el("resRank").textContent = resultRank;
        el("resTime").textContent = formatTime(me.elapsed);
        refreshResultCard();
      }
    }
  } catch(e) {}
}

function formatTime(s) {
  const m = Math.floor(s / 60); const sec = s % 60;
  return `${m}分${String(sec).padStart(2,"0")}秒`;
}

// ---------- 主催者からのお知らせ（速報一覧は表示しない） ----------
async function loadAnnouncement() {
  try {
    const r = await fetch(API + "/api/announcement");
    const d = await r.json();
    el("announcementText").textContent = d.message || "";
    el("announcement").style.display = d.message ? "block" : "none";
  } catch(e) { return false; }
}

// ---------- 演出 ----------
function playSfx(type) {
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const o = ctx.createOscillator();
    const g = ctx.createGain();
    o.connect(g); g.connect(ctx.destination);
    if (type === "correct") {
      o.type = "sine";
      o.frequency.setValueAtTime(523, ctx.currentTime);
      o.frequency.setValueAtTime(659, ctx.currentTime + 0.12);
      o.frequency.setValueAtTime(784, ctx.currentTime + 0.24);
      g.gain.setValueAtTime(0.25, ctx.currentTime);
      g.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.55);
      o.start(); o.stop(ctx.currentTime + 0.55);
    } else {
      o.type = "sawtooth";
      o.frequency.setValueAtTime(200, ctx.currentTime);
      o.frequency.setValueAtTime(140, ctx.currentTime + 0.15);
      g.gain.setValueAtTime(0.2, ctx.currentTime);
      g.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.35);
      o.start(); o.stop(ctx.currentTime + 0.35);
    }
  } catch(e) {}
}

function confettiBurst() { return; // アニメーション無効化

  const canvas = el("confettiCanvas");
  const ctx = canvas.getContext("2d");
  canvas.width = window.innerWidth;
  canvas.height = window.innerHeight;
  const colors = ["#f1c40f","#58a6ff","#3fb950","#f85149","#bc8cff","#ffa657"];
  const parts = Array.from({length: 90}, () => ({
    x: canvas.width / 2, y: canvas.height * 0.35,
    vx: (Math.random() - 0.5) * 16, vy: -Math.random() * 14 - 4,
    size: Math.random() * 8 + 4, color: colors[Math.floor(Math.random()*colors.length)],
    rot: Math.random() * 360, vr: (Math.random() - 0.5) * 20, life: 1
  }));
  let frames = 0;
  function loop() {
    ctx.clearRect(0,0,canvas.width,canvas.height);
    parts.forEach(p => {
      p.x += p.vx; p.y += p.vy; p.vy += 0.45; p.rot += p.vr; p.life -= 0.012;
      ctx.save(); ctx.translate(p.x, p.y); ctx.rotate(p.rot * Math.PI / 180);
      ctx.globalAlpha = Math.max(0, p.life); ctx.fillStyle = p.color;
      ctx.fillRect(-p.size/2, -p.size/2, p.size, p.size * 0.6);
      ctx.restore();
    });
    frames++;
    if (frames < 90) requestAnimationFrame(loop); else ctx.clearRect(0,0,canvas.width,canvas.height);
  }
  loop();
}

function shake(node) { return; // アニメーション無効化

  node.style.transform = "translateX(-8px)";
  setTimeout(() => node.style.transform = "translateX(8px)", 70);
  setTimeout(() => node.style.transform = "translateX(-5px)", 140);
  setTimeout(() => node.style.transform = "translateX(0)", 210);
}

function toast(msg) {
  const t = el("toast");
  t.textContent = msg; t.style.display = "block";
  clearTimeout(t._tm);
  t._tm = setTimeout(() => t.style.display = "none", 2800);
}

// ---------- スマートフォン・SNS向け結果カード ----------
el("btnShareImg").addEventListener("click", generateResultImage);
el("btnNativeShare").addEventListener("click", shareResultImage);

function createResultCard() {
  const name = (player && player.name) || "名探偵";
  const title = (currentPuzzle && currentPuzzle.title) || "謎解きミッション";
  const time = el("resTime").textContent;
  const c = document.createElement("canvas");
  c.width = 1080; c.height = 1350;
  const ctx = c.getContext("2d");
  const g = ctx.createLinearGradient(0, 0, 1080, 1350);
  g.addColorStop(0, "#0d1726"); g.addColorStop(1, "#09101a");
  ctx.fillStyle = g; ctx.fillRect(0, 0, 1080, 1350);
  ctx.strokeStyle = "#42516a"; ctx.lineWidth = 3;
  ctx.strokeRect(48, 48, 984, 1254);
  ctx.textAlign = "center";
  ctx.fillStyle = "#d4b878"; ctx.fillRect(455, 165, 170, 5);
  ctx.font = '700 31px -apple-system, "Hiragino Sans", sans-serif';
  ctx.fillText("MYSTERY CHALLENGE", 540, 220);
  ctx.font = '800 74px -apple-system, "Hiragino Sans", sans-serif';
  ctx.fillStyle = "#f5f0e5"; ctx.fillText("MISSION CLEAR", 540, 305, 900);

  // 長い日本語名や大会名も2行まで折り返し、最後の行は幅内に収める。
  function textLines(text, y, font, color, width, lineHeight) {
    ctx.font = font; ctx.fillStyle = color;
    const chars = Array.from(String(text).replace(/\s+/g, " ").trim());
    const lines = []; let line = "";
    for (const ch of chars) {
      if (line && ctx.measureText(line + ch).width > width && lines.length < 1) {
        lines.push(line); line = ch;
      } else line += ch;
    }
    if (line) lines.push(line);
    lines.forEach((value, i) => ctx.fillText(value, 540, y + i * lineHeight, width));
  }
  textLines(title, 370, '600 42px -apple-system, "Hiragino Sans", sans-serif', "#a8b6c7", 880, 52);
  ctx.fillStyle = "#43516a"; ctx.fillRect(120, 455, 840, 2);
  ctx.fillStyle = "#a8b6c7"; ctx.font = '600 32px -apple-system, "Hiragino Sans", sans-serif';
  ctx.fillText("参加者", 540, 520);
  textLines(name, 590, '700 58px -apple-system, "Hiragino Sans", sans-serif', "#f5f0e5", 840, 70);

  ctx.fillStyle = "#182335"; ctx.fillRect(108, 720, 864, 260);
  ctx.strokeStyle = "#42516a"; ctx.lineWidth = 2; ctx.strokeRect(108, 720, 864, 260);
  ctx.fillStyle = "#42516a"; ctx.fillRect(539, 760, 2, 180);
  ctx.fillStyle = "#a8b6c7"; ctx.font = '600 34px -apple-system, "Hiragino Sans", sans-serif';
  ctx.fillText("順位", 324, 800); ctx.fillText("クリアタイム", 756, 800);
  ctx.fillStyle = "#f1cb76"; ctx.font = '700 64px -apple-system, "Hiragino Sans", sans-serif';
  ctx.fillText(resultRank, 324, 890, 380); ctx.fillText(time, 756, 890, 380);
  ctx.fillStyle = "#a8b6c7"; ctx.font = '500 30px -apple-system, "Hiragino Sans", sans-serif';
  ctx.fillText("謎解きクリア！", 540, 1090);
  return c.toDataURL("image/png");
}

function refreshResultCard() {
  const key = JSON.stringify([resultRank, el("resTime").textContent, player && player.name, currentPuzzle && currentPuzzle.title]);
  if (key === resultCardKey) return;
  try {
    const data = createResultCard();
    resultCardData = data; resultCardKey = key; resultCardFile = null;
    el("resultPreview").src = data;
    el("resultPreview").style.display = "block";
    el("btnShareImg").disabled = false;
    el("btnNativeShare").style.display = "none";
    try {
      if (typeof navigator !== "undefined" && navigator.share && navigator.canShare && typeof File === "function") {
        const bytes = Uint8Array.from(atob(data.split(",")[1]), ch => ch.charCodeAt(0));
        const file = new File([bytes], "nazotoki-result.png", {type: "image/png"});
        if (navigator.canShare({files: [file]})) {
          resultCardFile = file;
          el("btnNativeShare").style.display = "inline-flex";
        }
      }
    } catch(e) { /* 画像共有非対応時は、保存して手動投稿できる */ }
  } catch(e) {
    el("cardHelp").textContent = "画像を作成できませんでした。画面を再読み込みしてください。";
  }
}

function generateResultImage() {
  if (!resultCardData) return toast("結果カードの準備中です");
  const a = document.createElement("a");
  a.download = "nazotoki-result.png";
  a.href = resultCardData;
  a.click();
  toast("保存できない場合は画像を長押ししてください");
}

async function shareResultImage() {
  if (!resultCardFile) return;
  try { await navigator.share({files: [resultCardFile]}); }
  catch(e) { if (e.name !== "AbortError") toast("共有できない場合は画像を保存して投稿してください"); }
}

init();
