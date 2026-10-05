# Open Learn on your phone

The conversation tab is **Buddy**, backed by the existing tutor and conversation history. The initial web implementation adds a phone bottom bar with Buddy, Courses, Notes, and More. The updated redesign target is **Buddy, Courses, Review, More**, with Notes reachable through course Study, More, and the canvas. This document does not claim that the updated navigation is implemented.

## Product hypothesis

Use the shared [behavior and recovery contract](BUDDY_BEHAVIOR_AND_RECOVERY_CONTRACT.md) for Conversation naming, mode restoration, memory controls, proactive notification settings, offline labels, and capture interruptions. Mobile uses the same server-authoritative state as desktop, with device-specific permissions and actual capture support.

Students will return more frequently if they can start with a conversation, ask a quick question, and continue the same study work on a laptop. Keep the same course, notes, quiz, review, and settings capabilities. Reorganize access for a small screen rather than squeezing the desktop sidebar onto a phone.

Buddy restores the selected companion's current conversation, or its home state when none exists. Home/Today offers a greeting, a few relevant class/deadline/review/prepared-content cards, and the composer. Tap the avatar/name to switch or customize companions; use a separate Chats button for that companion's searchable history and New chat. New conversations start in Conversation mode; Ask, Learn, Quiz, and In-Class remain available through the same interface. Expanded study views retain context and offer Back to chat.

Courses show their preferred Buddy and Start class near the header. A class-session override is explicit and does not change the course default. Notes, decks, quizzes, reminders, and progress are shared account resources even when different companions help with them. Notification links restore the associated companion, conversation, and resource. See [Personalized Buddies, home, courses, and class sessions](BUDDY_HOME_COURSES_AND_CHATS.md) for complete screen behavior and integration.

Short voice messages and lecture recording are separate intents. Voice messages need playback, transcript correction, and cancel before send. Lecture recording needs course selection, a visible timer, pause/stop, durable local capture, and recovery. Native implementation and device testing remain governed by `Open Learn 2.0/27_mobile_and_provider_choices.md`.

## Installation shipped in the web interface

A first-visit invitation appears after 1.5 seconds. Dismissal is saved per browser; users can reopen it from Install app in the sidebar. Standalone app windows and the Electron shell suppress the invitation. Supported browsers receive their native install prompt only after the user clicks Install. Other browsers receive instructions, including Safari on iPhone/iPad. Storage restrictions may cause the invitation to appear again on a later visit.

The manifest launches `/chat` in a standalone window. This is an installable web app; it requires HTTPS in production and an online connection for backend features. It does not promise offline lessons, native background recording, or an App Store build. Existing desktop installers need published download URLs before the invitation can offer native downloads. No release URLs are invented.

## Validation still needed before launch

Test installation on Android Chrome, desktop Chrome/Edge, and iPhone Safari over the actual production HTTPS origin. Check the phone keyboard, safe areas, attachments, and long lessons on physical devices. Compare first-chat completion and return visits with the prior phone interface, and measure invitation dismissal versus successful installation. A native app and the fuller Buddy conversation-list design are subsequent work.
