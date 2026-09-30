"""Embedding cache and semantic ranking contract without external API calls."""
from contextlib import contextmanager

from sqlalchemy import create_engine, text
import httpx

from backend.app import semantic_retrieval
from backend.app import automatic_note_context
from types import SimpleNamespace


def test_embedding_model_requires_explicit_opt_in(monkeypatch):
    monkeypatch.setenv("AI_TUTOR_PROVIDER", "openai")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "configured")
    monkeypatch.delenv("AI_TUTOR_EMBEDDING_MODEL", raising=False)
    assert semantic_retrieval.configured_model() is None
    monkeypatch.setenv("AI_TUTOR_EMBEDDING_MODEL", "text-embedding-3-small")
    assert semantic_retrieval.configured_model() == "text-embedding-3-small"
    monkeypatch.delenv("OPENAI_API_KEY")
    assert semantic_retrieval.configured_model() is None


def test_openrouter_embedding_uses_existing_key_and_model_slug(monkeypatch):
    monkeypatch.setenv("AI_TUTOR_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-router-key")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("AI_TUTOR_EMBEDDING_MODEL", "text-embedding-3-small")
    model = semantic_retrieval.configured_model()
    assert model == "openai/text-embedding-3-small"
    captured = {}

    def post(url, **kwargs):
        captured.update(url=url, **kwargs)
        return httpx.Response(200, request=httpx.Request("POST", url), json={
            "data": [{"index": 0, "embedding": [1.0, 0.0]}]})

    monkeypatch.setattr(httpx, "post", post)
    assert semantic_retrieval._embed(["sample"], model) == [[1.0, 0.0]]
    assert captured["url"] == "https://openrouter.ai/api/v1/embeddings"
    assert captured["headers"]["Authorization"] == "Bearer test-router-key"


class MemoryStore:
    def __init__(self):
        self.engine = create_engine("sqlite://")
        with self.engine.begin() as connection:
            connection.execute(text("CREATE TABLE material_embeddings (block_id TEXT, model TEXT, text_hash TEXT, vector_json TEXT, PRIMARY KEY (block_id, model))"))

    @contextmanager
    def transaction(self):
        with self.engine.begin() as connection:
            yield connection


def test_semantic_scores_cache_passages_and_embed_query_each_time(monkeypatch):
    store = MemoryStore()
    calls = []

    def embed(texts, model):
        calls.append(list(texts))
        vectors = {"apple fruit": [1.0, 0.0], "banana fruit": [0.0, 1.0],
                   "fruit like apple": [1.0, 0.0], "fruit like banana": [0.0, 1.0]}
        return [vectors[item] for item in texts]

    monkeypatch.setattr(semantic_retrieval, "_embed", embed)
    blocks = [{"id": "a", "text": "apple fruit"}, {"id": "b", "text": "banana fruit"}]
    first = semantic_retrieval.similarity_scores(store, "fruit like apple", blocks, "test-model")
    second = semantic_retrieval.similarity_scores(store, "fruit like banana", blocks, "test-model")
    assert first["a"] > first["b"]
    assert second["b"] > second["a"]
    assert calls == [["apple fruit", "banana fruit"], ["fruit like apple"], ["fruit like banana"]]


def test_oversized_corpus_skips_semantic_request(monkeypatch):
    monkeypatch.setattr(semantic_retrieval, "_embed", lambda *_: (_ for _ in ()).throw(AssertionError("API used")))
    blocks = [{"id": str(index), "text": "passage"} for index in range(3)]
    assert semantic_retrieval.similarity_scores(MemoryStore(), "query", blocks, "test-model", max_blocks=2) == {}


def test_note_retrieval_scopes_before_embedding_and_excludes_explicit_selection(monkeypatch):
    summaries = [
        SimpleNamespace(id="match", title="Mechanics", frontmatter={"course_id": "course-a"}),
        SimpleNamespace(id="other-course", title="Mechanics", frontmatter={"course_id": "course-b"}),
        SimpleNamespace(id="explicit", title="Mechanics", frontmatter={"course_id": "course-a"}),
    ]
    class FakeService:
        def __init__(self, store):
            pass
        def search(self, owner, term, limit=10):
            assert owner == "owner-a"
            return summaries
        def list(self, owner):
            assert owner == "owner-a"
            return summaries
        def get(self, owner, note_id):
            assert owner == "owner-a"
            return SimpleNamespace(id=note_id, title="Mechanics", revision=1, body="The force causes motion.")
    seen = []
    def score(store, query, notes, model):
        seen.extend(note.id for note in notes)
        return {"match": 0.9}
    monkeypatch.setattr(automatic_note_context, "WorkspaceNoteService", FakeService)
    monkeypatch.setattr(automatic_note_context, "configured_model", lambda: "test-model")
    monkeypatch.setattr(automatic_note_context, "note_similarity_scores", score)
    results = automatic_note_context.retrieve_relevant_notes(object(), "owner-a", "force mechanics", "course-a", {"explicit"})
    assert seen == ["match"]
    assert [item["noteId"] for item in results] == ["match"]
    assert results[0]["retrieval"] == "hybrid_embedding"
