import { useEffect, useRef, useState } from 'react';
import { getStoredEmployee } from './auth-storage';

/** Retain only list controls within this signed-in employee's browser tab. */
export function useRetainedView<T>(key: string, initial: T) {
  const scopedKey = useRef(`t24-view:${key}:${(() => { try { return JSON.parse(getStoredEmployee() || '{}').id || 'current'; } catch { return 'current'; } })()}`);
  const [value, setValue] = useState<T>(() => {
    try { const saved = sessionStorage.getItem(scopedKey.current); return saved ? JSON.parse(saved) as T : initial; }
    catch { return initial; }
  });
  useEffect(() => { try { sessionStorage.setItem(scopedKey.current, JSON.stringify(value)); } catch { /* Persistence is optional. */ } }, [value]);
  return [value, setValue] as const;
}
