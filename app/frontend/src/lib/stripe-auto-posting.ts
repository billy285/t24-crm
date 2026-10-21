export type StripeAutoPostingStatus = 'queued' | 'retry' | 'manual_required' | 'auto_posted' | 'manual_completed';
export type StripeAutoPostingEvidence = {
  status: StripeAutoPostingStatus; reason?: string | null; payment_id?: number | null;
  authorized_by_name?: string | null; effective_from?: string | null; processed_at?: string | null;
};
export type StripeAutoPostingTrial = { passed: boolean; checked_at: string; invoice_count: number; reasons: string[] };
export type StripeAutoPostingPolicy = {
  binding_id: number; customer_name: string; package_name: string; stripe_subscription_id: string;
  amount: number; currency: string; billing_cycle: string; enabled: boolean; effective_from: string | null;
  revision: number; eligible: boolean; eligibility_reasons: string[]; trial: StripeAutoPostingTrial | null;
  latest_job: { status: StripeAutoPostingStatus; reason?: string | null; payment_id?: number | null; review_id?: number | null; last_attempt_at?: string | null } | null;
};
export type StripeAutoPostingTotal = { currency: string; amount: number; count: number };
export type StripeAutoPostingSummary = {
  enabled_count: number; counts: Record<StripeAutoPostingStatus, number>; totals: StripeAutoPostingTotal[];
  today_totals?: StripeAutoPostingTotal[];
};
export type StripeAutoPostingOverview = StripeAutoPostingSummary & { limit: number; items: StripeAutoPostingPolicy[] };
export type StripeAutoPostingJob = {
  id: number; review_id: number; binding_id: number; customer_name: string; package_name: string;
  currency: string; amount: number | null; status: StripeAutoPostingStatus; reason?: string | null;
  payment_id?: number | null; last_attempt_at?: string | null; created_at: string;
};
export const stripeAutoPostingLabels: Record<StripeAutoPostingStatus, string> = {
  queued: '等待系统核验', retry: '凭据待重试', manual_required: '待你处理', auto_posted: '已自动入账', manual_completed: '已人工处理',
};
export function validAutoPostingSelection(ids: number[], policies: StripeAutoPostingPolicy[], limit = 5): boolean {
  if (!Number.isSafeInteger(limit) || limit < 3) return false;
  if (ids.length < 3 || ids.length > Math.min(limit, 5) || new Set(ids).size !== ids.length) return false;
  return ids.every(id => Number.isSafeInteger(id) && id > 0 && policies.some(item => item.binding_id === id && item.eligible === true && item.enabled === false));
}
export function canEnableAutoPosting(policy: StripeAutoPostingPolicy, enabledCount: number, limit = 5): boolean {
  return Number.isSafeInteger(limit) && limit >= 3 && policy.eligible === true && policy.trial?.passed === true && policy.enabled === false
    && Number.isSafeInteger(enabledCount) && enabledCount >= 0 && enabledCount < Math.min(limit, 5);
}
export function safeAutoPostingTotals(totals: unknown): StripeAutoPostingTotal[] | null {
  if (!Array.isArray(totals)) return null;
  if (!totals.every(item => item && typeof item.currency === 'string' && /^[A-Za-z]{3}$/.test(item.currency) && typeof item.amount === 'number' && Number.isFinite(item.amount) && item.amount >= 0 && Number.isSafeInteger(item.count) && item.count >= 0)) return null;
  const currencies = totals.map(item => item.currency.toUpperCase());
  if (new Set(currencies).size !== currencies.length) return null;
  return totals.map(item => ({ currency: item.currency.toUpperCase(), amount: item.amount, count: item.count }));
}
export function isAutoPostedReview(review: { auto_posting?: StripeAutoPostingEvidence | null }): boolean {
  return review.auto_posting?.status === 'auto_posted';
}
export function autoPostingCount(value: unknown): number | null {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0 ? value : null;
}
export function autoPostingTotalsCount(totals: unknown): number | null {
  const safe = safeAutoPostingTotals(totals);
  if (safe === null) return null;
  const count = safe.reduce((sum, item) => sum + item.count, 0);
  return Number.isSafeInteger(count) ? count : null;
}
export function isAwaitingAutoPosting(review: { auto_posting?: StripeAutoPostingEvidence | null }): boolean {
  return review.auto_posting?.status === 'queued' || review.auto_posting?.status === 'retry';
}
