import { appConfigApi, type AppConfigKey } from '@/api/app-config';

export const APP_CONFIG_UPDATED_EVENT = 'crm:app-config-updated';

export const APP_CONFIG_STORAGE_KEYS: Record<AppConfigKey, string> = {
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
  return typeof window !== 'undefined' && typeof window.localStorage !== 'undefined';
}

export function emitAppConfigUpdated(keys: AppConfigKey[] = []) {
  if (!hasStorage()) return;
  window.dispatchEvent(new CustomEvent(APP_CONFIG_UPDATED_EVENT, { detail: { keys } }));
}

export function readCachedAppConfig<T>(key: AppConfigKey, fallback: T): T {
  if (!hasStorage()) return fallback;
  try {
    const stored = window.localStorage.getItem(APP_CONFIG_STORAGE_KEYS[key]);
    return stored ? JSON.parse(stored) as T : fallback;
  } catch {
    return fallback;
  }
}

export function writeCachedAppConfig<T>(key: AppConfigKey, value: T, options?: { emit?: boolean }) {
  if (!hasStorage()) return;
  window.localStorage.setItem(APP_CONFIG_STORAGE_KEYS[key], JSON.stringify(value));
  if (options?.emit !== false) {
    emitAppConfigUpdated([key]);
  }
}

export async function loadRemoteAppConfig<T>(key: AppConfigKey, fallback: T): Promise<T> {
  const response = await appConfigApi.get<T>(key);
  const value = response?.value ?? fallback;
  writeCachedAppConfig(key, value);
  return value;
}

export async function saveRemoteAppConfig<T>(key: AppConfigKey, value: T): Promise<T> {
  const response = await appConfigApi.update<T>(key, value);
  const saved = response?.value ?? value;
  writeCachedAppConfig(key, saved);
  return saved;
}

export async function syncAppConfigCache(): Promise<Partial<Record<AppConfigKey, any>>> {
  const items = await appConfigApi.getAll();
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
