from typing import TypedDict, Optional, List, Any

class AgentState(TypedDict, total=False):
    # Existing fields
    user_message: str
    user_id: str
    session_id: str
    intent: str
    confidence: float
    order_id: Optional[str]

    conversation_history: Optional[List[dict]]  # ADD THIS

    # Agent 2 fields
    preferences: Optional[dict]
    original_preferences: Optional[dict]
    search_results: Optional[List[dict]]
    ranked_products: Optional[List[dict]]
    broaden_attempt: int
    relaxed_filters: Optional[List[str]]
    filters_exhausted: bool
    
    # Agent 3 fields - ADD THESE
    support_issue: Optional[dict]
    severity: Optional[str]
    policy: Optional[dict]
    ticket_history: Optional[List[dict]]
    recent_critical_count: int
    priority: Optional[str]
    
    # Final response
    final_response: Optional[str]

    from typing import TypedDict, Optional, List, Any

class AgentState(TypedDict, total=False):
    # Existing fields
    user_message: str
    user_id: str
    session_id: str
    intent: str
    confidence: float
    order_id: Optional[str]
    conversation_history: Optional[List[dict]]
    
    # Agent 1 fields - ADD THESE
    user_orders: Optional[List[dict]]
    order_data: Optional[dict]
    tracking_data: Optional[dict]
    
    # Agent 2 fields
    preferences: Optional[dict]
    original_preferences: Optional[dict]
    search_results: Optional[List[dict]]
    ranked_products: Optional[List[dict]]
    broaden_attempt: int
    relaxed_filters: Optional[List[str]]
    filters_exhausted: bool
    
    # Agent 3 fields
    support_issue: Optional[dict]
    severity: Optional[str]
    policy: Optional[dict]
    ticket_history: Optional[List[dict]]
    recent_critical_count: int
    priority: Optional[str]
    
    # Final response
    final_response: Optional[str]