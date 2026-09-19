import os

import httpx
from typing import Optional
from app.core.logger import get_logger, get_request_id

logger = get_logger("app.tools.shipment_tools")

# Inside Docker the mock API is a separate container — use its service name.
# Outside Docker (local scripts / tests) fall back to localhost.
_carrier_url = os.getenv("MOCK_CARRIER_API_URL")
if _carrier_url:
    CARRIER_API_BASE = _carrier_url.rstrip("/")
else:
    # Render supplies the private service host/port separately; local Docker
    # Compose uses the service-name fallback below.
    _carrier_hostport = os.getenv("MOCK_CARRIER_API_HOSTPORT", "mock-carrier-api:9000")
    CARRIER_API_BASE = f"http://{_carrier_hostport}"


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
