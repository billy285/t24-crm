import { invokeWithAuth } from './tokenStore';

export type FinanceEntryKind = 'manual_receipt' | 'customer_expense' | 'company_expense';
export type FinanceEntryStatus = 'draft' | 'submitted' | 'returned' | 'posted' | 'voided';
export type FinanceEntryCustomer = { id: number; business_name: string; customer_code?: string | null };
export type FinanceEntryDraft = {
  id: number; kind: FinanceEntryKind; customer_id: number | null; customer_name: string | null;
  payload: Record<string, unknown>; status: FinanceEntryStatus; revision: number;
  created_by_id: number; created_by_name: string; created_at: string; updated_at: string;
  return_reason?: string | null; posted_entity?: string | null; posted_id?: number | null;
};
export type FinanceEntryList = { items: FinanceEntryDraft[]; total: number; skip: number; limit: number };
export type FinanceEntryAttachment = { id: number; filename: string; media_type: string; byte_size: number; sha256: string; created_at: string };
export type FinanceEntryAttachments = { items: FinanceEntryAttachment[]; draft_revision: number };

export async function financeEntryApi<T>(path = '', method: 'GET' | 'POST' | 'PUT' | 'DELETE' = 'GET', data?: unknown): Promise<T> {
  const response = await invokeWithAuth({ url: `/api/v1/finance-entry-drafts${path}`, method, ...(data === undefined ? {} : { data }) });
  return response.data as T;
}

export async function uploadFinanceEntryAttachment(id: number, revision: number, file: File): Promise<{ item: FinanceEntryAttachment; draft_revision: number }> {
  const body = new FormData(); body.append('file', file); body.append('expected_revision', String(revision));
  const response = await invokeWithAuth({ url: `/api/v1/finance-entry-drafts/${id}/attachments`, method: 'POST', data: body, options: { headers: { 'Content-Type': 'multipart/form-data' } } });
  return response.data;
}

export async function downloadFinanceEntryAttachment(id: number, attachment: FinanceEntryAttachment): Promise<Blob> {
  const response = await invokeWithAuth({ url: `/api/v1/finance-entry-drafts/${id}/attachments/${attachment.id}`, method: 'GET', options: { responseType: 'blob' } });
  if (!(response.data instanceof Blob) || !['application/pdf', 'image/jpeg', 'image/png', 'image/webp'].includes(response.data.type.split(';')[0])) throw new Error('凭据文件返回不完整，请重新下载。');
  return response.data;
}

export function financeEntryErrorStatus(error: unknown): number | undefined {
  const value = error as {response?: {status?: number}; status?: number; data?: {status?: number}};
  return value?.response?.status || value?.status || value?.data?.status;
}

export function financeEntryError(error: unknown, fallback = '资料暂时无法读取，请重试。') {
  const value = error as { response?: { status?: number; data?: { detail?: unknown } }; data?: { detail?: unknown }; status?: number };
  const detail = value?.response?.data?.detail || value?.data?.detail;
  if (typeof detail === 'string' && detail.trim()) return detail;
  const status = financeEntryErrorStatus(error);
  if (status === 401 || status === 403 || status === 404) return '当前登记或客户授权已不可用，请重新读取。';
  if (status === 409) return '登记内容或状态已变化，请重新读取后核对，当前输入会保留。';
  if (status === 422) return '填写内容尚不符合要求，请核对金额、日期与必要资料。';
  return fallback;
}

export function financeEntryRequestId() {
  return globalThis.crypto?.randomUUID?.() || `entry-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 14)}`;
}

export const financeEntryStatusLabels: Record<FinanceEntryStatus, string> = {
  draft: '草稿', submitted: '待老板核对', returned: '已退回', posted: '已入账', voided: '已作废',
};

export function editableFinanceEntry(item: FinanceEntryDraft | null | undefined) {
  return Boolean(item && (item.status === 'draft' || item.status === 'returned'));
}
