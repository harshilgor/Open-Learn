// Adapted from CopilotKit/OpenIntelligentUI; see LICENSE and UPSTREAM.json.
// React-free so the runtime verification kit shares the exact sizing rule.
export const MIN_HEIGHT = 50;
export const MAX_HEIGHT = 4000;

/**
 * Clamp a sandbox-reported height to the allowed range. Returns null for
 * anything that is not a finite number (NaN/Infinity pass a bare typeof
 * check and would otherwise poison the container height).
 */
export function clampReportedHeight(height: unknown): number | null {
  if (typeof height !== "number" || !Number.isFinite(height)) return null;
  return Math.max(MIN_HEIGHT, Math.min(Math.ceil(height), MAX_HEIGHT));
}
