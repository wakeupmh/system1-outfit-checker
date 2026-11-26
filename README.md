# system1-outfit-checker

A real-time webcam "fit check": a photo-booth style page streams camera frames to a
local server, where a Liquid AI **d1 decision model** rates the outfit in a single forward
pass (no text generation). The page shows the result as a live 0–100 % meter.

Inspired by the Fit Check demo in Liquid AI's
[System One Arcade](https://huggingface.co/spaces/LiquidAI/system-one-arcade)
([blog](https://www.liquid.ai/blog/d1-open)). The code, prompt and art here are original.

## How it works

1. `static/app.js` grabs a webcam frame, scales it to ≤512 px, and sends it as JPEG over `/ws`.
   Only one frame is in flight at a time, so the frame rate matches how fast the model runs.
2. `server.py` asks d1 one `score` question with 5 ordered levels (from lounge/gym wear up to
   a striking, deliberate look), using `model.system_one(None, {"outfit": QUESTION}, [image])`.
3. The level probabilities become an expected level, mapped to 0–100. The page smooths it
   between frames and picks a caption (いいかも ♡, さいこう！ ✦ …).

The prompt tells the model to judge only the clothes, not the person's body, face or room.
Edit `QUESTION` / `LEVELS` in `server.py` to change what counts as a good outfit.

## Run

```bash
pip install -r requirements.txt
python server.py                          # LiquidAI/d1-2B (default), ~4 GB download
python server.py --model LiquidAI/d1-3B   # the other open d1 vision model
python server.py --compile                # NVIDIA only: CUDA graphs, faster per-frame
python server.py --mock                   # no model: fake scores, for working on the UI
```

Open http://127.0.0.1:7860 and press **Start camera**. Browsers only allow the camera on
`localhost` or HTTPS, so put a TLS proxy in front if you serve it to other devices.

Runs on CUDA, Apple Silicon (`mps`) or CPU (slow). Liquid reports d1 at roughly 17–60 ms for
a 384 px image on an RTX 4090 / M5 Pro.

## API

- `GET /info` – model id and level descriptions
- `POST /score` – `{"image": "<data URL>"}` → `{"score": 0-100, "probs": [...], "ms": ...}`
- `WS /ws` – send data URLs, receive the same JSON per frame

The d1 weights are under the LFM Open License v1.0 – check its terms for your use.
