# Misconception hypotheses and diagnostic checks

Feature 07 uses `Hypothesis`/`HypothesisSupport` from shared contracts and the canonical evidence ledger. Migration `0034_misconception_hypotheses` follows capability-state migration 0033. It adds hypotheses, immutable status history, idempotent analysis results and diagnostic-to-quiz links. Existing learner-state fields are not repurposed as diagnoses.

## Analysis and evidence

Admitted partial/incorrect answers enqueue an owner-scoped `hypothesis_analyze` job through the transactional outbox. The worker loads the original private rubric, accepted answer, assistance and effective ledger events; provider work occurs outside its commit transaction. Analysis is idempotent by event ID and rechecks evidence after provider work.

Choice responses receive conservative competing candidates. Grader-supplied structured hypotheses are preferred. An extra bounded model interpretation is only attempted for substantive written reasoning (at least eighty nonblank characters), with at most three proposals and a bounded event list. Categories, concept identity, exact response-span bounds and cited event IDs are validated. Unknown IDs or unsupported citations are not admitted. Optional provider failure retains conservative candidates.

No single error creates a supported misconception. Active hypotheses are capped at four per concept. Unsupported candidates expire after fourteen days; a later error can reopen an explanation as a new episode while preserving earlier history. These are explicit operational defaults, not calibrated psychological probabilities.

## Diagnostic loop

The learner can choose a short check from quiz feedback or `/diagnostics`. Starting it creates a one-question quiz with a pinned distinguishing objective, existing source retrieval, and the existing author/checker gate. The objective is passed to both question authoring and validation; the proposed explanation must not disclose the answer. Each episode permits two checks, then asks the learner to continue or choose an explanation instead of looping.

Diagnostic results are read from effective ledger events, never accepted as a client-reported success. Only independent admitted correct/incorrect outcomes update support. An isolated failure supports its linked explanation; an isolated success contradicts it, or resolves a previously supported episode. Assisted success, skips, unknown independence and contested evidence cannot resolve an explanation. Checks for one explanation do not lower support for competing explanations that they did not measure.

Corrections refresh status from current effective evidence, including retraction of the original supporting answer. Expired/resolved/contradicted history remains visible. Student reports such as a typo or misread question are stored as ledger SELF_REPORT observations, retained alongside task evidence and never treated as scored performance.

## Teaching integration and UI

`recommendation(owner,concept_id)` supplies an advisory action: clarifying check for tentative alternatives, contrastive explanation for supported conceptual confusion, prerequisite repair for a supported prerequisite issue, or a focused worked example. It includes the hypothesis revision and reason. The shared control plane consumes this advisory input while preserving direct learner requests; the pedagogy feature extends concrete intervention selection.

Quiz feedback embeds a panel with tentative language, diagnostic launch, self-report, current recommended action and revision history. Diagnostic results refresh that panel. A review without any associated owned learning conversation surfaces a session-required message rather than silently changing course scope.

## Limits and verification

Analyzer outputs and diagnostic wording still depend on question-quality checks; no clinical or causal diagnosis is claimed. Legacy unreviewed concept attribution remains legacy/uncertain, and unknown assistance remains unknown. The feature uses conservative evidence admission rather than manufacturing independence.

Static source inspection is performed; no tests, live migrations, browser checks or model-provider experiments were run. Runtime acceptance still needs competing-cause scenarios, fabricated citation rejection, assisted-success cases, correction races, expiry/reopening and diagnostic question-quality evaluation.
