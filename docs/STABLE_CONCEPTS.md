# Stable concepts and course mappings

Feature 05 adds an owner-scoped concept service and the `/concepts` review page, linked from course folders. Migration `0032_stable_concepts` follows `0031_evidence_ledger`. API routes use the verified `material_owner` dependency and transactions check the identity deletion fence.

## Identity and review

`StableConcept` extends the shared `ConceptRecord` with title, expected grain, examples and reviewed successor references. IDs are opaque and independent of course names and generated graph nodes. Manually authored personal definitions are reviewed by their owner. All relationship proposals, including model-origin proposals, remain proposed until a separate explicit review request with the current graph revision succeeds. There is no shared curriculum catalog or cross-account editor masquerading as a personal graph.

Course mappings retain wording, aliases, outcome ID, scope, capability and owned source material IDs. Name similarity alone never merges concepts. Resolution checks explicit IDs, then reviewed course aliases/outcomes, then lexical candidates. A bounded optional semantic call can suggest only existing eligible IDs and always requests clarification; provider failure falls back to deterministic clarification. Course-scoped searches never broaden to another course.

Prerequisite, part-of, related and commonly-confused-with relationships retain rationale, provenance and effective revisions. Only reviewed prerequisite edges participate in traversal. Cycle validation is deterministic and graph mutations serialize on an owner revision. Traversal defaults to three levels/twenty candidates, with hard limits of eight levels/one hundred candidates and an explicit truncation flag. Other relationship types do not silently become requirements.

## History and correction

Every graph mutation saves a historical snapshot and invalidates `RevisionRef(kind="concept_graph", id="concept_graph", revision=N)` through DecisionStore. Consumers must pin this reference. Historical reads use `/v1/concepts?revision=N`; displayed quiz content is never rewritten.

Legacy mappings require a node and revision from a graph already imported into the owner's learner graph. They are explicit reviewed mappings, not lexical migration guesses. A mapping correction requires its current mapping revision and retains the old mapping in graph history. Merge redirects retain aliases/provenance and original event IDs. Splits retain uncertain evidence on the original broad concept. Course mappings and relationships involving retired concepts need review; the service does not invent narrower historical attribution.

When feature 06's projection table is available, identity/mapping changes rebuild capability projections in the same transaction. `canonical(owner,id,connection=...)` and `resolve_legacy(owner,graph_id,graph_revision,node_id,connection=...)` let evidence consumers follow reviewed identity while retaining original IDs. Split resolution returns ambiguity. Missing mappings return unmapped.

## Rubric attribution

Immutable question-revision mappings pin criterion IDs, concept/capability links, roles and relevance weights. Criteria must exist in the saved private rubric; the public API never returns private answer-key content. Attribution never treats relevance as a failure probability. A failed multi-concept criterion is ambiguous; no linked concept is automatically penalized. Full success exposes aggregate positive evidence. Partial/unknown attribution requests a discriminating check. These records are consumed by question planning/grading integration, without replacing their owning services.

## User workflow

Users can define concepts, attach course meanings, resolve ambiguous topics, propose/review/reject edges, inspect bounded prerequisites, explicitly map imported nodes, review merges/splits, and submit mapping-error reports. Reports do not mutate relationships. The graph remains personal; students cannot rewrite a shared academic catalog through this surface.

## Inspection

Python source parsed successfully. Web TypeScript checking found no concept-page errors, but the concurrent identity implementation had unresolved `oidc-client-ts` imports and an unknown-value diagnostic when checked. No tests were added/run and no live migrations, browser scenarios or provider calls were exercised. Runtime verification remains necessary for concurrent graph edits, alias ambiguity, cycle rejection, merge/split history and identity-scoped deletion.
