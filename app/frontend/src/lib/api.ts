import { createClient } from '@metagptx/web-sdk';
import { getAPIBaseURL } from './config';

// Create client instance
const baseURL =
  (import.meta.env && (import.meta.env as any).VITE_API_BASE_URL) ||
  (import.meta.env.DEV ? '' : getAPIBaseURL());

export const client = createClient({ baseURL } as any);

// Reports export helpers
export async function exportProfitMonthlyCsv(params: { start?: string; end?: string; currency?: 'USD'|'CNY'; base_currency?: string }) {
  const res = await client.apiCall.invoke({
    url: '/api/v1/reports/profit-monthly.csv',
    method: 'GET',
    data: params,
    options: { responseType: 'blob' as any },
  });
  return res;
}

export async function exportProfitMonthlyXlsx(params: { start?: string; end?: string; currency?: 'USD'|'CNY'; base_currency?: string }) {
  const res = await client.apiCall.invoke({
    url: '/api/v1/reports/profit-monthly.xlsx',
    method: 'GET',
    data: params,
    options: { responseType: 'blob' as any },
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
  });
}
