import { useEffect, useRef } from 'react';

type RefreshCallback = () => void | Promise<void>;

type AutoRefreshOptions = {
  enabled?: boolean;
  intervalMs?: number;
  refreshOnFocus?: boolean;
  refreshOnReconnect?: boolean;
};

export function useAutoRefresh(
  refresh: RefreshCallback,
  {
    enabled = true,
    intervalMs = 30000,
    refreshOnFocus = true,
    refreshOnReconnect = true,
  }: AutoRefreshOptions = {},
) {
  const refreshRef = useRef(refresh);
  const runningRef = useRef(false);

  useEffect(() => {
    refreshRef.current = refresh;
  }, [refresh]);

  useEffect(() => {
    if (!enabled || typeof window === 'undefined') return undefined;

    let disposed = false;
    const runRefresh = async () => {
      if (disposed || runningRef.current) return;
      if (document.visibilityState === 'hidden') return;
      runningRef.current = true;
      try {
        await refreshRef.current();
      } catch (err) {
        console.warn('Auto refresh failed:', err);
      } finally {
        runningRef.current = false;
      }
    };

    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') void runRefresh();
    };

    const intervalId = window.setInterval(() => void runRefresh(), intervalMs);
    document.addEventListener('visibilitychange', handleVisibilityChange);
    if (refreshOnFocus) window.addEventListener('focus', runRefresh);
    if (refreshOnReconnect) window.addEventListener('online', runRefresh);

    return () => {
      disposed = true;
      window.clearInterval(intervalId);
      document.removeEventListener('visibilitychange', handleVisibilityChange);
      if (refreshOnFocus) window.removeEventListener('focus', runRefresh);
      if (refreshOnReconnect) window.removeEventListener('online', runRefresh);
    };
  }, [enabled, intervalMs, refreshOnFocus, refreshOnReconnect]);
}
