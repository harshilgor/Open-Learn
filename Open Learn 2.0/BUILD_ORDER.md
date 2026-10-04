# Build order and shared decisions

Build by dependency and validate complete journeys at integration points. File numbering is for navigation; it is not a strictly sequential schedule. Baseline evaluation begins before behavior changes. Migration and operations begin with inventory and design, then finish after all write contracts are integrated.

## Suggested execution order

### Baseline and contracts

- [Evaluation and learning outcome instrumentation](22_evaluation_and_outcomes.md)
- [Application foundation and durable execution](01_application_foundation.md)
- [Shared data contracts and architecture decisions](02_shared_data_contracts.md)

### Ownership and stable references

- [Identity authorization and device synchronization](03_identity_and_device_sync.md)
- [Stable concepts and course mappings](05_stable_concepts.md)
- [Source evidence and derived memory](08_source_memory.md)

### Shared evidence and learning state

- [Evidence ledger and reversible observations](04_evidence_ledger.md)
- [Unified learner state and retention](06_learner_state_and_retention.md)
- [Misconception hypotheses and diagnostic checks](07_misconception_hypotheses.md)

### Shared decisions and learning workflows

- [Shared context compiler](09_shared_context_compiler.md)
- [Learning control plane and workflow integration](10_learning_control_plane.md)
- [Grading assistance and disputed questions](12_grading_and_challenges.md)
- [Adaptive quiz planning and question generation](11_adaptive_quiz_planning.md)
- [Pedagogical policy and adaptive teaching](13_pedagogical_policy.md)

### Recording and academic ingestion

- [Reliable recording and incremental transcription](14_recording_and_transcription.md)
- [Lecture understanding and timestamped observations](15_lecture_understanding.md)
- [Academic model and course fact reconciliation](16_academic_model.md)
- [Local Canvas reader and browser policy](17_canvas_reader.md)

### Readiness and actionable planning

- [Exam readiness and evidence reports](18_exam_readiness.md)
- [Executable study task generation](19_task_generation.md)
- [Task advice and priority selection](20_task_advice.md)
- [Study planning and controlled replanning](21_study_planning.md)

### Integration and cutover

- [API contracts and frontend integration](23_api_and_frontend.md)
- [Performance resource use and production operations](24_production_operations.md)
- [Existing data migration and cutover](25_migration_and_cutover.md)

Academic data contracts and manual ingestion can start before lecture understanding. The two integrate through academic observation contracts. Context compilation first ships against existing sources and state, then adds academic/readiness/planning consumers as those contracts become available. API integration happens throughout the work, rather than waiting until the last stage.

## Decisions to record before dependent implementation

- Supported desktop, browser, native mobile, and hosted deployment matrix.
- Authentication provider, offline identity, device grants, and synchronization protocol.
- Event taxonomy, stable concept grain, capability definitions, question families, and assistance lineage.
- Revisioned state rules, quality admission, contradiction handling, and retention policy.
- Field-specific academic conflict rules, timezone handling, and deliberate user overrides.
- Task completion, pinning, availability, automatic replanning, and recommendation cooldown semantics.
- Transaction boundary and event watermark contract for immediate state versus asynchronous projections.
- Educational review thresholds and environment-specific latency/cost limits after baseline measurement.

## Source work packages and integration requirements

### One integrated delivery

The team can implement independent modules concurrently after shared contracts are agreed. Integration follows the dependency order below. Work packages are internal execution units; every selected capability must pass its completion criteria before the product commitment is considered delivered.

| Work package | Suggested accountable function | Depends on | Required integration result |
| --- | --- | --- | --- |
| Baseline and test histories | Evaluation and engineering | Current product | Reproducible current behavior and labeled invariants |
| Identity and ownership | Backend and security | Account contract | Verified ownership across routes, jobs, sources, and devices |
| Data contracts and concept mapping | Backend and curriculum | Existing schema inventory | Stable IDs, source revisions, migration mappings |
| Evidence and projection | Backend and evaluation | Identity and concepts | Atomic writes, replay, corrections, shared state |
| Source memory and context | Backend and retrieval | Identity and source contracts | Shared authorized context across workflows |
| Assessment and teaching policy | Learning engineering and frontend | State, context, baseline | Planned questions and interventions with evidence feedback |
| Recording capture and media | Client and media engineering | Identity and object contracts | Durable capture, upload, decoding, recovery, live transcript |
| Lecture and academic data | Learning and backend | Sources, concepts, recording | Timestamped observations and reconciled academic facts |
| Canvas connection and skills | Browser and frontend | Identity, academic contracts | Complete supported local read and refresh workflows |
| Readiness and planning | Learning and frontend | Learner and academic state | Reports, executable tasks, feasible schedules, replanning |
| Migration and operations | Backend and platform | All write contracts | Safe cutover, monitoring, recovery, export, deletion |
| Final integrated validation | Engineering and product | All packages | Full user journeys, quality comparison, operational readiness |

### Agreement before implementation

Agree on ownership boundaries, event taxonomy, concept grain, assistance lineage, capability taxonomy, state categories, academic conflict rules, and task completion semantics. These decisions prevent teams from defining the same word differently. Record each in a concise architecture decision document with examples and a testable invariant.

Select and document the supported desktop, browser, mobile capture, and hosted deployment matrix. This determines extension packaging, native microphone implementation, decoding support, and CI targets. Browser foreground reliability and native background recording must have separate tests and clear product behavior.

### Integration reviews

Review working journeys at module boundaries rather than reviewing only diagrams. The evidence review demonstrates a duplicate answer and challenge reversal. The context review demonstrates a lecture quiz and cross-session continuity. The recording review demonstrates recovery after interruption. The planning review demonstrates insufficient time and a changed academic fact.

Avoid assigning delivery dates before repository inspection and supported-platform choices establish the actual effort. Track dependencies, completed integration tests, and unresolved decisions in the team backlog. An item is complete only after its interface, data, recovery path, and acceptance evidence are delivered together.

## Agent execution extension

Use the [decision workshop](AGENT_DECISION_WORKSHOP.md) before selecting providers or implementing this track. The [agent execution brief](26_agent_execution_platform.md) defines proposed phases A–H: kernel, search, sandbox, browser, hosted durability, connected apps, scheduling/notifications, and mobile. Foundation contracts start alongside identity, storage, context, and evidence; UI and operational integration happen in each phase. Study TaskSpec and execution tasks remain distinct and explicitly linked. Preserve the local Canvas reader's narrower policy. Provider selections and rollout gates remain open decisions.
