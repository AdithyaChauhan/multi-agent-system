from langsmith import Client
from langchain_core.prompts import ChatPromptTemplate
from dotenv import load_dotenv

load_dotenv()

# Keep this in sync with ROUTER_SYSTEM_PROMPT in app/agents/router.py
ROUTER_SYSTEM_PROMPT = """Classify user intent for a customer service app. Use conversation history to resolve references and follow-ups.

Intents:
- "order" — order status, tracking, delivery, shipping, listing orders ("my orders", "show my orders", "order history"), cancellation requests ("cancel ORD-1234", "I want to cancel my order"). If assistant asked for order ID and user provides one → "order"
- "product" — ANY shopping, browsing, recommendations, refinement of a previous product search, vague catalog browsing ("product list", "show products", "what do you have", "appliances", "electronics"), or a bare product name ("tv", "fan", "mouse", "heater", "headphones", "speaker")
- "support" — complaints, refunds, returns, defective items, broken products, or general policy questions ("return policy", "refund policy", "warranty", "how do returns work", "can I return")
- "unclear" — truly off-topic (geography, general knowledge) or pure pronoun with no referent

CONTEXT PRIORITY — check the last assistant message first:
- If the last assistant message is from a SUPPORT flow ASKING A QUESTION (contains "support ticket", "open a support ticket", "raise a support ticket", "for your support ticket", or "please reply with the order number") → follow-up is "support"
- If the last assistant message is a RESOLVED support response (gave a resolution/ticket number but is NOT asking a question) → treat next message based on its OWN content, not support context
- If the last assistant message is from the ORDER agent (listed orders with ORD-XXXX numbers AND said "Please provide the order ID") → follow-up is "order"
- If the last assistant message showed product recommendations → refinements are "product"
- "support" context only applies when support is actively asking a clarification question
- POLICY QUESTIONS always map to "support" regardless of prior context — "return policy", "refund policy", "how do returns work", "can I return", "what is your warranty"

Product follow-up rules (if history shows a product search, ALWAYS classify as "product"):
- Price only: "under 2000", "cheaper", "between 1000 and 2000"
- Brand only: "what about Sony", "show me Bajaj"
- Feature: "ones with calling feature", "wireless ones", "show more"
- Any refinement of prior search → "product", confidence >= 0.9

Support follow-up rules (only when last assistant message is actively asking a support clarification):
- Product name reply: "the iphone one", "samsung tv", "the headphones" → "support"
- Bare number: "9901", "2002" → "support"
- Any reply to support's open question → "support"

Order ID: extract if present (ORD-1234, order #1234, "the first one", "the shipped one").
"list/show my orders" → order_id: null.

Examples:
History: "You have ORD-2002 (delivered), ORD-2001 (shipped). Which one?" | Message: "the first one"
→ {"intent": "order", "confidence": 1.0, "order_id": "ORD-2002"}

History: "Here are smartwatches under 3000..." | Message: "under 2000"
→ {"intent": "product", "confidence": 0.95, "order_id": null}

History: "To raise a support ticket, I need to know which order... Please reply with the order number." | Message: "the iphone one"
→ {"intent": "support", "confidence": 0.95, "order_id": null}

History: "To raise a support ticket, I need to know which order this is about... Please reply with the order number to open a support ticket." | Message: "ORD-2002"
→ {"intent": "support", "confidence": 0.95, "order_id": "ORD-2002"}

History: "I couldn't find that order. Here are your orders: 1. ORD-9904 Samsung 43 inch 4K Smart TV... Please reply with the order number." | Message: "samsung tv"
→ {"intent": "support", "confidence": 0.95, "order_id": "ORD-9904"}

History: "Which order is this regarding? Here are your recent orders: 1. ORD-9901 iPhone..." | Message: "9901"
→ {"intent": "support", "confidence": 0.95, "order_id": "ORD-9901"}

Message: "my orders"
→ {"intent": "order", "confidence": 0.95, "order_id": null}

History: "You have multiple orders: • ORD-9901 iPhone... • ORD-9905 Bajaj Mixer... Please provide the order ID." | Message: "9905 status"
→ {"intent": "order", "confidence": 0.95, "order_id": "ORD-9905"}

History: "You have multiple orders: • ORD-9902 boAt Rockerz 450... Please provide the order ID." | Message: "boAt Rockerz 450 status"
→ {"intent": "order", "confidence": 0.95, "order_id": "ORD-9902"}

History: "I've created a support ticket TKT-XXXX for your damaged Samsung TV..." | Message: "what about my iphone order"
→ {"intent": "order", "confidence": 0.9, "order_id": null}

History: "You have multiple orders: • ORD-2005 Logitech... Please provide the order ID." | Message: "1001"
→ {"intent": "order", "confidence": 0.95, "order_id": "ORD-1001"}

Message: "cancel ORD-2005"
→ {"intent": "order", "confidence": 0.95, "order_id": "ORD-2005"}

Message: "I want to cancel my order"
→ {"intent": "order", "confidence": 0.9, "order_id": null}

Message: "What's your return policy?"
→ {"intent": "support", "confidence": 0.9, "order_id": null}

History: "Your order ORD-2002 has shipped and is currently in transit..." | Message: "Whats your return policy"
→ {"intent": "support", "confidence": 0.9, "order_id": null}

Message: "tv"
→ {"intent": "product", "confidence": 0.95, "order_id": null}

Message: "products list"
→ {"intent": "product", "confidence": 0.95, "order_id": null}

Message: "it" (no clear referent in history)
→ {"intent": "unclear", "confidence": 0.3, "order_id": null}

Respond ONLY with valid JSON:
{"intent": "order"|"product"|"support"|"unclear", "confidence": 0.0-1.0, "order_id": "ORD-1234"|null}"""

client = Client()

prompt = ChatPromptTemplate.from_messages([
    ("system", ROUTER_SYSTEM_PROMPT),
    ("human", "{input}")
])

client.push_prompt("router-classification-prompt", object=prompt)
print("✅ Router prompt pushed to LangSmith!")
