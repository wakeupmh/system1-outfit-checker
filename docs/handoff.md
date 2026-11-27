# Handoff: drive the demo to stage-ready

For a coding agent running on the presenter's own machine (a Mac, with their cloud logins and browser).
Read this file, then `docs/contract.md`, before changing anything.

## Goal

A DevFest SJC talk next week, Trilha PIT, 16:00 to 16:40: "Usando um Modelo de Decisão pra escolher o look
do meu mozão". On stage the page picks the best of 2 or 3 looks for an occasion with a small decision model,
live, and a Gemini stylist explains the pick. Done means all three are true:

1. `node dev/rehearse.js` prints `REHEARSAL OK` on the laptop with the real model (Plan B).
2. The same rehearsal passes against the deployed page with `BASE=<hosting url>` (Plan A).
3. The presenter's own looks give the pick they expect, and the meter uses most of its 0 to 100 range.

## Where things are (main at 83db326)

| Part | Where | State |
|---|---|---|
| Decider: Strands Decider E2B v2 (Gemma 4), `score` and `choose` | `decider/` | Done. Real model verified on Linux CPU |
| Front door Lambda: `/score`, `/choose`, `/status`, `/warm`, `/sleep` | `frontdoor/` | Done, unit tested. Never run in AWS |
| Stylist: ADK + Gemini, explains a Choice in pt-BR | `stylist/` | Done in mock mode. Never run with a real key |
| Page: Escolher o look and Termômetro, neobrutalist | `web/` | Done. Browser e2e passes |
| Terraform for both clouds, Makefile | `infra/`, `Makefile` | Validated and planned offline. Never applied |
| GitHub Actions: CI on PRs, deploy on merge | `.github/workflows/` | CI green. Deploy gated by `DEPLOY_ENABLED` |
| Keyless CI credentials bootstrap | `infra/bootstrap/` | Validated. Never applied |
| Measurements and open questions | `docs/unknowns.md` | Up to date |
| Demo-day runbook (artifact, not in the repo) | https://claude.ai/artifact/Xrk7UF7LN5vSNwA3fDM7k6 | Private to the presenter |

## Rules

- Never commit the presenter's photos or anything with faces. Keep them outside the repo; pass them with
  `LOOKS=` or `--dir`. Commit numbers only, anonymised, to `docs/unknowns.md`.
- Never print or commit `admin_key`, `demo_key` values, `GEMINI_API_KEY` or tfvars. `infra/terraform.tfvars`
  and state are gitignored; keep it that way.
- The GPU bills about $1.13/h in us-east-1 while warm. After any cloud test run `make sleep` and confirm
  `make status` says `cold`. Never run `make down` without the presenter saying so.
- Ask before anything that needs a person: quota requests, billing, logins, creating the GitHub environment,
  merging to `main` (merging can deploy once `DEPLOY_ENABLED=true`).
- Work on a branch, open PRs, keep CI green. `pytest` and `dev/e2e.js` must pass before every push.
- Do not ask a decision model one `choice` question over several images: it picks by position
  (`bench/choice_eval.py`). Score each look alone, as `/choose` does.

## Steps, in order

Each step ends with a check. Do not start the next until the current one passes or the presenter decides.

### 1. Plan B on the Mac

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
python bench/choice_eval.py --threads 4      # downloads the stock trio once; also a talk table
DECIDER_MOCK=0 dev/run.sh                    # first run downloads about 10 GB of weights
```

Check: the decider log says `decider ready: StrandsAgents/strands-decider-E2B-gemma4-v2-2611 on mps`. If it says
`on cpu`, find out why MPS is unavailable (`python -c "import torch; print(torch.backends.mps.is_available())"`)
before going further. Then, in a second terminal:

```bash
npm install --no-save playwright@1.63.0 && npx playwright install chromium
node dev/rehearse.js
```

Check: `REHEARSAL OK`, and note both lines' seconds. Record them in `docs/unknowns.md` under the choose-flow
timings, with the Mac model and chip.

Done in PR #9 on a MacBook Air M4: `/choose` now asks each look only its fit and `person`, and `/facts` answers
the other facts. A 3-look decision takes about 6 to 8 s on MPS. Keep `person` in `/choose`: asked for its fit
alone, a photo with nobody in it can outrank a real outfit (a cats photo scored level 1.56 against a plain
tank's 1.33). The page fetches the facts once per set of photos right after the first decision, so "Por quê?"
and a change of occasion rarely wait for them.

### 2. The presenter's own looks

Ask the presenter for 2 or 3 photos of the real looks for the talk: front-facing, full body, shoes visible,
where they will stand on stage. Then:

```bash
LOOKS=/path/a.jpg,/path/b.jpg,/path/c.jpg node dev/rehearse.js
python bench/choice_eval.py --dir /path/to/looks --occasion "jantar romântico" --occasion "corrida no parque"
python bench/outfit_eval.py decider --dir /path/to/named/looks   # lounge_*.jpg, plain_*.jpg, styled_*.jpg
```

Check: the picks match what the presenter expects for each occasion. If not, show them the per-look fits and
let them decide whether to change the occasions, the looks, or the question wording in `decider/questions.py`.

Calibrate: real photos scored about one level below stock ones. Set `LEVEL_LO`/`LEVEL_HI` (meter) and
`FIT_LO`/`FIT_HI` (choose) in `decider/questions.py` so the presenter's weakest and strongest looks land near
15 and 85. Update the calibration lines in `docs/contract.md` and the tests that pin them.

### 3. Cloud prerequisites (the presenter does these; the agent checks)

- AWS Service Quotas: `ml.g6.xlarge for endpoint usage` is at least 1 in the chosen region. If it is 0,
  the presenter requests it now; approval can take days.
- A Google Cloud project with billing linked, and a Gemini API key from AI Studio.
- `aws sts get-caller-identity` and `gcloud auth list` work in the agent's shell.

### 4. First deploy from the laptop

Follow `docs/deploy.md`. Prefer the laptop for the first run, so errors are easy to read.

Already checked without an account (C12 and C13 in `docs/unknowns.md`): the GPU decider image builds from
`decider/` and serves every route, and the front door zip runs in the Lambda runtime (`dev/lambda_check.py`, in
CI). What is left to learn here is AWS and Google themselves: quota, IAM, scale from zero, Firebase.

```bash
cp infra/terraform.tfvars.example infra/terraform.tfvars   # gcp_project, gemini_api_key
make plan
make up
make warm && make status                                   # repeat status until live; time it
BASE=<hosting url> node dev/rehearse.js
make sleep
```

Check: `REHEARSAL OK` against the hosting URL, and `make status` says `cold` at the end. Work through the
"First-run checklist" in `docs/deploy.md` and write each result into `docs/unknowns.md`: quota, GPU fit,
per-decision latency on the GPU, scale-from-zero time, scale-in time, both Lambda URL permissions.

Likely failures and where to look:

| Symptom | Likely cause | Fix |
|---|---|---|
| Endpoint stuck creating, or a capacity or quota error | GPU quota 0 or region without g6 | Quota request; try `us-west-2` |
| Inference component fails health check | Weights download over 900 s, or out of host memory | CloudWatch logs under `/aws/sagemaker/`; raise `decider_memory_mb` or use `ml.g5.xlarge` |
| Page gets 403 from the front door | Function URL permissions | Both `lambda:InvokeFunctionUrl` and `lambda:InvokeFunction` must exist (`infra/frontdoor.tf`) |
| `google_firebase_project` fails | Firebase terms not accepted | `docs/deploy.md`, "When Firebase does not work from Terraform" |
| Stylist 500s | Vertex mode instead of API key | `GOOGLE_GENAI_USE_ENTERPRISE=0` on the Cloud Run service |
| Cloud Build cannot push | Default build service account lacks Artifact Registry rights | Grant it, then rerun `make up` |

### 5. Deploys from GitHub (optional before the talk)

Follow `docs/ci.md`: apply `infra/bootstrap/`, create the `production` environment with the printed variables
and the `GEMINI_API_KEY` secret, set `TF_STATE_BUCKET` locally so the laptop and CI share state, then set
`DEPLOY_ENABLED=true`. Check: Actions > deploy > Run workflow > `status` succeeds. Skip this step if time is
short; the laptop can run `make` on the day.

### 6. Rehearsal

- Full talk timed on a phone hotspot, with the runbook open.
- A screen recording of a good run saved offline (Plan D).
- The three look photos on the laptop for the upload fallback (Plan C).

## Things that are easy to get wrong

- On 4 CPU cores a browser on the same machine halved the model's speed (13 to 16 s alone, 28 to 34 s with
  Chromium). Measure on the machine and setup used on stage.
- `make up` leaves one GPU instance running until scale-in (30 minutes idle) or `make sleep`.
- A cold `/score` or `/choose` does not wake the GPU. Only `/warm` with the admin key does (`make warm`, or the
  page's warm-up button with the presenter key).
- The demo key ships in the page; it is not a secret. The admin key is.
- Lambda and SageMaker requests are capped at 6 MB. The page sends JPEGs of at most 512 px; keep it so.
- `dev/e2e.js` uses generated stand-in photos when `bench/.images` is missing, as in CI.

## Reporting

After each step, tell the presenter in two or three lines: what ran, what passed with the numbers, what is
blocked and who has to act. Keep `docs/unknowns.md` as the record.
