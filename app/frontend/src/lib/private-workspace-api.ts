import { client } from './api';
import type { PrivateStripeReport, PrivateStripePeriodPreset } from './private-stripe-report';
import type { PrivateBossBriefData, PrivateBossPeriod } from './private-boss-brief';

export type PrivateSourceId = 'gmail' | 'google_ads' | 'bofa' | 'bofa_bank' | 'stripe' | 'manual';
export type PrivateSourceStatus = 'not_configured' | 'disconnected' | 'connecting' | 'connected' | 'error';
export type PrivateActionStatus = 'open' | 'done' | 'snoozed' | 'archived';
export type PrivatePriority = 'low' | 'normal' | 'high' | 'urgent';
export type PrivateEvidence = Record<string, unknown>;
export type PrivateAdsBucket = 'problem' | 'attention' | 'healthy' | 'paused' | 'unknown';
export type PrivateBankEnvironment = 'production' | 'sandbox';
export interface PrivateBankAccount {
  account_id: string;
  name: string;
  mask: string | null;
  type: string;
  subtype: string | null;
  currency: string | null;
  unofficial_currency?: string | null;
  current_minor: number | null;
  available_minor: number | null;
  limit_minor: number | null;
  balance_kind: 'funds' | 'owed' | 'other';
  balance_source: 'cached_accounts_get';
  balance_updated_at: string | null;
}
export interface PrivateBankSnapshot {
  id: string;
  observed_at: string;
  item_id: string;
  environment: PrivateBankEnvironment;
  institution_id: string;
  accounts_complete: boolean;
  transactions_complete: boolean;
  pagination_complete?: boolean;
  transaction_update_status: string;
  bank_updated_at: string | null;
  balance_realtime: false;
}
export interface PrivateBankLinkStart {
  session_id: string;
  authorization_url: string;
  expires_at: string;
  mode: PrivateBankEnvironment;
}
export interface PrivateBankLinkComplete {
  state: 'pending' | 'connected';
  session_id: string;
  source_id: 'bofa_bank';
}
export interface PrivateStripeSnapshot {
  id: string;
  observed_at: string;
  account_id: string;
  mode: 'live' | 'test';
}
export interface PrivateAdsSnapshot {
  id: string;
  observed_at: string;
  account_timezone: string;
  inventory_count: number;
  inventory_complete: boolean;
  metrics_complete: boolean;
  record_limit: number;
}
export interface PrivateAdsMetric {
  impressions: number;
  clicks: number;
  cost_micros: number;
  conversions: number;
}
export interface PrivateAdsHealth {
  version: 1;
  snapshot_id: string;
  bucket: PrivateAdsBucket;
  reason: string;
  impact: string;
  next_action: string;
  observed_at: string;
  account_timezone: string;
  local_date: string;
  currency: string;
  current: { status: string; primary_status: string; primary_status_reasons: string[]; serving_status: string; channel: string; start_date_time: string | null; end_date_time: string | null };
  metrics: { yesterday: PrivateAdsMetric | null; last_7_days: PrivateAdsMetric | null; previous_7_days: PrivateAdsMetric | null; last_30_days: PrivateAdsMetric | null };
  periods: Record<'yesterday' | 'last_7_days' | 'previous_7_days' | 'last_30_days', { start: string; end: string }>;
  comparison: { clicks_change_pct: number | null; cost_change_pct: number | null; conversions_change_pct: number | null; note: string };
  target: { cpa_micros: number | null; source: string; assessment: string };
  tracking: { state: 'configured' | 'unconfigured' | 'unknown'; status: string; note: string };
  coverage: { inventory_complete: boolean; metrics_complete: boolean };
  limitations: string[];
}
export type PrivateMailBucket = 'urgent' | 'today' | 'digest' | 'low';
export type PrivateMailTopic = 'finance' | 'ads' | 'security' | 'business';
export type PrivateMailFeedback = 'important' | 'not_relevant' | null;
export interface PrivateMailTranslation {
  state: 'ready' | 'failed' | 'pending' | 'unavailable';
  title_zh: string | null;
  summary_zh: string | null;
  body_zh?: string | null;
  body_original?: string | null;
  body_available: boolean;
  truncated: boolean;
  updated_at?: string | null;
}
export interface PrivateMailTranslationResult {
  configured: boolean;
  item_id: string;
  translation: PrivateMailTranslation;
  code?: string;
}
export interface PrivateMailTranslationBatch {
  configured: boolean;
  items: { item_id: string; translation: PrivateMailTranslation }[];
  code?: string;
}
export interface PrivateMailBrief {
  state: 'ready' | 'failed' | 'pending' | 'unavailable';
  title_zh: string | null;
  summary_zh: string | null;
  key_points: string[];
  relevance: string | null;
  next_action: string | null;
  needs_action: boolean | null;
  deadline: { at: string | null; text: string | null; confirmed: boolean; evidence?: string } | null;
  importance: 'urgent' | 'today' | 'read' | 'uncertain';
  source_scope: 'body' | 'preview';
  original_body?: string | null;
  source_evidence?: string[];
  evidence_limited?: boolean;
  provider_label?: string;
  truncated: boolean;
  updated_at?: string | null;
  code?: string;
}
export interface PrivateMailCapabilities {
  smart_brief: { enabled: boolean; configured: boolean; code?: string };
  translation: { enabled: boolean; configured: boolean; code?: string };
  budget?: { limit_usd: string; reserved_usd: string; remaining_usd: string; month: string; configured: boolean };
}
export interface PrivateMailBriefResult {
  configured: boolean;
  item_id: string;
  brief: PrivateMailBrief;
  code?: string;
}
export interface PrivateMailRelevance {
  bucket: PrivateMailBucket;
  category: PrivateMailTopic | 'general' | 'promotion';
  reasons: string[];
  feedback: PrivateMailFeedback;
  sender_address: string | null;
  sender_verification: 'unverified';
}
export interface PrivateGmailPreferences {
  topics: PrivateMailTopic[];
  watch_senders: string[];
  watch_keywords: string[];
  muted_senders: string[];
}
export interface PrivateWorkspacePreferences {
  sync_interval_seconds: number;
  gmail: PrivateGmailPreferences;
}
export const PRIVATE_MAIL_BUCKET_NAMES: Record<PrivateMailBucket, string> = {
  urgent: '立即关注', today: '今天处理', digest: '每日摘要', low: '低优先',
};
export const PRIVATE_MAIL_BUCKETS: PrivateMailBucket[] = ['urgent', 'today', 'digest', 'low'];
export type PrivateMailCounts = Record<PrivateMailBucket, number>;

export interface PrivateSource {
  id: PrivateSourceId;
  name: string;
  status: PrivateSourceStatus;
  capabilities: string[];
  missing_configuration: string[];
  last_sync: string | null;
  error: string | null;
  action_availability?: { can_connect: boolean; can_sync: boolean };
  metadata?: {
    account_label?: string;
    bank_item_id?: string;
    bank_environment?: PrivateBankEnvironment;
    bank_institution_id?: string;
    bank_institution_name?: string;
    bank_accounts?: PrivateBankAccount[];
    bank_snapshot?: PrivateBankSnapshot;
    stripe_account_id?: string;
    stripe_snapshot?: PrivateStripeSnapshot;
    ads_customer_id?: string;
    ads_snapshot?: PrivateAdsSnapshot;
    coverage?: string;
    partial?: boolean;
    sync_window?: string;
    record_limit?: number;
    record_limit_per_resource?: number;
    resources?: Record<string, { fetched: number; partial: boolean }>;
    mode?: 'test' | 'live';
    bank_data_verification?: string;
    read_only_adapter?: boolean;
    api_version?: string;
    aggregated_totals?: false;
    payouts_are_income?: false;
  };
}

export interface PrivateItem {
  id: string;
  source_id: PrivateSourceId;
  kind: string;
  title: string;
  summary: string;
  status: string;
  priority: PrivatePriority;
  amount_minor: number | null;
  currency: string | null;
  occurred_at: string | null;
  due_at: string | null;
  source_url: string | null;
  evidence: PrivateEvidence;
  action_status: PrivateActionStatus;
  snoozed_until: string | null;
  mail_relevance?: PrivateMailRelevance;
  mail_translation?: PrivateMailTranslation;
  mail_brief?: PrivateMailBrief;
}

export interface PrivateBalance {
  source_id: PrivateSourceId;
  currency: string;
  available_minor: number;
  pending_minor: number;
}

export interface PrivateWorkspaceData {
  sources: PrivateSource[];
  items: PrivateItem[];
  balances: PrivateBalance[];
  last_sync: string | null;
}

export interface PrivateItemList { items: PrivateItem[]; total: number; mail_counts?: PrivateMailCounts }
export interface PrivateItemFilters {
  source_id?: PrivateSourceId;
  kind?: string;
  action_status?: PrivateActionStatus;
  limit?: number;
  mail_bucket?: PrivateMailBucket;
}
export interface CreatePrivateItem {
  title: string;
  summary: string;
  priority: PrivatePriority;
  due_at?: string | null;
}
export interface UpdatePrivateItem {
  title?: string;
  summary?: string;
  action_status?: PrivateActionStatus;
  snoozed_until?: string | null;
}
export interface PrivateConnectResult {
  source: PrivateSource;
  authorization_url: string | null;
  requires_redirect: boolean;
}
export interface PrivateSyncResult {
  source: PrivateSource;
  counts: { created: number; updated: number };
}

export class PrivateWorkspaceApiError extends Error {
  status: number;
  constructor(message: string, status = 0) {
    super(message);
    this.name = 'PrivateWorkspaceApiError';
    this.status = status;
  }
}

function safeFailure(error: unknown, syncOperation = false): PrivateWorkspaceApiError {
  const value = error as { response?: { status?: number; data?: { detail?: unknown } }; status?: number; name?: string };
  const status = value?.response?.status || value?.status || 0;
  if (status === 403) return new PrivateWorkspaceApiError('此空间仅对本人开放。', status);
  if (status === 401 || value?.name === 'AuthSessionChangedError') return new PrivateWorkspaceApiError('登录状态已改变，请重新进入工作空间。', 401);
  if (syncOperation && [0, 408, 504].includes(status)) return new PrivateWorkspaceApiError('暂时没有收到同步结果，服务端可能仍在处理。请先刷新查看最后同步时间，再决定是否重试。', status);
  const detail = value?.response?.data?.detail;
  const message = typeof detail === 'string' && status >= 400 && status < 600
    ? detail.slice(0, 240)
    : status === 503 ? '此来源尚待配置或暂时无法连接，请稍后重试。' : '操作暂时无法完成，请重试。';
  return new PrivateWorkspaceApiError(message, status);
}

const PREFIX = '/api/v1/private-workspace';
async function request<T>(path: string, method: 'GET' | 'POST' | 'PATCH' | 'DELETE', data?: unknown, options?: { timeout: number }): Promise<T> {
  try {
    const response = await client.apiCall.invoke({ url: `${PREFIX}${path}`, method, ...(data === undefined ? {} : { data }), ...(options ? { options } : {}) });
    return response.data as T;
  } catch (error) {
    throw safeFailure(error, path.endsWith('/sync'));
  }
}

export const privateWorkspaceApi = {
  access: () => request<{ allowed: boolean }>('/access', 'GET'),
  stripeReport: (data: { period: PrivateStripePeriodPreset; start_date?: string; end_date?: string; refresh?: boolean }) => request<PrivateStripeReport>('/stripe/report', 'POST', data, { timeout: 65_000 }),
  overview: () => request<PrivateWorkspaceData>('', 'GET'),
  brief: (period: PrivateBossPeriod) => request<PrivateBossBriefData>(`/brief?period=${encodeURIComponent(period)}`, 'GET'),
  explainBrief: (period: PrivateBossPeriod, snapshotId: string) => request<PrivateBossBriefData>('/brief/explain', 'POST', { period, snapshot_id: snapshotId }, { timeout: 65_000 }),
  preferences: () => request<PrivateWorkspacePreferences>('/preferences', 'GET'),
  updatePreferences: (data: { gmail?: Partial<PrivateGmailPreferences>; sync_interval_seconds?: number }) => request<PrivateWorkspacePreferences>('/preferences', 'PATCH', data),
  items: (filters: PrivateItemFilters = {}) => {
    const query = new URLSearchParams();
    if (filters.source_id) query.set('source_id', filters.source_id);
    if (filters.kind) query.set('kind', filters.kind);
    if (filters.action_status) query.set('action_status', filters.action_status);
    if (filters.mail_bucket) query.set('mail_bucket', filters.mail_bucket);
    query.set('limit', String(Math.min(100, Math.max(1, filters.limit || 100))));
    return request<PrivateItemList>(`/items?${query.toString()}`, 'GET');
  },
  create: (data: CreatePrivateItem) => request<{ item: PrivateItem }>('/items', 'POST', { ...data, source_id: 'manual', kind: 'task' }),
  update: (id: string, data: UpdatePrivateItem) => request<{ item: PrivateItem }>(`/items/${encodeURIComponent(id)}`, 'PATCH', data),
  mailFeedback: (id: string, feedback: PrivateMailFeedback, applyToSender = false) => request<{ item: PrivateItem }>(`/items/${encodeURIComponent(id)}/mail-feedback`, 'POST', { feedback, apply_to_sender: applyToSender }),
  mailCapabilities: () => request<PrivateMailCapabilities>('/mail-capabilities', 'GET'),
  organizeMail: (id: string) => request<PrivateMailBriefResult>(`/items/${encodeURIComponent(id)}/mail-brief`, 'POST', { mode: 'body' }, { timeout: 65_000 }),
  translateMailPreviews: (ids: string[]) => request<PrivateMailTranslationBatch>('/mail-translations/batch', 'POST', { item_ids: [...new Set(ids)].slice(0, 10) }, { timeout: 65_000 }),
  translateMailBody: (id: string) => request<PrivateMailTranslationResult>(`/items/${encodeURIComponent(id)}/mail-translation`, 'POST', { mode: 'body' }, { timeout: 65_000 }),
  archive: (id: string) => request<{ item: PrivateItem }>(`/items/${encodeURIComponent(id)}`, 'DELETE'),
  bankLinkStart: () => request<PrivateBankLinkStart>('/bank/link/start', 'POST', undefined, { timeout: 95_000 }),
  bankLinkComplete: (sessionId: string) => request<PrivateBankLinkComplete>('/bank/link/complete', 'POST', { session_id: sessionId }, { timeout: 95_000 }),
  connect: (id: PrivateSourceId) => request<PrivateConnectResult>(`/sources/${id}/connect`, 'POST'),
  disconnect: (id: PrivateSourceId) => request<{ source: PrivateSource }>(`/sources/${id}/disconnect`, 'POST'),
  sync: (id: PrivateSourceId) => request<PrivateSyncResult>(`/sources/${id}/sync`, 'POST', undefined, { timeout: 65_000 }),
};

export function privateMailChinese(item: PrivateItem, part: 'title' | 'summary'): string {
  const brief = item.mail_brief;
  const organized = part === 'title' ? brief?.title_zh : brief?.summary_zh;
  if (item.source_id === 'gmail' && brief?.state === 'ready' && typeof organized === 'string' && organized.trim()) return organized;
  const translation = item.mail_translation;
  const value = part === 'title' ? translation?.title_zh : translation?.summary_zh;
  return item.source_id === 'gmail' && translation?.state === 'ready' && typeof value === 'string' && value.trim() ? value : item[part];
}
export function privateMailBriefNotice(code?: string, budget?: PrivateMailCapabilities['budget']): string {
  if (code === 'budget_exhausted') {
    const prefix = budget?.configured && typeof budget.limit_usd === 'string' && /^(?:0|[1-9]\d{0,2})\.\d{2}$/.test(budget.limit_usd) ? `本月 US$${budget.limit_usd} 智能整理可用额度不足` : '本月智能整理可用额度不足';
    return `${prefix}，已整理邮件和原文仍可查看`;
  }
  return ({
    not_configured: '智能整理尚待接入，当前可查看邮件原文',
    consent_required: '智能整理尚待确认接入，当前可查看邮件原文',
    limit_reached: '本月整理额度已用完，已整理的邮件仍可查看',
    budget_month_changed: '月份已更新，请重新整理这封邮件',
    upstream_unavailable: '暂时无法整理这封邮件，可先查看原文',
    authorization_expired: 'Gmail 授权已过期，请在工作接入重新连接',
    body_unavailable: '未找到可读取正文，当前仅依据邮件摘要整理',
    pending: '这封邮件正在整理，请稍后手动重试',
  } as Record<string, string>)[code || ''] || '暂时无法整理这封邮件，可先查看原文';
}
export function privateMailTranslationNotice(code?: string): string {
  return ({ not_configured: '中文翻译尚未开通', limit_reached: '本月翻译额度已用完，可先查看原文', upstream_unavailable: '中文翻译暂时无法完成，可先查看原文', authorization_expired: 'Gmail 授权已过期，请在工作接入重新连接', body_unavailable: '未找到可翻译正文，可在 Gmail 查看完整邮件' } as Record<string, string>)[code || ''] || '中文翻译暂时无法完成，可先查看原文';
}

/** Older records remain visible without inventing a personal relevance judgment. */
export function privateMailBucket(item: Pick<PrivateItem, 'mail_relevance'>): PrivateMailBucket {
  const bucket = item.mail_relevance?.bucket;
  return PRIVATE_MAIL_BUCKETS.includes(bucket) ? bucket : 'digest';
}

export function privateMailNeedsAttention(item: Pick<PrivateItem, 'source_id' | 'mail_relevance'>): boolean {
  return item.source_id !== 'gmail' || ['urgent', 'today'].includes(privateMailBucket(item));
}

/** Provider links never inherit authority from a returned title or hostname suffix. */
export function verifiedPrivateSourceUrl(source: PrivateSourceId, value: string | null | undefined): string | null {
  if (!value || source === 'manual') return null;
  const hosts: Record<Exclude<PrivateSourceId, 'manual'>, readonly string[]> = {
    gmail: ['mail.google.com'],
    google_ads: ['ads.google.com'],
    bofa: ['www.bankofamerica.com', 'secure.bankofamerica.com', 'online.bankofamerica.com', 'mail.google.com'],
    stripe: ['dashboard.stripe.com'],
    bofa_bank: ['secure.bankofamerica.com', 'online.bankofamerica.com', 'www.bankofamerica.com'],
  };
  try {
    const url = new URL(value);
    return url.protocol === 'https:' && !url.username && !url.password && (!url.port || url.port === '443') && hosts[source]?.includes(url.hostname)
      ? url.href : null;
  } catch { return null; }
}

export function verifiedGoogleAuthorizationUrl(value: string | null | undefined): string | null {
  if (!value) return null;
  try {
    const url = new URL(value);
    return url.protocol === 'https:' && url.hostname === 'accounts.google.com' && !url.username && !url.password
      && (!url.port || url.port === '443') && ['/o/oauth2/v2/auth', '/o/oauth2/auth'].includes(url.pathname)
      ? url.href : null;
  } catch { return null; }
}

export function verifiedPrivateAuthorizationUrl(source: PrivateSourceId, value: string | null | undefined): string | null {
  return ['gmail', 'google_ads', 'bofa'].includes(source) ? verifiedGoogleAuthorizationUrl(value) : null;
}

/** Hosted bank authorization only opens the exact approved Plaid HTTPS origin and Link path. */
export function verifiedBankAuthorizationUrl(value: string | null | undefined): string | null {
  if (!value) return null;
  try {
    const url = new URL(value);
    return url.protocol === 'https:' && url.hostname === 'secure.plaid.com' && !url.username && !url.password
      && (!url.port || url.port === '443') && url.pathname.startsWith('/hl/') && url.pathname.length > 4
      ? url.href : null;
  } catch { return null; }
}

export function privateSourceActionAvailability(source: PrivateSource) {
  const pendingConfiguration = source.status === 'not_configured' || source.missing_configuration.length > 0;
  const external = source.id !== 'manual';
  const stripeActions = source.id === 'stripe' ? source.action_availability : undefined;
  return {
    pendingConfiguration,
    canConnect: external && !pendingConfiguration && (stripeActions ? stripeActions.can_connect === true : source.status !== 'connected'),
    canSync: external && !pendingConfiguration && (stripeActions ? stripeActions.can_sync === true : source.status === 'connected'),
    canDisconnect: external && ['connected', 'connecting', 'error'].includes(source.status),
  };
}

// Stripe API units differ from ISO for ISK/UGX and MGA. HUF/TWD payouts still use amounts divisible by 100.
// https://docs.stripe.com/currencies#special-cases
const STRIPE_ZERO_DECIMAL_CURRENCIES = new Set(['BIF', 'CLP', 'DJF', 'GNF', 'JPY', 'KMF', 'KRW', 'MGA', 'PYG', 'RWF', 'VND', 'VUV', 'XAF', 'XOF', 'XPF']);

/** Preserve provider units; never convert or combine currencies. */
export function formatPrivateAmount(minor: number | null | undefined, currency: string | null | undefined, source: PrivateSourceId = 'manual'): string {
  if (minor === null || minor === undefined || !Number.isSafeInteger(minor) || !currency || !/^[A-Z]{3}$/.test(currency)) return '待确认';
  try {
    const options = { style: 'currency' as const, currency, currencyDisplay: 'code' as const };
    const isoFormat = new Intl.NumberFormat('zh-CN', options);
    const isoDigits = isoFormat.resolvedOptions().maximumFractionDigits;
    // No verified Stripe unit contract exists here for three-decimal currencies.
    if (source === 'stripe' && isoDigits > 2) return '待确认';
    const stripeZeroDecimal = STRIPE_ZERO_DECIMAL_CURRENCIES.has(currency);
    const digits = source === 'stripe' ? stripeZeroDecimal ? 0 : 2 : isoDigits;
    const displayDigits = stripeZeroDecimal || ['ISK', 'UGX'].includes(currency) ? 0 : 2;
    const format = source === 'stripe'
      ? new Intl.NumberFormat('zh-CN', { ...options, minimumFractionDigits: displayDigits, maximumFractionDigits: displayDigits }) : isoFormat;
    return format.format(minor / 10 ** digits);
  } catch { return '待确认'; }
}


export type PrivateStripePaymentState = 'pending' | 'failed' | 'authorized' | 'uncaptured_refunded' | 'partially_captured' | 'captured' | 'partially_refunded' | 'refunded';
const STRIPE_PAYMENT_STATES: Record<PrivateStripePaymentState, string> = {
  pending: '待处理', failed: '收款失败', authorized: '已授权 · 待捕获', partially_captured: '部分收款',
  captured: '已收款', partially_refunded: '部分退款', refunded: '已退款', uncaptured_refunded: '未捕获 · 来源标记退款',
};
const STRIPE_SNAPSHOT_MAX_AGE = 24 * 60 * 60 * 1000;
function privateStripeMinor(value: unknown, signed = false): number | null {
  return typeof value === 'number' && Number.isSafeInteger(value) && (signed || value >= 0) ? value : null;
}

/** A stored snapshot is never a real-time balance or verified bank settlement. */
export function privateStripeSnapshot(source?: PrivateSource, now = Date.now()) {
  const snapshot = source?.metadata?.stripe_snapshot;
  const accountId = source?.metadata?.stripe_account_id;
  const mode = source?.metadata?.mode;
  const observed = snapshot ? Date.parse(snapshot.observed_at) : NaN;
  const verified = Boolean(source?.id === 'stripe' && ['connected', 'error'].includes(source.status)
    && typeof accountId === 'string' && /^acct_[A-Za-z0-9]+$/.test(accountId)
    && (mode === 'live' || mode === 'test') && snapshot?.id && snapshot.account_id === accountId && snapshot.mode === mode
    && Number.isFinite(observed) && observed <= now + 5 * 60_000);
  const fresh = verified && source?.status === 'connected' && !source.error && now - observed <= STRIPE_SNAPSHOT_MAX_AGE;
  return {
    state: !verified ? 'unverified' as const : fresh ? 'fresh' as const : 'stale' as const,
    accountId: typeof accountId === 'string' ? accountId : null,
    mode: mode === 'live' || mode === 'test' ? mode : null,
    observedAt: verified ? snapshot!.observed_at : null,
    snapshotId: verified ? snapshot!.id : null,
    label: !verified ? '待重新同步' : fresh ? '同步余额' : '上次同步 · 需更新',
  };
}

/** Keep capture, refunds and transfers distinct; never turn a Charge authorization into income. */
export function privateStripeRecord(item: PrivateItem, source?: PrivateSource, now = Date.now()) {
  const snapshot = privateStripeSnapshot(source, now);
  const evidence = item.evidence || {};
  const observed = typeof evidence.stripe_observed_at === 'string' ? evidence.stripe_observed_at : null;
  const mode = evidence.stripe_mode === 'live' || evidence.stripe_mode === 'test' ? evidence.stripe_mode : null;
  const current = item.source_id === 'stripe' && snapshot.state !== 'unverified'
    && evidence.stripe_account_id === snapshot.accountId && mode === snapshot.mode
    && evidence.stripe_snapshot_id === snapshot.snapshotId && observed === snapshot.observedAt;
  const rawState = evidence.payment_state;
  const paymentState = item.kind === 'payment' && typeof rawState === 'string' && Object.prototype.hasOwnProperty.call(STRIPE_PAYMENT_STATES, rawState)
    ? rawState as PrivateStripePaymentState : null;
  const captured = privateStripeMinor(evidence.amount_captured_minor);
  const refunded = privateStripeMinor(evidence.amount_refunded_minor);
  const authorized = privateStripeMinor(evidence.amount_authorized_minor);
  const raw = privateStripeMinor(item.amount_minor, item.kind === 'payout');
  const negativePayout = item.kind === 'payout' && raw !== null && raw < 0;
  const amountMinor = paymentState === 'authorized' ? authorized
    : paymentState && ['captured', 'partially_captured', 'partially_refunded', 'refunded'].includes(paymentState) ? captured : raw;
  const amountLabel = negativePayout ? '反向划转金额' : paymentState === 'uncaptured_refunded' ? '来源请求金额' : paymentState === 'authorized' ? '授权金额'
    : paymentState && ['captured', 'partially_captured', 'partially_refunded', 'refunded'].includes(paymentState) ? '已收款金额'
    : item.kind === 'payment' ? '请求金额' : item.kind === 'refund' ? '退款记录金额' : item.kind === 'dispute' ? '争议金额' : '提现金额';
  const statusLabels: Record<string, string> = {
    succeeded: '已完成', paid: item.kind === 'payout' ? negativePayout ? 'Stripe 标记完成 · 银行待核对' : 'Stripe 标记支付 · 银行待核对' : '已支付',
    pending: '待处理', in_transit: '转账途中', failed: '失败', canceled: '已取消', cancelled: '已取消',
    needs_response: '需要回应', under_review: '审核中', won: '争议已胜诉', lost: '争议未胜诉',
  };
  return {
    current, observedAt: observed, mode,
    freshnessLabel: !current ? '历史记录 · 待重新同步' : snapshot.state === 'stale' ? '上次同步记录 · 需更新' : '同步记录',
    statusLabel: item.kind === 'payment' ? paymentState ? STRIPE_PAYMENT_STATES[paymentState] : '收款状态待复核' : statusLabels[item.status] || '来源状态待复核',
    paymentState, amountMinor, amountLabel, capturedMinor: captured, refundedMinor: refunded, authorizedMinor: authorized,
    hasRefund: Boolean(paymentState && ['partially_refunded', 'refunded'].includes(paymentState)),
  };
}
