import type { StripeAutoPostingEvidence } from '@/lib/stripe-auto-posting';
import { invokeWithAuth } from '@/lib/tokenStore';

export type ReconciliationIssue = { code: string; message: string };
export type CrmStripeService = { customer_id: number; customer_name: string; crm_subscription_id: number; package_name: string; amount: number; currency: string; billing_cycle: string; engagement_id?: number; business_line_id?: number; product_id?: number; status?: string };
export type StripeSubscriptionCandidate = { subscription_id: string; customer_id: string; customer_name?: string; email?: string; status: string; currency: string; amount?: number | null; billing_cycle?: string; price_id?: string; period_start?: string; period_end?: string; items_count?: number };
export type HistoricalStripeBinding = { id: number; customer_id: number; customer_name: string; crm_subscription_id: number; package_name: string; stripe_subscription_id: string; stripe_customer_id: string; currency: string; amount: number; billing_cycle: string; price_id?: string; sync_from: string; status: 'active' | 'paused'; revision: number; needs_refresh: boolean; last_synced_at?: string; verified_at?: string; pilot_validated?: boolean; can_validate_pilot?: boolean; validation_reason?: string; pilot_evidence?: { successful_sync_count: number; repeat_dedupe_verified: boolean; cash_evidence_verified: boolean; invoice_count: number; last_date_start?: string; last_date_end?: string } };
export type ReconciliationPilot = { limit: number; enabled_bindings: number; validated_bindings: number; bulk_enabled: boolean; can_activate_bulk: boolean };
export type HistoricalInvoiceSummary = { id: number; binding_id: number; customer_id: number; customer_name: string; package_name: string; stripe_invoice_id: string; status: 'pending_review' | 'needs_refresh' | 'exception' | 'confirmed' | 'linked_existing'; currency?: string; gross_amount?: number | null; payment_date?: string; issues?: ReconciliationIssue[]; payment_id?: number | null; updated_at?: string; auto_posting?: StripeAutoPostingEvidence | null };
export type HistoricalLedgerCandidate = { id: number; customer_name?: string; product_name?: string; amount_paid?: number; payment_date?: string; currency?: string; transaction_reference?: string; coverage_start?: string; coverage_end?: string };
export type HistoricalInvoiceReview = HistoricalInvoiceSummary & { service_amount: number | null; tax_amount: number | null; fee_amount: number | null; net_amount: number | null; coverage_start?: string; coverage_end?: string; revision: number; lines: { description?: string; amount?: number | null; currency?: string; period_start?: string; period_end?: string }[]; existing_payment_candidates: HistoricalLedgerCandidate[]; accounting_preview: { amount_due?: number; amount_paid?: number; management_amount?: number; ads_recharge_amount?: number; stripe_fee_amount?: number; net_amount?: number; income_type?: string } | null; can_confirm: boolean; can_create_payment: boolean; can_link_existing: boolean; read_only_reason?: string; note?: string };
export type HistoricalReconciliationOverview = { configured: boolean; provider_status: string; pilot: ReconciliationPilot; counts: Record<string, number>; bindings: HistoricalStripeBinding[]; invoice_reviews: HistoricalInvoiceSummary[]; scope_note?: string };
export type HistoricalBindingDraft = { crm_subscription_id: number; stripe_subscription_id: string; sync_from: string; income_type: string };
export type HistoricalBindingPreview = { token: string; expires_at?: string; crm_service: CrmStripeService; stripe_subscription: StripeSubscriptionCandidate; warnings: ReconciliationIssue[]; can_confirm: boolean; pilot: ReconciliationPilot };
export type HistoricalSyncResult = { items: HistoricalInvoiceSummary[]; has_more: boolean; next_cursor?: string | null; scope: { date_start: string; date_end: string }; binding?: HistoricalStripeBinding };

export async function stripeReconciliationApi<T>(path: string, method: 'GET' | 'POST' | 'PATCH' = 'GET', data?: unknown): Promise<T> {
  return (await invokeWithAuth({ url: `/api/v1/stripe-history-reconciliation${path}`, method, data })).data as T;
}
export function stripeReconciliationError(error: any, fallback: string) {
  const detail = error?.response?.data?.detail ?? error?.data?.detail;
  return typeof detail === 'string' ? detail : typeof detail?.message === 'string' ? detail.message : fallback;
}
export function stripeReconciliationDenied(error: any) { return [401, 403].includes(Number(error?.response?.status || error?.data?.status || error?.status)); }
export function reconciliationMoney(amount?: number | null, currency?: string) { return typeof amount === 'number' && Number.isFinite(amount) ? `${(currency || 'USD').toUpperCase()} ${amount.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : '待确认'; }
export function reconciliationToday() { return new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date()); }
export function reconciliationDateOffset(date: string, offset: number) { const parsed = new Date(`${date}T00:00:00Z`); if (Number.isNaN(parsed.getTime())) return ''; parsed.setUTCDate(parsed.getUTCDate() + offset); return parsed.toISOString().slice(0, 10); }
export function reconciliationTime(value?: string | null) { if (!value) return '尚无记录'; const parsed = new Date(value); return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }); }
export const reconciliationCycles: Record<string, string> = { monthly: '月付', quarterly: '季付', annual: '年付', semi_annual: '半年付', one_time: '一次性' };
export const reconciliationStates: Record<string, string> = { pending_review: '待老板核对', needs_refresh: '需刷新证据', exception: '存在异常', confirmed: '已确认记账', linked_existing: '已关联原账' };
