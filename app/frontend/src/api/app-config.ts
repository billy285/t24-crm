import { invokeWithAuth } from '@/lib/tokenStore';

export type AppConfigKey =
  | 'role_permissions'
  | 'customer_code_settings'
  | 'company_info'
  | 'dict_config'
  | 'dashboard_config'
  | 'reminder_config'
  | 'security_config'
  | 'notification_config'
  | 'export_config';

export interface AppConfigValue<T = any> {
  key: AppConfigKey;
  value: T;
  updated_at?: string | null;
}

export interface AppConfigCollection {
  items: Partial<Record<AppConfigKey, AppConfigValue>>;
}

export const appConfigApi = {
  async getAll(): Promise<Partial<Record<AppConfigKey, AppConfigValue>>> {
    const response = await invokeWithAuth({
      url: '/api/v1/app-config',
      method: 'GET',
    });
    return response.data?.items || {};
  },

  async get<T = any>(key: AppConfigKey): Promise<AppConfigValue<T>> {
    const response = await invokeWithAuth({
      url: `/api/v1/app-config/${key}`,
      method: 'GET',
    });
    return response.data;
  },

  async update<T = any>(key: AppConfigKey, value: T): Promise<AppConfigValue<T>> {
    const response = await invokeWithAuth({
      url: `/api/v1/app-config/${key}`,
      method: 'PUT',
      data: { value },
    });
    return response.data;
  },
};
