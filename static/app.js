// Webcam -> d1 server -> smoothed meter.
const MAX_SIDE = 512;     // longest side of each frame sent to the model
const SMOOTH = 0.2;       // how fast the shown score follows the model
const MOODS = [
  [85, "さいこう！ ✦"],
  [65, "いいかも ♡"],
  [40, "ふつう〜"],
  [0,  "もうすこし…"],
];

const $ = (id) => document.getElementById(id);
const video = $("video"), canvas = $("canvas"), ctx = canvas.getContext("2d");
let raw = null, shown = 0, sock = null, inFlight = false;

decorate();
$("stamp").textContent = new Date().toLocaleDateString("ja-JP");
$("start").addEventListener("click", start);

async function start() {
  try {
    video.srcObject = await navigator.mediaDevices.getUserMedia({
      video: { width: { ideal: 1280 }, height: { ideal: 720 } }, audio: false,
    });
  } catch (e) {
    $("status").textContent = "camera blocked: " + e.message;
    return;
  }
  $("placeholder").hidden = true;
  await video.play();
  connect();
  requestAnimationFrame(tick);
}

function connect() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  sock = new WebSocket(`${proto}://${location.host}/ws`);
  sock.onopen = () => { $("status").textContent = "scoring…"; send(); };
  sock.onmessage = (ev) => {
    inFlight = false;
    const r = JSON.parse(ev.data);
    if (r.error) $("status").textContent = r.error;
    else { raw = r.score; $("status").textContent = `${r.ms} ms / frame`; }
    send();
  };
  sock.onclose = () => {
    inFlight = false;
    $("status").textContent = "reconnecting…";
    setTimeout(connect, 1000);
  };
}

// One frame in flight at a time: the next frame is sent as soon as the
// previous answer arrives, so the rate adapts to the model's speed.
function send() {
  if (inFlight || !sock || sock.readyState !== WebSocket.OPEN || !video.videoWidth) return;
  const s = Math.min(1, MAX_SIDE / Math.max(video.videoWidth, video.videoHeight));
  canvas.width = Math.round(video.videoWidth * s);
  canvas.height = Math.round(video.videoHeight * s);
  ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
  inFlight = true;
  sock.send(canvas.toDataURL("image/jpeg", 0.8));
}

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
    spots.push([t * 100, 3], [t * 100, 95]); // top and bottom strips
  }
  for (let i = 1; i < 6; i++) spots.push([2.5, i * 16], [97.5, i * 16]); // sides
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
