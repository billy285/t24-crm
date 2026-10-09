import { useSyncExternalStore } from 'react';
import { hasUnsavedChanges } from './use-unsaved-changes';

const buildVersion = __T24_BUILD_VERSION__;
export type VersionState = { current: string; available: string | null; status: 'idle' | 'checking' | 'current' | 'update' | 'error' };
let state: VersionState = { current: buildVersion, available: null, status: 'idle' };
const listeners = new Set<() => void>();
let initialized = false;
let checking: Promise<void> | null = null;
let lastChecked = 0;
function publish(next: Partial<VersionState>) {
  state = { ...state, ...next };
  listeners.forEach(listener => listener());
}
export function checkAppVersion(): Promise<void> {
  if (checking) return checking;
  publish({ status: 'checking' });
  checking = (async () => {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 12000);
    try {
      const response = await fetch('/app-version.json', { cache: 'no-store', credentials: 'omit', signal: controller.signal });
      if (!response.ok) throw new Error('version unavailable');
      const data = await response.json();
      if (typeof data.version !== 'string' || !/^[a-f0-9]{12}$/.test(data.version)) throw new Error('invalid version');
      publish({ available: data.version === buildVersion ? null : data.version, status: data.version === buildVersion ? 'current' : 'update' });
      lastChecked = Date.now();
    } catch {
      publish({ status: state.available ? 'update' : 'error' });
    } finally {
      window.clearTimeout(timeout);
      checking = null;
    }
  })();
  return checking;
}
export function installAppVersionChecks() {
  if (initialized) return;
  initialized = true;
  const checkIfDue = () => {
    if (document.visibilityState === 'visible' && Date.now() - lastChecked > 60000) void checkAppVersion();
  };
  window.addEventListener('pageshow', checkIfDue);
  window.addEventListener('online', checkIfDue);
  document.addEventListener('visibilitychange', checkIfDue);
  window.addEventListener('t24:reload-required', () => { void checkAppVersion(); });
  window.setInterval(checkIfDue, 300000);
  void checkAppVersion();
}
export function applyAppUpdate(): boolean {
  if (hasUnsavedChanges()) return false;
  window.location.reload();
  return true;
}
export function useAppVersion() {
  return useSyncExternalStore(listener => {
    listeners.add(listener);
    return () => { listeners.delete(listener); };
  }, () => state, () => state);
}
