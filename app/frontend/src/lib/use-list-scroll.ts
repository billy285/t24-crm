import { useEffect } from 'react';

/** Restore a list's position when returning from an associated record. */
export function useListScroll(key: string, enabled = true) {
  useEffect(() => {
    if (!enabled) return;
    const storageKey = `t24-list-scroll:${key}`;
    const main = document.querySelector<HTMLElement>('.app-main');
    const frame = requestAnimationFrame(() => {
      try {
        const saved = JSON.parse(sessionStorage.getItem(storageKey) || 'null');
        if (saved) { if (main) main.scrollTop = Number(saved.main || 0); window.scrollTo(0, Number(saved.window || 0)); }
      } catch { /* A new list starts at its normal position. */ }
    });
    const retain = () => {
      try { sessionStorage.setItem(storageKey, JSON.stringify({ main: main?.scrollTop || 0, window: window.scrollY })); } catch { /* Session storage is optional. */ }
    };
    main?.addEventListener('scroll', retain, { passive: true });
    window.addEventListener('scroll', retain, { passive: true });
    return () => { cancelAnimationFrame(frame); main?.removeEventListener('scroll', retain); window.removeEventListener('scroll', retain); };
  }, [key, enabled]);
}
