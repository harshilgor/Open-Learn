"""Bounded authorized retrieval and canonical learner evidence."""
import re
import hashlib
import json
import math
from collections import Counter
import httpx
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from .material_service import MaterialService, uid, encoded, problem
from .policy_models import LearnerEvidenceProjection, ConceptEvidence
from .state_service import LearnerStateService
from .semantic_retrieval import configured_model, similarity_scores


def canonical_evidence(store, owner, graph):
    states = [s for s in LearnerStateService(store).get_state(owner).states if s.graph_id == graph.id and s.graph_version == graph.version]
    by_id = {s.concept_id: s for s in states}
    concepts = []
    for concept in graph.concepts:
        state = by_id.get(concept.id)
        status = state.status.value if state else "unexplored"
        concepts.append(ConceptEvidence(concept_id=concept.id, state="explored" if status == "exposed" else status,
            evidence_count=int(bool(state and state.last_evidence_id)), demonstrated=status == "demonstrated",
            evidence_ids=[state.last_evidence_id] if state and state.last_evidence_id else []))
    return LearnerEvidenceProjection(learner_id=owner, state_version=max((s.version for s in states), default=0), concepts=concepts)


def retrieve(store, owner, sid, query, byte_budget=16000, selected_span_ids=None, metadata_scope=None):
    """Resolve attached passages with an optional explicit selection boundary."""
    service = MaterialService(store)
    selected_span_ids = list(selected_span_ids or [])
    if len(set(selected_span_ids)) != len(selected_span_ids):
        problem("duplicate_source_selection", "A passage may be selected only once.")
    attached = set(service.attachments(owner, sid))
    session = service.session(owner, sid)
    course_id = getattr(session, "course_id", None)
    if selected_span_ids:
        selected = []
        for span_id in selected_span_ids:
            block = service.source(owner, span_id)
            if block["versionId"] not in attached:
                problem("source_not_attached", "Select passages only from material attached to this conversation.", 409)
            version = service.version(owner, block["versionId"])
            if course_id and version.get("courseId") not in {None, course_id}:
                problem("source_outside_course", "Select material from this course or general references.", 409)
            if version["role"] in {"answer_key", "sample_paper"} or version["status"] not in {"ready", "partially_ready"} or block["kind"] == "private_solution":
                problem("source_unavailable", "That passage cannot support teaching or assessment.", 409)
            selected.append({"spanId": block["id"], "versionId": block["versionId"], "pageIndex": block["pageIndex"], "title": version["title"], "text": block["text"], "retrieval": "explicit_selection", "relevanceScore": 1.0})
        if sum(len(item["text"].encode("utf-8")) for item in selected) > byte_budget:
            problem("source_budget_exceeded", "Selected passages exceed the context budget. Choose fewer passages.")
        return selected
    terms = set(re.findall(r"\w{3,}", query.lower()))
    candidates = []
    for vid in sorted(attached):
        version = service.version(owner, vid)
        # Course sessions may use general reference material and their own
        # course materials, but do not silently mix in another course.
        if course_id and version.get("courseId") not in {None, course_id}:
            continue
        if version["role"] in {"answer_key", "sample_paper"} or version["status"] not in {"ready", "partially_ready"}:
            continue
        for block in service.blocks(owner, vid):
            if block["kind"] == "private_solution":
                continue
            words = Counter(re.findall(r"\w{3,}", block["text"].lower()))
            candidates.append((block, version["title"], words))
    model = configured_model()
    semantic_scores = {}
    if model:
        try:
            semantic_scores = similarity_scores(store, query, [block for block, _, _ in candidates], model)
        except (httpx.HTTPError, SQLAlchemyError, ValueError, KeyError, TypeError, OSError):
            semantic_scores = {}
    document_frequency = Counter(term for _, _, words in candidates for term in terms & words.keys())
    count = len(candidates)
    query_phrase = query.strip().lower()
    ranked = []
    for block, title, words in candidates:
        # Rare query terms and term frequency improve ranking over overlap count.
        # Length normalization prevents long extracted pages from dominating.
        score = sum((1 + math.log1p(words[term])) * math.log1p((count + 1) / (document_frequency[term] + 1))
                    for term in terms & words.keys()) / (1 + math.log1p(sum(words.values())) / 10)
        if len(query_phrase) >= 8 and query_phrase in block["text"].lower():
            score += 3
        if score > 0 or semantic_scores.get(block["id"], 0) > 0.15:
            ranked.append((score, block, title))
    ranked = rerank_passages(ranked, query, semantic_scores, metadata_scope)
    selected, used = [], 0
    for _, block, title, score, semantic_score, metadata_score in ranked:
        cost = len(block["text"].encode("utf-8")) + len(title.encode("utf-8")) + 200
        if used + cost > byte_budget:
            continue
        selected.append({"spanId": block["id"], "versionId": block["versionId"], "pageIndex": block["pageIndex"], "title": title, "text": block["text"],
                         "retrieval": "hybrid_embedding" if semantic_scores else "lexical_ranked",
                         "lexicalScore": round(score, 4), "semanticScore": round(semantic_score, 4) if semantic_scores else None,
                         "metadataScore": round(metadata_score, 4),
                         "relevanceScore": round(score + 0.45 * semantic_score + 0.1 * metadata_score, 4)})
        used += cost
        if len(selected) == 6:
            break
    return selected


def rerank_passages(candidates, query: str, semantic_scores: dict[str, float] | None = None,
                    metadata_scope: dict | None = None):
    """Second-stage deterministic ranking over already authorized candidates.

    Metadata boosts relevance only. Attachment, owner, course, and source role
    checks happen before this stage and cannot be bypassed by a score.
    """
    semantic_scores = semantic_scores or {}
    terms = set(re.findall(r"[a-z0-9]{3,}", query.lower()))
    metadata_scope = metadata_scope or {}
    lexical_max = max((score for score, _, _ in candidates), default=0.0)
    reranked = []
    for lexical, block, title in candidates:
        semantic = max(0.0, min(1.0, float(semantic_scores.get(block["id"], 0.0))))
        metadata = " ".join(str(block.get(key, "")) for key in
                             ("heading", "section", "sectionId", "sectionTitle", "lessonId",
                              "lessonTitle", "conceptId", "conceptIds", "conceptTitle", "courseId"))
        metadata_terms = set(re.findall(r"[a-z0-9]{3,}", f"{title} {metadata}".lower()))
        metadata_relevance = len(terms & metadata_terms) / max(1, len(terms))
        # Exact structured IDs/titles carry a stronger signal than incidental
        # text overlap. They remain boosts, since extraction metadata is sparse.
        scope_matches = 0
        for key in ("conceptId", "lessonId", "sectionId", "courseId"):
            expected = metadata_scope.get(key)
            actual = block.get(key)
            actual_values = actual if isinstance(actual, list) else [actual]
            if expected and expected in actual_values:
                scope_matches += 1
        metadata_relevance = min(1.0, metadata_relevance + 0.5 * scope_matches)
        phrase = 1.0 if len(query.strip()) >= 8 and query.strip().lower() in block["text"].lower() else 0.0
        lexical_relevance = (0.75 * lexical / lexical_max if lexical_max else 0.0) + 0.15 * phrase
        final = lexical_relevance + 0.45 * semantic + 0.1 * metadata_relevance
        reranked.append((final, block, title, lexical_relevance, semantic, metadata_relevance))
    reranked.sort(key=lambda item: (-item[0], item[1]["id"]))
    return reranked


def save_manifest(store, owner, sid, query, sources, selected_span_ids=None):
    manifest = {
        "id": uid("context"), "sessionId": sid, "schemaVersion": 1,
        "retrievalMode": "explicit_selection" if selected_span_ids else ("hybrid_embedding" if any(source.get("retrieval") == "hybrid_embedding" for source in sources) else "lexical_ranked"), "evidenceByteBudget": 16000,
        "queryHash": hashlib.sha256(query.encode("utf-8")).hexdigest(),
        "sources": [{key: source[key] for key in ("spanId", "versionId", "pageIndex", "retrieval") if key in source} for source in sources],
        "evidenceBytes": sum(len(source["text"].encode("utf-8")) for source in sources),
        "selectedSpanIds": list(selected_span_ids or []),
        "limitations": ["Text extraction only", "No claim-level verification", "Sample papers and answer keys excluded"]
            + (["Study context is not independently verified"] if any(source.get("retrieval") == "study_context" for source in sources)
               else ["Only attached, learner-owned passages enter this context"])
            + ([] if any(source.get("retrieval") == "hybrid_embedding" for source in sources) else ["No semantic ranking"]),
    }
    with store.transaction() as connection:
        connection.execute(text("INSERT INTO context_records(id,owner_id,kind,session_id,sequence,payload) VALUES(:id,:owner,'retrieval_manifest',:sid,0,:payload)"), {"id": manifest["id"], "owner": owner, "sid": sid, "payload": encoded(manifest)})
    return manifest


def get_manifest(store, owner, manifest_id):
    with store.engine.connect() as connection:
        row = connection.execute(text("SELECT payload FROM context_records WHERE id=:id AND owner_id=:owner AND kind='retrieval_manifest'"), {"id": manifest_id, "owner": owner}).first()
    if row is None:
        problem("context_not_found", "Context is not available", 404)
    manifest = json.loads(row[0])
    service = MaterialService(store)
    service.session(owner, manifest["sessionId"])
    for source in manifest["sources"]:
        version_id = source["versionId"]
        if version_id.startswith("quiz-context:"):
            from .workflow_store import WorkflowStore
            quiz = WorkflowStore(store).read(owner, version_id.removeprefix("quiz-context:"), "quiz")
            if quiz.get("sessionId") != manifest["sessionId"]:
                problem("context_not_found", "Context is not available", 404)
        else:
            service.version(owner, version_id)
    return manifest
