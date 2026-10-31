import { mediaLocalToUtc, mediaUtcToLocal, type MediaPublication } from '@/lib/media-operations-api';

export type PublicationForm = { topic_type: 'STANDARD' | 'EVENT' | 'OFFER'; event_title: string; event_start: string; event_end: string; coupon_code: string; redeem_online_url: string; terms_conditions: string; action_type: string; action_url: string };
export const publicationTopicLabels = { STANDARD: '普通图文', EVENT: '活动', OFFER: '优惠' };
export const publicationActionLabels: Record<string, string> = { BOOK: '预约', ORDER: '下单', SHOP: '购买', LEARN_MORE: '了解更多', SIGN_UP: '注册', CALL: '致电门店' };
export const blankPublicationForm = (): PublicationForm => ({ topic_type: 'STANDARD', event_title: '', event_start: '', event_end: '', coupon_code: '', redeem_online_url: '', terms_conditions: '', action_type: '', action_url: '' });

export function publicationForm(value: MediaPublication | null | undefined, timezone: string): PublicationForm {
  return { ...blankPublicationForm(), topic_type: value?.topic_type || 'STANDARD', event_title: value?.event?.title || '', event_start: value?.event?.start_at ? mediaUtcToLocal(value.event.start_at, timezone) : '', event_end: value?.event?.end_at ? mediaUtcToLocal(value.event.end_at, timezone) : '', coupon_code: value?.offer?.coupon_code || '', redeem_online_url: value?.offer?.redeem_online_url || '', terms_conditions: value?.offer?.terms_conditions || '', action_type: value?.call_to_action?.action_type || '', action_url: value?.call_to_action?.url || '' };
}

export function publicationHttpsUrl(value: string): string | null {
  try { const url = new URL(value); return url.protocol === 'https:' && !url.username && !url.password ? url.href : null; } catch { return null; }
}

/** Only Google tasks get this field. Never carry stale Google fields onto Meta. */
export function publicationPayload(form: PublicationForm, timezone: string, platform: string): MediaPublication | undefined {
  if (platform !== 'google_business') return undefined;
  const result: MediaPublication = { topic_type: form.topic_type };
  if (form.topic_type !== 'STANDARD') {
    if (!form.event_title.trim()) throw new Error('请填写活动或优惠标题。');
    const start_at = mediaLocalToUtc(form.event_start, timezone), end_at = mediaLocalToUtc(form.event_end, timezone);
    if (Date.parse(end_at) <= Date.parse(start_at)) throw new Error('活动或优惠结束时间必须晚于开始时间。');
    result.event = { title: form.event_title.trim(), start_at, end_at };
  }
  if (form.topic_type === 'OFFER') {
    if (form.redeem_online_url.trim() && !publicationHttpsUrl(form.redeem_online_url.trim())) throw new Error('优惠兑换链接须为有效 HTTPS 地址。');
    result.offer = { coupon_code: form.coupon_code.trim() || null, redeem_online_url: form.redeem_online_url.trim() || null, terms_conditions: form.terms_conditions.trim() || null };
  }
  if (form.topic_type !== 'OFFER' && form.action_type) {
    if (!(form.action_type in publicationActionLabels)) throw new Error('请选择有效的行动按钮。');
    if (form.action_type !== 'CALL' && !publicationHttpsUrl(form.action_url.trim())) throw new Error('行动按钮须填写有效 HTTPS 链接。');
    result.call_to_action = { action_type: form.action_type as NonNullable<MediaPublication['call_to_action']>['action_type'], ...(form.action_type !== 'CALL' ? { url: form.action_url.trim() } : {}) };
  }
  return result;
}

export function publicationEquivalent(a: unknown, b: unknown): boolean {
  const normalized = (value: unknown): unknown => {
    if (Array.isArray(value)) return value.map(normalized);
    if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).filter(([,v])=>v!==null&&v!==undefined).sort(([x],[y])=>x.localeCompare(y)).map(([k,v])=>[k,['start_at','end_at'].includes(k)&&typeof v==='string'&&Number.isFinite(Date.parse(v))?new Date(v).toISOString():['url','redeem_online_url'].includes(k)&&typeof v==='string'?publicationHttpsUrl(v)||v:normalized(v)]));
    return value;
  };
  return JSON.stringify(normalized(a || { topic_type: 'STANDARD' })) === JSON.stringify(normalized(b || { topic_type: 'STANDARD' }));
}
