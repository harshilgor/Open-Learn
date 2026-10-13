Quality contract. Before a learner sees it, Open Learn mounts the artifact in a sandboxed browser at 720px and 360px wide, moves every control, and rejects it if any of these happen:
- an uncaught error, a rejected promise or any console.error;
- an empty frame, or a canvas that is still blank after setup;
- visible text containing NaN, undefined, Infinity or [object Object], including after controls are moved to their minimum and maximum;
- content wider than the frame (it is clipped, not scrolled).
It also flags controls that change nothing visible, and unlabeled controls.

Build to pass it:
- Layout: a short heading and one-sentence purpose, a controls row, the main visual, live readouts, then two or three "what to notice" sentences. Use CSS grid or flex with flex-wrap; no fixed widths above 320px.
- The frame grows to fit its content, so height:100%, 100vh and position:fixed collapse or clip the main graphic. Give the graphic's container an explicit height (for example height:360px or aspect-ratio:16/9) and keep it in normal flow.
- Size every canvas and SVG from its container (SVG viewBox with width:100%; canvas width from clientWidth times devicePixelRatio), and redraw on resize. Three.js renderers use the container width and a ResizeObserver.
- Every control has a visible label and a live value with units, and each input event recomputes and redraws. State the formula next to computed results.
- Guard the mathematics: clamp inputs to their ranges, avoid division by zero and roots of negatives, keep simulations numerically stable (fixed small time steps, or analytic solutions where they exist), and format numbers with toFixed or Intl.NumberFormat.
- Animations use requestAnimationFrame, offer pause/reset, and respect prefers-reduced-motion. Keep any single frame cheap.
- When the brief includes "editTarget", the learner is changing that existing visual: start from its exact source, apply only the requested change, keep the remaining behavior, element ids and control ids, and return the complete updated artifact.
