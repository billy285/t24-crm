import { invokeWithAuth } from '@/lib/tokenStore';

export const salesDealPlatforms = ['Google Business Profile', 'Google Ads', 'Meta Ads', 'Facebook', 'Instagram', 'TikTok', 'Yelp', '小红书', '官网'];
export const salesDealCycles: Record<string, string> = { monthly: '月付', quarterly: '季付', semi_annual: '半年付', annual: '年付', one_time: '一次性' };
export const salesCollectionMethods = [
  { value: 'stripe_auto', label: 'Stripe 自动扣款' }, { value: 'bank_transfer', label: '银行转账' },
  { value: 'check', label: '支票' }, { value: 'zelle', label: 'Zelle' }, { value: 'other', label: '其他方式' },
];
export type HandoffContact = { id?: string; name?: string; role?: string; phone?: string; email?: string; wechat?: string };
export type SalesPaymentLink = { url: string; amount: number; currency: string; billing_cycle: string; cadence_label: string; tax_mode: 'exclusive'; automatic_renewal: boolean };
export type SalesPaymentRequest = SalesPaymentLink & { id: number; reference: string; status: string; duplicate_warnings?: string[]; duplicate_scope?: string };
export type SalesPaymentRequestState = { can_create: boolean; read_only_reason?: string; payment_request: SalesPaymentRequest | null };
export type SalesPaymentObservation = { id: number; status: string; match_issues: string[]; session_id?: string; subscription_id?: string; invoice_id?: string; payment_intent_id?: string; service_amount?: number; tax_amount?: number; gross_amount?: number; currency?: string; checkout_completed_at?: string; paid_at?: string; payer_business_name?: string; payer_name?: string; payer_email?: string };
export type SalesReceiptEvidence = { service_amount: number; tax_amount: number; fee_amount: number; gross_amount: number; net_amount: number; currency?: string; transaction_reference?: string; payment_date?: string };
export type SalesPaymentObservations = { items: SalesPaymentObservation[]; receipt_evidence: SalesReceiptEvidence | null; duplicate_warnings?: string[]; duplicate_scope?: string };
export type SalesDealPlan = { id: number; product_id: number; name: string; standard_price: number; default_currency: string; default_billing_cycle: string; platform_limit?: number | null; scope_type: string; catalog_token: string; required_collection_method?: 'manual' | 'stripe_auto'; service_period_months?: number | null; plan_code?: string; payment_link?: SalesPaymentLink | null };
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
  can_request_payment?: boolean; can_view_payment_observations?: boolean; waiting_days?: number; receipt_review_status?: 'pending_owner_review' | 'owner_verified';
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
export async function salesDealPaymentApi<T>(path: string, method: 'GET' | 'POST' = 'GET', data?: unknown): Promise<T> {
  const response = await invokeWithAuth({ url: `/api/v1/sales-deal-payments${path}`, method, data });
  return response.data as T;
}
/** Only the server-associated Stripe URL may be shared from a deal. */
export function salesPaymentRequestUrl(request: SalesPaymentRequest | null) {
  if (!request?.url || !request.reference) return null;
  try {
    const url = new URL(request.url);
    return url.protocol === 'https:' && url.hostname === 'buy.stripe.com' && !url.username && !url.password
      && url.searchParams.get('client_reference_id') === request.reference ? url.toString() : null;
  } catch { return null; }
}
export function salesPaymentCadence(cycle?: string) {
  return ({ monthly: '每月自动续费', quarterly: '每 3 个月自动续费', annual: '每年自动续费' } as Record<string, string>)[cycle || ''] || '按套餐约定周期续费';
}
/** Reject fractional cents and compare as integers instead of floating point. */
export function salesPaymentCents(value: string | number | undefined): number | null {
  const text = String(value ?? '').trim();
  if (!/^\d+(?:\.\d{1,2})?$/.test(text)) return null;
  const [whole, fraction = ''] = text.split('.');
  const cents = Number(whole) * 100 + Number(fraction.padEnd(2, '0'));
  return Number.isSafeInteger(cents) && cents <= 100000000 ? cents : null;
}
export function salesPaymentReconciliation(values: { service_amount: string | number; tax_amount: string | number; fee_amount: string | number; gross_amount: string | number; net_amount: string | number }, expected?: number) {
  const cents = Object.fromEntries(Object.entries(values).map(([key, value]) => [key, salesPaymentCents(value)]));
  if (Object.values(cents).some(value => value === null)) return { complete: false, valid: false, message: '请按真实凭据填写税、手续费、客户支付总额和净到账，金额最多两位小数。' };
  if (cents.service_amount !== salesPaymentCents(expected)) return { complete: true, valid: false, message: '服务费与统一成交价不一致，不能确认收款。' };
  if (cents.service_amount! + cents.tax_amount! !== cents.gross_amount) return { complete: true, valid: false, message: '金额不一致：客户支付总额应等于服务费加税。请核对凭据。' };
  if (cents.gross_amount! - cents.fee_amount! !== cents.net_amount) return { complete: true, valid: false, message: '金额不一致：净到账应等于客户支付总额减手续费。请核对凭据。' };
  return { complete: true, valid: true, message: '金额核对一致；仍需老板核实真实到账日期和凭据后确认。' };
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
