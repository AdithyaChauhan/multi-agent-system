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
