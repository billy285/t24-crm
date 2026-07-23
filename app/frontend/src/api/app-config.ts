import { getToken, refreshToken } from '@/lib/tokenStore';

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

type AppConfigMethod = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';

function isNetworkError(err: any) {
  const message = err?.message || err?.data?.message || err?.response?.data?.message || '';
  return /Network Error|Failed to fetch|timeout|ERR_NETWORK/i.test(message);
}

async function parseErrorDetail(response: Response, fallback: string) {
  try {
    const body = await response.json();
    return body?.detail || body?.message || fallback;
  } catch {
    return fallback;
  }
}

async function requestAppConfig<T>(
  path: string,
  init: RequestInit = {},
  options: { retriedAuth?: boolean; retriedNetwork?: boolean } = {},
): Promise<T> {
  try {
    const token = getToken();
    const response = await fetch(path, {
      method: (init.method || 'GET') as AppConfigMethod,
      body: init.body,
      credentials: 'include',
      cache: 'no-store',
      headers: {
        ...(init.body ? { 'Content-Type': 'application/json' } : {}),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(init.headers || {}),
      },
    });

    if (response.status === 401 && !options.retriedAuth) {
      const newToken = await refreshToken();
      if (newToken) {
        return requestAppConfig<T>(path, init, { ...options, retriedAuth: true });
      }
    }

    if (!response.ok) {
      const detail = await parseErrorDetail(response, `请求失败 (${response.status})`);
      throw new Error(detail);
    }

    return response.json() as Promise<T>;
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
