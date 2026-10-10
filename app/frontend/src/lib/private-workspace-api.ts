import { client } from './api';

export type PrivateSourceId = 'gmail' | 'google_ads' | 'bofa' | 'stripe' | 'manual';
export type PrivateSourceStatus = 'not_configured' | 'disconnected' | 'connecting' | 'connected' | 'error';
export type PrivateActionStatus = 'open' | 'done' | 'snoozed' | 'archived';
export type PrivatePriority = 'low' | 'normal' | 'high' | 'urgent';
export type PrivateEvidence = Record<string, unknown>;
export type PrivateMailBucket = 'urgent' | 'today' | 'digest' | 'low';
export type PrivateMailTopic = 'finance' | 'ads' | 'security' | 'business';
export type PrivateMailFeedback = 'important' | 'not_relevant' | null;
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
  metadata?: {
    account_label?: string;
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

function safeFailure(error: unknown): PrivateWorkspaceApiError {
  const value = error as { response?: { status?: number; data?: { detail?: unknown } }; status?: number; name?: string };
  const status = value?.response?.status || value?.status || 0;
  if (status === 403) return new PrivateWorkspaceApiError('此空间仅对本人开放。', status);
  if (status === 401 || value?.name === 'AuthSessionChangedError') return new PrivateWorkspaceApiError('登录状态已改变，请重新进入工作空间。', 401);
  const detail = value?.response?.data?.detail;
  const message = typeof detail === 'string' && status >= 400 && status < 600
    ? detail.slice(0, 240)
    : status === 503 ? '此来源尚待配置或暂时无法连接，请稍后重试。' : '操作暂时无法完成，请重试。';
  return new PrivateWorkspaceApiError(message, status);
}

const PREFIX = '/api/v1/private-workspace';
async function request<T>(path: string, method: 'GET' | 'POST' | 'PATCH' | 'DELETE', data?: unknown): Promise<T> {
  try {
    const response = await client.apiCall.invoke({ url: `${PREFIX}${path}`, method, ...(data === undefined ? {} : { data }) });
    return response.data as T;
  } catch (error) {
    throw safeFailure(error);
  }
}

export const privateWorkspaceApi = {
  access: () => request<{ allowed: boolean }>('/access', 'GET'),
  overview: () => request<PrivateWorkspaceData>('', 'GET'),
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
  archive: (id: string) => request<{ item: PrivateItem }>(`/items/${encodeURIComponent(id)}`, 'DELETE'),
  connect: (id: PrivateSourceId) => request<PrivateConnectResult>(`/sources/${id}/connect`, 'POST'),
  disconnect: (id: PrivateSourceId) => request<{ source: PrivateSource }>(`/sources/${id}/disconnect`, 'POST'),
  sync: (id: PrivateSourceId) => request<PrivateSyncResult>(`/sources/${id}/sync`, 'POST'),
};

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

export function privateSourceActionAvailability(source: PrivateSource) {
  const pendingConfiguration = source.status === 'not_configured' || source.missing_configuration.length > 0;
  const external = source.id !== 'manual';
  return {
    pendingConfiguration,
    canConnect: external && !pendingConfiguration && source.status !== 'connected',
    canSync: external && !pendingConfiguration && source.status === 'connected',
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
