"""Load prompts from LangSmith Prompt Hub at runtime"""

import os
from langsmith import Client
from app.core.logger import get_logger

logger = get_logger("app.core.prompt_loader")

client = None

# In-process cache: (name, version) → (text, commit_hash)
_cache: dict[str, tuple[str, str]] = {}


def _get_client() -> Client | None:
    global client
    if client is None:
        client = Client()
    return client


def load_prompt(prompt_name: str, version: str = "latest") -> tuple[str, str]:
    """
    Load a prompt from LangSmith Prompt Hub.
    Results are cached in-process — LangSmith is only called once per (name, version).
    """
    cache_key = f"{prompt_name}:{version}"
    if cache_key in _cache:
        return _cache[cache_key]

    try:
        prompt_client = _get_client()
        if prompt_client is None:
            return None, None

        prompt = prompt_client.pull_prompt(f"{prompt_name}:{version}")

        system_text = ""
        for msg in prompt.messages:
            if hasattr(msg, "prompt"):
                system_text = msg.prompt.template
                break

        commit_hash = version if version != "latest" else "latest"
        result = (system_text, commit_hash)
        _cache[cache_key] = result
        logger.info(f"Loaded prompt | name={prompt_name} | version={version}")
        return result

    except Exception as e:
        logger.error(f"Failed to load prompt {prompt_name}: {str(e)}")
        return None, None


def prewarm_prompts() -> None:
    """Call at app startup to fetch all prompts before the first request arrives."""
    if os.getenv("PYTEST_CURRENT_TEST") or os.getenv("CI", "").lower() in {"1", "true", "yes"}:
        return

    for name, version in PROMPT_VERSIONS.items():
        text, _ = load_prompt(name, version)
        status = "ok" if text else "failed (will use fallback)"
        logger.info(f"Prompt pre-warm | {name} | {status}")


# Prompt version config — set env var to a commit hash to pin a specific version.
# "latest" always uses the newest push.
#
# product-extraction-prompt commits:
#   76fc2fcdbb31ca3c  ← v2 compressed rules (current latest)
#   fe87f99f7100f833  ← v1 original
#
# router-classification-prompt commits:
#   7407d626586f4ce0  ← v2 compressed rules (current latest)
#   1d5d71f9f6570a6f  ← v1 original
#
# To roll back: set env var to the v1 hash, e.g.
#   PRODUCT_EXTRACTION_PROMPT_VERSION=fe87f99f7100f833
#   ROUTER_PROMPT_VERSION=1d5d71f9f6570a6f
PROMPT_VERSIONS = {
    "router-classification-prompt": os.getenv("ROUTER_PROMPT_VERSION", "latest"),
    "support-classification-prompt": os.getenv("SUPPORT_PROMPT_VERSION", "latest"),
    "support-resolution-prompt": os.getenv("SUPPORT_RESOLUTION_PROMPT_VERSION", "latest"),
    "order-response-prompt": os.getenv("ORDER_RESPONSE_PROMPT_VERSION", "latest"),
    "product-extraction-prompt": os.getenv("PRODUCT_EXTRACTION_PROMPT_VERSION", "latest"),
}
