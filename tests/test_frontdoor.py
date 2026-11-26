import io
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from botocore.exceptions import ClientError

from frontdoor import handler as fd
from frontdoor.handler import HttpBackend, SageMakerBackend, route

KEY = "secret"
ADMIN = "boss"
KEYS = {"demo": KEY, "admin": ADMIN}
AUTH = {"x-demo-key": KEY, "x-admin-key": ADMIN}
VERDICT = {"score": 72, "level": 2.44, "probs": [0.01, 0.08, 0.4, 0.38, 0.13],
           "facts": {"person": 0.97, "formality": "smart_casual", "palette": "neutral", "shoes": 0.91},
           "ms": 143.2, "model": "StrandsAgents/strands-decider-E2B-gemma4-v2-2611"}
CHOICE = {"occasion": "jantar romântico", "pick": 1, "confident": True, "margin": 0.88,
          "looks": [{"fit": 18, "level": 1.09, "probs": [0.3, 0.4, 0.2, 0.08, 0.02],
                     "facts": {"person": 0.95, "formality": "athleisure", "palette": "neutral", "shoes": 0.13}},
                    {"fit": 73, "level": 1.97, "probs": [0.05, 0.2, 0.4, 0.3, 0.05],
                     "facts": {"person": 0.79, "formality": "casual", "palette": "pastel", "shoes": 0.12}}],
          "ms": 5012.4, "model": "StrandsAgents/strands-decider-E2B-gemma4-v2-2611"}
CHOOSE_BODY = json.dumps({"occasion": "jantar romântico", "images": ["a", "b"]}).encode()
NO_CAPACITY = ClientError(
    {"Error": {"Code": "ValidationError", "Message": "Inference Component has no capacity to process this request. "
               "ApplicationAutoScaling may be in-progress (if configured) or try to increase the capacity by "
               "invoking UpdateInferenceComponentRuntimeConfig API."}},
    "InvokeEndpoint",
)


class FakeControl:
    def __init__(self, current=0, desired=0):
        self.current, self.desired, self.updates = current, desired, []

    def describe_inference_component(self, InferenceComponentName):
        assert InferenceComponentName == "ic"
        return {"RuntimeConfig": {"CurrentCopyCount": self.current, "DesiredCopyCount": self.desired}}

    def update_inference_component_runtime_config(self, InferenceComponentName, DesiredRuntimeConfig):
        assert InferenceComponentName == "ic"
        self.updates.append(DesiredRuntimeConfig["CopyCount"])
        self.desired = DesiredRuntimeConfig["CopyCount"]


class FakeRuntime:
    def __init__(self, result):
        self.result, self.calls = result, []

    def invoke_endpoint(self, **kw):
        self.calls.append(kw)
        if isinstance(self.result, Exception):
            raise self.result
        return {"Body": io.BytesIO(json.dumps(self.result).encode())}


def sagemaker(result=VERDICT, current=1, desired=1):
    return SageMakerBackend(FakeRuntime(result), FakeControl(current, desired), "ep", "ic")


def call(backend, method, path, body=b"", headers=AUTH):
    return route(method, path, headers, body, backend, KEYS)


@pytest.mark.parametrize("method,path", [("POST", "/score"), ("POST", "/choose"), ("GET", "/status")])
@pytest.mark.parametrize("headers", [{}, {"x-demo-key": "wrong"}, {"x-admin-key": ADMIN}])
def test_scoring_routes_need_the_demo_key(method, path, headers):
    backend = sagemaker()
    assert call(backend, method, path, b"{}", headers)[0] == 401
    assert backend.runtime.calls == []


@pytest.mark.parametrize("path", ["/warm", "/sleep"])
@pytest.mark.parametrize("headers", [{}, {"x-demo-key": KEY}, {"x-demo-key": KEY, "x-admin-key": "wrong"}])
def test_the_public_demo_key_cannot_start_or_stop_the_gpu(path, headers):
    backend = sagemaker(current=0, desired=0)
    assert call(backend, "POST", path, b"", headers)[0] == 401
    assert backend.control.updates == []


def test_options_and_unknown_routes():
    assert call(sagemaker(), "OPTIONS", "/score", headers={})[0] == 204
    assert call(sagemaker(), "GET", "/nope")[0] == 404


def test_unset_keys_lock_their_routes():
    assert route("GET", "/status", {"x-demo-key": ""}, b"", sagemaker(), {"demo": "", "admin": ""})[0] == 401
    assert route("POST", "/warm", {"x-admin-key": ""}, b"", sagemaker(), {"demo": KEY, "admin": ""})[0] == 401


def test_score_passes_the_body_to_the_inference_component_and_returns_the_verdict():
    backend = sagemaker()
    body = json.dumps({"image": "abc"}).encode()
    assert call(backend, "POST", "/score", body) == (200, VERDICT)
    (kw,) = backend.runtime.calls
    assert kw["EndpointName"] == "ep" and kw["InferenceComponentName"] == "ic" and kw["Body"] == body


def test_choose_passes_the_body_to_the_inference_component_and_returns_the_choice():
    backend = sagemaker(CHOICE)
    assert call(backend, "POST", "/choose", CHOOSE_BODY) == (200, CHOICE)
    (kw,) = backend.runtime.calls
    assert kw["EndpointName"] == "ep" and kw["InferenceComponentName"] == "ic" and kw["Body"] == CHOOSE_BODY


@pytest.mark.parametrize("path", ["/score", "/choose"])
@pytest.mark.parametrize("current,desired,state", [(0, 0, "cold"), (0, 1, "warming")])
def test_decider_calls_without_capacity_are_503_with_the_component_state(path, current, desired, state):
    assert call(sagemaker(NO_CAPACITY, current, desired), "POST", path, b"{}") == (503, {"state": state})


@pytest.mark.parametrize("path", ["/score", "/choose"])
def test_decider_calls_map_a_decider_400_through(path):
    err = ClientError({"Error": {"Code": "ModelError", "Message": "not an image"}, "OriginalStatusCode": 400},
                      "InvokeEndpoint")
    status, body = call(sagemaker(err), "POST", path, b"{}")
    assert status == 400


@pytest.mark.parametrize("current,desired,state", [(0, 0, "cold"), (0, 1, "warming"), (1, 1, "live"), (1, 0, "live")])
def test_status_derives_state_from_copy_counts(current, desired, state):
    assert call(sagemaker(current=current, desired=desired), "GET", "/status") == (200, {"state": state})


def test_warm_asks_for_one_copy_once():
    backend = sagemaker(current=0, desired=0)
    assert call(backend, "POST", "/warm") == (202, {"state": "warming"})
    assert call(backend, "POST", "/warm") == (202, {"state": "warming"})
    assert backend.control.updates == [1]
    assert call(backend, "GET", "/status") == (200, {"state": "warming"})


def test_sleep_sets_zero_copies():
    backend = sagemaker(current=1, desired=1)
    assert call(backend, "POST", "/sleep") == (202, {"state": "cold"})
    assert backend.control.updates == [0]


def test_lambda_handler_speaks_payload_2(monkeypatch):
    monkeypatch.setenv("DEMO_KEY", KEY)
    monkeypatch.setenv("ADMIN_KEY", ADMIN)
    monkeypatch.setattr(fd, "_backend", sagemaker())
    event = {
        "rawPath": "/score",
        "headers": {"x-demo-key": KEY, "content-type": "application/json"},
        "requestContext": {"http": {"method": "POST"}},
        "body": "eyJpbWFnZSI6ICJhYmMifQ==",
        "isBase64Encoded": True,
    }
    r = fd.handler(event, None)
    assert r["statusCode"] == 200 and json.loads(r["body"]) == VERDICT
    assert fd._backend.runtime.calls[0]["Body"] == b'{"image": "abc"}'


def test_lambda_handler_turns_backend_failures_into_502(monkeypatch):
    monkeypatch.setenv("DEMO_KEY", KEY)
    monkeypatch.setenv("ADMIN_KEY", ADMIN)
    boom = ClientError({"Error": {"Code": "ThrottlingException", "Message": "slow down"}}, "InvokeEndpoint")
    monkeypatch.setattr(fd, "_backend", sagemaker(boom))
    event = {"rawPath": "/score", "headers": AUTH, "requestContext": {"http": {"method": "POST"}}, "body": "{}"}
    assert fd.handler(event, None)["statusCode"] == 502


@pytest.fixture
def fake_decider():
    replies = {"ping": 200, "invocations": (200, VERDICT), "bodies": []}

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(replies["ping"])
            self.end_headers()

        def do_POST(self):
            replies["bodies"].append(self.rfile.read(int(self.headers["content-length"])))
            status, payload = replies["invocations"]
            self.send_response(status)
            self.end_headers()
            self.wfile.write(json.dumps(payload).encode())

        def log_message(self, *a):
            pass

    server = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}", replies
    server.shutdown()


def test_http_backend_is_live_when_the_decider_pings_200(fake_decider):
    url, replies = fake_decider
    backend = HttpBackend(url)
    assert call(backend, "GET", "/status") == (200, {"state": "live"})
    assert call(backend, "POST", "/score", b'{"image": "x"}') == (200, VERDICT)
    replies["ping"] = 503
    assert call(backend, "GET", "/status") == (200, {"state": "warming"})


def test_http_backend_passes_choose_through_to_the_decider(fake_decider):
    url, replies = fake_decider
    replies["invocations"] = (200, CHOICE)
    assert call(HttpBackend(url), "POST", "/choose", CHOOSE_BODY) == (200, CHOICE)
    assert replies["bodies"] == [CHOOSE_BODY]


def test_http_backend_maps_a_loading_decider_to_warming(fake_decider):
    url, replies = fake_decider
    replies["invocations"] = (503, {"error": "model not loaded"})
    assert call(HttpBackend(url), "POST", "/choose", CHOOSE_BODY) == (503, {"state": "warming"})


def test_http_backend_reports_cold_when_the_decider_is_down():
    backend = HttpBackend("http://127.0.0.1:9")
    assert call(backend, "GET", "/status") == (200, {"state": "cold"})
    assert call(backend, "POST", "/score", b"{}") == (503, {"state": "cold"})
    assert call(backend, "POST", "/choose", CHOOSE_BODY) == (503, {"state": "cold"})
    assert call(backend, "POST", "/warm")[0] == 202
