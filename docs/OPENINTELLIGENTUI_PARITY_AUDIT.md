# OpenIntelligentUI integration parity audit

Audited October 10, 2026 against upstream HEAD `f6e4388b26a64b9a0714943b08a1ce622b924eec`, which matches our pinned copy. This is a source comparison, not a claim that every renderer has passed live acceptance.

## Overall finding

### Implementation update

The historical gap table below describes the initial audit. The follow-on implementation now supplies the full upstream design skill to the producer; snapshots bounded recent conversation, the committed explanation and exact prior table/control data; adds isolated portable HTML download/copy; exposes the three skill resources, prompts and document assembler over stdio or loopback MCP; registers upstream planning; persists trusted numeric input changes with serialized revisions and current voice focus; and validates syntax/DOM targets before publication. Browser module builds now use Three/Leaflet ES entry points. Host adapters support global-style generated library calls and common trip-controller aliases.

Verification: 28 focused backend tests, 13 frontend tests and an MCP protocol test passed during implementation. The real Open Learn chat persisted mass 7 at artifact revision 5 and restored it after reload. Live provider-generated table/chart/3D artifacts rendered; map rendering required deterministic literal-JSON and exact-class-to-ID normalization. Its independently downloaded HTML rendered USGS tiles, credited photos and replay controls without Open Learn assets. New production attempts can still fail because model output is not guaranteed correct; in-run tool validation feedback is bounded to three render calls. Acceptance of that correction loop, live microphone-driven voice edits, mobile behavior, cancellation and production release remain pending. Repository-wide types still contain unrelated route/test errors.

Bundled sample business data, fake login forms and demo todo/meeting tools remain outside the visual producer. Open Learn's existing owned data and task/approval services remain the application boundary for those workflows; they are not copied as claims of real integrations.

The comparison below is the historical baseline, not the current implementation status. Design context, conversation grounding, portable export and standalone MCP are implemented. Full acceptance and production release remain pending; demo business tools are intentionally mapped to Open Learn's owned task services rather than copied as fake integrations.

### Continuation verification, October 10

Restarted the local API, frontend and visual sidecars. Thirty backend checks passed before two additional regression cases were added; the updated pricing/planning suite then passed all 20 tests. All 13 frontend renderer/export/control/trip tests and the MCP protocol test passed. Live named tool forcing reached the photo lookup and rendering tools. One map attempt exceeded the bounded model input size; focused guidance now excludes unrelated recipes instead of duplicating the master playbook. The following live attempt was blocked by the local account allowance, with reset at 14:54 Pacific. That change therefore still needs live acceptance. Physical controls, reload persistence, mobile layout and cancellation have earlier live evidence; microphone-driven voice edits and production deployment remain outstanding.

Paid visual models require an exact model selection, review version and complete positive finite tariff registry. No paid visual model was enabled as part of these checks. Local services are available at localhost:3000; the release image requires Docker's engine to be running before it can be rebuilt.

## Capability comparison

| Upstream capability | Open Learn status | Evidence / implication |
| --- | --- | --- |
| Deep Agent, CopilotKit runtime, AG-UI streaming | Integrated | `integrations/openintelligentui/agent.py`, `runtime.mjs`, backend activity reducer |
| JEV text/table/custom-UI selection | Integrated through OpenRouter | Same upstream criteria/middleware; separate visual job preserves primary explanation on failure |
| Three bundled visual skills | Integrated | master-playbook, svg-diagrams, advanced-visualization are vendored and registered |
| Progressive preview/final Websandbox, autosizing | Integrated/adapted | Imported renderer, bounded sizing, local asset import map and stricter CSP |
| Theme, SVG and form styles | Assets present, model guidance incomplete | `OPEN_GEN_UI_DESIGN_SKILL` exists in imported design-system.ts but is never sent by headless host. Upstream React provider adds it as AG-UI context; ours sends `context: []`. A short tool description is not equivalent. |
| Recent conversational routing context | Missing | Upstream selects from four recent human/assistant messages. Our fresh child run sends one synthetic question plus title/source excerpts, with empty initial state. “Turn that into a chart” can lose the referenced table/data. |
| Grounding in actual answer/artifact state | Incomplete | Child brief stores title, visual type and up to four source excerpts, but not committed explanation, selected prior visual or current nonnumeric selections. This needs bounded, owner-checked context rather than entire provider payloads. |
| A2UI native table | Integrated as host table | Same 12-column/200-row contract, required provenance and semantic HTML. Upstream's active custom catalog is Table; a general A2UI component ecosystem is not missing parity with that catalog. Live table acceptance remains pending. |
| Charts, calculators, SVG diagrams, 3D | Generation/rendering machinery available | Calculator verified live. 3D/chart families still need real provider + browser acceptance; copying modules does not establish functional quality. |
| Leaflet maps, sourced photos, trip controller | Implemented, not fully validated | Local Leaflet and CSS, restricted USGS/Wikimedia images, get_trip_stop_images, and createTripAnimator present. Live geographic acceptance pending. |
| Local slider/filter state | Present | Runs in iframe. Upstream also does not automatically synchronize arbitrary local controls to agent memory. Our numeric host revision API is additional functionality; physical slider edits currently do not persist to it. |
| User-clicked follow-up / HTTPS links | Adapted | Upstream sends a new turn or opens a tab. Ours asks for host review and fills originating draft / shows explicit link. Adds another click and changes bridge success semantics. |
| HTML download / copy generated document | Omitted | Upstream ExportOverlay + assembleStandaloneHtmlFromActivity are not imported. Existing text-copy or lesson storage is not equivalent to standalone interactive export. Requires portable assets and explicit treatment of host-only callbacks. |
| Optional standalone MCP resources/prompts/assemble_document | Not integrated | Separate upstream app, distinct from streaming web renderer. Needed only if Open Learn should expose this visual stack to external MCP clients. |
| Sample CSV query, planning card, todo/form tools | Omitted from visual producer | Upstream agent registers query_data, plan_visualization, todo tools and demo form tool. Open Learn should use owned data and existing orchestration instead of bundled illustrative business data or nonfunctional login demonstrations. Absence is an architectural adaptation, not proof of matching functionality. |
| Human-in-the-loop picker / native chart demos | Not imported | Supporting examples and components exist upstream; not all are active main-chat capabilities. Useful patterns for Open Learn task workflows, separate from the sandbox pipeline. |
| Standalone chat shell, starter prompts, reveal/copy/scroll UX, BYOK | Replaced by Open Learn | Intentional product integration. Reader-position/mobile visual behavior still needs acceptance; server-managed OpenRouter credentials replace browser-memory provider keys. |
| Durable artifacts/revisions/recovery | Added by Open Learn | Upstream uses bounded process-memory checkpoints. Ours persists child jobs and saved candidates; does not resume partially generated model tokens. |
| Production operation | Pending | Container build and three-service boot passed; full release is not deployed. Local-only capability gate remains. |

## Priority work

1. Send the upstream design skill and precise host bridge descriptors through the headless model context. Verify theme consistency, accessible controls and reduced motion on actual generated output.
2. Pass bounded recent conversation plus committed explanation and referenced visual data into owned visual jobs. Test ambiguous follow-ups and exact table-to-chart transformations without fabricated values.
3. Run live acceptance for A2UI tables, charts, 3D and map/photo/trip animation, plus cancellation, mobile layout and voice edits. Import/adapt meaningful upstream renderer/trip tests rather than relying only on our four schema/policy tests.
4. Add a portable interactive export if required for the product; do not label stored lesson replay as export parity.
5. Decide separately whether external MCP access and upstream native workflow examples belong in Open Learn's broader agent system.
6. Complete production configuration and deployment after acceptance; preserve intentional ownership, metering and sandbox boundaries.

## Sources

- [Upstream architecture](https://github.com/CopilotKit/OpenIntelligentUI/blob/f6e4388b26a64b9a0714943b08a1ce622b924eec/docs/architecture.md)
- [Routing and maps](https://github.com/CopilotKit/OpenIntelligentUI/blob/f6e4388b26a64b9a0714943b08a1ce622b924eec/docs/visualization-routing.md)
- [Product behavior](https://github.com/CopilotKit/OpenIntelligentUI/blob/f6e4388b26a64b9a0714943b08a1ce622b924eec/docs/interactive-answers.md)
- [Provider/design wiring](https://github.com/CopilotKit/OpenIntelligentUI/blob/f6e4388b26a64b9a0714943b08a1ce622b924eec/apps/app/src/app/providers.tsx)
- [Export overlay](https://github.com/CopilotKit/OpenIntelligentUI/blob/f6e4388b26a64b9a0714943b08a1ce622b924eec/apps/app/src/components/generative-ui/export-overlay.tsx)
