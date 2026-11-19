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

    # Agent outputs
    preferences: Optional[dict]  # the shopper's current search filters, kept for the next turn
    ranked_products: Optional[List[dict]]
    relaxed_filters: Optional[List[str]]
    order_data: Optional[dict]
    support_order: Optional[dict]

    final_response: Optional[str]


# ── Product agent ──────────────────────────────────────────────────────────────


class ProductInput(TypedDict, total=False):
    user_message: str
    preferences: Optional[dict]


class ProductOutput(TypedDict, total=False):
    preferences: Optional[dict]
    ranked_products: Optional[List[dict]]
    relaxed_filters: Optional[List[str]]
    final_response: Optional[str]


class SearchInput(TypedDict, total=False):
    preferences: Optional[dict]


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
    cancel_answer: Optional[dict]  # what the shopper answered when the graph paused: {confirm, user_id}
