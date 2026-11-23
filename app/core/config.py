import os
from dotenv import load_dotenv

load_dotenv()

SESSION_EXPIRY_MINUTES = int(os.getenv("SESSION_EXPIRY_MINUTES", "30"))

# The one place the chat model is named. Checked against https://api.groq.com/openai/v1/models
# on 2026-11-17 (active). Deliberately not read from LLM_MODEL: older .env files set that to a
# retired Groq model that would break every agent at once.
GROQ_MODEL = os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b")

# Where escalation alerts go (safety reports, tickets for a person): a Slack or Discord incoming
# webhook URL. Unset: alerts are written to the log only. Keep the URL in .env, never in git.
ESCALATION_WEBHOOK_URL = os.getenv("ESCALATION_WEBHOOK_URL", "").strip()

# Product search (ADR 0006, 0014). "type": the typed-catalog search of Phase 1. "hybrid": pgvector +
# full text + the resolved type, fused by rank; it falls back to "type" off Postgres or before
# scripts/embed_catalog.py has run.
PRODUCT_SEARCH = os.getenv("PRODUCT_SEARCH", "hybrid").strip().lower()
# "llm": the model picks and orders the candidates. "off": the search order is kept (evals use this
# to measure retrieval on its own, at no token cost).
PRODUCT_RANKER = os.getenv("PRODUCT_RANKER", "llm").strip().lower()
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
# Fusion: weight of each candidate list, and the reciprocal-rank constant. Tuned on the dev half
# of eval/product_queries.json (eval/query_split.json), never on the test half.
HYBRID_WEIGHTS = {
    "vector": float(os.getenv("HYBRID_W_VECTOR", "1.0")),
    "text": float(os.getenv("HYBRID_W_TEXT", "1.0")),
    "type": float(os.getenv("HYBRID_W_TYPE", "1.0")),
}
HYBRID_RRF_K = int(os.getenv("HYBRID_RRF_K", "60"))
# Before "we don't carry X" for a word the catalog doesn't know, the closest product must be less
# similar than this (cosine), or we search instead.
NOT_CARRIED_MIN_SIM = float(os.getenv("NOT_CARRIED_MIN_SIM", "0.75"))
# Query text for hybrid search: the extracted product and features ("prefs"), or those plus the
# shopper's message ("prefs+message"). Tuned on the dev queries.
HYBRID_QUERY = os.getenv("HYBRID_QUERY", "prefs+message").strip().lower()
