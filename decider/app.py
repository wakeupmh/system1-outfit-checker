"""SageMaker-style decider: GET /ping, POST /invocations -> Verdict for one image, Choice for an occasion and
2-3 looks, Facts for 1-3 photos."""

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
from dataclasses import dataclass

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from PIL import Image, UnidentifiedImageError
from starlette.concurrency import run_in_threadpool

from decider.questions import (
    FACT_QUESTIONS,
    FRAME_STATE,
    QUESTIONS,
    look_questions,
    look_state,
    to_choice,
    to_facts,
    to_verdict,
)

DEFAULT_MODEL = "StrandsAgents/strands-decider-E2B-gemma4-v2-2611"
MAX_SIDE = 512
MAX_OCCASION = 120
MIN_LOOKS, MAX_LOOKS = 2, 3
MIN_FACTS = 1
log = logging.getLogger("decider")


class BadRequest(ValueError):
    pass


class BadImage(BadRequest):
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


@dataclass(frozen=True)
class ScoreRequest:
    image: str


@dataclass(frozen=True)
class ChooseRequest:
    occasion: str
    images: tuple[str, ...]


@dataclass(frozen=True)
class FactsRequest:
    images: tuple[str, ...]


def parse_invocation(body: object) -> ScoreRequest | ChooseRequest | FactsRequest:
    """`{"image"}` scores one frame, `{"occasion", "images"}` chooses between 2 or 3 looks, and `{"images"}`
    reads the facts of 1 to 3 photos."""
    if isinstance(body, dict) and "image" in body:
        return ScoreRequest(decode_image(body["image"]))
    if isinstance(body, dict) and "images" in body:
        images = body["images"]
        if not isinstance(images, list) or not MIN_FACTS <= len(images) <= MAX_LOOKS:
            raise BadRequest(f"images must be a list of {MIN_FACTS} to {MAX_LOOKS} images")
        decoded = tuple(decode_image(i) for i in images)
        if "occasion" not in body:
            return FactsRequest(decoded)
        occasion = body["occasion"]
        if not isinstance(occasion, str) or not 1 <= len(occasion.strip()) <= MAX_OCCASION:
            raise BadRequest(f"occasion must be 1 to {MAX_OCCASION} characters")
        if len(images) < MIN_LOOKS:
            raise BadRequest(f"a choice needs {MIN_LOOKS} to {MAX_LOOKS} images")
        return ChooseRequest(occasion.strip(), decoded)
    raise BadRequest('body must be {"image": ...}, {"occasion": ..., "images": [...]} or {"images": [...]}')


def _mock_score(h: bytes) -> dict:
    weights = [1 + b for b in h[:5]]
    total = sum(weights)
    probs = {str(i): w / total for i, w in enumerate(weights)}
    return {"score": sum(i * p for i, p in enumerate(probs.values())), "probabilities": probs}


def _digest(text: str) -> bytes:
    return hashlib.sha256(text.encode()).digest()


class MockEngine:
    model = "mock"
    device = "none"

    def answer(self, image_b64: str) -> dict:
        h = _digest(image_b64)
        formality = ["athleisure", "casual", "smart_casual", "formal", "party"]
        palette = ["neutral", "monochrome", "earthy", "pastel", "bold"]
        return {
            "outfit": _mock_score(h),
            "person": {"noul": 0.9 + h[5] / 2550},
            "formality": {"choice": formality[h[6] % 5]},
            "palette": {"choice": palette[h[7] % 5]},
            "shoes": {"noul": h[8] / 255},
        }

    def answer_looks(self, occasion: str, images: tuple[str, ...]) -> list[dict]:
        looks = []
        for image in images:
            h = _digest(image)
            looks.append({"fit": _mock_score(_digest(f"{occasion}\n{image}")), "person": {"noul": 0.9 + h[5] / 2550}})
        return looks

    def answer_facts(self, images: tuple[str, ...]) -> list[dict]:
        looks = []
        for image in images:
            answers = self.answer(image)
            del answers["outfit"]
            looks.append(answers)
        return looks


class DeciderEngine:
    def __init__(self, model_id: str, device: str):
        from strands_decider.decision import load_decision_engine

        self.model = model_id
        self.device = device
        self.engine = load_decision_engine(model_id, device=device, dtype="bfloat16")

    def _evaluate(self, state: str, image_b64: str, questions: dict) -> dict:
        from strands_decider.core import Request as DeciderRequest

        req = DeciderRequest.model_validate({"state": state, "images": [image_b64], "questions": questions})
        return self.engine.evaluate(req).model_dump()["answers"]

    def answer(self, image_b64: str) -> dict:
        return self._evaluate(FRAME_STATE, image_b64, QUESTIONS)

    def answer_looks(self, occasion: str, images: tuple[str, ...]) -> list[dict]:
        """strands-decider 0.4.0 batches the questions of one request, not requests, so each look is one call."""
        questions = look_questions(occasion)
        return [self._evaluate(look_state(occasion), image, questions) for image in images]

    def answer_facts(self, images: tuple[str, ...]) -> list[dict]:
        """One call per photo, as for the looks."""
        return [self._evaluate(FRAME_STATE, image, FACT_QUESTIONS) for image in images]


def build_app(load_engine) -> FastAPI:
    """`load_engine()` returns an object with `.model`, `.answer(image_b64) -> answers`,
    `.answer_looks(occasion, images) -> [answers]` and `.answer_facts(images) -> [answers]`."""
    slot: dict = {"engine": None, "error": None}
    lock = threading.Lock()

    def load():
        try:
            slot["engine"] = load_engine()
            log.warning("decider ready: %s on %s", slot["engine"].model, slot["engine"].device)
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
            parsed = parse_invocation(await request.json())
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        run = {ScoreRequest: score, ChooseRequest: choose, FactsRequest: facts}[type(parsed)]
        return await run_in_threadpool(run, engine, parsed, lock)

    return app


def score(engine, req: ScoreRequest, lock: threading.Lock) -> dict:
    with lock:
        t = time.perf_counter()
        answers = engine.answer(req.image)
        ms = (time.perf_counter() - t) * 1000
    return to_verdict(answers, ms, engine.model)


def choose(engine, req: ChooseRequest, lock: threading.Lock) -> dict:
    with lock:
        t = time.perf_counter()
        looks = engine.answer_looks(req.occasion, req.images)
        ms = (time.perf_counter() - t) * 1000
    return to_choice(req.occasion, looks, ms, engine.model)


def facts(engine, req: FactsRequest, lock: threading.Lock) -> dict:
    with lock:
        t = time.perf_counter()
        answers = engine.answer_facts(req.images)
        ms = (time.perf_counter() - t) * 1000
    return to_facts(answers, ms, engine.model)


def engine_from_env():
    if os.environ.get("DECIDER_MOCK") == "1":
        return MockEngine()
    model_id = os.environ.get("DECIDER_MODEL", DEFAULT_MODEL)
    from strands_decider.cli import resolve_device

    return DeciderEngine(model_id, resolve_device(os.environ.get("DECIDER_DEVICE") or None))


app = build_app(engine_from_env)
