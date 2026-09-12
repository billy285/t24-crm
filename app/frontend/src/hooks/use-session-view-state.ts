import { useEffect, useMemo, useState, type SetStateAction } from 'react';

// Only transient view preferences belong here. Never store records or form drafts.
export function useSessionViewState<T extends object>(key: string, defaults: T) {
  const initial = useMemo(() => {
    try {
      const saved = JSON.parse(window.sessionStorage.getItem(key) || '{}');
      const restore = (base: Record<string, unknown>, source: Record<string, unknown>): Record<string, unknown> => (
        Object.fromEntries(Object.entries(base).map(([field, value]) => {
          const candidate = source?.[field];
          if (value && typeof value === 'object' && !Array.isArray(value)) {
            return [field, restore(value as Record<string, unknown>, candidate as Record<string, unknown>)];
          }
          return [field, typeof candidate === typeof value && (typeof candidate !== 'number' || (Number.isFinite(candidate) && candidate > 0)) ? candidate : value];
        }))
      );
      return restore(defaults as Record<string, unknown>, saved) as T;
    } catch {
      return defaults;
    }
  }, [key, defaults]);
  const [snapshot, setSnapshot] = useState({ key, value: initial });
  const value = snapshot.key === key ? snapshot.value : initial;

  useEffect(() => {
    try {
      window.sessionStorage.setItem(key, JSON.stringify(value));
    } catch {
      // Browsers without session storage can still use the current page normally.
    }
  }, [key, value]);

  const setField = <K extends keyof T>(field: K, update: SetStateAction<T[K]>) => {
    setSnapshot(previous => {
      const current = previous.key === key ? previous.value : initial;
      const next = typeof update === 'function'
        ? (update as (value: T[K]) => T[K])(current[field])
        : update;
      return { key, value: { ...current, [field]: next } };
    });
  };
  return [value, setField] as const;
}
