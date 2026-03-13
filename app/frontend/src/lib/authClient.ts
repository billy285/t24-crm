import { apiFetch, tokenStore } from './api';

export async function login(username: string, password: string, remember: boolean): Promise<boolean> {
  const res = await apiFetch('/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password, remember_me: remember })
  });
  if (!res.ok) return false;
  const data = await res.json();
  if (data?.access_token) {
    tokenStore.set(data.access_token, remember);
    return true;
  }
  return false;
}

export async function refresh(): Promise<boolean> {
  const res = await apiFetch('/auth/refresh', { method: 'POST' });
  if (!res.ok) return false;
  const data = await res.json();
  if (data?.access_token) {
    tokenStore.set(data.access_token, !!localStorage.getItem('access_token'));
    return true;
  }
  return false;
}

export function logout(): void {
  tokenStore.clear();
  // Fire and forget backend logout to clear cookie
  apiFetch('/auth/logout', { method: 'POST' }).catch(() => {});
}
