import json
import os
from typing import Literal
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from langgraph.graph import StateGraph, END
from dotenv import load_dotenv

from app.agents.state import AgentState
from app.agents.support_agent_subgraph import escalation_handler_subgraph
from app.tools.support_tools import lookup_support_policy
from app.core.logger import get_logger, get_request_id
from app.core.prompt_loader import load_prompt, PROMPT_VERSIONS

load_dotenv()

logger = get_logger("app.agents.support_agent")

llm = ChatOpenAI(
    model="gpt-4o-mini",
    temperature=0,
    api_key=os.getenv("OPENAI_API_KEY")
)


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

# ==================== MAIN FLOW NODES ====================

def classify_issue(state: AgentState) -> dict:
    """LLM node — classifies issue using prompt from LangSmith Hub"""
    user_message = state.get("user_message", "")
    conversation_history = state.get("conversation_history", [])

    # Load prompt from LangSmith Hub
    version = PROMPT_VERSIONS.get("support-classification-prompt", "latest")
    system_prompt, commit_hash = load_prompt("support-classification-prompt", version)

    if not system_prompt:
        logger.warning(f"request_id={get_request_id()} | Using fallback support prompt")
        system_prompt = CLASSIFICATION_SYSTEM_PROMPT
        commit_hash = "fallback"

    # Build context from history
    history_context = ""
    if conversation_history:
        recent = conversation_history[-4:]
        history_context = "\n".join([
            f"{msg['role'].title()}: {msg['content']}"
            for msg in recent
        ])

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
        messages,
        config={
            "metadata": {
                "prompt_name": "support-classification-prompt",
                "prompt_version": commit_hash
            }
        }
    )
    raw = response.content.strip()

    if raw.startswith("```"):
        raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()

    try:
        issue = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error(f"request_id={get_request_id()} | Parse error | {str(e)}")
        issue = {
            "category": "other",
            "order_id": None,
            "description": user_message[:200]
        }

    logger.info(
        f"request_id={get_request_id()} | "
        f"Classified issue | category={issue.get('category')} | prompt_version={commit_hash}"
    )

    return {"support_issue": issue}

def assess_severity(state: AgentState) -> dict:
    """Deterministic node — assesses severity based on keywords"""
    user_message = state.get("user_message", "").lower()
    issue = state.get("support_issue", {})
    
    # Critical keywords
    critical_keywords = [
        "urgent", "emergency", "danger", "safety", "injury", "hurt", "burn",
        "child", "baby", "toddler", "hospital", "poison", "toxic", "choking"
    ]
    
    # Check for critical severity
    if any(keyword in user_message for keyword in critical_keywords):
        severity = "critical"
    # Defective product or damaged delivery usually medium
    elif issue.get("category") in ["defective_product", "damaged_delivery", "wrong_item"]:
        severity = "medium"
    # Refund requests and general questions are low
    else:
        severity = "low"
    
    logger.info(
        f"request_id={get_request_id()} | "
        f"Assessed severity | severity={severity}"
    )
    
    return {"severity": severity}


def lookup_policy(state: AgentState) -> dict:
    """Tool node — looks up handling policy"""
    issue = state.get("support_issue", {})
    severity = state.get("severity", "medium")
    category = issue.get("category", "other")
    
    policy = lookup_support_policy(category, severity)
    
    logger.info(
        f"request_id={get_request_id()} | "
        f"Policy lookup | category={category} | severity={severity}"
    )
    
    return {"policy": policy}


def draft_resolution(state: AgentState) -> dict:
    """LLM node — drafts resolution for low-severity issues"""
    issue = state.get("support_issue", {})
    policy = state.get("policy", {})
    
    prompt = f"""
Issue: {issue.get('description')}
Category: {issue.get('category')}
Policy: Response time {policy.get('response_time', '48 hours')}

Draft a helpful resolution for this customer issue.
"""
    
    messages = [
        SystemMessage(content=RESOLUTION_SYSTEM_PROMPT),
        HumanMessage(content=prompt),
    ]
    
    response = llm.invoke(messages)
    resolution = response.content.strip()
    
    logger.info(f"request_id={get_request_id()} | Drafted resolution for low-severity issue")
    
    return {"final_response": resolution}


# ==================== ROUTING ====================

def route_by_severity(state: AgentState) -> Literal["high", "low"]:
    """Route to escalation subgraph or direct resolution"""
    severity = state.get("severity", "low")
    
    # Critical and medium both go through escalation
    if severity in ["critical", "medium"]:
        return "high"
    return "low"


# ==================== BUILD MAIN GRAPH ====================

def build_support_agent_graph():
    """Main support agent graph"""
    
    graph = StateGraph(AgentState)
    
    graph.add_node("classify_issue", classify_issue)
    graph.add_node("assess_severity", assess_severity)
    graph.add_node("lookup_policy", lookup_policy)
    graph.add_node("escalation_handler", escalation_handler_subgraph)
    graph.add_node("draft_resolution", draft_resolution)
    
    graph.set_entry_point("classify_issue")
    
    graph.add_edge("classify_issue", "assess_severity")
    graph.add_edge("assess_severity", "lookup_policy")
    
    graph.add_conditional_edges(
        "lookup_policy",
        route_by_severity,
        {
            "high": "escalation_handler",
            "low": "draft_resolution",
        }
    )
    
    graph.add_edge("escalation_handler", END)
    graph.add_edge("draft_resolution", END)
    
    return graph.compile()


support_agent_graph = build_support_agent_graph()