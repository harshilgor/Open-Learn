# Open Learn 2.0 implementation briefs

This folder organizes the complete implementation specification into 25 original component briefs plus an agent execution scope extension. Each brief includes its purpose, dependencies, existing code to inspect, an implementation sequence, and the applicable detailed requirements and completion criteria.

Source: `OpenLearn_Complete_Implementation_Brief.docx`, prepared 30 September 2026. The original document is in the user’s Downloads folder. Source SHA-256: `8f2d160d5e447e3707f7834730ea954021308ae520cf9d3dc9dee22dbceab169`.

The Word brief is the detailed source for this package. The earlier [2.0 architecture brief](../docs/OPENLEARN_2_0_ARCHITECTURE_BRIEF.md) remains background context; proposed research methods excluded by the complete brief are not added back to scope here. These files document planned work and do not claim that implementation has shipped.

## How to use this folder

Start with [build order and shared decisions](BUILD_ORDER.md), then use each component brief as its implementation scope. Keep [acceptance and user journeys](ACCEPTANCE_AND_USER_JOURNEYS.md) as the integrated completion checklist. External reference URLs are preserved in [technical references](TECHNICAL_REFERENCES.md).

## Component index

| Brief | Feature outcome | Source section |
| --- | --- | --- |
| [Application foundation and durable execution](01_application_foundation.md) | Establish shared service ownership, durable workers, object storage boundaries, and reliable follow-up delivery within the modular monolith. | 3 |
| [Shared data contracts and architecture decisions](02_shared_data_contracts.md) | Define consistent ownership, identifiers, revisions, evidence meanings, and service contracts before changing the consumers. | 4 |
| [Identity authorization and device synchronization](03_identity_and_device_sync.md) | Make every resource belong to a verified account and let linked devices synchronize without losing local history. | 5 |
| [Evidence ledger and reversible observations](04_evidence_ledger.md) | Record one normalized history of observations across teaching, quizzes, review, and lecture coverage while preserving original attempts. | 6 |
| [Stable concepts and course mappings](05_stable_concepts.md) | Keep learning evidence attached to stable concepts across sessions and graph revisions while retaining course-specific meanings. | 7 |
| [Unified learner state and retention](06_learner_state_and_retention.md) | Give every workflow the same capability state, evidence strength, and retention status derived from accepted observations. | 8 |
| [Misconception hypotheses and diagnostic checks](07_misconception_hypotheses.md) | Preserve possible explanations for errors and use distinguishing checks to support, contradict, or resolve them. | 9 |
| [Source evidence and derived memory](08_source_memory.md) | Manage revisioned sources, exact evidence, and derived summaries with shared retrieval, correction, and deletion rules. | 10 |
| [Shared context compiler](09_shared_context_compiler.md) | Compile authorized, purpose-specific context for teaching, quizzes, readiness, and planning from the same memory services. | 11 |
| [Learning control plane and workflow integration](10_learning_control_plane.md) | Coordinate learner intent, shared context, policy decisions, generation, and resulting evidence across Ask, Learn, and Quiz. | 12 |
| [Adaptive quiz planning and question generation](11_adaptive_quiz_planning.md) | Choose a measurable objective before authoring each question and adapt practice within the learner’s agreed scope. | 13 |
| [Grading assistance and disputed questions](12_grading_and_challenges.md) | Evaluate answers fairly, preserve assistance history across workflows, and repair every dependent decision after a question correction. | 14 |
| [Pedagogical policy and adaptive teaching](13_pedagogical_policy.md) | Select an explicit teaching action that addresses supported needs and leads to an appropriate opportunity to demonstrate learning. | 15 |
| [Reliable recording and incremental transcription](14_recording_and_transcription.md) | Preserve durable audio, decode supported media correctly, and recover usable transcripts across capture, upload, and processing failures. | 16 |
| [Lecture understanding and timestamped observations](15_lecture_understanding.md) | Turn reconciled transcripts into inspectable concept coverage, examples, emphasis, and academic observations. | 17 |
| [Academic model and course fact reconciliation](16_academic_model.md) | Represent academic expectations, deadlines, and covered material with provenance and explicit conflicts. | 18 |
| [Local Canvas reader and browser policy](17_canvas_reader.md) | Import selected academic data through a paired local browser extension with bounded read permissions and recoverable synchronization. | 19 |
| [Exam readiness and evidence reports](18_exam_readiness.md) | Explain readiness for a defined assessment scope using capability evidence, retention, and uncertainty. | 20 |
| [Executable study task generation](19_task_generation.md) | Convert a validated learning need or academic obligation into a concrete task with a launch destination and completion rule. | 21 |
| [Task advice and priority selection](20_task_advice.md) | Rank feasible tasks and explain useful next actions from current goals, evidence, deadlines, and learner preferences. | 21 |
| [Study planning and controlled replanning](21_study_planning.md) | Fit executable tasks into real availability and explain necessary changes when evidence, deadlines, or the learner’s choices change. | 21 |
| [Evaluation and learning outcome instrumentation](22_evaluation_and_outcomes.md) | Establish a reproducible baseline and measure policy, question, grading, operational, and delayed learning outcomes separately. | 22 |
| [API contracts and frontend integration](23_api_and_frontend.md) | Expose the new services through coherent APIs and complete user-facing flows with revision-aware recovery and accessibility. | 23 |
| [Performance resource use and production operations](24_production_operations.md) | Operate the integrated system within measured latency, cost, privacy, recovery, and resource limits. | 24 |
| [Existing data migration and cutover](25_migration_and_cutover.md) | Bring existing learners and activities into the shared architecture without losing history or inventing stronger evidence. | 25 |

## Agent execution scope extension

The [general-purpose agent execution proposal](26_agent_execution_platform.md), added at the user's request on 3 October 2026, extends the original scope. Provider choices, APIs, frontend flows, and rollout details remain proposals until we complete the [decision workshop](AGENT_DECISION_WORKSHOP.md). This extension is planned work, not an implementation claim.

## Product scope

We will build OpenLearn as one connected learning system. Ask, Learn, Quiz, lecture recordings, course materials, review scheduling, exam readiness, and study planning will use the same account identity, concept identifiers, academic facts, and evidence about the learner. The completed product must help a student decide what to study, receive teaching suited to a specific gap, demonstrate understanding, and return later for useful retrieval practice.

This brief specifies the complete implementation of the features selected in our architecture review. Each feature includes the reason for changing the current behavior, the data it owns, the processing steps, the interface behavior, failure handling, and completion requirements. Implementation follows dependency order, but the delivery commitment is the complete integrated product. A database table, prompt, or isolated backend endpoint does not count as a completed feature.

Our central design decision is to preserve the modular monolith and improve the shared intelligence beneath the existing workflows. The backend will own learning evidence and pedagogical decisions. Language models will interpret content and generate explanations or questions within explicit contracts. Durable storage, authorization, state transitions, validation, and scheduling remain ordinary application code.

The finished system will answer four separate questions: what the learner encountered, what they demonstrated, what remains uncertain, and what action is useful now. Encountering a lecture or receiving an explanation must never be recorded as demonstrated understanding. Missing evidence must remain distinguishable from evidence of difficulty.

### Complete delivery scope

| Capability | Required completed behavior |
| --- | --- |
| Identity and synchronization | Verified accounts, account ownership, device linking, safe local migration, revocation, export, and deletion |
| Evidence ledger | Durable learning observations with provenance, corrections, deduplication, and replay |
| Unified learner state | Shared capability state, assistance history, evidence strength, uncertainty, and retention scheduling |
| Concept graph | Stable concept identity, scoped mappings, reviewed prerequisites, and historical compatibility |
| Misconception hypotheses | Persistent possible explanations for errors, discriminating checks, and reversible conclusions |
| Memory lifecycle | Source, evidence, and derived memory with revisions, retrieval, correction, and deletion |
| Context compiler | Purpose-specific context shared by Ask, Learn, Quiz, readiness, and planning |
| Learning control plane | Explicit action selection, explanation of decisions, workflow continuity, and streaming integration |
| Adaptive assessment | Objective selection, question specifications, validation, grading, challenges, and feedback into state |
| Adaptive teaching | Targeted interventions, prerequisite repair, independent checks, and measurable outcomes |
| Reliable recording | Durable capture, resumable uploads, incremental transcription, final reconciliation, and recovery |
| Lecture understanding | Timestamped extraction of concepts, examples, emphasis, and academic statements |
| Academic model | Courses, coverage, assignments, assessments, materials, deadlines, and source-backed facts |
| Local Canvas reader | Student-authorized local browser access, bounded read skills, import reconciliation, and disconnect |
| Readiness | Evidence categories against a stated assessment scope, with actionable uncertainty |
| Study planning | Feasible tasks, prioritization, availability constraints, progress tracking, and controlled replanning |
| Evaluation and instrumentation | Baselines, regression scenarios, learning outcomes, question-family data, and operational measurement |
| Production operations | Durable jobs, cancellation, monitoring, resource limits, backups, and complete migrations |

### Methods outside the committed scope

The selected design uses interpretable policies rather than a neural knowledge-tracing model, a mathematical information-gain optimizer, fitted Item Response Theory, or a learned reinforcement-learning teaching policy. We will fully implement the evidence collection and evaluation contracts needed to assess those methods. Their absence does not leave any selected user workflow unfinished.

The Canvas ingestion reader remains local and read-only. The agent execution extension adds proposed disposable, task-scoped cloud browsers and isolated code environments for broader authorized work; it does not allocate permanent per-student virtual machines or widen Canvas permissions. Automatically learned Canvas procedures remain outside the reader scope. Local skills will be maintained, tested implementations. Scheduled local checks will run when the connected device and browser are available; the interface will expose the last successful check and any missed execution. We will not promise unattended execution while every device is offline.

## Existing behavior and refactor boundaries

The architecture review records a React frontend using Next.js conventions through Vinext and a Python FastAPI modular monolith. Local persistence uses SQLite, while hosted deployment requires PostgreSQL. Notes and files are stored separately from relational metadata. Ask and Learn already compile conversation history, course context, notes, evidence, and material into a bounded model prompt.

Quiz already has durable activity IDs, authored questions, a separate checking call, structured response components, attempts, hint and retry tracking, challenges, and atomic progress updates. Its context is narrower than teaching context, and its next-question policy primarily uses the recent score. The current canonical state relies heavily on the latest accepted evidence. Ordinary quiz evidence has an uncalibrated reliability value of 0.4, while the demonstrated rule requires at least 0.5. Review labels are calculated separately.

Recording already persists browser slices in IndexedDB and processes uploads into transcripts and notes. Notes preserve revisions and user writing. Ask and Learn can retrieve lecture blocks, but the normal quiz path does not perform the same automatic search. Production routes require verified identity; development ownership commonly uses the local learner identity.

We will preserve successful mechanisms and connect them through shared services. The author/checker pipeline remains responsible for question production. The generation lifecycle remains responsible for streaming, cancellation, replay, and canonical completion. Note revision protection remains responsible for user-authored content. Existing quiz attempts remain authoritative historical records.

Before changing code, the team will verify these boundaries in journey_service.py, context_engine.py, quiz_service.py, assessment_generation.py, state_service.py, conversation_state.py, mode_transition_service.py, recording services, route authorization, and database migrations. New contracts below are proposed interfaces; they should be adapted to the repository's actual types and conventions rather than duplicated beside equivalent existing abstractions.


The [phone experience and provider recommendations](27_mobile_and_provider_choices.md) capture the message-first mobile direction, voice messages, lecture recording, and Daytona preference. For the current repository rather than future scope, start with the [current architecture map](../docs/CURRENT_ARCHITECTURE.md).
