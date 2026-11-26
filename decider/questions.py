"""The outfit questions, the display calibration, and the answers-to-Verdict mapping."""

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

LEVEL_LO = 0.5
LEVEL_HI = 3.2
PERSON_MIN = 0.5


def display_score(level: float, person: float) -> int:
    if person < PERSON_MIN:
        return 0
    return max(0, min(100, round(100 * (level - LEVEL_LO) / (LEVEL_HI - LEVEL_LO))))


def to_verdict(answers: dict, ms: float, model: str) -> dict:
    outfit = answers["outfit"]
    level = float(outfit["score"])
    probs = [float(p) for _, p in sorted(outfit["probabilities"].items(), key=lambda kv: int(kv[0]))]
    person = float(answers["person"]["noul"])
    return {
        "score": display_score(level, person),
        "level": round(level, 2),
        "probs": [round(p, 4) for p in probs],
        "facts": {
            "person": round(person, 2),
            "formality": answers["formality"]["choice"],
            "palette": answers["palette"]["choice"],
            "shoes": round(float(answers["shoes"]["noul"]), 2),
        },
        "ms": round(ms, 1),
        "model": model,
    }
