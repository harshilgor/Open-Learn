# Shared data contracts and architecture decisions

Feature 02 implementation, 1 October 2026. These decisions govern new Open Learn 2.0 services. Existing HTTP payloads and learning behavior retain their current contracts until the owning feature migrates its consumers.

## Delivered boundary

- `backend/app/shared_contracts.py`: frozen, versioned Pydantic contracts for all record families in section 4 of the implementation brief; validated payload dispatch; opaque ID generation; separate confidence meanings.
- `backend/app/decision_store.py`: internal repository protocol and SQL implementation for immutable decision snapshots, normalized dependencies, correction invalidations, direct-dependent discovery, and owner deletion.
- Migration `0029_shared_contracts`, after foundation `0028`: three additive tables. No legacy rows are renamed or silently reinterpreted.

This establishes contracts and decision persistence. It does not implement future identity, evidence reducers, academic reconciliation, planning services, or their UI. No new public endpoint exposes these private records. In particular, `QuestionRecord` contains a private answer-key reference and must never be used as a public response model.

## Record authority and ownership map

| Family | Existing records / owner | 2.0 authority and integration boundary |
| --- | --- | --- |
| Account/device | `learners`, development learner identity | Identity service will own verified auth subjects, grants and revocation. Existing learner IDs remain mapping inputs; no provider chosen. |
| Source/revision/span | `materials`, `material_versions`, `material_blocks`; workspace notes; lecture transcripts and audio chunks | Material, note and lecture owners retain original content. Source-memory service will supply immutable revisions and stable locators; indexes/embeddings are rebuildable. |
| Concept/mapping | `learner_graph_concepts`, `curriculum_scopes`, `graph_versions`, course roadmap | Stable-concept service will own reviewed concepts and mappings. Generated graph nodes are not silently promoted to canonical identity. |
| Concept relationship | `learner_graph_edges`, generated graph payloads | Concept owner validates directed relationships and graph cycles; proposals and reviewed relationships remain distinct. |
| Learning event | `state_events`, `action_events`, assessment attempts | Evidence-ledger service owns canonical observations. Existing action/replay records keep their operational purpose. No second event ledger is created by this migration. |
| Event concept link | Existing attempt/concept metadata | Ledger plus reviewed rubric attribution; links target a capability and record uncertainty. |
| Evidence evaluation | `evidence`, `evidence_challenges`, assessment grades | Grading owner owns evaluation revisions; ledger admits/suspends/supersedes evidence. Scores are not rewritten by a projection. |
| Learner projection | `learner_concept_states`, review schedules | State service owns rebuildable concept/capability projections. Legacy confidence/reliability numbers are not cast into the new categories. |
| Hypothesis | `misconception_hypotheses` and existing misconception annotations | Hypothesis service owns proposed explanations and their revision history. Its support is derived from supporting/contradicting events. |
| Academic fact | Courses and existing source metadata | Academic service owns provenance-bearing facts and explicit overrides. Readiness is a derived consumer. |
| Question/family | `practice_records`, `item_solutions`, presentation/exposure records | Assessment owns immutable displayed items, private solutions, rubric and family identity. Regeneration creates a new item. |
| Intervention | `learning_actions`, `lesson_artifacts`, generations, journeys | Control plane owns action selection; generation owns artifacts/streams; exposure and completion become evidence observations. |
| Plan/task | Course roadmap and next-action recommendations | Planner owns versioned schedule; task service owns executable task state. Existing roadmap progress is not proof of mastery. |
| Job/trace | `learning_jobs`, generation replay, `execution_outbox` | Foundation owns leases/retries. DecisionStore owns historical decisions and their dependency index. |

Authoritative observations, source revisions, displayed question content, and evaluation revisions are retained through normal corrections. Projections, indexes and readiness views can be rebuilt. Personal content remains deletable through an authorized deletion workflow.

## ADR 02-01: ownership and identity

Every personal record carries `owner_id`. It comes from the trusted service context, never from treating a request field as authentication. New decision keys and lookups include owner ID; dependency foreign keys include owner ID as well. `DecisionStore` rejects a model whose owner differs from the caller's owner.

Identifiers use the existing opaque prefix/UUID convention, with at most 160 ASCII identifier characters. They are not titles, normalized topic strings, or email addresses. Existing learner IDs currently have a 120-character boundary; do not widen legacy routes as a side effect of importing these contracts. Historical IDs are preserved through explicit mappings.

The v1 contracts are owner-scoped. A future shared curriculum catalog needs an explicit separate catalog namespace and access policy; it must not use a pretend personal account such as `global`. Cross-owner source/reference checks remain the source owner's responsibility before a decision is saved.

Invariant: knowing a decision ID under owner A cannot retrieve it under owner B. The repository provides scoping, not authentication. Feature 03 must supply authentication and deleted-account/job fencing before hosted use.

## ADR 02-02: concept grain and capabilities

A stable concept is one teachable idea with a definition and discipline, reusable across sessions/courses. A course outcome maps to that concept. A lesson section or every generated graph node is not automatically a new concept. Ambiguous matches remain proposals; merges/splits require explicit revisioned mappings in feature 05.

Capabilities in contract revision 1 are `recall`, `explain`, `apply`, and `transfer`. One concept can have different evidence for each. An answer about recalling a formula cannot establish transfer to an unfamiliar setting. Capabilities and prerequisite membership are not interchangeable. A later taxonomy change requires a parser and mapping revision.

Invariant: projections are concept-plus-capability records, and uncertain/incidental concept links cannot silently become target evidence. Self-edges are rejected by the shared model; full prerequisite-cycle review belongs to feature 05.

## ADR 02-03: observations, assistance and evidence

The initial observation taxonomy is `exposure`, `answer`, `skip`, `dont_know`, `assistance`, `challenge`, `correction`, and `completion`. Keep both device occurrence time and server receipt time; late/offline events are allowed. Ledger ordering will use an owner-scoped durable sequence/watermark rather than client timestamps. A deduplication key belongs to an owner and must reject conflicting input reuse.

Exposure and task completion are not correctness. Skip is not failure. A challenge suspends the relevant evaluation until adjudication; a correction supersedes rather than edits the earlier observation/evaluation. Those behaviors are obligations of features 04/12; this feature defines their data shape.

Assistance carries `independent`, `assisted` or `unknown`, the relevant question/family/capability scope, and supporting event IDs. An independent claim requires known absence of prior solution exposure. Historical missing help data maps to unknown, never independent. Family and assistance history span sessions; the latest turn cannot erase earlier hints. The assessment owner determines family/lineage membership before grading.

Four meanings remain distinct types:

| Type | Meaning | User language |
| --- | --- | --- |
| EvidenceQuality | Item/source/grading trustworthiness | usable, tentative, disputed, invalid, unknown |
| EvidenceStrength | Diversity and independence of observations | insufficient evidence, tentative, supported, conflicting |
| HypothesisSupport | Support for a possible error explanation | tentative, supported, contradicted, inconclusive |
| AcademicFactConfidence | How directly a source establishes a course fact | explicit source/user confirmation/inference plus conflict status |

There is no universal `confidence` float and no heuristic mastery probability in these contracts. Model scoring can be added only as a separate explicitly advisory, versioned measurement with calibration provenance. Legacy reliability/confidence values must remain legacy values until a reviewed migration maps their meaning.

## ADR 02-04: immutable revisions and reproducible decisions

`schema_revision` is the parser version; `revision` is a positive record version; reducer/policy versions are explicit references. These have different meanings. Datetimes must be timezone aware. Source text/audio spans use half-open increasing bounds. Hashes are SHA-256 lowercase hex. Unknown payload fields, unknown families, and unknown schema versions are rejected.

Each decision pins learner projection, academic snapshot, concept graph, policy, context manifest and source revisions. Missing domains are explicitly `unavailable` with a reason, or `not_applicable` with a reason, rather than a made-up revision. The store returns `pending_analysis` for unavailable inputs. A decision cannot pin two revisions of the same dependency. New decisions use new IDs; reusing an existing ID with changed payload fails.

`DecisionStore.read` returns the historical snapshot, not today's edited content. Referenced owners must retain immutable revision content; a pointer alone cannot reconstruct a deleted legacy source. Consumers that need fresh decisions compare required watermarks/current source revisions before commit. A historical `valid` result means no recorded correction invalidated its dependencies; it does not mean all inputs are current forever.

Source edits create new revisions without rewriting prior decisions. Corrections create `Invalidation` records against the exact old revision, optionally referencing a replacement. Dependencies are flattened into the decision; include relevant upstream source/evaluation references in `additional_dependencies` when they are not one of the standard slots. Direct invalidation lookup is implemented; a transitive rebuild graph is not claimed.

Invalidations are joined at read time, so a later-written snapshot that pins an already-invalidated dependency is still invalidated. A same-ID/different-input correction is rejected. Store operations accept an existing transaction: commit a correction, its invalidation and any `Outbox.emit` rebuild request together. Owning consumers perform rebuilds and advance foundation `ProjectionWatermarks`; DecisionStore does not mutate another owner's projection or schedule an invented handler.

Invariant: a corrected evaluation cannot become valid again just because a stale worker inserts a snapshot after the correction. For concurrent decision use, the calling feature must also apply its revision/lease checks in the final transaction; a prior read is not a commit fence.

## ADR 02-05: academic conflicts

Academic facts carry subject, predicate, scalar value, source revision, observation time and optional validity interval. Complex facts must use an explicitly versioned owning-service model rather than a generic unrestricted facts object. Unknown values remain unknown. Confirmation and conflict are separate from model certainty.

Field-specific reconciliation is required: a confirmed student-specific assignment date takes precedence over a generic class date; a deliberate user override remains identifiable and reversible; lecture emphasis is evidence for exam relevance rather than an authoritative due date. Contradictory explicit sources remain conflicting until resolved. Partial imports do not delete missing facts. A later receipt timestamp alone does not make a source more authoritative. Feature 16 implements the reconciliation policy and predicate-specific value parsers.

Invariant: a schedule change retains its old source/history and invalidates dependent readiness/planning decisions without silently removing a user override.

## ADR 02-06: task completion

A task declares an activity kind and a completion rule: submitted activity, created artifact, or explicit user confirmation. Rules include a positive required count. Opening a task is not completing it. Finishing a quiz does not necessarily demonstrate mastery; learner evidence remains a separate result. Completing a lecture-viewing task establishes exposure.

The owning task service must verify linked activities belong to the same owner, match the declared kind, and meet the completion rule. Replans create new plan revisions and preserve active/pinned work under feature 21's policy. These contracts do not schedule tasks or fabricate completion events.

## Service integration recipe

1. Authenticate and resolve the owner in the owning service. Resolve authorized immutable references and required projection watermarks.
2. Construct revision-1 models or use `parse_payload(family, 1, payload_json)`. Reject unsupported revisions; do not drop unknown fields.
3. Perform provider work outside the database transaction, as required by feature 01.
4. In the command transaction, validate source/aggregate revisions and the execution lease, persist authoritative output, and call `DecisionStore.save(connection, owner_id, snapshot)`.
5. Emit dedicated outbox work only for an implemented consumer. Keep decision dependency rows and source/evaluation references until authorized deletion.
6. On correction, call `DecisionStore.invalidate` in the authoritative correction transaction. `affected_snapshot_ids` identifies direct existing consumers for rebuilding; newly arriving stale snapshots will also read as invalidated.
7. Rebuild via the owning feature and advance its watermark. Surface pending analysis when required inputs are unavailable.

`DecisionRepository` is the internal service interface. The contracts use snake_case internally; existing camelCase API models remain unchanged. Frontend DTOs must be deliberately authored by feature 23 rather than exposing persistence/private question models.

## Persistence and compatibility

`decision_snapshots` uses typed ownership, identifier, purpose, revision, schema revision and creation time, plus a validated immutable payload. `decision_dependencies` normalizes lookup/ordering/uniqueness fields; `contract_invalidations` indexes exact owner/kind/record/revision matches. Composite foreign keys prevent a dependency row referencing another owner's snapshot. Integer revisions have database checks; parser validation handles nested payload invariants.

SQLite and PostgreSQL share SQLAlchemy-bound parameters and `ON CONFLICT` idempotency. No new migration rewrites existing consumer JSON, attempts, confidence values or identities. Apply through the normal Alembic deployment boundary before calling the repository. Downgrade removes the new history tables and is destructive to any decisions accumulated after rollout; export/backup before an intentional downgrade.

Current local export enumerates database tables, so these rows join local exports. `DecisionStore.delete_owner` supports the future account-deletion transaction and removes personal decision/dependency/invalidation records. It must be preceded by identity/job fencing to prevent resurrection. The current local-only privacy endpoint operates on the whole local database; it is not a hosted tenant-isolated deletion implementation.

## Decisions intentionally still open

- Authentication provider and hosted subject/account mapping; device grants and offline sync protocol (03).
- Shared curriculum catalog permissions and merge/split review tools (05).
- Calibrated admission/retention/hypothesis thresholds and evaluation fixtures (04/06/07/22).
- Supported desktop/browser/native mobile capture matrix and packaging (14/17).
- Academic predicate registry and per-field source priority policy (16), planning capacity/cooldowns (19–21).
- Deployment provider, storage credentials, backup retention, budget and latency limits after measurement (24).

These are dependencies for their features, not hidden defaults chosen by this implementation.

## Inspection and remaining verification

Implementation inspection covers source contracts, owner-filtered SQL, migration sequencing, and transaction boundaries. Static syntax and whitespace checks are recorded with the delivery. No tests were added/run, no live database migration was applied, and no provider or hosted deployment was exercised. Before rollout, explicitly verify SQLite/PostgreSQL migration and rollback, cross-owner access, conflicting idempotency, late correction/snapshot races, authorized deletion, and domain-consumer integration.
