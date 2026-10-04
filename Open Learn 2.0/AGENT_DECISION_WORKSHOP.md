# Agent platform decision workshop

Status: open brainstorming. Nothing in this document authorizes implementation, paid subscriptions, or final provider selection. Work through each part with the user and record decisions before updating the implementation scope.

## How we will decide

For each part, establish the learner use cases, required behavior, existing code we can reuse, product/service candidates, API contracts, frontend flow, local versus hosted behavior, permissions, cost envelope, recovery, and acceptance evidence. Compare options using current official documentation when discussing provider details. Record accepted decisions, rejected alternatives with reasons, unresolved questions, and dependencies. Candidate names in the agent brief are starting points.

## Discussion sequence

| Part | Product and API decisions | Frontend decisions |
| --- | --- | --- |
| 1. Product boundary | Target user; first three jobs; Ask/Learn/Quiz integration; local/hosted promise; initial release scope | Entry points; Tasks / Work purpose; relationship to existing chat |
| 2. Models and kernel | Existing adapter; model routing; custom loop versus framework; tool schemas; context/checkpoint contracts | Progress detail; interruption; follow-up messages; Stop/Resume |
| 3. Tasks and storage | Execution task versus study task; state API; event replay; sources/artifact ownership; retention | Task list/detail; waiting actions; Files; history and source inspection |
| 4. Search and extraction | Tavily/Exa candidates; extraction coverage; citation/source API; limits | Research progress; clickable citations; source passages and uncertainty |
| 5. Sandbox | E2B/Daytona/local isolation; runtime and packages; upload/download APIs; costs | File input; analysis progress; chart/document preview; artifact download |
| 6. Browser | Browserbase/local candidates; DOM/vision routing; profile policy; session API; mobile takeover | Live browser panel; Take Control/Return Control; login pause; downloads |
| 7. Permissions and approvals | Capability grants; credential broker; operation keys; uncertain outcome handling | Connected permission scopes; concrete action preview; approve/reject/recovery |
| 8. Durable execution | Existing jobs versus Temporal; checkpoint boundaries; retries; local/hosted support | Reconnect behavior; background status; retry and failure messages |
| 9. Connected apps | First integrations; direct OAuth versus Composio; API-first routing; revocation | Settings connections; scopes; expired login; disconnect and deletion |
| 10. Learner integration | Shared graph/context; exposure versus assisted/independent evidence; quiz linkage | Adapted teaching; follow-up quiz; explanation of learner-state changes |
| 11. Scheduling and notifications | Recurrence/timezone; missed runs; overlap; push/email options; spend limits | Schedule editor; upcoming runs; waiting approvals; notification preferences |
| 12. Observability and costs | Langfuse/alternatives; redaction; provider spend; quotas; failure diagnostics | Usage visibility; budget choices; actionable limit messages |
| 13. Mobile and rollout | Expo/native choices; supported device matrix; hosted account needs; rollout gates | Quick Ask; voice/camera; artifact review; push; approval and takeover |

Start with the product boundary because it determines which provider features, APIs, and screens we actually need. Then sketch the primary journey and screen states before committing backend contracts. Detailed designs should include loading, empty, permission-denied, interrupted, failed, cancelled, and completed states.

## Decision record template

- Part and user problem:
- Required first-release workflows:
- Existing implementation to reuse:
- Options and verified references:
- Selected product/provider and reason (or still open):
- API requests, responses, ownership, events, and errors:
- Frontend screens, interactions, and recovery:
- Local/hosted/mobile support:
- Permissions, privacy, retention, and cost envelope:
- Acceptance test and prototype needed:
- Accepted by user / unresolved questions:

## Current decisions

The user requested documentation first, followed by brainstorming each part before major implementation changes. The shared agent-under-learning architecture is the proposal under discussion. Specific vendors, API details, frontend layouts, prices, and delivery dates are unselected.
