"""
LLM-as-a-Judge evaluation against live production traces.

Pulls recent runs from the 'multi-agent-ecommerce' LangSmith project,
scores each one on 3 metrics, and submits the scores as feedback.
Results appear immediately in the LangSmith trace view and project dashboard.

Usage:
    # Score the 20 most recent traces
    python3 app/evaluation/run_trace_eval.py

    # Score more traces
    python3 app/evaluation/run_trace_eval.py --limit 50

    # Skip traces that already have scores (default: True)
    python3 app/evaluation/run_trace_eval.py --skip-scored
"""
import os
import sys
import json
import argparse
sys.path.insert(0, '/home/admin1/project/multi-agent-system')

from dotenv import load_dotenv
load_dotenv('/home/admin1/project/multi-agent-system/.env')

from langsmith import Client
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage

client = Client(api_key=os.getenv("LANGCHAIN_API_KEY"))
llm = ChatOpenAI(model="gpt-4o-mini", temperature=0, api_key=os.getenv("OPENAI_API_KEY"))

PROJECT_NAME = "multi-agent-ecommerce"

# ── Evaluator prompts ────────────────────────────────────────────────────────

RESPONSE_RELEVANCE_PROMPT = """You are evaluating an e-commerce customer service chatbot.

User message: {user_message}
Chatbot response: {response}

Is the response on-topic and relevant to what the user asked?
- "product" query (browsing, search, recommendations) → response should show products or explain what's available
- "order" query (status, tracking) → response should show order info or ask for an order ID
- "support" query (complaint, refund, return) → response should acknowledge the issue or ask for details

Score 1.0 — response directly addresses the user's query type
Score 0.5 — response is partially relevant (asks clarification when it could answer)
Score 0.0 — response is off-topic, shows wrong content, or completely misroutes the user

Respond ONLY with valid JSON: {{"score": 0.0|0.5|1.0, "reason": "one sentence"}}"""


NO_HALLUCINATION_PROMPT = """You are checking if an e-commerce chatbot invented product information.

User message: {user_message}
Chatbot response: {response}

Check for hallucinated product details:
- Implausible prices (₹50 TV, ₹500,000 earbuds)
- Invented brand+model combinations that sound made up
- Contradictory specs (e.g. "wireless wired headphones", "4K 720p screen")
- Fabricated availability or delivery claims

Score 1.0 — no hallucinations detected, or response is not about products
Score 0.0 — response contains clearly fabricated or implausible product details

Respond ONLY with valid JSON: {{"score": 1.0|0.0, "reason": "one sentence"}}"""


ANSWER_COMPLETENESS_PROMPT = """You are evaluating whether an e-commerce chatbot fully addressed the user's query.

User message: {user_message}
Chatbot response: {response}

Did the response fully resolve what the user asked?
- Product query → did it show actual products (not just "we have many options")?
- Order query → did it give order status, or ask for the order ID if needed?
- Support query → did it raise a ticket, ask for details, or give a resolution?
- Catalog browse ("what do you have") → did it explain what's available?

Score 1.0 — query is fully addressed
Score 0.5 — partial: response is on the right track but missing key info or overly vague
Score 0.0 — response completely fails to address the query

Respond ONLY with valid JSON: {{"score": 0.0|0.5|1.0, "reason": "one sentence"}}"""


# ── Evaluator functions ──────────────────────────────────────────────────────

def _call_llm_judge(prompt: str) -> tuple[float, str]:
    """Call GPT-4o-mini as judge. Returns (score, reason)."""
    messages = [
        SystemMessage(content="You are a strict but fair evaluator. Always respond with valid JSON only."),
        HumanMessage(content=prompt),
    ]
    raw = llm.invoke(messages).content.strip()
    try:
        parsed = json.loads(raw)
        return float(parsed.get("score", 0.0)), parsed.get("reason", "")
    except (json.JSONDecodeError, ValueError):
        return 0.0, f"parse error: {raw[:80]}"


def score_run(user_message: str, response: str) -> dict[str, tuple[float, str]]:
    """Run all three LLM-as-a-Judge evaluators. Returns {key: (score, reason)}."""
    results = {}

    for key, template in [
        ("response_relevance",  RESPONSE_RELEVANCE_PROMPT),
        ("no_hallucination",    NO_HALLUCINATION_PROMPT),
        ("answer_completeness", ANSWER_COMPLETENESS_PROMPT),
    ]:
        prompt = template.format(user_message=user_message, response=response)
        score, reason = _call_llm_judge(prompt)
        results[key] = (score, reason)

    return results


# ── Run fetching ─────────────────────────────────────────────────────────────

def _get_user_message(run) -> str | None:
    """Extract the user message from a run's inputs."""
    inputs = run.inputs or {}
    return (
        inputs.get("user_message")
        or inputs.get("message")
        or inputs.get("input")
        or inputs.get("query")
    )


def _get_response(run) -> str | None:
    """Extract the chatbot response from a run's outputs."""
    outputs = run.outputs or {}
    return (
        outputs.get("final_response")
        or outputs.get("response")
        or outputs.get("output")
        or outputs.get("answer")
    )


def _already_scored(run_id: str, key: str) -> bool:
    """True if this run already has a feedback entry for the given key."""
    existing = list(client.list_feedback(run_ids=[run_id], feedback_key=[key]))
    return len(existing) > 0


# ── Main ─────────────────────────────────────────────────────────────────────

def main(limit: int = 20, skip_scored: bool = True):
    print(f"Fetching last {limit} runs from project '{PROJECT_NAME}'...")

    runs = list(client.list_runs(
        project_name=PROJECT_NAME,
        run_type="chain",
        limit=limit,
        is_root=True,
    ))

    if not runs:
        print("No runs found.")
        return

    print(f"Found {len(runs)} runs. Evaluating...\n")

    scored = 0
    skipped = 0

    for run in runs:
        user_message = _get_user_message(run)
        response = _get_response(run)

        if not user_message or not response:
            print(f"  skip {str(run.id)[:8]}  (missing input or output)")
            skipped += 1
            continue

        if skip_scored and _already_scored(run.id, "response_relevance"):
            print(f"  skip {str(run.id)[:8]}  (already scored)")
            skipped += 1
            continue

        scores = score_run(user_message, response)

        for key, (score, reason) in scores.items():
            client.create_feedback(
                run_id=run.id,
                key=key,
                score=score,
                comment=reason,
            )

        relevance, hallucination, completeness = (
            scores["response_relevance"][0],
            scores["no_hallucination"][0],
            scores["answer_completeness"][0],
        )
        print(
            f"  scored {str(run.id)[:8]}  "
            f"relevance={relevance:.1f}  "
            f"no_halluc={hallucination:.1f}  "
            f"completeness={completeness:.1f}"
            f"  | \"{user_message[:40]}\""
        )
        scored += 1

    print(f"\nDone. Scored: {scored}  Skipped: {skipped}")
    proj = client.read_project(project_name=PROJECT_NAME)
    print(f"View feedback at: https://smith.langchain.com/o/~/projects/p/{proj.id}/traces")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Score recent production traces with LLM-as-a-Judge")
    parser.add_argument("--limit", type=int, default=20, help="Number of recent traces to evaluate")
    parser.add_argument("--skip-scored", action="store_true", default=True, help="Skip runs already scored")
    parser.add_argument("--rescore", dest="skip_scored", action="store_false", help="Rescore already-scored runs")
    args = parser.parse_args()
    main(limit=args.limit, skip_scored=args.skip_scored)
