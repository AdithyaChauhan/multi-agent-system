"""
Create the LangSmith evaluation dataset for the multi-agent e-commerce router.

Run once to push test cases:
    python3 app/evaluation/create_dataset.py

Dataset name: multi-agent-ecommerce-eval
Input fields:  user_message, conversation_history (list of {role, content})
Output fields: intent, order_id
"""

import os
import sys

sys.path.insert(0, '/home/admin1/project/multi-agent-system')

from dotenv import load_dotenv

load_dotenv('/home/admin1/project/multi-agent-system/.env')

from langsmith import Client

client = Client(api_key=os.getenv("LANGCHAIN_API_KEY"))

DATASET_NAME = "multi-agent-ecommerce-eval"

# Each entry: {"inputs": {...}, "outputs": {...}}
# conversation_history: last 2 messages as [{role, content}] — mirrors router's [-2:] window
EXAMPLES = [
    # ── Bare product names (always product) ──────────────────────────────────
    {
        "inputs": {"user_message": "tv", "conversation_history": []},
        "outputs": {"intent": "product", "order_id": None},
    },
    {
        "inputs": {"user_message": "fan", "conversation_history": []},
        "outputs": {"intent": "product", "order_id": None},
    },
    {
        "inputs": {"user_message": "mouse", "conversation_history": []},
        "outputs": {"intent": "product", "order_id": None},
    },
    {
        "inputs": {"user_message": "heater", "conversation_history": []},
        "outputs": {"intent": "product", "order_id": None},
    },
    {
        "inputs": {"user_message": "headphones", "conversation_history": []},
        "outputs": {"intent": "product", "order_id": None},
    },
    {
        "inputs": {"user_message": "speaker", "conversation_history": []},
        "outputs": {"intent": "product", "order_id": None},
    },
    # ── Standard product queries ──────────────────────────────────────────────
    {
        "inputs": {"user_message": "show me bluetooth speakers", "conversation_history": []},
        "outputs": {"intent": "product", "order_id": None},
    },
    {
        "inputs": {"user_message": "products list", "conversation_history": []},
        "outputs": {"intent": "product", "order_id": None},
    },
    {
        "inputs": {"user_message": "what do you have", "conversation_history": []},
        "outputs": {"intent": "product", "order_id": None},
    },
    {
        "inputs": {"user_message": "I want a smartwatch under 5000", "conversation_history": []},
        "outputs": {"intent": "product", "order_id": None},
    },
    {
        "inputs": {"user_message": "show me air purifiers", "conversation_history": []},
        "outputs": {"intent": "product", "order_id": None},
    },
    # ── Product follow-ups (refinement from prior search) ────────────────────
    {
        "inputs": {
            "user_message": "under 2000",
            "conversation_history": [
                {
                    "role": "assistant",
                    "content": "Here are smartwatches under 3000: 1. boAt Wave... 2. Noise ColorFit...",
                },
            ],
        },
        "outputs": {"intent": "product", "order_id": None},
    },
    {
        "inputs": {
            "user_message": "what about Sony",
            "conversation_history": [
                {"role": "assistant", "content": "Here are headphones from boAt: 1. boAt Rockerz 450..."},
            ],
        },
        "outputs": {"intent": "product", "order_id": None},
    },
    {
        "inputs": {
            "user_message": "show more",
            "conversation_history": [
                {"role": "assistant", "content": "Here are some TVs: 1. Samsung 43\" 4K Smart TV..."},
            ],
        },
        "outputs": {"intent": "product", "order_id": None},
    },
    {
        "inputs": {
            "user_message": "wireless ones",
            "conversation_history": [
                {"role": "assistant", "content": "Here are keyboards: 1. HP Wired Keyboard..."},
            ],
        },
        "outputs": {"intent": "product", "order_id": None},
    },
    {
        "inputs": {
            "user_message": "cheaper options",
            "conversation_history": [
                {"role": "assistant", "content": "Here are air purifiers from Philips..."},
            ],
        },
        "outputs": {"intent": "product", "order_id": None},
    },
    # ── Order queries (fresh) ─────────────────────────────────────────────────
    {
        "inputs": {"user_message": "my orders", "conversation_history": []},
        "outputs": {"intent": "order", "order_id": None},
    },
    {
        "inputs": {"user_message": "show my order history", "conversation_history": []},
        "outputs": {"intent": "order", "order_id": None},
    },
    {
        "inputs": {"user_message": "track my order", "conversation_history": []},
        "outputs": {"intent": "order", "order_id": None},
    },
    {
        "inputs": {"user_message": "where is my package", "conversation_history": []},
        "outputs": {"intent": "order", "order_id": None},
    },
    {
        "inputs": {"user_message": "ORD-9901 status", "conversation_history": []},
        "outputs": {"intent": "order", "order_id": "ORD-9901"},
    },
    # ── Order follow-ups (order ID extraction after listing) ─────────────────
    {
        "inputs": {
            "user_message": "9905 status",
            "conversation_history": [
                {
                    "role": "assistant",
                    "content": "You have multiple orders: • ORD-9901 iPhone (shipped) • ORD-9905 Bajaj Mixer (processing). Please provide the order ID.",
                },
            ],
        },
        "outputs": {"intent": "order", "order_id": "ORD-9905"},
    },
    {
        "inputs": {
            "user_message": "boAt Rockerz 450 status",
            "conversation_history": [
                {
                    "role": "assistant",
                    "content": "You have multiple orders: • ORD-9902 boAt Rockerz 450 (delivered). Please provide the order ID.",
                },
            ],
        },
        "outputs": {"intent": "order", "order_id": "ORD-9902"},
    },
    {
        "inputs": {
            "user_message": "the first one",
            "conversation_history": [
                {
                    "role": "assistant",
                    "content": "You have ORD-2002 (delivered), ORD-2001 (shipped). Which one? Please provide the order ID.",
                },
            ],
        },
        "outputs": {"intent": "order", "order_id": "ORD-2002"},
    },
    {
        "inputs": {
            "user_message": "the shipped one",
            "conversation_history": [
                {
                    "role": "assistant",
                    "content": "You have ORD-2002 (delivered), ORD-2001 (shipped). Which one? Please provide the order ID.",
                },
            ],
        },
        "outputs": {"intent": "order", "order_id": "ORD-2001"},
    },
    # ── Support queries (fresh) ───────────────────────────────────────────────
    {
        "inputs": {"user_message": "my product is damaged", "conversation_history": []},
        "outputs": {"intent": "support", "order_id": None},
    },
    {
        "inputs": {"user_message": "I want a refund", "conversation_history": []},
        "outputs": {"intent": "support", "order_id": None},
    },
    {
        "inputs": {"user_message": "item arrived broken", "conversation_history": []},
        "outputs": {"intent": "support", "order_id": None},
    },
    {
        "inputs": {"user_message": "I need to return this", "conversation_history": []},
        "outputs": {"intent": "support", "order_id": None},
    },
    # ── Support follow-ups (context sticky — last assistant is asking) ────────
    {
        "inputs": {
            "user_message": "the iphone one",
            "conversation_history": [
                {
                    "role": "assistant",
                    "content": "To raise a support ticket, I need to know which order... Please reply with the order number.",
                },
            ],
        },
        "outputs": {"intent": "support", "order_id": None},
    },
    {
        "inputs": {
            "user_message": "9901",
            "conversation_history": [
                {
                    "role": "assistant",
                    "content": "Which order is this regarding? Here are your recent orders: 1. ORD-9901 iPhone... Please reply with the order number.",
                },
            ],
        },
        "outputs": {"intent": "support", "order_id": None},
    },
    {
        "inputs": {
            "user_message": "samsung tv",
            "conversation_history": [
                {
                    "role": "assistant",
                    "content": "I couldn't find that order. Here are your orders: 1. ORD-9904 Samsung 43 inch 4K Smart TV... Please reply with the order number.",
                },
            ],
        },
        "outputs": {"intent": "support", "order_id": "ORD-9904"},
    },
    # ── Post-resolution: support context released, fresh classification ───────
    {
        "inputs": {
            "user_message": "what about my iphone order",
            "conversation_history": [
                {
                    "role": "assistant",
                    "content": "I've created a support ticket TKT-0042 for your damaged Samsung TV. Is there anything else I can help you with?",
                },
            ],
        },
        "outputs": {"intent": "order", "order_id": None},
    },
    {
        "inputs": {
            "user_message": "show me air purifiers",
            "conversation_history": [
                {
                    "role": "assistant",
                    "content": "Your refund for ORD-9903 has been initiated. It should reflect in 5-7 business days.",
                },
            ],
        },
        "outputs": {"intent": "product", "order_id": None},
    },
    # ── Unclear ───────────────────────────────────────────────────────────────
    {
        "inputs": {"user_message": "it", "conversation_history": []},
        "outputs": {"intent": "unclear", "order_id": None},
    },
    {
        "inputs": {"user_message": "what is the capital of france", "conversation_history": []},
        "outputs": {"intent": "unclear", "order_id": None},
    },
]


def main():
    existing = [ds.name for ds in client.list_datasets()]
    if DATASET_NAME in existing:
        print(f"Dataset '{DATASET_NAME}' already exists — deleting and recreating.")
        ds = client.read_dataset(dataset_name=DATASET_NAME)
        client.delete_dataset(dataset_id=ds.id)

    dataset = client.create_dataset(
        dataset_name=DATASET_NAME,
        description="Router intent classification — covers bare names, history follow-ups, order/support/product paths, and edge cases.",
    )

    client.create_examples(
        inputs=[e["inputs"] for e in EXAMPLES],
        outputs=[e["outputs"] for e in EXAMPLES],
        dataset_id=dataset.id,
    )

    print(f"Created dataset '{DATASET_NAME}' with {len(EXAMPLES)} examples.")
    print(f"View at: https://smith.langchain.com/datasets/{dataset.id}")


if __name__ == "__main__":
    main()
