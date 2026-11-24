from prometheus_client import Counter, Histogram

http_requests_total = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status_code"],
)

http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "endpoint"],
    buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)

agent_requests_total = Counter(
    "agent_requests_total",
    "Total requests classified and routed to each agent",
    ["agent"],
)

llm_requests_total = Counter(
    "llm_requests_total",
    "Total LLM API calls made",
    ["agent", "node"],
)

llm_tokens_total = Counter(
    "llm_tokens_total",
    "Total LLM tokens consumed",
    ["agent", "node", "token_type"],
)

llm_duration_seconds = Histogram(
    "llm_duration_seconds",
    "LLM API call duration in seconds",
    ["agent", "node"],
    buckets=[0.1, 0.5, 1.0, 2.0, 3.0, 5.0, 10.0, 30.0],
)

llm_fallback_total = Counter(
    "llm_fallback_total",
    "LLM calls answered by a fallback model because an earlier model failed",
    ["from_model", "to_model", "reason"],
)

llm_unavailable_total = Counter(
    "llm_unavailable_total",
    "LLM calls that no model in the fallback chain could answer",
)

llm_cache_hits_total = Counter(
    "llm_cache_hits_total",
    "LLM calls answered from the in-memory answer cache",
)

# One chat turn from start to reply, on /chat and /chat/stream alike. The HTTP histogram above can't
# time /chat/stream: its response starts before the graph runs.
chat_turns_total = Counter(
    "chat_turns_total",
    "Chat turns by how they ended: answered, busy (no model could answer), limited, refused, error",
    ["endpoint", "outcome"],
)

chat_turn_seconds = Histogram(
    "chat_turn_seconds",
    "Seconds from a chat turn's start to its reply",
    ["endpoint"],
    buckets=[0.25, 0.5, 1.0, 2.0, 3.0, 5.0, 8.0, 13.0, 20.0, 30.0],
)

chat_limited_total = Counter(
    "chat_limited_total",
    "Chat turns refused by a rate limit or daily turn budget",
    ["limit"],
)
