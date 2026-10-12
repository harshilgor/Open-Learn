"""Durable tool-call, receipt, alias, and cache persistence with scope checks."""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

from sqlalchemy import text

from ..material_service import encoded, uid
from .clock import Clock, SystemClock
from .lifecycle import ToolCallState, transition
from .models import (
    AuthScope,
    EvidencePacket,
    EvidenceSourceKind,
    StoredWebEvidence,
    TrustLabel,
    SourceClassification,
)
from .redact import redact_mapping


class AuthorizationError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class WebEvidenceStore:
    def __init__(self, store, clock: Clock | None = None):
        self.store = store
        self.clock = clock or SystemClock()

    def new_tool_call_id(self) -> str:
        return uid("toolcall")

    def new_evidence_id(self) -> str:
        return uid("webev")

    def new_bundle_id(self) -> str:
        return uid("webbundle")

    def create_tool_call(
        self,
        *,
        auth: AuthScope,
        response_bundle_id: str,
        tool_name: str,
        idempotency_key: str,
        policy_version: str,
        feature_version: str,
        source_policy_fingerprint: str,
        payload: dict[str, Any],
    ) -> tuple[str, ToolCallState, dict[str, Any] | None]:
        """Create or return an idempotent prior result. Never trusts model success claims."""
        now = self.clock.now()
        existing = self.get_tool_call_by_idempotency(auth.learner_id, idempotency_key)
        if existing is not None:
            return existing["id"], ToolCallState(existing["state"]), existing.get("result")

        tool_call_id = self.new_tool_call_id()
        safe_payload = redact_mapping(payload)
        with self.store.transaction() as connection:
            connection.execute(
                text(
                    "INSERT INTO web_tool_calls("
                    "id,owner_id,tenant_id,course_id,session_id,response_bundle_id,tool_name,state,"
                    "idempotency_key,policy_version,feature_version,source_policy_fingerprint,"
                    "request_id,conversation_id,trace_id,payload,created_at,updated_at"
                    ") VALUES ("
                    ":id,:owner,:tenant,:course,:sid,:bundle,:tool,:state,"
                    ":idem,:pv,:fv,:fp,:rid,:cid,:tid,:payload,:created,:updated)"
                ),
                {
                    "id": tool_call_id,
                    "owner": auth.learner_id,
                    "tenant": auth.tenant_id,
                    "course": auth.course_id,
                    "sid": auth.session_id,
                    "bundle": response_bundle_id,
                    "tool": tool_name,
                    "state": ToolCallState.proposed.value,
                    "idem": idempotency_key,
                    "pv": policy_version,
                    "fv": feature_version,
                    "fp": source_policy_fingerprint,
                    "rid": auth.request_id,
                    "cid": auth.conversation_id,
                    "tid": auth.trace_id,
                    "payload": encoded(safe_payload),
                    "created": now,
                    "updated": now,
                },
            )
        return tool_call_id, ToolCallState.proposed, None

    def get_tool_call_by_idempotency(self, owner_id: str, idempotency_key: str) -> dict[str, Any] | None:
        with self.store.engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT id,state,payload FROM web_tool_calls "
                    "WHERE owner_id=:owner AND idempotency_key=:idem"
                ),
                {"owner": owner_id, "idem": idempotency_key},
            ).first()
        if row is None:
            return None
        payload = json.loads(row[2])
        return {"id": row[0], "state": row[1], "result": payload.get("result")}

    def set_tool_state(
        self,
        tool_call_id: str,
        *,
        owner_id: str,
        current: ToolCallState,
        nxt: ToolCallState,
        result: dict[str, Any] | None = None,
    ) -> ToolCallState:
        new_state = transition(current, nxt)
        now = self.clock.now()
        with self.store.transaction() as connection:
            row = connection.execute(
                text(
                    "SELECT payload FROM web_tool_calls WHERE id=:id AND owner_id=:owner"
                ),
                {"id": tool_call_id, "owner": owner_id},
            ).first()
            if row is None:
                raise AuthorizationError("tool_call_not_found")
            payload = json.loads(row[0])
            if result is not None:
                payload["result"] = redact_mapping(result)
            connection.execute(
                text(
                    "UPDATE web_tool_calls SET state=:state, payload=:payload, updated_at=:ts "
                    "WHERE id=:id AND owner_id=:owner"
                ),
                {
                    "state": new_state.value,
                    "payload": encoded(payload),
                    "ts": now,
                    "id": tool_call_id,
                    "owner": owner_id,
                },
            )
        return new_state

    def save_receipt(self, record: StoredWebEvidence, *, alias: str) -> None:
        with self.store.transaction() as connection:
            connection.execute(
                text(
                    "INSERT INTO web_evidence_receipts("
                    "id,owner_id,tenant_id,course_id,session_id,response_bundle_id,tool_call_id,"
                    "source_policy_fingerprint,source_kind,provider,provider_result_ref,trust_label,"
                    "title,canonical_url,domain,author,published_date,excerpt,classification,"
                    "relevance_score,span_id,version_id,page_index,open_count,created_at,expires_at,deleted_at"
                    ") VALUES ("
                    ":id,:owner,:tenant,:course,:sid,:bundle,:tool,"
                    ":fp,:kind,:provider,:pref,:trust,"
                    ":title,:url,:domain,:author,:published,:excerpt,:classification,"
                    ":score,:span,:version,:page,:opens,:created,:expires,NULL)"
                ),
                {
                    "id": record.evidence_id,
                    "owner": record.owner_id,
                    "tenant": record.tenant_id,
                    "course": record.course_id,
                    "sid": record.session_id,
                    "bundle": record.response_bundle_id,
                    "tool": record.tool_call_id,
                    "fp": record.source_policy_fingerprint,
                    "kind": record.source_kind.value,
                    "provider": record.provider,
                    "pref": record.provider_result_ref,
                    "trust": record.trust_label.value,
                    "title": record.title,
                    "url": record.canonical_url,
                    "domain": record.domain,
                    "author": record.author,
                    "published": record.published_date,
                    "excerpt": record.excerpt,
                    "classification": record.source_classification.value,
                    "score": record.relevance_score,
                    "span": record.span_id,
                    "version": record.version_id,
                    "page": record.page_index,
                    "opens": record.open_count,
                    "created": record.created_at,
                    "expires": record.expires_at,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO web_evidence_aliases("
                    "response_bundle_id,alias,evidence_id,owner_id,tenant_id,session_id,source_policy_fingerprint"
                    ") VALUES (:bundle,:alias,:eid,:owner,:tenant,:sid,:fp)"
                ),
                {
                    "bundle": record.response_bundle_id,
                    "alias": alias,
                    "eid": record.evidence_id,
                    "owner": record.owner_id,
                    "tenant": record.tenant_id,
                    "sid": record.session_id,
                    "fp": record.source_policy_fingerprint,
                },
            )

    def authorize_receipt(
        self,
        *,
        auth: AuthScope,
        evidence_id: str | None = None,
        alias: str | None = None,
        response_bundle_id: str | None = None,
        source_policy_fingerprint: str,
        now=None,
    ) -> StoredWebEvidence:
        """Authorize by full scope — never by evidence ID alone."""
        now = now or self.clock.now()
        resolved_id = evidence_id
        if alias is not None:
            if response_bundle_id is None:
                raise AuthorizationError("evidence_scope_mismatch")
            with self.store.engine.connect() as connection:
                row = connection.execute(
                    text(
                        "SELECT evidence_id FROM web_evidence_aliases "
                        "WHERE response_bundle_id=:bundle AND alias=:alias "
                        "AND owner_id=:owner AND tenant_id=:tenant AND session_id=:sid "
                        "AND source_policy_fingerprint=:fp"
                    ),
                    {
                        "bundle": response_bundle_id,
                        "alias": alias,
                        "owner": auth.learner_id,
                        "tenant": auth.tenant_id,
                        "sid": auth.session_id,
                        "fp": source_policy_fingerprint,
                    },
                ).first()
            if row is None:
                raise AuthorizationError("evidence_scope_mismatch")
            resolved_id = row[0]
        if not resolved_id:
            raise AuthorizationError("evidence_not_found")

        with self.store.engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT id,owner_id,tenant_id,course_id,session_id,response_bundle_id,tool_call_id,"
                    "source_policy_fingerprint,source_kind,provider,provider_result_ref,trust_label,"
                    "title,canonical_url,domain,author,published_date,excerpt,classification,"
                    "relevance_score,span_id,version_id,page_index,open_count,created_at,expires_at,deleted_at "
                    "FROM web_evidence_receipts WHERE id=:id"
                ),
                {"id": resolved_id},
            ).first()
        if row is None:
            raise AuthorizationError("evidence_not_found")
        if row[26] is not None:
            raise AuthorizationError("evidence_expired")
        if row[1] != auth.learner_id or row[2] != auth.tenant_id or row[4] != auth.session_id:
            raise AuthorizationError("evidence_scope_mismatch")
        if row[7] != source_policy_fingerprint:
            raise AuthorizationError("evidence_scope_mismatch")
        expires = row[25]
        if isinstance(expires, str):
            from datetime import datetime, timezone
            expires = datetime.fromisoformat(expires)
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
        elif getattr(expires, "tzinfo", None) is None:
            from datetime import timezone
            expires = expires.replace(tzinfo=timezone.utc)
        if expires < now:
            raise AuthorizationError("evidence_expired")
        return StoredWebEvidence(
            evidence_id=row[0],
            owner_id=row[1],
            tenant_id=row[2],
            course_id=row[3],
            session_id=row[4],
            response_bundle_id=row[5],
            tool_call_id=row[6],
            source_policy_fingerprint=row[7],
            source_kind=EvidenceSourceKind(row[8]),
            provider=row[9],
            provider_result_ref=row[10],
            trust_label=TrustLabel(row[11]),
            title=row[12],
            canonical_url=row[13],
            domain=row[14],
            author=row[15],
            published_date=row[16],
            excerpt=row[17],
            source_classification=SourceClassification(row[18]),
            relevance_score=row[19],
            span_id=row[20],
            version_id=row[21],
            page_index=row[22],
            open_count=int(row[23] or 0),
            created_at=row[24],
            expires_at=expires,
            deleted_at=row[26],
            retrieval_session_id=row[5],
            citation_label="",
        )

    def bump_open_count(self, evidence_id: str, owner_id: str) -> None:
        with self.store.transaction() as connection:
            connection.execute(
                text(
                    "UPDATE web_evidence_receipts SET open_count=open_count+1 "
                    "WHERE id=:id AND owner_id=:owner AND deleted_at IS NULL"
                ),
                {"id": evidence_id, "owner": owner_id},
            )

    def list_bundle_packets(
        self,
        *,
        auth: AuthScope,
        response_bundle_id: str,
        source_policy_fingerprint: str,
    ) -> list[EvidencePacket]:
        with self.store.engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT a.alias, r.id, r.response_bundle_id, r.tool_call_id, r.source_kind, r.provider, "
                    "r.title, r.canonical_url, r.domain, r.author, r.published_date, r.excerpt, "
                    "r.classification, r.relevance_score, r.trust_label, r.span_id, r.version_id, "
                    "r.page_index, r.created_at, r.source_policy_fingerprint "
                    "FROM web_evidence_aliases a "
                    "JOIN web_evidence_receipts r ON r.id=a.evidence_id "
                    "WHERE a.response_bundle_id=:bundle AND a.owner_id=:owner AND a.tenant_id=:tenant "
                    "AND a.session_id=:sid AND a.source_policy_fingerprint=:fp "
                    "AND r.deleted_at IS NULL "
                    "ORDER BY a.alias"
                ),
                {
                    "bundle": response_bundle_id,
                    "owner": auth.learner_id,
                    "tenant": auth.tenant_id,
                    "sid": auth.session_id,
                    "fp": source_policy_fingerprint,
                },
            ).fetchall()
        packets: list[EvidencePacket] = []
        for row in rows:
            packets.append(
                EvidencePacket(
                    evidence_id=row[1],
                    alias=row[0],
                    retrieval_session_id=row[2],
                    response_bundle_id=row[2],
                    tool_call_id=row[3],
                    source_kind=EvidenceSourceKind(row[4]),
                    provider=row[5],
                    title=row[6],
                    canonical_url=row[7],
                    domain=row[8],
                    author=row[9],
                    published_date=row[10],
                    excerpt=row[11],
                    source_classification=SourceClassification(row[12]),
                    relevance_score=row[13],
                    citation_label=row[0],
                    trust_label=TrustLabel(row[14]),
                    span_id=row[15],
                    version_id=row[16],
                    page_index=row[17],
                    retrieved_at=row[18],
                    source_policy_fingerprint=row[19],
                )
            )
        return packets

    def cache_key(self, digest: str) -> str:
        return f"webcache_{digest}"

    def get_cache(self, cache_key: str, *, tenant_id: str, fingerprint: str) -> list[dict] | None:
        with self.store.engine.connect() as connection:
            row = connection.execute(
                text("SELECT payload FROM context_records WHERE id=:id AND kind='web_evidence_cache'"),
                {"id": cache_key},
            ).first()
        if row is None:
            return None
        data = json.loads(row[0])
        if data.get("tenantId") != tenant_id or data.get("fingerprint") != fingerprint:
            return None
        expires = data.get("expiresAt")
        if not expires:
            return None
        from datetime import datetime, timezone
        exp = datetime.fromisoformat(expires)
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if exp < self.clock.now():
            return None
        return data.get("hits")

    def cached_search(
        self,
        cache_key: str,
        *,
        owner_id: str,
        tenant_id: str,
        fingerprint: str,
        ttl_seconds: int,
        loader,
    ) -> list[dict]:
        """Return provider hits, from Redis when enabled, else the SQL cache.

        The key already binds tenant and source-policy fingerprint; Redis scope
        is the hashed tenant. Concurrent misses share one billed provider call.
        """
        from ..cache import get_or_load, json_codec, namespace_active, owner_scope
        if ttl_seconds > 0 and namespace_active("web_evidence"):
            return get_or_load("web_evidence", owner_scope("tenant:" + tenant_id),
                               {"key": cache_key, "fingerprint": fingerprint}, loader,
                               ttl_seconds=ttl_seconds, single_flight=True, **json_codec())
        cached = self.get_cache(cache_key, tenant_id=tenant_id, fingerprint=fingerprint)
        if cached is not None:
            return cached
        hits = loader()
        self.put_cache(cache_key, owner_id=owner_id, tenant_id=tenant_id, fingerprint=fingerprint,
                       hits=hits, ttl_seconds=ttl_seconds)
        return hits

    def put_cache(
        self,
        cache_key: str,
        *,
        owner_id: str,
        tenant_id: str,
        fingerprint: str,
        hits: list[dict],
        ttl_seconds: int,
    ) -> None:
        if ttl_seconds <= 0:
            return
        expires = self.clock.now() + timedelta(seconds=ttl_seconds)
        payload = {
            "hits": hits,
            "tenantId": tenant_id,
            "fingerprint": fingerprint,
            "expiresAt": expires.isoformat(),
        }
        with self.store.transaction() as connection:
            connection.execute(
                text("DELETE FROM context_records WHERE id=:id AND kind='web_evidence_cache'"),
                {"id": cache_key},
            )
            connection.execute(
                text(
                    "INSERT INTO context_records(id,owner_id,kind,session_id,sequence,payload) "
                    "VALUES(:id,:owner,'web_evidence_cache',NULL,0,:payload)"
                ),
                {"id": cache_key, "owner": owner_id, "payload": encoded(payload)},
            )
