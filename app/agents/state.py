"""Graph state. The router holds the conversation turn; each agent subgraph declares what it reads
(Input) and what it hands back (Output). Everything else an agent uses stays inside it."""

from typing import List, Optional, TypedDict


class RouterState(TypedDict, total=False):
    # Request
    user_message: str
    user_id: str
    session_id: str
    conversation_history: Optional[List[dict]]

    # Router decision
    intent: str
    order_id: Optional[str]
    risk: Optional[str]  # "none" | "legal" | "safety"
    support_issue: Optional[dict]
    route: Optional[str]  # set by terminal router nodes: clarify / sign_in / safety

    filter_edit: Optional[dict]  # a removed filter chip: {field, value}; skips the router's model call

    # Agent outputs
    preferences: Optional[dict]  # the shopper's current search filters, kept for the next turn
    active_filters: Optional[List[dict]]  # those filters as chips
    ranked_products: Optional[List[dict]]
    relaxed_filters: Optional[List[str]]
    order_data: Optional[dict]
    support_order: Optional[dict]

    # Escalation subgraph (safety reports): what to hand to a person, and the ticket it opened
    escalation: Optional[dict]
    ticket: Optional[dict]

    final_response: Optional[str]


# ── Product agent ──────────────────────────────────────────────────────────────


class ProductInput(TypedDict, total=False):
    user_message: str
    preferences: Optional[dict]
    filter_edit: Optional[dict]


class ProductOutput(TypedDict, total=False):
    preferences: Optional[dict]
    active_filters: Optional[List[dict]]
    ranked_products: Optional[List[dict]]
    relaxed_filters: Optional[List[str]]
    final_response: Optional[str]


class SearchInput(TypedDict, total=False):
    preferences: Optional[dict]
    user_message: Optional[str]  # hybrid search can add the shopper's own words to the query


class SearchOutput(TypedDict, total=False):
    search_results: Optional[List[dict]]
    relaxed_filters: Optional[List[str]]  # filters it had to loosen to find anything


class SearchState(SearchInput, SearchOutput, total=False):
    search_filters: Optional[dict]  # working copy, loosened step by step


class ProductState(ProductInput, ProductOutput, total=False):
    not_carried: Optional[dict]
    search_results: Optional[List[dict]]


# ── Order agent ────────────────────────────────────────────────────────────────


class OrderInput(TypedDict, total=False):
    user_id: str
    order_id: Optional[str]


class OrderOutput(TypedDict, total=False):
    order_id: Optional[str]
    order_data: Optional[dict]
    final_response: Optional[str]


class OrderState(OrderInput, OrderOutput, total=False):
    user_orders: Optional[List[dict]]
    tracking_data: Optional[dict]


# ── Support agent ──────────────────────────────────────────────────────────────


class SupportInput(TypedDict, total=False):
    user_message: str
    user_id: str
    order_id: Optional[str]
    risk: Optional[str]
    support_issue: Optional[dict]


class SupportOutput(TypedDict, total=False):
    support_order: Optional[dict]
    final_response: Optional[str]


class SupportState(SupportInput, SupportOutput, total=False):
    user_orders: Optional[List[dict]]
    escalation: Optional[dict]  # the ticket to open, for the escalation subgraph
    ticket: Optional[dict]
    cancel_answer: Optional[dict]  # what the shopper answered when the graph paused: {confirm, user_id}
