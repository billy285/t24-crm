import { invokeWithAuth } from './tokenStore';
import type { PublicationImage } from './media-publication-images';

export type MediaStatus = 'draft' | 'in_review' | 'ready' | 'completed' | 'blocked';
export type MediaAction = 'submit' | 'approve' | 'return' | 'complete' | 'block' | 'resume';
export type MediaPublication = {
  topic_type: 'STANDARD' | 'EVENT' | 'OFFER';
  event?: { title: string; start_at: string; end_at: string } | null;
  offer?: { coupon_code?: string | null; redeem_online_url?: string | null; terms_conditions?: string | null } | null;
  call_to_action?: { action_type: 'BOOK' | 'ORDER' | 'SHOP' | 'LEARN_MORE' | 'SIGN_UP' | 'CALL'; url?: string | null } | null;
};
export type MediaMaterial = { id: number; title: string; material_type: string; content_type?: string | null; source_type?: string | null; has_private_file?: boolean };
export type MediaCustomer = { id: number; name: string; can_write: boolean; can_prepare_images?: boolean; services: { id: number; name: string }[]; materials: MediaMaterial[] };
export type MediaOptions = { customers: MediaCustomer[]; assignees: { id: number; name: string; eligible_customer_ids?: number[] }[]; platforms: { value: string; label: string }[] };
export type MediaEvent = { id: number; action: string; actor_name: string; created_at: string; note?: string | null };
export type MediaTask = {
  id: number; customer_id: number; customer_name: string; service_progress_id?: number | null;
  title: string; platform: string; status: MediaStatus; due_at: string; timezone: string;
  assignee_id: number; assignee_name: string; content: string; material_id?: number | null; material_title?: string | null;
  publication?: MediaPublication | null;
  image_version_id?: string | null; publication_image?: PublicationImage | null;
  proof_url?: string | null; proof_material_id?: number | null; review_note?: string | null; block_reason?: string | null;
  revision: number; created_at: string; updated_at: string; completed_at?: string | null; events?: MediaEvent[];
  permissions: { can_edit: boolean; can_submit: boolean; can_review: boolean; can_return?: boolean; can_complete: boolean; can_block: boolean; can_resume: boolean };
};
export type MediaSummary = Record<MediaStatus | 'overdue', number>;
export type MediaList = { items: MediaTask[]; total: number; skip: number; limit: number; summary: MediaSummary; capabilities: { can_create: boolean; is_owner: boolean } };

export const mediaStatusLabels: Record<MediaStatus, string> = { draft: '待准备', in_review: '待审核', ready: '待发布', completed: '已完成', blocked: '需处理' };
export const mediaActionLabels: Record<MediaAction | 'create' | 'update' | 'edit', string> = { create: '创建任务', update: '修改草稿', edit: '修改草稿', submit: '提交审核', approve: '审核通过', return: '退回修改', complete: '确认已发布', block: '记录异常', resume: '恢复处理' };
export const mediaTimezones = [
  { value: 'Asia/Shanghai', label: '北京时间 · 上海 / 香港' },
  { value: 'America/Los_Angeles', label: '美国西部 · 洛杉矶' },
  { value: 'America/Denver', label: '美国山地 · 丹佛' },
  { value: 'America/Chicago', label: '美国中部 · 芝加哥' },
  { value: 'America/New_York', label: '美国东部 · 纽约' },
  { value: 'America/Phoenix', label: '美国亚利桑那 · 凤凰城' },
  { value: 'Pacific/Honolulu', label: '美国夏威夷 · 檀香山' },
];

export async function mediaOperationsApi<T>(path = '', method: 'GET' | 'POST' | 'PUT' = 'GET', data?: unknown): Promise<T> {
  const response = await invokeWithAuth({ url: `/api/v1/media-operations${path}`, method, ...(data === undefined ? {} : { data }) });
  return response.data as T;
}

export function mediaRequestId(): string {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  const bytes = new Uint8Array(16); globalThis.crypto.getRandomValues(bytes);
  bytes[6] = (bytes[6] & 15) | 64; bytes[8] = (bytes[8] & 63) | 128;
  const hex = [...bytes].map(value => value.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

export function mediaErrorStatus(error: unknown): number | undefined {
  const value = error as { response?: { status?: number }; status?: number; data?: { status?: number } };
  return value?.response?.status || value?.status || value?.data?.status;
}
export function mediaError(error: unknown, fallback = '暂时无法读取，请重试。'): string {
  const value = error as { response?: { data?: { detail?: unknown } }; data?: { detail?: unknown }; message?: string };
  const detail = value?.response?.data?.detail || value?.data?.detail;
  if (typeof detail === 'string' && detail.trim()) return detail;
  if (mediaErrorStatus(error) === 409) return '任务已被更新，请重新读取后再操作。';
  if ([401, 403, 404].includes(mediaErrorStatus(error) || 0)) return '当前任务或客户授权已不可用，请重新读取。';
  return fallback;
}

export function verifiedMediaTask(item: MediaTask, expectedId?: number): MediaTask {
  if (!item || !Number.isSafeInteger(item.id) || item.id < 1 || (expectedId && item.id !== expectedId) || !Number.isSafeInteger(item.revision) || item.revision < 1 || !Object.prototype.hasOwnProperty.call(mediaStatusLabels, item.status) || !item.permissions || !Number.isSafeInteger(item.customer_id)) throw new Error('任务返回不完整，请重新读取。');
  return item;
}

function localParts(value: Date, timezone: string): string {
  const parts = new Intl.DateTimeFormat('en-CA', { timeZone: timezone, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).formatToParts(value);
  const get = (type: Intl.DateTimeFormatPartTypes) => parts.find(part => part.type === type)?.value || '';
  return `${get('year')}-${get('month')}-${get('day')}T${get('hour')}:${get('minute')}`;
}

export function mediaUtcToLocal(value: string, timezone: string): string {
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return '';
  try { return localParts(date, timezone); } catch { return ''; }
}

/** Interpret a wall-clock input in its selected IANA zone, never the browser zone.
 * A repeated DST hour requires a different explicit time; no silent offset choice.
 */
export function mediaLocalToUtc(value: string, timezone: string): string {
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(value)) throw new Error('请填写完整的计划日期和时间。');
  const wall = Date.parse(`${value}:00Z`);
  if (!Number.isFinite(wall) || new Date(wall).toISOString().slice(0, 16) !== value) throw new Error('计划日期或时间无效。');
  try { new Intl.DateTimeFormat('en', { timeZone: timezone }).format(new Date(wall)); } catch { throw new Error('请选择有效的商家时区。'); }
  const candidates: number[] = [];
  // All supported business zones use quarter-hour offsets. Matching the actual
  // formatter also detects gaps and repeated hours at daylight-saving changes.
  for (let offset = -14 * 60; offset <= 14 * 60; offset += 15) {
    const instant = wall - offset * 60_000;
    if (localParts(new Date(instant), timezone) === value) candidates.push(instant);
  }
  if (!candidates.length) throw new Error('该时区正处于夏令时跳时，这个时间不存在，请换一个时间。');
  if (candidates.length > 1) throw new Error('该时区夏令时结束时，这个时间会出现两次，请选择重复时段之外的时间。');
  return new Date(candidates[0]).toISOString();
}

export function mediaScheduleLabel(value: string, timezone: string): string {
  const local = mediaUtcToLocal(value, timezone);
  return local ? `${local.slice(5).replace('T', ' ')} · ${timezone}` : '时间待核对';
}

export function mediaSafeProofUrl(value?: string | null): string | null {
  if (!value) return null;
  try { const url = new URL(value); return url.protocol === 'https:' && !url.username && !url.password ? url.href : null; } catch { return null; }
}
