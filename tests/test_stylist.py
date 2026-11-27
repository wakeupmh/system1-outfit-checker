import pytest
from fastapi.testclient import TestClient
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from stylist.app import CANNED_ADVICE, CANNED_CHOICE_ADVICE, CannedLlm, Stylist, build_app, stylist_from_env

VERDICT = {"score": 72, "level": 2.44, "probs": [0.01, 0.08, 0.4, 0.38, 0.13],
           "facts": {"person": 0.97, "formality": "smart_casual", "palette": "neutral", "shoes": 0.91},
           "ms": 143.2, "model": "m"}
ORIGIN = "http://localhost:9000"


def client(model=None):
    return TestClient(build_app(Stylist(model or CannedLlm(model="canned")), [ORIGIN]))


def test_healthz():
    assert client().get("/healthz").status_code == 200


def test_style_returns_the_agents_advice_with_cors_for_allowed_origins():
    r = client().post("/style", json={"verdict": VERDICT}, headers={"origin": ORIGIN})
    assert r.status_code == 200
    assert r.json() == {"advice": CANNED_ADVICE}
    assert r.headers["access-control-allow-origin"] == ORIGIN


def test_other_origins_get_no_cors_header():
    r = client().post("/style", json={"verdict": VERDICT}, headers={"origin": "https://evil.example"})
    assert "access-control-allow-origin" not in r.headers


def test_style_rejects_a_missing_verdict():
    assert client().post("/style", json={}).status_code == 422


class RecordingLlm(CannedLlm):
    seen: list = []

    async def generate_content_async(self, llm_request, stream=False):
        self.seen.extend(llm_request.contents)
        yield LlmResponse(content=types.Content(role="model", parts=[types.Part(text="ok")]))


def test_the_agent_sees_only_the_verdict_facts_as_text():
    llm = RecordingLlm(model="rec")
    llm.seen = []
    verdict = {**VERDICT, "image": "data:image/jpeg;base64,AAAA"}
    assert client(llm).post("/style", json={"verdict": verdict}).json() == {"advice": "ok"}
    parts = [p for c in llm.seen for p in c.parts]
    assert parts and all(p.text and not p.inline_data for p in parts)
    text = " ".join(p.text for p in parts)
    for fact in ("72/100", "2.44", "97%", "smart_casual", "neutral", "91%"):
        assert fact in text
    assert "base64" not in text and "143.2" not in text


# What /choose returns: fits only. The page adds each look's facts from /facts before it asks for advice.
CHOICE = {"occasion": "jantar romântico", "pick": 1, "confident": True, "margin": 0.88,
          "looks": [{"fit": 18, "level": 1.09, "probs": [0.3, 0.4, 0.2, 0.08, 0.02]},
                    {"fit": 73, "level": 1.97, "probs": [0.05, 0.2, 0.4, 0.3, 0.05]}],
          "ms": 2512.4, "model": "m"}
FACTS = [{"person": 0.95, "formality": "athleisure", "palette": "neutral", "shoes": 0.13},
         {"person": 0.79, "formality": "casual", "palette": "pastel", "shoes": 0.12}]


def with_facts(choice=CHOICE):
    return {**choice, "looks": [dict(look, facts=facts) for look, facts in zip(choice["looks"], FACTS)]}


def test_mock_mode_answers_a_choice_in_portuguese_and_a_verdict_as_before(monkeypatch):
    monkeypatch.setenv("STYLIST_MOCK", "1")
    mock = TestClient(build_app(stylist_from_env(), [ORIGIN]))
    choice = mock.post("/style", json={"choice": CHOICE})
    verdict = mock.post("/style", json={"verdict": VERDICT})
    assert choice.status_code == verdict.status_code == 200
    advice = choice.json()["advice"]
    assert advice == CANNED_CHOICE_ADVICE
    assert 2 <= advice.count(".") <= 4 and "look" in advice and " é " in advice
    assert verdict.json() == {"advice": CANNED_ADVICE}


def test_the_agent_sees_only_the_choice_facts_as_text():
    llm = RecordingLlm(model="rec")
    llm.seen = []
    choice = {**with_facts(), "images": ["data:image/jpeg;base64,AAAA"]}
    assert client(llm).post("/style", json={"choice": choice}).json() == {"advice": "ok"}
    parts = [p for c in llm.seen for p in c.parts]
    assert parts and all(p.text and not p.inline_data for p in parts)
    text = " ".join(p.text for p in parts)
    for fact in ("jantar romântico", "look 2 de 2", "0.88", "18/100", "73/100", "athleisure", "pastel", "95%", "12%"):
        assert fact in text
    assert "base64" not in text and "2512" not in text


def test_a_choice_without_facts_is_explained_from_the_fits_and_the_margin_alone():
    # /facts can fail on stage; the pick is already on screen and still deserves an explanation.
    llm = RecordingLlm(model="rec")
    llm.seen = []
    assert client(llm).post("/style", json={"choice": CHOICE}).json() == {"advice": "ok"}
    text = " ".join(p.text for c in llm.seen for p in c.parts)
    for fact in ("jantar romântico", "look 2 de 2", "0.88", "18/100", "73/100"):
        assert fact in text
    assert "Traje" not in text and "Paleta" not in text and "Pessoa visível" not in text


@pytest.mark.parametrize(
    "body",
    [
        {"verdict": VERDICT, "choice": CHOICE},
        {"choice": {**CHOICE, "pick": 2}},
        {"choice": {**CHOICE, "pick": -1}},
        {"choice": {**CHOICE, "looks": CHOICE["looks"][:1], "pick": 0}},
        {"choice": {**CHOICE, "occasion": ""}},
    ],
)
def test_style_rejects_malformed_choices(body):
    assert client().post("/style", json=body).status_code == 422
