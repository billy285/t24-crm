import { useEffect, useRef } from 'react';

/** Keep the reading position on the original list without storing customer data. */
export function useSalesListPosition(owner: string, ready: boolean) {
  const restored = useRef(false);
  const key = useRef('');
  key.current = `t24:sales-list-position:${owner}:${window.location.pathname}${window.location.search}`;
  useEffect(() => {
    restored.current = false;
  }, [owner]);
  useEffect(() => {
    if (!ready || restored.current) return;
    restored.current = true;
    const main = document.querySelector<HTMLElement>('.app-main');
    let top = 0;
    try { top = Math.max(0, Number(sessionStorage.getItem(key.current)) || 0); } catch { /* Storage may be disabled. */ }
    const frame = requestAnimationFrame(() => { if (main && main.scrollHeight > main.clientHeight) main.scrollTop = top; else window.scrollTo(0, top); });
    return () => cancelAnimationFrame(frame);
  }, [ready, owner]);
  useEffect(() => {
    const main = document.querySelector<HTMLElement>('.app-main');
    const save = () => { if (!restored.current) return; try { sessionStorage.setItem(key.current, String(main && main.scrollHeight > main.clientHeight ? main.scrollTop : window.scrollY)); } catch { /* Optional convenience. */ } };
    main?.addEventListener('scroll', save, { passive: true });
    window.addEventListener('scroll', save, { passive: true });
    window.addEventListener('pagehide', save);
    return () => { main?.removeEventListener('scroll', save); window.removeEventListener('scroll', save); window.removeEventListener('pagehide', save); };
  }, [owner]);
}
