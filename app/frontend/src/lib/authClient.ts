import { clearToken, invokeWithAuth, refreshToken, setToken } from './tokenStore';

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
  void invokeWithAuth({ url: '/api/v1/emp-auth/logout', method: 'POST' })
    .catch(() => undefined)
    .finally(() => clearToken());
}
