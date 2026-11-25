"""The conversation harness's honesty check: a product reply may say the results miss something only
when they do (eval/run_baseline.py · false_mismatch_claim)."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

import eval.run_baseline as rb

CLAIM = "These don't match everything you asked for, but they're the closest options we have:\n\n1. **M221**"


def _shown(**overrides):
    mouse = {"name": "Logitech M221", "brand": "Logitech", "type": "mouse", "price": 799, "rating": 4.4}
    return [{**mouse, "attributes": {}, **overrides}]


@pytest.fixture(autouse=True)
def catalog():
    """'mouse' resolves to the mouse type without a database."""
    with patch.object(rb, "_resolve", return_value=(SimpleNamespace(name="mouse"), None)):
        yield


def test_a_claim_over_matching_results_is_false():
    assert rb.false_mismatch_claim(CLAIM, {"product": "mouse", "brand": "logitech", "max_price": 1000}, _shown())


@pytest.mark.parametrize(
    "prefs,shown",
    [
        ({"product": "mouse", "max_price": 500}, _shown()),  # over budget: the claim is true
        ({"product": "mouse", "brand": "HP"}, _shown()),  # another brand
        ({"product": "mouse", "min_rating": 4.5}, _shown()),  # rated lower
        ({"product": "mouse"}, _shown(type="mouse pad")),  # another kind of product
        ({"product": "mouse", "features": ["silent"]}, _shown()),  # features can't be checked here
    ],
)
def test_true_or_uncheckable_claims_are_not_flagged(prefs, shown):
    assert not rb.false_mismatch_claim(CLAIM, prefs, shown)


def test_the_neutral_header_claims_nothing():
    assert not rb.false_mismatch_claim("Here's what I found:\n\n1. **M221**", {"product": "mouse"}, _shown())
