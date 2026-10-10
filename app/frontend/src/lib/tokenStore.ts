import { client, refreshClientAuth, refreshAccessToken } from './api';
import {
  type AuthPersistence,
  beginAuthSession,
  clearStoredToken,
  getAuthPersistence,
  getStoredToken,
  storeToken,
} from './auth-storage';

export const getToken = (): string => getStoredToken();
export const setToken = (token: string, persistence: AuthPersistence | boolean = getAuthPersistence()): void => {
  const resolvedPersistence = typeof persistence === 'boolean'
    ? (persistence ? 'persistent' : 'session')
    : persistence;
  try {
    beginAuthSession();
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

export const refreshToken = refreshAccessToken;

type InvokeArgs = {
  url: string;
  method: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  data?: any;
  options?: any;
};

// The SDK proxy handles the same refresh policy for both historical callers and
// direct apiCall/entity callers. Keep this compatibility entry point thin.
export async function invokeWithAuth(args: InvokeArgs) {
  return client.apiCall.invoke(args);
}
