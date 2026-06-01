#!/usr/bin/env python3
"""
DeepEval CI/CD evaluation for the multi-agent e-commerce system.

Mode selection
--------------
  Default (CI):        Uses fixture_response from dataset.json — no LLM or API calls.
  RUN_LIVE_EVAL=true:  Calls the running app at EVAL_API_URL with real LLM responses.

Reports written to eval/reports/:
  eval_report.json  — machine-readable; pushed to LangSmith dataset for history
  eval_report.html  — self-contained HTML with charts and per-sample table

Exit code 1 if any metric average falls below its configured threshold.

Usage:
  python eval/run_deepeval.py                      # CI (fixture) mode
  RUN_LIVE_EVAL=true python eval/run_deepeval.py   # Live mode
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

# Disable deepeval telemetry before importing deepeval
os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "YES")
# Prevent deepeval from hard-failing on missing OpenAI key for custom metrics
os.environ.setdefault("OPENAI_API_KEY", os.getenv("OPENAI_API_KEY", "ci-fixture-mode-no-llm"))

from deepeval import evaluate as deepeval_evaluate  # noqa: E402
from deepeval.metrics import BaseMetric  # noqa: E402
from deepeval.test_case import LLMTestCase  # noqa: E402

try:
    from deepeval.evaluate.configs import AsyncConfig, DisplayConfig

    _DEEPEVAL_V4 = True
except ImportError:
    _DEEPEVAL_V4 = False

# ── Paths ────────────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parent.parent
EVAL_DIR = REPO_ROOT / "eval"

RUN_LIVE_EVAL = os.getenv("RUN_LIVE_EVAL", "false").lower() == "true"


# ── Custom rule-based metrics (no LLM — deterministic for CI) ────────────────


class AnswerRelevancyMetric(BaseMetric):
    """
    Measures whether the response addresses the user's query.

    Rule-based: the fraction of expected_contains phrases that appear in the
    actual output, minus a penalty for any expected_not_contains violations.
    Encoded as JSON in test_case.expected_output.
    """

    def __init__(self, threshold: float = 0.75):
        self.threshold = threshold
        self.score = 0.0
        self.success = False
        self.reason = ""

    def measure(self, test_case: LLMTestCase, *args, **kwargs) -> float:
        actual = (test_case.actual_output or "").lower()

        try:
            criteria = json.loads(test_case.expected_output or "{}")
        except (json.JSONDecodeError, TypeError):
            criteria = {}

        contains = criteria.get("contains", [])
        not_contains = criteria.get("not_contains", [])

        if not contains:
            self.score = 1.0
            self.reason = "No contains criteria — full score."
        else:
            hits = [p for p in contains if p.lower() in actual]
            self.score = len(hits) / len(contains)
            self.reason = f"Matched {len(hits)}/{len(contains)}: {hits}"

        violations = [p for p in not_contains if p.lower() in actual]
        if violations:
            penalty = min(self.score, 0.15 * len(violations))
            self.score = max(0.0, self.score - penalty)
            self.reason += f" | Violations: {violations}"

        self.success = self.score >= self.threshold
        return self.score

    def is_successful(self) -> bool:
        return self.success

    @property
    def __name__(self):
        return "answer_relevancy"

    async def a_measure(self, test_case: LLMTestCase, *args, **kwargs) -> float:
        return self.measure(test_case)


class CorrectnessMetric(BaseMetric):
    """
    Measures whether the response is well-formed and contains correct information.

    Rule-based checks:
      1. Response is at least 20 characters (non-trivial)
      2. No error/exception strings present
      3. Expected phrases are present (from criteria JSON)
      4. Forbidden phrases are absent
    """

    def __init__(self, threshold: float = 0.80):
        self.threshold = threshold
        self.score = 0.0
        self.success = False
        self.reason = ""

    def measure(self, test_case: LLMTestCase, *args, **kwargs) -> float:
        actual = (test_case.actual_output or "").strip()
        actual_lower = actual.lower()

        try:
            criteria = json.loads(test_case.expected_output or "{}")
        except (json.JSONDecodeError, TypeError):
            criteria = {}

        contains = criteria.get("contains", [])
        not_contains = criteria.get("not_contains", [])

        score = 0.0
        total = 0.0
        reasons = []

        # Check 1: non-trivial response length
        total += 1
        if len(actual) >= 20:
            score += 1
            reasons.append("length OK")
        else:
            reasons.append(f"too short ({len(actual)} chars)")

        # Check 2: no error strings
        total += 1
        error_phrases = ["something went wrong", "internal server error", "exception", "traceback", "http 500"]
        found_errors = [p for p in error_phrases if p in actual_lower]
        if not found_errors:
            score += 1
            reasons.append("no errors")
        else:
            reasons.append(f"error phrases: {found_errors}")

        # Check 3: expected content present
        if contains:
            total += 1
            hits = sum(1 for p in contains if p.lower() in actual_lower)
            sub = hits / len(contains)
            score += sub
            reasons.append(f"contains {hits}/{len(contains)}")

        # Check 4: forbidden content absent
        if not_contains:
            total += 1
            violations = [p for p in not_contains if p.lower() in actual_lower]
            sub = max(0.0, 1.0 - len(violations) / len(not_contains))
            score += sub
            reasons.append(f"not_contains ok={not violations}")

        self.score = score / total if total > 0 else 0.0
        self.reason = " | ".join(reasons)
        self.success = self.score >= self.threshold
        return self.score

    def is_successful(self) -> bool:
        return self.success

    @property
    def __name__(self):
        return "correctness"

    async def a_measure(self, test_case: LLMTestCase, *args, **kwargs) -> float:
        return self.measure(test_case)


# ── Helpers ──────────────────────────────────────────────────────────────────


def get_git_info() -> dict:
    try:
        sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True, cwd=REPO_ROOT).strip()
        branch = subprocess.check_output(["git", "rev-parse", "--abbrev-ref", "HEAD"], text=True, cwd=REPO_ROOT).strip()
    except Exception:
        sha = "unknown"
        branch = "unknown"
    return {"commit_sha": sha, "branch": branch}


def get_actual_output(tc_data: dict, config: dict) -> str:
    """Return fixture response (CI) or call the live API (live eval)."""
    if not RUN_LIVE_EVAL:
        return tc_data.get("fixture_response", "")

    import httpx

    api_url = os.getenv("EVAL_API_URL", config.get("live_eval_api_url", "http://localhost:8000"))
    try:
        resp = httpx.post(
            f"{api_url}/chat",
            json={"message": tc_data["input"]["user_message"]},
            headers={"X-User-ID": "eval-test-user", "Content-Type": "application/json"},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json().get("response", "")
    except Exception as exc:
        print(f"  [WARN] Live API call failed for {tc_data['id']}: {exc}")
        return ""


def push_to_langsmith(report: dict, config: dict) -> None:
    """Push the JSON report as a new example to the LangSmith evaluation dataset."""
    try:
        from langsmith import Client

        lc_key = os.getenv("LANGCHAIN_API_KEY") or os.getenv("LANGSMITH_API_KEY")
        if not lc_key:
            print("  [WARN] LANGCHAIN_API_KEY not set — skipping LangSmith push.")
            return

        client = Client(api_key=lc_key)
        dataset_name = config.get("langsmith_dataset_name", "multi-agent-ecommerce-eval")

        existing = list(client.list_datasets(dataset_name=dataset_name))
        if not existing:
            print(f"  [WARN] LangSmith dataset '{dataset_name}' not found — skipping push.")
            return

        client.create_example(
            inputs={
                "report_timestamp": report["timestamp"],
                "branch": report["branch"],
                "commit_sha": report["commit_sha"],
                "eval_mode": "live" if RUN_LIVE_EVAL else "fixture",
            },
            outputs={
                "overall_pass": report["overall_pass"],
                "per_metric_averages": report["per_metric_averages"],
                "total_samples": report["total_samples"],
            },
            dataset_id=existing[0].id,
        )
        print(f"  Pushed report to LangSmith dataset '{dataset_name}'")
    except Exception as exc:
        print(f"  [WARN] LangSmith push failed: {exc}")


# ── HTML report generation ────────────────────────────────────────────────────


def _svg_bar(score: float, threshold: float, width: int = 300) -> str:
    bar_w = int(score * width)
    thresh_x = int(threshold * width)
    color = "#2ecc71" if score >= threshold else "#e74c3c"
    return (
        f'<svg width="{width + 60}" height="44" style="display:block">'
        f'<rect x="30" y="8" width="{width}" height="26" fill="#ecf0f1" rx="4"/>'
        f'<rect x="30" y="8" width="{bar_w}" height="26" fill="{color}" rx="4"/>'
        f'<line x1="{30 + thresh_x}" y1="3" x2="{30 + thresh_x}" y2="41" '
        f'stroke="#7f8c8d" stroke-width="2" stroke-dasharray="4"/>'
        f'<text x="0" y="26" font-size="11" fill="#7f8c8d">0</text>'
        f'<text x="{width + 34}" y="26" font-size="11" fill="#7f8c8d">1</text>'
        f'<text x="{25 + thresh_x}" y="3" font-size="9" fill="#555" '
        f'text-anchor="middle">t={threshold:.2f}</text>'
        f'</svg>'
    )


def generate_html_report(report: dict, config: dict) -> str:
    ts = report["timestamp"]
    sha = report["commit_sha"][:8] if report["commit_sha"] != "unknown" else "unknown"
    branch = report["branch"]
    total = report["total_samples"]
    overall = report["overall_pass"]
    mode = "Live (real LLM)" if RUN_LIVE_EVAL else "Fixture (CI — no LLM)"
    status_color = "#27ae60" if overall else "#c0392b"
    status_text = "PASS ✓" if overall else "FAIL ✗"

    # Metric summary rows
    summary_rows = ""
    for name, data in report["per_metric_averages"].items():
        bg = "#d5f5e3" if data["pass"] else "#fadbd8"
        icon = "✅" if data["pass"] else "❌"
        label = name.replace("_", " ").title()
        summary_rows += (
            f'<tr style="background:{bg}">'
            f"<td>{label}</td>"
            f'<td><strong>{data["average_score"]:.3f}</strong></td>'
            f"<td>{data['threshold']:.2f}</td>"
            f"<td>{icon} {'PASS' if data['pass'] else 'FAIL'}</td>"
            f"</tr>"
        )

    # Chart blocks
    charts_html = '<div style="display:flex;flex-wrap:wrap;gap:32px">'
    for name, data in report["per_metric_averages"].items():
        label = name.replace("_", " ").title()
        charts_html += (
            f'<div style="min-width:360px">'
            f"<h3 style='margin:0 0 8px;color:#34495e'>{label}</h3>"
            + _svg_bar(data["average_score"], data["threshold"])
            + f'<p style="margin:4px 0;font-size:13px;color:#555">'
            f'Average: <strong>{data["average_score"]:.3f}</strong> &nbsp;|&nbsp; '
            f'Threshold: {data["threshold"]:.2f}</p>'
            f"</div>"
        )
    charts_html += "</div>"

    # Per-sample table
    metric_names = list(report["per_sample_scores"][0]["metrics"].keys()) if report["per_sample_scores"] else []
    header_cells = "".join(f"<th>{n.replace('_', ' ').title()}</th>" for n in metric_names)

    sample_rows = ""
    for s in report["per_sample_scores"]:
        bg = "#eafaf1" if s["overall_pass"] else "#fdedec"
        preview = (s.get("actual_output") or "")[:120].replace("<", "&lt;").replace(">", "&gt;")
        if len(s.get("actual_output") or "") > 120:
            preview += "…"
        m_cells = "".join(
            f'<td style="text-align:center">{d["score"]:.2f} {"✅" if d["pass"] else "❌"}</td>'
            for d in s["metrics"].values()
        )
        sample_rows += (
            f'<tr style="background:{bg}">'
            f'<td style="font-family:monospace;font-size:12px">{s["id"]}</td>'
            f"<td>{s['name']}</td>"
            f'<td style="font-size:12px;max-width:300px">{preview}</td>'
            f"{m_cells}"
            f'<td style="text-align:center">{"✅" if s["overall_pass"] else "❌"}</td>'
            f"</tr>"
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>DeepEval Report — {branch} @ {sha}</title>
  <style>
    *{{box-sizing:border-box;margin:0;padding:0}}
    body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
          background:#f0f2f5;color:#2c3e50;padding:24px}}
    .header{{background:{status_color};color:#fff;border-radius:10px;padding:24px 32px;margin-bottom:24px}}
    .header h1{{font-size:22px;margin-bottom:6px}}
    .header .meta{{font-size:13px;opacity:.88;line-height:1.8}}
    .badge{{background:rgba(0,0,0,.18);border-radius:5px;padding:2px 12px;
            font-weight:700;font-size:15px;letter-spacing:.5px}}
    section{{background:#fff;border-radius:10px;padding:24px 32px;
             margin-bottom:20px;box-shadow:0 1px 4px rgba(0,0,0,.08)}}
    h2{{font-size:17px;color:#2c3e50;border-bottom:2px solid #ecf0f1;
        padding-bottom:10px;margin-bottom:16px}}
    table{{width:100%;border-collapse:collapse;font-size:13px}}
    th{{background:#f4f6f8;padding:10px 14px;text-align:left;
        font-weight:600;color:#555;border-bottom:2px solid #dee2e6}}
    td{{padding:9px 14px;border-bottom:1px solid #f0f0f0;vertical-align:top}}
    tr:last-child td{{border-bottom:none}}
  </style>
</head>
<body>

  <div class="header">
    <h1>DeepEval Evaluation Report &nbsp;<span class="badge">{status_text}</span></h1>
    <div class="meta">
      🕐 {ts}<br>
      🌿 Branch: <strong>{branch}</strong> &nbsp;|&nbsp;
      #️⃣ Commit: <code>{sha}</code> &nbsp;|&nbsp;
      📊 Samples: <strong>{total}</strong> &nbsp;|&nbsp;
      ⚙️ Mode: <strong>{mode}</strong>
    </div>
  </div>

  <section>
    <h2>Metric Summary</h2>
    <table>
      <thead>
        <tr><th>Metric</th><th>Average Score</th><th>Threshold</th><th>Result</th></tr>
      </thead>
      <tbody>{summary_rows}</tbody>
    </table>
  </section>

  <section>
    <h2>Score Distribution</h2>
    {charts_html}
  </section>

  <section>
    <h2>Per-Sample Results</h2>
    <table>
      <thead>
        <tr>
          <th>ID</th><th>Name</th><th>Response (preview)</th>
          {header_cells}
          <th>Overall</th>
        </tr>
      </thead>
      <tbody>{sample_rows}</tbody>
    </table>
  </section>

</body>
</html>"""


# ── Main ─────────────────────────────────────────────────────────────────────


def main() -> None:
    sep = "=" * 62
    print(f"\n{sep}")
    print(f"  DeepEval Evaluation  |  {'LIVE MODE' if RUN_LIVE_EVAL else 'CI FIXTURE MODE'}")
    print(f"{sep}\n")

    # Load config and dataset
    config = yaml.safe_load((EVAL_DIR / "config.yaml").read_text())
    dataset = json.loads((EVAL_DIR / "dataset.json").read_text())
    git_info = get_git_info()

    thresholds = config["metrics"]
    rel_threshold = thresholds["answer_relevancy"]["threshold"]
    cor_threshold = thresholds["correctness"]["threshold"]

    print(f"Dataset : {len(dataset)} test cases")
    print(f"Metrics : answer_relevancy ≥ {rel_threshold}  |  correctness ≥ {cor_threshold}\n")

    # Build LLMTestCase objects
    test_cases: list[LLMTestCase] = []
    for tc_data in dataset:
        actual = get_actual_output(tc_data, config)
        criteria_json = json.dumps(
            {
                "contains": tc_data.get("expected_contains", []),
                "not_contains": tc_data.get("expected_not_contains", []),
            }
        )
        test_cases.append(
            LLMTestCase(
                input=tc_data["input"]["user_message"],
                actual_output=actual,
                expected_output=criteria_json,
            )
        )

    # Compute per-sample scores with fresh metric instances (so each sample is independent)
    per_sample: list[dict] = []
    relevancy_scores: list[float] = []
    correctness_scores: list[float] = []

    print("Evaluating test cases:")
    for tc, tc_data in zip(test_cases, dataset):
        rel_m = AnswerRelevancyMetric(threshold=rel_threshold)
        cor_m = CorrectnessMetric(threshold=cor_threshold)

        r = rel_m.measure(tc)
        c = cor_m.measure(tc)

        relevancy_scores.append(r)
        correctness_scores.append(c)

        passed = r >= rel_threshold and c >= cor_threshold
        icon = "✓" if passed else "✗"
        print(f"  [{icon}] {tc_data['id']}  rel={r:.2f}  cor={c:.2f}  — {tc_data['name']}")

        per_sample.append(
            {
                "id": tc_data["id"],
                "name": tc_data["name"],
                "input": tc_data["input"]["user_message"],
                "actual_output": tc.actual_output,
                "metrics": {
                    "answer_relevancy": {"score": r, "pass": r >= rel_threshold},
                    "correctness": {"score": c, "pass": c >= cor_threshold},
                },
                "overall_pass": passed,
            }
        )

    # Run deepeval evaluate() for framework-level integration
    print("\nRunning deepeval evaluate()...")
    try:
        eval_kwargs: dict = dict(
            metrics=[
                AnswerRelevancyMetric(threshold=rel_threshold),
                CorrectnessMetric(threshold=cor_threshold),
            ]
        )
        if _DEEPEVAL_V4:
            eval_kwargs["async_config"] = AsyncConfig(run_async=False)
            eval_kwargs["display_config"] = DisplayConfig(
                show_indicator=False,
                print_results=False,
                inspect_after_run=False,
            )
        else:
            eval_kwargs["run_async"] = False
            eval_kwargs["show_indicator"] = False
            eval_kwargs["print_results"] = False

        deepeval_evaluate(test_cases, **eval_kwargs)
    except Exception as exc:
        print(f"  [WARN] deepeval evaluate() raised: {exc}  (scores already computed above)")

    # Aggregate scores
    n = len(dataset)
    avg_rel = sum(relevancy_scores) / n
    avg_cor = sum(correctness_scores) / n

    per_metric_averages = {
        "answer_relevancy": {
            "average_score": round(avg_rel, 4),
            "threshold": rel_threshold,
            "pass": avg_rel >= rel_threshold,
        },
        "correctness": {
            "average_score": round(avg_cor, 4),
            "threshold": cor_threshold,
            "pass": avg_cor >= cor_threshold,
        },
    }
    overall_pass = all(m["pass"] for m in per_metric_averages.values())

    # Build JSON report
    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "commit_sha": git_info["commit_sha"],
        "branch": git_info["branch"],
        "total_samples": n,
        "overall_pass": overall_pass,
        "eval_mode": "live" if RUN_LIVE_EVAL else "fixture",
        "per_metric_averages": per_metric_averages,
        "per_sample_scores": per_sample,
    }

    # Write reports
    reports_dir = REPO_ROOT / config.get("report_dir", "eval/reports")
    reports_dir.mkdir(parents=True, exist_ok=True)

    json_path = reports_dir / "eval_report.json"
    html_path = reports_dir / "eval_report.html"

    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    html_path.write_text(generate_html_report(report, config))

    # Print summary
    print(f"\n{'─'*50}")
    print("Results:")
    for metric, data in per_metric_averages.items():
        status = "PASS ✓" if data["pass"] else "FAIL ✗"
        print(f"  {metric}: {data['average_score']:.3f}  (threshold: {data['threshold']:.2f})  → {status}")

    failed_cases = [s for s in per_sample if not s["overall_pass"]]
    if failed_cases:
        print(f"\n  {len(failed_cases)} test case(s) below threshold:")
        for s in failed_cases:
            print(f"    ✗ [{s['id']}] {s['name']}")

    print("\nReports written:")
    print(f"  JSON : {json_path}")
    print(f"  HTML : {html_path}")

    # Push to LangSmith
    print("\nPushing report to LangSmith...")
    push_to_langsmith(report, config)

    print(f"\nOverall: {'PASS ✓' if overall_pass else 'FAIL ✗'}")
    print(f"{sep}\n")

    sys.exit(0 if overall_pass else 1)


if __name__ == "__main__":
    main()
