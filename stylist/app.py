"""Stylist: an ADK agent that turns a Verdict's or a Choice's facts into short outfit advice. Text only."""

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
from pydantic import BaseModel, Field, model_validator

INSTRUCTION = (
    "You are a friendly personal stylist. You get facts a vision model measured about someone's "
    "outfit from a webcam frame: a 0-100 style score, the raw level on a 0-4 scale, the probability "
    "that a person is visible, the dress code, the colour palette, and the probability that shoes "
    "are visible. Reply with 2 to 4 short sentences of concrete, kind advice about the clothes only. "
    "Never comment on the person's body, face or looks. If no person is likely visible, ask them to "
    "step back so the outfit is in view."
)

CHOICE_INSTRUCTION = (
    "Você é um personal stylist simpático. Um modelo de visão avaliou 2 ou 3 looks, um de cada vez, "
    "para uma ocasião e escolheu o que mais combina. Você recebe só os fatos medidos: a ocasião, a "
    "adequação de 0 a 100 de cada look, o traje, a paleta de cores, a chance de haver uma pessoa e "
    "sapatos visíveis, qual look venceu e se a decisão foi confiante ou quase um empate. Responda em "
    "português do Brasil com 2 a 4 frases curtas explicando por que o look escolhido combina com a "
    "ocasião, usando apenas esses fatos. Se foi quase um empate, diga isso e dê um critério para "
    "desempatar. Fale só das roupas, nunca do corpo, rosto ou aparência da pessoa. Se o traje e a paleta "
    "de um look não vierem na mensagem, explique só pela adequação e pela margem, sem inventar esses detalhes."
)

CANNED_ADVICE = (
    "Nice base to build on. Add one accent piece, like a belt or a bold bag, to give the look a focus. "
    "Shoes that echo a colour from your top will tie it together."
)

CANNED_CHOICE_ADVICE = (
    "O look escolhido é o que mais conversa com a ocasião: o traje e a paleta estão no tom certo. "
    "Os outros funcionam, mas ficam um pouco fora do clima do programa. "
    "Um acessório simples fecha o visual."
)

MAX_OCCASION = 120


class Facts(BaseModel):
    person: float
    formality: str
    palette: str
    shoes: float


class Verdict(BaseModel):
    score: int
    level: float
    facts: Facts


class Look(BaseModel):
    fit: int
    level: float
    # /choose asks only the fit; the page adds the facts from /facts before it asks for advice, when it can.
    facts: Facts | None = None


class Choice(BaseModel):
    occasion: str = Field(min_length=1, max_length=MAX_OCCASION)
    pick: int
    confident: bool
    margin: float
    looks: list[Look] = Field(min_length=2, max_length=3)

    @model_validator(mode="after")
    def _pick_is_a_look(self):
        if not 0 <= self.pick < len(self.looks):
            raise ValueError("pick must index looks")
        return self


class StyleRequest(BaseModel):
    verdict: Verdict | None = None
    choice: Choice | None = None

    @model_validator(mode="after")
    def _exactly_one(self):
        if (self.verdict is None) == (self.choice is None):
            raise ValueError("send exactly one of verdict or choice")
        return self


def describe(verdict: Verdict) -> str:
    f = verdict.facts
    return (
        f"Style score: {verdict.score}/100 (level {verdict.level:.2f} of 4).\n"
        f"Person visible: {f.person:.0%}. Dress code: {f.formality}. Palette: {f.palette}. "
        f"Shoes visible: {f.shoes:.0%}."
    )


def describe_choice(choice: Choice) -> str:
    verdict = "confiante" if choice.confident else "quase um empate"
    lines = [
        f"Ocasião: {choice.occasion}",
        f"Escolhido: look {choice.pick + 1} de {len(choice.looks)} "
        f"(margem {choice.margin:.2f} sobre o segundo; decisão {verdict}).",
    ]
    for i, look in enumerate(choice.looks):
        line = f"Look {i + 1}: adequação {look.fit}/100."
        if look.facts:
            f = look.facts
            line += (f" Traje: {f.formality}. Paleta: {f.palette}. "
                     f"Pessoa visível: {f.person:.0%}. Sapatos visíveis: {f.shoes:.0%}.")
        lines.append(line)
    return "\n".join(lines)


class CannedLlm(BaseLlm):
    """Answers every turn with `text`, so the agent runs without a Gemini key."""

    text: str = CANNED_ADVICE

    async def generate_content_async(self, llm_request, stream: bool = False) -> AsyncGenerator[LlmResponse, None]:
        yield LlmResponse(content=types.Content(role="model", parts=[types.Part(text=self.text)]))


def _runner(name: str, model, instruction: str) -> InMemoryRunner:
    return InMemoryRunner(agent=Agent(name=name, model=model, instruction=instruction), app_name=name)


async def _ask(runner: InMemoryRunner, text: str) -> str:
    session = await runner.session_service.create_session(app_name=runner.app_name, user_id="web")
    message = types.Content(role="user", parts=[types.Part(text=text)])
    reply = ""
    async for event in runner.run_async(user_id="web", session_id=session.id, new_message=message):
        if event.is_final_response() and event.content and event.content.parts:
            reply = "".join(p.text or "" for p in event.content.parts)
    return reply.strip()


class Stylist:
    def __init__(self, model, choice_model=None):
        self.verdict_runner = _runner("stylist", model, INSTRUCTION)
        self.choice_runner = _runner("chooser", choice_model or model, CHOICE_INSTRUCTION)

    async def advise(self, req: StyleRequest) -> str:
        if req.choice is not None:
            return await _ask(self.choice_runner, describe_choice(req.choice))
        return await _ask(self.verdict_runner, describe(req.verdict))


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
        return {"advice": await stylist.advise(req)}

    return app


def stylist_from_env() -> Stylist:
    if os.environ.get("STYLIST_MOCK") == "1":
        return Stylist(CannedLlm(model="canned"), CannedLlm(model="canned", text=CANNED_CHOICE_ADVICE))
    os.environ.setdefault("GOOGLE_GENAI_USE_ENTERPRISE", "0")
    return Stylist(os.environ.get("STYLIST_MODEL", "gemini-flash-latest"))


app = build_app(
    stylist_from_env(),
    [o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip()],
)
