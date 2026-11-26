"""SageMaker-style decider: GET /ping, POST /invocations -> Verdict."""

from __future__ import annotations

import base64
import binascii
import hashlib
import io
import logging
import os
import threading
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from PIL import Image, UnidentifiedImageError
from starlette.concurrency import run_in_threadpool

from decider.questions import QUESTIONS, to_verdict

DEFAULT_MODEL = "StrandsAgents/strands-decider-E2B-gemma4-v2-2611"
MAX_SIDE = 512
log = logging.getLogger("decider")


class BadImage(ValueError):
    pass


def decode_image(value: object) -> str:
    """Base64 JPEG of the image, at most MAX_SIDE px, from a base64 string with an optional data: prefix."""
    if not isinstance(value, str) or not value:
        raise BadImage("image must be a base64 string")
    b64 = value.split(",", 1)[1] if value.startswith("data:") else value
    try:
        image = Image.open(io.BytesIO(base64.b64decode(b64, validate=True))).convert("RGB")
    except (binascii.Error, UnidentifiedImageError, OSError) as e:
        raise BadImage(f"not an image: {e}") from e
    image.thumbnail((MAX_SIDE, MAX_SIDE))
    buf = io.BytesIO()
    image.save(buf, "JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode()


class MockEngine:
    model = "mock"

    def answer(self, image_b64: str) -> dict:
        h = hashlib.sha256(image_b64.encode()).digest()
        weights = [1 + b for b in h[:5]]
        total = sum(weights)
        probs = {str(i): w / total for i, w in enumerate(weights)}
        formality = ["athleisure", "casual", "smart_casual", "formal", "party"]
        palette = ["neutral", "monochrome", "earthy", "pastel", "bold"]
        return {
            "outfit": {"score": sum(i * p for i, p in enumerate(probs.values())), "probabilities": probs},
            "person": {"noul": 0.9 + h[5] / 2550},
            "formality": {"choice": formality[h[6] % 5]},
            "palette": {"choice": palette[h[7] % 5]},
            "shoes": {"noul": h[8] / 255},
        }


class DeciderEngine:
    def __init__(self, model_id: str, device: str):
        from strands_decider.decision import load_decision_engine

        self.model = model_id
        self._engine = load_decision_engine(model_id, device=device, dtype="bfloat16")

    def answer(self, image_b64: str) -> dict:
        from strands_decider.core import Request as DeciderRequest

        req = DeciderRequest.model_validate(
            {"state": "A webcam photo.", "images": [image_b64], "questions": QUESTIONS}
        )
        return self._engine.evaluate(req).model_dump()["answers"]


def default_device() -> str:
    import torch

    return "cuda" if torch.cuda.is_available() else "cpu"


def build_app(load_engine) -> FastAPI:
    """`load_engine()` returns an object with `.model` and `.answer(image_b64) -> answers`."""
    slot: dict = {"engine": None, "error": None}
    lock = threading.Lock()

    def load():
        try:
            slot["engine"] = load_engine()
            log.warning("decider ready: %s", slot["engine"].model)
        except Exception as e:
            log.exception("decider failed to load")
            slot["error"] = repr(e)

    @asynccontextmanager
    async def lifespan(_app):
        threading.Thread(target=load, daemon=True).start()
        yield

    app = FastAPI(lifespan=lifespan)

    @app.get("/ping")
    def ping():
        if slot["engine"] is None:
            return JSONResponse({"status": "loading", "error": slot["error"]}, status_code=503)
        return {"status": "ok", "model": slot["engine"].model}

    @app.post("/invocations")
    async def invocations(request: Request):
        engine = slot["engine"]
        if engine is None:
            return JSONResponse({"error": "model not loaded"}, status_code=503)
        try:
            body = await request.json()
            image = decode_image(body.get("image") if isinstance(body, dict) else None)
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        return await run_in_threadpool(score, engine, image, lock)

    return app


def score(engine, image_b64: str, lock: threading.Lock) -> dict:
    with lock:
        t = time.perf_counter()
        answers = engine.answer(image_b64)
        ms = (time.perf_counter() - t) * 1000
    return to_verdict(answers, ms, engine.model)


def engine_from_env():
    if os.environ.get("DECIDER_MOCK") == "1":
        return MockEngine()
    model_id = os.environ.get("DECIDER_MODEL", DEFAULT_MODEL)
    return DeciderEngine(model_id, os.environ.get("DECIDER_DEVICE") or default_device())


app = build_app(engine_from_env)
