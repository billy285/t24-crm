import type { PrivateAdsBucket, PrivateAdsHealth, PrivateAdsMetric, PrivateItem, PrivateSource } from './private-workspace-api';

export const ADS_BUCKET_NAMES: Record<PrivateAdsBucket, string> = {
  problem: '异常停投', attention: '需关注', healthy: '正常投放', paused: '暂停结束', unknown: '数据待确认',
};
export const ADS_BUCKETS: PrivateAdsBucket[] = ['problem', 'attention', 'healthy', 'paused', 'unknown'];
const MAX_AGE = 24 * 60 * 60 * 1000;
const object = (value: unknown): Record<string, unknown> | null => value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : null;
const text = (value: unknown): string => typeof value === 'string' ? value.trim() : '';
const timestamp = (value: unknown) => typeof value === 'string' ? Date.parse(value) : NaN;
const fresh = (value: unknown, now: number) => Number.isFinite(timestamp(value)) && now - timestamp(value) <= MAX_AGE && timestamp(value) - now <= 5 * 60 * 1000;
const strings = (value: unknown) => Array.isArray(value) ? value.filter((entry): entry is string => typeof entry === 'string').slice(0, 30) : [];
const finite = (value: unknown) => typeof value === 'number' && Number.isFinite(value) ? value : null;

/** A display alias only. The provider name remains on the unchanged item. */
export function privateAdsDisplayTitle(item: Pick<PrivateItem, 'title'>): string {
  const title = text(item.title);
  return /^(?:LocalServicesCampaign:)?SystemGenerated(?:$|[-_\s:])/i.test(title) ? '本地服务广告' : title || '未命名广告系列';
}
function readHealth(raw: Record<string, unknown> | null): PrivateAdsHealth | null {
  if (!raw || raw.version !== 1 || !ADS_BUCKETS.includes(raw.bucket as PrivateAdsBucket)) return null;
  const current = object(raw.current); const metrics = object(raw.metrics); const periods = object(raw.periods);
  const comparison = object(raw.comparison); const target = object(raw.target); const tracking = object(raw.tracking); const coverage = object(raw.coverage);
  return {
    version: 1, bucket: raw.bucket as PrivateAdsBucket, snapshot_id: text(raw.snapshot_id), reason: text(raw.reason), impact: text(raw.impact), next_action: text(raw.next_action),
    observed_at: text(raw.observed_at), account_timezone: text(raw.account_timezone), local_date: text(raw.local_date), currency: /^[A-Z]{3}$/.test(text(raw.currency)) ? text(raw.currency) : '',
    current: { status: text(current?.status), primary_status: text(current?.primary_status), primary_status_reasons: strings(current?.primary_status_reasons), serving_status: text(current?.serving_status), channel: text(current?.channel), start_date_time: text(current?.start_date_time) || null, end_date_time: text(current?.end_date_time) || null },
    metrics: { yesterday: privateAdsMetric(metrics?.yesterday), last_7_days: privateAdsMetric(metrics?.last_7_days), previous_7_days: privateAdsMetric(metrics?.previous_7_days), last_30_days: privateAdsMetric(metrics?.last_30_days) },
    periods: Object.fromEntries(['yesterday', 'last_7_days', 'previous_7_days', 'last_30_days'].map(key => { const period = object(periods?.[key]); return [key, { start: text(period?.start), end: text(period?.end) }]; })) as PrivateAdsHealth['periods'],
    comparison: { clicks_change_pct: finite(comparison?.clicks_change_pct), cost_change_pct: finite(comparison?.cost_change_pct), conversions_change_pct: finite(comparison?.conversions_change_pct), note: text(comparison?.note) },
    target: { cpa_micros: finite(target?.cpa_micros), source: text(target?.source), assessment: text(target?.assessment) },
    tracking: { state: tracking?.state === 'configured' || tracking?.state === 'unconfigured' ? tracking.state : 'unknown', status: text(tracking?.status), note: text(tracking?.note) },
    coverage: { inventory_complete: coverage?.inventory_complete === true, metrics_complete: coverage?.metrics_complete === true }, limitations: strings(raw.limitations),
  };
}

/** These are delivery observations, never the local task's action_status. */
export function privateAdsObservation(item: PrivateItem, source?: PrivateSource, now = Date.now()) {
  const raw = object(item.evidence?.ads_health);
  const health = readHealth(raw);
  const snapshot = source?.metadata?.ads_snapshot;
  let warning = '';
  if (!source || source.status !== 'connected' || source.error) warning = '来源未连接或最近同步失败，请先检查接入。';
  else if (!health || !snapshot || !text(snapshot.id)) warning = '尚无完整的投放检查数据，请重新同步。';
  else if (health.snapshot_id !== snapshot.id) warning = '这条记录不属于最新检查，当前状态待确认。';
  else if (!fresh(health.observed_at, now) || !fresh(snapshot.observed_at, now)) warning = '检查数据已过期，请重新同步后判断投放状态。';
  else if (health.coverage.metrics_complete !== true || snapshot.metrics_complete !== true || !health.currency || !health.metrics.yesterday || !health.metrics.last_7_days) warning = '当前检查数据不完整，暂不判断投放是否正常。';
  else if (!text(health.reason) || !text(health.next_action)) warning = '检查依据不完整，请在 Google Ads 核实。';
  return {
    health,
    bucket: warning ? 'unknown' as PrivateAdsBucket : health!.bucket,
    current: Boolean(health && snapshot && health.snapshot_id === snapshot.id),
    verified: !warning,
    reason: warning || health!.reason,
    impact: warning ? '当前数据不能代表此刻的投放状态。' : text(health!.impact),
    nextAction: warning ? '重新同步，或打开 Google Ads 核实当前状态。' : health!.next_action,
  };
}

export function privateAdsNeedsAttention(item: PrivateItem, source?: PrivateSource, now = Date.now()): boolean {
  const observation = privateAdsObservation(item, source, now);
  return observation.verified && ['problem', 'attention'].includes(observation.bucket);
}

export function privateAdsMetric(value: unknown): PrivateAdsMetric | null {
  const metric = object(value);
  if (!metric || !['impressions', 'clicks', 'cost_micros', 'conversions'].every(key => typeof metric[key] === 'number' && Number.isFinite(metric[key]) && (metric[key] as number) >= 0)) return null;
  if (!['impressions', 'clicks', 'cost_micros'].every(key => Number.isSafeInteger(metric[key]))) return null;
  return metric as unknown as PrivateAdsMetric;
}

export function privateAdsMoney(micros: unknown, currency: unknown): string {
  if (typeof micros !== 'number' || !Number.isSafeInteger(micros) || micros < 0 || typeof currency !== 'string' || !/^[A-Z]{3}$/.test(currency)) return '待确认';
  return `${currency} ${new Intl.NumberFormat('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(micros / 1_000_000)}`;
}
export function privateAdsNumber(value: unknown): string {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 ? new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 2 }).format(value) : '待确认';
}
export function privateAdsConversions(health: PrivateAdsHealth | null, metric: PrivateAdsMetric | null): string {
  if (health?.tracking?.state !== 'configured') return health?.tracking?.state === 'unconfigured' ? '未配置' : '待确认';
  return privateAdsNumber(metric?.conversions);
}
export function privateAdsPeriod(value: unknown): string {
  const period = object(value);
  const start = text(period?.start); const end = text(period?.end);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(start) || !/^\d{4}-\d{2}-\d{2}$/.test(end)) return '日期待确认';
  return start === end ? start : `${start} 至 ${end}`;
}
export function privateAdsTime(value: unknown): string {
  const stamp = timestamp(value);
  return Number.isFinite(stamp) ? new Date(stamp).toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '尚未检查';
}
export function privateAdsStatus(value: unknown): string {
  return ({ ENABLED: '已启用', PAUSED: '已暂停', REMOVED: '已移除', ENDED: '已结束' } as Record<string, string>)[text(value)] || '待确认';
}
const PRIMARY_REASONS: Record<string, string> = {
  BUDGET_CONSTRAINED: '预算限制展示', BUDGET_MISCONFIGURED: '预算配置错误', BIDDING_STRATEGY_MISCONFIGURED: '出价策略配置错误',
  BIDDING_STRATEGY_LIMITED: '出价设置限制', BIDDING_STRATEGY_CONSTRAINED: 'CPA / ROAS 目标限制', BIDDING_STRATEGY_LEARNING: '出价学习中',
  SEARCH_VOLUME_LIMITED: '搜索覆盖受限', HAS_ADS_DISAPPROVED: '部分广告被拒', HAS_ASSET_GROUPS_DISAPPROVED: '部分素材组被拒',
  HAS_ADS_LIMITED_BY_POLICY: '部分广告受政策限制', HAS_ASSET_GROUPS_LIMITED_BY_POLICY: '部分素材组受政策限制',
  MOST_ADS_UNDER_REVIEW: '多数广告审核中', MOST_ASSET_GROUPS_UNDER_REVIEW: '多数素材组审核中',
  NO_AD_GROUPS: '缺少可投放广告组', NO_AD_GROUP_ADS: '缺少可投放广告', NO_KEYWORDS: '缺少可投放关键词', NO_ASSET_GROUPS: '缺少可投放素材组',
  MISSING_CALL_EXTENSION: '缺少电话素材', MISSING_LEAD_FORM_EXTENSION: '缺少线索表单素材', MISSING_LOCATION_TARGETING: '缺少位置定位',
  CAMPAIGN_PAUSED: '广告系列已暂停', CAMPAIGN_REMOVED: '广告系列已移除', CAMPAIGN_ENDED: '广告系列已结束', CAMPAIGN_PENDING: '广告系列尚未开始',
};
export function privateAdsReasons(health: PrivateAdsHealth | null): string[] {
  return [...new Set((health?.current.primary_status_reasons || []).map(reason => PRIMARY_REASONS[reason] || 'Google 状态原因待确认'))];
}
export function privateAdsActualCpa(health: PrivateAdsHealth | null): string {
  const metric = privateAdsMetric(health?.metrics.last_7_days);
  if (health?.tracking.state !== 'configured' || !metric || metric.conversions <= 0) return '待确认';
  return privateAdsMoney(Math.round(metric.cost_micros / metric.conversions), health.currency);
}
