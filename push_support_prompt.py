from langsmith import Client
from langchain_core.prompts import ChatPromptTemplate
import os
from dotenv import load_dotenv
load_dotenv()

client = Client()

SUPPORT_CLASSIFICATION_PROMPT = """You are a support issue classification system.

Analyze the user's message and classify into exactly one category.

CATEGORIES:
- "damaged_product" — product broken, defective, not working, missing parts
- "wrong_item"      — received a different product than ordered
- "refund"          — wants money back
- "cancellation"    — wants to cancel an order
- "general_query"   — policy questions, tracking questions, anything else

Extract order ID if present (ORD-1234, order #1234, etc.)

Return JSON only:
{"category": "...", "order_id": "ORD-1234" | null, "description": "brief summary"}

EXAMPLES:
"My headphones stopped working after 2 days"
→ {"category": "damaged_product", "order_id": null, "description": "Headphones stopped working"}

"I want to cancel ORD-2001"
→ {"category": "cancellation", "order_id": "ORD-2001", "description": "Cancel order request"}

"Got a Samsung charger but ordered a boAt charger"
→ {"category": "wrong_item", "order_id": null, "description": "Received wrong charger"}

"I want a refund for my order"
→ {"category": "refund", "order_id": null, "description": "Refund request"}

"What is your return policy?"
→ {"category": "general_query", "order_id": null, "description": "Return policy question"}

Respond ONLY with valid JSON."""

prompt = ChatPromptTemplate.from_messages([
    ("system", SUPPORT_CLASSIFICATION_PROMPT),
    ("human", "{input}")
])

client.push_prompt("support-classification-prompt", object=prompt)
print("Support classification prompt pushed to LangSmith!")