"""Real-time outfit checker backed by a Liquid AI d1 decision model.

The browser streams webcam frames over a WebSocket; each frame is answered
with one forward pass of d1 (a "score" question with ordered levels), and the
page turns the level probabilities into a 0-100 meter.

    python server.py                       # LiquidAI/d1-2B on cuda/mps/cpu
    python server.py --model LiquidAI/d1-3B --compile
    python server.py --mock                # no model: fake scores, for UI work
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import io
import math
import random
import time
from pathlib import Path

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image
from pydantic import BaseModel

STATIC = Path(__file__).parent / "static"
MAX_SIDE = 512

# Ordered lowest first; the meter is the expected level mapped onto 0-100.
LEVELS = [
    "Sleepwear, gym or lounge clothes, or no outfit clearly visible.",
    "Plain everyday basics thrown on without any styling.",
    "A neat, wearable outfit whose pieces go together but play it safe.",
    "A put-together look: colours, shapes and accessories clearly chosen to match.",
    "A striking, confident look with a clear personal style where every piece works.",
]

QUESTION = {
    "type": "score",
    "instructions": (
        "Rate how well styled the visible outfit is as a look for going out today. "
        "Consider the clothes, shoes and accessories as a whole: colour harmony, fit "
        "of the pieces to each other, and whether there is a clear styling idea. "
        "Judge only the clothing. Ignore the person's body, face, looks, pose, "
        "the room and the photo quality. If no outfit is visible, pick the lowest level."
    ),
    "criteria": LEVELS,
}


class Scorer:
    def __init__(self, model_id: str, compile_: bool, mock: bool):
        self.mock = mock
        self.lock = asyncio.Lock()
        self.model_id = "mock" if mock else model_id
        if mock:
            self._t0 = time.time()
            return
        import torch
        from transformers import AutoModel

        if torch.cuda.is_available():
            device, dtype = "cuda", torch.bfloat16
        elif torch.backends.mps.is_available():
            device, dtype = "mps", torch.bfloat16
        else:
            device, dtype = "cpu", torch.float32
        print(f"loading {model_id} on {device} ...", flush=True)
        self.model = AutoModel.from_pretrained(
            model_id, trust_remote_code=True, dtype=dtype
        ).to(device)
        if compile_ and device == "cuda":
            self.model.compile(mode="reduce-overhead")
        # Warm up the image shape we serve so the first real frame is fast.
        self._score(Image.new("RGB", (384, MAX_SIDE), "gray"))
        print("ready", flush=True)

    def _score(self, image: Image.Image) -> list[float]:
        if self.mock:
            t = time.time() - self._t0
            base = [0.05, 0.1, 0.2, 0.3, 0.35]
            wobble = [max(1e-3, b + 0.15 * math.sin(t / 2 + i) + random.uniform(-0.03, 0.03))
                      for i, b in enumerate(base)]
            s = sum(wobble)
            return [w / s for w in wobble]
        out = self.model.system_one(None, {"outfit": QUESTION}, [image])
        return [float(p) for p in out["answers"]["outfit"]["probabilities"]]

    async def score(self, data_url: str) -> dict:
        image = decode(data_url)
        async with self.lock:
            t = time.perf_counter()
            probs = await asyncio.to_thread(self._score, image)
            ms = (time.perf_counter() - t) * 1000
        n = len(probs)
        expected = sum(i * p for i, p in enumerate(probs)) / (n - 1)
        return {"score": round(100 * expected, 1), "probs": probs, "ms": round(ms, 1)}


def decode(data_url: str) -> Image.Image:
    b64 = data_url.split(",", 1)[1] if data_url.startswith("data:") else data_url
    image = Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGB")
    image.thumbnail((MAX_SIDE, MAX_SIDE))
    return image


class Frame(BaseModel):
    image: str


def build_app(scorer: Scorer) -> FastAPI:
    app = FastAPI()

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/info")
    def info():
        return {"model": scorer.model_id, "levels": LEVELS}

    @app.post("/score")
    async def score(frame: Frame):
        return await scorer.score(frame.image)

    @app.websocket("/ws")
    async def ws(sock: WebSocket):
        await sock.accept()
        try:
            while True:
                msg = await sock.receive_text()
                try:
                    await sock.send_json(await scorer.score(msg))
                except Exception as e:  # bad frame: report and keep the stream alive
                    await sock.send_json({"error": str(e)})
        except WebSocketDisconnect:
            pass

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="LiquidAI/d1-2B")
    ap.add_argument("--compile", action="store_true", help="CUDA graphs (NVIDIA only)")
    ap.add_argument("--mock", action="store_true", help="fake scores, no model download")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=7860)
    args = ap.parse_args()
    app = build_app(Scorer(args.model, args.compile, args.mock))
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
