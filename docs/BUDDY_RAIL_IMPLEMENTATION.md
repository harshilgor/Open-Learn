# Buddy navigation update

Implemented the single permanent desktop rail with Home, global chat search, Courses, buddy icons, Add buddy, More, and account access. The previous permanent workspace sidebar is removed. Notes keeps its own list within the Notes destination.

Clicking a buddy resumes its remembered conversation; a buddy with multiple chats shows a history chevron when selected. The flyout supports search, date groups, current-chat highlighting, pinning, renaming, title regeneration, deletion, and older-history pagination. Choosing a conversation closes the flyout. New chat in the buddy header creates a conversation with that buddy. Existing buddy/chat draft persistence is retained.

Global history searches conversation titles, bounded learner-message previews, goals, buddy names, and course names. Pins are stored on the current device. Search operates on loaded pages; Load older chats makes additional saved history available.

The server returns at most 180 characters from the latest learner question in a history preview. Private lessons, answers, and solutions are excluded, and the existing owner-scoped query controls access. Frontend versions remain compatible with services without preview support by falling back to the conversation goal.

Mobile uses a buddy picker and a bottom-sheet history list, with a toggle between the current buddy and all conversations. Notes, Review, Reminders, Courses, Home, Settings, and account actions remain accessible.

Validation: 11 frontend tests passed across navigation, history filtering/pinning/search, and Notes behavior; the backend preview test passed for truncation, owner isolation, and exclusion of private answers. ESLint reported no errors in changed components (six existing workspace warnings). Full TypeScript checking remains blocked by existing generated route types and unrelated browser-assistant/quiz-quality test type errors; no changed component type errors were reported.

The real components were checked in the local browser using synthetic saved-chat data at desktop and 390px mobile widths. Flyout selection, mobile history scope, and absence of mobile horizontal overflow were verified. The actual local page rendered the new rail and Notes navigation, including API-unavailable retry states. Local API startup did not complete, so a full real-data browser journey was not verified. Screenshots: outputs/buddy-history-desktop.jpg and outputs/buddy-history-mobile.jpg.

These changes have not been deployed to production.
