import { clearToken, invokeWithAuth, refreshToken, setToken, getToken } from './tokenStore';
import { AUTH_SESSION_INVALIDATED_EVENT, markExplicitLogout, clearStoredEmployee } from './auth-storage';
import { clearCachedAppConfig } from './app-config';

export async function login(username: string, password: string, remember: boolean): Promise<boolean> {
  const res = await invokeWithAuth({
    url: '/api/v1/emp-auth/login',
    method: 'POST',
    data: { email: username, password },
  });
  const accessToken = res?.data?.access_token || res?.data?.token;
  if (accessToken) {
    setToken(accessToken, remember ? 'persistent' : 'session');
    return true;
  }
  return false;
}

export async function refresh(): Promise<boolean> {
  return Boolean(await refreshToken());
}

export function logout(): void {
  const token = getToken();
  markExplicitLogout();
  clearToken();
  clearStoredEmployee();
  clearCachedAppConfig();
  if (typeof window !== 'undefined') window.dispatchEvent(new Event(AUTH_SESSION_INVALIDATED_EVENT));
  void invokeWithAuth({
    url: '/api/v1/emp-auth/logout', method: 'POST',
    options: { withCredentials: true, headers: token ? { Authorization: `Bearer ${token}` } : {} },
  }).catch(() => undefined);
}
