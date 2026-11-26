from fastapi.testclient import TestClient
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from stylist.app import CANNED_ADVICE, CannedLlm, Stylist, build_app

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
