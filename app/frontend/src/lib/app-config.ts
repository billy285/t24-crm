import { appConfigApi, type AppConfigKey } from '@/api/app-config';
import { AUTH_SESSION_INVALIDATED_EVENT, getAuthSessionEpoch } from './auth-storage';
import { authSessionChangedError, isAuthSessionCurrent } from './api';

export const APP_CONFIG_UPDATED_EVENT = 'crm:app-config-updated';
const suppressedCacheKeys = new Set<AppConfigKey>();

// Sensitive server-only configuration (for example payroll_sheets_v1) must
// never be mirrored into browser storage. Only explicitly listed keys are
// eligible for the local compatibility cache.
export const APP_CONFIG_STORAGE_KEYS: Partial<Record<AppConfigKey, string>> = {
  role_permissions: 'crm_role_permissions',
  customer_code_settings: 'crm_customer_code_settings',
  company_info: 'crm_company_info',
  dict_config: 'crm_dict_config',
  dashboard_config: 'crm_dashboard_config',
  reminder_config: 'crm_reminder_config',
  security_config: 'crm_security_config',
  notification_config: 'crm_notification_config',
  export_config: 'crm_export_config',
};

function hasStorage() {
  try { return typeof window !== 'undefined' && typeof window.localStorage !== 'undefined'; }
  catch { return false; }
}

export function emitAppConfigUpdated(keys: AppConfigKey[] = []) {
  if (!hasStorage()) return;
  window.dispatchEvent(new CustomEvent(APP_CONFIG_UPDATED_EVENT, { detail: { keys } }));
}

export function readCachedAppConfig<T>(key: AppConfigKey, fallback: T): T {
  if (!hasStorage() || suppressedCacheKeys.has(key)) return fallback;
  const storageKey = APP_CONFIG_STORAGE_KEYS[key];
  if (!storageKey) return fallback;
  try {
    const stored = window.localStorage.getItem(storageKey);
    return stored ? JSON.parse(stored) as T : fallback;
  } catch {
    return fallback;
  }
}

export function writeCachedAppConfig<T>(key: AppConfigKey, value: T, options?: { emit?: boolean }) {
  if (!hasStorage()) return;
  const storageKey = APP_CONFIG_STORAGE_KEYS[key];
  if (!storageKey) return;
  try { window.localStorage.setItem(storageKey, JSON.stringify(value)); }
  catch { return; }
  suppressedCacheKeys.delete(key);
  if (options?.emit !== false) {
    emitAppConfigUpdated([key]);
  }
}

export function clearCachedAppConfig() {
  (Object.keys(APP_CONFIG_STORAGE_KEYS) as AppConfigKey[]).forEach(key => suppressedCacheKeys.add(key));
  if (!hasStorage()) return;
  (Object.keys(APP_CONFIG_STORAGE_KEYS) as AppConfigKey[]).forEach((key) => {
    const storageKey = APP_CONFIG_STORAGE_KEYS[key];
    try { if (storageKey) window.localStorage.removeItem(storageKey); } catch { /* Fall back to checked-in defaults. */ }
  });
  emitAppConfigUpdated(Object.keys(APP_CONFIG_STORAGE_KEYS) as AppConfigKey[]);
}

export async function loadRemoteAppConfig<T>(key: AppConfigKey, fallback: T): Promise<T> {
  const epoch = getAuthSessionEpoch();
  const response = await appConfigApi.get<T>(key);
  if (!isAuthSessionCurrent(epoch)) throw authSessionChangedError();
  const value = response?.value ?? fallback;
  writeCachedAppConfig(key, value);
  return value;
}

export async function saveRemoteAppConfig<T>(key: AppConfigKey, value: T): Promise<T> {
  const epoch = getAuthSessionEpoch();
  const response = await appConfigApi.update<T>(key, value);
  if (!isAuthSessionCurrent(epoch)) throw authSessionChangedError();
  const saved = response?.value ?? value;
  writeCachedAppConfig(key, saved);
  return saved;
}

export async function syncAppConfigCache(): Promise<Partial<Record<AppConfigKey, any>>> {
  const epoch = getAuthSessionEpoch();
  const items = await appConfigApi.getAll();
  if (!isAuthSessionCurrent(epoch)) throw authSessionChangedError();
  clearCachedAppConfig();
  const touched: AppConfigKey[] = [];

  (Object.keys(APP_CONFIG_STORAGE_KEYS) as AppConfigKey[]).forEach((key) => {
    const item = items[key];
    if (!item) return;
    writeCachedAppConfig(key, item.value, { emit: false });
    touched.push(key);
  });

  if (touched.length > 0) {
    emitAppConfigUpdated(touched);
  }

  return items;
}

// The auth transport invalidates identity without importing this cache module.
// Clear sensitive convenience data even when the role UI is still mounting.
if (typeof window !== 'undefined') {
  window.addEventListener(AUTH_SESSION_INVALIDATED_EVENT, clearCachedAppConfig);
}
