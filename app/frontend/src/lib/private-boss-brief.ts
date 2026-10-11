import type { PrivateMailCapabilities, PrivatePriority, PrivateSourceId, PrivateSourceStatus } from './private-workspace-api';

export type PrivateBossPeriod = 'today' | 'last7days';
export type PrivateBossDataState = 'ready' | 'partial' | 'stale' | 'missing' | 'unsupported';
export interface PrivateBossIssue {
  id: string;
  source_id: PrivateSourceId;
  item_id?: string | null;
  title: string;
  summary: string;
  next_action: string;
  priority: PrivatePriority;
  observed_at: string | null;
  task_title?: string | null;
}
export interface PrivateBossSource {
  source_id: PrivateSourceId;
  status: PrivateSourceStatus;
  last_sync: string | null;
  data_state: PrivateBossDataState;
  summary: string;
  facts: string[];
}
export interface PrivateBossAI {
  state: 'ready' | 'pending' | 'failed' | 'unavailable';
  summary: string;
  issue_notes: { issue_id: string; explanation: string }[];
  updated_at?: string | null;
  code?: string;
}
export interface PrivateBossBriefData {
  snapshot_id: string;
  period: PrivateBossPeriod;
  generated_at: string;
  window: { start: string; end: string; timezone: 'Asia/Shanghai' };
  issues: PrivateBossIssue[];
  sources: PrivateBossSource[];
  ai?: PrivateBossAI | null;
  capabilities: { configured: boolean; code?: string };
  budget?: PrivateMailCapabilities['budget'];
  limitations: string[];
}
export interface PrivateBossTaskDraft { title: string; summary: string }
export const PRIVATE_BOSS_SOURCE_NAMES: Record<PrivateSourceId, string> = { gmail: '重要邮件', google_ads: '广告观察', stripe: 'Stripe', bofa: '银行提醒', manual: '个人事项' };
export const PRIVATE_BOSS_PERIOD_NAMES: Record<PrivateBossPeriod, string> = { today: '今日', last7days: '近7天' };
const sources: PrivateSourceId[] = ['gmail', 'google_ads', 'stripe', 'bofa', 'manual'];
const dataStates: PrivateBossDataState[] = ['ready', 'partial', 'stale', 'missing', 'unsupported'];
const text = (value: unknown, maximum = 600) => typeof value === 'string' ? value.trim().slice(0, maximum) : '';
export function bossBriefForPeriod(data: PrivateBossBriefData | null, period: PrivateBossPeriod): PrivateBossBriefData | null {
  return data && data.period === period && text(data.snapshot_id, 128) ? data : null;
}
export function bossBriefTime(value: string | null | undefined): string {
  if (!value) return '未同步';
  const date = new Date(value);
  return Number.isFinite(date.getTime()) ? date.toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Shanghai' }) : '时间待确认';
}
export function bossBriefIssues(data: PrivateBossBriefData | null): PrivateBossIssue[] {
  const seen = new Set<string>();
  return (Array.isArray(data?.issues) ? data.issues : []).filter(issue => {
    if (!issue || !sources.includes(issue.source_id) || !text(issue.id, 128) || seen.has(issue.id) || !text(issue.title, 240)) return false;
    seen.add(issue.id); return true;
  }).slice(0, 3).map(issue => ({ ...issue, title: text(issue.title, 240), summary: text(issue.summary), next_action: text(issue.next_action), task_title: text(issue.task_title, 240) || null }));
}
export function bossBriefSources(data: PrivateBossBriefData | null): PrivateBossSource[] {
  const rows = Array.isArray(data?.sources) ? data.sources : [];
  return sources.flatMap(id => {
    const row = rows.find(source => source?.source_id === id);
    if (!row) return [];
    const state = dataStates.includes(row.data_state) ? row.data_state : 'missing';
    return [{ ...row, data_state: state, summary: row.status !== 'connected' ? row.status === 'error' ? '同步需要检查，当前数据待确认' : '连接后查看真实数据' : text(row.summary), facts: row.status !== 'connected' || ['missing', 'unsupported'].includes(state) ? [] : (Array.isArray(row.facts) ? row.facts : []).filter(value => typeof value === 'string' && value.trim()).slice(0, 6).map(value => text(value, 500)) }];
  });
}
export function bossBriefStateLabel(source: PrivateBossSource): string {
  if (source.data_state === 'unsupported') return '尚待接入';
  if (source.status !== 'connected') return source.status === 'error' ? '同步需检查' : source.status === 'connecting' ? '等待授权' : '尚未连接';
  return ({ ready: '已同步', partial: '部分记录', stale: '需更新', missing: '暂无依据', unsupported: '尚待接入' } as const)[source.data_state] || '暂无依据';
}
export function bossBriefTaskDraft(issue: PrivateBossIssue): PrivateBossTaskDraft {
  const source = PRIVATE_BOSS_SOURCE_NAMES[issue.source_id] || '私人工作';
  return { title: text(issue.task_title, 240) || text(issue.title, 240) || '核对私人工作事项', summary: `${source}：${text(issue.title, 240)}\n下一步：${text(issue.next_action) || '核对原始来源后再决定。'}`.slice(0, 2000) };
}
export function bossBriefAINotes(data: PrivateBossBriefData | null): { issue: PrivateBossIssue; explanation: string }[] {
  if (data?.ai?.state !== 'ready') return [];
  const notes = Array.isArray(data.ai.issue_notes) ? data.ai.issue_notes : [];
  return bossBriefIssues(data).flatMap(issue => {
    const note = notes.find(value => value?.issue_id === issue.id);
    const explanation = text(note?.explanation, 800);
    return explanation ? [{ issue, explanation }] : [];
  });
}
export function bossBriefBudget(data: PrivateBossBriefData | null): { limit: string; remaining: string } | null {
  const budget = data?.budget;
  const decimal = (value: unknown) => typeof value === 'string' && /^(?:0|[1-9]\d{0,2})\.\d{2}$/.test(value);
  if (data?.capabilities?.configured !== true || budget?.configured !== true || !decimal(budget.limit_usd) || !decimal(budget.remaining_usd)) return null;
  const limit = Number(budget.limit_usd); const remaining = Number(budget.remaining_usd);
  return limit > 0 && limit <= 5 && remaining >= 0 && remaining <= limit ? { limit: budget.limit_usd, remaining: budget.remaining_usd } : null;
}
export function bossBriefNotice(code?: string): string {
  return ({ not_configured: '中文解读尚待接入', consent_required: '中文解读尚待确认接入', stale_snapshot: '数据已更新，请重新读取简报后再解读', snapshot_expired: '数据已更新，请重新读取简报后再解读', snapshot_changed: '数据已更新，请重新读取简报后再解读', budget_exhausted: '本月解读可用额度不足，已有内容仍可查看', budget_month_changed: '月份已更新，请重新点击中文解读', pending: '这份简报正在解读，请稍后手动重试', upstream_unavailable: '暂时无法生成中文解读，可先查看系统简报' } as Record<string, string>)[code || ''] || '暂时无法生成中文解读，可先查看系统简报';
}
