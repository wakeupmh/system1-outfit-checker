# system1-outfit-checker

A real-time webcam "fit check": a photo-booth style page sends camera frames to a decision model,
which rates the outfit in one forward pass (no text generation). The page shows the result as a live
0–100 % meter, and a stylist agent turns the result into a few lines of advice.

Inspired by the Fit Check demo in Liquid AI's
[System One Arcade](https://huggingface.co/spaces/LiquidAI/system-one-arcade)
([blog](https://www.liquid.ai/blog/d1-open)). The code, prompt and art here are original.

Picking up the work before the talk? Start with `docs/handoff.md`.

## Parts

`docs/contract.md` is the spec every part builds against.

| Dir | Job |
|---|---|
| `decider/` | Strands Decider E2B answers five questions about one frame (`/ping`, `/invocations`). `questions.py` holds the questions and the 0–100 calibration |
| `frontdoor/` | Lambda handler: demo-key auth, `/score`, `/warm`, `/sleep`, `/status`. `local.py` runs it on port 9000 and serves `web/` |
| `stylist/` | ADK agent on Gemini that turns a verdict's numbers into advice. It never sees the image |
| `web/` | The page, a state machine `off -> starting -> cold -> warming -> live`, plus `paused` and `error`. It stops sending frames when you press Stop, hide the tab, or after 5 minutes |
| `dev/` | Runs all of it on one machine |

## Run locally

Without Docker, from a Python 3.12+ environment:

```bash
pip install -r requirements-dev.txt
dev/run.sh                                   # mock decider and stylist
DECIDER_MOCK=0 dev/run.sh                    # real Decider E2B (about 10 GB download once); uses CUDA, then Apple MPS, then CPU
STYLIST_MOCK=0 GOOGLE_API_KEY=... dev/run.sh # real Gemini stylist
```

With Docker:

```bash
docker compose -f dev/docker-compose.yml up --build
DECIDER_MOCK=0 docker compose -f dev/docker-compose.yml up --build
```

Open http://localhost:9000. The page opens on **Escolher o look** (`#look`); **Termômetro** (`#termometro`)
is the live meter. Browsers only allow the camera on
`localhost` or HTTPS. The decider listens on 8080 and the stylist on 8081. The local front door serves
the page's `config.js` itself, pointing at them with demo key `dev`. Stop the decider and the page drops to "model asleep"; start it again
and press **Warm up** with presenter key `dev-admin`.

On 4 CPU threads the real model takes about 4.6 s per frame for all five questions, so the meter moves
slowly. A 3-look decision takes 13 to 16 s with nothing else running, and 28 to 34 s when Chromium shares
the same 4 cores. A GPU is the fast path; the log line `decider ready: ... on mps` confirms a Mac uses its GPU.

## Rehearse

With the real model running (`DECIDER_MOCK=0 dev/run.sh`), drive the stage flow in a browser and check the
known answers (blazer for "Jantar romântico", plain tank for "Corrida no parque"):

```bash
NODE_PATH=$(npm root -g) node dev/rehearse.js            # studio trio, checks the picks
LOOKS=a.jpg,b.jpg,c.jpg NODE_PATH=$(npm root -g) node dev/rehearse.js   # your own looks, prints the picks
```

`BASE=https://<hosting url>` points it at the deployed page.

## Tests

```bash
pip install -r requirements-dev.txt
pytest
NODE_PATH=$(npm root -g) node dev/e2e.js   # browser check, with dev/run.sh running
```

Pull requests run all of this in GitHub Actions, plus the Terraform checks. A merge to `main` deploys to
both clouds; `docs/ci.md` has the one-time setup and where the credentials go.

## Benchmark

`bench/outfit_eval.py` scores a labelled image set with the app's own outfit question. See
`docs/unknowns.md` for results. To check your own webcam photos, name them `lounge_1.jpg`, `plain_1.jpg`,
`styled_1.jpg` and so on, and run `python bench/outfit_eval.py decider --dir <folder>`.
