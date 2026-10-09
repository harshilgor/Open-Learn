# Mode classification architecture

The learner's wording should not have to match a phrase list to get the right workflow. Mode classification uses a hybrid pipeline: deterministic rules handle unambiguous commands and hard suppression cases, while a structured semantic classifier handles other messages in context.

## Request flow

1. The API loads the current mode, the latest three learner/assistant turns, the active topic, and available modes.
2. Fast safeguards handle exact social turns, quoted or negated instructions, deferred quiz requests, and clear explicit commands.
3. In `hybrid` mode, any remaining message is classified by the configured lesson provider. It receives the bounded conversation context as data, not instructions, and returns a structured decision: `stay`, `suggest`, or `request_transition`; target mode; explicit/implicit/none request type; confidence; and a short rationale.
4. Explicit transitions require confidence of at least 0.78. Proactive suggestions require at least 0.88. Lower-confidence or invalid results abstain and keep the current mode.
5. Mode changes still require learner acceptance in the UI. Accept/dismiss/applied/failed outcomes are persisted, so recommendations can be suppressed after dismissal and measured over time.

For example, `hello dude test my maths` is not required to match an `explicit_quiz` regex. It reaches semantic classification with the current conversation and topic, where the classifier can recognize the request to be tested on maths.

## Configuration and failure behavior

- `AI_TUTOR_MODE_CLASSIFICATION=hybrid` is the default. It uses rules plus the configured lesson provider.
- `provider` is retained as an alias for the hybrid provider path.
- `rules` disables model classification and uses only deterministic rules.
- `jev` retains its separately metered, ambiguous-request-only behavior.
- A timeout, missing provider, malformed result, unsupported mode, or low-confidence result falls back to the current chat mode. The classifier request is capped at 2.5 seconds and 180 output tokens.

The semantic check currently adds one short provider request before generation for messages that do not match a fast path. The model's confidence field is a conservative gate, not a calibrated probability. Production thresholds should be tuned against a labeled set of varied learner prompts and the saved accept/dismiss outcomes; logs record the decision source and reason without logging raw prompt text.

## Evaluation approach

Keep a labeled set that includes paraphrases, slang, multilingual requests, ordinary questions, follow-ups, quoted examples, negation, hypothetical/future requests, and mixed-intent prompts. Measure explicit-intent recall separately from unsolicited-suggestion precision. Add a new example whenever a false switch or missed switch is reported. Suggestions should remain opt-in until the false-positive rate is acceptable.
