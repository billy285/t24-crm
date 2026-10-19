export type StripeReminderKind = 'pending_review' | 'needs_refresh' | 'exception';
export type StripeDailyScanStatus = 'disabled' | 'no_bindings' | 'never' | 'running' | 'completed' | 'partial' | 'retrying';

export type StripeHistoryReminder = { id: number; kind: StripeReminderKind; customer_name: string; package_name: string; title: string; href: string; observed_at: string | null };
export type StripeHistoryReminders = {
  counts: Record<StripeReminderKind | 'total', number>;
  items: StripeHistoryReminder[];
  exception_items: StripeHistoryReminder[];
  exception_has_more: boolean;
  daily_scan: {
    enabled: boolean;
    timezone: 'Asia/Shanghai';
    daily_time: '09:00';
    next_scheduled_at: string | null;
    last_completed_at: string | null;
    last_run_at: string | null;
    last_run_status: StripeDailyScanStatus;
    last_discovered_reviews: number | null;
    active_bindings: number;
    covered_bindings: number;
    catchup_bindings: number;
    retry_bindings: number;
    running_bindings: number;
    last_error_code: string | null;
    window_start: string | null;
    window_end: string | null;
    covered_through: string | null;
    note?: string;
  };
  auto_accounting: false;
};

export function reminderCount(value: unknown): number | null {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0 ? value : null;
}

export function pendingStripeReminders(counts: StripeHistoryReminders['counts'] | undefined): number | null {
  const pending = reminderCount(counts?.pending_review);
  const refresh = reminderCount(counts?.needs_refresh);
  return pending === null || refresh === null ? null : pending + refresh;
}

export function stripeDailyScanState(scan?: StripeHistoryReminders['daily_scan']): { label: string; tone: 'neutral' | 'warning' | 'complete' } {
  if (!scan) return { label: '补查结果待确认', tone: 'neutral' };
  if (scan.enabled === false || scan.last_run_status === 'disabled') return { label: '每日补查未启用', tone: 'warning' };
  if (scan.enabled !== true) return { label: '补查结果待确认', tone: 'neutral' };
  if (scan.last_run_status === 'no_bindings' || scan.active_bindings === 0) return { label: '暂无已关联服务可补查', tone: 'neutral' };
  if ((reminderCount(scan.retry_bindings) !== null && scan.retry_bindings > 0) || scan.last_run_status === 'retrying' || scan.last_error_code) return { label: '补查待重试', tone: 'warning' };
  if (scan.running_bindings > 0 || scan.last_run_status === 'running') return { label: '正在补查', tone: 'neutral' };
  if (scan.catchup_bindings > 0 || scan.last_run_status === 'partial') return { label: '补查尚未完成', tone: 'warning' };
  if (scan.last_run_status === 'never') return { label: '等待首次补查', tone: 'neutral' };
  if (scan.last_run_status === 'completed' && scan.last_completed_at && reminderCount(scan.covered_bindings) !== null && reminderCount(scan.active_bindings) !== null && scan.covered_bindings === scan.active_bindings) return { label: '最近补查已完成', tone: 'complete' };
  return { label: '补查结果待确认', tone: 'neutral' };
}

export function stripeReminderHref(href: unknown): string | null {
  if (typeof href !== 'string' || !href.startsWith('/finance?') || href.includes('\\')) return null;
  const query = new URLSearchParams(href.slice('/finance?'.length));
  const id = query.get('stripe_review');
  if (query.get('tab') !== 'stripe_reconciliation' || query.get('stripe_view') !== 'reviews' || !/^[1-9]\d*$/.test(id || '')) return null;
  return `/finance?tab=stripe_reconciliation&stripe_view=reviews&stripe_review=${id}`;
}
