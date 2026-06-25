import { getToken, refreshToken } from '@/lib/tokenStore';
import { getAPIBaseURL } from '@/lib/config';

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

async function parseErrorDetail(response: Response, fallback: string) {
  try {
    const body = await response.json();
    return body?.detail || body?.message || fallback;
  } catch {
    return fallback;
  }
}

function buildAppConfigUrl(path: string) {
  const baseUrl = getAPIBaseURL().replace(/\/$/, '');
  return `${baseUrl}${path}`;
}

async function requestAppConfig<T>(
  path: string,
  init: RequestInit = {},
  options: { retriedAuth?: boolean; retriedNetwork?: boolean } = {},
): Promise<T> {
  const token = getToken();
  try {
    const response = await fetch(buildAppConfigUrl(path), {
      ...init,
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
    if (!options.retriedNetwork && (err?.name === 'TypeError' || /Network Error|Failed to fetch/i.test(err?.message || ''))) {
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
