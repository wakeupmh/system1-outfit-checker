// Stage rehearsal with the REAL model: drives Escolher o look in Chromium and checks the known answers.
//   DECIDER_MOCK=0 dev/run.sh                 # in one terminal
//   NODE_PATH=$(npm root -g) node dev/rehearse.js
// BASE points it at another front door, e.g. the deployed page. Looks default to the bench studio trio
// (python bench/choice_eval.py downloads them); LOOKS=a.jpg,b.jpg,c.jpg uses your own and skips the checks.
const { chromium } = require("playwright");
const path = require("path");

const REPO = path.resolve(__dirname, "..");
const BASE = process.env.BASE || "http://localhost:9000";
const OUT = process.env.OUT || require("os").tmpdir();
const OWN = process.env.LOOKS ? process.env.LOOKS.split(",") : null;
const LOOKS = OWN || ["deepfashion_0.jpg", "deepfashion_10.jpg", "deepfashion_4.jpg"]
  .map((f) => path.join(REPO, "bench", ".images", f));
// Expected picks for the studio trio (plain tank, blazer, plaid dress), measured in docs/unknowns.md.
const CASES = [
  { chip: "Jantar romântico", expect: 1, name: "blazer" },
  { chip: "Corrida no parque", expect: 0, name: "plain tank" },
];

(async () => {
  const browser = await chromium.launch({
    args: ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"],
  });
  const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto(`${BASE}/#look`);
  for (const [i, file] of LOOKS.entries()) await page.setInputFiles(`[data-slot="${i}"] input[type=file]`, file);

  let failed = false;
  for (const c of CASES) {
    await page.click(`.chip:has-text("${c.chip}")`);
    const t = Date.now();
    await page.click("#decide");
    await page.waitForSelector('#mode-look:is([data-phase="revealed"], [data-phase="failed"])', { timeout: 120000 });
    const secs = ((Date.now() - t) / 1000).toFixed(1);
    const choice = await page.evaluate(() => {
      const el = document.getElementById("engine-json");
      return el && el.textContent ? JSON.parse(el.textContent) : null;
    });
    if (!choice) throw new Error(`${c.chip}: no decision (${await page.textContent("#mode-look")})`);
    const fits = choice.looks.map((l) => l.fit).join(" / ");
    const ok = OWN || choice.pick === c.expect;
    if (!ok) failed = true;
    console.log(`${ok ? "OK  " : "FAIL"} ${c.chip}: pick ${"ABC"[choice.pick]}${OWN ? "" : ` (expected ${"ABC"[c.expect]}, the ${c.name})`}, ` +
      `fits ${fits}, margin ${choice.margin}, ${choice.confident ? "confident" : "tie"}, ` +
      `${secs} s in the browser (model ${(choice.ms / 1000).toFixed(1)} s), ${choice.model}`);
    await page.waitForTimeout(3000);
    await page.screenshot({ path: path.join(OUT, `rehearse-${c.expect}.png`) });
  }
  if (errors.length) { failed = true; console.log("page errors:", errors); }
  await browser.close();
  console.log(failed ? "REHEARSAL FAILED" : "REHEARSAL OK");
  process.exit(failed ? 1 : 0);
})().catch((e) => { console.error("FAIL", e); process.exit(1); });
