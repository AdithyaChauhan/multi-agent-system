from typing import List, Optional, TypedDict


class AgentState(TypedDict, total=False):
    # Request
    user_message: str
    user_id: str
    session_id: str
    conversation_history: Optional[List[dict]]

    # Router decision
    intent: str
    order_id: Optional[str]
    risk: Optional[str]  # "none" | "legal" | "safety"
    route: Optional[str]  # set by terminal router nodes: clarify / sign_in / safety

    # Order agent
    user_orders: Optional[List[dict]]
    order_data: Optional[dict]
    tracking_data: Optional[dict]

    # Product agent
    preferences: Optional[dict]
    original_preferences: Optional[dict]
    not_carried: Optional[dict]
    search_results: Optional[List[dict]]
    ranked_products: Optional[List[dict]]
    relaxed_filters: Optional[List[str]]

    # Support agent
    support_issue: Optional[dict]
    support_order: Optional[dict]

    # Cancel needs the user's explicit "Yes" in the UI
    action_required: Optional[dict]

    final_response: Optional[str]
