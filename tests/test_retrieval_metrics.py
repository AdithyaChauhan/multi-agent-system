"""Scoring rules for the product-search eval (eval/retrieval_metrics.py)."""

import pytest

from eval.retrieval_metrics import by_tag, percentile, score_query, summarize

QUERY = {"expect": {"exact": ["E1", "E2"], "ok": ["K1"]}}


class TestScoreQuery:
    def test_exact_product_in_top_five_is_a_hit_with_its_rank(self):
        s = score_query(QUERY, ["X", "K1", "E2", "Y"], "")
        assert s["hit5"] is True and s["rr"] == pytest.approx(1 / 3, abs=1e-3)

    def test_ok_products_count_for_precision_but_not_for_a_hit(self):
        s = score_query(QUERY, ["K1", "X", "Y"], "")
        assert s["hit5"] is False and s["rr"] == 0.0
        assert s["precision3"] == pytest.approx(1 / 3, abs=1e-3)

    def test_hit_must_be_within_the_top_five(self):
        assert score_query(QUERY, ["A", "B", "C", "D", "F", "E1"], "")["hit5"] is False

    def test_precision_uses_only_what_was_shown(self):
        assert score_query(QUERY, ["E1"], "")["precision3"] == 1.0

    def test_nothing_shown_is_empty_and_scores_zero(self):
        s = score_query(QUERY, [], "Sorry, I couldn't find that.")
        assert s["empty"] is True and s["hit5"] is False and s["precision3"] == 0.0

    def test_brand_we_dont_carry_accepts_any_product_of_the_right_kind(self):
        s = score_query({"expect": {"exact": [], "ok": ["K1", "K2"]}}, ["K2"], "")
        assert s["hit5"] is True and s["rr"] == 1.0

    @pytest.mark.parametrize(
        "shown,reply,correct",
        [
            ([], "Sorry, we don't carry iphones.", True),
            ([], "What are you looking for?", False),
            (["P1"], "Sorry, we don't carry iphones.", False),
        ],
    )
    def test_out_of_scope_needs_no_products_and_a_clear_answer(self, shown, reply, correct):
        assert score_query({"expect_none": True}, shown, reply)["correct_refusal"] is correct


def _rec(score, tags=("plain",), tokens=100, seconds=1.0, error=None):
    rec = {"score": score, "tags": list(tags), "llm_calls": 2, "tokens": tokens, "seconds": seconds}
    if error:
        rec["error"] = error
    return rec


def test_summary_averages_scored_queries_and_counts_errors():
    hit = score_query(QUERY, ["E1", "K1", "X"], "")
    miss = score_query(QUERY, [], "")
    refusal = score_query({"expect_none": True}, [], "we don't carry that")
    out = summarize([_rec(hit), _rec(miss, tokens=300), _rec(refusal), {"error": "boom", "tags": []}])
    assert out["scored"] == 3 and out["errors"] == 1
    assert out["recall@5"] == 0.5 and out["empty_rate"] == 0.5 and out["correct_refusal_rate"] == 1.0
    assert out["precision@3"] == pytest.approx(1 / 3, abs=1e-3)
    assert out["tokens_per_query"] == pytest.approx(166.667, abs=1e-3)


def test_by_tag_breaks_results_down():
    hit = score_query(QUERY, ["E1"], "")
    miss = score_query(QUERY, ["X"], "")
    tags = by_tag([_rec(hit, tags=["brand"]), _rec(miss, tags=["brand", "typo"])])
    assert tags["brand"]["recall@5"] == 0.5 and tags["typo"]["recall@5"] == 0.0


def test_percentile_is_nearest_rank():
    assert percentile([], 95) is None
    assert percentile([3.0, 1.0, 2.0], 50) == 2.0
    assert percentile(list(range(1, 21)), 95) == 19


def test_rescore_applies_current_labels_to_a_saved_run(tmp_path, monkeypatch):
    import json

    import eval.run_retrieval as runner

    labels = tmp_path / "queries.json"
    labels.write_text(json.dumps({"queries": [{"id": "q1", "expect": {"exact": ["NEW"], "ok": []}}]}), encoding="utf-8")
    saved = tmp_path / "run.json"
    record = {"id": "q1", "tags": ["plain"], "shown": ["NEW"], "reply": "", "llm_calls": 2, "tokens": 9, "seconds": 1.0}
    record["score"] = {"kind": "search", "hit5": False, "rr": 0.0, "precision3": 0.0, "empty": False, "shown": 1}
    saved.write_text(json.dumps({"queries": [record]}), encoding="utf-8")
    monkeypatch.setattr(runner, "QUERIES_FILE", labels)

    result = runner.rescore(saved)

    assert result["summary"]["recall@5"] == 1.0
    assert json.loads(saved.read_text(encoding="utf-8"))["queries"][0]["score"]["hit5"] is True
