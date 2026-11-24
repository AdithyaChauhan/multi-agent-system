"""The safety floor (ADR 0008) and the catalog's say on "unclear" messages (Phase 4)."""

from unittest.mock import patch

import pytest

import app.agents.router as router
from app.agents.router import SAFETY_PATTERN, RouteDecision
from app.core import config

REPORTS = [
    "my charger caught fire",
    "the heater burst into flames last night",
    "it sparked and gave me a shock",
    "I got an electric shock from the iron",
    "sparks coming out of the plug",
    "smoke coming from the kettle",
    "the power bank exploded",
    "the cable melted",
    "my son was injured by the blender",
    "it burned my hand",
    "the fan was on fire",
]
NOT_REPORTS = [
    "amazon fire tv stick",
    "fire-boltt smartwatch",
    "is the fire tv on sale",
    "fire sale on tvs?",
    "hdmi cable for fire stick",
    "smoke detector",
    "burner phone",
    "explosive bass speakers",
    "shock proof case",
    "I have an issue with my order",
]


@pytest.mark.parametrize("message", REPORTS)
def test_real_reports_match(message):
    assert SAFETY_PATTERN.search(message)


@pytest.mark.parametrize("message", NOT_REPORTS)
def test_product_names_and_ordinary_words_do_not(message):
    assert not SAFETY_PATTERN.search(message)


def _classify(decision, message, closest=None):
    with patch.object(router, "call_llm", return_value=decision), patch.object(
        router, "fetch_user_orders", return_value=[]
    ), patch.object(router.hybrid, "catalog_match", return_value=closest):
        return router.classify({"user_message": message, "user_id": "anon-1"})


class TestClassify:
    def test_pattern_escalates_what_the_model_missed(self):
        result = _classify(RouteDecision(intent="support", risk="none"), "my charger caught fire")
        assert result["risk"] == "safety"
        assert router.route({**result, "user_id": "anon-1"}) == "safety"

    def test_pattern_never_lowers_or_moves_anything(self):
        result = _classify(RouteDecision(intent="product", risk="none"), "amazon fire tv stick")
        assert (result["intent"], result["risk"]) == ("product", "none")

    def test_unclear_becomes_product_when_the_catalog_sells_it(self, monkeypatch):
        monkeypatch.setattr(config, "PRODUCT_SEARCH", "hybrid")
        close = {"type": "lint remover", "word": "lint remover", "similarity": 0.76}
        result = _classify(RouteDecision(intent="unclear", reply="Hi!"), "remove fuzz balls from my sweaters", close)
        assert (result["intent"], result["final_response"]) == ("product", None)

    def test_unclear_stays_unclear_without_a_close_product(self, monkeypatch):
        monkeypatch.setattr(config, "PRODUCT_SEARCH", "hybrid")
        far = {"type": "home appliance", "word": "humidifier", "similarity": 0.62}
        result = _classify(
            RouteDecision(intent="unclear", reply="Hi! What do you need?"), "resolve support issues", far
        )
        assert (result["intent"], result["final_response"]) == ("unclear", "Hi! What do you need?")
