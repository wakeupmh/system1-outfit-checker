import base64
import io
import threading
import time

from fastapi.testclient import TestClient
from PIL import Image

from decider.app import MockEngine, build_app


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


def test_a_failed_load_keeps_ping_at_503():
    def broken():
        raise RuntimeError("no weights")

    with TestClient(build_app(broken)) as client:
        time.sleep(0.05)
        r = client.get("/ping")
    assert r.status_code == 503 and "no weights" in r.json()["error"]
