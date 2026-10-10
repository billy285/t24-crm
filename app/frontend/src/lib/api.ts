import { createClient } from '@metagptx/web-sdk';
import { getAPIBaseURL } from './config';
import {
  AUTH_SESSION_INVALIDATED_EVENT, clearStoredEmployee, clearStoredToken,
  getAuthPersistence, getAuthSessionEpoch, getStoredEmployee, getStoredToken, markExplicitLogout,
  storeToken, wasExplicitlyLoggedOut,
} from './auth-storage';

type SdkClient = ReturnType<typeof createClient>;
type InvokeArgs = Parameters<SdkClient['apiCall']['invoke']>[0];

const createSdkClient = (): SdkClient => {
  const token = getStoredToken();
  return createClient({
    baseURL: getAPIBaseURL(),
    timeout: 15000,
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
  } as any);
};

let activeClient = createSdkClient();
let refreshInFlight: { epoch: string; promise: Promise<string | null> } | null = null;
let temporarilyUnavailableRefreshEpoch = '';
let cookieControlTail: Promise<unknown> = Promise.resolve();
const COOKIE_CONTROL_LOCK = 't24-employee-auth-cookie-control';

export function isRefreshTemporarilyUnavailable(epoch: string): boolean {
  return temporarilyUnavailableRefreshEpoch === epoch;
}

export function authSessionChangedError(): Error {
  const error = new Error('登录账号已切换，请重新加载当前页面。');
  error.name = 'AuthSessionChangedError';
  return error;
}

export function isAuthSessionCurrent(epoch: string): boolean {
  return epoch === getAuthSessionEpoch() && !wasExplicitlyLoggedOut();
}

function httpStatus(error: any): number {
  return error?.response?.status || error?.data?.status || error?.status || 0;
}

// Auth control requests must never attempt to refresh themselves. In particular,
// a rejected password must not silently restore a previous employee's cookie.
function isAuthControlRequest(url: string): boolean {
  return /^\/api\/v1\/(?:emp-auth\/(?:login|refresh|logout|set_refresh)|auth\/(?:login|logout))(?:[/?#]|$)/.test(url);
}

function changesAuthCookie(url: string): boolean {
  return /^\/api\/v1\/emp-auth\/(?:refresh|logout|set_refresh)(?:[/?#]|$)/.test(url);
}

// A browser applies Set-Cookie before resolving the transport promise. Keep the
// lock until then: discarding a stale JS result alone cannot discard its cookie.
// Web Locks serialize tabs on this origin; the promise tail covers one tab when
// that API is unavailable. Never dispatch a queued, superseded account intent.
function runCookieControl<T>(epoch: string, execute: () => Promise<T>): Promise<T> {
  const dispatch = () => {
    if (epoch !== getAuthSessionEpoch()) throw authSessionChangedError();
    return execute();
  };
  const run = async (): Promise<T> => typeof navigator !== 'undefined' && navigator.locks
    ? await navigator.locks.request(COOKIE_CONTROL_LOCK, { mode: 'exclusive' }, dispatch)
    : await dispatch();
  const request = cookieControlTail.then(run, run);
  cookieControlTail = request.then(() => undefined, () => undefined);
  return request;
}

function invalidateConfirmedSession(epoch: string): void {
  if (!isAuthSessionCurrent(epoch)) return;
  markExplicitLogout();
  clearStoredToken();
  clearStoredEmployee();
  refreshClientAuth();
  if (typeof window !== 'undefined') window.dispatchEvent(new Event(AUTH_SESSION_INVALIDATED_EVENT));
}

function tokenIdentity(token: string): { emp_id?: number; sid?: string } | null {
  try {
    const encoded = token.split('.')[1];
    if (!encoded) return null;
    const claims = JSON.parse(atob(encoded.replace(/-/g, '+').replace(/_/g, '/')));
    return {
      emp_id: typeof claims.emp_id === 'number' && Number.isSafeInteger(claims.emp_id) ? claims.emp_id : undefined,
      sid: typeof claims.sid === 'string' ? claims.sid : undefined,
    };
  } catch { return null; }
}

function cachedEmployeeId(): number | undefined {
  try {
    const employee = JSON.parse(getStoredEmployee());
    return Number.isSafeInteger(employee?.id) && employee.id > 0 ? employee.id : undefined;
  } catch { return undefined; }
}

export function refreshAccessToken(): Promise<string | null> {
  if (wasExplicitlyLoggedOut()) return Promise.resolve(null);
  const epoch = getAuthSessionEpoch();
  if (refreshInFlight?.epoch === epoch) return refreshInFlight.promise;
  const persistence = getAuthPersistence();
  const currentIdentity = tokenIdentity(getStoredToken());
  const expectedEmployeeId = currentIdentity?.emp_id || cachedEmployeeId();
  temporarilyUnavailableRefreshEpoch = '';
  const pending = {
    epoch,
    promise: Promise.resolve(null) as Promise<string | null>,
  };
  pending.promise = (async () => {
    try {
      const response = await runCookieControl(epoch, () => activeClient.apiCall.invoke({
        url: '/api/v1/emp-auth/refresh', method: 'POST',
        options: { withCredentials: true },
      }));
      if (!isAuthSessionCurrent(epoch)) return null;
      const token = response?.data?.access_token;
      if (typeof token !== 'string' || !token) {
        temporarilyUnavailableRefreshEpoch = epoch;
        return null;
      }
      const refreshedIdentity = tokenIdentity(token);
      // Parsed/cached identity is used only to reject a mixed session, never as
      // authority. The server verifies signatures and /me verifies the employee.
      if (refreshedIdentity && (
        expectedEmployeeId && refreshedIdentity.emp_id !== expectedEmployeeId
        || currentIdentity?.sid && refreshedIdentity.sid !== currentIdentity.sid
      )) {
        invalidateConfirmedSession(epoch);
        return null;
      }
      // Token rotation is not an account change. Do not advance the epoch.
      storeToken(token, persistence);
      refreshClientAuth();
      return token;
    } catch (error) {
      if (httpStatus(error) === 401) invalidateConfirmedSession(epoch);
      else if (isAuthSessionCurrent(epoch)) temporarilyUnavailableRefreshEpoch = epoch;
      return null;
    } finally {
      if (refreshInFlight === pending) refreshInFlight = null;
    }
  })();
  refreshInFlight = pending;
  return pending.promise;
}

async function withAuthRetry<T>(execute: () => Promise<T>): Promise<T> {
  const epoch = getAuthSessionEpoch();
  const initialToken = getStoredToken();
  // A foreign tab may have cleared this tab's token while the SDK still holds
  // its old default header. Do not let that SDK credential start a new request.
  if (!initialToken || !isAuthSessionCurrent(epoch)) throw authSessionChangedError();
  try {
    const response = await execute();
    if (!isAuthSessionCurrent(epoch)) throw authSessionChangedError();
    return response;
  } catch (error) {
    if (!isAuthSessionCurrent(epoch)) throw authSessionChangedError();
    if (httpStatus(error) !== 401) throw error;
    // Concurrent requests may have already completed the shared refresh.
    const currentToken = getStoredToken();
    const refreshed = currentToken && currentToken !== initialToken
      ? currentToken : await refreshAccessToken();
    if (!isAuthSessionCurrent(epoch)) throw authSessionChangedError();
    if (!refreshed) throw error;
    // Only an explicit 401 is retried, once. Network failures and 403 responses
    // are never replayed, including for non-idempotent writes.
    try {
      const response = await execute();
      if (!isAuthSessionCurrent(epoch)) throw authSessionChangedError();
      return response;
    } catch (retryError) {
      if (!isAuthSessionCurrent(epoch)) throw authSessionChangedError();
      if (httpStatus(retryError) === 401) invalidateConfirmedSession(epoch);
      throw retryError;
    }
  }
}

const authenticatedApiCall = {
  invoke: (args: InvokeArgs) => {
    if (isAuthControlRequest(args.url)) {
      const epoch = getAuthSessionEpoch();
      const execute = () => activeClient.apiCall.invoke(args);
      const request = changesAuthCookie(args.url) ? runCookieControl(epoch, execute) : execute();
      return request.then(response => {
        if (!args.url.startsWith('/api/v1/emp-auth/logout') && epoch !== getAuthSessionEpoch()) throw authSessionChangedError();
        return response;
      });
    }
    return withAuthRetry(() => {
      const token = getStoredToken();
      return activeClient.apiCall.invoke({
        ...args,
        options: {
          ...args.options,
          headers: { ...args.options?.headers, ...(token ? { Authorization: `Bearer ${token}` } : {}) },
        },
      });
    });
  },
};

// Entity methods in the actual SDK close over an Axios instance. Resolve the
// current instance again on retry rather than calling the stale method twice.
const entityClients = new Map<string | symbol, any>();
const authenticatedEntities = new Proxy({} as SdkClient['entities'], {
  get(_target, entityName) {
    if (!entityClients.has(entityName)) {
      const methods = new Map<string | symbol, any>();
      entityClients.set(entityName, new Proxy({}, {
        get(_entity, method) {
          const value = Reflect.get(Reflect.get(activeClient.entities, entityName), method);
          if (typeof value !== 'function') return value;
          if (!methods.has(method)) methods.set(method, (...args: any[]) => withAuthRetry(() => {
            const entity = Reflect.get(activeClient.entities, entityName);
            return Reflect.get(entity, method).apply(entity, args);
          }));
          return methods.get(method);
        },
      }));
    }
    return entityClients.get(entityName);
  },
});

// Preserve the SDK response shape and stable public object, while all business
// apiCall and entity methods share the same auth/refresh lifecycle.
export const client = new Proxy({} as SdkClient, {
  get(_target, property) {
    if (property === 'apiCall') return authenticatedApiCall;
    if (property === 'entities') return authenticatedEntities;
    const value = Reflect.get(activeClient, property);
    return typeof value === 'function' ? value.bind(activeClient) : value;
  },
});

export function refreshClientAuth(): void {
  activeClient = createSdkClient();
}

export type DealFinalizeRequest = {
  ensure_subscription: boolean;
  auto_renew: boolean;
  create_service_board: boolean;
};

export type DealFinalizeStep = {
  status: 'completed' | 'skipped' | 'failed';
  message: string;
  resource_id?: number | null;
  created_count?: number;
  retryable?: boolean;
};

export type DealFinalizeResponse = {
  deal_id: number;
  complete: boolean;
  retryable: boolean;
  steps: Record<'subscription' | 'customer' | 'service_board', DealFinalizeStep>;
};

export async function finalizeDeal(dealId: number, data: DealFinalizeRequest) {
  return client.apiCall.invoke({
    url: `/api/v1/entities/deals/${dealId}/finalize`,
    method: 'POST',
    data,
  });
}

function getStoredAuthHeaders() {
  if (typeof window === 'undefined') return {};
  const token = getStoredToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

// Reports export helpers
export async function exportProfitMonthlyCsv(params: { start?: string; end?: string; currency?: 'USD'|'CNY'; base_currency?: string }) {
  const res = await client.apiCall.invoke({
    url: '/api/v1/reports/profit-monthly.csv',
    method: 'GET',
    data: params,
    options: { responseType: 'blob' as any, headers: getStoredAuthHeaders() },
  });
  return res;
}

export async function exportProfitMonthlyXlsx(params: { start?: string; end?: string; currency?: 'USD'|'CNY'; base_currency?: string }) {
  const res = await client.apiCall.invoke({
    url: '/api/v1/reports/profit-monthly.xlsx',
    method: 'GET',
    data: params,
    options: { responseType: 'blob' as any, headers: getStoredAuthHeaders() },
  });
  return res;
}

// Deduction default + import
export async function getDefaultDeduction() {
  return client.apiCall.invoke({ url: '/api/v1/deductions-monthly/default', method: 'GET' });
}

export async function updateDefaultDeduction(rate: number) {
  return client.apiCall.invoke({ url: '/api/v1/deductions-monthly/default', method: 'PUT', data: { rate } });
}

export async function importMonthlyDeductions(file: File, overwrite: boolean) {
  const form = new FormData();
  form.append('file', file);
  form.append('overwrite', String(overwrite));
  return client.apiCall.invoke({
    url: '/api/v1/deductions-monthly/import',
    method: 'POST',
    data: form,
    options: { headers: { 'Content-Type': 'multipart/form-data' } },
  });
}

export async function getProfitMonthly(params: { start: string; end: string; currency?: string; base_currency?: string }) {
  return client.apiCall.invoke({
    url: '/api/v1/reports/profit-monthly.json',
    method: 'GET',
    data: params,
    options: { headers: getStoredAuthHeaders() },
  });
}
