# Buddy production release — October 10, 2026

Release commit: `49138382a5ef0d0750c5c5940be236206e05b401` on `main`.

- Vercel production `dpl_HCVZow8bAhUDUF8ePvUsxgLXH9fC` is Ready at https://open-learn-eta.vercel.app.
- Render API deployment `dep-db5beo0473hc73ai8hh0` is Live on the same commit. `/ready` returns HTTP 200. OpenAPI confirms appearance, focus, hintsFirst, exampleTheme, and rememberPreferences fields.
- Production build and TypeScript passed. Four Buddy interface tests and 18 backend Buddy tests passed.
- Authenticated production browser check created a temporary blue Buddy with Cap and Scarf, switched to it, and reopened Customize to confirm saved appearance. Screenshot: `work/buddy-production-editor.png`.
- Assets are shared SVG React components. The app uses them in navigation, headers, course companions, creation/customization, and thinking status. Profiles persist appearance in existing JSON payloads without a schema migration.
- Production currently has intermittent database pool timeouts unrelated to Buddy schema. The verification Buddy was successfully archived after retry; the original Buddy was restored.
