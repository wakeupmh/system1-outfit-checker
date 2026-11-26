# system1-outfit-checker

A real-time webcam "fit check": a photo-booth style page sends camera frames to a decision model,
which rates the outfit in one forward pass (no text generation). The page shows the result as a live
0–100 % meter, and a stylist agent turns the result into a few lines of advice.

Inspired by the Fit Check demo in Liquid AI's
[System One Arcade](https://huggingface.co/spaces/LiquidAI/system-one-arcade)
([blog](https://www.liquid.ai/blog/d1-open)). The code, prompt and art here are original.

## Parts

`docs/contract.md` is the spec every part builds against.

| Dir | Job |
|---|---|
| `decider/` | Strands Decider E2B answers five questions about one frame (`/ping`, `/invocations`). `questions.py` holds the questions and the 0–100 calibration |
| `frontdoor/` | Lambda handler: demo-key auth, `/score`, `/warm`, `/sleep`, `/status`. `local.py` runs it on port 9000 and serves `web/` |
| `stylist/` | ADK agent on Gemini that turns a verdict's numbers into advice. It never sees the image |
| `web/` | The page, a state machine `off -> starting -> cold -> warming -> live`, plus `error` |
| `dev/` | Runs all of it on one machine |

## Run locally

Without Docker, from a Python 3.12+ environment:

```bash
pip install -r decider/requirements.txt -r stylist/requirements.txt
dev/run.sh                                   # mock decider and stylist
DECIDER_MOCK=0 dev/run.sh                    # real Decider E2B on CPU (about 10 GB download once)
STYLIST_MOCK=0 GOOGLE_API_KEY=... dev/run.sh # real Gemini stylist
```

With Docker:

```bash
docker compose -f dev/docker-compose.yml up --build
DECIDER_MOCK=0 docker compose -f dev/docker-compose.yml up --build
```

Open http://localhost:9000 and press **Start camera**. Browsers only allow the camera on
`localhost` or HTTPS. The decider listens on 8080 and the stylist on 8081. `web/config.js` points the
page at them with demo key `dev`. Stop the decider and the page drops to "model asleep"; start it again
and press **Warm up**.

On 4 CPU threads the real model takes about 4.6 s per frame for all five questions, so the meter moves
slowly. A GPU is the fast path.

## Tests

```bash
pip install pytest httpx
pytest
```

## Benchmark

`bench/outfit_eval.py` scores a labelled image set with the app's own outfit question. See
`docs/unknowns.md` for results.
