"""
LangSmith Evaluation — Multi-Agent E-commerce Router

Evaluates router intent classification against the dataset created by create_dataset.py.
The target is the app's own router node (app.agents.router.classify), so the evaluation
always measures the prompt and schema that run in production.

Run:
    python app/evaluation/run_eval.py

Evaluators
----------
- intent_correctness   : 1.0 if predicted intent == expected intent, else 0.0
- order_id_correctness : 1.0/0.0 only scored when the example expects a non-null order_id
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from langsmith import Client  # noqa: E402
from langsmith.evaluation import evaluate, EvaluationResult  # noqa: E402

from app.agents.router import classify  # noqa: E402
from app.core.config import GROQ_MODEL  # noqa: E402

client = Client(api_key=os.getenv("LANGCHAIN_API_KEY"))

DATASET_NAME = "multi-agent-ecommerce-eval"


def predict(inputs: dict) -> dict:
    """Run the app's router node on one dataset example (anonymous user, no order list)."""
    decision = classify(
        {
            "user_message": inputs.get("user_message", ""),
            "conversation_history": inputs.get("conversation_history", []),
            "user_id": "anon-eval",
        }
    )
    return {"intent": decision["intent"], "order_id": decision["order_id"]}


# ── Evaluators ──────────────────────────────────────────────────────────────


def intent_correctness(run, example) -> dict:
    predicted = run.outputs.get("intent", "unclear")
    expected = example.outputs.get("intent", "")
    score = 1.0 if predicted == expected else 0.0
    return {
        "key": "intent_correctness",
        "score": score,
        "comment": f"predicted={predicted}  expected={expected}",
    }


def order_id_correctness(run, example) -> EvaluationResult:
    expected_id = example.outputs.get("order_id")
    if not expected_id:
        # LangSmith requires a return value — score=None marks it as "not evaluated"
        return EvaluationResult(key="order_id_correctness", score=None, comment="n/a — no order_id expected")

    predicted_id = run.outputs.get("order_id")
    score = 1.0 if predicted_id == expected_id else 0.0
    return EvaluationResult(
        key="order_id_correctness",
        score=score,
        comment=f"predicted={predicted_id}  expected={expected_id}",
    )


# ── Entry point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"Running evaluation on dataset: {DATASET_NAME}")

    results = evaluate(
        predict,
        data=DATASET_NAME,
        evaluators=[intent_correctness, order_id_correctness],
        experiment_prefix="router-intent-eval",
        client=client,
        metadata={"model": GROQ_MODEL},
    )

    print("\nEvaluation complete.")
    print(f"View results in LangSmith under Datasets & Experiments → {DATASET_NAME}")
