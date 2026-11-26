import pytest
from strands_decider.core import Request

from decider.questions import QUESTIONS, look_questions, look_state, to_choice, to_verdict


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


def look(level=1.6, person=0.9, formality="casual", palette="neutral", shoes=0.5):
    a = answers(person=person, formality=formality, palette=palette, shoes=shoes)
    del a["outfit"]
    a["fit"] = {"type": "score", "score": level, "probabilities": {"0": 0.1, "1": 0.2, "2": 0.4, "3": 0.2, "4": 0.1}}
    return a


def test_occasion_questions_are_a_valid_decider_request_matching_the_contract():
    occasion = "a dinner date"
    req = Request.model_validate({"state": look_state(occasion), "images": [], "questions": look_questions(occasion)})
    q = {name: question.normalised() for name, question in req.questions.items()}
    assert set(q) == {"fit", "person", "formality", "palette", "shoes"}
    assert q["fit"].kind == "score" and len(q["fit"].options) == 5
    assert "a dinner date" in q["fit"].instructions
    assert look_state(occasion) == "The plan: a dinner date."
    assert q["formality"].options == ("athleisure", "casual", "smart_casual", "formal", "party")


@pytest.mark.parametrize("level,fit", [(0.8, 0), (2.4, 100), (1.6, 50), (0.0, 0), (4.0, 100), (1.97, 73)])
def test_fit_stretches_measured_levels_onto_0_to_100(level, fit):
    choice = to_choice("x", [look(level=level), look(level=0.1)], 10.0, "m")
    assert choice["looks"][0]["fit"] == fit


def test_choice_picks_the_highest_level_and_keeps_the_request_order():
    choice = to_choice("jantar romântico", [look(1.09), look(1.97), look(1.5)], 5012.43, "some/model")
    assert choice["pick"] == 1
    assert choice["margin"] == 0.47 and choice["confident"] is True
    assert [lk["level"] for lk in choice["looks"]] == [1.09, 1.97, 1.5]
    assert choice["occasion"] == "jantar romântico" and choice["ms"] == 5012.4 and choice["model"] == "some/model"


def test_choice_shape():
    choice = to_choice("x", [look(1.09, person=0.951, formality="athleisure", shoes=0.13), look(1.97)], 1.0, "m")
    assert set(choice) == {"occasion", "pick", "confident", "margin", "looks", "ms", "model"}
    assert choice["looks"][0] == {
        "fit": 18,
        "level": 1.09,
        "probs": [0.1, 0.2, 0.4, 0.2, 0.1],
        "facts": {"person": 0.95, "formality": "athleisure", "palette": "neutral", "shoes": 0.13},
    }


@pytest.mark.parametrize("margin,confident", [(0.39, False), (0.4, True), (1.41, True)])
def test_confident_means_a_margin_of_at_least_0_4(margin, confident):
    choice = to_choice("x", [look(1.0), look(1.0 + margin)], 1.0, "m")
    assert choice["pick"] == 1
    assert choice["margin"] == margin and choice["confident"] is confident


def test_a_tie_picks_the_first_look_and_is_not_confident():
    choice = to_choice("x", [look(1.5), look(1.5)], 1.0, "m")
    assert choice["pick"] == 0 and choice["margin"] == 0 and choice["confident"] is False


def test_a_look_with_no_person_fits_zero_and_cannot_win_on_level():
    choice = to_choice("x", [look(2.3, person=0.49), look(1.2)], 1.0, "m")
    assert choice["looks"][0]["fit"] == 0
    assert choice["pick"] == 1 and choice["margin"] == 1.2
