export type AuthPersistence = 'session' | 'persistent';

export const EMP_TOKEN_KEY = 'emp_auth_token';
export const SDK_TOKEN_KEY = 'token';
export const EMP_DATA_KEY = 'emp_auth_data';

const REMEMBERED_LOGIN_KEY = 'emp_auth_remembered';
const SESSION_LOGIN_KEY = 'emp_auth_session';
const EXPLICIT_LOGOUT_KEY = 'emp_auth_logged_out';
let inMemoryToken = '';

function readStorage(storage: Storage | undefined, key: string): string {
  if (!storage) return '';
  try {
    return storage.getItem(key) || '';
  } catch {
    return '';
  }
}

function removeStorageKeys(storage: Storage | undefined, keys: string[]): void {
  if (!storage) return;
  try {
    keys.forEach(key => storage.removeItem(key));
  } catch {
    // Storage may be unavailable in privacy-restricted browsers.
  }
}

function browserStorage(kind: 'local' | 'session'): Storage | undefined {
  if (typeof window === 'undefined') return undefined;
  try {
    return kind === 'local' ? window.localStorage : window.sessionStorage;
  } catch {
    return undefined;
  }
}

export function getAuthPersistence(): AuthPersistence {
  const local = browserStorage('local');
  if (readStorage(local, REMEMBERED_LOGIN_KEY) === '1') return 'persistent';
  return 'session';
}

export function wasExplicitlyLoggedOut(): boolean {
  return readStorage(browserStorage('local'), EXPLICIT_LOGOUT_KEY) === '1';
}

export function markExplicitLogout(): void {
  try {
    browserStorage('local')?.setItem(EXPLICIT_LOGOUT_KEY, '1');
  } catch {
    // The access and employee tokens are still cleared even without the marker.
  }
}

export function getStoredToken(): string {
  if (wasExplicitlyLoggedOut()) return '';
  const session = browserStorage('session');
  const local = browserStorage('local');
  const sessionToken = readStorage(session, EMP_TOKEN_KEY) || readStorage(session, SDK_TOKEN_KEY);
  if (sessionToken) return sessionToken;

  // Migrate access tokens written by older releases out of persistent browser
  // storage. Long-lived login is carried by the HttpOnly refresh cookie; the
  // browser-readable bearer token only needs to survive the current tab session.
  const legacyPersistentToken = readStorage(local, EMP_TOKEN_KEY) || readStorage(local, SDK_TOKEN_KEY);
  if (!legacyPersistentToken) return inMemoryToken;
  inMemoryToken = legacyPersistentToken;
  try {
    session?.setItem(EMP_TOKEN_KEY, legacyPersistentToken);
    session?.setItem(SDK_TOKEN_KEY, legacyPersistentToken);
    removeStorageKeys(local, [EMP_TOKEN_KEY, SDK_TOKEN_KEY]);
  } catch {
    // Returning the token preserves the current session even when storage is
    // restricted; the next authenticated write will retry the migration.
  }
  return legacyPersistentToken;
}

export function storeToken(token: string, persistence: AuthPersistence): void {
  clearStoredToken();
  inMemoryToken = token;
  const target = browserStorage('session');
  if (!target) return;

  try {
    target.setItem(EMP_TOKEN_KEY, token);
    target.setItem(SDK_TOKEN_KEY, token);
    if (persistence === 'persistent') {
      browserStorage('local')?.setItem(REMEMBERED_LOGIN_KEY, '1');
    } else {
      browserStorage('session')?.setItem(SESSION_LOGIN_KEY, '1');
    }
    browserStorage('local')?.removeItem(EXPLICIT_LOGOUT_KEY);
  } catch {
    // The caller can still use the in-memory login state for this render.
  }
}

export function clearStoredToken(): void {
  inMemoryToken = '';
  const keys = [EMP_TOKEN_KEY, SDK_TOKEN_KEY, REMEMBERED_LOGIN_KEY, SESSION_LOGIN_KEY];
  removeStorageKeys(browserStorage('local'), keys);
  removeStorageKeys(browserStorage('session'), keys);
}

export function getStoredEmployee(): string {
  return readStorage(browserStorage('session'), EMP_DATA_KEY)
    || readStorage(browserStorage('local'), EMP_DATA_KEY);
}

export function storeEmployee(employee: unknown, persistence: AuthPersistence): void {
  clearStoredEmployee();
  const target = browserStorage(persistence === 'persistent' ? 'local' : 'session');
  if (!target) return;
  try {
    target.setItem(EMP_DATA_KEY, JSON.stringify(employee));
  } catch {
    // Employee data is a convenience cache only; /me remains authoritative.
  }
}

export function clearStoredEmployee(): void {
  removeStorageKeys(browserStorage('local'), [EMP_DATA_KEY]);
  removeStorageKeys(browserStorage('session'), [EMP_DATA_KEY]);
}
