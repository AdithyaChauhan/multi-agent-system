from pydantic import BaseModel, ConfigDict
from typing import List, Optional
from datetime import datetime


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    # The answer to a paused question (the Yes / No buttons for "cancel this order?").
    confirm: Optional[bool] = None
    # A filter chip the shopper removed: {"field": "brand"} or {"field": "features", "value": "4k"}.
    remove_filter: Optional[dict] = None


class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    session_id: str
    role: str
    content: str
    created_at: datetime


class SessionMessagesResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    session_id: str
    user_id: str
    messages: List[MessageResponse]


class ChatResponse(BaseModel):
    session_id: str
    user_id: str
    response: str
    action: Optional[dict] = None
    run_id: Optional[str] = None
    active_filters: Optional[List[dict]] = None  # the product search's filters, shown as chips
    products: Optional[List[dict]] = None  # the products in the reply, shown as cards
    orders: Optional[List[dict]] = None  # the orders a reply lists, as data the page draws cards from
