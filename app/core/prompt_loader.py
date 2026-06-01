"""Load prompts from LangSmith Prompt Hub at runtime"""

import os
from langsmith import Client
from app.core.logger import get_logger

logger = get_logger("app.core.prompt_loader")

client = Client()

# In-process cache: (name, version) → (text, commit_hash)
_cache: dict[str, tuple[str, str]] = {}


def load_prompt(prompt_name: str, version: str = "latest") -> tuple[str, str]:
    """
    Load a prompt from LangSmith Prompt Hub.
    Results are cached in-process — LangSmith is only called once per (name, version).
    """
    cache_key = f"{prompt_name}:{version}"
    if cache_key in _cache:
        return _cache[cache_key]

    try:
        prompt = client.pull_prompt(f"{prompt_name}:{version}")

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
    for name, version in PROMPT_VERSIONS.items():
        text, _ = load_prompt(name, version)
        status = "ok" if text else "failed (will use fallback)"
        logger.info(f"Prompt pre-warm | {name} | {status}")


# Prompt version config — change version here to switch without code change
PROMPT_VERSIONS = {
    "router-classification-prompt": os.getenv("ROUTER_PROMPT_VERSION", "latest"),
    "support-classification-prompt": os.getenv("SUPPORT_PROMPT_VERSION", "latest"),
}
