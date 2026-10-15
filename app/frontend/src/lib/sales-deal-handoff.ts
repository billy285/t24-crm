import { invokeWithAuth } from '@/lib/tokenStore';

export const salesDealPlatforms = ['Google Business Profile', 'Google Ads', 'Meta Ads', 'Facebook', 'Instagram', 'TikTok', 'Yelp', '小红书', '官网'];
export const salesDealCycles: Record<string, string> = { monthly: '月付', quarterly: '季付', semi_annual: '半年付', annual: '年付', one_time: '一次性' };
export const salesCollectionMethods = [
  { value: 'stripe_auto', label: 'Stripe 自动扣款' }, { value: 'bank_transfer', label: '银行转账' },
  { value: 'check', label: '支票' }, { value: 'zelle', label: 'Zelle' }, { value: 'other', label: '其他方式' },
];
export type HandoffContact = { id?: string; name?: string; role?: string; phone?: string; email?: string; wechat?: string };
export type SalesDealPlan = { id: number; product_id: number; name: string; standard_price: number; default_currency: string; default_billing_cycle: string; platform_limit?: number | null; scope_type: string; catalog_token: string; required_collection_method?: 'manual' | 'stripe_auto'; service_period_months?: number | null };
export type SalesDealCatalog = { business_lines: { id: number; code: string; name: string }[]; products: { id: number; business_line_id: number; name: string }[]; plans: SalesDealPlan[]; can_manage_catalog?: boolean; platform_options?: string[]; status?: string; message?: string | null };
export type SalesDealHandoff = {
  id: number; lead_id: number; customer_id: number; engagement_id?: number; deal_id?: number; subscription_id?: number;
  package_name?: string; amount?: number; currency?: string; billing_cycle?: string; payment_status?: string; operations_status?: string;
  operations_owner_employee_id?: number; operations_owner_name?: string; operations_access_status?: string; customer_access_status?: string;
  customer_goal?: string; special_commitments?: string; handoff_notes?: string; contacts?: HandoffContact[]; preferred_contact_id?: string;
  source?: { service_start_date?: string; service_end_date?: string; selected_platforms?: string[]; contacts?: HandoffContact[]; customer_goal?: string; special_commitments?: string; handoff_notes?: string; lead_notes?: string; need_summary?: string; best_contact_time?: string; summary?: Record<string, unknown>; history?: { id: number; notes?: string; outcome?: string; called_at?: string; sales_employee_name?: string }[] }; business_name?: string; created_at?: string; sales_name?: string; service_start_date?: string; service_end_date?: string;
  collection_method?: string; selected_platforms?: string[]; summary?: Record<string, unknown>;
  can_view_customer?: boolean; can_view_history?: boolean; history_url?: string | null; can_finance_confirm?: boolean; can_operations_ack?: boolean;
  operations_acknowledged_at?: string; operations_ack_note?: string; acknowledged_at?: string; acknowledged_by_name?: string; payment_confirmed_by_name?: string; payment_date?: string;
};
export type SalesDealLeadState = {
  registered: boolean; lead: { id: number; business_name: string; contact_name?: string; phone?: string; converted_customer_id?: number };
  can_register: boolean; read_only_reason?: string; operations_candidates: { id: number; name: string }[];
  contacts?: HandoffContact[]; preferred_contact_id?: string; customer_goal?: string; summary?: Record<string, unknown>;
  handoff: SalesDealHandoff | null; legacy_quotes?: { id: number; package_name?: string; currency?: string; final_amount?: number; status?: string; selected_platforms?: string[]; review_notes?: string; reviewed_by_name?: string; submitted_by_name?: string }[];
  can_view_customer?: boolean; can_view_history?: boolean; history_url?: string | null; can_finance_confirm?: boolean; can_operations_ack?: boolean;
};
export async function dealHandoffApi<T>(path: string, method: 'GET' | 'POST' = 'GET', data?: unknown): Promise<T> {
  const response = await invokeWithAuth({ url: `/api/v1/sales-deal-handoffs${path}`, method, data });
  return response.data as T;
}
export function salesHandoffError(error: any, fallback: string) {
  const detail = error?.data?.detail ?? error?.response?.data?.detail;
  return typeof detail === 'string' ? detail : typeof detail?.message === 'string' ? detail.message : error?.message || fallback;
}
export function salesHandoffMoney(amount?: number, currency?: string) {
  if (typeof amount !== 'number' || !Number.isFinite(amount)) return '';
  return `${currency || 'USD'} ${amount.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}
/** Trust only explicit server permission and a local, expected sales route. */
export function salesHandoffHistoryUrl(item: { can_view_history?: boolean; history_url?: string | null }) {
  const url = item.history_url || '';
  return item.can_view_history === true && /^\/sales-leads\?dossier=[1-9]\d*$/.test(url) && !url.includes('\\') ? url : null;
}

/** Calendar periods end on the same day, clamped to the target month's last day. */
export function salesDealPeriodEnd(start: string, plan: Pick<SalesDealPlan, 'default_billing_cycle' | 'service_period_months'>) {
  if (plan.default_billing_cycle === 'one_time' || !/^\d{4}-\d{2}-\d{2}$/.test(start)) return '';
  const [year, month, day] = start.split('-').map(Number);
  if (year < 1900 || month < 1 || month > 12 || day < 1 || day > 31) return '';
  const parsed = new Date(Date.UTC(year, month - 1, day));
  if (parsed.toISOString().slice(0, 10) !== start) return '';
  const months = plan.service_period_months ?? ({ monthly: 1, quarterly: 3, semi_annual: 6, annual: 12 }[plan.default_billing_cycle]);
  if (![1, 3, 6, 12].includes(months)) return '';
  const targetYear = year + Math.floor((month - 1 + months) / 12);
  const targetMonth = (month - 1 + months) % 12;
  if (targetYear > 9999) return '';
  const lastDay = new Date(Date.UTC(targetYear, targetMonth + 1, 0)).getUTCDate();
  return `${targetYear}-${String(targetMonth + 1).padStart(2, '0')}-${String(Math.min(day, lastDay)).padStart(2, '0')}`;
}
