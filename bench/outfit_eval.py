"""Score a small labelled image set with one model and check that it ranks outfits.

    python bench/outfit_eval.py d1        [--model LiquidAI/d1-2B]
    python bench/outfit_eval.py decider   [--model StrandsAgents/strands-decider-E2B-gemma4-v2-2611]
    python bench/outfit_eval.py siglip    [--model google/siglip2-base-patch16-224]

Groups in labels.csv: none (no outfit in view), plain (sport or plain basics), styled
(fashion photos). Pass: mean(none) < mean(plain) < mean(styled) and
AUC(styled vs the rest) >= 0.85. Prints per-image level (0-4), seconds, and a summary.
"""
import argparse, base64, csv, io, json, statistics, sys, time, urllib.request
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from server import QUESTION, LEVELS  # the app's own question

CACHE = ROOT / "bench" / ".images"
FASHION_ROWS = ("https://datasets-server.huggingface.co/first-rows"
                "?dataset=detection-datasets/fashionpedia&config=default&split=val")


def load_images():
    CACHE.mkdir(parents=True, exist_ok=True)
    rows = list(csv.DictReader(open(ROOT / "bench" / "labels.csv")))
    fashion = None
    out = []
    for r in rows:
        path = CACHE / f"{r['source']}_{r['id']}.jpg"
        if not path.exists():
            if r["source"] == "coco":
                url = f"http://images.cocodataset.org/val2017/{r['id']}.jpg"
            else:
                fashion = fashion or json.load(urllib.request.urlopen(FASHION_ROWS))["rows"]
                img = fashion[int(r["id"])]["row"]["image"]
                url = img["src"] if isinstance(img, dict) else img
            urllib.request.urlretrieve(url, path)
        im = Image.open(path).convert("RGB")
        im.thumbnail((512, 512))
        out.append((f"{r['source']}_{r['id']}", r["group"], im))
    return out


def jpeg_b64(im):
    buf = io.BytesIO(); im.save(buf, "JPEG", quality=80)
    return base64.b64encode(buf.getvalue()).decode()


def d1_scorer(model_id):
    import torch
    from transformers import AutoModel
    m = AutoModel.from_pretrained(model_id, trust_remote_code=True, dtype=torch.float32)
    def score(im):
        with torch.inference_mode():
            p = m.system_one(None, {"outfit": QUESTION}, [im])["answers"]["outfit"]["probabilities"]
        p = [float(v) for v in (p.values() if isinstance(p, dict) else p)]
        return sum(i * v for i, v in enumerate(p))
    return score


def decider_scorer(model_id):
    from strands_decider.core import Request
    from strands_decider.decision import load_decision_engine
    eng = load_decision_engine(model_id, device="cpu", dtype="bfloat16")
    def score(im):
        req = Request.model_validate({"state": "A webcam photo.", "images": [jpeg_b64(im)],
                                      "questions": {"outfit": QUESTION}})
        return float(eng.evaluate(req).model_dump()["answers"]["outfit"]["score"])
    return score


def siglip_scorer(model_id):
    import torch
    from transformers import AutoModel, AutoProcessor
    m = AutoModel.from_pretrained(model_id).eval(); proc = AutoProcessor.from_pretrained(model_id)
    prompts = ["a photo with no person, or a person in pajamas or gym clothes",
               "a photo of a person in plain everyday basics",
               "a photo of a person in a neat, matching casual outfit",
               "a photo of a person in a stylish, put-together outfit",
               "a photo of a person in a striking high-fashion outfit"]
    def score(im):
        x = proc(text=prompts, images=im, padding="max_length", max_length=64, return_tensors="pt")
        with torch.inference_mode():
            p = m(**x).logits_per_image.softmax(-1)[0].tolist()
        return sum(i * v for i, v in enumerate(p))
    return score


def auc(pos, neg):
    pairs = [(p > n) + 0.5 * (p == n) for p in pos for n in neg]
    return sum(pairs) / len(pairs)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("kind", choices=["d1", "decider", "siglip"])
    ap.add_argument("--model")
    a = ap.parse_args()
    default = {"d1": "LiquidAI/d1-2B", "decider": "StrandsAgents/strands-decider-E2B-gemma4-v2-2611",
               "siglip": "google/siglip2-base-patch16-224"}[a.kind]
    model_id = a.model or default
    images = load_images()
    t = time.perf_counter()
    score = {"d1": d1_scorer, "decider": decider_scorer, "siglip": siglip_scorer}[a.kind](model_id)
    print(f"model {model_id}  load {time.perf_counter() - t:.1f}s", flush=True)
    score(images[0][2])  # warm-up
    res, times = {}, []
    for name, group, im in images:
        t = time.perf_counter(); s = score(im); dt = time.perf_counter() - t
        times.append(dt); res.setdefault(group, []).append(s)
        print(f"{dt:6.2f}s  {group:6s} {name:22s} level {s:.2f}", flush=True)
    means = {g: statistics.mean(v) for g, v in res.items()}
    a_ = auc(res["styled"], res["none"] + res["plain"])
    ok = means["none"] < means["plain"] < means["styled"] and a_ >= 0.85
    print(f"means none {means['none']:.2f}  plain {means['plain']:.2f}  styled {means['styled']:.2f}"
          f"  AUC(styled vs rest) {a_:.2f}  median {statistics.median(times):.2f}s/frame"
          f"  -> {'PASS' if ok else 'FAIL'}")


if __name__ == "__main__":
    main()
