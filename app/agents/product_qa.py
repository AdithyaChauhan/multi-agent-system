"""Questions about products already shown, answered by an agent loop with read-only tools (ADR 0016).

"Tell me more about the second one", "which of these is lighter?": the model decides which facts it
needs and calls the tools through a ToolNode, up to MAX_TOOL_ROUNDS times, then answers from what
they returned. This is the one place the model picks its own tools, and it is safe by construction:
- the tools only read product facts, and only for the products on screen (by list position), so a
  prompt-injected product id or an order number can't reach them;
- no tool takes a user id or touches orders, tickets or accounts (ADR 0002).
"""

import json
from typing import Annotated, List, Optional, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.tools import tool
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import InjectedState, ToolNode

from app.core.llm import call_llm
from app.core.logger import get_logger, get_request_id
from app.core.prompt_loader import load_prompt
from app.db.database import SessionLocal
from app.models.product import Brand, Product

logger = get_logger("app.agents.product_qa")

MAX_TOOL_ROUNDS = 3
NO_ANSWER = "Sorry, I couldn't find that in the product details. Could you ask it another way?"


class QAInput(TypedDict, total=False):
    user_message: str
    shown_products: Optional[List[dict]]


class QAOutput(TypedDict, total=False):
    final_response: Optional[str]


class QAState(QAInput, QAOutput, total=False):
    messages: Annotated[list, add_messages]
    rounds: int


def _facts(position: int, shown: list) -> dict:
    """What the store knows about the product at this list position (1-based), or why not."""
    if not isinstance(position, int) or not 1 <= position <= len(shown):
        return {"error": f"There is no product {position} in the list (1 to {len(shown)})."}
    db = SessionLocal()
    try:
        row = (
            db.query(Product, Brand.name)
            .outerjoin(Brand, Product.brand_id == Brand.id)
            .filter(Product.product_id == shown[position - 1]["product_id"])
            .first()
        )
    finally:
        db.close()
    if row is None:
        return {"error": f"Product {position} is no longer in the catalog."}
    p, brand = row
    return {
        "position": position,
        "title": p.title or p.name,
        "brand": brand or p.brand,
        "price_rupees": p.price,
        "rating": float(p.rating) if p.rating else None,
        "attributes": p.attributes or {},
        "description": (p.description or p.name or "")[:600],
    }


@tool
def get_product_details(position: int, state: Annotated[dict, InjectedState]) -> str:
    """Facts about one listed product: title, brand, price, rating, attributes and description.

    Args:
        position: the product's number in the list shown to the shopper (1, 2 or 3)
    """
    return json.dumps(_facts(position, state.get("shown_products") or []), ensure_ascii=False)


@tool
def compare_products(positions: List[int], state: Annotated[dict, InjectedState]) -> str:
    """Facts about several listed products at once, to compare them.

    Args:
        positions: the products' numbers in the list shown to the shopper, e.g. [1, 2]
    """
    shown = state.get("shown_products") or []
    return json.dumps([_facts(p, shown) for p in (positions or [])[:5]], ensure_ascii=False)


TOOLS = [get_product_details, compare_products]


def qa_think(state: QAState) -> dict:
    """LLM node: call tools for the facts it needs, or answer. Tools are withheld after the cap."""
    new = []
    messages = list(state.get("messages") or [])
    if not messages:
        shown = state.get("shown_products") or []
        listing = "\n".join(f"{i}. {p.get('title')} — ₹{p.get('price')}" for i, p in enumerate(shown, 1))
        new = [
            SystemMessage(content=load_prompt("product_qa")),
            HumanMessage(content=f"Listed products:\n{listing}\n\nQuestion: {state.get('user_message', '')}"),
        ]
        messages = new
    rounds = state.get("rounds") or 0
    if rounds < MAX_TOOL_ROUNDS:
        reply = call_llm("product", "answer_question", messages, tools=TOOLS)
    else:  # enough lookups: answer from what's already there
        reply = AIMessage(content=call_llm("product", "answer_question", messages) or "")
    calls = [c.get("name") for c in (reply.tool_calls or [])]
    logger.info(f"request_id={get_request_id()} | product_qa | round={rounds} | tool_calls={calls}")
    return {"messages": [*new, reply], "rounds": rounds + (1 if calls else 0)}


def route_after_think(state: QAState) -> str:
    last = (state.get("messages") or [None])[-1]
    return "qa_tools" if getattr(last, "tool_calls", None) else "qa_answer"


def qa_answer(state: QAState) -> dict:
    last = (state.get("messages") or [None])[-1]
    text = (getattr(last, "content", "") or "").strip()
    return {"final_response": text or NO_ANSWER}


def build_product_qa_graph():
    graph = StateGraph(QAState, input_schema=QAInput, output_schema=QAOutput)
    graph.add_node("qa_think", qa_think)
    graph.add_node("qa_tools", ToolNode(TOOLS))
    graph.add_node("qa_answer", qa_answer)
    graph.add_edge(START, "qa_think")
    graph.add_conditional_edges("qa_think", route_after_think, {"qa_tools": "qa_tools", "qa_answer": "qa_answer"})
    graph.add_edge("qa_tools", "qa_think")
    graph.add_edge("qa_answer", END)
    return graph.compile()


product_qa_graph = build_product_qa_graph()
