The sandbox already includes the OpenIntelligentUI design system. Build on it instead of restyling from scratch.

Colors and theming:
- Use the CSS variables for every color: --color-background-primary / --color-background-secondary / --color-background-tertiary, --color-text-primary / --color-text-secondary / --color-text-tertiary, plus the semantic info/danger/success/warning variants (--color-background-info, --color-text-danger, --color-border-success, etc.).
- Dark mode is automatic via these variables — NEVER hardcode hex values for text or backgrounds.
- Fonts: --font-sans, --font-serif, --font-mono. Radii: --border-radius-md, --border-radius-lg, --border-radius-xl.

Form controls:
- button, input (text/number/email/search/range/checkbox/radio), textarea, and select are pre-styled by the design system. Do not restyle these basics.

SVG diagrams and charts:
- Pre-built color-ramp classes: .c-purple .c-teal .c-coral .c-pink .c-gray .c-blue .c-green .c-amber .c-red.
- Diagram helpers: .box .node .arr .leader for shapes/connectors, and .t .ts .th for text (body/small/heading).

Layout:
- Use flex/grid with compact spacing.
- The css parameter should hold widget-specific styles only — the theme, form styles, and SVG classes are already loaded.