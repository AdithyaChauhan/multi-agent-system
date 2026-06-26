"""
Register feedback metric keys in LangSmith.

Run once — creates the scoring dimensions that will appear in your project's
feedback panel and in the Evaluators section of LangSmith.

    python3 app/evaluation/create_feedback_configs.py
"""

import os
import sys

sys.path.insert(0, '/home/admin1/project/multi-agent-system')

from dotenv import load_dotenv

load_dotenv('/home/admin1/project/multi-agent-system/.env')

from langsmith import Client
from langsmith.schemas import FeedbackConfig, FeedbackCategory

client = Client(api_key=os.getenv("LANGCHAIN_API_KEY"))

CONFIGS = [
    {
        "key": "response_relevance",
        "config": FeedbackConfig(
            type="continuous",
            min=0.0,
            max=1.0,
        ),
        "is_lower_score_better": False,
    },
    {
        "key": "no_hallucination",
        "config": FeedbackConfig(
            type="continuous",
            min=0.0,
            max=1.0,
        ),
        "is_lower_score_better": False,
    },
    {
        "key": "answer_completeness",
        "config": FeedbackConfig(
            type="continuous",
            min=0.0,
            max=1.0,
        ),
        "is_lower_score_better": False,
    },
    {
        "key": "routing_correct",
        "config": FeedbackConfig(
            type="categorical",
            categories=[
                FeedbackCategory(value=1.0, label="correct"),
                FeedbackCategory(value=0.0, label="wrong"),
            ],
        ),
        "is_lower_score_better": False,
    },
]


def main():
    existing_keys = {fc.feedback_key for fc in client.list_feedback_configs()}

    for cfg in CONFIGS:
        key = cfg["key"]
        if key in existing_keys:
            print(f"  skip  {key} (already exists)")
            continue
        client.create_feedback_config(
            feedback_key=key,
            feedback_config=cfg["config"],
            is_lower_score_better=cfg["is_lower_score_better"],
        )
        print(f"  created  {key}")

    print("\nDone. Feedback keys are now registered in LangSmith.")


if __name__ == "__main__":
    main()
