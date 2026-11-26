// Two modes on one page, each an explicit state model.
// Termômetro: webcam -> front door -> decider, off -> starting -> cold -> warming -> live, plus paused and error.
// Paused stops sending frames, so an idle GPU can scale back to zero.
// Escolher o look: a reducer over {phase, slots, occasion, choice, facts, advice}; phase is editing -> thinking -> revealed | failed.
// /choose asks each look only for its fit and whether a person is visible. The rest comes from /facts when the
// stylist is asked for.
const CFG = window.OUTFIT_CONFIG || null;
const MAX_SIDE = 512;
const SMOOTH = 0.2;
const POLL_MS = 5000;
const LIVE_LIMIT_MS = 5 * 60 * 1000;
const CHOOSE_TIMEOUT_MS = 60000;
const MOODS = [
  [85, "ARRASOU ♥"],
  [65, "TÁ ÓTIMO"],
  [40, "DÁ PRO GASTO"],
  [0, "HMM… QUASE"],
];
const LABELS = {
  off: "câmera desligada",
  starting: "ligando…",
  cold: "modelo dormindo",
  warming: "aquecendo…",
  live: "ao vivo",
  paused: "pausado",
  error: "erro",
};

const $ = (id) => document.getElementById(id);
const video = $("video"), canvas = $("canvas"), ctx = canvas.getContext("2d");

const camera = {
  stream: null,
  async get() {
    if (!this.stream || !this.stream.active) {
      this.stream = await navigator.mediaDevices.getUserMedia({
        video: { width: { ideal: 1280 }, height: { ideal: 720 } }, audio: false,
      });
    }
    return this.stream;
  },
  release() {
    if (this.stream) this.stream.getTracks().forEach((t) => t.stop());
    this.stream = null;
  },
};

function toJpeg(src, w, h) {
  if (!w || !h) return null;
  const s = Math.min(1, MAX_SIDE / Math.max(w, h));
  canvas.width = Math.round(w * s);
  canvas.height = Math.round(h * s);
  ctx.drawImage(src, 0, 0, canvas.width, canvas.height);
  return canvas.toDataURL("image/jpeg", 0.8);
}

async function api(method, path, body, extraHeaders = {}, signal) {
  const r = await fetch(`${CFG.frontdoorUrl}${path}`, {
    method,
    headers: { "content-type": "application/json", "x-demo-key": CFG.demoKey, ...extraHeaders },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal,
  });
  let parsed = {};
  try { parsed = await r.json(); } catch (e) {}
  return { status: r.status, body: parsed };
}

async function askStylist(payload) {
  try {
    const r = await fetch(`${CFG.stylistUrl}/style`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
    });
    const body = await r.json();
    return r.ok ? { ok: true, text: body.advice } : { ok: false, text: `o estilista falhou (${r.status})` };
  } catch (e) {
    return { ok: false, text: "o estilista está fora do ar" };
  }
}

function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }
const num = (x, digits) => x.toLocaleString("pt-BR", { minimumFractionDigits: digits, maximumFractionDigits: digits });

/* ---------- Termômetro ---------- */

let state = "off", epoch = 0;
let raw = null, shown = 0, lastVerdict = null;

const ENTER = {
  off() {
    video.srcObject = null;
    camera.release();
    $("placeholder").hidden = false;
  },
  async starting(my) {
    try {
      if (!video.srcObject || !video.srcObject.active) video.srcObject = await camera.get();
      await video.play();
    } catch (e) {
      if (my === epoch) go("error", "câmera bloqueada: " + e.message);
      return;
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
    const until = Date.now() + LIVE_LIMIT_MS;
    while (my === epoch) {
      if (Date.now() > until) return go("paused", "pausado depois de 5 minutos pra poupar GPU");
      const frame = toJpeg(video, video.videoWidth, video.videoHeight);
      if (!frame) { await sleep(100); continue; }
      let res;
      try {
        res = await api("POST", "/score", { image: frame });
      } catch (e) {
        if (my === epoch) go("error", "front door fora do ar");
        return;
      }
      if (my !== epoch) return;
      if (res.status === 200) {
        lastVerdict = res.body;
        raw = res.body.score;
        $("styleme").disabled = false;
        $("status").textContent = `${Math.round(res.body.ms)} ms por quadro`;
      } else if (res.status === 503 && res.body.state) {
        return go(res.body.state);
      } else {
        return go("error", res.body.error || `a avaliação falhou (${res.status})`);
      }
    }
  },
  paused() {},
  error() {},
};

function go(next, detail) {
  if (!(next in ENTER)) { detail = `estado desconhecido ${next}`; next = "error"; }
  state = next;
  const my = ++epoch;
  const badge = $("state");
  badge.dataset.state = next;
  badge.textContent = LABELS[next];
  $("mode-meter").dataset.state = next;
  $("warm").hidden = next !== "cold";
  $("retry").hidden = next !== "error";
  $("resume").hidden = next !== "paused";
  $("stop").hidden = next === "off";
  if (next !== "live") $("status").textContent = detail || LABELS[next];
  ENTER[next](my);
}

async function checkStatus(my) {
  try {
    const res = await api("GET", "/status");
    if (my !== epoch) return;
    if (res.status !== 200) return go("error", res.body.error || `status falhou (${res.status})`);
    if (res.body.state !== state) go(res.body.state);
  } catch (e) {
    if (my === epoch) go("error", "front door fora do ar");
  }
}

// The presenter key starts the GPU. It never ships in config.js, so visitors cannot run up the bill.
function adminKey() {
  let key = null;
  try { key = sessionStorage.getItem("adminKey"); } catch (e) {}
  if (!key) key = window.prompt("Chave do apresentador pra ligar o modelo:");
  if (key) { try { sessionStorage.setItem("adminKey", key); } catch (e) {} }
  return key;
}

async function warm() {
  const key = adminKey();
  if (!key) return;
  $("warm").disabled = true;
  try {
    const res = await api("POST", "/warm", undefined, { "x-admin-key": key });
    if (res.status === 401) {
      try { sessionStorage.removeItem("adminKey"); } catch (e) {}
      return go("cold", "chave do apresentador errada");
    }
    if (res.status !== 202) return go("error", res.body.error || `aquecer falhou (${res.status})`);
    go(res.body.state === "live" ? "live" : "warming");
  } catch (e) {
    go("error", "front door fora do ar");
  } finally {
    $("warm").disabled = false;
  }
}

async function styleMe() {
  if (!lastVerdict) return;
  const advice = $("advice");
  advice.hidden = false;
  advice.textContent = "pensando…";
  $("styleme").disabled = true;
  advice.textContent = (await askStylist({ verdict: lastVerdict })).text;
  $("styleme").disabled = false;
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

/* ---------- Escolher o look ---------- */

const LETTERS = ["A", "B", "C"];
const OCCASIONS = ["Jantar romântico", "Show no sábado", "Trilha", "Corrida no parque", "Casamento"];
const FORMALITY = { athleisure: "esportivo", casual: "casual", smart_casual: "esporte fino", formal: "formal", party: "festa" };
const PALETTE = { neutral: "neutra", monochrome: "monocromática", earthy: "terrosa", pastel: "pastel", bold: "vibrante" };
const THOUGHTS = [
  "olhando look por look…",
  "lendo a ocasião…",
  "conferindo os sapatos…",
  "consultando o manual do mozão…",
  "medindo o nível de produção…",
  "quase lá…",
];
// What the advice bubble says while the page waits: first for the facts, then for the stylist.
const ADVICE_WAITING = {
  facts: "lendo o traje e a paleta de cada look…",
  loading: "o estilista está pensando…",
};
const CAM_MSG = {
  off: "A câmera mostra cada look ao vivo.",
  starting: "Ligando a câmera…",
  failed: "Câmera indisponível. Use o botão ↑ de cada look pra enviar uma foto.",
};

const blankSlot = () => ({ img: null, src: "", note: "" });
const blankLook = (cam = "off") => ({
  phase: "editing",
  cam,
  slots: [blankSlot(), blankSlot(), blankSlot()],
  occasion: "",
  sent: [],
  choice: null,
  facts: null,
  error: "",
  advice: { status: "none", text: "" },
});
let look = blankLook();
const lookcam = $("lookcam");

const filledSlots = (m) => m.slots.flatMap((s, i) => (s.img ? [i] : []));
const ready = (m) => filledSlots(m).length >= 2 && m.occasion.trim() !== "";
const setSlot = (m, i, patch) => ({ ...m, slots: m.slots.map((s, j) => (j === i ? { ...s, ...patch } : s)) });

// Edits change the inputs, so they drop any result. They are ignored while a decision is in flight.
const EDITS = {
  SNAP: (m, a) => setSlot(m, a.slot, { img: a.img, src: a.src, note: "" }),
  SLOT_FAIL: (m, a) => setSlot(m, a.slot, { note: a.note }),
  CLEAR: (m, a) => setSlot(m, a.slot, blankSlot()),
  OCCASION: (m, a) => (a.text === m.occasion ? m : { ...m, occasion: a.text }),
  RESTART: (m) => blankLook(m.cam),
};

const STEPS = {
  editing: {
    DECIDE: (m) => (ready(m) ? { ...m, phase: "thinking", sent: filledSlots(m) } : m),
  },
  thinking: {
    RESULT: (m, a) => ({ ...m, phase: "revealed", choice: a.choice }),
    FAIL: (m, a) => ({ ...m, phase: "failed", error: a.error }),
  },
  revealed: {
    ASK: (m) => (m.advice.status === "none" || m.advice.status === "done" || m.advice.status === "error"
      ? { ...m, advice: { status: m.facts ? "loading" : "facts", text: "" } } : m),
    // A failed /facts sends null: the stylist then explains from the fits and the margin alone.
    FACTS: (m, a) => (a.choice === m.choice && m.advice.status === "facts"
      ? { ...m, facts: a.facts, advice: { status: "loading", text: "" } } : m),
    ADVICE: (m, a) => (a.choice === m.choice && (m.advice.status === "facts" || m.advice.status === "loading")
      ? { ...m, advice: { status: a.ok ? "done" : "error", text: a.text } } : m),
  },
  failed: {
    DECIDE: (m) => STEPS.editing.DECIDE(m),
  },
};

function reduce(m, a) {
  if (a.type === "CAMERA") return a.cam === m.cam ? m : { ...m, cam: a.cam };
  if (a.type in EDITS) {
    if (m.phase === "thinking") return m;
    const next = EDITS[a.type](m, a);
    if (next === m) return m;
    return { ...next, phase: "editing", choice: null, facts: null, error: "", advice: { status: "none", text: "" } };
  }
  const step = STEPS[m.phase][a.type];
  return step ? step(m, a) : m;
}

function dispatch(action) {
  const prev = look;
  look = reduce(look, action);
  if (look === prev) return false;
  const reshuffle = (prev.phase === "revealed") !== (look.phase === "revealed");
  const motion = !matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (reshuffle && motion && document.startViewTransition && document.body.dataset.mode === "look") {
    document.startViewTransition(() => renderLook(prev));
  } else {
    renderLook(prev);
  }
  return true;
}

function parseChoice(body, sent) {
  const ok = body && Array.isArray(body.looks) && body.looks.length === sent
    && Number.isInteger(body.pick) && body.pick >= 0 && body.pick < sent
    && typeof body.margin === "number"
    && body.looks.every((l) => typeof l.fit === "number" && typeof l.level === "number");
  return ok ? body : null;
}

function parseFacts(body, sent) {
  const ok = body && Array.isArray(body.facts) && body.facts.length === sent
    && body.facts.every((f) => f && typeof f.person === "number" && typeof f.formality === "string"
      && typeof f.palette === "string" && typeof f.shoes === "number");
  return ok ? body.facts : null;
}

// What the page says when the front door answers 503: the decider has no copy running.
const coldMessage = (body) => body.state === "warming"
  ? "O modelo ainda está aquecendo. Tenta de novo em alguns segundos."
  : "O modelo está dormindo. Aqueça no Termômetro com a chave do apresentador.";

async function decide() {
  if (!dispatch({ type: "DECIDE" })) return;
  $("look-stage").scrollIntoView({ behavior: "smooth", block: "nearest" });
  thinkingClock();
  const { occasion, sent, slots } = look;
  let res;
  try {
    res = await api("POST", "/choose", { occasion: occasion.trim(), images: sent.map((i) => slots[i].img) },
      {}, AbortSignal.timeout(CHOOSE_TIMEOUT_MS));
  } catch (e) {
    return dispatch({ type: "FAIL", error: e.name === "TimeoutError" ? "Demorou demais. Tenta de novo?" : "Front door fora do ar." });
  }
  if (res.status === 503) return dispatch({ type: "FAIL", error: coldMessage(res.body) });
  if (res.status !== 200) return dispatch({ type: "FAIL", error: res.body.error || `A decisão falhou (${res.status}).` });
  const choice = parseChoice(res.body, sent.length);
  dispatch(choice ? { type: "RESULT", choice } : { type: "FAIL", error: "Resposta inesperada do modelo." });
}

async function explain() {
  if (!dispatch({ type: "ASK" })) return;
  const choice = look.choice;
  const { sent, slots } = look;
  let { facts } = look;
  if (!facts) {
    let res;
    try {
      res = await api("POST", "/facts", { images: sent.map((i) => slots[i].img) }, {}, AbortSignal.timeout(CHOOSE_TIMEOUT_MS));
    } catch (e) {
      res = { status: 0, body: {} };
    }
    facts = res.status === 200 ? parseFacts(res.body, sent.length) : null;
    if (!dispatch({ type: "FACTS", choice, facts })) return;
  }
  // Without facts the stylist still explains, from the fits and the margin.
  const full = { ...choice, looks: choice.looks.map((l, k) => ({ ...l, facts: facts ? facts[k] : undefined })) };
  const answer = await askStylist({ choice: full });
  dispatch({ type: "ADVICE", choice, ...answer });
}

async function startLookCam() {
  if (look.cam === "on" || look.cam === "starting") return;
  dispatch({ type: "CAMERA", cam: "starting" });
  try {
    const stream = await camera.get();
    if (look.cam !== "starting") return;
    lookcam.srcObject = stream;
    await lookcam.play();
    dispatch({ type: "CAMERA", cam: "on" });
  } catch (e) {
    if (look.cam === "starting") dispatch({ type: "CAMERA", cam: "failed" });
  }
}

function stopLookCam() {
  lookcam.srcObject = null;
  dispatch({ type: "CAMERA", cam: "off" });
}

function replay(el, cls) {
  el.classList.remove(cls);
  void el.offsetWidth;
  el.classList.add(cls);
}

function snap(slot) {
  const img = look.cam === "on" ? toJpeg(lookcam, lookcam.videoWidth, lookcam.videoHeight) : null;
  if (!img) return dispatch({ type: "SLOT_FAIL", slot, note: "A câmera ainda não mandou imagem." });
  if (dispatch({ type: "SNAP", slot, img, src: "camera" })) {
    replay($("flash"), "go");
    replay(slotEls[slot], "developing");
  }
}

async function upload(slot, file) {
  if (!file) return;
  try {
    const bmp = await createImageBitmap(file);
    const img = toJpeg(bmp, bmp.width, bmp.height);
    bmp.close();
    if (dispatch({ type: "SNAP", slot, img, src: "file" })) replay(slotEls[slot], "developing");
  } catch (e) {
    dispatch({ type: "SLOT_FAIL", slot, note: "Esse arquivo não é uma imagem." });
  }
}

function thinkingClock() {
  const t0 = performance.now();
  $("thinking-clock").textContent = `${num(0, 1)} s`;
  $("thinking-line").textContent = THOUGHTS[0];
  const id = setInterval(() => {
    if (look.phase !== "thinking") return clearInterval(id);
    const s = (performance.now() - t0) / 1000;
    $("thinking-clock").textContent = `${num(s, 1)} s`;
    $("thinking-line").textContent = THOUGHTS[Math.floor(s / 1.3) % THOUGHTS.length];
  }, 100);
}

function countUp(el, to, delay) {
  const t0 = performance.now() + delay;
  const step = (t) => {
    const k = Math.min(1, Math.max(0, (t - t0) / 1200));
    el.textContent = Math.round(to * (1 - Math.pow(1 - k, 3)));
    if (k < 1) requestAnimationFrame(step);
  };
  el.textContent = "0";
  requestAnimationFrame(step);
}

const slotEls = LETTERS.map((letter, i) => {
  const el = document.createElement("article");
  el.className = "polaroid";
  el.dataset.slot = i;
  el.style.setProperty("--i", i);
  el.style.viewTransitionName = `look-${letter.toLowerCase()}`;
  el.innerHTML = `
    <div class="shot">
      <img alt="Look ${letter}">
      <div class="empty">
        <span class="empty-letter">${letter}</span>
        <span class="empty-text">${i === 2 ? "opcional" : "sem foto"}</span>
      </div>
      <button class="clear" aria-label="Tirar a foto do look ${letter}">×</button>
    </div>
    <div class="stamp" aria-hidden="true">ESCOLHIDO <span>♥</span></div>
    <div class="caption">
      <span class="letter">${letter}</span>
      <div class="actions">
        <button class="btn btn-sm snap">Foto</button>
        <label class="btn btn-sm up" title="Enviar um arquivo" aria-label="Enviar arquivo pro look ${letter}">↑<input type="file" accept="image/*"></label>
      </div>
      <div class="score">
        <div class="fitbar"><i></i></div>
        <b class="fitnum">0</b>
      </div>
      <p class="facts"></p>
      <p class="note" role="alert"></p>
    </div>`;
  el.querySelector(".snap").addEventListener("click", () => snap(i));
  el.querySelector(".clear").addEventListener("click", () => dispatch({ type: "CLEAR", slot: i }));
  const input = el.querySelector("input");
  input.addEventListener("change", () => { upload(i, input.files[0]); input.value = ""; });
  $("slots").append(el);
  return el;
});

const chipEls = OCCASIONS.map((text, i) => {
  const b = document.createElement("button");
  b.className = "chip";
  b.style.setProperty("--i", i);
  b.textContent = text;
  b.addEventListener("click", () => dispatch({ type: "OCCASION", text }));
  $("chips").append(b);
  return b;
});

function hintFor(m) {
  if (m.phase === "failed") return m.error;
  if (m.phase !== "editing") return "";
  const missing = 2 - filledSlots(m).length;
  if (missing > 0) return missing === 2 ? "Fotografe ou envie pelo menos 2 looks." : "Falta 1 look.";
  if (!m.occasion.trim()) return "Escolha a ocasião.";
  return "Tudo pronto. Manda ver!";
}

function renderLook(prev) {
  const m = look;
  const section = $("mode-look");
  const busy = m.phase === "thinking";
  const choice = m.phase === "revealed" ? m.choice : null;
  section.dataset.phase = m.phase;
  section.dataset.cam = m.cam;
  section.dataset.verdict = choice ? (choice.confident ? "clear" : "tie") : "";
  $("cam-off").hidden = m.cam === "on";
  $("cam-start").hidden = m.cam === "starting";
  $("cam-start").textContent = m.cam === "failed" ? "Tentar a câmera de novo" : "Ligar a câmera";
  $("cam-msg").textContent = CAM_MSG[m.cam] || "";
  $("stage-occasion").hidden = !m.occasion.trim();
  $("stage-occasion").textContent = m.occasion.trim();

  chipEls.forEach((b) => {
    b.setAttribute("aria-pressed", String(b.textContent === m.occasion));
    b.disabled = busy;
  });
  const input = $("occasion");
  if (input.value !== m.occasion) input.value = m.occasion;
  input.disabled = busy;
  $("decide").disabled = busy || !ready(m);
  $("decide").textContent = busy ? "PENSANDO…" : "DECIDIR";
  $("hint").textContent = hintFor(m);
  $("hint").dataset.tone = m.phase === "failed" ? "error" : "";

  slotEls.forEach((el, i) => {
    const s = m.slots[i];
    el.dataset.state = s.img ? "filled" : "empty";
    el.dataset.src = s.src;
    const img = el.querySelector("img");
    if (s.img && img.getAttribute("src") !== s.img) img.src = s.img;
    if (!s.img) img.removeAttribute("src");
    el.querySelector(".note").textContent = s.note;
    el.querySelector(".snap").disabled = busy || m.cam !== "on";
    el.querySelector(".clear").disabled = busy;
    el.querySelector("input").disabled = busy;
    el.querySelector(".up").classList.toggle("disabled", busy);

    const k = choice ? m.sent.indexOf(i) : -1;
    const scored = k >= 0 ? choice.looks[k] : null;
    el.classList.toggle("scored", !!scored);
    el.classList.toggle("picked", !!scored && k === choice.pick);
    el.classList.toggle("lost", !!scored && k !== choice.pick);
    el.classList.toggle("skipped", !!choice && !scored);
    el.style.setProperty("--fit", scored ? scored.fit : 0);
    el.style.setProperty("--order", Math.max(k, 0));
    const f = scored && m.facts ? m.facts[k] : {};
    el.querySelector(".facts").textContent = [FORMALITY[f.formality], PALETTE[f.palette] && `paleta ${PALETTE[f.palette]}`]
      .filter(Boolean).join(" · ");
    if (!scored) el.querySelector(".fitnum").textContent = "0";
  });

  $("verdict").hidden = !choice;
  if (choice && choice !== prev.choice) {
    const margin = $("margin");
    const tag = document.createElement("b");
    tag.textContent = choice.confident ? `VITÓRIA DO ${LETTERS[m.sent[choice.pick]]}` : "EMPATE TÉCNICO";
    const sub = document.createElement("span");
    sub.textContent = `margem de ${num(choice.margin, 2)} nível`;
    margin.replaceChildren(tag, sub);
  }
  if (choice) {
    const explainBtn = $("explain");
    explainBtn.textContent = choice.confident ? "Por quê?" : "Pedir desempate ao estilista";
    explainBtn.disabled = m.advice.status === "facts" || m.advice.status === "loading";
    const adv = $("look-advice");
    adv.hidden = m.advice.status === "none";
    adv.dataset.tone = m.advice.status;
    adv.textContent = ADVICE_WAITING[m.advice.status] || m.advice.text;
  }

  renderEngine(m);

  if (choice && prev.phase !== "revealed") {
    slotEls.forEach((el, i) => {
      const k = m.sent.indexOf(i);
      if (k >= 0) countUp(el.querySelector(".fitnum"), choice.looks[k].fit, 400 + 350 * k);
    });
  }
}

function renderEngine(m) {
  if (m.phase === "thinking") $("engine-json").textContent = "esperando o modelo…";
  if (!m.choice) return;
  const c = m.choice;
  $("engine-model").textContent = c.model || "–";
  $("engine-ms").textContent = typeof c.ms === "number" ? `${num(Math.round(c.ms), 0)} ms` : "–";
  $("engine-pass").textContent = `${c.looks.length} looks · 1 passada por look · 0 tokens gerados`;
  const rows = c.looks.map((l, k) => {
    const row = document.createElement("div");
    row.className = "probrow";
    const name = document.createElement("b");
    name.textContent = LETTERS[m.sent[k]];
    row.append(name);
    (l.probs || []).forEach((p, lvl) => {
      const bar = document.createElement("i");
      bar.style.setProperty("--p", p);
      bar.title = `nível ${lvl + 1}: ${num(p * 100, 0)}%`;
      row.append(bar);
    });
    const lv = document.createElement("span");
    lv.textContent = `nível ${num(l.level, 2)}`;
    row.append(lv);
    return row;
  });
  $("engine-probs").replaceChildren(...rows);
  $("engine-json").textContent = JSON.stringify(c, null, 2);
}

/* ---------- modes ---------- */

function setMode() {
  const mode = location.hash === "#termometro" ? "meter" : "look";
  document.body.dataset.mode = mode;
  $("tab-look").setAttribute("aria-selected", String(mode === "look"));
  $("tab-meter").setAttribute("aria-selected", String(mode === "meter"));
  if (mode === "look") {
    if (state === "live" || state === "warming" || state === "starting") go("paused", "pausado enquanto você escolhe o look");
    if (CFG) startLookCam();
  } else {
    stopLookCam();
    if (!video.srcObject) camera.release();
  }
}

$("start").addEventListener("click", () => go("starting"));
$("warm").addEventListener("click", warm);
$("retry").addEventListener("click", () => go(video.srcObject ? "starting" : "off"));
$("resume").addEventListener("click", () => go("starting"));
$("stop").addEventListener("click", () => go("off"));
$("styleme").addEventListener("click", styleMe);
$("cam-start").addEventListener("click", startLookCam);
$("decide").addEventListener("click", decide);
$("explain").addEventListener("click", explain);
$("again").addEventListener("click", () => dispatch({ type: "RESTART" }));
$("occasion").addEventListener("input", (e) => dispatch({ type: "OCCASION", text: e.target.value }));
$("occasion").addEventListener("keydown", (e) => { if (e.key === "Enter") decide(); });
document.addEventListener("visibilitychange", () => {
  if (document.hidden && (state === "live" || state === "warming")) go("paused", "pausado com a aba escondida");
});
window.addEventListener("hashchange", setMode);

renderLook(look);
requestAnimationFrame(tick);
if (CFG) go("off");
else go("error", "config.js não encontrado");
setMode();
