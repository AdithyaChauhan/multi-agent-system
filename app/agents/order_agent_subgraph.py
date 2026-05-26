from langgraph.graph import StateGraph, END

from app.agents.state import AgentState
from app.tools.shipment_tools import fetch_tracking_info
from app.core.logger import get_logger, get_request_id

logger = get_logger("app.agents.order_subgraph")


def get_carrier_info(state: AgentState) -> dict:
    """Deterministic node — reads carrier and tracking_id from already-fetched order_data."""
    order_data = state.get("order_data") or {}
    carrier = order_data.get("carrier")
    tracking_id = order_data.get("tracking_id")

    logger.info(f"request_id={get_request_id()} | Carrier info | carrier={carrier} | tracking_id={tracking_id}")

    return {
        "tracking_data": {
            "carrier": carrier,
            "tracking_id": tracking_id,
            "status_from_db": order_data.get("status"),
        }
    }


def fetch_tracking(state: AgentState) -> dict:
    """ToolNode-style node — calls the mock carrier API."""
    tracking_data = state.get("tracking_data") or {}
    tracking_id = tracking_data.get("tracking_id")

    if not tracking_id:
        logger.warning(f"request_id={get_request_id()} | No tracking_id, skipping API call")
        return {
            "tracking_data": {
                **tracking_data,
                "live_status": None,
                "current_location": None,
                "estimated_delivery": None,
            }
        }

    api_result = fetch_tracking_info(tracking_id)

    if not api_result:
        logger.warning(f"request_id={get_request_id()} | Carrier API returned no data")
        return {
            "tracking_data": {
                **tracking_data,
                "live_status": None,
                "current_location": None,
                "estimated_delivery": None,
            }
        }

    return {
        "tracking_data": {
            **tracking_data,
            "live_status": api_result.get("status"),
            "current_location": api_result.get("current_location"),
            "estimated_delivery": api_result.get("estimated_delivery"),
            "last_update": api_result.get("last_update"),
        }
    }


def extract_latest_status(state: AgentState) -> dict:
    """Deterministic node — picks the best available status."""
    tracking_data = state.get("tracking_data") or {}
    live_status = tracking_data.get("live_status")
    db_status = tracking_data.get("status_from_db")

    final_status = live_status or db_status or "Status unavailable"

    logger.info(f"request_id={get_request_id()} | Latest status | status={final_status}")

    return {
        "tracking_data": {
            **tracking_data,
            "final_status": final_status,
        }
    }


def build_shipment_tracking_subgraph():
    graph = StateGraph(AgentState)

    graph.add_node("get_carrier_info", get_carrier_info)
    graph.add_node("fetch_tracking", fetch_tracking)
    graph.add_node("extract_latest_status", extract_latest_status)

    graph.set_entry_point("get_carrier_info")
    graph.add_edge("get_carrier_info", "fetch_tracking")
    graph.add_edge("fetch_tracking", "extract_latest_status")
    graph.add_edge("extract_latest_status", END)

    return graph.compile()


shipment_tracking_subgraph = build_shipment_tracking_subgraph()