# Settings design review

Reviewed the ten current settings destinations and their child components. The redesign is now implemented locally. The user requested that Usage remain a separate tab and that installed apps have Updates. No pricing, plan assignments, quotas, or billing were added.

## Original review (superseded by the implementation below)

| Current destination | Proposed home | Changes |
| --- | --- | --- |
| Account & devices | Account | Start with identity/sign-in, followed by a compact device list. Place connected websites here. Move transfer, pending edits, source memory and destructive account actions to Privacy & data. Put device pairing and grant details behind an explicit advanced flow. |
| Connected websites | Account / Connections | Use connection cards with name, status and one primary action. Hide pairing JSON from the ordinary flow. Explain permissions before connecting. |
| General | Appearance | Keep theme, accent, density, text size and reduced motion. Show a small theme preview; make the accent selection visible without relying on color alone. Move desktop updates to Help and remove the web-only unavailable-update notice. |
| Learning | Learning | Group explanation style, quiz defaults and class recording defaults. Show each setting as a label, brief description and aligned control. Keep conditional quiz duration directly beneath timed mode. |
| Audio & recordings | Learning / Class recordings | These are class-note detail and retention preferences, not general audio controls. Merge the section; explain retention separately from microphone permission. |
| Usage | Account / Usage | Remove the separate top-level tab. Prioritize understandable activity and actual account limits if available. Keep raw token analytics secondary; do not present device-only totals as account usage. |
| AI service | Help / Service status | Remove the separate settings tab: the customer cannot configure the provider. Present service status and Retry as a compact section, keeping outages close to the affected action too. |
| Notifications | Notifications | Separate study reminders from delivery preferences. Hide desktop-only controls on web; distinguish account preferences from permissions on this device. Avoid blanket text claiming all reminders are device-local. |
| Data & privacy | Privacy & data | Use accurate account-service language for hosted products. Group source memory, retention, export/import and pending edits. Place delete/reset actions in a clearly separated danger section with existing confirmations. |
| About | Help | Keep version/platform details compact; include service status and desktop updates only where supported. Diagnostics belongs in an expandable troubleshooting section. |

## Visual system

Use one consistent page heading and short description, with a readable content width around 720–800px. Replace nested cards and dense paragraph blocks with section titles and setting rows: label and explanation on the left, control on the right. Use light dividers, generous section spacing, 44px touch targets and visible keyboard focus. Avoid showing raw identifiers, sync revisions, command payloads or credential grants in the ordinary settings flow.

Provide visible Saved feedback for immediate preferences. Separate local-device preferences from account-level choices using plain, short descriptions. Loading, unavailable and signed-out states should offer the appropriate action without replacing the entire page with an error. Destructive actions should remain visually distinct from ordinary controls.

On desktop use a single settings navigation rail and scrollable content pane. On phones replace the wide settings rail with a category list and back navigation, rather than squeezing ten tabs into horizontal scrolling. Stack setting controls below their labels and keep the selected category and page title visible.

## Implementation order

1. Consolidate ten destinations into six while preserving old category links through aliases.
2. Introduce shared page/section/setting-row components, starting with Account and Appearance.
3. Apply the same layout to Learning, Notifications and Privacy & data; correct hosted/local copy and capability gating.
4. Add Help with compact service status and platform-aware updates; verify keyboard and narrow-screen navigation.

## Navigation fixes made with this review

The rail plus button previously depended on a successful Buddy snapshot and became disabled during an outage. It now opens the real Buddy editor, allowing customization while disconnected; saving requires reconnection and a Retry action explains that state. Home and rail Settings callbacks passed the navigation regression. Hover and pointer feedback were added. The app-level settings shortcut was removed from the top-right navbar; the profile Settings item remains.

These source changes are local and have not been redeployed. The live backend still lacks hosting/sign-in configuration, so saving Buddies and sending messages remain unavailable there.

## Implemented settings structure

Account, Appearance, Learning, Usage, Notifications, Privacy & data, Help, and Updates. Web hides Updates because releases are automatic; the desktop shell exposes its existing updater. Old websites/audio/API-key categories map to Account/Learning/Help. Recording defaults moved to Learning, connected websites to Account, and source memory, transfer, pending edits and destructive actions to Privacy & data. The ordinary account view hides credential pairing behind explicit disclosure controls. Local backup/restore tooling is shown only for an explicit local desktop service.

Shared spacing, cards, readable width, controls and keyboard focus apply across the settings pages. Phone navigation uses a labeled section picker. Preference writes show saved feedback. Accent selection includes a check mark. The hardcoded Free profile label was removed because no account entitlement exists yet.

Usage remains visible on web/desktop, and native mobile Settings now contains Usage and Updates. Recorded usage is owner-scoped, from the existing completed tutor-generation summary; it is not a complete inference billing ledger and does not establish a Basic/Pro allowance. No limits, paid-plan assignment, upgrade flow or customer charges have been invented. Future plan work must add authoritative accounting/admission across inference paths before displaying remaining balances or enforcing quotas.

Android/iOS Updates opens an explicitly configured official store listing; without a listing it says that no check has been performed. Configure `EXPO_PUBLIC_IOS_STORE_URL` and `EXPO_PUBLIC_ANDROID_STORE_URL` after publication. Store-link validation rejects arbitrary sites and wrong-platform URLs. Mobile app version comes from the same source as its Expo release configuration. The update section is accessible before sign-in. Desktop check/install errors remain visible and retryable.

Validation: Next.js production build and both client type checks pass. Eleven affected web tests and the native store-link test pass. Browser verification covers profile access, category consolidation, account outage states and a 390px phone viewport without horizontal overflow. Packaged Windows updater installation and native store interaction need device acceptance; no app-store release or deployment was performed.
