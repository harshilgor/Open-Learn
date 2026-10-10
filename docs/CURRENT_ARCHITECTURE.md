# Open Learn current architecture map

Repository map inspected 3 October 2026. This document separates current code boundaries from the proposed agent/mobile extension; it does not certify deployment readiness.

## Current application

- Web: React 19 and TypeScript, with Next.js conventions and a Vinext/Vite development/build wrapper. Source: [web/package.json](../web/package.json), [framework runner](../web/scripts/run-framework.mjs), [routes](../web/app), and [components](../web/components).
- API: Python FastAPI modular monolith. [backend/app/main.py](../backend/app/main.py) registers routes and application lifecycle. Domain services own learning, assessment, materials, notes, courses, lectures, identity, and planning.
- Research: [web_evidence](../backend/app/web_evidence) already contains Exa-backed retrieval, a provider interface, bounded tool orchestration, citation mapping, quotas, auditing, and retention. Agent research should extend this path.
- Models: [model_provider.py](../backend/app/model_provider.py) provides the existing provider boundary. Context compilation and learning services sit between the UI and provider calls.
- Persistence: local SQLite and hosted PostgreSQL through the backend store and migrations. Notes, audio, uploads, and other binary content have storage boundaries separate from relational metadata.
- Execution: existing durable job/outbox/lease machinery and workers from the same backend codebase. Inspect [foundation decisions](OPENLEARN_2_FOUNDATION_DECISIONS.md) and [application foundation](APPLICATION_FOUNDATION.md) alongside current worker code; earlier documents may describe earlier implementation stages.
- Desktop: Electron companion in [desktop/src/main.cjs](../desktop/src/main.cjs), with local API integration and a Canvas browser-extension boundary.
- Recording: web capture, durable audio upload, transcription, and lecture-derived material. See [lecture recording architecture](LECTURE_RECORDING_ARCHITECTURE.md); its historical verification statements are not fresh release checks.
- Browser: the working tree includes browser assistant services, frontend task/connection controls, and extension changes. See [browser architecture](BROWSER_ASSISTANT_ARCHITECTURE.md) and [implementation notes](BROWSER_ASSISTANT_IMPLEMENTATION.md). These changes predate the current documentation work and remain independently reviewable.

The web API client reads NEXT_PUBLIC_LEARNING_API_URL and otherwise defaults to http://127.0.0.1:8000. Publishing only the frontend does not publish the Python API, database, storage, worker, or a native phone application.

## Architecture and implementation references

- [Visual stack parity audit](OPENINTELLIGENTUI_PARITY_AUDIT.md) and [local/hosted integration](OPENINTELLIGENTUI_LOCAL_INTEGRATION.md): owned durable visual jobs, contextual generation, portable isolated exports, MCP resources and release acceptance boundaries.

- [Original 2.0 architecture proposal](OPENLEARN_2_0_ARCHITECTURE_BRIEF.md): product direction and learner intelligence architecture.
- [Implementation tracker](OPENLEARN_2_IMPLEMENTATION_TRACKER.md): historical delivery/gap tracking; verify claims against the current checkout.
- [2.0 component index](../Open%20Learn%202.0/README.md): original component specifications and scope extension.
- [General agent proposal](../Open%20Learn%202.0/26_agent_execution_platform.md): planned shared kernel, execution tasks, tools, permissions, artifacts, recovery, and learner integration.
- [Product/provider and phone proposal](../Open%20Learn%202.0/27_mobile_and_provider_choices.md): message-first mobile interface, recording, API candidates, and current selections.

## Planned additions

- [OpenIntelligentUI visual stack replacement plan](OPENINTELLIGENTUI_VISUAL_STACK_MIGRATION_PLAN.md): replacement design covering JEV presentation routing, Deep Agents/LangGraph, CopilotKit/AG-UI, A2UI and Websandbox. The [local integration status](OPENINTELLIGENTUI_LOCAL_INTEGRATION.md) records the implemented first slice, setup, tests and outstanding acceptance gates. It is not activated or accepted for production.

A native Expo mobile application, Daytona agent sandbox adapter, broader connected apps, selected hosted workflow infrastructure, and the complete general-purpose agent track remain design/implementation work. Installing the Daytona SDK or preparing a smoke check does not implement those capabilities. Existing service contracts should be reconciled before introducing replacements.

The [revised agent architecture](../Open%20Learn%202.0/26_agent_execution_platform.md) maps the inspected services to the proposed persistent assistant, responsibility/task contracts, feature flows, migration and acceptance gates. It identifies the existing interactive-generation disconnect policy and worker/outbox reconciliation as explicit integration boundaries.
