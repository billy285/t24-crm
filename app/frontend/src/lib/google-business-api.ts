import { invokeWithAuth } from './tokenStore';
import type { MediaPublication } from './media-operations-api';
import type { PublicationImage } from './media-publication-images';

export type GbpConnection = { id: number; label: string; active: boolean; needs_reconnect: boolean; connected_at: string | null; last_error: string | null };
export type GbpBinding = {
  id: number; customer_id: number; customer_name: string; connection_id: number; location_name: string;
  title: string; address: string; active: boolean; revision: number;
  lifecycle?: 'active' | 'paused' | 'stopped'; primary_operator_id?: number | null; primary_operator_name?: string | null;
  permissions: { can_read: boolean; can_reply: boolean; can_publish: boolean; can_manage: boolean };
};
export type GbpStatus = { enabled: boolean; configured: boolean; setup_missing: string[]; is_owner: boolean; connections: GbpConnection[]; bindings: GbpBinding[] };
export type GbpOptions = { customers: { id: number; name: string }[]; assignees: { id: number; name: string; eligible_customer_ids: number[] }[] };
export type GbpLocation = { location_name: string; title: string; address: string };
export type GbpLocations = { items: GbpLocation[]; truncated: boolean };
export type GbpGrant = { employee_id: number; name: string; eligible: boolean; can_reply: boolean; can_publish: boolean };
export type GbpGrants = { binding: GbpBinding; employees: GbpGrant[]; revision: number };
export type GbpReview = {
  name: string; reviewer_name: string; rating: string; comment: string; created_at: string | null; updated_at: string | null;
  reply: string | null; reply_updated_at: string | null; reply_state: string | null; version: string; requires_owner_review?: boolean;
};
export type GbpReviews = { items: GbpReview[]; next_page_token: string | null; fetched_at: string };
export type GbpReadyTask = { publication?: MediaPublication | null; timezone?: string; id: number; title: string; content: string; revision: number; material_id: number | null; material_title: string | null; has_public_image: boolean; can_return?: boolean; preview_image_url: string | null; preview_image_path?: string | null; image_version_id?: string | null; image_sha256?: string | null; publication_image?: PublicationImage | null; publish_blocked_reason: string | null };
export type GbpPublicationPayload = {
  topicType?: 'STANDARD' | 'EVENT' | 'OFFER';
  event?: { title?: string; schedule?: { startDate?: { year?: number; month?: number; day?: number }; startTime?: { hours?: number; minutes?: number; seconds?: number; nanos?: number }; endDate?: { year?: number; month?: number; day?: number }; endTime?: { hours?: number; minutes?: number; seconds?: number; nanos?: number } } };
  offer?: { couponCode?: string; redeemOnlineUrl?: string; termsConditions?: string };
  callToAction?: { actionType?: 'BOOK' | 'ORDER' | 'SHOP' | 'LEARN_MORE' | 'SIGN_UP' | 'CALL'; url?: string };
};
export type GbpActionStatus = 'pending' | 'unknown' | 'accepted' | 'succeeded' | 'rejected' | 'failed';
export type GbpAction = {
  id: number; request_id: string; binding_id: number; customer_id: number; kind: 'review_reply' | 'post_publish'; task_id: number | null;
  submitted_image_version_id?: string; submitted_image_sha256?: string; submitted_image_status?: 'ready'|'revoked'|'source_changed'; submitted_image_preview_path?: string|null; submitted_publication_image?: PublicationImage|null;
  status: GbpActionStatus; actor_name: string; created_at: string; updated_at: string;
  publication_payload?: GbpPublicationPayload | null; provider_state: string | null; provider_url: string | null; content: string | null; message: string; can_reconcile: boolean;
};

export const gbpActionLabels: Record<GbpActionStatus, string> = {
  pending: '提交结果待确认', unknown: '结果待确认', accepted: 'Google 处理中', succeeded: 'Google 已确认', rejected: 'Google 未通过', failed: '未提交成功',
};
export function googleReplyBytes(value: string): number { return new TextEncoder().encode(value).byteLength; }

export async function googleBusinessApi<T>(path: string, method: 'GET' | 'POST' | 'PUT' = 'GET', data?: unknown): Promise<T> {
  const response = await invokeWithAuth({ url: `/api/v1/google-business${path}`, method, ...(data === undefined ? {} : { data }) });
  return response.data as T;
}

const positiveId = (value: unknown) => Number.isSafeInteger(value) && Number(value) > 0;
const bool = (value: unknown) => typeof value === 'boolean';
export function verifiedGbpBinding(value: GbpBinding): GbpBinding {
  if (!value || !positiveId(value.id) || !positiveId(value.customer_id) || !positiveId(value.connection_id) || !positiveId(value.revision)
    || typeof value.customer_name !== 'string' || typeof value.title !== 'string' || !bool(value.active) || !value.permissions
    || !['can_read', 'can_reply', 'can_publish', 'can_manage'].every(key => bool(value.permissions[key as keyof GbpBinding['permissions']]))) throw new Error('Google 门店资料返回不完整，请重新读取。');
  return value;
}
export function verifiedGbpStatus(value: GbpStatus): GbpStatus {
  if (!value || !bool(value.enabled) || !bool(value.configured) || !bool(value.is_owner) || !Array.isArray(value.setup_missing)
    || !Array.isArray(value.connections) || !Array.isArray(value.bindings)) throw new Error('Google 连接状态返回不完整，请重新读取。');
  value.bindings.forEach(verifiedGbpBinding);
  if (value.connections.some(row => !positiveId(row.id) || !bool(row.active) || !bool(row.needs_reconnect) || typeof row.label !== 'string')) throw new Error('Google 连接资料返回不完整，请重新读取。');
  return value;
}
export function verifiedGbpAction(value: GbpAction, requestId?: string): GbpAction {
  if (!value || !positiveId(value.id) || !positiveId(value.binding_id) || !positiveId(value.customer_id) || !Object.prototype.hasOwnProperty.call(gbpActionLabels, value.status)
    || !['review_reply', 'post_publish'].includes(value.kind) || typeof value.request_id !== 'string' || (requestId && value.request_id !== requestId)
    || typeof value.message !== 'string' || !bool(value.can_reconcile)) throw new Error('Google 操作结果返回不完整，请按原请求编号重新查询。');
  return value;
}
export function googleAuthorizationUrl(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  try {
    const url = new URL(value);
    return url.origin === 'https://accounts.google.com' && url.pathname === '/o/oauth2/v2/auth' && !url.username && !url.password ? url.href : null;
  } catch { return null; }
}
export function googlePublicUrl(value: string | null): string | null {
  if (!value) return null;
  try {
    const url = new URL(value), host = url.hostname.toLowerCase();
    return url.protocol === 'https:' && !url.username && !url.password && !url.port && (host === 'google.com' || host.endsWith('.google.com') || host === 'g.page') ? url.href : null;
  } catch { return null; }
}
export function googlePreviewImageUrl(value: string | null): string | null {
  if (!value) return null;
  try {
    const url = new URL(value), host = url.hostname.toLowerCase();
    return url.protocol === 'https:' && !url.username && !url.password && !url.port && !url.search && !url.hash && host.includes('.')
      && !host.endsWith('.local') && !host.endsWith('.localhost') && !/^[\d.]+$/.test(host) && !host.startsWith('[') ? url.href : null;
  } catch { return null; }
}
