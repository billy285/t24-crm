import { invokeWithAuth } from './tokenStore';
import { sha256Blob, sourceImageDimensions } from './media-publication-images';
import type { MetaAuthorization, MetaPlatform } from './meta-business-api';

export type MetaOpsCapabilities = { can_publish: boolean; can_reply: boolean; can_read_posts: boolean; can_read_comments: boolean; can_schedule: boolean; blocked_reasons: string[] };
export type MetaOpsBinding = { id: number; customer_id: number; customer_name: string; platform: MetaPlatform; asset_name: string; connection_id: number; revision: number; operations_active: boolean; can_pause: boolean; paused: boolean; capabilities: MetaOpsCapabilities };
export type MetaOpsStatus = { is_owner: boolean; pilot_label: string; write_configured: boolean; setup_missing: string[]; scheduler: { enabled: boolean; activation_from: string | null }; authorization: MetaAuthorization | null; bindings: MetaOpsBinding[] };
export type MetaOpsMedia = { id: string; sha256: string; byte_size: number; width: number; height: number; preview_path: string; created_at: string };
export type MetaOpsDraft = { id: number; binding_id: number; kind: 'post' | 'reply'; title: string; content: string; media_id: string | null; target_ref: string | null; expected_target_version: string | null; status: 'draft' | 'approved'; revision: number; preview_hash: string | null; approved_at: string | null; created_at: string; updated_at: string };
export type MetaOpsPreview = { draft: MetaOpsDraft; preview_hash: string; target: { customer_name: string; platform: MetaPlatform; asset_name: string }; media: MetaOpsMedia | null; warnings: string[]; ready_for_publish: boolean; media_delivery_notice?: string | null; reply_to: { content: string; author_name: string; created_at: string | null; version: string } | null };
export type MetaOpsActionStatus = 'pending' | 'processing' | 'unknown' | 'succeeded' | 'failed';
export type MetaOpsAction = { id: number; binding_id: number; draft_id: number; kind: 'post' | 'reply'; request_id: string; status: MetaOpsActionStatus; revision: number; can_continue: boolean; submitted_draft: { title: string; content: string; media_id: string | null; kind: 'post' | 'reply'; target_ref: string | null; draft_revision: number; preview_hash: string }; media: MetaOpsMedia | null; target: { customer_name: string; platform: MetaPlatform; asset_name: string }; message: string; provider_url?: string | null; created_at: string; updated_at: string };
export type MetaOpsScheduleStatus = 'prepared' | 'scheduled' | 'cancelled' | 'dispatching' | 'blocked' | 'unknown' | 'succeeded' | 'failed' | 'missed';
export type MetaOpsSchedule = { id: number; binding_id: number; draft_id: number; draft_revision: number; planned_at: string; timezone: string; status: MetaOpsScheduleStatus; revision: number; preview_hash: string; submitted_draft: MetaOpsAction['submitted_draft']; media: MetaOpsMedia | null; target: MetaOpsAction['target']; message: string; action_id?: number | null; created_at: string };
export type MetaOpsWorkspace = { binding: MetaOpsBinding; drafts: MetaOpsDraft[]; actions: MetaOpsAction[]; schedules: MetaOpsSchedule[]; media: MetaOpsMedia[] };
export type MetaOpsPost = { target_ref: string; content: string; created_at: string | null; permalink: string | null };
export type MetaOpsComment = { target_ref: string; post_ref: string; content: string; author_name: string; created_at: string | null; version: string };
export type MetaOpsPosts = { items: MetaOpsPost[]; next_cursor: string | null };
export type MetaOpsComments = { items: MetaOpsComment[]; next_cursor: string | null };
export type MetaOpsRequest = { kind: 'draft' | 'action' | 'schedule' | 'media' | 'oauth'; result: unknown };
export const META_OPS_CALLBACK_URI = 'https://t24-crm.com/api/v1/meta-operations/oauth/callback';
export const metaOpsActionLabels: Record<MetaOpsActionStatus, string> = { pending: '提交结果待确认', processing: 'Instagram 素材处理中', unknown: '结果待确认', succeeded: '平台已确认', failed: '未提交成功' };
export const metaOpsScheduleLabels: Record<MetaOpsScheduleStatus, string> = { prepared: '已保存计划 · 尚未启用执行', scheduled: '已排期', cancelled: '已取消', dispatching: '正在提交', blocked: '已暂停', unknown: '结果待确认', succeeded: '平台已确认', failed: '发布未成功', missed: '错过排期' };
const positive = (v: unknown): v is number => Number.isSafeInteger(v) && Number(v) > 0;
const string = (v: unknown): v is string => typeof v === 'string';
const optionalString = (v: unknown) => v == null || string(v);
const boolean = (v: unknown) => typeof v === 'boolean';
const strings = (v: unknown): v is string[] => Array.isArray(v) && v.every(string);
export const META_OPS_REQUIRED_SCOPES = ['pages_show_list', 'pages_read_engagement', 'instagram_basic', 'pages_manage_posts', 'pages_manage_engagement', 'pages_read_user_content', 'instagram_content_publish', 'instagram_manage_comments'];
const operationsScopes = (value: unknown): value is string[] => strings(value) && value.length === META_OPS_REQUIRED_SCOPES.length && new Set(value).size === META_OPS_REQUIRED_SCOPES.length && value.every(scope => META_OPS_REQUIRED_SCOPES.includes(scope));
const opaque = (v: unknown): v is string => string(v) && /^[a-f0-9]{32}$/.test(v);
const hash = (v: unknown): v is string => string(v) && /^[a-f0-9]{64}$/.test(v);
const platform = (v: unknown) => v === 'facebook' || v === 'instagram';
const time = (v: unknown) => string(v) && Number.isFinite(Date.parse(v));
const nullableTime = (v: unknown) => v === null || time(v);
export const metaOpsPreviewPath = (v: unknown, id: string): v is string => string(v) && opaque(id) && v === `/api/v1/meta-operations/media/${id}/preview`;
export async function metaOperationsApi<T>(path: string, method: 'GET' | 'POST' | 'PATCH' = 'GET', data?: unknown): Promise<T> {
  const response = await invokeWithAuth({ url: `/api/v1/meta-operations${path}`, method, ...(data === undefined ? {} : { data }) });
  return response.data as T;
}
export function verifiedMetaOpsBinding(value: MetaOpsBinding): MetaOpsBinding {
  const caps = value?.capabilities;
  if (!value || !positive(value.id) || !positive(value.customer_id) || !positive(value.connection_id) || !positive(value.revision) || !platform(value.platform) || !string(value.customer_name) || !string(value.asset_name) || !boolean(value.operations_active) || !boolean(value.can_pause) || !boolean(value.paused) || value.paused && value.operations_active || value.can_pause && !value.operations_active || !caps || !['can_publish', 'can_reply', 'can_read_posts', 'can_read_comments', 'can_schedule'].every(key => boolean(caps[key as keyof MetaOpsCapabilities])) || !strings(caps.blocked_reasons) || value.paused && (caps.can_publish || caps.can_reply || caps.can_read_posts || caps.can_read_comments || caps.can_schedule) || !value.operations_active && (caps.can_publish || caps.can_reply || caps.can_schedule)) throw new Error('Meta 试点账号与操作范围返回不完整，请重新读取。');
  return value;
}
export function verifiedMetaOpsStatus(value: MetaOpsStatus): MetaOpsStatus {
  if (!value || !boolean(value.is_owner) || !string(value.pilot_label) || !boolean(value.write_configured) || !strings(value.setup_missing) || !value.scheduler || !boolean(value.scheduler.enabled) || !nullableTime(value.scheduler.activation_from) || !Array.isArray(value.bindings)) throw new Error('Meta 试点能力返回不完整，请重新读取。');
  value.bindings.forEach(verifiedMetaOpsBinding);
  if (value.bindings.some(row => !value.write_configured && (row.capabilities.can_publish || row.capabilities.can_reply) || !value.scheduler.enabled && row.capabilities.can_schedule)) throw new Error('Meta 运营能力与授权或排期执行状态不一致。');
  if (!value.is_owner && (value.bindings.length || value.authorization !== null)) throw new Error('当前账号的 Meta 试点范围无法核实。');
  const auth = value.authorization;
  if (auth && (auth.provider !== 'Meta' || auth.token_type !== 'user' || !/^\d{5,40}$/.test(auth.client_id) || !/^\d{5,40}$/.test(auth.config_id) || !/^v\d{1,3}\.\d{1,2}$/.test(auth.graph_version) || auth.redirect_uri !== META_OPS_CALLBACK_URI || !operationsScopes(auth.requested_scopes) || !strings(auth.asset_types) || !string(auth.flow) || !string(auth.purpose) || !string(auth.token_storage))) throw new Error('Meta 运营授权说明无法核实。');
  return value;
}
export function verifiedMetaOpsMedia(value: MetaOpsMedia): MetaOpsMedia {
  if (!value || !opaque(value.id) || !hash(value.sha256) || !positive(value.byte_size) || value.byte_size > 8 * 1024 * 1024 || !positive(value.width) || !positive(value.height) || value.width * value.height > 40_000_000 || !metaOpsPreviewPath(value.preview_path, value.id) || !time(value.created_at)) throw new Error('Meta 固定图片版本返回不完整，请重新读取。');
  return value;
}
export function verifiedMetaOpsDraft(value: MetaOpsDraft, bindingId?: number): MetaOpsDraft {
  if (!value || !positive(value.id) || !positive(value.binding_id) || bindingId !== undefined && value.binding_id !== bindingId || !['post', 'reply'].includes(value.kind) || !string(value.title) || !string(value.content) || !(value.media_id === null || opaque(value.media_id)) || !(value.target_ref === null || opaque(value.target_ref)) || !(value.expected_target_version === null || hash(value.expected_target_version)) || !['draft', 'approved'].includes(value.status) || !positive(value.revision) || !(value.preview_hash === null || hash(value.preview_hash)) || !nullableTime(value.approved_at) || !time(value.created_at) || !time(value.updated_at)) throw new Error('Meta 草稿返回不完整，请重新读取。');
  return value;
}
export function verifiedMetaOpsAction(value: MetaOpsAction, bindingId?: number, requestId?: string): MetaOpsAction {
  if (!value || !positive(value.id) || !positive(value.binding_id) || bindingId !== undefined && value.binding_id !== bindingId || !positive(value.draft_id) || !['post', 'reply'].includes(value.kind) || !string(value.request_id) || requestId !== undefined && value.request_id !== requestId || !(value.status in metaOpsActionLabels) || !positive(value.revision) || !boolean(value.can_continue) || !value.submitted_draft || !string(value.submitted_draft.title) || !string(value.submitted_draft.content) || !['post', 'reply'].includes(value.submitted_draft.kind) || value.submitted_draft.kind !== value.kind || value.can_continue && !['processing', 'pending'].includes(value.status) || !(value.submitted_draft.media_id === null || opaque(value.submitted_draft.media_id)) || !positive(value.submitted_draft.draft_revision) || !hash(value.submitted_draft.preview_hash) || !(value.submitted_draft.target_ref === null || opaque(value.submitted_draft.target_ref)) || !value.target || !platform(value.target.platform) || !string(value.target.customer_name) || !string(value.target.asset_name) || !((value.submitted_draft.media_id === null && value.media === null) || (value.submitted_draft.media_id !== null && value.media !== null && verifiedMetaOpsMedia(value.media).id === value.submitted_draft.media_id)) || !string(value.message) || !optionalString(value.provider_url) || !time(value.created_at) || !time(value.updated_at)) throw new Error('Meta 提交结果返回不完整，请查询原请求。');
  return value;
}
export function verifiedMetaOpsSchedule(value: MetaOpsSchedule, bindingId?: number): MetaOpsSchedule {
  if (!value || !positive(value.id) || !positive(value.binding_id) || bindingId !== undefined && value.binding_id !== bindingId || !positive(value.draft_id) || !positive(value.draft_revision) || !time(value.planned_at) || !string(value.timezone) || !(value.status in metaOpsScheduleLabels) || !positive(value.revision) || !hash(value.preview_hash) || !value.submitted_draft || value.submitted_draft.kind !== 'post' || !string(value.submitted_draft.title) || !string(value.submitted_draft.content) || !(value.submitted_draft.media_id === null || opaque(value.submitted_draft.media_id)) || value.submitted_draft.draft_revision !== value.draft_revision || value.submitted_draft.preview_hash !== value.preview_hash || !value.target || !platform(value.target.platform) || !string(value.target.customer_name) || !string(value.target.asset_name) || !((value.submitted_draft.media_id === null && value.media === null) || (value.submitted_draft.media_id !== null && value.media !== null && verifiedMetaOpsMedia(value.media).id === value.submitted_draft.media_id)) || !string(value.message) || !(value.action_id == null || positive(value.action_id)) || !time(value.created_at)) throw new Error('Meta 排期结果返回不完整，请读取实际工作区。');
  return value;
}
export function verifiedMetaOpsWorkspace(value: MetaOpsWorkspace, bindingId: number): MetaOpsWorkspace {
  if (!value || verifiedMetaOpsBinding(value.binding).id !== bindingId || !Array.isArray(value.drafts) || !Array.isArray(value.actions) || !Array.isArray(value.schedules) || !Array.isArray(value.media)) throw new Error('Meta 工作区返回不完整，请重新读取。');
  value.drafts.forEach(row => verifiedMetaOpsDraft(row, bindingId)); value.actions.forEach(row => verifiedMetaOpsAction(row, bindingId)); value.schedules.forEach(row => verifiedMetaOpsSchedule(row, bindingId)); value.media.forEach(verifiedMetaOpsMedia);
  return value;
}
export function verifiedMetaOpsPreview(value: MetaOpsPreview, draft: MetaOpsDraft, binding: MetaOpsBinding): MetaOpsPreview {
  if (!value || verifiedMetaOpsDraft(value.draft, binding.id).id !== draft.id || value.draft.revision !== draft.revision || value.draft.content !== draft.content || value.draft.title !== draft.title || value.draft.kind !== draft.kind || value.draft.status !== draft.status || value.draft.expected_target_version !== draft.expected_target_version || value.draft.media_id !== draft.media_id || value.draft.target_ref !== draft.target_ref || !hash(value.preview_hash) || !value.target || value.target.platform !== binding.platform || value.target.customer_name !== binding.customer_name || value.target.asset_name !== binding.asset_name || !strings(value.warnings) || !boolean(value.ready_for_publish) || !optionalString(value.media_delivery_notice) || value.media !== null && verifiedMetaOpsMedia(value.media).id !== draft.media_id || draft.media_id !== null && value.media === null || !(value.reply_to === null || value.reply_to && string(value.reply_to.content) && string(value.reply_to.author_name) && nullableTime(value.reply_to.created_at) && hash(value.reply_to.version)) || draft.kind === 'reply' && (!value.reply_to || value.reply_to.version !== draft.expected_target_version)) throw new Error('Meta 当前预览与草稿、账号或图片版本不一致，请重新核对。');
  return value;
}
export function verifiedMetaOpsPosts(value: MetaOpsPosts): MetaOpsPosts {
  if (!value || !Array.isArray(value.items) || !optionalString(value.next_cursor) || value.items.some(row => !opaque(row.target_ref) || !string(row.content) || !nullableTime(row.created_at) || !optionalString(row.permalink))) throw new Error('Meta 帖文清单返回不完整。');
  return value;
}
export function verifiedMetaOpsComments(value: MetaOpsComments, postRef: string): MetaOpsComments {
  if (!value || !Array.isArray(value.items) || !optionalString(value.next_cursor) || value.items.some(row => !opaque(row.target_ref) || row.post_ref !== postRef || !string(row.content) || !string(row.author_name) || !nullableTime(row.created_at) || !hash(row.version))) throw new Error('Meta 评论清单与当前帖文不一致，请重新读取。');
  return value;
}
export function metaOpsPublicUrl(value: string | null | undefined): string | null {
  if (!value) return null;
  try { const url = new URL(value); return url.protocol === 'https:' && !url.username && !url.password && !url.port && ['facebook.com', 'instagram.com'].some(host => url.hostname === host || url.hostname.endsWith(`.${host}`)) ? url.href : null; } catch { return null; }
}
export function metaOpsAuthorizationUrl(value: unknown, authorization: MetaAuthorization | null): string | null {
  if (!string(value) || !authorization || authorization.redirect_uri !== META_OPS_CALLBACK_URI || !operationsScopes(authorization.requested_scopes)) return null;
  try {
    const url = new URL(value), allowed = new Set(['client_id', 'redirect_uri', 'response_type', 'state', 'config_id']), keys = [...url.searchParams.keys()];
    if (url.protocol !== 'https:' || url.hostname !== 'www.facebook.com' || url.port || url.username || url.password || url.hash || url.pathname !== `/${authorization.graph_version}/dialog/oauth` || keys.length !== allowed.size || new Set(keys).size !== keys.length || keys.some(key => !allowed.has(key)) || authorization.token_type !== 'user' || url.searchParams.get('client_id') !== authorization.client_id || url.searchParams.get('config_id') !== authorization.config_id || url.searchParams.get('redirect_uri') !== META_OPS_CALLBACK_URI || url.searchParams.get('response_type') !== 'code' || !/^[A-Za-z0-9_-]{20,1024}$/.test(url.searchParams.get('state') || '')) return null;
    return url.href;
  } catch { return null; }
}
export async function metaOpsImageDataUrl(image: MetaOpsMedia, input: unknown): Promise<string> {
  verifiedMetaOpsMedia(image);
  if (!(input instanceof Blob) || input.size !== image.byte_size || await sha256Blob(input) !== image.sha256) throw new Error('Meta 图片与保存版本不一致，请重新读取。');
  const bytes = new Uint8Array(await input.arrayBuffer()), dimensions = sourceImageDimensions(bytes);
  if (dimensions.kind !== 'jpeg' || dimensions.width !== image.width || dimensions.height !== image.height) throw new Error('Meta 图片格式或尺寸与保存版本不一致。');
  const chunks: string[] = []; for (let offset = 0; offset < bytes.length; offset += 0x8000) chunks.push(String.fromCharCode(...bytes.subarray(offset, offset + 0x8000)));
  return `data:image/jpeg;base64,${btoa(chunks.join(''))}`;
}
