"""
LangSmith Evaluation — Multi-Agent E-commerce Router

Evaluates router intent classification against the dataset created by create_dataset.py.

Run:
    python3 app/evaluation/run_eval.py

Evaluators
----------
- intent_correctness   : 1.0 if predicted intent == expected intent, else 0.0
- confidence_check     : 1.0 if confidence >= 0.7 (router threshold), else 0.0
- order_id_correctness : 1.0/0.0 only scored when the example expects a non-null order_id
"""
import os
import sys
import json
sys.path.insert(0, '/home/admin1/project/multi-agent-system')

from dotenv import load_dotenv
load_dotenv('/home/admin1/project/multi-agent-system/.env')

from langsmith import Client
from langsmith.evaluation import evaluate, EvaluationResult
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage

client = Client(api_key=os.getenv("LANGCHAIN_API_KEY"))
llm = ChatOpenAI(model="gpt-4o-mini", temperature=0, api_key=os.getenv("OPENAI_API_KEY"))

DATASET_NAME = "multi-agent-ecommerce-eval"
CONFIDENCE_THRESHOLD = 0.7  # matches route_after_classification in router.py

# Fallback prompt — used only if LangSmith hub pull fails
from app.agents.router import ROUTER_SYSTEM_PROMPT as _FALLBACK_PROMPT


def _load_router_prompt() -> str:
    """Pull the live router prompt from LangSmith hub, fall back to hardcoded."""
    try:
        from app.core.prompt_loader import load_prompt
        text, _ = load_prompt("router-classification-prompt", "latest")
        if text:
            return text
    except Exception:
        pass
    return _FALLBACK_PROMPT


ROUTER_PROMPT = _load_router_prompt()


def predict(inputs: dict) -> dict:
    """
    Run the router on a single dataset example.

    Mirrors classify_intent_and_extract() in router.py:
    - Formats up to 2 history messages as context
    - Calls GPT-4o-mini with the live LangSmith hub prompt
    - Returns intent, confidence, order_id
    """
    user_message = inputs.get("user_message", "")
    conversation_history = inputs.get("conversation_history", [])

    history_context = ""
    if conversation_history:
        recent = conversation_history[-2:]
        history_context = "\n".join(
            f"{msg['role'].title()}: {msg['content']}" for msg in recent
        )

    prompt_text = user_message
    if history_context:
        prompt_text = f"Recent conversation:\n{history_context}\n\nCurrent message: {user_message}"

    messages = [
        SystemMessage(content=ROUTER_PROMPT),
        HumanMessage(content=prompt_text),
    ]

    response = llm.invoke(messages)
    raw = response.content.strip()

    try:
        parsed = json.loads(raw)
        return {
            "intent":     parsed.get("intent", "unclear"),
            "confidence": float(parsed.get("confidence", 0.0)),
            "order_id":   parsed.get("order_id"),
        }
    except (json.JSONDecodeError, ValueError):
        return {"intent": "unclear", "confidence": 0.0, "order_id": None}


# ── Evaluators ──────────────────────────────────────────────────────────────

def intent_correctness(run, example) -> dict:
    predicted = run.outputs.get("intent", "unclear")
    expected  = example.outputs.get("intent", "")
    score = 1.0 if predicted == expected else 0.0
    return {
        "key":     "intent_correctness",
        "score":   score,
        "comment": f"predicted={predicted}  expected={expected}",
    }


def confidence_check(run, _example) -> dict:
    confidence = run.outputs.get("confidence", 0.0)
    score = 1.0 if confidence >= CONFIDENCE_THRESHOLD else 0.0
    return {
        "key":     "confidence_check",
        "score":   score,
        "comment": f"confidence={confidence:.2f}  threshold={CONFIDENCE_THRESHOLD}",
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
    print(f"Router prompt source: {'LangSmith hub' if ROUTER_PROMPT != _FALLBACK_PROMPT else 'fallback (hardcoded)'}\n")

    results = evaluate(
        predict,
        data=DATASET_NAME,
        evaluators=[intent_correctness, confidence_check, order_id_correctness],
        experiment_prefix="router-intent-eval",
        client=client,
        metadata={"model": "gpt-4o-mini", "confidence_threshold": CONFIDENCE_THRESHOLD},
    )

    print("\nEvaluation complete.")
    print(f"View results in LangSmith under Datasets & Experiments → {DATASET_NAME}")
