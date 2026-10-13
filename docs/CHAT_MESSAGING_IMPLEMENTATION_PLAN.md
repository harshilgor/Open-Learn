# Instant chat messages

## Interaction

Text-only messages appear immediately in a right-aligned bubble, clear the composer, and enter an ordered outbox. Users can send additional text while Buddy is preparing or streaming a reply. One response runs at a time, preserving the existing server journey revision and context rules. Each queued message is processed after the previous reply finishes; this initial release does not interrupt paid generation or combine distinct user requests.

The composer keeps a send control while a separate Stop control is available for an active response. Attachments, note mentions, mode changes, voice and dictation retain their existing busy-state rules. Quiz and Learn workflows retain their existing submission behavior. Text queuing is enabled in Ask/conversation mode.

## State and recovery

Messages have stable client IDs, creation times, and queued/sending/failed/awaiting-mode-decision states. The outbox serializes dispatch, pauses after failures or mode decisions, and exposes retry/remove controls. Retained messages are stored in session storage per buddy/conversation and move from the new-chat key to the created session key. Reloaded entries require review and manual retry; no uncertain submission is silently replayed. Server turns replace optimistic bubbles when they become visible, avoiding duplicate learner messages.

## Presentation

Compact bubbles, restrained arrival animation, readable wrapping and mobile sizing. Standalone messages keep every corner rounded. Consecutive queued messages use tight vertical spacing. Waiting status appears under the bubble, and thinking remains an assistant state. New content follows the bottom only while the learner is already near it; sending intentionally brings the learner to the latest message. Reduced-motion preferences are respected.

## Validation

Test FIFO dispatch, no overlapping sends, failure blocking, retries, recovery without automatic replay, immediate composer clearing, continued sends while busy, and preservation of dictation/attachment constraints. Verify desktop and mobile bubble wrapping and overflow, optimistic replacement, and scroll behavior. Existing generation replay and server revision handling remain authoritative.

## Implementation and verification

Implemented in `use-chat-outbox.ts`, `chat-outbox.ts`, `outgoing-messages.tsx`, `learn-chat.tsx`, and `chat-composer.tsx`. Account changes clear retained outbox text. Recovery also handles the buddy identity arriving after the initial component mount. Queued messages remain visible even when their text matches an earlier message. Sending errors propagate to the outbox and pause later dispatch.

19 focused tests passed across the outbox, composer, and dictation suites. ESLint has no errors in the changed messaging components (one existing LearnChat dependency warning). Full TypeScript checking still reports the existing generated-route and unrelated test errors; changed messaging components had no reported type errors.

Browser verification used the real outbox, outgoing-message, composer, and thinking-indicator components with synthetic delayed responses. Two messages appeared immediately while the response was pending, the composer cleared after each send, and the queue advanced in order. Desktop and 390px mobile layouts were inspected, with no mobile horizontal overflow. Screenshots are `outputs/instant-messaging-desktop.jpg` and `outputs/instant-messaging-mobile.jpg`. The temporary fixture was removed afterward.

The local tutor API startup issue prevented a real provider-backed end-to-end conversation test. This release preserves the existing generation transport and authoritative server journey flow. These changes have not been deployed to production.
