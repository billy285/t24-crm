import { client } from './api';

const EMP_TOKEN_KEY = 'emp_auth_token';

export const getToken = (): string => localStorage.getItem(EMP_TOKEN_KEY) || '';
export const setToken = (t: string): void => {
  try {
    localStorage.setItem(EMP_TOKEN_KEY, t);
  } catch (e) {
    // Fallback: ignore storage quota errors
    // eslint-disable-next-line no-console
    console.warn('Failed to persist token to localStorage:', e);
  }
};
export const clearToken = (): void => {
  try {
    localStorage.removeItem(EMP_TOKEN_KEY);
  } catch (e) {
    // eslint-disable-next-line no-console
    console.warn('Failed to remove token from localStorage:', e);
  }
};

export async function refreshToken(): Promise<string | null> {
  try {
    const res = await client.apiCall.invoke({
      url: '/api/v1/emp-auth/refresh',
      method: 'POST',
      options: { withCredentials: true },
    });
    const newTok: string | undefined = res?.data?.access_token;
    if (newTok) {
      setToken(newTok);
      return newTok;
    }
    return null;
  } catch (e) {
    // eslint-disable-next-line no-console
    console.warn('Refresh token failed:', e);
    return null;
  }
}

type InvokeArgs = {
  url: string;
  method: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  data?: any;
  options?: any;
};

export async function invokeWithAuth(args: InvokeArgs) {
  const baseHeaders = (args.options && args.options.headers) || {};
  let token = getToken();
  try {
    const res = await client.apiCall.invoke({
      url: args.url,
      method: args.method,
      data: args.data,
      options: {
        ...args.options,
        headers: { ...baseHeaders, ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      },
    });
    return res;
  } catch (err: any) {
    const status = err?.response?.status || err?.data?.status || 0;
    if (status === 401) {
      try {
        const newToken = await refreshToken();
        if (newToken) {
          token = newToken;
          const res2 = await client.apiCall.invoke({
            url: args.url,
            method: args.method,
            data: args.data,
            options: {
              ...args.options,
              headers: { ...baseHeaders, Authorization: `Bearer ${token}` },
            },
          });
          return res2;
        }
      } catch (e) {
        // eslint-disable-next-line no-console
        console.warn('Retry after refresh failed:', e);
      }
    }
    throw err;
  }
}