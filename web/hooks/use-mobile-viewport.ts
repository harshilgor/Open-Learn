import { useEffect, useRef } from 'react';

export function useMobileViewport() {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const element = ref.current;
    const viewport = window.visualViewport;
    if (!element || !viewport) return;
    let frame = 0;
    const update = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        const mobile = window.matchMedia('(max-width: 1023px)').matches;
        if (!mobile) {
          element.style.removeProperty('--mobile-viewport-height');
          delete element.dataset.keyboardOpen;
          return;
        }
        element.style.setProperty('--mobile-viewport-height', `${Math.round(viewport.height)}px`);
        const editing = document.activeElement?.matches('textarea, input, [contenteditable="true"]');
        element.dataset.keyboardOpen = String(!!editing && window.innerHeight - viewport.height > 120);
      });
    };
    update();
    viewport.addEventListener('resize', update);
    window.addEventListener('resize', update);
    document.addEventListener('focusin', update);
    document.addEventListener('focusout', update);
    return () => {
      cancelAnimationFrame(frame);
      viewport.removeEventListener('resize', update);
      window.removeEventListener('resize', update);
      document.removeEventListener('focusin', update);
      document.removeEventListener('focusout', update);
    };
  }, []);
  return ref;
}
