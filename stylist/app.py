"""Stylist: an ADK agent that turns a Verdict's facts into short outfit advice. Text only."""

from __future__ import annotations

import os
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from google.adk.agents import Agent
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.adk.runners import InMemoryRunner
from google.genai import types
from pydantic import BaseModel

INSTRUCTION = (
    "You are a friendly personal stylist. You get facts a vision model measured about someone's "
    "outfit from a webcam frame: a 0-100 style score, the raw level on a 0-4 scale, the probability "
    "that a person is visible, the dress code, the colour palette, and the probability that shoes "
    "are visible. Reply with 2 to 4 short sentences of concrete, kind advice about the clothes only. "
    "Never comment on the person's body, face or looks. If no person is likely visible, ask them to "
    "step back so the outfit is in view."
)

CANNED_ADVICE = (
    "Nice base to build on. Add one accent piece, like a belt or a bold bag, to give the look a focus. "
    "Shoes that echo a colour from your top will tie it together."
)


class Facts(BaseModel):
    person: float
    formality: str
    palette: str
    shoes: float


class Verdict(BaseModel):
    score: int
    level: float
    facts: Facts


class StyleRequest(BaseModel):
    verdict: Verdict


def describe(verdict: Verdict) -> str:
    f = verdict.facts
    return (
        f"Style score: {verdict.score}/100 (level {verdict.level:.2f} of 4).\n"
        f"Person visible: {f.person:.0%}. Dress code: {f.formality}. Palette: {f.palette}. "
        f"Shoes visible: {f.shoes:.0%}."
    )


class CannedLlm(BaseLlm):
    """Answers every turn with CANNED_ADVICE, so the agent runs without a Gemini key."""

    async def generate_content_async(self, llm_request, stream: bool = False) -> AsyncGenerator[LlmResponse, None]:
        yield LlmResponse(content=types.Content(role="model", parts=[types.Part(text=CANNED_ADVICE)]))


class Stylist:
    def __init__(self, model):
        agent = Agent(name="stylist", model=model, instruction=INSTRUCTION)
        self.runner = InMemoryRunner(agent=agent, app_name="stylist")

    async def advise(self, text: str) -> str:
        session = await self.runner.session_service.create_session(app_name="stylist", user_id="web")
        message = types.Content(role="user", parts=[types.Part(text=text)])
        reply = ""
        async for event in self.runner.run_async(user_id="web", session_id=session.id, new_message=message):
            if event.is_final_response() and event.content and event.content.parts:
                reply = "".join(p.text or "" for p in event.content.parts)
        return reply.strip()


def build_app(stylist: Stylist, allowed_origins: list[str]) -> FastAPI:
    app = FastAPI()
    app.add_middleware(
        CORSMiddleware, allow_origins=allowed_origins, allow_methods=["GET", "POST"], allow_headers=["content-type"]
    )

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    @app.post("/style")
    async def style(req: StyleRequest):
        return {"advice": await stylist.advise(describe(req.verdict))}

    return app


def stylist_from_env() -> Stylist:
    if os.environ.get("STYLIST_MOCK") == "1":
        return Stylist(CannedLlm(model="canned"))
    os.environ.setdefault("GOOGLE_GENAI_USE_ENTERPRISE", "0")
    return Stylist(os.environ.get("STYLIST_MODEL", "gemini-flash-latest"))


app = build_app(
    stylist_from_env(),
    [o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip()],
)
