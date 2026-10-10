export type AuthPersistence = 'session' | 'persistent';

export const EMP_TOKEN_KEY = 'emp_auth_token';
export const SDK_TOKEN_KEY = 'token';
export const EMP_DATA_KEY = 'emp_auth_data';

const REMEMBERED_LOGIN_KEY = 'emp_auth_remembered';
const SESSION_LOGIN_KEY = 'emp_auth_session';
const EXPLICIT_LOGOUT_KEY = 'emp_auth_logged_out';
export const AUTH_SESSION_EPOCH_KEY = 'emp_auth_epoch';
export const AUTH_SESSION_INVALIDATED_EVENT = 'crm:auth-session-invalidated';
let inMemoryToken = '';
let tokenEpoch = '';
let inMemoryEpoch = 'initial';
let lastObservedStorageEpoch = '';
let explicitlyLoggedOut = false;
let epochCounter = 0;

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

export function getAuthSessionEpoch(): string {
  const storedEpoch = readStorage(browserStorage('local'), AUTH_SESSION_EPOCH_KEY);
  if (storedEpoch && storedEpoch !== lastObservedStorageEpoch) {
    lastObservedStorageEpoch = storedEpoch;
    inMemoryEpoch = storedEpoch;
  }
  return inMemoryEpoch;
}

// Advance only at identity boundaries. Rotating a token keeps the same epoch so
// concurrent requests may reuse a completed refresh without crossing accounts.
export function beginAuthSession(): void {
  inMemoryEpoch = `${Date.now()}:${++epochCounter}:${Math.random().toString(36).slice(2)}`;
  const storage = browserStorage('local');
  try { storage?.setItem(AUTH_SESSION_EPOCH_KEY, inMemoryEpoch); } catch { /* Memory still protects this tab. */ }
  // A readable but full/blocked store must not override the new in-memory epoch.
  lastObservedStorageEpoch = readStorage(storage, AUTH_SESSION_EPOCH_KEY);
}

export function wasExplicitlyLoggedOut(): boolean {
  return explicitlyLoggedOut || readStorage(browserStorage('local'), EXPLICIT_LOGOUT_KEY) === '1';
}

export function markExplicitLogout(): void {
  explicitlyLoggedOut = true;
  beginAuthSession();
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
  const storedEpoch = readStorage(session, AUTH_SESSION_EPOCH_KEY);
  const currentEpoch = getAuthSessionEpoch();
  if (sessionToken && storedEpoch && storedEpoch !== currentEpoch) {
    removeStorageKeys(session, [EMP_TOKEN_KEY, SDK_TOKEN_KEY, EMP_DATA_KEY, AUTH_SESSION_EPOCH_KEY]);
    inMemoryToken = '';
    return '';
  }
  if (sessionToken) {
    if (!storedEpoch) {
      try { session?.setItem(AUTH_SESSION_EPOCH_KEY, currentEpoch); } catch { /* Legacy token is confined to this runtime. */ }
    }
    return sessionToken;
  }

  // Migrate access tokens written by older releases out of persistent browser
  // storage. Long-lived login is carried by the HttpOnly refresh cookie; the
  // browser-readable bearer token only needs to survive the current tab session.
  const legacyPersistentToken = readStorage(local, EMP_TOKEN_KEY) || readStorage(local, SDK_TOKEN_KEY);
  if (!legacyPersistentToken) return tokenEpoch === currentEpoch ? inMemoryToken : '';
  inMemoryToken = legacyPersistentToken;
  tokenEpoch = currentEpoch;
  try {
    session?.setItem(EMP_TOKEN_KEY, legacyPersistentToken);
    session?.setItem(SDK_TOKEN_KEY, legacyPersistentToken);
    session?.setItem(AUTH_SESSION_EPOCH_KEY, currentEpoch);
    removeStorageKeys(local, [EMP_TOKEN_KEY, SDK_TOKEN_KEY]);
  } catch {
    // Returning the token preserves the current session even when storage is
    // restricted; the next authenticated write will retry the migration.
  }
  return legacyPersistentToken;
}

export function storeToken(token: string, persistence: AuthPersistence): void {
  clearTokenValues();
  explicitlyLoggedOut = false;
  inMemoryToken = token;
  tokenEpoch = getAuthSessionEpoch();
  const target = browserStorage('session');
  try { browserStorage('local')?.removeItem(EXPLICIT_LOGOUT_KEY); } catch { /* In-memory state remains usable. */ }
  if (!target) return;

  try {
    target.setItem(EMP_TOKEN_KEY, token);
    target.setItem(SDK_TOKEN_KEY, token);
    target.setItem(AUTH_SESSION_EPOCH_KEY, tokenEpoch);
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

function clearTokenValues(): void {
  inMemoryToken = '';
  tokenEpoch = '';
  const keys = [EMP_TOKEN_KEY, SDK_TOKEN_KEY, REMEMBERED_LOGIN_KEY, SESSION_LOGIN_KEY];
  removeStorageKeys(browserStorage('local'), keys);
  removeStorageKeys(browserStorage('session'), [...keys, AUTH_SESSION_EPOCH_KEY]);
}

export function clearStoredToken(): void {
  beginAuthSession();
  clearTokenValues();
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
