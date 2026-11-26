import base64
import io
import threading
import time

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from decider.app import (
    ChooseRequest,
    DeciderEngine,
    FactsRequest,
    MockEngine,
    build_app,
    choose as run_choose,
    facts as run_facts,
)


def jpeg(color="red", size=(640, 480)) -> str:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "JPEG")
    return base64.b64encode(buf.getvalue()).decode()


def wait_ready(client, timeout=5):
    deadline = time.time() + timeout
    while client.get("/ping").status_code != 200:
        assert time.time() < deadline, "decider never became ready"
        time.sleep(0.01)


def test_ping_is_503_until_the_model_loads_then_200():
    release = threading.Event()

    def slow_load():
        release.wait(5)
        return MockEngine()

    with TestClient(build_app(slow_load)) as client:
        assert client.get("/ping").status_code == 503
        assert client.post("/invocations", json={"image": jpeg()}).status_code == 503
        release.set()
        wait_ready(client)
        assert client.get("/ping").status_code == 200


def test_invocations_returns_a_deterministic_verdict_for_data_urls_and_plain_base64():
    with TestClient(build_app(MockEngine)) as client:
        wait_ready(client)
        a = client.post("/invocations", json={"image": "data:image/jpeg;base64," + jpeg("red")})
        b = client.post("/invocations", json={"image": jpeg("red")})
        c = client.post("/invocations", json={"image": jpeg("blue")})
    assert a.status_code == b.status_code == c.status_code == 200
    va, vb, vc = a.json(), b.json(), c.json()
    assert set(va) == {"score", "level", "probs", "facts", "ms", "model"}
    assert set(va["facts"]) == {"person", "formality", "palette", "shoes"}
    assert len(va["probs"]) == 5 and 0 <= va["score"] <= 100
    assert va["model"] == "mock"
    assert {k: v for k, v in va.items() if k != "ms"} == {k: v for k, v in vb.items() if k != "ms"}
    assert va["probs"] != vc["probs"]


def test_invocations_rejects_bodies_that_are_not_an_image():
    with TestClient(build_app(MockEngine)) as client:
        wait_ready(client)
        for body in ({"image": "aGVsbG8="}, {"image": "%%%"}, {"image": 3}, {}, [1]):
            assert client.post("/invocations", json=body).status_code == 400, body
        assert client.post("/invocations", content=b"not json").status_code == 400


def choose(client, occasion="a dinner date", colors=("red", "blue", "green")):
    return client.post("/invocations", json={"occasion": occasion, "images": [jpeg(c) for c in colors]})


def test_invocations_with_an_occasion_returns_a_deterministic_choice():
    with TestClient(build_app(MockEngine)) as client:
        wait_ready(client)
        a, b = choose(client), choose(client)
        run = choose(client, "a morning run")
        pair = choose(client, colors=("red", "blue"))
    assert a.status_code == b.status_code == run.status_code == pair.status_code == 200
    ca = a.json()
    assert set(ca) == {"occasion", "pick", "confident", "margin", "looks", "ms", "model"}
    assert ca["occasion"] == "a dinner date" and ca["model"] == "mock"
    assert len(ca["looks"]) == 3 and len(pair.json()["looks"]) == 2
    assert all(set(lk) == {"fit", "level", "probs"} for lk in ca["looks"])
    best = max(range(3), key=lambda i: ca["looks"][i]["level"])
    assert ca["pick"] == best
    assert {k: v for k, v in ca.items() if k != "ms"} == {k: v for k, v in b.json().items() if k != "ms"}
    assert [lk["level"] for lk in ca["looks"]] != [lk["level"] for lk in run.json()["looks"]]


def test_invocations_with_images_alone_returns_the_facts_of_each_photo_in_order():
    with TestClient(build_app(MockEngine)) as client:
        wait_ready(client)
        body = {"images": [jpeg("red"), jpeg("blue")]}
        a, b = client.post("/invocations", json=body), client.post("/invocations", json=body)
        one = client.post("/invocations", json={"images": [jpeg("red")]})
    assert a.status_code == b.status_code == one.status_code == 200
    read, first = a.json(), one.json()
    assert set(read) == {"facts", "ms", "model"} and read["model"] == "mock"
    assert len(read["facts"]) == 2 and len(first["facts"]) == 1
    assert all(set(f) == {"person", "formality", "palette", "shoes"} for f in read["facts"])
    assert {k: v for k, v in read.items() if k != "ms"} == {k: v for k, v in b.json().items() if k != "ms"}
    assert read["facts"][0] == first["facts"][0] and read["facts"][0] != read["facts"][1]


class RecordingEngine(DeciderEngine):
    """The real engine's request building, with no model: it records what it would be asked."""

    def __init__(self):
        self.model, self.device, self.calls = "rec", "none", []

    def _evaluate(self, state, image_b64, questions):
        self.calls.append((state, image_b64, tuple(questions)))
        if "fit" in questions:
            return {"fit": {"score": 1.0 + 0.5 * len(self.calls), "probabilities": {}}}
        return {
            "person": {"noul": 0.9}, "formality": {"choice": "casual"},
            "palette": {"choice": "neutral"}, "shoes": {"noul": 0.5},
        }


def test_a_look_is_asked_its_fit_alone_in_its_own_pass_and_the_facts_are_a_separate_call():
    engine = RecordingEngine()
    choice = run_choose(engine, ChooseRequest("a dinner date", ("A", "B", "C")), threading.Lock())
    assert [lk["level"] for lk in choice["looks"]] == [1.5, 2.0, 2.5] and choice["pick"] == 2
    assert engine.calls == [("The plan: a dinner date.", image, ("fit",)) for image in "ABC"]

    engine.calls.clear()
    run_facts(engine, FactsRequest(("A", "B")), threading.Lock())
    assert engine.calls == [
        ("A webcam photo.", image, ("person", "formality", "palette", "shoes")) for image in "AB"
    ]


def test_an_image_body_still_returns_a_verdict_next_to_choices():
    with TestClient(build_app(MockEngine)) as client:
        wait_ready(client)
        r = client.post("/invocations", json={"image": jpeg()})
    assert r.status_code == 200 and "score" in r.json() and "pick" not in r.json()


@pytest.mark.parametrize(
    "body",
    [
        {"occasion": "", "images": ["RED", "BLUE"]},
        {"occasion": "   ", "images": ["RED", "BLUE"]},
        {"occasion": "x" * 121, "images": ["RED", "BLUE"]},
        {"occasion": 3, "images": ["RED", "BLUE"]},
        {"occasion": "a party", "images": ["RED"]},
        {"occasion": "a party", "images": ["RED", "BLUE", "RED", "BLUE"]},
        {"occasion": "a party", "images": "RED"},
        {"occasion": "a party", "images": ["RED", "aGVsbG8="]},
        {"occasion": None, "images": ["RED", "BLUE"]},
        {"occasion": "a party"},
        {"images": []},
        {"images": ["RED", "BLUE", "GREEN", "YELLOW"]},
        {"images": "RED"},
        {"images": [3]},
        {"images": ["aGVsbG8="]},
    ],
)
def test_invocations_rejects_bad_choice_bodies(body):
    real = {"RED": jpeg("red"), "BLUE": jpeg("blue")}
    if isinstance(body.get("images"), list):
        body = {**body, "images": [real.get(i, i) for i in body["images"]]}
    with TestClient(build_app(MockEngine)) as client:
        wait_ready(client)
        assert client.post("/invocations", json=body).status_code == 400


def test_occasion_length_bounds_are_inclusive():
    with TestClient(build_app(MockEngine)) as client:
        wait_ready(client)
        assert choose(client, "x", ("red", "blue")).status_code == 200
        assert choose(client, "x" * 120, ("red", "blue")).status_code == 200


def test_a_failed_load_keeps_ping_at_503():
    def broken():
        raise RuntimeError("no weights")

    with TestClient(build_app(broken)) as client:
        time.sleep(0.05)
        r = client.get("/ping")
    assert r.status_code == 503 and "no weights" in r.json()["error"]
