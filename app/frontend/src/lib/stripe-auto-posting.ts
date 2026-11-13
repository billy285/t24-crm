export type StripeAutoPostingStatus = 'queued' | 'retry' | 'manual_required' | 'auto_posted' | 'manual_completed';
export type StripeAutoPostingEvidence = {
  status: StripeAutoPostingStatus; reason?: string | null; payment_id?: number | null;
  authorized_by_name?: string | null; effective_from?: string | null; processed_at?: string | null;
};
export type StripeAutoPostingTrial = { passed: boolean; checked_at: string; invoice_count: number; reasons: string[]; validation_state?: 'passed' | 'expired' | 'scope_changed' | 'not_passed'; reenable_required?: boolean };
export type StripeAutoPostingHealth = {
  global_enabled: boolean; worker_supported: boolean; current_process_only: true;
  worker_state: 'disabled' | 'unsupported' | 'not_started' | 'starting' | 'running' | 'stopped' | 'failed';
  heartbeat_state?: 'awaiting_start' | 'current' | 'stale' | 'unavailable'; heartbeat_stale_after_seconds?: number;
  started_at?: string | null; last_heartbeat_at?: string | null; last_batch_completed_at?: string | null;
  last_batch_error?: string | null; last_attempt_at?: string | null; last_auto_posted_at?: string | null; checked_at: string;
};
export type StripeAutoPostingPolicy = {
  binding_id: number; customer_name: string; package_name: string; stripe_subscription_id: string;
  amount: number; currency: string; billing_cycle: string; enabled: boolean; effective_from: string | null;
  revision: number; eligible: boolean; eligibility_reasons: string[]; trial: StripeAutoPostingTrial | null;
  latest_job: { status: StripeAutoPostingStatus; reason?: string | null; payment_id?: number | null; review_id?: number | null; last_attempt_at?: string | null } | null;
};
export type StripeAutoPostingTotal = { currency: string; amount: number; count: number };
export type StripeAutoPostingSummary = {
  enabled_count: number; counts: Record<StripeAutoPostingStatus, number>; totals: StripeAutoPostingTotal[];
  today_totals?: StripeAutoPostingTotal[]; health?: StripeAutoPostingHealth;
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
export function autoPostingTime(value?: string | null): string {
  if (!value) return '尚无记录';
  const timestamp = /^(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?)(Z|[+-]\d{2}:\d{2})?$/.exec(value.trim());
  if (!timestamp) return value;
  // Auto-posting DB timestamps are UTC, including SQLite's timezone-less ISO values.
  const datetime = timestamp[1].replace(' ', 'T').replace(/(\.\d{3})\d+$/, '$1');
  const parsed = new Date(`${datetime}${timestamp[2] || 'Z'}`);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString('zh-CN', {
    timeZone: 'Asia/Shanghai', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false,
  });
}
export function validAutoPostingSelection(ids: number[], policies: StripeAutoPostingPolicy[], limit = 5): boolean {
  if (!Number.isSafeInteger(limit) || limit < 3) return false;
  if (ids.length < 3 || ids.length > Math.min(limit, 5) || new Set(ids).size !== ids.length) return false;
  return ids.every(id => Number.isSafeInteger(id) && id > 0 && policies.some(item => item.binding_id === id && item.eligible === true && item.enabled === false));
}
export function canEnableAutoPosting(policy: StripeAutoPostingPolicy, enabledCount: number, limit = 5): boolean {
  return Number.isSafeInteger(limit) && limit >= 3 && policy.eligible === true && policy.trial?.passed === true && policy.trial.reenable_required !== true
    && (!policy.trial.validation_state || policy.trial.validation_state === 'passed') && policy.enabled === false
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

export function autoPostingHealthState(health?: StripeAutoPostingHealth): { label: string; tone: 'neutral' | 'warning' | 'complete'; note: string } {
  const scope = '调度状态仅反映当前 API 进程；其他进程与整站持续运行情况需结合运行记录核对。';
  if (!health || typeof health.global_enabled !== 'boolean') return { label: '自动调度状态待确认', tone: 'neutral', note: '尚未取得运行状态，请重新读取。' };
  if (health.global_enabled === false) return { label: '全局自动记账未启用', tone: 'warning', note: '服务授权单独保留；总开关关闭期间不会自动处理新账单。' };
  if (health.worker_supported === false || health.worker_state === 'unsupported') return { label: '当前进程不支持后台调度', tone: 'warning', note: scope };
  if (health.worker_supported !== true || health.current_process_only !== true) return { label: '自动调度观察范围待确认', tone: 'neutral', note: scope };
  if (health.worker_state === 'failed' || health.worker_state === 'stopped') return { label: '当前进程调度待检查', tone: 'warning', note: scope };
  if (health.last_batch_error) return { label: '最近一次调度需检查', tone: 'warning', note: `最近批次未成功完成，请核对异常与后续重试结果。${scope}` };
  if (health.worker_state === 'running' && health.heartbeat_state === 'current' && health.last_heartbeat_at) return { label: '当前进程调度运行中', tone: 'complete', note: scope };
  if (health.heartbeat_state === 'stale') return { label: '当前进程心跳待确认', tone: 'neutral', note: `最近心跳已超出服务端观察窗口，请重新读取并核对最近批次。${scope}` };
  return { label: health.worker_state === 'starting' ? '当前进程调度启动中' : '当前进程尚无运行确认', tone: 'neutral', note: scope };
}

export function autoPostingTrialState(policy: StripeAutoPostingPolicy): { label: string; note: string; showReasons: boolean } {
  if (!policy.trial) return { label: '尚未模拟核验', note: '', showReasons: true };
  const state = policy.trial.validation_state;
  if (policy.enabled && state === 'expired') return { label: '已授权 · 重新开启前需复验', note: '模拟有效期用于再次启用校验，不代表已授权服务停止自动记账。', showReasons: false };
  if (state === 'expired') return { label: '模拟已过期 · 启用前需复验', note: '请重新选择 3–5 项服务模拟，再逐项确认开启。', showReasons: true };
  if (state === 'scope_changed') return { label: '服务范围变化 · 需重新核验', note: '请核对当前服务与订阅，再查看最近处理记录。', showReasons: true };
  return { label: policy.trial.passed ? '模拟已通过' : '模拟待处理', note: '', showReasons: true };
}
