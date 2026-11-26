// Webcam -> front door -> decider, as a state machine:
// off -> starting -> cold -> warming -> live, plus error.
const CFG = window.OUTFIT_CONFIG || null;
const MAX_SIDE = 512;
const SMOOTH = 0.2;
const POLL_MS = 5000;
const MOODS = [
  [85, "さいこう！ ✦"],
  [65, "いいかも ♡"],
  [40, "ふつう〜"],
  [0,  "もうすこし…"],
];
const LABELS = {
  off: "camera off",
  starting: "starting…",
  cold: "model asleep",
  warming: "warming up…",
  live: "live",
  error: "error",
};

const $ = (id) => document.getElementById(id);
const video = $("video"), canvas = $("canvas"), ctx = canvas.getContext("2d");
let state = "off", epoch = 0;
let raw = null, shown = 0, lastVerdict = null;

const ENTER = {
  off() {},
  async starting(my) {
    try {
      if (!video.srcObject) {
        video.srcObject = await navigator.mediaDevices.getUserMedia({
          video: { width: { ideal: 1280 }, height: { ideal: 720 } }, audio: false,
        });
      }
      await video.play();
    } catch (e) {
      return go("error", "camera blocked: " + e.message);
    }
    $("placeholder").hidden = true;
    if (my === epoch) await checkStatus(my);
  },
  cold() {},
  async warming(my) {
    while (my === epoch) {
      await sleep(POLL_MS);
      if (my === epoch) await checkStatus(my);
    }
  },
  async live(my) {
    while (my === epoch) {
      const frame = grab();
      if (!frame) { await sleep(100); continue; }
      let res;
      try {
        res = await api("POST", "/score", { image: frame });
      } catch (e) {
        if (my === epoch) go("error", "front door unreachable");
        return;
      }
      if (my !== epoch) return;
      if (res.status === 200) {
        lastVerdict = res.body;
        raw = res.body.score;
        $("styleme").disabled = false;
        $("status").textContent = `${Math.round(res.body.ms)} ms / frame`;
      } else if (res.status === 503 && res.body.state) {
        return go(res.body.state);
      } else {
        return go("error", res.body.error || `score failed (${res.status})`);
      }
    }
  },
  error() {},
};

function go(next, detail) {
  if (!(next in ENTER)) { detail = `unknown state ${next}`; next = "error"; }
  state = next;
  const my = ++epoch;
  const badge = $("state");
  badge.dataset.state = next;
  badge.textContent = LABELS[next];
  document.body.dataset.state = next;
  $("warm").hidden = next !== "cold";
  $("retry").hidden = next !== "error";
  if (next !== "live") $("status").textContent = detail || LABELS[next];
  ENTER[next](my);
}

async function checkStatus(my) {
  try {
    const res = await api("GET", "/status");
    if (my !== epoch) return;
    if (res.status !== 200) return go("error", res.body.error || `status failed (${res.status})`);
    if (res.body.state !== state) go(res.body.state);
  } catch (e) {
    if (my === epoch) go("error", "front door unreachable");
  }
}

async function warm() {
  $("warm").disabled = true;
  try {
    const res = await api("POST", "/warm");
    if (res.status !== 202) return go("error", res.body.error || `warm failed (${res.status})`);
    go(res.body.state === "live" ? "live" : "warming");
  } catch (e) {
    go("error", "front door unreachable");
  } finally {
    $("warm").disabled = false;
  }
}

async function styleMe() {
  if (!lastVerdict) return;
  const advice = $("advice");
  advice.hidden = false;
  advice.textContent = "thinking…";
  $("styleme").disabled = true;
  try {
    const r = await fetch(`${CFG.stylistUrl}/style`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ verdict: lastVerdict }),
    });
    const body = await r.json();
    advice.textContent = r.ok ? body.advice : `stylist error (${r.status})`;
  } catch (e) {
    advice.textContent = "stylist unreachable";
  } finally {
    $("styleme").disabled = false;
  }
}

async function api(method, path, body) {
  const r = await fetch(`${CFG.frontdoorUrl}${path}`, {
    method,
    headers: { "content-type": "application/json", "x-demo-key": CFG.demoKey },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  let parsed = {};
  try { parsed = await r.json(); } catch (e) {}
  return { status: r.status, body: parsed };
}

function grab() {
  if (!video.videoWidth) return null;
  const s = Math.min(1, MAX_SIDE / Math.max(video.videoWidth, video.videoHeight));
  canvas.width = Math.round(video.videoWidth * s);
  canvas.height = Math.round(video.videoHeight * s);
  ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
  return canvas.toDataURL("image/jpeg", 0.8);
}

function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }

function tick() {
  if (raw !== null) {
    shown += SMOOTH * (raw - shown);
    const v = Math.round(shown);
    $("pct").textContent = v;
    $("fill").style.width = `${shown}%`;
    $("mood").textContent = MOODS.find(([min]) => v >= min)[1];
  }
  requestAnimationFrame(tick);
}

// Scatter stickers around the border, never over the camera window.
function decorate() {
  const glyphs = ["♡", "♥", "✦", "★", "☆", "✧", "♪", "❀"];
  const colors = ["#fff", "#f3d6ff", "#fff6c9", "#cfe8ff", "#e6d4ff"];
  const box = $("stickers");
  const spots = [];
  for (let i = 0; i < 14; i++) {
    const t = i / 14;
    spots.push([t * 100, 3], [t * 100, 95]);
  }
  for (let i = 1; i < 6; i++) spots.push([2.5, i * 16], [97.5, i * 16]);
  spots.forEach(([x, y], i) => {
    if (y < 10 && x < 45) return; // leave room for the title
    if (y > 90 && x > 80) return; // and the date stamp
    const s = document.createElement("span");
    s.textContent = glyphs[i % glyphs.length];
    s.style.left = `calc(${x}% - 0.5em)`;
    s.style.top = `calc(${y}% - 0.5em)`;
    s.style.color = colors[i % colors.length];
    s.style.fontSize = `${18 + ((i * 7) % 14)}px`;
    s.style.setProperty("--r", `${(i % 2 ? 1 : -1) * 12}deg`);
    s.style.animationDelay = `${(i % 5) * 0.4}s`;
    box.appendChild(s);
  });
}

decorate();
$("stamp").textContent = new Date().toLocaleDateString("ja-JP");
$("start").addEventListener("click", () => go("starting"));
$("warm").addEventListener("click", warm);
$("retry").addEventListener("click", () => go(video.srcObject ? "starting" : "off"));
$("styleme").addEventListener("click", styleMe);
requestAnimationFrame(tick);
if (CFG) go("off");
else go("error", "missing config.js");
