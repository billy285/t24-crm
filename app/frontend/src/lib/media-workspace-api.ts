import { invokeWithAuth } from './tokenStore';
import { verifiedMediaTask, type MediaTask } from './media-operations-api';

export type WorkspaceView = 'overview' | 'calendar' | 'review' | 'inbox';
export type WorkspacePlatform = 'google_business' | 'facebook' | 'instagram' | 'tiktok' | 'xiaohongshu' | 'other';
export type WorkspaceSource = { key: 'tasks' | 'google' | 'meta' | 'monthly'; state: 'ready' | 'missing' | 'locked' | 'error'; message: string };
export type WorkspaceStatusFilter = 'all' | 'attention' | 'review' | 'unassigned' | 'no_schedule';
export type WorkspaceIssue = { code: string; label: string; severity: 'high' | 'medium' | 'info' };
export type WorkspacePortfolioSummary = Record<'merchants' | 'attention' | 'review' | 'unassigned' | 'no_schedule', number>;
export type WorkspaceOperator = { id: number; name: string; merchants: number; tasks: number; in_review: number; overdue: number; blocked: number; completed: number; scheduled: number };
export type WorkspacePortfolio = { summary: WorkspacePortfolioSummary; exceptions: WorkspaceMerchant[]; operators: WorkspaceOperator[]; observed_at: string; sources_complete: boolean; filtered_merchants?: number };
export type WorkspaceCalendarDay = { date: string; total: number; scheduled: number; suggested: number; task_due: number; blocked: number };
export type WorkspaceReviewGroup = { customer_id: number; name: string; month: string; total: number; in_review: number; platforms: string[] };
export type WorkspaceReadinessCheck = { key: string; label: string; state: 'ready' | 'missing' | 'blocked' | 'unknown' };
export type WorkspaceQueueAction = { kind: 'monthly' | 'materials' | 'rules' | 'accounts' | 'content' | 'review'; label: string; run_id?: number };
export type WorkspaceMerchantQueue = { month: string | null; target: number | null; prepared: number; in_review: number; scheduled: number; published: number; readiness: 'ready' | 'needs_setup' | 'blocked' | 'unknown' | 'not_applicable'; checks: WorkspaceReadinessCheck[]; next_action: WorkspaceQueueAction | null; can_prepare_monthly: boolean; basis: 'monthly_plan' | 'authorized_records' | 'unknown' };
export type WorkspaceMerchant = { id: number; name: string; platforms: string[]; can_create: boolean; can_edit: boolean; region?: string | null; industry?: string | null; timezone?: string | null; primary_operator_name?: string | null; primary_operator_id?: number | null; in_review?: number; blocked?: number; overdue?: number; scheduled?: number; next_publish_at?: string | null; next_publish_timezone?: string | null; next_7_days_count?: number | null; coverage_state?: 'scheduled' | 'none_saved' | 'unknown' | 'not_applicable' | 'not_connected'; operating_state?: 'active' | 'not_cooperating' | 'pending_connection' | 'unknown'; assignment_state?: 'assigned' | 'unassigned' | 'not_applicable'; cooperation_status?: string | null; data_state?: 'complete' | 'partial'; issues?: WorkspaceIssue[]; observed_at?: string; work_queue?: WorkspaceMerchantQueue };
export type WorkspacePage<T> = { items: T[]; total: number; next_cursor: string | null; partial: boolean; sources: WorkspaceSource[]; observed_at: string; sources_complete?: boolean; has_more?: boolean; summary?: WorkspacePortfolioSummary; operators?: WorkspaceOperator[] };
export type WorkspaceRow = { id: string; kind: 'task' | 'google_schedule' | 'google_reply_draft' | 'google_action' | 'meta_draft' | 'meta_schedule' | 'meta_comment' | 'meta_post' | 'meta_action' | 'monthly_run' | 'monthly_item'; customer_id: number; customer_name: string; platform: string; title: string; content: string; status: string; at: string | null; time_basis: 'task_due' | 'scheduled_publish' | 'platform_created' | 'record_created' | 'proposed_publish'; timezone: string | null; revision: number | null; version: string | null; source_id: number | string; binding_id: number | null; binding_revision: number | null; review_eligible: boolean; account_label?: string | null; navigation: { workspace: 'tasks' | 'google' | 'meta' | 'monthly'; run_id?: number; task_id?: number; binding_id?: number; draft_id?: number | string; schedule_id?: number; action_id?: number; target_ref?: string; post_ref?: string } };
export type WorkspaceSummary = Record<'tasks' | 'drafts' | 'in_review' | 'ready' | 'scheduled' | 'blocked' | 'unknown' | 'inbox' | 'review_candidates', number>;
export type WorkspaceProjection = Omit<WorkspacePage<WorkspaceRow>, 'summary'> & { scope: { customer_id: number | null; platform: string | null; view: WorkspaceView; status?: WorkspaceStatusFilter; operator_id?: number | null }; range: { start: string; end: string }; summary: WorkspaceSummary; portfolio?: WorkspacePortfolio; calendar_days?: WorkspaceCalendarDay[]; review_groups?: WorkspaceReviewGroup[]; capabilities: { is_owner: boolean; meta_owner_only: true } };
export type WorkspaceQuery = { customerId: number | null; platform: string | null; view: WorkspaceView; start: string; end: string; cursor?: string | null; limit?: number; status?: WorkspaceStatusFilter; operatorId?: number | null };
export const workspacePlatformLabels: Record<string, string> = { google_business: 'Google 商家', facebook: 'Facebook', instagram: 'Instagram', tiktok: 'TikTok', xiaohongshu: '小红书', other: '其他平台' };
const kinds = new Set(['task', 'google_schedule', 'google_reply_draft', 'google_action', 'meta_draft', 'meta_schedule', 'meta_comment', 'meta_post', 'meta_action', 'monthly_run', 'monthly_item']);
const positive = (value: unknown): value is number => Number.isSafeInteger(value) && Number(value) > 0;
const count = (value: unknown): value is number => Number.isSafeInteger(value) && Number(value) >= 0;
const text = (value: unknown): value is string => typeof value === 'string';
const optionalText = (value: unknown) => value == null || text(value);
const instant = (value: unknown): value is string => text(value) && /(?:Z|[+-]\d{2}:\d{2})$/.test(value) && Number.isFinite(Date.parse(value));
const optionalId = (value: unknown) => value == null || positive(value);
function requireValue(ok: unknown, message = '运营工作区返回不完整，请重新读取。'): asserts ok { if (!ok) throw new Error(message); }
export const workspaceStatusOptions: { value: WorkspaceStatusFilter; label: string }[] = [{ value: 'all', label: '全部商家' }, { value: 'attention', label: '需要处理' }, { value: 'review', label: '待审核' }, { value: 'unassigned', label: '未分配主要运营' }, { value: 'no_schedule', label: '未来7天暂无排期' }];
function verifiedIssue(value: WorkspaceIssue) { return value && text(value.code) && text(value.label) && ['high', 'medium', 'info'].includes(value.severity); }
function verifiedSummary(value: WorkspacePortfolioSummary) { return value && ['merchants', 'attention', 'review', 'unassigned', 'no_schedule'].every(key => count(value[key as keyof WorkspacePortfolioSummary])); }
function verifiedOperator(value: WorkspaceOperator) { return value && positive(value.id) && text(value.name) && ['merchants', 'tasks', 'in_review', 'overdue', 'blocked', 'completed', 'scheduled'].every(key => count(value[key as keyof WorkspaceOperator])); }
function verifiedQueue(value: WorkspaceMerchantQueue) {
  return value && (value.month === null || /^\d{4}-(0[1-9]|1[0-2])$/.test(value.month)) && (value.target === null || count(value.target)) && ['prepared', 'in_review', 'scheduled', 'published'].every(key => count(value[key as keyof WorkspaceMerchantQueue])) && ['ready', 'needs_setup', 'blocked', 'unknown', 'not_applicable'].includes(value.readiness) && typeof value.can_prepare_monthly === 'boolean' && ['monthly_plan', 'authorized_records', 'unknown'].includes(value.basis) && Array.isArray(value.checks) && value.checks.every(check => check && text(check.key) && text(check.label) && ['ready', 'missing', 'blocked', 'unknown'].includes(check.state)) && new Set(value.checks.map(check => check.key)).size === value.checks.length && (value.next_action === null || value.next_action && ['monthly', 'materials', 'rules', 'accounts', 'content', 'review'].includes(value.next_action.kind) && text(value.next_action.label) && (value.next_action.run_id === undefined || positive(value.next_action.run_id))) && (value.next_action?.kind !== 'monthly' || value.can_prepare_monthly);
}
function verifiedMerchant(row: WorkspaceMerchant) {
  return row && positive(row.id) && text(row.name) && Array.isArray(row.platforms) && row.platforms.every(text) && typeof row.can_create === 'boolean' && typeof row.can_edit === 'boolean' && ['region', 'industry', 'timezone', 'primary_operator_name'].every(key => optionalText(row[key as keyof WorkspaceMerchant])) && optionalId(row.primary_operator_id) && ['in_review', 'blocked', 'overdue', 'scheduled', 'next_7_days_count'].every(key => row[key as keyof WorkspaceMerchant] === undefined || key === 'next_7_days_count' && row[key] === null || count(row[key as keyof WorkspaceMerchant])) && (row.next_publish_at === undefined || row.next_publish_at === null || instant(row.next_publish_at)) && (row.coverage_state === undefined || ['scheduled', 'none_saved', 'unknown', 'not_applicable', 'not_connected'].includes(row.coverage_state)) && (row.operating_state === undefined || ['active', 'not_cooperating', 'pending_connection', 'unknown'].includes(row.operating_state)) && (row.assignment_state === undefined || ['assigned', 'unassigned', 'not_applicable'].includes(row.assignment_state)) && optionalText(row.cooperation_status) && optionalText(row.next_publish_timezone) && (row.data_state === undefined || ['complete', 'partial'].includes(row.data_state)) && (row.issues === undefined || Array.isArray(row.issues) && row.issues.every(verifiedIssue)) && (row.observed_at === undefined || instant(row.observed_at)) && (row.work_queue === undefined || verifiedQueue(row.work_queue));
}
function verifiedPage<T>(value: Omit<WorkspacePage<T>, 'summary'>): Omit<WorkspacePage<T>, 'summary'> {
  requireValue(value && Array.isArray(value.items) && value.items.length <= 100 && count(value.total) && value.total >= value.items.length && (value.next_cursor === null || text(value.next_cursor)) && typeof value.partial === 'boolean' && instant(value.observed_at) && Array.isArray(value.sources) && value.sources.length <= 4);
  requireValue(value.sources.every(row => row && ['tasks', 'google', 'meta', 'monthly'].includes(row.key) && ['ready', 'missing', 'locked', 'error'].includes(row.state) && text(row.message)) && new Set(value.sources.map(row => row.key)).size === value.sources.length);
  requireValue((value.sources_complete === undefined || typeof value.sources_complete === 'boolean') && (value.has_more === undefined || typeof value.has_more === 'boolean') && (value.operators === undefined || Array.isArray(value.operators) && value.operators.every(verifiedOperator)));
  return value;
}
export function verifiedWorkspaceMerchants(value: WorkspacePage<WorkspaceMerchant>): WorkspacePage<WorkspaceMerchant> {
  verifiedPage(value);
  requireValue(value.items.every(verifiedMerchant) && new Set(value.items.map(row => row.id)).size === value.items.length && (value.summary === undefined || verifiedSummary(value.summary)));
  return value;
}
export function verifiedWorkspaceProjection(value: WorkspaceProjection, expected: WorkspaceQuery): WorkspaceProjection {
  verifiedPage(value);
  requireValue(value.scope && value.scope.customer_id === expected.customerId && value.scope.platform === expected.platform && value.scope.view === expected.view && value.range && instant(value.range.start) && instant(value.range.end) && Date.parse(value.range.start) === Date.parse(expected.start) && Date.parse(value.range.end) === Date.parse(expected.end), '运营工作区与当前商家、平台或日期范围不一致，请重新读取。');
  requireValue((value.scope.status ?? 'all') === (expected.status ?? 'all') && (value.scope.operator_id ?? null) === (expected.operatorId ?? null), '当前筛选范围已变化，请重新读取。');
  if (value.portfolio !== undefined) requireValue(verifiedSummary(value.portfolio.summary) && (value.portfolio.filtered_merchants === undefined || count(value.portfolio.filtered_merchants)) && Array.isArray(value.portfolio.exceptions) && value.portfolio.exceptions.every(verifiedMerchant) && value.portfolio.exceptions.every(row => expected.customerId === null || row.id === expected.customerId) && Array.isArray(value.portfolio.operators) && value.portfolio.operators.every(verifiedOperator) && instant(value.portfolio.observed_at) && typeof value.portfolio.sources_complete === 'boolean');
  if (value.calendar_days !== undefined) requireValue(Array.isArray(value.calendar_days) && value.calendar_days.every(day => day && /^\d{4}-\d{2}-\d{2}$/.test(day.date) && ['total', 'scheduled', 'suggested', 'task_due', 'blocked'].every(key => count(day[key as keyof WorkspaceCalendarDay]))) && new Set(value.calendar_days.map(day => day.date)).size === value.calendar_days.length);
  if (value.review_groups !== undefined) requireValue(Array.isArray(value.review_groups) && value.review_groups.every(group => group && positive(group.customer_id) && (expected.customerId === null || group.customer_id === expected.customerId) && text(group.name) && /^\d{4}-(0[1-9]|1[0-2])$/.test(group.month) && count(group.total) && count(group.in_review) && group.in_review <= group.total && Array.isArray(group.platforms) && group.platforms.every(text)));
  requireValue(value.capabilities && typeof value.capabilities.is_owner === 'boolean' && value.capabilities.meta_owner_only === true && value.summary && ['tasks', 'drafts', 'in_review', 'ready', 'scheduled', 'blocked', 'unknown', 'inbox', 'review_candidates'].every(key => count(value.summary[key as keyof WorkspaceSummary])));
  requireValue(value.items.every(row => row && text(row.id) && kinds.has(row.kind) && positive(row.customer_id) && (expected.customerId === null || row.customer_id === expected.customerId) && text(row.customer_name) && text(row.platform) && (expected.platform === null || row.platform === expected.platform) && text(row.title) && text(row.content) && text(row.status) && (row.at === null || instant(row.at)) && ['task_due', 'scheduled_publish', 'platform_created', 'record_created', 'proposed_publish'].includes(row.time_basis) && optionalText(row.timezone) && optionalId(row.revision) && optionalText(row.version) && (positive(row.source_id) || text(row.source_id)) && optionalId(row.binding_id) && optionalId(row.binding_revision) && typeof row.review_eligible === 'boolean' && optionalText(row.account_label) && row.navigation && ['tasks', 'google', 'meta', 'monthly'].includes(row.navigation.workspace) && Object.entries(row.navigation).every(([key, v]) => ['workspace', 'target_ref', 'post_ref'].includes(key) ? text(v) : key === 'draft_id' ? positive(v) || text(v) : ['task_id', 'binding_id', 'schedule_id', 'action_id', 'run_id'].includes(key) && positive(v)) && (!row.kind.startsWith('meta_') || value.capabilities.is_owner) && (!row.kind.startsWith('monthly_') ? row.navigation.workspace !== 'monthly' : value.capabilities.is_owner && row.platform === 'google_business' && row.navigation.workspace === 'monthly' && positive(row.navigation.run_id) && !row.review_eligible && (row.kind !== 'monthly_run' || row.source_id === row.navigation.run_id) && (row.kind !== 'monthly_item' || row.time_basis === 'proposed_publish')) && (!row.review_eligible || row.kind === 'task' && row.status === 'in_review' && value.capabilities.is_owner)), '运营记录超出当前范围或操作权限，请重新读取。');
  requireValue(new Set(value.items.map(row => row.id)).size === value.items.length);
  return value;
}
export function workspaceQueryString(query: WorkspaceQuery): string {
  const params = new URLSearchParams({ view: query.view, start: query.start, end: query.end, limit: String(query.limit || 20) });
  if (query.customerId !== null) params.set('customer_id', String(query.customerId));
  if (query.platform !== null) params.set('platform', query.platform);
  if (query.cursor) params.set('cursor', query.cursor);
  if (query.status && query.status !== 'all') params.set('status', query.status);
  if (query.operatorId) params.set('operator_id', String(query.operatorId));
  return params.toString();
}
export async function mediaWorkspaceGet<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await invokeWithAuth({ url: `/api/v1/media-workspace${path}`, method: 'GET', ...(signal ? { options: { signal } } : {}) });
  return response.data as T;
}
export function verifiedReviewTask(value: MediaTask, row: WorkspaceRow): MediaTask {
  const task = verifiedMediaTask(value, row.navigation.task_id || Number(row.source_id));
  requireValue(row.kind === 'task' && row.review_eligible && task.customer_id === row.customer_id && task.platform === row.platform && task.revision === row.revision && task.status === 'in_review' && task.permissions.can_review && task.title === row.title && task.content === row.content, '任务内容、版本、客户或审核权限已变化，请重新选择后核对。');
  requireValue((!task.image_version_id || task.publication_image?.status === 'ready') && (!task.material_id || !!task.image_version_id && task.publication_image?.id === task.image_version_id), '此任务的素材需要逐项核对，请打开原任务完成审核。');
  return task;
}
export function workspaceDateKey(value: string, zone = 'Asia/Shanghai'): string {
  if (!instant(value)) return '';
  try { const parts = new Intl.DateTimeFormat('en-CA', { timeZone: zone, year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(new Date(value)); const get = (type: string) => parts.find(row => row.type === type)?.value || ''; return `${get('year')}-${get('month')}-${get('day')}`; } catch { return ''; }
}
export function workspaceRange(start: string, end: string): { start: string; end: string } {
  requireValue(/^\d{4}-\d{2}-\d{2}$/.test(start) && /^\d{4}-\d{2}-\d{2}$/.test(end), '请选择完整日期范围。');
  const from = Date.parse(`${start}T00:00:00+08:00`), through = Date.parse(`${end}T00:00:00+08:00`);
  requireValue(Number.isFinite(from) && Number.isFinite(through) && through >= from && through - from < 62 * 86400000 && workspaceDateKey(new Date(from).toISOString()) === start && workspaceDateKey(new Date(through).toISOString()) === end, '请选择不超过62天的有效日期范围。');
  return { start: new Date(from).toISOString(), end: new Date(through + 86400000).toISOString() };
}
