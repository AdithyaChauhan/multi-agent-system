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

llm = ChatOpenAI(model="gpt-4o-mini", temperature=0, api_key=os.getenv("OPENAI_API_KEY"))


CLASSIFICATION_SYSTEM_PROMPT = """You are a support issue classification system.

Analyze the user's message and extract:
1. Issue category
2. Order ID if mentioned
3. Brief description

ISSUE CATEGORIES:
- "defective_product": Product doesn't work, broken, faulty
- "wrong_item": Received wrong product
- "damaged_delivery": Package arrived damaged
- "missing_parts": Product incomplete, missing accessories
- "refund_request": Want money back
- "other": Anything else

Extract order ID if present (ORD-1234, order #1234, etc.)

Return JSON:
{
  "category": "defective_product" | "wrong_item" | "damaged_delivery" | "missing_parts" | "refund_request" | "other",
  "order_id": "ORD-1234" or null,
  "description": "brief summary of the issue"
}

EXAMPLES:

Input: "My product arrived broken"
Output: {"category": "damaged_delivery", "order_id": null, "description": "Product arrived broken"}

Input: "I want a refund for order ORD-2002"
Output: {"category": "refund_request", "order_id": "ORD-2002", "description": "Refund request"}

Input: "Battery leaked from toy, child got chemical burn"
Output: {"category": "defective_product", "order_id": null, "description": "Defective toy caused chemical burn to child"}

Respond ONLY with valid JSON."""


RESOLUTION_SYSTEM_PROMPT = """You are a customer support agent drafting resolutions for low-severity issues.

Given:
- Issue description
- Category
- Company policy

Draft a helpful, empathetic response that:
1. Acknowledges the issue
2. Provides solution based on policy
3. Offers next steps
4. Maintains professional, friendly tone

Keep response under 150 words. Be specific and actionable.
IMPORTANT:
- Respond conversationally like a chat message, NOT as a formal email
- Do NOT use placeholders like [Customer's Name], [Your Name], [Company Name]
- Do NOT write Subject lines or sign-offs
- Address the user directly as "you"
- Be direct and helpful"""

# Product categories that carry higher physical risk
HIGH_RISK_PRODUCT_KEYWORDS = [
    "baby",
    "infant",
    "toddler",
    "child",
    "toy",
    "heater",
    "iron",
    "kettle",
    "fryer",
    "blender",
    "pressure",
    "gas",
    "electric",
    "induction",
]


# ==================== MAIN FLOW NODES ====================


def classify_issue(state: AgentState) -> dict:
    """LLM node — classifies the support issue from message + conversation history."""
    user_message = state.get("user_message", "")
    conversation_history = state.get("conversation_history", [])

    version = PROMPT_VERSIONS.get("support-classification-prompt", "latest")
    system_prompt, commit_hash = load_prompt("support-classification-prompt", version)

    if not system_prompt:
        logger.warning(f"request_id={get_request_id()} | Using fallback support prompt")
        system_prompt = CLASSIFICATION_SYSTEM_PROMPT
        commit_hash = "fallback"

    history_context = ""
    if conversation_history:
        recent = conversation_history[-4:]
        history_context = "\n".join([f"{msg['role'].title()}: {msg['content']}" for msg in recent])

    if history_context:
        full_prompt = (
            f"Recent conversation:\n{history_context}\n\n"
            f"Current message: {user_message}\n\n"
            f"Classify the support issue using context from the conversation."
        )
    else:
        full_prompt = user_message

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=full_prompt),
    ]

    response = llm.invoke(
        messages, config={"metadata": {"prompt_name": "support-classification-prompt", "prompt_version": commit_hash}}
    )
    raw = response.content.strip()

    if raw.startswith("```"):
        raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()

    try:
        issue = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error(f"request_id={get_request_id()} | Parse error | {str(e)}")
        issue = {"category": "other", "order_id": None, "description": user_message[:200]}

    # Also check router-extracted order_id as fallback
    if not issue.get("order_id") and state.get("order_id"):
        issue["order_id"] = state.get("order_id")

    logger.info(
        f"request_id={get_request_id()} | "
        f"Classified issue | category={issue.get('category')} | order_id={issue.get('order_id')}"
    )

    return {"support_issue": issue}


def fetch_order_for_support(state: AgentState) -> dict:
    """
    Fetches the order the support ticket is about.
    - If order_id found in issue: validate it belongs to this user
    - If not found: load user's order list so ask_for_order can display it
    """
    user_id = state.get("user_id", "")
    issue = state.get("support_issue", {})
    order_id = issue.get("order_id")

    # Also check conversation history for ORD-XXXX pattern if LLM missed it
    if not order_id:
        conversation_history = state.get("conversation_history", [])
        for msg in reversed(conversation_history[-6:]):
            match = re.search(r'\bORD-\d+\b', msg.get("content", ""), re.IGNORECASE)
            if match:
                order_id = match.group().upper()
                break

    if order_id:
        order = fetch_order_from_db(order_id, user_id)
        if order:
            logger.info(f"request_id={get_request_id()} | Support order fetched | order_id={order_id}")
            return {"support_order": order}
        else:
            logger.info(f"request_id={get_request_id()} | Order not found or not owned | order_id={order_id}")

    # No valid order found — fetch user's orders so ask_for_order can list them
    user_orders = fetch_user_orders(user_id)
    logger.info(f"request_id={get_request_id()} | No order_id | user has {len(user_orders)} orders")
    return {"support_order": None, "user_orders": user_orders}


def ask_for_order(state: AgentState) -> dict:
    """
    Asks the user which order they're raising a ticket for.
    Shows their recent orders if available.
    """
    user_orders = state.get("user_orders") or []
    issue = state.get("support_issue", {})
    had_invalid_id = bool(issue.get("order_id"))

    if not user_orders:
        msg = (
            "I'd be happy to help! To raise a support ticket, I need the order this is about.\n\n"
            "I couldn't find any orders on your account. "
            "Could you double-check and provide the order number (e.g. ORD-1234)?"
        )
    else:
        order_lines = "\n".join(
            [
                f"{i+1}. **{o['order_id']}** — {o['product_name'][:60]} ({o['status'].title()})"
                for i, o in enumerate(user_orders[:5])
            ]
        )
        prefix = (
            f"I couldn't find order **{issue['order_id']}** on your account. "
            if had_invalid_id
            else "To raise a support ticket, I need to know which order this is about.\n\n"
            "Here are your recent orders:\n\n"
        )
        msg = f"{prefix}" f"{order_lines}\n\n" f"Please reply with the order number you need help with."

    logger.info(f"request_id={get_request_id()} | Asking user for order")
    return {"final_response": msg}


def assess_severity(state: AgentState) -> dict:
    """
    Deterministic node — severity based on:
    1. Critical keywords in user message
    2. Physical risk of the actual product ordered
    3. Issue category
    """
    user_message = state.get("user_message", "").lower()
    issue = state.get("support_issue", {})
    support_order = state.get("support_order", {})

    critical_message_keywords = [
        "urgent",
        "emergency",
        "danger",
        "safety",
        "injury",
        "hurt",
        "burn",
        "child",
        "baby",
        "toddler",
        "hospital",
        "poison",
        "toxic",
        "choking",
        "fire",
        "smoke",
        "electric shock",
    ]

    product_name = (support_order.get("product_name") or "").lower()
    product_is_high_risk = any(kw in product_name for kw in HIGH_RISK_PRODUCT_KEYWORDS)

    if any(kw in user_message for kw in critical_message_keywords):
        severity = "critical"
    elif product_is_high_risk and issue.get("category") in ("defective_product", "damaged_delivery"):
        # e.g. defective heater or broken baby toy → critical regardless of wording
        severity = "critical"
    elif issue.get("category") in ("defective_product", "damaged_delivery", "wrong_item"):
        severity = "medium"
    else:
        severity = "low"

    logger.info(
        f"request_id={get_request_id()} | "
        f"Assessed severity | severity={severity} | product_high_risk={product_is_high_risk} | "
        f"order_id={support_order.get('order_id')}"
    )

    return {"severity": severity}


def lookup_policy(state: AgentState) -> dict:
    """Tool node — looks up handling policy for this category + severity."""
    issue = state.get("support_issue", {})
    severity = state.get("severity", "medium")
    category = issue.get("category", "other")

    policy = lookup_support_policy(category, severity)

    logger.info(f"request_id={get_request_id()} | " f"Policy lookup | category={category} | severity={severity}")

    return {"policy": policy}


def draft_resolution(state: AgentState) -> dict:
    """LLM node — drafts a conversational resolution for low-severity issues."""
    issue = state.get("support_issue", {})
    support_order = state.get("support_order", {})
    policy = state.get("policy", {})

    prompt = (
        f"Order: {support_order.get('order_id')} — {support_order.get('product_name', 'your product')}\n"
        f"Issue: {issue.get('description')}\n"
        f"Category: {issue.get('category')}\n"
        f"Policy: Response time {policy.get('response_time', '48 hours')}\n\n"
        f"Draft a helpful resolution for this customer issue."
    )

    messages = [
        SystemMessage(content=RESOLUTION_SYSTEM_PROMPT),
        HumanMessage(content=prompt),
    ]

    response = llm.invoke(messages)
    logger.info(f"request_id={get_request_id()} | Drafted resolution for low-severity issue")
    return {"final_response": response.content.strip()}


# ==================== ROUTING ====================


def route_after_order_fetch(state: AgentState) -> Literal["found", "not_found"]:
    return "found" if state.get("support_order") else "not_found"


def route_by_severity(state: AgentState) -> Literal["high", "low"]:
    severity = state.get("severity", "low")
    return "high" if severity in ("critical", "medium") else "low"


# ==================== BUILD GRAPH ====================


def build_support_agent_graph():
    graph = StateGraph(AgentState)

    graph.add_node("classify_issue", classify_issue)
    graph.add_node("fetch_order_for_support", fetch_order_for_support)
    graph.add_node("ask_for_order", ask_for_order)
    graph.add_node("assess_severity", assess_severity)
    graph.add_node("lookup_policy", lookup_policy)
    graph.add_node("escalation_handler", escalation_handler_subgraph)
    graph.add_node("draft_resolution", draft_resolution)

    graph.set_entry_point("classify_issue")

    graph.add_edge("classify_issue", "fetch_order_for_support")

    graph.add_conditional_edges(
        "fetch_order_for_support",
        route_after_order_fetch,
        {
            "found": "assess_severity",
            "not_found": "ask_for_order",
        },
    )

    graph.add_edge("assess_severity", "lookup_policy")

    graph.add_conditional_edges(
        "lookup_policy",
        route_by_severity,
        {
            "high": "escalation_handler",
            "low": "draft_resolution",
        },
    )

    graph.add_edge("escalation_handler", END)
    graph.add_edge("draft_resolution", END)
    graph.add_edge("ask_for_order", END)

    return graph.compile()


support_agent_graph = build_support_agent_graph()
