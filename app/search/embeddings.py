"""Text embeddings for hybrid search (ADR 0014): a small local model, no API key, no per-call cost.

Products are embedded from their own words (title, full name, kind and attribute values), never
from our type or category names, so renaming the catalog's sections can't move the vectors.
"""

import os
from functools import lru_cache
from typing import Iterable, List

from app.core.config import EMBEDDING_MODEL

# bge-*-v1.5: short queries match passages better with this instruction in front (model card).
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


@lru_cache(maxsize=1)
def _model():
    from fastembed import TextEmbedding  # imported lazily: unit tests and "type" search never load it

    return TextEmbedding(EMBEDDING_MODEL, cache_dir=os.getenv("FASTEMBED_CACHE_PATH") or None)


def embed_query(text: str) -> List[float]:
    return [float(x) for x in next(iter(_model().embed([QUERY_PREFIX + text])))]


def embed_documents(texts: Iterable[str], batch_size: int = 64) -> List[List[float]]:
    return [[float(x) for x in v] for v in _model().embed(list(texts), batch_size=batch_size)]


def product_document(title: str, name: str, attributes: dict) -> str:
    """What a product is, in its own words: '<title>. <kind>. <name>. <attribute values>'."""
    attributes = attributes or {}
    parts = [title or "", str(attributes.get("kind") or ""), name or ""]
    details = []
    for key, value in attributes.items():
        if key == "kind" or value in (None, False, "", []):
            continue
        if value is True:
            details.append(key.replace("_", " "))
        elif isinstance(value, list):
            details.append(" ".join(map(str, value)))
        else:
            details.append(f"{value} {key.replace('_', ' ')}")
    parts.append(", ".join(details))
    return ". ".join(p for p in parts if p)


def to_pgvector(vector: Iterable[float]) -> str:
    """The text form pgvector reads: '[0.1,0.2,...]'."""
    return "[" + ",".join(f"{x:.6f}" for x in vector) + "]"
