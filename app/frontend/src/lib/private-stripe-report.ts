import { formatPrivateAmount, verifiedPrivateSourceUrl } from './private-workspace-api';

export type PrivateStripePeriodPreset = 'month' | 'quarter' | 'year' | 'custom';
export type PrivateStripeDashboardTab = 'overview' | 'subscriptions' | 'records' | 'funds';
export type PrivateStripeRecordFilter = 'all' | 'subscription' | 'one_time' | 'unclassified' | 'refund' | 'dispute';
export type PrivateStripeIncomeCategory = 'subscription' | 'one_time' | 'unclassified';
export interface PrivateStripeSelection {
  preset: PrivateStripePeriodPreset;
  start_date: string;
  end_date: string;
  currency: string;
  tab: PrivateStripeDashboardTab;
  filter: PrivateStripeRecordFilter;
  search: string;
  expanded_record_id: string | null;
  expanded_subscription_id: string | null;
}
export interface PrivateStripeReportPeriod {
  preset: PrivateStripePeriodPreset;
  label: string;
  start_date: string;
  end_date: string;
  timezone: string;
  comparison_label: string;
}
export interface PrivateStripeReportCurrency {
  currency: string;
  gross_minor: number | null;
  subscription_minor: number | null;
  one_time_minor: number | null;
  unclassified_minor: number | null;
  refunds_minor: number | null;
  net_receipts_minor: number | null;
  fees_minor: number | null;
  count: number | null;
  summary: string[];
  comparison: { gross_minor: number | null; change_pct: number | null; complete: boolean };
  trend: { date: string; subscription_minor: number | null; one_time_minor: number | null; unclassified_minor: number | null }[];
}
export interface PrivateStripeReportRecord {
  id: string;
  kind: 'payment' | 'refund' | 'dispute' | 'payout' | 'adjustment';
  title: string;
  status: string;
  occurred_at: string | null;
  amount_minor: number | null;
  currency: string;
  category: PrivateStripeIncomeCategory | null;
  customer_label: string | null;
  subscription_id: string | null;
  invoice_id: string | null;
  source_url: string | null;
  details: Record<string, string | number | null>;
}
export interface PrivateStripeReportSubscription {
  id: string;
  customer_label: string | null;
  status: string;
  currency: string;
  next_payment_at: string | null;
  amount_minor: number | null;
  source_url: string | null;
  period_end?: string | null;
  cancel_at_period_end?: boolean;
  plans?: { label: string; amount_minor: number | null; currency: string; quantity: number; interval: string; interval_count: number }[];
}
export interface PrivateStripeReport {
  state: 'ready' | 'partial' | 'unavailable';
  snapshot_id: string;
  generated_at: string;
  account_label: string;
  mode: 'live' | 'test';
  period: PrivateStripeReportPeriod;
  coverage: { complete: boolean; amounts_complete?: boolean; classifications_complete?: boolean; subscriptions_complete?: boolean; payouts_complete?: boolean; disputes_complete?: boolean; funds_complete?: boolean; attention_complete?: boolean; reasons: string[] };
  currencies: PrivateStripeReportCurrency[];
  records: PrivateStripeReportRecord[];
  subscriptions: PrivateStripeReportSubscription[];
  attention: { id: string; title: string; reason: string; source_url: string | null }[];
  balances: { currency: string; available_minor: number | null; pending_minor: number | null; observed_at: string | null }[];
}
export interface PrivateStripeDashboardProps {
  report: PrivateStripeReport | null;
  selection: PrivateStripeSelection;
  loading: boolean;
  error?: string;
  busy?: boolean;
  connectionLabel?: string;
  connected?: boolean;
  canManageConnection?: boolean;
  onChangeSelection: (next: PrivateStripeSelection) => void;
  onRetry: () => void;
  onManageConnection: () => void;
}

export const PRIVATE_STRIPE_PERIOD_NAMES: Record<PrivateStripePeriodPreset, string> = { month: '本月', quarter: '本季度', year: '本年', custom: '自定义' };
export const PRIVATE_STRIPE_TAB_NAMES: Record<PrivateStripeDashboardTab, string> = { overview: '总览', subscriptions: '订阅', records: '流水', funds: '资金' };
export const PRIVATE_STRIPE_FILTER_NAMES: Record<PrivateStripeRecordFilter, string> = { all: '全部', subscription: '订阅相关收款', one_time: '单次收款', unclassified: '待分类', refund: '退款', dispute: '争议' };
export const PRIVATE_STRIPE_CATEGORY_NAMES: Record<PrivateStripeIncomeCategory, string> = { subscription: '订阅相关收款', one_time: '单次收款', unclassified: '待分类收款' };
export const privateStripeReportText = (value: unknown, limit = 600): string => typeof value === 'string' ? value.trim().slice(0, limit) : '';
export const privateStripeReportMinor = (value: unknown): value is number => typeof value === 'number' && Number.isSafeInteger(value);
export const privateStripeReportCurrencyCode = (value: unknown): value is string => typeof value === 'string' && value.length === 3 && /^[A-Z]{3}$/.test(value);
export function privateStripeReportMoney(value: unknown, currency: unknown): string {
  return privateStripeReportMinor(value) && privateStripeReportCurrencyCode(currency) ? formatPrivateAmount(value, currency, 'stripe') : '待确认';
}
/** An empty incomplete read is not evidence of a financial zero. */
export function privateStripeReportMetricMoney(value: unknown, currency: unknown, complete: boolean): string {
  return value === 0 && !complete ? '待确认' : privateStripeReportMoney(value, currency);
}
export function privateStripeReportTime(value: unknown, timezone = 'UTC', dateOnly = false): string {
  if (typeof value !== 'string' || !value) return '时间待确认';
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return '时间待确认';
  const options: Intl.DateTimeFormatOptions = { month: 'numeric', day: 'numeric', ...(dateOnly ? {} : { hour: '2-digit', minute: '2-digit' }), timeZone: timezone };
  try { return new Intl.DateTimeFormat('zh-CN', options).format(date); } catch { return '时间待确认'; }
}
export function privateStripeReportDate(value: unknown): value is string {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const date = new Date(`${value}T00:00:00Z`);
  return Number.isFinite(date.getTime()) && date.toISOString().slice(0, 10) === value;
}
export function createPrivateStripeSelection(now = new Date()): PrivateStripeSelection {
  const end = now.toISOString().slice(0, 10);
  return { preset: 'month', start_date: `${end.slice(0, 7)}-01`, end_date: end, currency: '', tab: 'overview', filter: 'all', search: '', expanded_record_id: null, expanded_subscription_id: null };
}
function copyPrivateStripeCurrencyRow<T extends { currency: string }>(row: T): T {
  if (!row || typeof row !== 'object') return row;
  const currency = typeof row.currency === 'string' && row.currency.length === 3 && /^[A-Za-z]{3}$/.test(row.currency) ? row.currency.toUpperCase() : row.currency;
  return { ...row, currency };
}
/** Period and currency selection never combine provider amounts across currencies. */
export function privateStripeReportForSelection(report: PrivateStripeReport | null, selection: PrivateStripeSelection): PrivateStripeReport | null {
  if (!report || !['ready', 'partial', 'unavailable'].includes(report.state) || !privateStripeReportText(report.snapshot_id, 200)
    || report.period?.preset !== selection.preset || !privateStripeReportDate(report.period.start_date) || !privateStripeReportDate(report.period.end_date)
    || report.period.start_date > report.period.end_date) return null;
  if (selection.preset === 'custom' && (report.period.start_date !== selection.start_date || report.period.end_date !== selection.end_date)) return null;
  // Stripe provider rows can retain lowercase codes while summary rows use
  // uppercase. Normalize copies once, before every view validates and filters.
  return {
    ...report,
    currencies: Array.isArray(report.currencies) ? report.currencies.map(copyPrivateStripeCurrencyRow) : report.currencies,
    records: Array.isArray(report.records) ? report.records.map(copyPrivateStripeCurrencyRow) : report.records,
    balances: Array.isArray(report.balances) ? report.balances.map(copyPrivateStripeCurrencyRow) : report.balances,
    subscriptions: Array.isArray(report.subscriptions) ? report.subscriptions.map(row => {
      const subscription = copyPrivateStripeCurrencyRow(row);
      return subscription && typeof subscription === 'object' && Array.isArray(subscription.plans)
        ? { ...subscription, plans: subscription.plans.map(copyPrivateStripeCurrencyRow) } : subscription;
    }) : report.subscriptions,
  };
}
export function privateStripeReportCurrencies(report: PrivateStripeReport | null): PrivateStripeReportCurrency[] {
  const seen = new Set<string>();
  return (Array.isArray(report?.currencies) ? report.currencies : []).filter(row => {
    if (!row || !privateStripeReportCurrencyCode(row.currency) || seen.has(row.currency)) return false;
    seen.add(row.currency); return true;
  });
}
export function privateStripeSelectedCurrency(report: PrivateStripeReport | null, selection: PrivateStripeSelection): PrivateStripeReportCurrency | null {
  const rows = privateStripeReportCurrencies(report);
  return rows.find(row => row.currency === selection.currency) || (!selection.currency ? rows[0] : null) || null;
}
export function privateStripeAmountsComplete(report: PrivateStripeReport | null): boolean {
  return Boolean(report && report.state !== 'unavailable' && (report.coverage?.amounts_complete ?? report.coverage?.complete) === true);
}
export function privateStripeClassificationsComplete(report: PrivateStripeReport | null): boolean {
  return Boolean(report && report.state !== 'unavailable' && (report.coverage?.classifications_complete ?? report.coverage?.complete) === true);
}
export function privateStripeReportComparison(report: PrivateStripeReport, row: PrivateStripeReportCurrency): string {
  const comparison = row.comparison;
  if (!privateStripeAmountsComplete(report) || comparison?.complete !== true || !privateStripeReportMinor(comparison.gross_minor)
    || typeof comparison.change_pct !== 'number' || !Number.isFinite(comparison.change_pct)) return `${privateStripeReportText(report.period.comparison_label, 100) || '与上一期间相比'} · 对比待确认`;
  const percent = Math.abs(comparison.change_pct).toLocaleString('zh-CN', { maximumFractionDigits: 1 });
  return `${privateStripeReportText(report.period.comparison_label, 100) || '与上一期间相比'} · ${comparison.change_pct === 0 ? '持平' : `${comparison.change_pct > 0 ? '增加' : '减少'} ${percent}%`}`;
}
export function privateStripeReportStatus(status: string, kind?: PrivateStripeReportRecord['kind'] | 'subscription'): string {
  if (kind === 'payout') return ({ paid: 'Stripe 已支付 · 银行待核对', pending: '待划转', in_transit: '划转中', failed: '提现失败', canceled: '提现已取消' } as Record<string, string>)[status] || '提现状态待确认';
  if (kind === 'payment' && ['succeeded', 'paid'].includes(status)) return '已收款';
  if (kind === 'adjustment') return '来源资金记录';
  return ({ active: '进行中', trialing: '试用中', past_due: '付款逾期', unpaid: '未付款', canceled: '已取消', incomplete: '等待首次付款', incomplete_expired: '首次付款已过期', paused: '已暂停', succeeded: '已完成', captured: '已收款', partially_captured: '部分收款', authorized: '已授权 · 待收款', pending: '待处理', failed: '失败', paid: '已支付', refunded: '已退款', partially_refunded: '部分退款', needs_response: '需要回应', under_review: '审核中', won: '争议胜诉', lost: '争议败诉', warning_needs_response: '需要回应', warning_under_review: '审核中', warning_closed: '已关闭', canceled_refund: '退款已取消', requires_payment_method: '待付款', requires_action: '等待付款确认', processing: '处理中' } as Record<string, string>)[status] || '状态待确认';
}
export function privateStripeReportRecords(report: PrivateStripeReport | null, selection: PrivateStripeSelection, funds = false): PrivateStripeReportRecord[] {
  const currency = privateStripeSelectedCurrency(report, selection)?.currency || selection.currency;
  const query = privateStripeReportText(selection.search, 240).toLocaleLowerCase();
  const seen = new Set<string>();
  return (Array.isArray(report?.records) ? report.records : []).filter(row => {
    if (!row || !privateStripeReportText(row.id, 200) || seen.has(row.id) || !['payment', 'refund', 'dispute', 'payout', 'adjustment'].includes(row.kind)
      || !privateStripeReportCurrencyCode(row.currency) || row.currency !== currency || (funds !== ['payout', 'adjustment'].includes(row.kind))) return false;
    seen.add(row.id);
    if (!funds && selection.filter !== 'all' && (['refund', 'dispute'].includes(selection.filter) ? row.kind !== selection.filter : row.kind !== 'payment' || row.category !== selection.filter)) return false;
    return !query || [row.title, row.customer_label, row.id, row.subscription_id, row.invoice_id, privateStripeReportStatus(row.status, row.kind)].join(' ').toLocaleLowerCase().includes(query);
  });
}
export function privateStripeReportSubscriptions(report: PrivateStripeReport | null, selection: PrivateStripeSelection): PrivateStripeReportSubscription[] {
  const currency = privateStripeSelectedCurrency(report, selection)?.currency || selection.currency;
  const query = privateStripeReportText(selection.search, 240).toLocaleLowerCase();
  const seen = new Set<string>();
  return (Array.isArray(report?.subscriptions) ? report.subscriptions : []).filter(row => {
    if (!row || !privateStripeReportText(row.id, 200) || seen.has(row.id) || !privateStripeReportCurrencyCode(row.currency) || row.currency !== currency) return false;
    seen.add(row.id);
    return !query || [row.customer_label, row.id, privateStripeReportStatus(row.status, 'subscription')].join(' ').toLocaleLowerCase().includes(query);
  });
}
export function privateStripeReportSourceUrl(value: string | null | undefined): string | null { return verifiedPrivateSourceUrl('stripe', value); }
