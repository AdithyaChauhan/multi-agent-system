import json
import os
import re
from typing import Literal
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from langgraph.graph import StateGraph, END
from dotenv import load_dotenv

from app.agents.state import AgentState
from app.agents.support_agent_subgraph import escalation_handler_subgraph
from app.tools.support_tools import lookup_support_policy, get_user_ticket_history
from app.tools.order_tools import fetch_order_from_db, fetch_user_orders
from app.core.logger import get_logger, get_request_id
from app.core.prompt_loader import load_prompt, PROMPT_VERSIONS

load_dotenv()

logger = get_logger("app.agents.support_agent")

llm = ChatOpenAI(
    model="gpt-4o-mini",
    temperature=0,
    api_key=os.getenv("OPENAI_API_KEY")
)

# Order value threshold (in rupees) for HIGH vs MEDIUM severity
HIGH_VALUE_THRESHOLD = 10000

# Cancellation eligibility — status strings verbatim from the DB
_NON_CANCELLABLE = {'shipped', 'in transit', 'out_for_delivery', 'delivered'}
_CANCELLATION_PHRASES = {
    'shipped':          'has already shipped',
    'in transit':       'is already in transit',
    'out_for_delivery': 'is out for delivery',
    'delivered':        'has already been delivered',
}

CLASSIFICATION_SYSTEM_PROMPT = """You are a support issue classification system.

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


RESOLUTION_SYSTEM_PROMPT = """You are a customer support agent for an online store. Draft a short, helpful response.

Store policies:
- Returns: 30-day return window, item must be unused and in original packaging
- Refunds: processed within 5-7 business days after the return is received
- Delivery: standard 3-7 business days, express 1-2 business days
- Cancellations: only possible before the order has shipped
- Warranty: 1 year for electronics, 6 months for accessories

Rules:
- Answer policy questions directly using the store policies above — do NOT ask the user for more details
- Conversational chat style, not a formal email
- No placeholders like [Customer Name] or [Company]
- Address the user as "you"
- Under 100 words"""


# ==================== NODES ====================

def classify_issue(state: AgentState) -> dict:
    """LLM node — classifies the support issue."""
    user_message = state.get("user_message", "")
    conversation_history = state.get("conversation_history", [])

    version = PROMPT_VERSIONS.get("support-classification-prompt", "latest")
    system_prompt, commit_hash = load_prompt("support-classification-prompt", version)
    if not system_prompt:
        system_prompt = CLASSIFICATION_SYSTEM_PROMPT
        commit_hash = "fallback"

    # Only user turns needed for classification — assistant replies are large ticket/product dumps
    history_context = ""
    if conversation_history:
        user_turns = [m for m in conversation_history if m["role"] == "user"][-2:]
        if user_turns:
            history_context = "\n".join([f"User: {m['content']}" for m in user_turns])

    full_prompt = (
        f"Recent conversation:\n{history_context}\n\nCurrent message: {user_message}\n\n"
        f"Classify the support issue using context from the conversation."
        if history_context else user_message
    )

    response = llm.invoke(
        [SystemMessage(content=system_prompt), HumanMessage(content=full_prompt)],
        config={"metadata": {"prompt_name": "support-classification-prompt", "prompt_version": commit_hash}}
    )
    raw = response.content.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()

    try:
        issue = json.loads(raw)
    except json.JSONDecodeError:
        issue = {"category": "general_query", "order_id": None, "description": user_message[:200]}

    # Fallback: use router-extracted order_id if LLM missed it
    if not issue.get("order_id") and state.get("order_id"):
        issue["order_id"] = state.get("order_id")

    logger.info(
        f"request_id={get_request_id()} | "
        f"Classified | category={issue.get('category')} | order_id={issue.get('order_id')}"
    )
    return {"support_issue": issue}


def fetch_order_for_support(state: AgentState) -> dict:
    """
    Fetches and validates the order the user is raising a ticket about.
    Resolution priority:
      1. Explicit ORD-XXXX in the current message
      2. Product-name keywords from the current message matched against user's orders
      3. LLM/router-extracted order_id (may be from history — normalised to ORD-XXXX)
      4. Single open support ticket
      5. Single user order (auto-select)
      6. Ask the user
    general_query doesn't need an order — passes through with support_order=None.
    """
    user_id = state.get("user_id", "")
    user_message = state.get("user_message", "")
    issue = state.get("support_issue", {})
    order_id = issue.get("order_id")

    # general_query doesn't need an order
    if issue.get("category") == "general_query":
        return {"support_order": None, "user_orders": []}

    # Step 1: explicit ORD-XXXX in the current message takes top priority
    msg_explicit = re.search(r'\b(ORD-?\d{4})\b', user_message, re.IGNORECASE)
    if msg_explicit:
        explicit_id = msg_explicit.group(1).upper()
        if not explicit_id.startswith("ORD-"):
            explicit_id = f"ORD-{explicit_id[3:]}"
        order = fetch_order_from_db(explicit_id, user_id)
        if order:
            logger.info(f"request_id={get_request_id()} | Support order fetched from message | order_id={explicit_id}")
            return {"support_order": order}

    # Fetch once for steps 2, 5, and the fallback listing
    user_orders = fetch_user_orders(user_id)

    # Step 2: product-name matching — more reliable than history-sourced order_id
    if user_orders and user_message:
        msg_lower = user_message.lower()
        for o in user_orders:
            words = [w for w in re.findall(r'\w+', o.get('product_name', '').lower()) if len(w) > 3]
            if words and any(w in msg_lower for w in words):
                order = fetch_order_from_db(o['order_id'], user_id)
                if order:
                    logger.info(f"request_id={get_request_id()} | Order matched by product name | order_id={o['order_id']}")
                    return {"support_order": order}

    # Step 3: LLM/router-extracted order_id (may come from history context)
    if order_id:
        # Normalise bare 4-digit IDs (e.g. "9903" extracted from history text → "ORD-9903")
        if re.match(r'^\d{4}$', str(order_id).strip()):
            order_id = f"ORD-{order_id.strip()}"
        order = fetch_order_from_db(order_id, user_id)
        if order:
            logger.info(f"request_id={get_request_id()} | Support order fetched | order_id={order_id}")
            return {"support_order": order}
        logger.info(f"request_id={get_request_id()} | Order not found or not owned | order_id={order_id}")

    # Step 4: single open ticket
    open_tickets = [
        t for t in get_user_ticket_history(user_id, limit=10)
        if t.get("status") in ("open", "in_progress") and t.get("order_id")
    ]
    if len(open_tickets) == 1:
        tid = open_tickets[0]["order_id"]
        order = fetch_order_from_db(tid, user_id)
        if order:
            logger.info(f"request_id={get_request_id()} | Resolved order from open ticket | order_id={tid}")
            return {"support_order": order}

    # Step 5: single user order — auto-select
    if len(user_orders) == 1:
        tid = user_orders[0]["order_id"]
        order = fetch_order_from_db(tid, user_id)
        if order:
            logger.info(f"request_id={get_request_id()} | Resolved order from single user order | order_id={tid}")
            return {"support_order": order}

    logger.info(f"request_id={get_request_id()} | No valid order | user has {len(user_orders)} orders")
    return {"support_order": None, "user_orders": user_orders}


def ask_for_order(state: AgentState) -> dict:
    """Asks which order the issue is about, listing the user's recent orders."""
    user_orders = state.get("user_orders") or []
    issue = state.get("support_issue", {})
    had_invalid_id = bool(issue.get("order_id"))

    if not user_orders:
        msg = (
            "I'd be happy to help! To raise a support ticket I need the order number.\n\n"
            "I couldn't find any orders on your account. "
            "Please provide the order number (e.g. ORD-1234)."
        )
    else:
        order_lines = "\n".join([
            f"{i+1}. **{o['order_id']}** — {o['product_name'][:55]} ({o['status'].title()})"
            for i, o in enumerate(user_orders[:5])
        ])
        if had_invalid_id:
            prefix = f"I couldn't find order **{issue['order_id']}** on your account.\n\nHere are your recent orders:\n\n"
        else:
            prefix = "Which order is this regarding? Here are your recent orders:\n\n"
        msg = f"{prefix}{order_lines}\n\nPlease reply with the order number."

    logger.info(f"request_id={get_request_id()} | Asking user for order")
    return {"final_response": msg}


def assess_severity(state: AgentState) -> dict:
    """
    Severity rules:
    - general_query / cancellation → always LOW
    - damaged_product / wrong_item / refund + order_value >= 10000 → HIGH
    - damaged_product / wrong_item / refund + order_value < 10000  → MEDIUM
    """
    issue = state.get("support_issue", {})
    support_order = state.get("support_order") or {}
    category = issue.get("category", "general_query")
    order_value = support_order.get("order_value", 0) or 0

    if category in ("damaged_product", "wrong_item", "refund"):
        severity = "high" if order_value >= HIGH_VALUE_THRESHOLD else "medium"
    elif category == "cancellation":
        severity = "medium"
    else:
        severity = "low"

    logger.info(
        f"request_id={get_request_id()} | "
        f"Severity | category={category} | order_value={order_value} | severity={severity}"
    )
    return {"severity": severity}


def lookup_policy(state: AgentState) -> dict:
    issue = state.get("support_issue", {})
    severity = state.get("severity", "medium")
    category = issue.get("category", "general_query")
    policy = lookup_support_policy(category, severity)
    logger.info(f"request_id={get_request_id()} | Policy | category={category} | severity={severity}")
    return {"policy": policy}


def draft_resolution(state: AgentState) -> dict:
    """LLM node — drafts a resolution for LOW severity (no ticket created)."""
    issue = state.get("support_issue", {})
    support_order = state.get("support_order") or {}
    policy = state.get("policy", {})

    order_context = (
        f"Order: {support_order['order_id']} — {support_order['product_name']}\n"
        if support_order.get("order_id") else ""
    )

    prompt = (
        f"{order_context}"
        f"Issue: {issue.get('description')}\n"
        f"Category: {issue.get('category')}\n"
        f"Policy: Response time {policy.get('response_time', '48 hours')}\n\n"
        f"Draft a helpful response. No ticket will be created for this issue."
    )

    version = PROMPT_VERSIONS.get("support-resolution-prompt", "latest")
    resolution_prompt, commit_hash = load_prompt("support-resolution-prompt", version)
    if not resolution_prompt:
        resolution_prompt = RESOLUTION_SYSTEM_PROMPT
        commit_hash = "fallback"

    response = llm.invoke(
        [SystemMessage(content=resolution_prompt), HumanMessage(content=prompt)],
        config={"metadata": {"prompt_name": "support-resolution-prompt", "prompt_version": commit_hash}}
    )
    logger.info(f"request_id={get_request_id()} | Drafted LOW-severity resolution")
    return {"final_response": response.content.strip()}


def check_cancellation_eligibility(state: AgentState) -> dict:
    """
    Guard node — runs only when category='cancellation' and support_order is resolved.
    Refuses inline (no ticket) for shipped/in-transit/out_for_delivery/delivered/canceled.
    Returns {} for placed/processing so the normal cancellation-ticket flow continues.
    """
    support_order = state.get("support_order") or {}
    order_id     = support_order.get("order_id", "")
    product_name = support_order.get("product_name", "your product")
    status       = (support_order.get("status") or "").lower()

    logger.info(
        f"request_id={get_request_id()} | "
        f"Cancellation eligibility | order_id={order_id} | status={status}"
    )

    if status == 'canceled':
        return {
            "final_response": (
                f"Order **{order_id}** is already cancelled — nothing more needed on it. "
                f"Anything else I can help with?"
            )
        }

    if status in _NON_CANCELLABLE:
        phrase = _CANCELLATION_PHRASES.get(status, 'can no longer be cancelled')
        return {
            "final_response": (
                f"Order **{order_id}** ({product_name}) {phrase}, so it can't be cancelled now. "
                f"Once it arrives you can return it within 30 days if it's unused and in "
                f"original packaging — want me to help start a return instead?"
            )
        }

    # 'placed' or 'processing' — eligible, proceed to existing cancellation-ticket flow
    return {}


# ==================== ROUTING ====================

def route_after_order_fetch(state: AgentState) -> Literal["found", "not_found", "cancellation_check"]:
    issue         = state.get("support_issue", {})
    support_order = state.get("support_order")
    category      = issue.get("category")

    # Resolved order + cancellation → eligibility guard (must run before dup-check)
    if support_order and category == "cancellation":
        return "cancellation_check"
    # general_query passes through without an order; all other resolved orders proceed
    if support_order or category == "general_query":
        return "found"
    return "not_found"


def route_by_severity(state: AgentState) -> Literal["high", "low"]:
    return "high" if state.get("severity") in ("high", "medium") else "low"


# ==================== GRAPH ====================

def build_support_agent_graph():
    graph = StateGraph(AgentState)

    graph.add_node("classify_issue",                 classify_issue)
    graph.add_node("fetch_order_for_support",        fetch_order_for_support)
    graph.add_node("ask_for_order",                  ask_for_order)
    graph.add_node("check_cancellation_eligibility", check_cancellation_eligibility)
    graph.add_node("assess_severity",                assess_severity)
    graph.add_node("lookup_policy",                  lookup_policy)
    graph.add_node("escalation_handler",             escalation_handler_subgraph)
    graph.add_node("draft_resolution",               draft_resolution)

    graph.set_entry_point("classify_issue")
    graph.add_edge("classify_issue", "fetch_order_for_support")

    graph.add_conditional_edges(
        "fetch_order_for_support",
        route_after_order_fetch,
        {"found": "assess_severity", "not_found": "ask_for_order", "cancellation_check": "check_cancellation_eligibility"},
    )

    graph.add_conditional_edges(
        "check_cancellation_eligibility",
        lambda s: "refused" if s.get("final_response") else "proceed",
        {"refused": END, "proceed": "assess_severity"},
    )

    graph.add_edge("assess_severity", "lookup_policy")

    graph.add_conditional_edges(
        "lookup_policy",
        route_by_severity,
        {"high": "escalation_handler", "low": "draft_resolution"},
    )

    graph.add_edge("escalation_handler", END)
    graph.add_edge("draft_resolution",   END)
    graph.add_edge("ask_for_order",      END)

    return graph.compile()


support_agent_graph = build_support_agent_graph()
