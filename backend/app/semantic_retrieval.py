"""Opt-in embeddings for attached material passages.

The cache is scoped through MaterialService's owner checks. Missing credentials,
API errors, and oversized sets leave ordinary lexical retrieval available.
"""
from __future__ import annotations

import hashlib
import json
import math
import os

import httpx
from sqlalchemy import text, bindparam


def configured_model() -> str | None:
    configured = os.getenv("AI_TUTOR_EMBEDDING_MODEL", "").strip()
    # Embeddings send learner material to an external service, so deployments
    # must explicitly opt in by naming a model. A key alone is insufficient.
    if not configured or configured.lower() in {"off", "disabled", "none"}:
        return None
    provider = os.getenv("AI_TUTOR_PROVIDER", "").strip().lower()
    if provider == "openrouter":
        return (configured if "/" in configured else f"openai/{configured}") if os.getenv("OPENROUTER_API_KEY") else None
    if provider == "openai":
        return configured if os.getenv("OPENAI_API_KEY") else None
    if os.getenv("OPENROUTER_API_KEY"):
        return configured if "/" in configured else f"openai/{configured}"
    return configured if os.getenv("OPENAI_API_KEY") else None


def _embed(texts: list[str], model: str) -> list[list[float]]:
    openrouter = "/" in model
    response = httpx.post(
        "https://openrouter.ai/api/v1/embeddings" if openrouter else "https://api.openai.com/v1/embeddings",
        headers={"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY' if openrouter else 'OPENAI_API_KEY']}"},
        json={"model": model, "input": texts}, timeout=30.0,
    )
    response.raise_for_status()
    data = sorted(response.json()["data"], key=lambda item: item["index"])
    vectors = [item["embedding"] for item in data]
    if len(vectors) != len(texts) or not all(isinstance(vector, list) and vector for vector in vectors):
        raise ValueError("Invalid embedding response")
    return vectors


def _cosine(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        return 0.0
    norm = math.sqrt(sum(value * value for value in left) * sum(value * value for value in right))
    return sum(a * b for a, b in zip(left, right)) / norm if norm else 0.0


def similarity_scores(store, query: str, blocks: list[dict], model: str, *, max_blocks: int = 32) -> dict[str, float]:
    """Embed and rank an authorized bounded set; callers enforce ownership first."""
    if not query.strip() or not blocks or len(blocks) > max_blocks:
        return {}
    ids = [block["id"] for block in blocks]
    with store.engine.connect() as connection:
        statement = text("SELECT block_id,text_hash,vector_json FROM material_embeddings WHERE model=:model AND block_id IN :ids")
        rows = connection.execute(statement.bindparams(bindparam("ids", expanding=True)),
                                  {"model": model, "ids": ids}).mappings().all()
    cached = {row["block_id"]: row for row in rows}
    vectors: dict[str, list[float]] = {}
    missing = []
    for block in blocks:
        digest = hashlib.sha256(block["text"].encode("utf-8")).hexdigest()
        row = cached.get(block["id"])
        if row and row["text_hash"] == digest:
            vectors[block["id"]] = json.loads(row["vector_json"])
        else:
            missing.append((block, digest))
    for offset in range(0, len(missing), 32):
        batch = missing[offset:offset + 32]
        embeddings = _embed([block["text"][:8000] for block, _ in batch], model)
        with store.transaction() as connection:
            for (block, digest), vector in zip(batch, embeddings):
                vectors[block["id"]] = vector
                connection.execute(text("DELETE FROM material_embeddings WHERE block_id=:id AND model=:model"),
                                   {"id": block["id"], "model": model})
                connection.execute(text("INSERT INTO material_embeddings(block_id,model,text_hash,vector_json) VALUES(:id,:model,:digest,:vector)"),
                                   {"id": block["id"], "model": model, "digest": digest,
                                    "vector": json.dumps(vector, separators=(",", ":"))})
    query_vector = _embed([query[:8000]], model)[0]
    return {block_id: _cosine(query_vector, vector) for block_id, vector in vectors.items()}


def note_similarity_scores(store, query: str, notes: list, model: str, *, max_notes: int = 32) -> dict[str, float]:
    """Score already owner/course-filtered note records, caching by content hash."""
    if not query.strip() or not notes or len(notes) > max_notes:
        return {}
    ids = [note.id for note in notes]
    with store.engine.connect() as connection:
        statement = text("SELECT note_id,content_hash,vector_json FROM workspace_note_embeddings WHERE model=:model AND note_id IN :ids")
        rows = connection.execute(statement.bindparams(bindparam("ids", expanding=True)),
                                  {"model": model, "ids": ids}).mappings().all()
    cached = {row["note_id"]: row for row in rows}
    vectors = {}
    missing = []
    for note in notes:
        content = f"{note.title}\n{note.body}"
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        row = cached.get(note.id)
        if row and row["content_hash"] == digest:
            vectors[note.id] = json.loads(row["vector_json"])
        else:
            missing.append((note, digest, content[:8000]))
    for offset in range(0, len(missing), 32):
        batch = missing[offset:offset + 32]
        embeddings = _embed([content for _, _, content in batch], model)
        with store.transaction() as connection:
            for (note, digest, _), vector in zip(batch, embeddings):
                vectors[note.id] = vector
                connection.execute(text("DELETE FROM workspace_note_embeddings WHERE note_id=:id AND model=:model"),
                                   {"id": note.id, "model": model})
                connection.execute(text("INSERT INTO workspace_note_embeddings(note_id,model,content_hash,vector_json) VALUES(:id,:model,:digest,:vector)"),
                                   {"id": note.id, "model": model, "digest": digest,
                                    "vector": json.dumps(vector, separators=(",", ":"))})
    query_vector = _embed([query[:8000]], model)[0]
    return {note_id: _cosine(query_vector, vector) for note_id, vector in vectors.items()}
