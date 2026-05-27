from langsmith import Client
from langchain_core.prompts import ChatPromptTemplate
import os
from dotenv import load_dotenv
load_dotenv()

client = Client()

ROUTER_SYSTEM_PROMPT = """Classify user intent for a customer service app. Use conversation history to resolve references and follow-ups.

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

prompt = ChatPromptTemplate.from_messages([
    ("system", ROUTER_SYSTEM_PROMPT),
    ("human", "{input}")
])

client.push_prompt("router-classification-prompt", object=prompt)
print("✅ Router prompt pushed to LangSmith!")
