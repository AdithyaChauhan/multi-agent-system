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
from app.tools.support_tools import lookup_support_policy
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


RESOLUTION_SYSTEM_PROMPT = """You are a customer support agent. Draft a short, helpful response.

Rules:
- Conversational chat style — NOT a formal email
- No placeholders like [Customer Name] or [Company]
- Address user as "you"
- Under 120 words
- Be specific about next steps based on the policy provided"""


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
    Falls back to scanning conversation history for ORD-XXXX if LLM missed it.
    general_query doesn't need an order — passes through with support_order=None.
    """
    user_id = state.get("user_id", "")
    issue = state.get("support_issue", {})
    order_id = issue.get("order_id")

    # general_query doesn't need an order
    if issue.get("category") == "general_query":
        return {"support_order": None, "user_orders": []}

    # Scan history if LLM didn't extract an order_id
    if not order_id:
        for msg in reversed((state.get("conversation_history") or [])[-6:]):
            match = re.search(r'\bORD-\d+\b', msg.get("content", ""), re.IGNORECASE)
            if match:
                order_id = match.group().upper()
                break

    if order_id:
        order = fetch_order_from_db(order_id, user_id)
        if order:
            logger.info(f"request_id={get_request_id()} | Support order fetched | order_id={order_id}")
            return {"support_order": order}
        logger.info(f"request_id={get_request_id()} | Order not found or not owned | order_id={order_id}")

    user_orders = fetch_user_orders(user_id)
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


# ==================== ROUTING ====================

def route_after_order_fetch(state: AgentState) -> Literal["found", "not_found"]:
    issue = state.get("support_issue", {})
    # general_query passes through even without an order
    if state.get("support_order") or issue.get("category") == "general_query":
        return "found"
    return "not_found"


def route_by_severity(state: AgentState) -> Literal["high", "low"]:
    return "high" if state.get("severity") in ("high", "medium") else "low"


# ==================== GRAPH ====================

def build_support_agent_graph():
    graph = StateGraph(AgentState)

    graph.add_node("classify_issue",          classify_issue)
    graph.add_node("fetch_order_for_support", fetch_order_for_support)
    graph.add_node("ask_for_order",           ask_for_order)
    graph.add_node("assess_severity",         assess_severity)
    graph.add_node("lookup_policy",           lookup_policy)
    graph.add_node("escalation_handler",      escalation_handler_subgraph)
    graph.add_node("draft_resolution",        draft_resolution)

    graph.set_entry_point("classify_issue")
    graph.add_edge("classify_issue", "fetch_order_for_support")

    graph.add_conditional_edges(
        "fetch_order_for_support",
        route_after_order_fetch,
        {"found": "assess_severity", "not_found": "ask_for_order"},
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
