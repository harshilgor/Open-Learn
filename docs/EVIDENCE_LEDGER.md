# Evidence ledger and reversible observations

Feature 04 adds migration `0031_evidence_ledger` after identity migration 0030. `EvidenceLedger.record_learning_event` accepts the caller's transaction and versioned shared `LearningEvent`/`EventConceptLink` contracts. It preserves authoritative attempts, presentations, and evaluations; the ledger holds their interpretation and references.

## Delivered behavior

- Owner-local receipt sequences are serialized before idempotency checks. Conflicting reuse fails the caller's transaction. Receipt time is server metadata; occurrence time and stable ID determine replay order.
- Quiz and review commits append observations in the same transaction as presentation revision checks, attempt, evaluation, legacy state, and workflow progress. Hints, retries, solution exposure, teaching completion, self-report, skips, and verified lecture coverage remain distinct categories.
- Grading happens before the short commit. The existing durable command mechanism handles command retries; ledger keys use authoritative attempt identities.
- Challenges append retractions rather than overwriting the original attempt. Correction records reference original evidence and invalidate dependent immutable decision snapshots. A correction cannot reference another owner's evidence or substitute a different attempt.
- History first resolves corrections and then sorts observations, including late events. Server sequence remains the accepted-event watermark. History is computed from effective records, so there is no stale separate history cache.
- Concept progress exposes conditions, dates, exclusions, and the original public question text without exposing private solutions.
- Owner-scoped backfill endpoint conservatively records legacy practice as excluded pending admission review. It does not invent independence or promote historical correctness. Repeated backfills reuse deterministic keys. Legacy teaching events are exposure.
- All ledger mutations and reads use the identity deletion fence; owner columns support account export and erasure. No independent background job can recreate erased observations.

## Integration boundaries

This feature supplies evidence history, not a competing mastery algorithm. Feature 06 replaces the legacy learner reducer/review interpretation using this event set. Readiness and planning recomputation belong to their future owning services; decision invalidations already make corrections visible to existing snapshot readers. There is no fake outbox topic without a registered consumer.

Existing generated graph concept identifiers remain historical identifiers with unknown attribution. Feature 05 must resolve reviewed stable mappings; lecture coverage deliberately carries a source reference without manufacturing a concept ID from a title. Unknown capability/attribution is not proof of understanding. Existing unassisted assessment records remain assistance unknown until family-level lineage is verified by feature 12.

Feature 12 supplies adjudication UI and accepted replacement evaluations using `EVALUATION_CORRECTED`; generic clients cannot submit fabricated assessment observations through a public API. The ledger is an internal trusted-service boundary. The source-memory feature supplies durable transcript navigation and source revision corrections.

## Verification

Python AST parsing and Git whitespace inspection completed. No tests were added or run, no live migrations executed, and no providers called. SQLite/PostgreSQL concurrent commands, privacy deletion, end-to-end correction/rebuild, and browser behavior require explicit execution verification before rollout. Policy calibration is not claimed.
