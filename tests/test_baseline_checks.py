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


# ── Phase 6: checks every turn of every set gets ──────────────────────────────────────────────────

TICKET_REPLY = (
    "I've created a support ticket: **TKT-ABC123**\n\n**Response Time:** 24 hours\n\n"
    "Our support team will review this and contact you. You'll receive email updates at your registered address."
)
POLICY = (
    "**Returns:** Most items can be returned within 30 days of delivery in original condition.\n"
    "**Refunds:** Processed within 3-5 business days after we receive the return.\n"
    "**Damaged delivery:** Report within 48 hours for priority resolution."
)


def test_promises_nothing_keeps_are_flagged():
    with patch.object(rb, "_db_rows", return_value=[("TKT-ABC123",)]):
        failures = rb.claim_failures(TICKET_REPLY, "judge-user-1", tickets_delta=1)
    assert {"Response Time", "contact you", "email updates", "registered address"} <= {
        f.split("'")[1] for f in failures
    }
    assert rb.claim_failures("I'll contact the carrier right away.", "anon-x", 0)
    assert rb.claim_failures("A human team member will follow up with you.", "anon-x", 0)


def test_policy_text_and_plain_facts_are_not_promises():
    assert rb.claim_failures(POLICY, "anon-x", 0) == []
    assert rb.claim_failures("I can't contact the carrier or change an order myself.", "anon-x", 0) == []
    with patch.object(rb, "_db_rows", return_value=[("TKT-ABC123",)]):
        assert rb.claim_failures("Ticket **TKT-ABC123** opened for ORD-7001.", "judge-user-1", 1) == []


def test_a_ticket_or_cancel_claim_needs_the_database_to_agree():
    with patch.object(rb, "_db_rows", return_value=[]):
        assert rb.claim_failures("Ticket **TKT-NOPE1** opened.", "judge-user-1", 0) == [
            "ticket TKT-NOPE1 doesn't exist"
        ]
    assert rb.claim_failures("I've created a support ticket for you.", "judge-user-1", 0)
    with patch.object(rb, "order_status", return_value="processing"):
        assert rb.claim_failures("Order **ORD-7004** has been cancelled.", "judge-user-1", 0)
    with patch.object(rb, "order_status", return_value="cancelled"):
        assert rb.claim_failures("Order **ORD-7004** has been cancelled.", "judge-user-1", 0) == []


def test_the_same_product_twice_is_flagged_colours_included():
    watch = {"title": "Fire-Boltt Ninja 3 Smartwatch 1.69\" Black", "type": "smartwatch"}
    green = {**watch, "title": "Fire-Boltt Ninja 3 Smartwatch 1.69\" Green"}
    other = {"title": "Boult Dive+ Smartwatch", "type": "smartwatch"}
    assert rb.screen_failures("", {}, [watch, green, other]) == ["the same product is shown twice"]
    assert rb.screen_failures("", {}, [watch, other]) == []


def test_a_product_chip_must_match_a_card():
    watch = {"title": "Fire-Boltt Ninja 3", "type": "smartwatch", "attributes": {}}
    api = {"active_filters": [{"field": "product", "label": "mouse"}]}
    assert rb.screen_failures("", api, [watch]) == ["product chip 'mouse' matches none of the cards"]
    assert rb.screen_failures("", api, [{**watch, "type": "mouse"}]) == []


LISTED = (
    "You have multiple orders.\n\n• **ORD-7001** - Philips Steam Iron (delivered)\n"
    "• **ORD-7002** - boAt Rockerz Neckband (in transit)\n• **ORD-7003** - Mi TV (shipped)\n"
)


def test_the_page_hiding_an_in_transit_order_is_flagged():
    assert rb.screen_failures(LISTED, {}, []) == ["the page hides listed orders ['ORD-7002']"]
    assert rb.page_visible_orders(LISTED, {}) == {"ORD-7001", "ORD-7003"}


def test_orders_sent_as_data_are_what_the_page_shows():
    api = {"orders": [{"order_id": o} for o in ("ORD-7001", "ORD-7002", "ORD-7003")]}
    assert rb.page_visible_orders(LISTED, api) == {"ORD-7001", "ORD-7002", "ORD-7003"}
    assert rb.screen_failures(LISTED, api, []) == []
