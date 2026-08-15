import { createClient } from '@metagptx/web-sdk';
import { getAPIBaseURL } from './config';
import { getStoredToken } from './auth-storage';

type SdkClient = ReturnType<typeof createClient>;

const createSdkClient = (): SdkClient => {
  const token = getStoredToken();
  return createClient({
    baseURL: getAPIBaseURL(),
    timeout: 15000,
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
  } as any);
};

// Keep a stable exported proxy while allowing authentication changes to replace
// the SDK client. The explicit header also supports session-only logins without
// copying their access token into localStorage.
let activeClient = createSdkClient();

export const client = new Proxy({} as SdkClient, {
  get(_target, property) {
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
