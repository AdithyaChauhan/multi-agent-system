from pydantic import BaseModel, ConfigDict
from typing import List
from datetime import datetime

class ChatRequest(BaseModel):
    message: str

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