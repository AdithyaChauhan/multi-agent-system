import httpx
from typing import Optional
from app.core.logger import get_logger, get_request_id

logger = get_logger("app.tools.shipment_tools")

CARRIER_API_BASE = "http://localhost:9000"


def fetch_tracking_info(tracking_id: str) -> Optional[dict]:
    """
    Call the mock carrier API and return tracking info.
    Returns the tracking data as a dict, or None on failure.
    """
    url = f"{CARRIER_API_BASE}/tracking/{tracking_id}"

    try:
        response = httpx.get(url, timeout=5.0)

        if response.status_code == 404:
            logger.warning(f"request_id={get_request_id()} | Tracking not found | tracking_id={tracking_id}")
            return None

        if response.status_code != 200:
            logger.error(
                f"request_id={get_request_id()} | Carrier API error | status={response.status_code} | tracking_id={tracking_id}"
            )
            return None

        data = response.json()
        logger.info(f"request_id={get_request_id()} | Tracking fetched | tracking_id={tracking_id}")
        return data

    except httpx.RequestError as e:
        logger.error(f"request_id={get_request_id()} | Carrier API connection error | {str(e)}")
        return None
