// Drives the local stack in headless Chromium with a fake camera. Start dev/run.sh first.
//   NODE_PATH=$(npm root -g) node dev/e2e.js
const { chromium } = require("playwright");
const { execSync, spawn } = require("child_process");

const REPO = process.env.REPO || require("path").resolve(__dirname, "..");
const PY = process.env.PY || "python3";
const OUT = process.env.OUT || require("os").tmpdir();
const state = (page) => page.getAttribute("#state", "data-state");
const log = (...a) => console.log(new Date().toISOString().slice(11, 19), ...a);

(async () => {
  const browser = await chromium.launch({
    args: ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"],
  });
  const page = await browser.newPage({ viewport: { width: 1000, height: 1000 } });
  page.on("console", (m) => log("console:", m.text()));
  await page.goto("http://localhost:9000/");
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
    return t && t !== "thinking…";
  }, null, { timeout: 15000 });
  log("advice:", await page.textContent("#advice"));
  await page.screenshot({ path: `${OUT}/e2e-mock.png` });

  execSync("pkill -f 'uvicorn [d]ecider.app'");
  log("decider stopped; /status ->", execSync("curl -s -H 'x-demo-key: dev' localhost:9000/status").toString());
  await page.waitForSelector('#state[data-state="cold"]', { timeout: 15000 });
  log("page state", await state(page), "| badge:", await page.textContent("#state"),
      "| warm visible:", await page.isVisible("#warm"));
  await page.screenshot({ path: `${OUT}/e2e-mock-decider-down.png` });

  const dec = spawn(PY, ["-m", "uvicorn", "decider.app:app", "--host", "127.0.0.1", "--port", "8080"],
    { cwd: REPO, env: { ...process.env, DECIDER_MOCK: "1" }, stdio: "ignore", detached: true });
  dec.unref();
  for (let i = 0; i < 50; i++) {
    try { execSync("curl -sf localhost:8080/ping"); break; } catch (e) { await page.waitForTimeout(200); }
  }
  await page.click("#warm");
  await page.waitForSelector('#state[data-state="live"]', { timeout: 15000 });
  log("after Warm up with decider back:", await state(page));

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
  await browser.close();
})().catch((e) => { console.error("FAIL", e); process.exit(1); });
