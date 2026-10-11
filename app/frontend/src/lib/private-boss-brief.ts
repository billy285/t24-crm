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
  connection_state_known?: boolean;
}
export interface PrivateBossAI {
  state: 'ready' | 'pending' | 'failed' | 'unavailable';
  summary: string;
  issue_notes: { issue_id: string; explanation: string }[];
  source_refs?: PrivateSourceId[];
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
export const PRIVATE_BOSS_SOURCE_NAMES: Record<PrivateSourceId, string> = { gmail: '重要邮件', google_ads: '广告观察', stripe: 'Stripe', bofa: '银行邮件提醒', bofa_bank: '银行余额与流水', manual: '个人事项' };
export const PRIVATE_BOSS_PERIOD_NAMES: Record<PrivateBossPeriod, string> = { today: '今日', last7days: '近7天' };
const sources: PrivateSourceId[] = ['gmail', 'google_ads', 'stripe', 'bofa_bank', 'bofa', 'manual'];
const dataStates: PrivateBossDataState[] = ['ready', 'partial', 'stale', 'missing', 'unsupported'];
const text = (value: unknown, maximum = 600) => typeof value === 'string' ? value.trim().slice(0, maximum) : '';
const recordNames: Record<string, string> = { pi: '付款记录', ch: '付款记录', po: '提现记录', re: '退款记录', dp: '争议记录', du: '争议记录', txn: '资金流水', cs: '结账记录', sub: '订阅记录', in: '账单记录', acct: '账户记录' };
export function bossBriefReadableText(value: unknown, maximum = 600): string {
  return text(value, maximum)
    .replace(/LocalServicesCampaign:SystemGenerated:[a-z0-9]+/gi, '本地服务广告')
    .replace(/\b(pi|ch|po|re|dp|du|txn|cs|sub|in|acct)_[A-Za-z0-9]+\b/g, (_, kind: string) => recordNames[kind])
    .replace(/\b(gmail|google_ads|bofa_bank|bofa|manual)\b/g, source => PRIVATE_BOSS_SOURCE_NAMES[source as PrivateSourceId])
    .replace(/\b(?:campaign_id|customer_id|snapshot_id|source_id|item_id)\b/g, field => ({ campaign_id: '广告系列', customer_id: '广告账户', snapshot_id: '同步依据', source_id: '来源', item_id: '来源记录' } as Record<string, string>)[field]);
}
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
  const seenItems = new Set<string>();
  return (Array.isArray(data?.issues) ? data.issues : []).filter(issue => {
    if (!issue || !sources.includes(issue.source_id) || !text(issue.id, 128) || seen.has(issue.id) || !text(issue.title, 240)) return false;
    const item = text(issue.item_id, 128);
    const itemKey = item ? `${issue.source_id}:${item}` : '';
    if (itemKey && seenItems.has(itemKey)) return false;
    if (itemKey) seenItems.add(itemKey);
    seen.add(issue.id); return true;
  }).slice(0, 3).map(issue => ({ ...issue, title: text(issue.title, 240), summary: text(issue.summary), next_action: text(issue.next_action), task_title: text(issue.task_title, 240) || null }));
}
export function bossBriefSources(data: PrivateBossBriefData | null): PrivateBossSource[] {
  if (!data) return [];
  const rows = Array.isArray(data?.sources) ? data.sources : [];
  return sources.flatMap(id => {
    const row = rows.find(source => source?.source_id === id);
    if (!row) return [{ source_id: id, status: 'disconnected' as const, connection_state_known: false, last_sync: null, data_state: 'missing' as const, summary: '当前简报未取得此来源的依据', facts: [] }];
    const suppliedState = dataStates.includes(row.data_state) ? row.data_state : 'missing';
    const validTime = Boolean(row.last_sync && Number.isFinite(new Date(row.last_sync).getTime()));
    const state = id !== 'manual' && !validTime && ['ready', 'partial'].includes(suppliedState) ? 'missing' : suppliedState;
    return [{ ...row, data_state: state, summary: row.status !== 'connected' ? row.status === 'error' ? '同步需要检查，当前数据待确认' : '连接后查看真实数据' : ['missing', 'unsupported'].includes(state) ? '来源依据待确认，不能据此判断当前状态' : bossBriefReadableText(row.summary), facts: row.status !== 'connected' || ['missing', 'unsupported'].includes(state) ? [] : (Array.isArray(row.facts) ? row.facts : []).filter(value => typeof value === 'string' && value.trim()).slice(0, 6).map(value => bossBriefReadableText(value, 500)) }];
  });
}
export function bossBriefStateLabel(source: PrivateBossSource): string {
  if (source.connection_state_known === false) return '待确认';
  if (source.data_state === 'unsupported') return '尚待接入';
  if (source.status !== 'connected') return source.status === 'error' ? '同步需检查' : source.status === 'connecting' ? '等待授权' : '尚未连接';
  if (source.source_id === 'bofa' && ['ready', 'partial'].includes(source.data_state)) return '待核实';
  return ({ ready: '已同步', partial: '部分记录', stale: '需更新', missing: '暂无依据', unsupported: '尚待接入' } as const)[source.data_state] || '暂无依据';
}
export function bossBriefCoverageLabel(source: PrivateBossSource): string {
  if (source.status !== 'connected' || ['missing', 'unsupported'].includes(source.data_state)) return '覆盖待确认';
  if (source.source_id === 'manual') return '当前个人事项';
  if (source.data_state === 'partial') return '仅部分记录';
  if (source.data_state === 'stale') return '仅历史记录';
  return '已同步范围';
}
export function bossBriefFreshnessLabel(source: PrivateBossSource): string {
  if (source.source_id === 'manual' && source.status === 'connected' && source.data_state === 'ready') return '本地记录';
  if (!source.last_sync) return '时间待确认';
  return `${source.data_state === 'stale' ? '需更新 · ' : '同步 '}${bossBriefTime(source.last_sync)}`;
}
export interface PrivateBossIssueView { title: string; reason: string; nextAction: string; kind: 'business' | 'verification'; trust: string }
export function bossBriefIssueView(issue: PrivateBossIssue, data: PrivateBossBriefData | null): PrivateBossIssueView {
  const source = bossBriefSources(data).find(row => row.source_id === issue.source_id);
  const needsData = issue.id.startsWith('source:') || !source || source.status !== 'connected' || ['stale', 'missing', 'unsupported'].includes(source.data_state);
  const rawTitle = text(issue.title, 240);
  const technicalTitle = /\b(?:pi|ch|po|re|dp|du|txn|cs|sub|in|acct)_[A-Za-z0-9]+\b|\b(?:campaign_id|customer_id|snapshot_id|source_id|item_id)\b|(?:Campaign|广告系列)[\s_-]*\d{5,}|LocalServicesCampaign:SystemGenerated:/i.test(rawTitle);
  const aliases: Record<PrivateSourceId, string> = { gmail: '核对需要处理的邮件', google_ads: '核对广告投放状态', stripe: /争议|dispute/i.test(`${rawTitle} ${issue.summary}`) ? '核对 Stripe 争议回应' : /退款|refund/i.test(`${rawTitle} ${issue.summary}`) ? '核对 Stripe 退款记录' : /提现|payout/i.test(`${rawTitle} ${issue.summary}`) ? '核对 Stripe 提现记录' : '核对 Stripe 款项状态', bofa: '核对银行邮件提醒', bofa_bank: '核对银行流水', manual: '处理个人事项' };
  const verificationTitles: Record<PrivateSourceId, string> = { gmail: '核实邮件来源依据', google_ads: '更新广告数据再判断', stripe: '核实 Stripe 同步记录', bofa: '核实银行提醒来源', bofa_bank: '核实银行同步记录', manual: '核实个人事项记录' };
  const title = needsData ? verificationTitles[issue.source_id] : technicalTitle || !/[\u3400-\u9fff]/.test(rawTitle) ? aliases[issue.source_id] : bossBriefReadableText(rawTitle, 240);
  return {
    title,
    reason: needsData ? source?.data_state === 'stale' ? '来源记录需要更新，当前状态尚未确认。' : '来源覆盖或同步依据不完整，先核实数据再判断。' : bossBriefReadableText(issue.summary) || '系统将这条来源记录标记为需关注，仍需本人核对。',
    nextAction: needsData ? '打开来源，更新并核对记录后再决定。' : bossBriefReadableText(issue.next_action) || '查看原始来源后再决定。',
    kind: needsData ? 'verification' : 'business',
    trust: needsData ? '数据待核实' : issue.source_id === 'bofa' || issue.source_id === 'gmail' ? '内容待本人核对' : source?.data_state === 'partial' ? '依据部分记录' : '依据已同步记录',
  };
}
export function bossBriefConclusion(data: PrivateBossBriefData | null): string {
  const views = bossBriefIssues(data).map(issue => bossBriefIssueView(issue, data));
  const first = views[0];
  if (first?.kind === 'business') return `先${first.title.startsWith('核对') || first.title.startsWith('处理') ? '' : '处理：'}${first.title}。`;
  if (views.length) return '先补齐来源依据，再确认需要处理的事项。';
  const gaps = bossBriefSources(data).some(source => source.status !== 'connected' || ['stale', 'missing', 'unsupported'].includes(source.data_state));
  return gaps ? '已取得的记录中暂无优先事项，未覆盖的来源仍待确认。' : '当前已同步范围内，暂无优先事项。';
}
export function bossBriefTaskDraft(issue: PrivateBossIssue): PrivateBossTaskDraft {
  const source = PRIVATE_BOSS_SOURCE_NAMES[issue.source_id] || '私人工作';
  return { title: text(issue.task_title, 240) || text(issue.title, 240) || '核对私人工作事项', summary: `${source}：${text(issue.title, 240)}\n下一步：${text(issue.next_action) || '核对原始来源后再决定。'}`.slice(0, 2000) };
}
export function bossBriefAINotes(data: PrivateBossBriefData | null): { issue: PrivateBossIssue; explanation: string }[] {
  if (data?.ai?.state !== 'ready') return [];
  const notes = Array.isArray(data.ai.issue_notes) ? data.ai.issue_notes : [];
  return bossBriefIssues(data).flatMap(issue => {
    if (issue.source_id === 'bofa_bank') return [];
    const note = notes.find(value => value?.issue_id === issue.id);
    const explanation = text(note?.explanation, 800);
    return explanation ? [{ issue, explanation }] : [];
  });
}
export function bossBriefAIAction(data: PrivateBossBriefData | null): { issue: PrivateBossIssue; explanation: string } | null {
  const issue = bossBriefIssues(data).find(value => value.source_id !== 'bofa_bank' && Array.isArray(data?.sources) && data.sources.some(source => source?.source_id === value.source_id));
  if (!issue) return null;
  const note = bossBriefAINotes(data).find(value => value.issue.id === issue.id);
  return { issue, explanation: note?.explanation || bossBriefIssueView(issue, data).nextAction };
}
export function bossBriefAIReferences(data: PrivateBossBriefData | null): PrivateBossSource[] {
  if (data?.ai?.state !== 'ready' || !text(data.ai.summary, 1200)) return [];
  const refs = data.ai.source_refs;
  const rows = bossBriefSources(data);
  if (!Array.isArray(refs) || !refs.length || refs.some(id => id === 'bofa_bank' || !sources.includes(id) || !Array.isArray(data.sources) || !data.sources.some(source => source?.source_id === id))) return [];
  return rows.filter(source => refs.includes(source.source_id));
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
