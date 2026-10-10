import { client } from '@/lib/api';

export type AppConfigKey =
  | 'role_permissions'
  | 'customer_code_settings'
  | 'company_info'
  | 'dict_config'
  | 'dashboard_config'
  | 'reminder_config'
  | 'security_config'
  | 'notification_config'
  | 'export_config'
  | 'payroll_sheets_v1';

export interface AppConfigValue<T = any> {
  key: AppConfigKey;
  value: T;
  updated_at?: string | null;
}

export interface AppConfigCollection {
  items: Partial<Record<AppConfigKey, AppConfigValue>>;
}

// Use the same authenticated SDK transport as the rest of the application.
// This preserves HTTP status information and prevents a stale config response
// or network retry from crossing an employee identity boundary.
async function requestAppConfig<T>(path: string, init: { method?: 'GET' | 'PUT'; data?: unknown } = {}): Promise<T> {
  const response = await client.apiCall.invoke({
    url: path, method: init.method || 'GET', data: init.data,
    options: { withCredentials: true, headers: { 'Cache-Control': 'no-cache' } },
  });
  return response.data as T;
}

export const appConfigApi = {
  async getAll(): Promise<Partial<Record<AppConfigKey, AppConfigValue>>> {
    const response = await requestAppConfig<AppConfigCollection>('/api/v1/app-config');
    return response?.items || {};
  },

  async get<T = any>(key: AppConfigKey): Promise<AppConfigValue<T>> {
    return requestAppConfig<AppConfigValue<T>>(`/api/v1/app-config/${key}`);
  },

  async update<T = any>(key: AppConfigKey, value: T): Promise<AppConfigValue<T>> {
    return requestAppConfig<AppConfigValue<T>>(`/api/v1/app-config/${key}`, {
      method: 'PUT',
      data: { value },
    });
  },
};
