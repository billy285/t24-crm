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

type AppConfigMethod = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';

function parseRequestBody(body: BodyInit | null | undefined) {
  if (!body) return undefined;
  if (typeof body !== 'string') return body;
  try {
    return JSON.parse(body);
  } catch {
    return body;
  }
}

function isNetworkError(err: any) {
  const message = err?.message || err?.data?.message || err?.response?.data?.message || '';
  return /Network Error|Failed to fetch|timeout|ERR_NETWORK/i.test(message);
}

async function requestAppConfig<T>(
  path: string,
  init: RequestInit = {},
  options: { retriedNetwork?: boolean } = {},
): Promise<T> {
  try {
    const response = await invokeWithAuth({
      url: path,
      method: (init.method || 'GET') as AppConfigMethod,
      data: parseRequestBody(init.body),
      options: {
        withCredentials: true,
        headers: {
          ...(init.body ? { 'Content-Type': 'application/json' } : {}),
          ...(init.headers || {}),
        },
      },
    });
    return response?.data as T;
  } catch (err: any) {
    if (isNetworkError(err) && !options.retriedNetwork) {
      await new Promise(resolve => setTimeout(resolve, 600));
      return requestAppConfig<T>(path, init, { ...options, retriedNetwork: true });
    }
    throw err;
  }
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
      body: JSON.stringify({ value }),
    });
  },
};
