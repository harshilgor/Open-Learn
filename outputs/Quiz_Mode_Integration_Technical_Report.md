# Quiz mode integration: technical report

27 September 2026 · Proposed implementation plan

## 1. Product contract

The learner can enter Quiz by selecting Quiz directly, by accepting a Quiz suggestion in Ask or Learn, or by resuming an existing quiz. A message that says or implies a desire to be quizzed produces a confirmation card; it does not silently create a quiz. Directly selecting Quiz is itself an affirmative action. If the subject is unclear, the tutor asks a short clarification in Ask chat before creating a quiz.

Quiz is one persisted workflow with two presentation locations:

| Origin at launch | Placement | Return path |
| --- | --- | --- |
| Ask | Open the right panel on a Quiz tab, keeping chat visible. | Close or switch panel tabs to return to Ask. |
| Learn with an active lesson note | Open that lesson in Notes and show its embedded Practice section. | Continue the lesson at the same position. |

The right panel's **new tab** menu contains Notes and Sources only. Opening the panel, reopening an old Quiz tab, or viewing quiz history never creates a quiz. A Quiz tab is opened programmatically for an Ask quiz, or by selecting an existing quiz from history. A lesson quiz remains attached to its lesson even if the learner later switches chat mode.

Each quiz has a durable server ID. The learner can find active, paused, interrupted, and completed quizzes in a quiz history list. Opening an existing quiz restores its questions and progress; a new quiz requires a new explicit launch. A completed quiz remains readable.

This report supersedes the separate Quiz navigation placement in [the earlier Learn and Quiz blueprint](Learn_and_Quiz_Product_Technical_Blueprint.md). The prior blueprint's question quality and assessment principles still apply.

## 2. Current code and gaps

| Area | What exists | Change required |
| --- | --- | --- |
| Mode intent | `backend/app/mode_transition_service.py` has rules, suppression, persisted suggestions, and an optional general model fallback. | Add a Jev decision adapter for semantic hints; retain deterministic policy and durable accept/dismiss. |
| Quiz launch | `LearnChat.onQuiz` routes to the full Quiz view through `learning-workspace.tsx`. | Launch in the right panel for Ask, and in the active lesson note for Learn. |
| Right panel | `workspace-panel.tsx` offers Notes, Quiz, and Sources in the `+` menu; `WorkspaceSplit` persists tab layout in browser storage. | Remove Quiz from manual tab creation; open it only for a quiz ID or from quiz history. Validate persisted legacy Quiz tabs on hydration. |
| Quiz UI | `QuizWorkspace` handles setup, creation, restore, questions, pause, and completion. Its `inline` flag also forces one question. | Split placement from quiz configuration and reuse one player in both locations. |
| Persistence | Quiz, presentation, attempt, and challenge records already exist on the server. The browser stores a latest quiz ID. | Make server IDs and history authoritative; link quizzes to lesson notes and teach-back events. |
| Study note | Learn creates an ordinary workspace note with `study_note: true`. Quiz can propose a review checklist for weak attempts. | Embed a structured Practice section and project all relevant quiz activity into lesson context automatically. |

## 3. State and transition model

Keep the existing Ask/Learn chat mode and add an explicit quiz workflow state. Store `activeQuizId` separately from `chatMode`; a learner may leave a quiz open while Ask or Learn chat remains visible. Placement is derived from the **quiz's launch origin and lesson link**, not from the current composer mode after launch.

Recommended state transitions:

```text
No quiz -- direct Quiz action --> resolve topic --> create quiz --> active
No quiz -- intent detected --> confirmation --> resolve topic --> create quiz --> active
No quiz -- intent detected --> dismiss --> remain in Ask/Learn
Active --> pause --> paused --> resume --> active --> complete --> completed
Active/paused/completed --> open by ID --> restore same quiz
```

`resolve topic` uses the current user request first, then the active concept, lesson objective, session goal, and the existing concise study context. If that evidence identifies more than one plausible subject, ask “What topic should I quiz you on?” in Ask chat and wait. Do not create a blank or generic quiz. The learner's answer becomes the launch request. A lesson can supply its current concept without another question when the target is clear.

The transition suggestion should preserve `sourceMode`, `sessionId`, `lessonNoteId` where applicable, requested topic text, and a server suggestion ID. Acceptance is idempotent and creates at most one quiz. Dismissal respects the existing cooldown. A pending offer should not consume the learner's unrelated next message.

## 4. Jev classification adapter

The selected Jev is [TypeSafe's Jev](https://typesafe.ai/blog/introducing-system-one-models-and-jev). It accepts text state and returns typed decisions and probabilities, not generated prose. The current adapter uses OpenRouter's separate Decisions API, `POST https://openrouter.ai/api/alpha/decisions`, with model `typesafe/jev-1.13`; the existing chat-completions `complete_json` method is not the Jev transport. It reuses the server-side `OPENROUTER_API_KEY`, so local users do not need a separate Jev credential. See [TypeSafe's model concepts](https://docs.typesafe.ai/concepts/system-one) and [OpenRouter's Jev integration guide](https://openrouter.ai/blog/tutorials/how-to-use-jev/).

The `ModeTransitionService` implements the Jev adapter behind its existing boundary. Set `AI_TUTOR_MODE_CLASSIFICATION=jev` to enable it; the model defaults to `typesafe/jev-1.13` and can be overridden with `AI_TUTOR_JEV_MODEL`. The default remains `rules`, and missing key, timeout, or invalid output safely falls back to staying in the current mode. The server constructs a bounded, text-only state containing the latest message, up to two recent turns, current mode, and active topic/concept. No API key or raw provider response goes to the browser.

Ask narrow typed questions in one Jev decision request: (1) is the learner requesting interactive questions now, (2) is a quiz merely being discussed or deferred, and (3) which workflow best fits the immediate request (`ask`, `learn`, `quiz`, `none`). Include explicit `none` and define terms for quoted, negated, future, and hypothetical mentions. Code validates the returned choices and probabilities, then applies the product policy. Jev supplies evidence; the server may show a transition offer, remain in place, or ask for clarification. No Jev result directly writes mode state or creates a quiz.

Run hard rules first for explicit mode selection, negation, quoted text, “quiz me later,” accepted offers, and duplicate/cooldown checks. Use Jev on semantic hints and ambiguous phrasing. On timeout, invalid response, or absent key, fall back to rules and normal conversation; never turn an uncertain classification into a quiz launch. Select confidence thresholds from a labeled set of actual learner utterances before rollout, and log classifier version, rule/Jev path, decision, latency, and acceptance/dismissal without logging full student text. Compare suggestion precision and missed quiz requests, including Ask and Learn origins.

## 5. Shared frontend

Build a common `QuizPlayer` for the question sequence and feedback. It receives `quizId`, fetches the server quiz, and renders the existing assessment card for `single`, `multiple`, and `short` questions. These types share the shell, progress, feedback, source links, pause/resume, and completion screen; option controls differ by question kind. Keep answer keys server-side until evaluation. A quiz can contain a mix of question types, and the UI never needs a bespoke page per generated question.

Separate these concerns from today's `QuizWorkspace`:

- `QuizLauncher`: resolves the requested topic and creates one quiz after confirmation/clarification; exposes count and difficulty when useful. Default count can remain five, with one-question checks as an explicit choice rather than a side effect of right-panel rendering.
- `QuizHost`: selects `panel` or `lesson` placement from persisted origin and `lessonNoteId`, owns active ID and restore behavior, and handles empty/loading/error states.
- `QuizPlayer`: displays the persisted quiz and actions regardless of placement.
- `QuizHistory`: lists active, paused/interrupted, and completed quizzes with topic, lesson, progress, last activity, and Resume/View action. Filter by session or lesson but offer a global entry point in the left Quiz navigation area. Clicking a history row opens its existing ID and location.
- `LessonPractice`: a structured widget embedded in the lesson note view, containing the launch action, active quiz, and prior quizzes for that lesson. It should use the same `QuizPlayer` as the panel.

On Learn entry, open the current lesson note in Notes automatically. On Quiz entry from Learn, focus the note's Practice section without replacing the lesson content or creating a separate free-floating note. On Quiz entry from Ask, open the panel's Quiz tab with the created or selected quiz ID. The `+` menu offers only Notes and Sources. If an old saved layout names Quiz but has no valid active quiz, restore Notes instead. Closing the Quiz tab only hides it; it never abandons progress.

On narrow screens, present the panel or lesson as a reachable sheet/view with a clear return to chat. Focus the first quiz heading when opened; announce status changes once, preserve keyboard operation, and respect reduced motion. Ensure a pending request and answered question stay visible after refresh.

## 6. Backend records and API changes

Extend quiz creation with bounded `requestedTopic`, `origin: ask|learn`, optional `lessonNoteId`, `lessonRevisionAtStart`, `conceptIds`, selected source spans, `sourceTransitionId`, and a client/server idempotency key. Keep the existing `sessionId`, count, difficulty, and timed mode. Validate owner access to session, note, concept, source spans, and transition. A lesson quiz must link to a study note belonging to the same learner and session. Store the topic/context snapshot used to create the quiz so later note edits do not rewrite the meaning of prior questions.

The existing quiz ID remains the canonical identifier. Add a stable lesson-to-quiz link record or indexed `lessonNoteId` field, with creation time, last activity, status, origin, and title. Server history queries return all owned quizzes, with optional `sessionId`, `lessonNoteId`, and status filters. The frontend's localStorage pointer is only a convenience; a new device can recover history from the API. Keep revision checks on answer, pause, resume, and next-question operations. Treat duplicate launch retries as the same quiz, including after network failure.

Suggested endpoints or equivalents in current route conventions:

```text
POST /v1/quizzes                 create or replay by idempotency key
GET  /v1/quizzes?sessionId=...  list/history, including paused and completed
GET  /v1/quizzes/{quizId}       restore current state and public attempts
GET  /v1/notes/{noteId}/quizzes list quizzes linked to one lesson
```

Existing `/next`, `/attempts`, `/pause`, and `/resume` actions can be retained. Launch should request the first question after durable quiz creation; if generation fails, keep a resumable `ready` quiz and show Retry. Avoid creating the same question twice on refresh. Quiz generation uses the study context, active concept, lesson snapshot, session goal, learner's request, and selected references. The selected material and exact source spans should be recorded on each question. If relevant material is absent, the tutor can offer clearly labeled general practice or ask for material, without fabricated citations.

## 7. Feed every quiz back into its lesson

“All data goes back to the lesson” should mean a durable, queryable association for every relevant quiz event, with a useful visible projection in the note. Store question/presentation IDs, concept and reasoning target, learner response, hint/assistance use, skip/“don't know,” timing when applicable, evaluation, challenge/contestation, source references, retry, and completion summary. Link each record to both `quizId` and `lessonNoteId`; for Ask quizzes without a lesson, link to session now and attach to a lesson only when the learner explicitly chooses one or the system later establishes an unambiguous link. Do not silently attach Ask practice to an unrelated note.

The lesson's Practice section shows the quiz title, status, last attempt, score with its limits, demonstrated reasoning, gaps, and next action. The full event log stays in structured records rather than being dumped into Markdown. Keep private answer keys and grading rubrics out of learner-facing note content. A projection worker/service updates the visible summary after each committed attempt, pause, challenge, and completion. Use event IDs or a last-applied revision to make this projection retry-safe; note edits and quiz updates must not overwrite one another. If a learner edits the note, maintain the Practice widget by reference instead of rewriting their prose.

The teaching planner reads the linked evidence before the next Learn turn: what the learner answered independently, where help was used, what was skipped, and what was contested. It can choose review, a different explanation, a prerequisite, or progression. Preserve the existing evidence policy: one answer does not prove mastery; challenged or unreliable items do not count as demonstrated understanding; source coverage limits claims. Record the reason for a teaching adjustment so it is inspectable. The visible lesson summary is a projection, while the structured record is the source of truth.

## 8. Delivery sequence

1. Add the persistent quiz origin/lesson link and history API. Preserve existing quiz IDs and migrate legacy `quiz`/`learn_inline` origins with a compatibility mapping; do not orphan old quizzes.
2. Refactor `QuizWorkspace` into shared launch/host/player/history pieces. Remove Quiz from the new-tab menu, add programmatic open-by-ID, and handle old saved panel layouts.
3. Wire direct Quiz and accepted Quiz suggestions to topic resolution and the correct placement. Open the lesson note automatically in Learn and put `LessonPractice` inside it. Preserve chat and journey position.
4. Link every quiz event to the lesson and update the Practice projection. Feed structured evidence into subsequent lesson planning.
5. Roll out the quiz experience with the existing classifier and confirmation policy, using end-to-end scenarios to check the agreed placement and persistence behavior.
6. In the later classification phase, add the Jev adapter with a configuration switch and deterministic fallback. Keep the existing persisted transition policy as the sole authority for offering and accepting switches. Tune Jev thresholds from a labeled set of learner utterances without changing the quiz placement contract.

## 9. Acceptance criteria

- A direct Quiz selection launches once; a message hint shows a confirmation card; dismissal leaves the learner in the current state.
- “I have a quiz tomorrow” and “quiz me later” do not start a quiz. “Test me on fractions” can be confirmed and launches a fractions quiz. If the topic cannot be resolved, Ask chat clarifies before quiz creation.
- Ask-origin quizzes open the right Quiz tab; Learn-origin quizzes appear in the active lesson's Practice section. Learn entry opens the lesson in Notes.
- The right panel's `+` menu contains Notes and Sources only. Reopening the panel or a past Quiz tab never creates a quiz.
- Active, paused, interrupted, and completed quizzes are discoverable and restorable by the same server ID across refresh and devices. Repeated launch or answer requests do not duplicate records.
- Single choice, multiple choice, and short response questions render through the same player in both locations. Panel placement does not force a one-question quiz.
- Every committed lesson-quiz interaction is linked to the lesson and available to future teaching decisions; the visible lesson summary updates without exposing private answer keys or overwriting learner-authored notes.
- Jev failure leaves the rules path and chat usable. A model output alone never creates a quiz.

## 10. Deferred integration choice

TypeSafe Jev is confirmed. Choose direct TypeSafe API versus OpenRouter Decisions API when the later classification phase starts. The repository already has server-side OpenRouter configuration, so that route can reuse its key; a direct integration would use TypeSafe's server-side credential instead. Either path implements the same `IntentClassifier` interface and leaves quiz creation under the existing transition policy.
