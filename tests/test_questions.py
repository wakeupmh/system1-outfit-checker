import pytest
from strands_decider.core import Request

from decider.questions import QUESTIONS, to_verdict


def answers(level=2.0, person=0.9, formality="casual", palette="earthy", shoes=0.3):
    probs = {"0": 0.1, "1": 0.2, "2": 0.4, "3": 0.2, "4": 0.1}
    return {
        "outfit": {"type": "score", "score": level, "probabilities": probs},
        "person": {"type": "noul", "noul": person},
        "formality": {"type": "choice", "choice": formality, "probabilities": {}},
        "palette": {"type": "choice", "choice": palette, "probabilities": {}},
        "shoes": {"type": "noul", "noul": shoes},
    }


def test_questions_are_a_valid_decider_request_matching_the_contract():
    req = Request.model_validate({"state": "A webcam photo.", "images": [], "questions": QUESTIONS})
    q = {name: question.normalised() for name, question in req.questions.items()}
    assert set(q) == {"outfit", "person", "formality", "palette", "shoes"}
    assert q["outfit"].kind == "score" and len(q["outfit"].options) == 5
    assert q["person"].kind == "noul" and q["person"].instructions == "Is a person with their clothes visible?"
    assert q["shoes"].kind == "noul" and q["shoes"].instructions == "Are shoes visible?"
    assert q["formality"].options == ("athleisure", "casual", "smart_casual", "formal", "party")
    assert q["palette"].options == ("neutral", "monochrome", "earthy", "pastel", "bold")


@pytest.mark.parametrize(
    "level,score",
    [(0.5, 0), (3.2, 100), (1.85, 50), (0.0, 0), (4.0, 100), (2.44, 72)],
)
def test_score_stretches_measured_levels_onto_0_to_100(level, score):
    assert to_verdict(answers(level=level), 10.0, "m")["score"] == score


def test_no_person_scores_zero_whatever_the_outfit():
    assert to_verdict(answers(level=3.0, person=0.49), 10.0, "m")["score"] == 0
    assert to_verdict(answers(level=3.0, person=0.5), 10.0, "m")["score"] > 0


def test_verdict_shape():
    v = to_verdict(answers(level=2.4449, person=0.973), 143.24, "some/model")
    assert v == {
        "score": 72,
        "level": 2.44,
        "probs": [0.1, 0.2, 0.4, 0.2, 0.1],
        "facts": {"person": 0.97, "formality": "casual", "palette": "earthy", "shoes": 0.3},
        "ms": 143.2,
        "model": "some/model",
    }
