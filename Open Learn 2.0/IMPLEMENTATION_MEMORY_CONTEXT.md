# Identity, source memory, and context compiler implementation

Implemented on 3 October 2026 in the existing modular monolith. This document records delivered behavior and remaining integration checks; it does not replace the feature requirements.

## Delivered

- Migration `0035_source_memory` creates owner-scoped immutable source revisions, source lifecycle records, derived facts with provenance, and context manifests.
- `SourceMemory` provides semantic paragraph ranges, exact text hashes, optimistic revision conflict handling, current-source retrieval, correction/removal, provenance invalidation, and explicitly labeled extractive continuity summaries. Inferred preferences remain tentative; the compiler admits explicit preferences only.
- `/v1/memory` provides revision inspection/correction/removal, summaries, derived fact inspection/dismissal, context compilation, and owner-authorized decision traces. Account settings exposes source inspection and correction and remembered facts.
- `ContextCompiler.compile` is the shared control-plane adapter. Teaching, assessment, readiness, and planning purpose values use the same owner scope, source lifecycle, evidence projection, academic entities, course/concept scope, continuity and preference records. Existing notes, current material versions, and lecture transcript intervals are retrieved with exact original locators.
- Context packets report selected source spans, revisions, omissions, scope warnings, projection lag, and a conservative input budget after reserving output/protocol overhead. Required sources or premises that cannot fit return `insufficient_context`; they are not silently truncated. Retrieval diversifies sources and groups duplicate origins.
- Publication validates account status, evidence/projection watermark, source revision/access, academic entities, graph revision, continuity revision, preferences, and derived-fact validity. Historical manifests retain the presented context; no shared cross-account cache is used.
- Local profiles can export portable packages. Signed-in users review and explicitly copy an export into an empty account. The existing durable import checkpoint remaps IDs, checks file hashes, preserves source history, and resumes retries. Device grants, authentication records, executable jobs, and context prompt manifests are not imported. Source-owner and relationship checks reject foreign rows and unowned records.
- Account settings event-listener cleanup was repaired; the previously mixed text encoding was normalized to UTF-8.

## Validation

Seven focused backend tests pass: source correction invalidates facts and rejects stale publication; retrieval respects owners and removal; required sources exceeding budget prevent generation; packages reject foreign-owner records; portable copy is resumable and remaps IDs while preserving originals; API revision conflicts and cross-account reads are fenced; account deletion removes source history and rejects resurrection; Canvas device grants restrict route access and stop working after revocation.

Fresh SQLite migrations through the current integrated migration head succeeded. Python syntax compilation, whitespace checks, and frontend TypeScript compilation passed. Test command: `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_source_memory_compiler.py -q -p no:cacheprovider` from the repository root with the backend import path configured, or the equivalent command from `backend`.

## Remaining verification and implementation boundaries

- Browser authentication/device linking requires a real configured OIDC provider. No provider credentials were invented. PostgreSQL/S3 deployment verification remains outstanding.
- Existing note/material/conversation pipelines continue owning their storage and extraction. The compiler retrieves them directly with publication fences. The generalized registry does not yet automatically mirror every legacy source into revision records or regenerate every existing model summary after edits. Exact context manifests preserve historical admitted content; no claim is made that all legacy memory consumers have been replaced.
- Source summaries currently use a deterministic extractive continuity method; provider-generated semantic summaries and calibrated provider tokenizers remain separate integration work. The token estimate is a conservative UTF-8 budget bound, not an asserted exact provider token count.
- Import into an account with existing history intentionally reports a conflict. Resolving a many-profile merge requires an explicit relationship/conflict UI and is not inferred from display names.
