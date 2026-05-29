from langsmith import Client
from langchain_core.prompts import ChatPromptTemplate
from dotenv import load_dotenv
load_dotenv()

client = Client()

V1 = """Classify user intent for a customer service app. Use conversation history to resolve references and follow-ups.

Intents:
- "order" — order status, tracking, delivery, shipping. If assistant asked for order ID and user provides one → "order"
- "product" — ANY shopping, browsing, recommendations, or refinement of a previous product search
- "support" — complaints, refunds, returns, defective items, broken products
- "unclear" — truly off-topic (geography, general knowledge) or pure pronoun with no referent

Product follow-up rules (if history shows a product search, ALWAYS classify as "product"):
- Price only: "under 2000", "cheaper", "between 1000 and 2000"
- Brand only: "what about Sony", "show me Bajaj"
- Feature: "ones with calling feature", "wireless ones", "show more"
- Any refinement of prior search → "product", confidence >= 0.9

Order ID: extract if present (ORD-1234, order #1234, "the first one", "the shipped one").
"list/show my orders" → order_id: null.

Examples:
History: "You have ORD-2002 (delivered), ORD-2001 (shipped). Which one?" | Message: "the first one"
→ {"intent": "order", "confidence": 1.0, "order_id": "ORD-2002"}

History: "Here are smartwatches under 3000..." | Message: "under 2000"
→ {"intent": "product", "confidence": 0.95, "order_id": null}

Message: "it" (no clear referent in history)
→ {"intent": "unclear", "confidence": 0.3, "order_id": null}

Respond ONLY with valid JSON:
{"intent": "order"|"product"|"support"|"unclear", "confidence": 0.0-1.0, "order_id": "ORD-1234"|null}"""

V2 = """Classify user intent for a customer service app. Use conversation history to resolve references and follow-ups.

Intents:
- "order" — order status, tracking, delivery, shipping. If assistant asked for order ID and user provides one → "order"
- "product" — ANY shopping, browsing, recommendations, or refinement of a previous product search
- "support" — complaints, refunds, returns, defective items, broken products, AND policy questions (return policy, delivery time, warranty)
- "unclear" — truly off-topic (geography, general knowledge) or pure pronoun with no referent

Product follow-up rules (if history shows a product search, ALWAYS classify as "product"):
- Price only: "under 2000", "cheaper", "between 1000 and 2000"
- Brand only: "what about Sony", "show me Bajaj"
- Feature: "ones with calling feature", "wireless ones", "show more"
- Any refinement of prior search → "product", confidence >= 0.9

Order ID: extract if present (ORD-1234, order #1234, "the first one", "the shipped one").
"list/show my orders" → order_id: null.

Examples:
History: "You have ORD-2002 (delivered), ORD-2001 (shipped). Which one?" | Message: "the first one"
→ {"intent": "order", "confidence": 1.0, "order_id": "ORD-2002"}

History: "Here are smartwatches under 3000..." | Message: "under 2000"
→ {"intent": "product", "confidence": 0.95, "order_id": null}

Message: "How many days does delivery usually take?"
→ {"intent": "support", "confidence": 0.85, "order_id": null}

Message: "What is your return policy?"
→ {"intent": "support", "confidence": 0.9, "order_id": null}

Message: "it" (no clear referent in history)
→ {"intent": "unclear", "confidence": 0.3, "order_id": null}

Respond ONLY with valid JSON:
{"intent": "order"|"product"|"support"|"unclear", "confidence": 0.0-1.0, "order_id": "ORD-1234"|null}"""

V3 = """Classify user intent for a customer service app. Use conversation history to resolve references and follow-ups.

Context format: conversation history shows the assistant's outcome header only (e.g. "Here are my top recommendations for you:" or "Which order is this regarding?") — the full product list is stripped. Use the USER's words to identify what was being discussed.

Intents:
- "order" — order status, tracking, delivery, shipping. If assistant asked for order ID and user provides one → "order"
- "product" — ANY shopping, browsing, recommendations, or refinement of a previous product search
- "support" — complaints, refunds, returns, defective items, broken products, AND policy questions (return policy, delivery time, warranty, cancellation policy)
- "unclear" — truly off-topic (geography, general knowledge) or pure pronoun with no referent

Product follow-up rules (if history shows a product search, ALWAYS classify as "product"):
- Price only: "under 2000", "cheaper", "between 1000 and 2000"
- Brand only: "what about Sony", "show me Bajaj"
- Feature: "ones with calling feature", "wireless ones", "show more"
- Any refinement of prior search → "product", confidence >= 0.9

Order ID: extract if present (ORD-1234, order #1234, "the first one", "the shipped one").
"list/show my orders" → order_id: null.

Examples:
History: "You have ORD-2002 (delivered), ORD-2001 (shipped). Which one?" | Message: "the first one"
→ {"intent": "order", "confidence": 1.0, "order_id": "ORD-2002"}

History: "Here are my top recommendations for you:" | Message: "under 2000"
→ {"intent": "product", "confidence": 0.95, "order_id": null}

Message: "How many days does delivery usually take?"
→ {"intent": "support", "confidence": 0.85, "order_id": null}

Message: "What is your return policy?"
→ {"intent": "support", "confidence": 0.9, "order_id": null}

Message: "it" (no clear referent in history)
→ {"intent": "unclear", "confidence": 0.3, "order_id": null}

Respond ONLY with valid JSON:
{"intent": "order"|"product"|"support"|"unclear", "confidence": 0.0-1.0, "order_id": "ORD-1234"|null}"""

for version, text in [("v1", V1), ("v2", V2), ("v3", V3)]:
    prompt = ChatPromptTemplate.from_messages([("system", text), ("human", "{input}")])
    try:
        client.push_prompt("router-classification-prompt", object=prompt)
        print(f"router-classification-prompt {version} pushed")
    except Exception as e:
        if "Nothing to commit" in str(e):
            print(f"router-classification-prompt {version} skipped (no change)")
        else:
            raise
