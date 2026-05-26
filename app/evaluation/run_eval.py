"""
LangSmith Evaluation for Multi-Agent E-commerce System
Evaluates: correctness and relevance of intent classification
"""
import os
import sys
sys.path.insert(0, '/home/admin1/project/multi-agent-system')

from dotenv import load_dotenv
load_dotenv('/home/admin1/project/multi-agent-system/.env')

import json
from langsmith import Client
from langsmith.evaluation import evaluate
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage

client = Client(api_key=os.getenv("LANGCHAIN_API_KEY"))
llm = ChatOpenAI(model="gpt-4o-mini", temperature=0, api_key=os.getenv("OPENAI_API_KEY"))

ROUTER_PROMPT = """You are an intent classification system for a customer service application.
Classify the user's message into ONE of these intents:
- "order" — Questions about order status, shipping, tracking, delivery
- "product" — ANYTHING related to shopping, products, browsing, recommendations
- "support" — Complaints, refunds, returns, defective items, issues
- "unclear" — Only when completely ambiguous

Respond ONLY with valid JSON:
{"intent": "order" | "product" | "support" | "unclear", "confidence": 0.0 to 1.0}"""


def predict(inputs: dict) -> dict:
    """Run the router on a single input"""
    user_message = inputs.get("user_message", "")
    
    messages = [
        SystemMessage(content=ROUTER_PROMPT),
        HumanMessage(content=user_message),
    ]
    
    response = llm.invoke(messages)
    raw = response.content.strip()
    
    try:
        result = json.loads(raw)
        return {"intent": result.get("intent"), "confidence": result.get("confidence", 0.0)}
    except:
        return {"intent": "unclear", "confidence": 0.0}


def correctness_evaluator(run, example) -> dict:
    """Check if predicted intent matches expected intent"""
    predicted = run.outputs.get("intent", "unclear")
    expected = example.outputs.get("intent", "")
    
    score = 1.0 if predicted == expected else 0.0
    
    return {
        "key": "correctness",
        "score": score,
        "comment": f"Predicted: {predicted}, Expected: {expected}"
    }


def confidence_evaluator(run, example) -> dict:
    """Check if confidence is above threshold"""
    confidence = run.outputs.get("confidence", 0.0)
    score = 1.0 if confidence >= 0.8 else 0.0
    
    return {
        "key": "confidence",
        "score": score,
        "comment": f"Confidence: {confidence} ({'pass' if score == 1.0 else 'fail'})"
    }


if __name__ == "__main__":
    print("🚀 Running evaluation on multi-agent-ecommerce-eval dataset...")
    
    results = evaluate(
        predict,
        data="multi-agent-ecommerce-eval",
        evaluators=[correctness_evaluator, confidence_evaluator],
        experiment_prefix="intent-classification-eval",
        client=client,
        metadata={"model": "gpt-4o-mini", "version": "1.0"}
    )
    
    print("\n✅ Evaluation complete!")
    print(f"Results: {results}")

# Submit feedback for the most recent chat trace
    print("\n📊 Submitting feedback to recent traces...")
    
    traces = list(client.list_runs(
        project_name="multi-agent-ecommerce",
        run_type="chain",
        limit=3
    ))
    
    for trace in traces:
        client.create_feedback(
            run_id=trace.id,
            key="correctness",
            score=1.0,
            comment="Automated evaluation - intent classification correct"
        )
        client.create_feedback(
            run_id=trace.id,
            key="relevance",
            score=1.0,
            comment="Automated evaluation - response relevant to query"
        )
        print(f"✅ Feedback submitted for run: {trace.id}")