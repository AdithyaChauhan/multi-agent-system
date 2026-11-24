"""
Targeted coverage tests for support_agent.py, order_agent_subgraph.py,
and order_agent.py uncovered branches.
"""

import pytest
from unittest.mock import MagicMock, patch

# ── order_agent_subgraph ─────────────────────────────────────────────────────


# ── order_agent ──────────────────────────────────────────────────────────────


# ── support_agent ─────────────────────────────────────────────────────────────


# ── prompt_loader ────────────────────────────────────────────────────────────


class TestPromptLoader:
    def test_loads_prompt_from_disk(self):
        from app.core.prompt_loader import load_prompt, PROMPTS_DIR

        assert (PROMPTS_DIR / "router.md").exists()
        assert load_prompt("router") == (PROMPTS_DIR / "router.md").read_text(encoding="utf-8").strip()

    def test_fills_placeholders_but_keeps_json_braces(self, tmp_path, monkeypatch):
        import app.core.prompt_loader as loader

        (tmp_path / "t.md").write_text('Catalog:\n{catalog}\nExample: {"a": 1}\n', encoding="utf-8")
        monkeypatch.setattr(loader, "PROMPTS_DIR", tmp_path)
        loader._read.cache_clear()
        try:
            assert loader.load_prompt("t", catalog="tv | mouse") == 'Catalog:\ntv | mouse\nExample: {"a": 1}'
        finally:
            loader._read.cache_clear()

    def test_missing_prompt_raises(self):
        import pytest
        from app.core.prompt_loader import load_prompt

        with pytest.raises(FileNotFoundError):
            load_prompt("__no_such_prompt__")


# ── product_agent extra branches ─────────────────────────────────────────────
