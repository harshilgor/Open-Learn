# Buddy behavior, memory, proactivity, and recovery

Implementation contract — 4 October 2026. Product decisions for the planned redesign; not evidence that these capabilities are implemented. This document governs the companion/home, In-Class, and flashcard briefs where behavior overlaps. Existing backend invariants must be retained until explicitly migrated and tested.

## Naming and mode state

**Buddy** means the personalized companion (for example Pip or Nova). **Conversation** is the default mode. The selector offers Conversation, Ask, Learn, Quiz, and In-Class. Review is a destination; flashcard creation is a shared capability. The mobile Buddy tab retains its name because it opens the companion workspace, not a specific response mode.

New chats start in Conversation. Persist the selected response mode per chat, and restore it on reopening; device-local storage can cache but must not override a newer server revision. In-Class selection opens setup, and reopening an existing class session restores its actual capture state without restarting the microphone. Treat class capture as a session lifecycle independent of the current response mode.

Snapshot mode and Buddy identity when a message is accepted. Changing the selector during a response affects the next submission, not the active response. Preserve earlier message rendering, ongoing lesson/quiz state, and the unsent draft. A mode change alone never generates content or triggers a tool. Disable duplicate submissions while an acknowledgement is unknown, or reconcile using the same message ID.

If any prototype serialized the mode as `buddy`, provide an explicit compatibility alias to `conversation`. Do not rename Buddy profile fields, the Buddy navigation tab, or existing Ask/Learn values indiscriminately. Current production contracts need inventory before adding the new value. Migrations must be additive and tolerate older clients with an explicit unsupported-mode response or read-only fallback.

## Memory scopes

| Scope | Available context | Default rule |
| --- | --- | --- |
| Account | Explicit student preferences, courses, saved materials, authoritative progress, reminders | Shared across the student's companions; retrieve relevant records on demand |
| Buddy profile | Name, appearance, communication style, assigned responsibilities | Apply only for the selected companion; cannot override account permissions |
| Course | Approved materials, course-specific saved preferences, assessments, notes | Retrieve when the course is selected or explicitly requested |
| Chat | Messages, selected source excerpts, local discussion state | Scoped to that chat; new chats do not automatically receive previous transcripts |
| Class session | Recording/transcript, covered topics, generated outputs and revisions | Available to linked class work and explicitly requested follow-ups |
| Saved memory | User-approved durable fact or preference with declared scope | Viewable, editable, deletable, and labelled with source and scope |

Shared availability does not mean copying all data into every prompt. The existing context compiler should select bounded relevant context, validate ownership, and record source/revision references. Raw conversation text, textbook text, and retrieved instructions are data, not authority to change permissions or memory policy. Remembering a study preference does not create a reminder, course enrollment, or calendar event.

### Creating and using saved memories

“Remember that I prefer worked examples” saves an account preference after successful validation and shows a small confirmation with Edit, Scope, and Forget. “For Biology, explain terminology first” saves course-scoped guidance. Infer scope from explicit wording; clarify when ambiguity would expose or apply information beyond the intended context.

Do not silently promote incidental conversation details to durable memory. A model can suggest “Remember this preference?”; only an accepted suggestion or explicit request commits it. Store the statement, scope, source reference, revision, creation/update time, and optional expiry. Do not store credentials as companion memories. Time-bound facts require an expiry/date rather than persisting as timeless truths.

For conflicting style preferences, follow the user's current explicit request, then applicable course/Buddy preference, then account defaults. Ownership, permissions, and authoritative academic records are enforced separately and cannot be overridden by style instructions. A statement conflicting with a verified schedule should be treated as a proposed correction and resolved visibly, not silently overwrite the schedule or remain a competing memory.

Provide Settings → Memory with account/course/companion filters, source labels, editing, deletion, and a memory-enabled control. A per-chat “Use saved memories” setting can disable optional remembered personalization while preserving necessary course/task inputs and account access controls. Clarify this distinction in its description. Switching accounts clears visible cached context and isolates pending writes by owner.

### Edits, deletion, and cross-chat retrieval

Memory updates use optimistic revisions; concurrent edits show both versions rather than silently overwrite. Deletion removes the item from future retrieval, invalidates summaries/search entries, and fences queued work that depended on its old revision. Already delivered messages remain historical output unless separately deleted; explain this in the memory UI. In-flight work revalidates memory dependencies before delivery where required and regenerates or marks the result stale.

Default cross-chat retrieval is off. Explicit requests such as “Use our discussion from yesterday” resolve candidate chats within the same account, clarify ambiguity, and retrieve a bounded selected summary with a visible source-chat link. Course material sharing never implies unrestricted sharing of all conversation transcripts. A future automatic cross-chat memory feature requires its own user control.

Deleting a chat removes its chat-scoped context and derived summaries. Independently saved explicit memories and course artifacts remain unless the user selects them for deletion too; show those retained items in the deletion flow. Account deletion covers all these scopes. Archiving a Buddy preserves history and shared course resources while its future responsibilities are explicitly reassigned or cancelled.

## Proactive preparation policy

Automatic preparation is off for a course until the student enables it. Offer clear toggles for summaries/cheat sheets, draft flashcards, practice quizzes, and pre-class refreshers. Enabling preparation does not itself grant microphone access, enable device notifications, or authorize actions in external applications.

Proposed initial defaults after opt-in: assessment preparation 24 hours before a confirmed assessment, and a pre-class refresher 30 minutes before a confirmed class. Make these editable. All-day or date-only assessments use the student's configured preparation time on the preceding day, visibly labelled; do not invent an exam start time. If schedule confidence or required materials are insufficient, show a setup/coverage card instead of generating a falsely specific preparation package.

Prepare against versioned schedule/material records. Use a unique responsibility key such as account + course + event + output type + policy revision, with an execution record for the source revision. Claim jobs transactionally so two companions/devices cannot create duplicate work. Bound cost, concurrency, source size, and generated item count server-side. At a limit, show a deferred/skipped state; do not repeatedly retry expensive work without a policy.

### Autonomy boundaries

Once enabled, generating and saving private draft study artifacts can proceed without asking on each run. The student can preview or discard them. Publishing flashcards into scheduled review, adding unrelated reminders, or changing existing plans requires an explicit command or a separately visible standing preference. No implicit authority to send messages to others, submit work, buy materials, or edit external calendars.

User-requested reminders execute independently of proactive-preparation settings. “Remind me at 7” saves once the date/time/timezone is resolved; show Saved only after durable acknowledgement. Preparation activity and notification delivery have separate states. If an API timeout leaves the result unknown, reconcile by command ID instead of issuing a new reminder.

### Notifications and controls

Proposed default for proactive notifications: one consolidated digest per day at a student-chosen local time, with an initial maximum of two proactive device notifications per day account-wide if event-specific delivery is enabled. These are configurable product defaults, not implemented service limits. Quiet hours are explicitly selected during setup; suppress proactive pushes until the next allowed time. Keep prepared content accessible immediately inside the app.

Explicit reminders follow their requested time; the UI must explain the user's chosen quiet-hour policy before applying it. If the user has not selected a policy, preserve the requested scheduled time and state that device/OS settings may silence delivery. A permission-denied device does not invalidate a saved reminder; show “Saved; device notifications are off” with available setup steps.

Deduplicate notification events across retries and track per-device delivery attempts separately from one logical account notification. Let users choose device destinations; do not assume receipt means the student saw the message. Dismissing an in-app notification syncs across devices. Expire outdated preparation alerts; do not send a flood of missed pushes after reconnect. Keep missed reminders visible with the actual due time and a late label.

Schedule updates invalidate queued jobs for the old revision. If preparation already exists, label it with the assessment/date it was based on and regenerate only when useful. Cancelling an event cancels future associated preparation and delivery; preserve completed artifacts with historical context. Disabling a course policy cancels queued work and fences active work before publication, retaining prior saved artifacts. Never claim provider computation stopped instantly if it cannot be interrupted.

Reassigning a course Buddy transfers future responsibility attribution atomically without duplicating tasks. Completed outputs retain creator attribution. If a Buddy is archived, resolve responsibility reassignment before finishing archival. User edits to a prepared artifact are preserved; later generated changes become a new version or proposal.

## Conversation and Ask behavior

Both modes use the same identity, tools, permissions, sources, and factual standards. Conversation emphasizes interaction and helpful actions. Ask emphasizes a developed answer with structure and supporting detail. Neither mode has a hard response-length ceiling. Users can request detail in Conversation or brevity in Ask without changing modes.

| Request | Conversation | Ask |
| --- | --- | --- |
| “What should I review before biology?” | Short prioritized plan using available course context, with a useful next action | Explain priorities, relevant concepts, gaps, and an organized review plan |
| “Explain cellular respiration” | Start with an approachable explanation and offer to unpack a part | Structured explanation with stages, relationships, examples, and sources where available |
| “Remind me at 7 tonight” | Resolve missing reminder content if needed, save, and show a confirmation card | Perform the same action with the same concise confirmation; do not pad an action receipt into an essay |
| “Make cards from this lesson” | Invoke the shared flashcard capability and show its task card | Invoke the same capability with the same result identity and controls |
| “I have ten minutes before class” | Quick, conversational preparation with a small number of priorities | A more organized ten-minute preparation outline while honoring the time constraint |

Do not silently switch modes. Offer Learn for a structured lesson and Quiz for practice when useful; explicit requests can start those workflows with a visible transition. Avoid repeated suggestions once dismissed. Switching the mode selector itself only prepares the next interaction. Source failures, unavailable schedules, and permission limits get the same honest treatment in every mode.

Prototype paired prompts against identical account/course fixtures. Check whether users understand each mode, can complete the same actions, and can access details without unnecessary switching. Acceptance is recognizable usefulness and presentation differences, not a word-count quota or differing model quality.

## Persistence and recovery invariants

Maintain independent states for local persistence, server acknowledgement, task execution, output availability, and notification delivery. Use plain labels: “Saved on this device”, “Syncing”, “Saved to your account”, “Processing”, “Needs attention”, and “Ready”. Never use Synced/Ready as a substitute for multiple unverified stages.

Client commands use stable IDs and payload hashes. Identical retries return the prior result; reusing an ID with different content fails. Server mutations and an outbox obligation commit together. Durable workers use leases and input revisions; stale workers cannot publish over newer work. Persist output references before announcing completion. Reconnect loads a snapshot and replays cursor events; gaps trigger resnapshot, not speculative completion. Client navigation events are not a persistence layer.

### Failure and interruption behavior

| Case | User-visible behavior | Recovery contract |
| --- | --- | --- |
| Offline before sending chat | Preserve draft; show Offline and an explicit pending-send option if supported | Do not pretend the message was delivered; queued sends have expiry/cancel controls and stable IDs |
| Request timeout after submission | Show Checking status, preserving the message | Query acknowledgement by command ID; retry the same command only after reconciliation |
| Interactive response disconnects | Keep received text labelled incomplete until confirmed complete | Respect the existing generation disconnect/cancellation policy; fetch actual status and offer continuation/retry without inventing a complete answer |
| Durable artifact task loses its viewer | Show its current status on return | Server task continues under its own policy; closing a panel does not cancel it |
| Provider generation fails | Keep prior saved work and show retry on the failed task/output | Classify retryable errors, use bounded backoff, and preserve task lineage and partial outputs |
| Session/auth expires | Show Sign in to continue; protect cached content from another account | Pause authenticated sync, preserve owner-scoped pending writes, and resume only as the same verified owner |
| Edit conflicts between devices | Show latest version and the student's pending edit | Preserve both; explicit merge/reapply with a new revision, never silent last-write overwrite |
| Browser refresh or app restart | Restore acknowledged chat/artifact references and safe local drafts | Resnapshot tasks and replay events; ignore duplicate/old revisions |
| Storage full or local save fails | Prominent Not saved warning; stop accepting unsafe recording data | Preserve previously persisted chunks, release capture safely, and expose recovery/export where available |
| Deleted/revoked source | Show Source unavailable and affected coverage | Deny further access, invalidate dependent queued work, and apply artifact retention/deletion policy |
| Cancel races with completion | Show the server's committed outcome | Linearize command/publication: cancellation winning fences publication; completed output winning remains saved and is explicitly reported |

Offline queues must be implemented per operation. Current note/quiz queue support does not imply cards, reminders, messages, or profiles already support offline mutation. Never replay expired timed actions silently: reconfirm a queued reminder if its intended time has passed. Sign-out must not submit pending actions under the next signed-in account.

### Recording-specific cases

- Microphone denial or missing input: stay in setup, identify the problem, and offer Retry/change device. No recording badge before capture actually starts.
- Network drops: persist capture chunks locally if capacity allows; show “Recording on this device; live assistance paused/catching up”. Retry uploads with checksums and sequence identities. Local-only capture is not cloud transcription.
- Microphone unplug, call interruption, or OS suspension: mark interruption and timings, retain saved audio, and offer explicit resume. Never invent audio for the gap. Native and browser adapters report their actual capture status.
- Tab/app termination: recover persisted manifests and incomplete uploads at restart. Do not auto-enable the microphone; explain any unsaved tail risk from the capture implementation.
- Pause: stop collecting new audio while earlier upload/transcription may continue. Resume starts only through the visible capture action.
- Stop: release microphone promptly, persist expected chunk count/duration/interruption metadata, then continue upload and final processing. Repeated Stop/finalize is idempotent.
- Missing chunks: expose sequence/time gaps and retry retained local chunks. A partial package needs an explicit incomplete-coverage state, not a full-completion label.
- One specialist fails: notes/other ready outputs remain usable; retry that specialist without starting a new recording or regenerating edited output.
- Switching Buddy/course view during capture: keep the active session's original owner/course/Buddy identity and persistent recording controls. A new view never reassigns or starts another capture.
- Two devices open the session: both can view permitted progress, but only the designated capture device records. Reject an unsupported second capture and offer joining the existing session.

### Review and flashcard cases

Pin card versions for an active review session. Draft generation never overwrites a reviewed or user-edited card. Reveal and rating are separate actions. A pending offline rating is visibly pending and does not become authoritative due progress until accepted. Duplicate rating commands apply once; concurrent incompatible outcomes return a conflict and reconcile server state. Closing the view is neither Skip nor Again. Transcript corrections flag dependent cards and preserve the version used by past attempts.

## Integration and release checks

Add a versioned memory/preferences service at the existing identity/context boundary rather than a companion-specific copy of course/progress stores. Proactive scheduling consumes durable academic event records and the current job/outbox runtime. Task context carries Buddy/course/chat attribution but ownership is derived from the verified principal. Current review scheduling, lecture capture, and agent execution retain their authoritative state until documented adapters are implemented.

Persist account preferences, memory revisions, proactive policies, task keys, notification status, and chat mode server-side using existing migration conventions. Local storage is a cache/queue with explicit owner isolation. Future Supabase services host these records; realtime notifications are hints to refresh, not the sole recovery mechanism.

Required scenarios before release:

1. A new chat sees explicit shared preferences and course data, but not an unrelated chat transcript.
2. Memory edit/delete invalidates retrieval and dependent queued work; historical messages are not falsely claimed erased.
3. Two Buddies preparing the same assessment produce one responsibility/output set; reassignment preserves it.
4. Quiet hours, date-only events, timezone changes, cancellation, and revoked proactive settings do not produce stale or duplicate pushes.
5. The same action works from Conversation and Ask with identical permissions and durable results.
6. Switching mode mid-response affects only subsequent requests and does not reset a lesson/quiz.
7. Network loss before/after server commit reconciles without duplicate chats, reminders, decks, or attempts.
8. Capture interruption preserves acknowledged audio and labels missing coverage; reopening never activates a microphone.
9. Expired auth and account switching do not expose another user's caches or replay their pending writes.
10. Worker crash, stale lease, source correction, and cancel/completion races preserve valid outputs and fence obsolete ones.

Use deterministic state/contract tests plus cross-device PostgreSQL concurrency tests and browser/native-device acceptance. These specifications reduce ambiguity; they cannot substitute for integration tests and real-device validation. Unimplemented states must be visibly unavailable instead of simulated as successful.
