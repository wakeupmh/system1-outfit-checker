"""Lambda function URL front door: auth, routing to the decider, warm-up and status."""

from __future__ import annotations

import base64
import hmac
import json
import os
import urllib.error
import urllib.request

COLD, WARMING, LIVE = "cold", "warming", "live"


def derive_state(current: int, desired: int) -> str:
    if current > 0:
        return LIVE
    if desired > current:
        return WARMING
    return COLD


class SageMakerBackend:
    def __init__(self, runtime, control, endpoint: str, component: str):
        self.runtime = runtime
        self.control = control
        self.endpoint = endpoint
        self.component = component

    @classmethod
    def from_env(cls):
        import boto3
        from botocore.config import Config

        config = Config(read_timeout=70, retries={"max_attempts": 1})
        return cls(
            boto3.client("sagemaker-runtime", config=config),
            boto3.client("sagemaker"),
            os.environ["ENDPOINT_NAME"],
            os.environ["INFERENCE_COMPONENT"],
        )

    def _copies(self) -> tuple[int, int]:
        rc = self.control.describe_inference_component(InferenceComponentName=self.component).get("RuntimeConfig", {})
        return rc.get("CurrentCopyCount", 0), rc.get("DesiredCopyCount", 0)

    def state(self) -> str:
        return derive_state(*self._copies())

    def _set_copies(self, n: int):
        self.control.update_inference_component_runtime_config(
            InferenceComponentName=self.component, DesiredRuntimeConfig={"CopyCount": n}
        )

    def warm(self) -> str:
        current, desired = self._copies()
        if desired < 1:
            self._set_copies(1)
            desired = 1
        return derive_state(current, desired)

    def sleep(self) -> str:
        current, desired = self._copies()
        if desired > 0:
            self._set_copies(0)
        return COLD

    def invoke(self, body: bytes) -> tuple[int, dict]:
        from botocore.exceptions import ClientError

        try:
            r = self.runtime.invoke_endpoint(
                EndpointName=self.endpoint,
                InferenceComponentName=self.component,
                ContentType="application/json",
                Accept="application/json",
                Body=body,
            )
        except ClientError as e:
            error = e.response.get("Error", {})
            if error.get("Code") == "ModelError":
                status = int(e.response.get("OriginalStatusCode") or 502)
                return (status if 400 <= status < 500 else 502), {"error": error.get("Message", "")}
            if "capacity" in error.get("Message", "").lower():
                return 503, {"state": COLD if self.state() == COLD else WARMING}
            raise
        return 200, json.loads(r["Body"].read())


class HttpBackend:
    """A decider reachable over HTTP (local runs). /warm and /sleep do nothing."""

    def __init__(self, url: str):
        self.url = url.rstrip("/")

    @classmethod
    def from_env(cls):
        return cls(os.environ["DECIDER_URL"])

    def _call(self, path: str, body: bytes | None = None, timeout: float = 5) -> tuple[int, bytes]:
        req = urllib.request.Request(
            self.url + path, data=body, headers={"content-type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def state(self) -> str:
        try:
            status, _ = self._call("/ping")
        except OSError:
            return COLD
        return LIVE if status == 200 else WARMING

    def warm(self) -> str:
        return self.state()

    def sleep(self) -> str:
        return self.state()

    def invoke(self, body: bytes) -> tuple[int, dict]:
        try:
            status, data = self._call("/invocations", body, timeout=70)
        except OSError:
            return 503, {"state": COLD}
        if status == 503:
            return 503, {"state": WARMING}
        return status, json.loads(data)


BACKENDS = {"sagemaker": SageMakerBackend, "http": HttpBackend}

# Each route names the key it needs. The demo key ships in the page; the admin key does not,
# so only the presenter can start or stop the GPU.
KEY_HEADERS = {"demo": "x-demo-key", "admin": "x-admin-key"}

ROUTES = {
    ("POST", "/score"): ("demo", lambda b, body: b.invoke(body)),
    ("POST", "/choose"): ("demo", lambda b, body: b.invoke(body)),
    ("POST", "/facts"): ("demo", lambda b, body: b.invoke(body)),
    ("GET", "/status"): ("demo", lambda b, body: (200, {"state": b.state()})),
    ("POST", "/warm"): ("admin", lambda b, body: (202, {"state": b.warm()})),
    ("POST", "/sleep"): ("admin", lambda b, body: (202, {"state": b.sleep()})),
}


def keys_from_env() -> dict:
    return {"demo": os.environ.get("DEMO_KEY", ""), "admin": os.environ.get("ADMIN_KEY", "")}


def route(method: str, path: str, headers: dict, body: bytes, backend, keys: dict) -> tuple[int, dict]:
    """`headers` keys are lower case, as Lambda delivers them. An empty key locks its routes."""
    if method == "OPTIONS":
        return 204, {}
    entry = ROUTES.get((method, path))
    if entry is None:
        return 404, {"error": f"no route {method} {path}"}
    role, op = entry
    header = KEY_HEADERS[role]
    expected, given = keys.get(role, ""), headers.get(header, "")
    if not expected or not hmac.compare_digest(given.encode(), expected.encode()):
        return 401, {"error": f"missing or wrong {header}"}
    return op(backend, body)


_backend = None


def handler(event, context):
    global _backend
    if _backend is None:
        _backend = BACKENDS[os.environ.get("BACKEND", "sagemaker")].from_env()
    body = event.get("body") or ""
    raw = base64.b64decode(body) if event.get("isBase64Encoded") else body.encode()
    try:
        status, payload = route(
            event["requestContext"]["http"]["method"],
            event.get("rawPath", "/"),
            event.get("headers") or {},
            raw,
            _backend,
            keys_from_env(),
        )
    except Exception as e:
        print(f"front door error: {e!r}")
        status, payload = 502, {"error": "decider call failed"}
    return {"statusCode": status, "headers": {"content-type": "application/json"}, "body": json.dumps(payload)}
