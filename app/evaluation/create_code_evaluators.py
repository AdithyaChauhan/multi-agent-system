"""
Create LangSmith Code Evaluators for the multi-agent e-commerce chatbot.

These replace the broken LLM-as-a-Judge evaluator (which fails because
gpt-4o-mini routes through AsyncResponses.create() in LangSmith's runtime,
which doesn't accept the 'seed' kwarg langchain-openai passes).

Code evaluators run pure Python — no LLM calls, no version conflicts.

Run once:
    python3 app/evaluation/create_code_evaluators.py
"""
import os
import sys
sys.path.insert(0, '/home/admin1/project/multi-agent-system')

from dotenv import load_dotenv
load_dotenv('/home/admin1/project/multi-agent-system/.env')

from langsmith import Client

client = Client(api_key=os.getenv("LANGCHAIN_API_KEY"))
PROJECT_NAME = "multi-agent-ecommerce"
OLD_RULE_ID  = "91965491-46be-4f78-a0db-296c4261fbe0"  # the broken LLM evaluator

# ── Evaluator code strings ───────────────────────────────────────────────────

INTENT_SERVED_CODE = '''
def perform_eval(run):
    """Did the response match the user's intent?"""
    inputs  = run.get("inputs", {})  if isinstance(run, dict) else (run.inputs  or {})
    outputs = run.get("outputs", {}) if isinstance(run, dict) else (run.outputs or {})

    response = (outputs.get("final_response") or "").lower()
    intent   = (outputs.get("intent") or "").lower()

    if not response or len(response.strip()) < 5:
        return {"score": 0.0, "comment": "empty response"}

    if intent == "product":
        # Product response should list items, prices, or catalog info
        keywords = ["\\u20b9", "rs.", "1.", "2.", "3.", "found", "here are",
                    "available", "brand", "specifications", "price", "rating"]
        served = any(kw in response for kw in keywords)
        return {"score": 1.0 if served else 0.5,
                "comment": f"product intent — items shown: {served}"}

    if intent == "order":
        # Order response should mention ORD-IDs or ask for one
        served = ("ord-" in response or "order id" in response
                  or "order number" in response or "your orders" in response
                  or "no orders" in response)
        return {"score": 1.0 if served else 0.5,
                "comment": f"order intent — order info present: {served}"}

    if intent == "support":
        # Support response should acknowledge the issue or ask for order details
        keywords = ["ticket", "sorry", "understand", "order", "help",
                    "issue", "concern", "refund", "return", "damaged"]
        served = any(kw in response for kw in keywords)
        return {"score": 1.0 if served else 0.5,
                "comment": f"support intent — issue acknowledged: {served}"}

    if intent == "unclear":
        # Unclear → clarification response expected
        keywords = ["help", "assist", "order", "product", "support", "looking"]
        served = any(kw in response for kw in keywords)
        return {"score": 1.0 if served else 0.0,
                "comment": f"unclear intent — clarification given: {served}"}

    return {"score": None, "comment": f"unrecognised intent: {intent}"}
'''

RESPONSE_NON_EMPTY_CODE = '''
def perform_eval(run):
    """Did the chatbot return a meaningful (non-empty) response?"""
    outputs  = run.get("outputs", {}) if isinstance(run, dict) else (run.outputs or {})
    response = (outputs.get("final_response") or "").strip()

    if not response:
        return {"score": 0.0, "comment": "no final_response in output"}
    if len(response) < 10:
        return {"score": 0.0, "comment": f"too short: {repr(response)}"}

    return {"score": 1.0, "comment": f"len={len(response)}"}
'''

NO_AUTH_WALL_FOR_PRODUCTS_CODE = '''
def perform_eval(run):
    """Anonymous users should never see a sign-in wall for product queries."""
    inputs  = run.get("inputs",  {}) if isinstance(run, dict) else (run.inputs  or {})
    outputs = run.get("outputs", {}) if isinstance(run, dict) else (run.outputs or {})

    user_id  = (inputs.get("user_id") or "")
    intent   = (outputs.get("intent") or "").lower()
    response = (outputs.get("final_response") or "").lower()

    is_anon = user_id.startswith("anon-") or not user_id

    if intent != "product" or not is_anon:
        return {"score": None, "comment": "n/a — not an anonymous product query"}

    auth_wall = any(kw in response for kw in ["sign in", "log in", "login", "sign up", "sign-in"])
    return {
        "score": 0.0 if auth_wall else 1.0,
        "comment": "auth wall shown" if auth_wall else "no auth wall",
    }
'''

# ── Entry point ──────────────────────────────────────────────────────────────

def main():
    proj = client.read_project(project_name=PROJECT_NAME)

    # Delete the old broken LLM evaluator rule
    try:
        client.request_with_retries("DELETE", f"/api/v1/runs/rules/{OLD_RULE_ID}", request_kwargs={})
        print(f"Deleted old LLM evaluator rule ({OLD_RULE_ID})")
    except Exception as e:
        print(f"Could not delete old rule (may already be gone): {e}")

    # LangSmith allows only 1 evaluator per rule — create one rule each
    import json
    evaluators = [
        ("intent_served",             INTENT_SERVED_CODE,             "intent_served"),
        ("response_non_empty",        RESPONSE_NON_EMPTY_CODE,        "response_non_empty"),
        ("no_auth_wall_for_products", NO_AUTH_WALL_FOR_PRODUCTS_CODE, "no_auth_wall_for_products"),
    ]

    for name, code, feedback_key in evaluators:
        payload = {
            "display_name": name,
            "session_id": str(proj.id),
            "sampling_rate": 1.0,
            "filter": "",
            "trace_filter": "",
            "code_evaluators": [{"name": name, "code": code, "feedback_key": feedback_key}],
        }
        resp = client.request_with_retries("POST", "/api/v1/runs/rules", request_kwargs={"json": payload})
        result = json.loads(resp.text)
        print(f"  created  {name}  (rule {result['id']})")

    print(f"\nEvaluators are live — scoring new traces automatically.")
    print(f"View at: https://smith.langchain.com/o/~/projects/p/{proj.id}/traces")


if __name__ == "__main__":
    main()
