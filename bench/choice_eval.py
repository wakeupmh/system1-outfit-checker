"""Can Decider choose a look for an occasion? Compares the two ways to ask it, on CPU.

    python bench/choice_eval.py                    # stock trio: plain_tank, blazer, plaid_dress
    python bench/choice_eval.py --dir ~/looks      # 2 or 3 of your own looks, named after their files
    python bench/choice_eval.py --occasion "jantar romântico" --occasion "a job interview"

Table 1 asks one `choice` question over all looks, in every order. When the winner moves with the
order, the question is position-biased. Table 2 scores each look alone against the occasion, through
the same engine, questions and to_choice as the decider's POST /invocations, and prints its pick.
"""
import argparse, base64, itertools, sys, threading, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from bench.outfit_eval import fetch
from decider.app import DEFAULT_MODEL, MAX_LOOKS, MIN_LOOKS, ChooseRequest, DeciderEngine, choose, decode_image

STOCK = {"plain_tank": ("deepfashion", 0), "blazer": ("deepfashion", 10), "plaid_dress": ("deepfashion", 4)}
OCCASIONS = ["a dinner date at a nice restaurant", "a morning run in the park"]
SUFFIXES = (".jpg", ".jpeg", ".png", ".webp")


def stock_looks():
    return {name: fetch(*src) for name, src in STOCK.items()}


def dir_looks(folder):
    paths = sorted(p for p in Path(folder).expanduser().iterdir() if p.suffix.lower() in SUFFIXES)
    if not MIN_LOOKS <= len(paths) <= MAX_LOOKS:
        sys.exit(f"{folder} holds {len(paths)} images; the decider chooses between {MIN_LOOKS} and {MAX_LOOKS}")
    return {p.stem: p for p in paths}


def as_b64(path):
    return decode_image(base64.b64encode(Path(path).read_bytes()).decode())


def position_bias(engine, images, occasion):
    """One choice question over every order of the looks. Returns the winners, one per order."""
    from strands_decider.core import Request

    winners = []
    for order in itertools.permutations(images):
        criteria = {f"look_{i + 1}": f"The outfit in image {i + 1}" for i in range(len(order))}
        req = Request.model_validate({
            "state": f"Images 1 to {len(order)} each show one outfit. The plan: {occasion}.",
            "images": [images[name] for name in order],
            "questions": {"pick": {"type": "choice",
                                   "instructions": f"Which outfit is the better choice for {occasion}?",
                                   "criteria": criteria}},
        })
        t = time.perf_counter()
        a = engine.evaluate(req).model_dump()["answers"]["pick"]
        slot = int(a["choice"].split("_")[1]) - 1
        probs = "  ".join(f"{order[int(k.split('_')[1]) - 1]} {v:.2f}" for k, v in sorted(a["probabilities"].items()))
        winners.append(order[slot])
        print(f"  {' / '.join(order):40s} -> {order[slot]:14s} slot {slot + 1}  {probs}  "
              f"{time.perf_counter() - t:.1f}s", flush=True)
    return winners


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--dir", help="folder with 2 or 3 photos of your own looks")
    ap.add_argument("--occasion", action="append", help="repeatable; defaults to a dinner date and a morning run")
    ap.add_argument("--threads", type=int, help="CPU threads, to estimate smaller machines")
    a = ap.parse_args()
    if a.threads:
        import torch
        torch.set_num_threads(a.threads)
    looks = dir_looks(a.dir) if a.dir else stock_looks()
    occasions = a.occasion or OCCASIONS
    images = {name: as_b64(path) for name, path in looks.items()}
    names = list(images)

    t = time.perf_counter()
    decider = DeciderEngine(a.model, "cpu")
    print(f"model {a.model}  load {time.perf_counter() - t:.1f}s  looks {', '.join(names)}", flush=True)

    print("\n1. One choice question over all looks, every order")
    for occasion in occasions:
        print(f"\n{occasion}")
        winners = position_bias(decider.engine, images, occasion)
        top = max(set(winners), key=winners.count)
        verdict = "stable" if winners.count(top) == len(winners) else "POSITION-BIASED"
        print(f"  same winner ({top}) in {winners.count(top)} of {len(winners)} orders -> {verdict}")

    print("\n2. Each look scored alone (what POST /invocations does)")
    print(f"{'occasion':40s} " + " ".join(f"{n:>18s}" for n in names) + "   pick           margin  confident  seconds")
    for occasion in occasions:
        c = choose(decider, ChooseRequest(occasion, tuple(images.values())), threading.Lock())
        cells = " ".join(f"{lk['level']:>10.2f} fit {lk['fit']:3d}" for lk in c["looks"])
        print(f"{occasion[:40]:40s} {cells}   {names[c['pick']]:14s} {c['margin']:6.2f}  "
              f"{'yes' if c['confident'] else 'no':9s}  {c['ms'] / 1000:.1f}", flush=True)


if __name__ == "__main__":
    main()
