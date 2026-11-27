"""The outfit and occasion questions, their display calibration, and the answers-to-Verdict/Choice/Facts mappings."""

from __future__ import annotations

LEVELS = [
    "Sleepwear, gym or lounge clothes, or no outfit clearly visible.",
    "Plain everyday basics thrown on without any styling.",
    "A neat, wearable outfit whose pieces go together but play it safe.",
    "A put-together look: colours, shapes and accessories clearly chosen to match.",
    "A striking, confident look with a clear personal style where every piece works.",
]

OUTFIT = {
    "type": "score",
    "instructions": (
        "Rate how well styled the visible outfit is as a look for going out today. "
        "Consider the clothes, shoes and accessories as a whole: colour harmony, fit "
        "of the pieces to each other, and whether there is a clear styling idea. "
        "Judge only the clothing. Ignore the person's body, face, looks, pose, "
        "the room and the photo quality. If no outfit is visible, pick the lowest level."
    ),
    "criteria": LEVELS,
}

QUESTIONS = {
    "outfit": OUTFIT,
    "person": {"type": "noul", "instructions": "Is a person with their clothes visible?"},
    "formality": {
        "type": "choice",
        "instructions": "Which dress code does the visible outfit fit best?",
        "criteria": {
            "athleisure": "Sportswear, gym or lounge clothes.",
            "casual": "Relaxed everyday clothes such as jeans, tees and sneakers.",
            "smart_casual": "Polished but relaxed, such as chinos, a shirt or a blazer without a tie.",
            "formal": "Suits, tailored dresses, ties or business wear.",
            "party": "Eye-catching evening or going-out wear.",
        },
    },
    "palette": {
        "type": "choice",
        "instructions": "Which colour palette describes the visible outfit?",
        "criteria": {
            "neutral": "Mostly black, white, grey, beige or navy.",
            "monochrome": "Shades of one single colour.",
            "earthy": "Browns, olives, rust, tan and other muted natural tones.",
            "pastel": "Soft, light colours.",
            "bold": "Bright, saturated or strongly contrasting colours.",
        },
    },
    "shoes": {"type": "noul", "instructions": "Are shoes visible?"},
}

FIT_LEVELS = [
    "Wrong for it: would look out of place or be impractical.",
    "Poor fit: wearable but clearly not what the occasion asks for.",
    "Acceptable: fits the occasion without standing out.",
    "Good fit: suits the occasion well.",
    "Ideal: exactly what this occasion calls for.",
]

FACT_NAMES = ("person", "formality", "palette", "shoes")


def occasion_fit(occasion: str) -> dict:
    return {
        "type": "score",
        "instructions": (
            f"How well does the visible outfit suit {occasion}? "
            "Judge only the clothes, shoes and accessories, not the person."
        ),
        "criteria": FIT_LEVELS,
    }


def look_questions(occasion: str) -> dict:
    """One look's /choose request: the occasion fit, and `person` so that a photo with nobody in it cannot win.
    Each question adds time (on the M4: fit alone 1.7 s, with `person` 2.1 s, with all four facts 3.3 s per
    look), so the other facts come from FACT_QUESTIONS when they are needed."""
    return {"fit": occasion_fit(occasion), "person": QUESTIONS["person"]}


def look_state(occasion: str) -> str:
    return f"The plan: {occasion}."


FRAME_STATE = "A webcam photo."
FACT_QUESTIONS = {name: QUESTIONS[name] for name in FACT_NAMES}
"""A /facts request: the four facts of a Verdict for one photo, with FRAME_STATE as its state."""

LEVEL_LO = 0.5
LEVEL_HI = 3.2
FIT_LO = 0.8
FIT_HI = 2.4
PERSON_MIN = 0.5
CONFIDENT_MARGIN = 0.4


def stretch(level: float, lo: float, hi: float) -> int:
    return max(0, min(100, round(100 * (level - lo) / (hi - lo))))


def display_score(level: float, person: float) -> int:
    if person < PERSON_MIN:
        return 0
    return stretch(level, LEVEL_LO, LEVEL_HI)


def display_fit(level: float, person: float) -> int:
    if person < PERSON_MIN:
        return 0
    return stretch(level, FIT_LO, FIT_HI)


def _level_and_probs(answer: dict) -> tuple[float, list[float]]:
    probs = [float(p) for _, p in sorted(answer["probabilities"].items(), key=lambda kv: int(kv[0]))]
    return float(answer["score"]), [round(p, 4) for p in probs]


def _facts(answers: dict) -> dict:
    return {
        "person": round(float(answers["person"]["noul"]), 2),
        "formality": answers["formality"]["choice"],
        "palette": answers["palette"]["choice"],
        "shoes": round(float(answers["shoes"]["noul"]), 2),
    }


def to_verdict(answers: dict, ms: float, model: str) -> dict:
    level, probs = _level_and_probs(answers["outfit"])
    person = float(answers["person"]["noul"])
    return {
        "score": display_score(level, person),
        "level": round(level, 2),
        "probs": probs,
        "facts": _facts(answers),
        "ms": round(ms, 1),
        "model": model,
    }


def to_choice(occasion: str, per_look_answers: list[dict], ms: float, model: str) -> dict:
    """The highest level wins and a tie goes to the first look. A look with no person in view ranks as level 0,
    like its fit, so an empty photo cannot win: asked for its fit alone, a photo with nobody in it scores up to
    level 2.2 (`docs/unknowns.md`, M11)."""
    looks, ranks = [], []
    for answers in per_look_answers:
        level, probs = _level_and_probs(answers["fit"])
        person = float(answers["person"]["noul"])
        looks.append({"fit": display_fit(level, person), "level": round(level, 2), "probs": probs})
        ranks.append(level if person >= PERSON_MIN else 0.0)
    order = sorted(range(len(ranks)), key=lambda i: -ranks[i])
    margin = round(ranks[order[0]] - ranks[order[1]], 2)
    return {
        "occasion": occasion,
        "pick": order[0],
        "confident": margin >= CONFIDENT_MARGIN,
        "margin": margin,
        "looks": looks,
        "ms": round(ms, 1),
        "model": model,
    }


def to_facts(per_image_answers: list[dict], ms: float, model: str) -> dict:
    """One Facts per photo, in the request's order."""
    return {"facts": [_facts(answers) for answers in per_image_answers], "ms": round(ms, 1), "model": model}
