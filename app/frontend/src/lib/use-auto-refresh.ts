import { useEffect, useRef } from 'react';
import { BUSINESS_DATA_REFRESH_EVENT } from './data-refresh';

type RefreshCallback = () => void | Promise<void>;

type AutoRefreshOptions = {
  enabled?: boolean;
  intervalMs?: number;
  refreshOnFocus?: boolean;
  refreshOnReconnect?: boolean;
  refreshOnMount?: boolean;
};

export function useAutoRefresh(
  refresh: RefreshCallback,
  {
    enabled = true,
    intervalMs = 30000,
    refreshOnFocus = true,
    refreshOnReconnect = true,
    refreshOnMount = false,
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

    const handlePageShow = () => void runRefresh();
    const handleBusinessDataRefresh = () => void runRefresh();

    const intervalId = window.setInterval(() => void runRefresh(), intervalMs);
    document.addEventListener('visibilitychange', handleVisibilityChange);
    window.addEventListener('pageshow', handlePageShow);
    window.addEventListener(BUSINESS_DATA_REFRESH_EVENT, handleBusinessDataRefresh);
    if (refreshOnFocus) window.addEventListener('focus', handleBusinessDataRefresh);
    if (refreshOnReconnect) window.addEventListener('online', handleBusinessDataRefresh);

    // Pages perform their own initial request. Keep the mount refresh opt-in so
    // navigation does not immediately duplicate every page's API calls.
    const mountRefreshId = refreshOnMount
      ? window.setTimeout(() => void runRefresh(), 250)
      : undefined;

    return () => {
      disposed = true;
      window.clearInterval(intervalId);
      if (mountRefreshId !== undefined) window.clearTimeout(mountRefreshId);
      document.removeEventListener('visibilitychange', handleVisibilityChange);
      window.removeEventListener('pageshow', handlePageShow);
      window.removeEventListener(BUSINESS_DATA_REFRESH_EVENT, handleBusinessDataRefresh);
      if (refreshOnFocus) window.removeEventListener('focus', handleBusinessDataRefresh);
      if (refreshOnReconnect) window.removeEventListener('online', handleBusinessDataRefresh);
    };
  }, [enabled, intervalMs, refreshOnFocus, refreshOnReconnect, refreshOnMount]);
}
