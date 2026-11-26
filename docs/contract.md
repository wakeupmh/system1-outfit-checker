# Contract

Every component builds against this file. Change it here first.

## Parts

| Dir | Runs on | Job |
|---|---|---|
| `decider/` | SageMaker inference component (GPU), or Docker locally (CPU) | Answers the outfit questions for one frame |
| `frontdoor/` | AWS Lambda with a function URL | Auth, routing to the decider, warm-up and status |
| `stylist/` | Google Cloud Run | ADK agent with Gemini that turns a verdict into advice. Gets text only |
| `web/` | Firebase Hosting | Webcam page |
| `infra/` | Terraform, AWS and Google providers in one state | All cloud resources |
| `dev/` | Docker Compose | The whole system on one machine |

## Questions (one source of truth)

`decider/questions.py` holds the question set and the display calibration. Nothing else defines questions.

- `outfit`: `score` question, 5 levels, lowest first (the current `LEVELS` in `server.py`).
- `person`: `noul`, "Is a person with their clothes visible?"
- `formality`: `choice` over `athleisure`, `casual`, `smart_casual`, `formal`, `party`.
- `palette`: `choice` over `neutral`, `monochrome`, `earthy`, `pastel`, `bold`.
- `shoes`: `noul`, "Are shoes visible?"

All five go in one request, so the model reads the image once.

Calibration: measured levels sit between about 0.5 and 3.2 (`docs/unknowns.md`).
`score = clamp(round(100 * (level - LEVEL_LO) / (LEVEL_HI - LEVEL_LO)), 0, 100)` with
`LEVEL_LO = 0.5`, `LEVEL_HI = 3.2`. When `person < 0.5`, `score = 0`.

## Verdict

Every hop returns the same JSON for a scored frame:

```json
{
  "score": 72,
  "level": 2.44,
  "probs": [0.01, 0.08, 0.40, 0.38, 0.13],
  "facts": {"person": 0.97, "formality": "smart_casual", "palette": "neutral", "shoes": 0.91},
  "ms": 143.2,
  "model": "StrandsAgents/strands-decider-E2B-gemma4-v2-2611"
}
```

## Decider container (`decider/`)

SageMaker custom container rules: listens on port 8080, started as `docker run <image> serve`.

- `GET /ping` returns 200 once the model is loaded, 503 before.
- `POST /invocations` with body `{"image": "<base64 JPEG, optional data: prefix>"}` returns a Verdict.
  400 for a body that is not an image.

Env:

| Var | Default | Meaning |
|---|---|---|
| `DECIDER_MODEL` | `StrandsAgents/strands-decider-E2B-gemma4-v2-2611` | Hugging Face id |
| `DECIDER_DEVICE` | `cuda` if available, else `cpu` | |
| `DECIDER_MOCK` | unset | `1` returns a deterministic fake Verdict without loading a model |

The container downloads the weights from Hugging Face at startup.

## Front door (`frontdoor/`)

Lambda function URL (payload format 2.0). Every request except `OPTIONS` needs header
`x-demo-key: <DEMO_KEY>`, else 401. CORS is set on the function URL, not in code.

| Route | Does | Returns |
|---|---|---|
| `POST /score` | Body `{"image": ...}` passed to the decider | 200 Verdict. 503 `{"state": "cold"}` or `{"state": "warming"}` when the inference component has no copy |
| `POST /warm` | Sets the inference component's desired copy count to 1 | 202 `{"state": "warming"}` |
| `POST /sleep` | Sets the desired copy count to 0 | 202 `{"state": "cold"}` |
| `GET /status` | Reads the inference component | 200 `{"state": "cold" \| "warming" \| "live"}` |

`state` is derived from the inference component: current copies > 0 means `live`, desired > current means
`warming`, else `cold`.

Env: `DEMO_KEY`, `BACKEND` (`sagemaker` or `http`), `ENDPOINT_NAME`, `INFERENCE_COMPONENT` (sagemaker),
`DECIDER_URL` (http, for local runs). With `BACKEND=http`, `/warm` and `/sleep` are no-ops and `/status`
is `live` when `DECIDER_URL/ping` answers 200.

## Stylist (`stylist/`)

Cloud Run service, port from `$PORT` (default 8080).

- `POST /style` with body `{"verdict": <Verdict>}` returns `{"advice": "<2 to 4 short sentences>"}`.
- The agent sees the verdict's score, level, and facts only. Never an image.
- `GET /healthz` returns 200.

Env: `GOOGLE_API_KEY`, `GOOGLE_GENAI_USE_ENTERPRISE=0`, `STYLIST_MODEL` (default `gemini-flash-latest`),
`ALLOWED_ORIGINS` (comma list), `STYLIST_MOCK=1` for a canned answer.

## Web (`web/`)

Static files. `web/config.js` sets `window.OUTFIT_CONFIG = {frontdoorUrl, stylistUrl, demoKey}`.
`make up` writes it from Terraform outputs and it is gitignored. Locally, `frontdoor/local.py` serves `/config.js` from its own env.

The page is a state machine: `off -> starting -> cold -> warming -> live`, plus `paused` and `error`.
It enters `paused` when the tab is hidden or after 5 minutes of `live`, and `off` (camera released) on Stop.
In `live` it sends one frame at a time to `POST /score`. In `cold` it shows a "Warm up" button
that calls `POST /warm`, then polls `GET /status` every 5 s. "Style me" posts the last Verdict to the
stylist and shows the advice.

## Ports for local runs

decider 8080, front door 9000 (also serves `web/`), stylist 8081.
