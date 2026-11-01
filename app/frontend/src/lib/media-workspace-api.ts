import { invokeWithAuth } from './tokenStore';
import { verifiedMediaTask, type MediaTask } from './media-operations-api';

export type WorkspaceView = 'overview' | 'calendar' | 'review' | 'inbox';
export type WorkspacePlatform = 'google_business' | 'facebook' | 'instagram' | 'tiktok' | 'xiaohongshu' | 'other';
export type WorkspaceSource = { key: 'tasks' | 'google' | 'meta' | 'monthly'; state: 'ready' | 'missing' | 'locked' | 'error'; message: string };
export type WorkspaceMerchant = { id: number; name: string; platforms: string[]; can_create: boolean; can_edit: boolean; region?: string | null; industry?: string | null; timezone?: string | null; primary_operator_name?: string | null };
export type WorkspacePage<T> = { items: T[]; total: number; next_cursor: string | null; partial: boolean; sources: WorkspaceSource[]; observed_at: string };
export type WorkspaceRow = { id: string; kind: 'task' | 'google_schedule' | 'google_reply_draft' | 'google_action' | 'meta_draft' | 'meta_schedule' | 'meta_comment' | 'meta_post' | 'meta_action' | 'monthly_run' | 'monthly_item'; customer_id: number; customer_name: string; platform: string; title: string; content: string; status: string; at: string | null; time_basis: 'task_due' | 'scheduled_publish' | 'platform_created' | 'record_created' | 'proposed_publish'; timezone: string | null; revision: number | null; version: string | null; source_id: number | string; binding_id: number | null; binding_revision: number | null; review_eligible: boolean; account_label?: string | null; navigation: { workspace: 'tasks' | 'google' | 'meta' | 'monthly'; run_id?: number; task_id?: number; binding_id?: number; draft_id?: number | string; schedule_id?: number; action_id?: number; target_ref?: string; post_ref?: string } };
export type WorkspaceSummary = Record<'tasks' | 'drafts' | 'in_review' | 'ready' | 'scheduled' | 'blocked' | 'unknown' | 'inbox' | 'review_candidates', number>;
export type WorkspaceProjection = WorkspacePage<WorkspaceRow> & { scope: { customer_id: number | null; platform: string | null; view: WorkspaceView }; range: { start: string; end: string }; summary: WorkspaceSummary; capabilities: { is_owner: boolean; meta_owner_only: true } };
export type WorkspaceQuery = { customerId: number | null; platform: string | null; view: WorkspaceView; start: string; end: string; cursor?: string | null; limit?: number };
export const workspacePlatformLabels: Record<string, string> = { google_business: 'Google 商家', facebook: 'Facebook', instagram: 'Instagram', tiktok: 'TikTok', xiaohongshu: '小红书', other: '其他平台' };
const kinds = new Set(['task', 'google_schedule', 'google_reply_draft', 'google_action', 'meta_draft', 'meta_schedule', 'meta_comment', 'meta_post', 'meta_action', 'monthly_run', 'monthly_item']);
const positive = (value: unknown): value is number => Number.isSafeInteger(value) && Number(value) > 0;
const count = (value: unknown): value is number => Number.isSafeInteger(value) && Number(value) >= 0;
const text = (value: unknown): value is string => typeof value === 'string';
const optionalText = (value: unknown) => value == null || text(value);
const instant = (value: unknown): value is string => text(value) && /(?:Z|[+-]\d{2}:\d{2})$/.test(value) && Number.isFinite(Date.parse(value));
const optionalId = (value: unknown) => value == null || positive(value);
function requireValue(ok: unknown, message = '运营工作区返回不完整，请重新读取。'): asserts ok { if (!ok) throw new Error(message); }
function verifiedPage<T>(value: WorkspacePage<T>): WorkspacePage<T> {
  requireValue(value && Array.isArray(value.items) && value.items.length <= 100 && count(value.total) && value.total >= value.items.length && (value.next_cursor === null || text(value.next_cursor)) && typeof value.partial === 'boolean' && instant(value.observed_at) && Array.isArray(value.sources) && value.sources.length <= 4);
  requireValue(value.sources.every(row => row && ['tasks', 'google', 'meta', 'monthly'].includes(row.key) && ['ready', 'missing', 'locked', 'error'].includes(row.state) && text(row.message)) && new Set(value.sources.map(row => row.key)).size === value.sources.length);
  return value;
}
export function verifiedWorkspaceMerchants(value: WorkspacePage<WorkspaceMerchant>): WorkspacePage<WorkspaceMerchant> {
  verifiedPage(value);
  requireValue(value.items.every(row => row && positive(row.id) && text(row.name) && Array.isArray(row.platforms) && row.platforms.every(text) && typeof row.can_create === 'boolean' && typeof row.can_edit === 'boolean' && ['region', 'industry', 'timezone', 'primary_operator_name'].every(key => optionalText(row[key as keyof WorkspaceMerchant]))) && new Set(value.items.map(row => row.id)).size === value.items.length);
  return value;
}
export function verifiedWorkspaceProjection(value: WorkspaceProjection, expected: WorkspaceQuery): WorkspaceProjection {
  verifiedPage(value);
  requireValue(value.scope && value.scope.customer_id === expected.customerId && value.scope.platform === expected.platform && value.scope.view === expected.view && value.range && instant(value.range.start) && instant(value.range.end) && Date.parse(value.range.start) === Date.parse(expected.start) && Date.parse(value.range.end) === Date.parse(expected.end), '运营工作区与当前商家、平台或日期范围不一致，请重新读取。');
  requireValue(value.capabilities && typeof value.capabilities.is_owner === 'boolean' && value.capabilities.meta_owner_only === true && value.summary && ['tasks', 'drafts', 'in_review', 'ready', 'scheduled', 'blocked', 'unknown', 'inbox', 'review_candidates'].every(key => count(value.summary[key as keyof WorkspaceSummary])));
  requireValue(value.items.every(row => row && text(row.id) && kinds.has(row.kind) && positive(row.customer_id) && (expected.customerId === null || row.customer_id === expected.customerId) && text(row.customer_name) && text(row.platform) && (expected.platform === null || row.platform === expected.platform) && text(row.title) && text(row.content) && text(row.status) && (row.at === null || instant(row.at)) && ['task_due', 'scheduled_publish', 'platform_created', 'record_created', 'proposed_publish'].includes(row.time_basis) && optionalText(row.timezone) && optionalId(row.revision) && optionalText(row.version) && (positive(row.source_id) || text(row.source_id)) && optionalId(row.binding_id) && optionalId(row.binding_revision) && typeof row.review_eligible === 'boolean' && optionalText(row.account_label) && row.navigation && ['tasks', 'google', 'meta', 'monthly'].includes(row.navigation.workspace) && Object.entries(row.navigation).every(([key, v]) => ['workspace', 'target_ref', 'post_ref'].includes(key) ? text(v) : key === 'draft_id' ? positive(v) || text(v) : ['task_id', 'binding_id', 'schedule_id', 'action_id', 'run_id'].includes(key) && positive(v)) && (!row.kind.startsWith('meta_') || value.capabilities.is_owner) && (!row.kind.startsWith('monthly_') ? row.navigation.workspace !== 'monthly' : value.capabilities.is_owner && row.customer_id === 20 && row.platform === 'google_business' && row.navigation.workspace === 'monthly' && positive(row.navigation.run_id) && !row.review_eligible && (row.kind !== 'monthly_run' || row.source_id === row.navigation.run_id) && (row.kind !== 'monthly_item' || row.time_basis === 'proposed_publish')) && (!row.review_eligible || row.kind === 'task' && row.status === 'in_review' && value.capabilities.is_owner)), '运营记录超出当前范围或操作权限，请重新读取。');
  requireValue(new Set(value.items.map(row => row.id)).size === value.items.length);
  return value;
}
export function workspaceQueryString(query: WorkspaceQuery): string {
  const params = new URLSearchParams({ view: query.view, start: query.start, end: query.end, limit: String(query.limit || 20) });
  if (query.customerId !== null) params.set('customer_id', String(query.customerId));
  if (query.platform !== null) params.set('platform', query.platform);
  if (query.cursor) params.set('cursor', query.cursor);
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
