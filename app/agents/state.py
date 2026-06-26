from typing import Annotated, TypedDict, Optional, List

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict, total=False):
    # Core
    user_message: str
    user_id: str
    session_id: str
    intent: str
    confidence: float
    order_id: Optional[str]
    conversation_history: Optional[List[dict]]

    # Agent 1 — Order
    user_orders: Optional[List[dict]]
    order_data: Optional[dict]
    tracking_data: Optional[dict]

    # Agent 2 — Product
    preferences: Optional[dict]
    original_preferences: Optional[dict]
    search_results: Optional[List[dict]]
    ranked_products: Optional[List[dict]]
    broaden_attempt: int
    relaxed_filters: Optional[List[str]]
    filters_exhausted: bool
    keyword_recovery_attempted: bool

    # Agent 3 — Support
    support_issue: Optional[dict]
    support_order: Optional[dict]
    severity: Optional[str]
    policy: Optional[dict]
    ticket_history: Optional[List[dict]]
    recent_critical_count: int
    priority: Optional[str]

    # ToolNode message channel — required by langgraph.prebuilt.ToolNode
    messages: Annotated[List[BaseMessage], add_messages]

    # Reroute signal — support agent sets this when bare order lookup detected
    reroute_to_order: Optional[bool]

    # Action signal — support agent sets this when user confirmation is needed (e.g. cancel)
    action_required: Optional[dict]

    # Final response
    final_response: Optional[str]
