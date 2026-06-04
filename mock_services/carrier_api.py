from fastapi import FastAPI, HTTPException
from datetime import datetime, timedelta
import random

app = FastAPI(title="Mock Carrier API")


TRACKING_DATA = {
    "TRK-9001": {
        "carrier": "FakeExpress",
        "status": "In Transit",
        "current_location": "Bengaluru Hub",
        "last_update": "2026-05-20 14:32:00",
        "estimated_delivery": "2026-05-22",
    },
    "TRK-9002": {
        "carrier": "FakeExpress",
        "status": "Delivered",
        "current_location": "Customer Address",
        "last_update": "2026-05-18 11:15:00",
        "estimated_delivery": "2026-05-18",
    },
    "TRK-9003": {
        "carrier": "FakeExpress",
        "status": "In Transit",
        "current_location": "Mumbai Sorting Facility",
        "last_update": "2026-05-21 08:05:00",
        "estimated_delivery": "2026-05-23",
    },
    "TRK-9004": {
        "carrier": "FakeExpress",
        "status": "Out for Delivery",
        "current_location": "Bengaluru Local Hub",
        "last_update": "2026-05-21 07:45:00",
        "estimated_delivery": "2026-05-21",
    },
    "TRK-9005": {
        "carrier": "FakeExpress",
        "status": "Delivered",
        "current_location": "Customer Address",
        "last_update": "2026-05-15 16:20:00",
        "estimated_delivery": "2026-05-15",
    },
    "TRK-1001": {
        "carrier": "FakeExpress",
        "status": "Delivered",
        "current_location": "Customer Address",
        "last_update": "2026-06-01 10:00:00",
        "estimated_delivery": "2026-06-01",
    },
    "TRK-1002": {
        "carrier": "FakeExpress",
        "status": "In Transit",
        "current_location": "Delhi Sorting Facility",
        "last_update": "2026-06-03 09:15:00",
        "estimated_delivery": "2026-06-06",
    },
    "TRK-1003": {
        "carrier": "FakeExpress",
        "status": "Out for Delivery",
        "current_location": "Bangalore Local Hub",
        "last_update": "2026-06-04 08:30:00",
        "estimated_delivery": "2026-06-04",
    },
    "TRK-1004": {
        "carrier": "FakeExpress",
        "status": "Delivered",
        "current_location": "Customer Address",
        "last_update": "2026-05-28 14:45:00",
        "estimated_delivery": "2026-05-28",
    },
    "TRK-1005": {
        "carrier": "FakeExpress",
        "status": "Cancelled",
        "current_location": "Warehouse",
        "last_update": "2026-05-25 11:00:00",
        "estimated_delivery": None,
    },
}


@app.get("/health")
def health():
    return {"status": "ok", "service": "mock-carrier-api"}


@app.get("/tracking/{tracking_id}")
def get_tracking(tracking_id: str):
    if tracking_id not in TRACKING_DATA:
        raise HTTPException(status_code=404, detail="Tracking ID not found")

    return {
        "tracking_id": tracking_id,
        **TRACKING_DATA[tracking_id]
    }