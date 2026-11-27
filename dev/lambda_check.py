"""Runs frontdoor/ in AWS's Lambda runtime (the public Python 3.13 image and its runtime emulator), packaged
the way infra/frontdoor.tf zips it, and sends function URL events (payload 2.0) through it to a decider.

    DECIDER_MOCK=1 python -m uvicorn decider.app:app --host 0.0.0.0 --port 18080 &
    python dev/lambda_check.py                       # needs Docker; DECIDER_URL defaults to the host's 18080

Catches what the unit tests cannot: a module the Lambda runtime lacks, a handler path that does not match
infra/frontdoor.tf, or an event shape the real runtime delivers differently. Exits 1 on the first mismatch.
"""
import base64
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
IMAGE = "public.ecr.aws/lambda/python:3.13"
PORT = os.environ.get("LAMBDA_PORT", "19001")
DECIDER_URL = os.environ.get("DECIDER_URL", "http://host.docker.internal:18080")
DEMO, ADMIN = "demo-check", "admin-check"


def package(dest: Path):
    """Mirror infra/frontdoor.tf: frontdoor/ without __pycache__ and tests."""
    shutil.copytree(ROOT / "frontdoor", dest, ignore=shutil.ignore_patterns("__pycache__", "tests"))


def jpeg(colour) -> str:
    buf = io.BytesIO()
    Image.new("RGB", (64, 96), colour).save(buf, "JPEG")
    return base64.b64encode(buf.getvalue()).decode()


def invoke(method, path, headers, body=None, b64=False):
    raw = json.dumps(body) if body is not None else ""
    event = {"version": "2.0", "rawPath": path, "headers": headers, "requestContext": {"http": {"method": method}},
             "body": base64.b64encode(raw.encode()).decode() if b64 else raw, "isBase64Encoded": b64}
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}/2015-03-31/functions/function/invocations",
                                 json.dumps(event).encode())
    out = json.load(urllib.request.urlopen(req, timeout=120))
    return out["statusCode"], json.loads(out["body"])


def main():
    images = [jpeg(c) for c in [(220, 80, 160), (40, 40, 40), (90, 160, 220)]]
    demo = {"x-demo-key": DEMO, "content-type": "application/json"}
    cases = [
        ("GET /status with the demo key", ("GET", "/status", demo), 200, {"state"}),
        ("POST /choose, base64 body", ("POST", "/choose", demo, {"occasion": "Jantar romântico", "images": images}, True),
         200, {"pick", "looks", "margin", "confident"}),
        ("POST /facts", ("POST", "/facts", demo, {"images": images[:2]}), 200, {"facts"}),
        ("POST /score", ("POST", "/score", demo, {"image": images[0]}), 200, {"score", "facts"}),
        ("POST /score without a key", ("POST", "/score", {}, {"image": images[0]}), 401, {"error"}),
        ("POST /warm with only the demo key", ("POST", "/warm", demo), 401, {"error"}),
        ("POST /warm with the admin key", ("POST", "/warm", {"x-admin-key": ADMIN}), 202, {"state"}),
        ("OPTIONS preflight", ("OPTIONS", "/choose", {}), 204, set()),
    ]
    with tempfile.TemporaryDirectory() as tmp:
        task = Path(tmp) / "task"
        package(task)
        name = f"lambda-check-{os.getpid()}"
        subprocess.run(["docker", "run", "-d", "--rm", "--name", name, "-p", f"{PORT}:8080",
                        "--add-host", "host.docker.internal:host-gateway", "-v", f"{task}:/var/task:ro",
                        "-e", f"DEMO_KEY={DEMO}", "-e", f"ADMIN_KEY={ADMIN}", "-e", "BACKEND=http",
                        "-e", f"DECIDER_URL={DECIDER_URL}", IMAGE, "handler.handler"], check=True, capture_output=True)
        failed = False
        try:
            for _ in range(30):
                try:
                    invoke("OPTIONS", "/status", {})
                    break
                except OSError:
                    time.sleep(1)
            for label, args, want_status, want_keys in cases:
                try:
                    status, body = invoke(*args)
                except urllib.error.HTTPError as e:
                    status, body = e.code, {"runtime": e.read().decode(errors="replace")[:300]}
                ok = status == want_status and want_keys <= set(body)
                failed |= not ok
                print(f"{'OK  ' if ok else 'FAIL'} {status} {label}{'' if ok else f'  got {body}'}", flush=True)
        finally:
            logs = subprocess.run(["docker", "logs", name], capture_output=True, text=True)
            subprocess.run(["docker", "stop", name], capture_output=True)
        errors = [line for line in (logs.stdout + logs.stderr).splitlines() if "ERROR" in line or "Traceback" in line]
        if errors:
            failed = True
            print("runtime errors:", *errors[:5], sep="\n  ")
    print("LAMBDA CHECK FAILED" if failed else "LAMBDA CHECK OK")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
