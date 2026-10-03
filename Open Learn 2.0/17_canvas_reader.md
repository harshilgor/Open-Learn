# Local Canvas reader and browser policy

Import selected academic data through a paired local browser extension with bounded read permissions and recoverable synchronization.

Status: planned. Source: section 19 of OpenLearn Complete Implementation Brief, prepared 30 September 2026.

The implementation sequence below translates the brief into repository work. Proposed names and policies must be reconciled with existing contracts before implementation. The detailed requirements retain the source brief’s wording.

## Dependencies

- [Identity authorization and device synchronization](03_identity_and_device_sync.md)
- [Source evidence and derived memory](08_source_memory.md)
- [Academic model and course fact reconciliation](16_academic_model.md)

Dependencies here are implementation prerequisites. Later consumers integrate through typed contracts; their existence is not required to begin this component. See [build order](BUILD_ORDER.md).

## Existing implementation to inspect

- [desktop/src/main.cjs](../desktop/src/main.cjs)
- [backend/app/course_service.py](../backend/app/course_service.py)
- [backend/app/material_service.py](../backend/app/material_service.py)
- [web/components/settings-page.tsx](../web/components/settings-page.tsx)
- [web/components/course-home.tsx](../web/components/course-home.tsx)

## Implementation sequence

1. Add extension packaging and an authenticated companion channel; bind grants to account, device, approved origin, and selected course scope.
2. Implement maintained read skills for courses, assignments, calendar, modules, syllabus, and announcements with pagination and completeness markers.
3. Enforce navigation and sender policy outside model output; block submissions, messaging, account changes, and timed-quiz entry.
4. Checkpoint reads, reconcile observations through the academic service, and provide login-expiry, partial-import, refresh, and disconnect interfaces.
5. Schedule local checks only when the device/browser is available; coalesce missed runs and report last successful synchronization.

## Detailed feature requirements

### Connection architecture

Implement BrowserRuntime operations behind a local Canvas adapter. Use a user-installed browser extension to access approved Canvas tabs and an authenticated companion channel to the desktop app or backend. A desktop companion can use native messaging, whose host allows explicitly registered extension origins [3]. The extension requests host access only for the student's approved Canvas origin [4].

A normal web application cannot automatically control another origin's authenticated tab. We therefore include extension installation, pairing, permission handling, status, and disconnect in the feature. We will not attach an unrestricted remote-debugging port to the student's everyday browser as an implicit integration mechanism.

Pairing binds the extension to the OpenLearn account, approved institution origin, device, and selected browser context. The student chooses the Canvas tab or connection. Extracted data is associated with that context and checked for course and account consistency. Do not rely on cookies being available to OpenLearn; Canvas authentication remains inside the user's browser.

### Supported skills

Build maintained skills for courses, assignments, calendar, modules, syllabus, and announcements. Each skill has supported page patterns, deterministic extraction, pagination or expanded-section logic, output schema, completeness markers, and a test fixture set. Prefer accessible DOM structure and stable links over positional clicks.

Store checkpoints so interrupted reads resume at a course or page boundary. Capture only necessary academic data and provenance. Large files use the ordinary authorized material-ingestion path. Screenshots and raw page captures are opt-in diagnostics with limited retention because they can contain personal information.

DOM failure can trigger a bounded interpretation fallback on the approved Canvas page. Proposed navigation is validated against allowed origins and known read routes. Do not automatically learn and execute arbitrary new procedures from model output. If the layout is unsupported, show a partial import and the affected skill instead of claiming a complete synchronization.

### Policy outside the model

The policy layer permits approved navigation, reading academic content, and controlled material downloads. This delivery blocks messaging, submitting assignments, entering quiz answers, enrollment changes, account changes, and arbitrary scripts. LLM instructions in page content cannot enlarge that authority.

Validate extension message sender, tab origin, task identity, account grant, course scope, and response size. Chrome specifically recommends validating content-script senders before forwarding messages to a native host [3]. Treat all page text and downloaded documents as untrusted content when included in prompts. Do not pass Canvas cookies, passwords, or tokens to a model.

Read workflows should avoid actions with meaningful course-state consequences, including starting timed quizzes or acknowledging work as submitted. Browser navigation can have incidental platform side effects; the supported routes must be audited so read-only product claims correspond to actual behavior. External LTI destinations require separate permitted-domain handling or manual material upload.

### Synchronization and authentication recovery

Each run returns successful entities, source revision observations, completeness per course and skill, and safe errors. Reconcile changed facts without duplicating previous assignments. Missing entities are retired only after a confirmed complete read and the appropriate source-specific rule. An expired login transitions the run to needs authentication and asks the student to sign in directly in Canvas. OpenLearn never stores the university password.

Local scheduled checks execute when the device and permitted browser context are available. Coalesce missed checks into one fresh run rather than replaying every missed interval. The course page displays last successful check, pending local check, and partial synchronization. Disconnect revokes the device grant and stops local tasks; the student separately chooses whether to remove previously imported academic records.

### Completion requirements

Test pagination, lazy loading, SSO expiry, multiple Canvas origins, switched university accounts, changed layout, malicious page instructions, extension suspension, partial imports, and forbidden navigation. Completion requires a student to connect Canvas, import the selected courses, refresh changes, recover from expiry, and disconnect through ordinary product screens.

## Completion and integration

Deliver the service and data changes, the user-facing behavior described above, recovery paths, migration compatibility, and evidence for the relevant [acceptance criteria](ACCEPTANCE_AND_USER_JOURNEYS.md). Passing an isolated unit test or adding an endpoint does not establish integrated completion.

Platform reference numbers in the source requirements resolve through [technical references](TECHNICAL_REFERENCES.md).
