import { client, refreshClientAuth } from './api';
import {
  type AuthPersistence,
  clearStoredToken,
  getAuthPersistence,
  getStoredToken,
  storeToken,
  wasExplicitlyLoggedOut,
} from './auth-storage';

export const getToken = (): string => getStoredToken();
export const setToken = (token: string, persistence: AuthPersistence | boolean = getAuthPersistence()): void => {
  const resolvedPersistence = typeof persistence === 'boolean'
    ? (persistence ? 'persistent' : 'session')
    : persistence;
  try {
    storeToken(token, resolvedPersistence);
    refreshClientAuth();
  } catch (e) {
    // eslint-disable-next-line no-console
    console.warn('Failed to persist the access token:', e);
  }
};
export const clearToken = (): void => {
  try {
    clearStoredToken();
    refreshClientAuth();
  } catch (e) {
    // eslint-disable-next-line no-console
    console.warn('Failed to remove the access token:', e);
  }
};

export async function refreshToken(): Promise<string | null> {
  if (wasExplicitlyLoggedOut()) return null;
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
