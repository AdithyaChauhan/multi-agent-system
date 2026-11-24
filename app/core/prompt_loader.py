"""System prompts live in app/prompts/<name>.md and are read from disk.

The file in git is the prompt that runs. There is no runtime fetch from the LangSmith hub
and no fallback copy: a missing file raises immediately. LangSmith is used for tracing only.
"""

from functools import lru_cache
from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


@lru_cache(maxsize=None)
def _read(name: str) -> str:
    return (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8").strip()


def load_prompt(name: str, **values: str) -> str:
    """Return prompt `name`, replacing each `{key}` placeholder with values[key].

    Plain replacement (not str.format) so JSON examples in the prompt keep their braces.
    """
    text = _read(name)
    for key, value in values.items():
        text = text.replace("{" + key + "}", value)
    return text
