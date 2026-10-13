# Buddy creation and adaptation

Creation asks only for a name. The existing API supplies a neutral avatar, sage color, encouraging tone, concise answers, and relevant examples. The new Buddy becomes active after saving. Rename uses the same single-field form; account management and archiving remain available for existing Buddies.

Teaching adapts on two levels:

- Each turn uses the existing teaching context, learner evidence, course context, and current request. Current requests take priority over saved communication defaults. Uncertainty should lead to a short clarification rather than an invented learner trait.
- Explicit standalone communication requests persist in the existing owner-scoped Buddy profile. Supported requests include “keep answers short”, “explain in detail”, “use examples”, “skip examples”, and requests for direct, calm, encouraging, or playful tone. New requests replace the corresponding preference and apply in subsequent chats with that Buddy.

The journey response paths apply preferences before generating a reply. Persistence accepts only finite, validated preference values; names and arbitrary user text never become system instructions. Quoted/source text and inferred sensitive traits are not persisted. Changes increment the existing revision and respect account and Buddy boundaries. No extra model call, provider, schema migration, or paid routing is introduced.

This implementation deliberately limits durable learning to explicit supported requests. Broader inference from repeated behavior would require confidence, provenance, user inspection/reset controls, and evaluation before it can be claimed as reliable automatic learning. Voice receives adaptation when it uses these same journey response paths; independently generated voice responses need the same integration before claiming parity.

## Personal appearance and presence

Buddy profiles now save shape, outfit, coordinated palette, face, celebration, keepsake pin, and an optional study focus. Creation keeps the main choices short; extra details and communication preferences are expandable. The same SVG character is shared by the design board and actual Buddy avatars.

Foreground time is tracked locally per Buddy for visual presence only. After 45 minutes, or during local device hours 22:00–06:00, the active Buddy looks sleepy. Window/tab absence shows sleeping; returning plays a short wake-up stretch. A break of 15 minutes resets the session fatigue. Sleepiness does not change model quality or availability. Reduced motion disables animation. Users can disable sleep behavior.

Standalone explicit requests also support hints-first and music, sports, games, everyday, or general examples. The editor shows these defaults, allows corrections/reset, and can disable new preference learning. Preferences remain owner/Buddy scoped. The current request takes priority. A free-form study focus is labeled user context in teaching prompts, not a rule overriding instructions. Pins are user-selected keepsakes rather than automatically awarded achievements.
