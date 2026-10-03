# API contracts and frontend integration

Expose the new services through coherent APIs and complete user-facing flows with revision-aware recovery and accessibility.

Status: planned. Source: section 23 of OpenLearn Complete Implementation Brief, prepared 30 September 2026.

The implementation sequence below translates the brief into repository work. Proposed names and policies must be reconciled with existing contracts before implementation. The detailed requirements retain the source brief’s wording.

## Dependencies

- [Shared data contracts and architecture decisions](02_shared_data_contracts.md)
- [Identity authorization and device synchronization](03_identity_and_device_sync.md)
- [Learning control plane and workflow integration](10_learning_control_plane.md)

Dependencies here are implementation prerequisites. Later consumers integrate through typed contracts; their existence is not required to begin this component. See [build order](BUILD_ORDER.md).

## Existing implementation to inspect

- [backend/app/main.py](../backend/app/main.py)
- [backend/app/learning_routes.py](../backend/app/learning_routes.py)
- [backend/app/generation_routes.py](../backend/app/generation_routes.py)
- [web/lib/api.ts](../web/lib/api.ts)
- [web/components/learning-workspace.tsx](../web/components/learning-workspace.tsx)
- [web/components/workspace-panel.tsx](../web/components/workspace-panel.tsx)
- [web/components/quiz-workspace.tsx](../web/components/quiz-workspace.tsx)

## Implementation sequence

1. Map the representative operations onto existing routes and typed frontend clients before creating new endpoints.
2. Standardize command keys, expected revisions, safe errors, durable job responses, and authorized progress channels.
3. Integrate concept evidence, source inspection, Canvas, recording recovery, readiness, and planning screens as their services land.
4. Implement partial, conflict, expired-authentication, retry, empty, and completed states; validate keyboard use and accessible progress announcements.

## Detailed feature requirements

### Service surface

The table specifies representative routes and command behavior. Reuse existing routes where they already express these operations. Route names are illustrative; the ownership, validation, revision, and response contracts are binding design requirements.

| Operation | Inputs | Required response behavior |
| --- | --- | --- |
| Read concept state | Principal, course, concept | Capability state, evidence IDs, retention, projection revision |
| Read evidence history | Authorized concept or activity, cursor | Ordered events, corrections, exclusions, source links |
| Create quiz | Scope, goal, source snapshot, request key | Durable quiz ID, resolved scope, generation status |
| Submit answer | Question presentation ID, response, expected revision, key | Attempt ID, evaluation or pending status, activity revision |
| Request hint | Presentation ID, hint level, key | Hint content and recorded assistance state |
| Challenge item | Presentation or attempt, explanation, key | Challenge ID, suspended evidence status, resolution progress |
| Launch teaching | Intent, course, context, gear, key | Generation ID, selected action, authorized event stream |
| Start recording | Course, encoding, device, key | Recording ID, upload policy, manifest revision |
| Upload unit | Recording, epoch, sequence, hash, bytes | Durable acknowledgment or explicit integrity conflict |
| Finish recording | Final manifest, expected revision | Missing units or finalization job ID |
| Correct transcript | Segment, text, expected revision | New transcript revision and affected processing status |
| Connect Canvas | Device proof, origin, selected scope | Paired grant and permitted skills |
| Refresh Canvas | Grant, selected courses, key | Run ID, status, completeness by skill and course |
| Read readiness | Assessment and optional scope revision | Evidence report, uncertainty, diagnostic launch targets |
| Generate plan | Goal, availability, expected state revisions | Plan revision, tasks, feasibility and capacity gap |
| Update task | Task, desired action, expected revision, key | New task state and resulting plan change |
| Export or delete | Verified account request | Durable operation status and completion result |

### Common errors and progress

Use consistent safe error codes for unauthenticated, forbidden, stale revision, ambiguous scope, missing source, uncertain evaluation, incomplete capture, needs authentication, provider unavailable, and unsupported operation. Do not leak another user's entity existence through detailed error text.

Commands that can be retried use idempotency keys bound to owner, operation, and canonical request hash. Reusing a key with a different request returns a conflict. Long operations return a durable job ID and authorized progress channel. Every visible progress state has a defined recovery action; indefinite loading is not a terminal state.

### Frontend integration

Keep existing navigation and reusable quiz components. Add course timeline and source views, concept evidence details, recording recovery, Canvas connection management, readiness, and a study-plan task list. These views use shared API state and revision-aware cache invalidation. Avoid frontend-only calculations that disagree with server learner state.

Use loading, partial, empty, conflict, expired-authentication, retry, and completed states consistently. Empty evidence means untested, while an unavailable projection means loading or delayed processing. Screen readers must announce generation and assessment state changes without announcing every token. Support keyboard submission, hint access, pause and stop recording, and plan adjustments. Mathematical content must remain readable and selectable where supported.

Source links open the relevant note revision, document page, transcript interval, or Canvas locator. Sensitive source access rechecks authorization. The student should be able to inspect the basis of a recommendation without viewing raw backend traces or system prompts.

## Completion and integration

Deliver the service and data changes, the user-facing behavior described above, recovery paths, migration compatibility, and evidence for the relevant [acceptance criteria](ACCEPTANCE_AND_USER_JOURNEYS.md). Passing an isolated unit test or adding an endpoint does not establish integrated completion.

Platform reference numbers in the source requirements resolve through [technical references](TECHNICAL_REFERENCES.md).
