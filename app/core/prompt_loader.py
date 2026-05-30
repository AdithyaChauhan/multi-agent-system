"""Load prompts from LangSmith Prompt Hub with in-memory TTL cache."""
import os
import time
from langsmith import Client
from app.core.logger import get_logger

logger = get_logger("app.core.prompt_loader")

client = Client()

_cache: dict[str, tuple[str, str, float]] = {}
_TTL = 300  # 5 minutes — refresh from LangSmith no more than once per 5 min


def load_prompt(prompt_name: str, version: str = "latest") -> tuple[str, str]:
    """
    Load a prompt from LangSmith Prompt Hub, with TTL-cached results.

    Returns (prompt_text, commit_hash). Returns (None, None) on failure.
    On network error, returns a stale cached entry if one exists.
    """
    key = f"{prompt_name}:{version}"
    now = time.monotonic()

    cached = _cache.get(key)
    if cached:
        text, commit_hash, cached_at = cached
        if now - cached_at < _TTL:
            return text, commit_hash

    try:
        prompt = client.pull_prompt(key)
        system_text = ""
        for msg in prompt.messages:
            if hasattr(msg, "prompt"):
                system_text = msg.prompt.template
                break

        commit_hash = version if version != "latest" else "latest"
        _cache[key] = (system_text, commit_hash, now)
        logger.info(f"Fetched prompt | name={prompt_name} | version={version}")
        return system_text, commit_hash

    except Exception as e:
        logger.error(f"Failed to load prompt {prompt_name}: {e}")
        if cached:
            logger.warning(f"Returning stale cache | name={prompt_name}")
            return cached[0], cached[1]
        return None, None


# Prompt version config — override via env vars to pin a specific commit
PROMPT_VERSIONS = {
    "router-classification-prompt":  os.getenv("ROUTER_PROMPT_VERSION", "latest"),
    "support-classification-prompt": os.getenv("SUPPORT_PROMPT_VERSION", "latest"),
    "support-resolution-prompt":     os.getenv("SUPPORT_RESOLUTION_PROMPT_VERSION", "latest"),
    "product-extraction-prompt":     os.getenv("PRODUCT_EXTRACTION_PROMPT_VERSION", "latest"),
    "order-response-prompt":         os.getenv("ORDER_RESPONSE_PROMPT_VERSION", "latest"),
}
