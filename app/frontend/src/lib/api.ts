import { createClient } from '@metagptx/web-sdk';
import { getAPIBaseURL } from './config';

type SdkClient = ReturnType<typeof createClient>;

const createSdkClient = (): SdkClient => createClient({ baseURL: getAPIBaseURL() } as any);

// The SDK reads localStorage.token only when createClient() runs. Keep a stable
// exported proxy while allowing authentication changes to replace its backing client.
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

function getStoredAuthHeaders() {
  if (typeof window === 'undefined') return {};
  const token = window.localStorage.getItem('emp_auth_token') || window.localStorage.getItem('token');
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
