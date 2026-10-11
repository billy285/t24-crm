import { client } from './api';

export type FinanceEntryKind = 'expense' | 'income' | 'transfer' | 'borrow' | 'lend' | 'repay' | 'collect';
export type FinancePeriod = 'month' | 'quarter' | 'year' | 'custom';
export type FinanceAccountKind = 'cash' | 'bank' | 'wechat' | 'alipay';
export interface FinanceCategory { id: string; name: string; kind: 'expense' | 'income'; icon: string; active: boolean; sort_order: number; used?: boolean; entry_count?: number }
export interface FinanceAccount { id: string; name: string; kind: FinanceAccountKind; currency: 'CNY'; opening_balance_minor: number; balance_minor: number; active: boolean }
export interface FinanceDebt { id: string; name: string; direction: 'payable' | 'receivable'; principal_minor: number; remaining_minor: number; due_date: string | null; installment_minor: number | null; note: string | null }
export interface FinancePlan { id: string; name: string; category_id: string; amount_minor: number; due_date: string; status: 'pending' | 'paid' | 'cancelled'; paid_entry_id: string | null; actual_minor?: number; paid_date?: string }
export interface FinanceGoal { id: string; name: string; target_minor: number; prepared_minor: number; target_date: string | null; active: boolean }
export interface FinanceState { initialized: boolean; currency: 'CNY'; categories: FinanceCategory[]; accounts: FinanceAccount[]; debts: FinanceDebt[]; plans: FinancePlan[]; goals: FinanceGoal[]; budget_minor: number | null }
export interface FinanceEntry { id: string; kind: FinanceEntryKind; amount_minor: number; account_id: string; to_account_id?: string | null; category_id?: string | null; debt_id?: string | null; counterparty?: string | null; entry_date: string; note: string | null; status: 'active' | 'void'; category_name?: string; account_name?: string }
export interface FinanceEntryInput { kind: FinanceEntryKind; amount_minor: number; account_id: string; to_account_id?: string; category_id?: string; debt_id?: string; counterparty?: string; entry_date: string; note?: string; client_request_id: string }
export interface FinanceReport { currency: 'CNY'; start_date: string; end_date: string; income_minor: number; expense_minor: number; net_minor: number; movements: Record<'borrow_minor' | 'lend_minor' | 'repay_minor' | 'collect_minor' | 'transfer_minor', number>; category_totals: { category_id: string; name: string; kind: 'expense' | 'income'; total_minor: number; count: number }[]; trend: { date: string; income_minor: number; expense_minor: number }[] }
export interface FinanceEntries { items: FinanceEntry[]; total: number; page: number; page_size: number }
export interface FinanceDateRange { start_date: string; end_date: string }
export const FINANCE_MAX_MINOR = 9_000_000_000_000;

/** Decimal text enters the ledger as integer fen, never floating point yuan. */
export function parseFinanceAmount(value: string, allowZero = false): number | null {
  const text = value.trim();
  if (!/^(?:0|[1-9][0-9]{0,10})(?:\.[0-9]{1,2})?$/.test(text)) return null;
  const [whole, fraction = ''] = text.split('.');
  const minor = Number(whole) * 100 + Number(fraction.padEnd(2, '0'));
  return Number.isSafeInteger(minor) && minor <= FINANCE_MAX_MINOR && (allowZero ? minor >= 0 : minor > 0) ? minor : null;
}
export function financeAmountInput(minor: number): string {
  if (!Number.isSafeInteger(minor) || minor < 0) return '';
  return `${Math.floor(minor / 100)}.${String(minor % 100).padStart(2, '0')}`;
}
export function formatFinanceAmount(minor: number | null | undefined): string {
  if (!Number.isSafeInteger(minor)) return '—';
  const integer = minor as number;
  const absolute = Math.abs(integer);
  return `${integer < 0 ? '−' : ''}¥${Math.floor(absolute / 100).toLocaleString('zh-CN')}.${String(absolute % 100).padStart(2, '0')}`;
}
export function financeToday(now = new Date()): string {
  if (!Number.isFinite(now.getTime())) throw new Error('日期无效');
  const parts = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(now);
  return ['year', 'month', 'day'].map(type => parts.find(part => part.type === type)?.value).join('-');
}
export function validFinanceDate(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const [year, month, day] = value.split('-').map(Number);
  if (year < 2000 || year > 2100 || month < 1 || month > 12) return false;
  return day >= 1 && day <= new Date(Date.UTC(year, month, 0)).getUTCDate();
}
export function financePeriodRange(preset: FinancePeriod, anchor: string, custom?: FinanceDateRange): FinanceDateRange {
  if (preset === 'custom') {
    if (!custom || !validFinanceDate(custom.start_date) || !validFinanceDate(custom.end_date) || custom.start_date > custom.end_date) throw new Error('请选择正确的起止日期');
    return { ...custom };
  }
  if (!validFinanceDate(anchor)) throw new Error('请选择正确的日期');
  const [year, month] = anchor.split('-').map(Number);
  const firstMonth = preset === 'month' ? month : preset === 'quarter' ? Math.floor((month - 1) / 3) * 3 + 1 : 1;
  const lastMonth = preset === 'month' ? month : preset === 'quarter' ? firstMonth + 2 : 12;
  const pad = (value: number) => String(value).padStart(2, '0');
  return { start_date: `${year}-${pad(firstMonth)}-01`, end_date: `${year}-${pad(lastMonth)}-${pad(new Date(Date.UTC(year, lastMonth, 0)).getUTCDate())}` };
}
export function shiftFinanceAnchor(anchor: string, preset: Exclude<FinancePeriod, 'custom'>, direction: -1 | 1): string {
  if (!validFinanceDate(anchor)) throw new Error('日期无效');
  const [year, month] = anchor.split('-').map(Number);
  const date = new Date(Date.UTC(year, month - 1 + direction * (preset === 'month' ? 1 : preset === 'quarter' ? 3 : 12), 1));
  const result = `${date.getUTCFullYear()}-${String(date.getUTCMonth() + 1).padStart(2, '0')}-01`;
  if (!validFinanceDate(result)) throw new Error('已到可选日期边界');
  return result;
}
export function financePeriodLabel(preset: FinancePeriod, range: FinanceDateRange): string {
  if (preset === 'custom') return `${range.start_date} 至 ${range.end_date}`;
  const [year, month] = range.start_date.split('-');
  return preset === 'month' ? `${year}年${Number(month)}月` : preset === 'quarter' ? `${year}年第${Math.floor((Number(month) - 1) / 3) + 1}季度` : `${year}年`;
}
export function financeRequestId(): string { return crypto.randomUUID(); }

export class PersonalFinanceApiError extends Error {
  constructor(message: string, public status = 0) { super(message); this.name = 'PersonalFinanceApiError'; }
}
export function financeOutcomeUnknown(error: unknown): boolean {
  return error instanceof PersonalFinanceApiError && (error.status === 0 || error.status === 408 || error.status >= 500);
}
/** Keep the exact original operation for receipt replay after a lost response. */
export function createFinanceSubmissionGuard<T>() {
  let pending: T | null = null;
  let uncertain = false;
  return {
    begin(value: T) { if (pending !== null) throw new Error('请先核对上一笔操作'); pending = value; },
    unknown() { if (pending !== null) uncertain = true; },
    retry() { return uncertain ? pending : null; },
    locked() { return uncertain; },
    resolved() { pending = null; uncertain = false; },
  };
}
const PREFIX = '/api/v1/private-workspace/personal-finance';
async function request<T>(path: string, method: 'GET' | 'POST' | 'PATCH' | 'DELETE', data?: unknown): Promise<T> {
  try {
    const response = await client.apiCall.invoke({ url: `${PREFIX}${path}`, method, ...(data === undefined ? {} : { data }) });
    return response.data as T;
  } catch (error) {
    const value = error as { name?: string; response?: { status?: number; data?: { detail?: unknown } }; status?: number };
    const status = value?.response?.status || value?.status || 0;
    const message = status === 401 || value?.name === 'AuthSessionChangedError' ? '登录状态已改变，请重新进入私人空间。'
      : status === 403 ? '个人财务仅对本人开放。'
      : status === 409 ? typeof value?.response?.data?.detail === 'string' ? value.response.data.detail.slice(0, 180) : '记录状态已改变，请刷新后再操作。'
      : status === 422 || status === 400 ? typeof value?.response?.data?.detail === 'string' ? value.response.data.detail.slice(0, 180) : '请检查金额、日期及必填内容。'
      : status === 404 ? '这条记录已不存在，请刷新。'
      : method === 'GET' ? '暂时无法读取账本，请重新读取。'
      : '暂时未收到操作结果，请使用“原样重试并核对”。原表单已保留。';
    throw new PersonalFinanceApiError(message, status);
  }
}
const encoded = (id: string) => encodeURIComponent(id);
function query(values: Record<string, string | number | undefined>): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) if (value !== undefined && value !== '') params.set(key, String(value));
  return params.toString();
}
export const personalFinanceApi = {
  state: () => request<FinanceState>('/state', 'GET'),
  bootstrap: (client_request_id: string) => request<FinanceState>('/bootstrap', 'POST', { client_request_id }),
  entries: (filter: FinanceDateRange & { category_id?: string; kind?: FinanceEntryKind; status?: 'all' | 'active' | 'void'; page?: number; page_size?: number }) => request<FinanceEntries>(`/entries?${query({ ...filter })}`, 'GET'),
  report: (range: FinanceDateRange) => request<FinanceReport>(`/report?${query({ ...range })}`, 'GET'),
  createEntry: (data: FinanceEntryInput) => request<{ entry: FinanceEntry }>('/entries', 'POST', data),
  updateEntry: (id: string, data: { category_id?: string; entry_date?: string; note?: string }) => request<{ entry: FinanceEntry }>(`/entries/${encoded(id)}`, 'PATCH', data),
  voidEntry: (id: string) => request<{ entry: FinanceEntry }>(`/entries/${encoded(id)}/void`, 'POST'),
  restoreEntry: (id: string) => request<{ entry: FinanceEntry }>(`/entries/${encoded(id)}/restore`, 'POST'),
  createCategory: (data: Pick<FinanceCategory, 'name' | 'kind' | 'icon'> & { client_request_id: string }) => request<FinanceCategory>('/categories', 'POST', data),
  updateCategory: (id: string, data: Partial<Pick<FinanceCategory, 'name' | 'icon' | 'active' | 'sort_order'>>) => request<FinanceCategory>(`/categories/${encoded(id)}`, 'PATCH', data),
  reorderCategories: (kind: 'expense' | 'income', category_ids: string[]) => request<{ categories: FinanceCategory[] }>('/categories/reorder', 'POST', { kind, category_ids }),
  deleteCategory: (id: string) => request<void>(`/categories/${encoded(id)}`, 'DELETE'),
  createAccount: (data: Pick<FinanceAccount, 'name' | 'kind' | 'opening_balance_minor'> & { currency: 'CNY'; client_request_id: string }) => request<FinanceAccount>('/accounts', 'POST', data),
  updateAccount: (id: string, data: Partial<Pick<FinanceAccount, 'name' | 'active' | 'kind'>>) => request<FinanceAccount>(`/accounts/${encoded(id)}`, 'PATCH', data),
  createDebt: (data: Pick<FinanceDebt, 'name' | 'direction' | 'principal_minor' | 'due_date' | 'installment_minor' | 'note'> & { client_request_id: string }) => request<FinanceDebt>('/debts', 'POST', data),
  updateDebt: (id: string, data: Partial<Pick<FinanceDebt, 'name' | 'due_date' | 'installment_minor' | 'note'>>) => request<FinanceDebt>(`/debts/${encoded(id)}`, 'PATCH', data),
  createPlan: (data: Pick<FinancePlan, 'name' | 'category_id' | 'amount_minor' | 'due_date'> & { client_request_id: string }) => request<FinancePlan>('/plans', 'POST', data),
  updatePlan: (id: string, data: Partial<Pick<FinancePlan, 'name' | 'category_id' | 'amount_minor' | 'due_date' | 'status'>>) => request<FinancePlan>(`/plans/${encoded(id)}`, 'PATCH', data),
  payPlan: (id: string, data: { account_id: string; amount_minor: number; entry_date: string; client_request_id: string; note?: string }) => request<{ entry: FinanceEntry }>(`/plans/${encoded(id)}/pay`, 'POST', data),
  createGoal: (data: Pick<FinanceGoal, 'name' | 'target_minor' | 'prepared_minor' | 'target_date'> & { client_request_id: string }) => request<FinanceGoal>('/goals', 'POST', data),
  updateGoal: (id: string, data: Partial<Pick<FinanceGoal, 'name' | 'target_minor' | 'prepared_minor' | 'target_date' | 'active'>>) => request<FinanceGoal>(`/goals/${encoded(id)}`, 'PATCH', data),
  budget: (budget_minor: number | null) => request<{ budget_minor: number | null }>('/budget', 'PATCH', { budget_minor }),
};
