import json
import os
import re
import time
from typing import Literal
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.tools import tool
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from dotenv import load_dotenv

from app.agents.state import AgentState
from app.agents.support_agent_subgraph import escalation_handler_subgraph
from app.tools.support_tools import lookup_support_policy, get_open_ticket_for_order
from app.tools.order_tools import fetch_order_from_db, fetch_user_orders, cancel_order_in_db
from app.core.logger import get_logger, get_request_id
from app.core.metrics import llm_requests_total, llm_tokens_total, llm_duration_seconds
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
- "cancellation_request": User wants to cancel an order
- "other": Anything else

Extract order ID ONLY if explicitly stated in the CURRENT message (ORD-1234, order #1234, "order 2001", etc.). Do NOT infer order ID from conversation history.

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
- Order details (including status)
- Issue description
- Category
- Company policy

Draft a helpful, empathetic response that:
1. Acknowledges the issue
2. Provides solution based on policy AND order status
3. Offers next steps
4. Maintains professional, friendly tone

Cancellation rules (check order status and conversation history):
- "processing" + user has NOT yet confirmed: tell them cancellation is possible and ask them to confirm ("Shall I go ahead and cancel it?").
- "processing" + user IS confirming (said "yes", "confirm", "go ahead", "please cancel", "do it"): CALL the cancel_order tool with order_id and user_id, then confirm in your reply.
- "shipped" / "out_for_delivery" / "in_transit": not possible — offer return once it arrives.
- "delivered": not possible — offer return within 30-day policy window.
- "cancelled": inform the order is already cancelled.

IMPORTANT: Call cancel_order only when the user explicitly confirms. Do NOT cancel without confirmation.

Keep response under 150 words. Be specific and actionable.
IMPORTANT:
- Respond conversationally like a chat message, NOT as a formal email
- Do NOT use placeholders like [Customer's Name], [Your Name], [Company Name]
- Do NOT write Subject lines or sign-offs
- Address the user directly as "you"
- Be direct and helpful"""


_POLICY_QUESTION_PHRASES = [
    "return policy",
    "refund policy",
    "warranty policy",
    "exchange policy",
    "what is your policy",
    "whats your policy",
    "what's your policy",
    "how do returns work",
    "how do i return",
    "when can i return",
    "how long to return",
    "how long do i have",
    "can i return",
    "what is your return",
    "what's your return",
    "how does the refund",
]

_POLICY_RESPONSE = (
    "Here's a quick summary of our policies:\n\n"
    "**Returns:** Most items can be returned within 30 days of delivery in original condition.\n"
    "**Refunds:** Processed within 3-5 business days after we receive the return.\n"
    "**Defective items:** Replacement or full refund — no questions asked.\n"
    "**Damaged delivery:** Report within 48 hours for priority resolution.\n\n"
    "If you have a specific order you'd like help with, just share the order number and I'll get started."
)


# ==================== MAIN FLOW NODES ====================


def classify_issue(state: AgentState) -> dict:
    """LLM node — classifies the support issue from message + conversation history."""
    user_message = state.get("user_message", "")
    conversation_history = state.get("conversation_history", [])

    system_prompt = CLASSIFICATION_SYSTEM_PROMPT
    commit_hash = "hardcoded"

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

    _t0 = time.perf_counter()
    response = llm.invoke(
        messages, config={"metadata": {"prompt_name": "support-classification-prompt", "prompt_version": commit_hash}}
    )
    _latency_s = time.perf_counter() - _t0
    _latency_ms = int(_latency_s * 1000)
    _meta = getattr(response, "response_metadata", {})
    _usage = _meta.get("token_usage", {}) if isinstance(_meta, dict) else {}
    logger.info(
        f"request_id={get_request_id()} | LLM_USAGE | agent=support | node=classify_issue"
        f" | prompt_tokens={_usage.get('prompt_tokens', 0)}"
        f" | completion_tokens={_usage.get('completion_tokens', 0)}"
        f" | total_tokens={_usage.get('total_tokens', 0)}"
        f" | latency_ms={_latency_ms}"
    )
    llm_requests_total.labels(agent="support", node="classify_issue").inc()
    llm_duration_seconds.labels(agent="support", node="classify_issue").observe(_latency_s)
    llm_tokens_total.labels(agent="support", node="classify_issue", token_type="prompt").inc(
        _usage.get("prompt_tokens", 0)
    )
    llm_tokens_total.labels(agent="support", node="classify_issue", token_type="completion").inc(
        _usage.get("completion_tokens", 0)
    )
    llm_tokens_total.labels(agent="support", node="classify_issue", token_type="total").inc(
        _usage.get("total_tokens", 0)
    )
    raw = response.content.strip()

    if raw.startswith("```"):
        raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()

    try:
        issue = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error(f"request_id={get_request_id()} | Parse error | {str(e)}")
        issue = {"category": "other", "order_id": None, "description": user_message[:200]}

    # Only keep order_id if it's actually mentioned in the current message
    # (prevents the LLM from pulling order IDs out of conversation history)
    if issue.get("order_id"):
        raw_id = str(issue["order_id"]).replace("ORD-", "").strip()
        if raw_id not in user_message and issue["order_id"] not in user_message:
            issue["order_id"] = None

    # Router-extracted order_id as last-resort fallback (handles pronouns like "cancel it")
    if not issue.get("order_id") and state.get("order_id"):
        issue["order_id"] = state.get("order_id")

    # Deterministic policy-question detection — bypasses order lookup entirely
    msg_lower = user_message.lower()
    issue["is_policy_question"] = any(phrase in msg_lower for phrase in _POLICY_QUESTION_PHRASES)

    logger.info(
        f"request_id={get_request_id()} | "
        f"Classified issue | category={issue.get('category')} | order_id={issue.get('order_id')} | policy_q={issue.get('is_policy_question')}"
    )

    return {"support_issue": issue}


_COMPLAINT_KEYWORDS = {
    "broken",
    "damaged",
    "wrong",
    "missing",
    "refund",
    "return",
    "not working",
    "stopped working",
    "defective",
    "cracked",
    "faulty",
    "malfunction",
    "cancel",
    "complaint",
    "issue",
    "problem",
    "help",
    "support",
    "hurt",
    "bleed",
    "fire",
}


def _is_bare_order_lookup(message: str) -> bool:
    """True when the message is just an order ID or bare number with no complaint context."""
    stripped = message.strip()
    if re.match(r'^\d+$', stripped):
        return True
    if re.match(r'^ORD-?\d+$', stripped, re.IGNORECASE):
        return True
    words = set(stripped.lower().split())
    return len(stripped) < 20 and not words.intersection(_COMPLAINT_KEYWORDS)


def fetch_order_for_support(state: AgentState) -> dict:
    """
    Fetches the order the support ticket is about.
    Priority: (1) product name match in current message, (2) explicit order ID, (3) history-extracted ID.
    """
    user_id = state.get("user_id", "")
    issue = state.get("support_issue", {})
    user_message = state.get("user_message", "")
    msg_lower = user_message.lower()

    # Load user orders once — needed for product name matching and fallback listing
    user_orders = fetch_user_orders(user_id)

    # Priority 1: product name match from current message (beats history-extracted IDs)
    for order in user_orders:
        product_words = [w for w in order.get("product_name", "").lower().split() if len(w) > 3]
        if product_words and any(w in msg_lower for w in product_words):
            order_obj = fetch_order_from_db(order["order_id"], user_id)
            if order_obj:
                logger.info(
                    f"request_id={get_request_id()} | Matched order by product name | order_id={order['order_id']}"
                )
                return {"support_order": order_obj}

    # Priority 2: explicit order ID from classifier or current message digits
    order_id = issue.get("order_id")
    if order_id and str(order_id).strip().isdigit():
        order_id = f"ORD-{order_id.strip()}"
    if not order_id:
        match = re.search(r'\b(\d+)\b', user_message)
        if match:
            order_id = f"ORD-{match.group(1)}"

    if order_id:
        order = fetch_order_from_db(order_id, user_id)
        if order:
            logger.info(f"request_id={get_request_id()} | Support order fetched | order_id={order_id}")
            if _is_bare_order_lookup(user_message) and not get_open_ticket_for_order(user_id, order_id):
                logger.info(
                    f"request_id={get_request_id()} | Bare order lookup — rerouting to order agent | order_id={order_id}"
                )
                return {"support_order": order, "reroute_to_order": True}
            return {"support_order": order}
        logger.info(f"request_id={get_request_id()} | Order not found or not owned | order_id={order_id}")

    logger.info(f"request_id={get_request_id()} | No order resolved | user has {len(user_orders)} orders")
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
            "I'd be happy to help! To open a support ticket, I need the order this is about.\n\n"
            "I couldn't find any orders on your account. "
            "Could you double-check and provide the order number (e.g. ORD-1234)?"
        )
    else:
        shown = user_orders[:5]
        order_lines = "\n".join(
            [
                f"{i+1}. **{o['order_id']}** — {o['product_name'][:60]} ({o['status'].title()})"
                for i, o in enumerate(shown)
            ]
        )
        footer = f"\n_(showing {len(shown)} most recent of {len(user_orders)} orders)_" if len(user_orders) > 5 else ""
        prefix = (
            f"I couldn't find order **{issue['order_id']}** on your account. "
            if had_invalid_id
            else "To raise a support ticket, I need to know which order this is about.\n\nHere are your recent orders:\n\n"
        )
        msg = f"{prefix}{order_lines}{footer}\n\nPlease reply with the order number to open a support ticket."

    logger.info(f"request_id={get_request_id()} | Asking user for order")
    return {"final_response": msg}


_LEGAL_THREAT_KEYWORDS = {
    "sue",
    "lawsuit",
    "lawyer",
    "attorney",
    "court",
    "legal action",
    "consumer court",
    "solicitor",
}


def assess_severity(state: AgentState) -> dict:
    """Deterministic node — business severity based on issue category and legal threats."""
    issue = state.get("support_issue", {})
    support_order = state.get("support_order") or {}
    user_message = state.get("user_message", "").lower()

    has_legal_threat = any(kw in user_message for kw in _LEGAL_THREAT_KEYWORDS)

    if has_legal_threat or issue.get("category") in (
        "defective_product",
        "damaged_delivery",
        "wrong_item",
        "refund_request",
    ):
        severity = "medium"
    else:
        severity = "low"

    logger.info(
        f"request_id={get_request_id()} | "
        f"Assessed severity | severity={severity} | legal_threat={has_legal_threat} | order_id={support_order.get('order_id')}"
    )

    return {"severity": severity}


# ── Support policy tool + ToolNode ───────────────────────────────────────────


@tool
def fetch_support_policy(category: str, severity: str) -> str:
    """
    Look up the company's support policy for an issue category and severity level.
    Returns the applicable policy as JSON, including auto-resolve flag,
    response time, and escalation path.
    Use this before drafting a resolution to ensure the correct policy is applied.
    """
    policy = lookup_support_policy(category, severity)
    return json.dumps(policy)


@tool
def cancel_order(order_id: str, user_id: str) -> str:
    """
    Cancel a customer's order. Only works for orders in 'processing' status.
    Call this only when the customer has explicitly confirmed they want to cancel.
    Returns a confirmation or an error message.
    """
    success = cancel_order_in_db(order_id, user_id)
    if success:
        return f"Order {order_id} has been successfully cancelled."
    return f"Could not cancel order {order_id}. It may not be in 'processing' status or may not belong to this account."


_support_tools = [fetch_support_policy, cancel_order]
draft_tool_node = ToolNode(_support_tools)


def lookup_policy(state: AgentState) -> dict:
    """Deterministic node — fetches support policy directly from the policy table."""
    issue = state.get("support_issue", {})
    severity = state.get("severity", "medium")
    category = issue.get("category", "other")
    logger.info(f"request_id={get_request_id()} | Policy lookup | category={category} | severity={severity}")
    policy = lookup_support_policy(category, severity)
    logger.info(f"request_id={get_request_id()} | Policy fetched | response_time={policy.get('response_time')}")
    return {"policy": policy}


def draft_resolution(state: AgentState) -> dict:
    """LLM node — calls fetch_support_policy to retrieve policy, then drafts a resolution."""
    issue = state.get("support_issue", {})
    support_order = state.get("support_order") or {}
    severity = state.get("severity", "low")
    category = issue.get("category", "other")
    user_id = state.get("user_id", "")
    conversation_history = state.get("conversation_history", [])
    resolution_prompt_version = PROMPT_VERSIONS.get("support-resolution-prompt", "latest")
    resolution_system_prompt, res_hash = load_prompt("support-resolution-prompt", resolution_prompt_version)
    if not resolution_system_prompt:
        resolution_system_prompt = RESOLUTION_SYSTEM_PROMPT
        res_hash = "fallback"

    history_context = ""
    if conversation_history:
        recent = conversation_history[-4:]
        history_context = (
            "Recent conversation:\n" + "\n".join([f"{m['role'].title()}: {m['content']}" for m in recent]) + "\n\n"
        )

    prompt = (
        f"{history_context}"
        f"Order: {support_order.get('order_id')} — {support_order.get('product_name', 'your product')}\n"
        f"Order Status: {support_order.get('status', 'unknown')}\n"
        f"User ID: {user_id}\n"
        f"Issue: {issue.get('description')}\n"
        f"Category: {category}, Severity: {severity}\n\n"
        f"Use the fetch_support_policy tool to retrieve the applicable policy, "
        f"then draft a helpful, empathetic resolution for the customer."
    )

    messages = [
        SystemMessage(content=resolution_system_prompt),
        HumanMessage(content=prompt),
    ]

    _t0 = time.perf_counter()
    response = llm.bind_tools(_support_tools).invoke(
        messages,
        config={"metadata": {"prompt_name": "support-resolution-prompt", "prompt_version": res_hash}},
    )
    _latency_s = time.perf_counter() - _t0
    _latency_ms = int(_latency_s * 1000)
    _meta = getattr(response, "response_metadata", {})
    _usage = _meta.get("token_usage", {}) if isinstance(_meta, dict) else {}
    logger.info(
        f"request_id={get_request_id()} | LLM_USAGE | agent=support | node=draft_resolution"
        f" | prompt_tokens={_usage.get('prompt_tokens', 0)}"
        f" | completion_tokens={_usage.get('completion_tokens', 0)}"
        f" | total_tokens={_usage.get('total_tokens', 0)}"
        f" | latency_ms={_latency_ms}"
    )
    llm_requests_total.labels(agent="support", node="draft_resolution").inc()
    llm_duration_seconds.labels(agent="support", node="draft_resolution").observe(_latency_s)
    llm_tokens_total.labels(agent="support", node="draft_resolution", token_type="prompt").inc(
        _usage.get("prompt_tokens", 0)
    )
    llm_tokens_total.labels(agent="support", node="draft_resolution", token_type="completion").inc(
        _usage.get("completion_tokens", 0)
    )
    llm_tokens_total.labels(agent="support", node="draft_resolution", token_type="total").inc(
        _usage.get("total_tokens", 0)
    )

    if getattr(response, "tool_calls", None):
        logger.info(f"request_id={get_request_id()} | draft_resolution calling fetch_support_policy")
        return {"messages": [response]}

    logger.info(f"request_id={get_request_id()} | Drafted resolution (no tool call)")
    return {"final_response": response.content.strip()}


def finalize_draft(state: AgentState) -> dict:
    """LLM node — after fetch_support_policy tool call, generates the final resolution draft."""
    issue = state.get("support_issue", {})
    support_order = state.get("support_order") or {}
    severity = state.get("severity", "low")
    category = issue.get("category", "other")

    context_prompt = (
        f"Order: {support_order.get('order_id')} — {support_order.get('product_name', 'the product')}\n"
        f"Order Status: {support_order.get('status', 'unknown')}\n"
        f"Issue: {issue.get('description')}\n"
        f"Category: {category.replace('_', ' ')}, Severity: {severity}\n\n"
        f"Using the policy retrieved above, draft a helpful and empathetic response for the customer."
    )

    tool_messages = state.get("messages") or []
    messages = [SystemMessage(content=RESOLUTION_SYSTEM_PROMPT), HumanMessage(content=context_prompt)] + tool_messages

    _t0 = time.perf_counter()
    response = llm.invoke(messages)
    _latency_s = time.perf_counter() - _t0
    _latency_ms = int(_latency_s * 1000)
    _meta = getattr(response, "response_metadata", {})
    _usage = _meta.get("token_usage", {}) if isinstance(_meta, dict) else {}
    logger.info(
        f"request_id={get_request_id()} | LLM_USAGE | agent=support | node=finalize_draft"
        f" | prompt_tokens={_usage.get('prompt_tokens', 0)}"
        f" | completion_tokens={_usage.get('completion_tokens', 0)}"
        f" | total_tokens={_usage.get('total_tokens', 0)}"
        f" | latency_ms={_latency_ms}"
    )
    llm_requests_total.labels(agent="support", node="finalize_draft").inc()
    llm_duration_seconds.labels(agent="support", node="finalize_draft").observe(_latency_s)
    llm_tokens_total.labels(agent="support", node="finalize_draft", token_type="prompt").inc(
        _usage.get("prompt_tokens", 0)
    )
    llm_tokens_total.labels(agent="support", node="finalize_draft", token_type="completion").inc(
        _usage.get("completion_tokens", 0)
    )
    llm_tokens_total.labels(agent="support", node="finalize_draft", token_type="total").inc(
        _usage.get("total_tokens", 0)
    )
    logger.info(f"request_id={get_request_id()} | Resolution drafted")
    return {"final_response": response.content.strip()}


def route_to_draft_tool(state: AgentState) -> Literal["draft_tools", "end"]:
    messages = state.get("messages") or []
    if messages and getattr(messages[-1], "tool_calls", None):
        return "draft_tools"
    return "end"


def answer_policy_question(state: AgentState) -> dict:
    """Short-circuit node — answers generic policy questions without order lookup."""
    logger.info(f"request_id={get_request_id()} | Answering policy question directly")
    return {"final_response": _POLICY_RESPONSE}


# ==================== ROUTING ====================


def route_after_classify(state: AgentState) -> Literal["fetch_order", "answer_policy"]:
    issue = state.get("support_issue", {})
    if issue.get("is_policy_question"):
        return "answer_policy"
    return "fetch_order"


def handle_cancellation(state: AgentState) -> dict:
    """Deterministic node — handles cancel order request; sets action_required for UI confirmation."""
    support_order = state.get("support_order") or {}
    order_id = support_order.get("order_id")
    status = (support_order.get("status") or "").lower()
    product = support_order.get("product_name", "your order")

    if status == "processing":
        return {
            "final_response": f"Your order **{order_id}** ({product}) is in processing and can still be cancelled.",
            "action_required": {"type": "confirm_cancel", "order_id": order_id, "product_name": product},
        }
    elif status in ("shipped", "out_for_delivery", "in_transit"):
        return {
            "final_response": f"Order **{order_id}** has already shipped — cancellation isn't possible. Once it arrives, I can help you initiate a return."
        }
    elif status == "delivered":
        return {
            "final_response": f"Order **{order_id}** has been delivered and can't be cancelled. You can return it within our 30-day policy window."
        }
    elif status == "cancelled":
        return {"final_response": f"Order **{order_id}** is already cancelled — nothing further needed."}
    return {"final_response": f"I wasn't able to look up **{order_id}**. Please contact our support team."}


def route_after_order_fetch(state: AgentState) -> Literal["found", "not_found", "reroute", "cancellation"]:
    if state.get("reroute_to_order"):
        return "reroute"
    issue = state.get("support_issue", {})
    if state.get("support_order") and issue.get("category") == "cancellation_request":
        return "cancellation"
    if state.get("support_order"):
        return "found"
    # Legal threats escalate immediately even without an order — no ticket FK needed
    user_message = state.get("user_message", "").lower()
    if any(kw in user_message for kw in _LEGAL_THREAT_KEYWORDS):
        return "found"
    return "not_found"


def reroute_exit(state: AgentState) -> dict:
    """Exit node — signals main.py to re-invoke the order agent."""
    return {}


def route_by_severity(state: AgentState) -> Literal["high", "low"]:
    severity = state.get("severity", "low")
    return "high" if severity in ("critical", "medium") else "low"


# ==================== BUILD GRAPH ====================


def build_support_agent_graph():
    graph = StateGraph(AgentState)

    graph.add_node("classify_issue", classify_issue)
    graph.add_node("answer_policy_question", answer_policy_question)
    graph.add_node("fetch_order_for_support", fetch_order_for_support)
    graph.add_node("ask_for_order", ask_for_order)
    graph.add_node("handle_cancellation", handle_cancellation)
    graph.add_node("assess_severity", assess_severity)
    graph.add_node("lookup_policy", lookup_policy)
    graph.add_node("escalation_handler", escalation_handler_subgraph)
    graph.add_node("draft_resolution", draft_resolution)
    graph.add_node("draft_tools", draft_tool_node)
    graph.add_node("finalize_draft", finalize_draft)
    graph.add_node("reroute_exit", reroute_exit)

    graph.set_entry_point("classify_issue")

    graph.add_conditional_edges(
        "classify_issue",
        route_after_classify,
        {"fetch_order": "fetch_order_for_support", "answer_policy": "answer_policy_question"},
    )

    graph.add_conditional_edges(
        "fetch_order_for_support",
        route_after_order_fetch,
        {
            "found": "assess_severity",
            "not_found": "ask_for_order",
            "reroute": "reroute_exit",
            "cancellation": "handle_cancellation",
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

    graph.add_conditional_edges(
        "draft_resolution",
        route_to_draft_tool,
        {"draft_tools": "draft_tools", "end": END},
    )
    graph.add_edge("draft_tools", "finalize_draft")
    graph.add_edge("finalize_draft", END)

    graph.add_edge("escalation_handler", END)
    graph.add_edge("ask_for_order", END)
    graph.add_edge("handle_cancellation", END)
    graph.add_edge("answer_policy_question", END)
    graph.add_edge("reroute_exit", END)

    return graph.compile()


support_agent_graph = build_support_agent_graph()
