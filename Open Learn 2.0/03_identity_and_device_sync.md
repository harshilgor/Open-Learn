# Identity authorization and device synchronization

Make every resource belong to a verified account and let linked devices synchronize without losing local history.

Status: planned. Source: section 5 of OpenLearn Complete Implementation Brief, prepared 30 September 2026.

The implementation sequence below translates the brief into repository work. Proposed names and policies must be reconciled with existing contracts before implementation. The detailed requirements retain the source brief’s wording.

## Dependencies

- [Application foundation and durable execution](01_application_foundation.md)
- [Shared data contracts and architecture decisions](02_shared_data_contracts.md)

Dependencies here are implementation prerequisites. Later consumers integrate through typed contracts; their existence is not required to begin this component. See [build order](BUILD_ORDER.md).

## Existing implementation to inspect

- [backend/app/material_routes.py](../backend/app/material_routes.py)
- [backend/app/state_routes.py](../backend/app/state_routes.py)
- [backend/app/privacy_routes.py](../backend/app/privacy_routes.py)
- [backend/app/backup_service.py](../backend/app/backup_service.py)
- [desktop/src/main.cjs](../desktop/src/main.cjs)
- [web/components/settings-page.tsx](../web/components/settings-page.tsx)

## Implementation sequence

1. Select the authentication integration and define a verified principal plus separate web, desktop, and Canvas device grants.
2. Replace production development-owner dependencies throughout routes and service entry points; enforce ownership on jobs, streams, retrieval, and objects.
3. Implement device pairing, revocation, immutable offline-event synchronization, expected-revision conflicts, and explicit local-profile import.
4. Build account and device settings, sync recovery, export, and deletion. Make deletion cancel work and prevent workers or backup restores from resurrecting removed data.

## Detailed feature requirements

### Value and account model

Shared learner intelligence requires a stable owner. A hosted request must derive its account from a verified session, never from a learner ID supplied in a header or body. A desktop installation can maintain a clearly scoped offline profile, but synchronization must attach that profile to a verified account through an explicit migration operation.

Integrate a maintained authentication solution using a standard account flow. Keep OpenLearn ownership and device grants in our database rather than duplicating passwords. Browser extension pairing, desktop device linking, and ordinary web sessions receive separate narrowly scoped grants. Revoking a Canvas device must not require deleting the learner's learning history.

### Authorization enforcement

All service entry points accept an authenticated principal and verify ownership before loading source content. Queries, retrieval, object downloads, event streams, job status, exports, and evaluation tools enforce the same boundary. A valid conversation ID is not permission to read that conversation. Signed object URLs are short-lived and issued only after authorization.

Use explicit repository filters and authorization tests throughout. PostgreSQL row security can add defense in depth, but connection-pool identity and privileged-worker behavior must be designed and tested; it does not replace application checks [7]. Development bypasses are disabled in production startup validation.

### Synchronization semantics

Append immutable events using globally unique event IDs and device sequence numbers. Deduplicate retried device uploads. Use the server's accepted event order and preserved occurrence time rather than trusting a device clock for every conflict. Mutable preferences use revision checks. Notes retain their existing user-edit protection. Quiz attempts and source revisions are immutable; conflicting submissions are reconciled by command identity rather than last-write-wins.

The client submits expected revisions when changing a plan, note, or activity. A stale revision receives a conflict response containing the current revision. The interface refreshes and lets the user resolve an actual conflict. Offline events remain visibly pending until acknowledged; they do not silently appear as confirmed server evidence.

### Local data migration and privacy controls

Inventory local conversations, courses, graphs, attempts, notes, recordings, and evidence. Let the learner choose whether to import the profile into the signed-in account. Copy IDs through explicit mapping tables, preserve relationships, verify checksums, and resume from a durable migration checkpoint. Never automatically combine two local profiles solely because they share a display name.

Provide export of source files, transcripts, attempts, evidence, course facts, and derived state in readable and machine-readable forms. Account deletion revokes access immediately, cancels workers, removes objects and indexes, and records completion without retaining sensitive content in the audit log. Prevent in-flight jobs from recreating deleted data. Document backup expiry and ensure restores reapply deletion markers before serving restored content.

### Interface and completion requirements

Settings must show signed-in identity, linked devices, Canvas grants, synchronization status, export, and deletion. Test cross-account access to every resource class, expired sessions during uploads, revoked devices, offline replay, and interrupted local migration. The feature is complete when the same learner can resume across supported devices without duplicates or ownership leakage.

## Completion and integration

Deliver the service and data changes, the user-facing behavior described above, recovery paths, migration compatibility, and evidence for the relevant [acceptance criteria](ACCEPTANCE_AND_USER_JOURNEYS.md). Passing an isolated unit test or adding an endpoint does not establish integrated completion.

Platform reference numbers in the source requirements resolve through [technical references](TECHNICAL_REFERENCES.md).
