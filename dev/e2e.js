// Drives the local stack in headless Chromium with a fake camera. Start dev/run.sh first.
//   NODE_PATH=$(npm root -g) node dev/e2e.js
// BASE and DECIDER_PORT point it at a stack on other ports.
const { chromium } = require("playwright");
const { execSync, spawn } = require("child_process");
const path = require("path");

const REPO = process.env.REPO || path.resolve(__dirname, "..");
const PY = process.env.PY || "python3";
const OUT = process.env.OUT || require("os").tmpdir();
const BASE = process.env.BASE || "http://localhost:9000";
const DECIDER_PORT = process.env.DECIDER_PORT || "8080";
const IMAGES = ["deepfashion_0.jpg", "deepfashion_10.jpg", "deepfashion_4.jpg"]
  .map((f) => path.join(REPO, "bench", ".images", f));
const state = (page) => page.getAttribute("#state", "data-state");
async function decided(page) {
  await page.waitForSelector('#mode-look:is([data-phase="revealed"], [data-phase="failed"])', { timeout: 60000 });
  if (await page.$('#mode-look[data-phase="failed"]')) throw new Error(`/choose failed: ${await page.textContent("#hint")}`);
}
const log = (...a) => console.log(new Date().toISOString().slice(11, 19), ...a);

(async () => {
  const browser = await chromium.launch({
    args: ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"],
  });
  const page = await browser.newPage({ viewport: { width: 1280, height: 720 } });
  const errors = [];
  let expectHttpErrors = false;
  page.on("console", (m) => {
    log("console:", m.text());
    const expected = expectHttpErrors && /status of (401|503)/.test(m.text());
    if (m.type() === "error" && !expected) errors.push(m.text());
  });
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto(`${BASE}/#termometro`);
  log("initial state", await state(page));

  await page.click("#start");
  await page.waitForSelector('#state[data-state="live"]', { timeout: 20000 });
  log("reached live");

  const seen = new Set();
  for (let i = 0; i < 20; i++) {
    seen.add(await page.textContent("#pct"));
    await page.waitForTimeout(150);
  }
  log("score values seen", [...seen].join(","));
  if (seen.size < 3) throw new Error("score did not update");

  await page.click("#styleme");
  await page.waitForFunction(() => {
    const t = document.getElementById("advice").textContent;
    return t && t !== "pensando…";
  }, null, { timeout: 15000 });
  log("advice:", await page.textContent("#advice"));
  await page.screenshot({ path: `${OUT}/e2e-mock.png` });

  expectHttpErrors = true;
  execSync(`pkill -f 'uvicorn [d]ecider.app.*--port ${DECIDER_PORT}'`);
  log("decider stopped; /status ->", execSync(`curl -s -H 'x-demo-key: dev' ${BASE}/status`).toString());
  await page.waitForSelector('#state[data-state="cold"]', { timeout: 15000 });
  log("page state", await state(page), "| badge:", await page.textContent("#state"),
      "| warm visible:", await page.isVisible("#warm"));
  await page.screenshot({ path: `${OUT}/e2e-mock-decider-down.png` });

  const dec = spawn(PY, ["-m", "uvicorn", "decider.app:app", "--host", "127.0.0.1", "--port", DECIDER_PORT],
    { cwd: REPO, env: { ...process.env, DECIDER_MOCK: "1" }, stdio: "ignore", detached: true });
  dec.unref();
  for (let i = 0; i < 50; i++) {
    try { execSync(`curl -sf localhost:${DECIDER_PORT}/ping`); break; } catch (e) { await page.waitForTimeout(200); }
  }
  const publicWarm = execSync(`curl -s -o /dev/null -w '%{http_code}' -X POST -H 'x-demo-key: dev' ${BASE}/warm`).toString();
  if (publicWarm !== "401") throw new Error(`/warm with only the public key returned ${publicWarm}`);
  log("/warm with only the public demo key ->", publicWarm);

  page.once("dialog", (d) => d.accept("wrong"));
  await page.click("#warm");
  await page.waitForFunction(() => document.getElementById("status").textContent === "chave do apresentador errada",
    null, { timeout: 5000 });
  log("wrong presenter key -> stays", await state(page));

  page.once("dialog", (d) => d.accept("dev-admin"));
  await page.click("#warm");
  await page.waitForSelector('#state[data-state="live"]', { timeout: 15000 });
  log("after Warm up with decider back:", await state(page));
  expectHttpErrors = false;

  let scores = 0;
  page.on("request", (r) => { if (r.url().endsWith("/score")) scores++; });
  await page.evaluate(() => {
    Object.defineProperty(document, "hidden", { value: true, configurable: true });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await page.waitForSelector('#state[data-state="paused"]', { timeout: 5000 });
  await page.waitForTimeout(300);
  const before = scores;
  await page.waitForTimeout(1500);
  if (scores !== before) throw new Error(`frames sent while paused: ${scores - before}`);
  log("tab hidden -> paused, no frames sent in 1.5 s");
  await page.evaluate(() => { delete document.hidden; });

  await page.click("#resume");
  await page.waitForSelector('#state[data-state="live"]', { timeout: 15000 });
  await page.click("#stop");
  await page.waitForSelector('#state[data-state="off"]', { timeout: 5000 });
  const tracks = await page.evaluate(() => !!document.getElementById("video").srcObject);
  if (tracks) throw new Error("camera still on after Stop");
  log("Resume -> live, Stop -> off with camera released");

  // Escolher o look
  await page.click("#tab-look");
  await page.waitForSelector('#mode-look[data-cam="on"]', { timeout: 10000 });
  await page.waitForFunction(() => document.getElementById("lookcam").videoWidth > 0, null, { timeout: 10000 });
  await page.click('[data-slot="0"] .snap');
  await page.waitForSelector('[data-slot="0"][data-state="filled"][data-src="camera"]', { timeout: 5000 });
  log("slot A captured from the live camera");

  for (const [i, file] of IMAGES.entries()) await page.setInputFiles(`[data-slot="${i}"] input[type=file]`, file);
  await page.waitForSelector('[data-slot="2"][data-state="filled"][data-src="file"]', { timeout: 5000 });
  if (!(await page.isDisabled("#decide"))) throw new Error("DECIDIR enabled without an occasion");
  await page.click('.chip:has-text("Jantar romântico")');
  if (await page.isDisabled("#decide")) throw new Error("DECIDIR disabled with 3 looks and an occasion");
  log("3 looks uploaded, occasion chip picked");

  const sent = page.waitForRequest((r) => r.url().endsWith("/choose"));
  await page.click("#decide");
  const body = (await sent).postDataJSON();
  if (body.occasion !== "Jantar romântico" || body.images.length !== 3) throw new Error(`bad /choose body: ${body.occasion}, ${body.images.length} images`);
  const sides = await page.evaluate((imgs) => Promise.all(imgs.map((src) => new Promise((ok, fail) => {
    const im = new Image();
    im.onload = () => ok(Math.max(im.width, im.height));
    im.onerror = fail;
    im.src = src;
  }))), body.images);
  if (!body.images.every((s) => s.startsWith("data:image/jpeg")) || sides.some((s) => s > 512)) {
    throw new Error(`frames not JPEG at most 512 px: ${sides}`);
  }
  log("POST /choose with occasion and 3 JPEGs, longest sides", sides.join(","));

  await decided(page);
  await page.waitForTimeout(3000);
  const reveal = await page.evaluate(() => {
    const scored = [...document.querySelectorAll(".polaroid.scored")];
    return {
      verdict: document.getElementById("mode-look").dataset.verdict,
      margin: document.getElementById("margin").textContent,
      picked: [...document.querySelectorAll(".polaroid.picked .stamp")].filter((s) => s.getBoundingClientRect().width > 0).length,
      bars: scored.map((el) => {
        const bar = el.querySelector(".fitbar");
        const fill = bar.querySelector("i").offsetWidth;
        return { fit: +el.querySelector(".fitnum").textContent, pct: Math.round((100 * fill) / bar.clientWidth) };
      }),
      json: JSON.parse(document.getElementById("engine-json").textContent),
      pass: document.getElementById("engine-pass").textContent,
    };
  });
  log("reveal:", JSON.stringify({ ...reveal, json: undefined }));
  if (reveal.picked !== 1) throw new Error(`expected one winner stamp, saw ${reveal.picked}`);
  if (reveal.bars.length !== 3) throw new Error(`expected 3 fit bars, saw ${reveal.bars.length}`);
  for (const [k, b] of reveal.bars.entries()) {
    if (b.fit !== reveal.json.looks[k].fit) throw new Error(`card ${k} shows ${b.fit}, Choice says ${reveal.json.looks[k].fit}`);
    if (Math.abs(b.pct - b.fit) > 3) throw new Error(`card ${k} bar at ${b.pct}% for fit ${b.fit}`);
  }
  const tie = !reveal.json.confident;
  if (tie !== (reveal.verdict === "tie") || tie !== reveal.margin.includes("EMPATE TÉCNICO")) {
    throw new Error(`confident=${reveal.json.confident} but page shows ${reveal.margin}`);
  }
  const marginText = (c) => c.margin.toFixed(2).replace(".", ",");
  if (!reveal.margin.includes(marginText(reveal.json))) throw new Error(`margin shows ${reveal.margin}, Choice says ${reveal.json.margin}`);
  if (!reveal.pass.includes("0 tokens gerados")) throw new Error(`capô line: ${reveal.pass}`);
  await page.screenshot({ path: `${OUT}/e2e-look-reveal.png` });

  const explainLabel = await page.textContent("#explain");
  if (explainLabel !== (tie ? "Pedir desempate ao estilista" : "Por quê?")) throw new Error(`explain button says ${explainLabel}`);
  await page.click("#explain");
  await page.waitForSelector('#look-advice[data-tone="done"]', { timeout: 30000 });
  log(`stylist (${explainLabel}):`, await page.textContent("#look-advice"));

  await page.click('.chip:has-text("Corrida no parque")');
  await page.waitForSelector('#mode-look[data-phase="editing"]', { timeout: 5000 });
  if (await page.$(".polaroid.scored")) throw new Error("result still shown after changing the occasion");
  await page.click("#decide");
  await decided(page);
  const again = await page.evaluate(() => JSON.parse(document.getElementById("engine-json").textContent));
  const againMargin = await page.textContent("#margin");
  if (again.occasion !== "Corrida no parque" || !againMargin.includes(marginText(again))) {
    throw new Error(`second decision: ${again.occasion}, page margin ${againMargin}, Choice margin ${again.margin}`);
  }
  log("new occasion -> back to the live video, decided again:", againMargin, "| pick", again.pick);

  if (errors.length) throw new Error(`console errors:\n${errors.join("\n")}`);
  log("no unexpected console errors");
  await browser.close();
})().catch((e) => { console.error("FAIL", e); process.exit(1); });
