import type { GbpPublicationPayload } from '@/lib/google-business-api';
import { mediaUtcToLocal, type MediaPublication } from '@/lib/media-operations-api';
import { publicationActionLabels, publicationHttpsUrl, publicationTopicLabels } from './media-publication';
import './media-publication.css';

export default function MediaPublicationPreview({ publication, timezone = 'Asia/Shanghai', heading = '已准备的发布内容' }: { publication?: MediaPublication | null; timezone?: string; heading?: string }) {
  const value = publication || { topic_type: 'STANDARD' };
  const time = (date: string) => mediaUtcToLocal(date, timezone).replace('T', ' ') || '时间待核对';
  return <section className="media-publication" aria-label={heading}><header><strong>{heading}</strong><span>{publicationTopicLabels[value.topic_type] || '类型待核对'}</span></header>{value.event && <dl><div><dt>{value.topic_type === 'OFFER' ? '优惠标题' : '活动标题'}</dt><dd>{value.event.title}</dd></div><div><dt>开始</dt><dd>{time(value.event.start_at)}</dd></div><div><dt>结束</dt><dd>{time(value.event.end_at)}</dd></div><div><dt>商家时区</dt><dd>{timezone}</dd></div></dl>}{value.topic_type !== 'STANDARD' && !value.event && <p className="mp-warning">起止时间或标题尚不完整，请先补齐后审核。</p>}{value.offer && <dl><div><dt>优惠码</dt><dd>{value.offer.coupon_code || '不使用优惠码'}</dd></div><div><dt>在线兑换链接</dt><dd>{value.offer.redeem_online_url || '未填写'}{value.offer.redeem_online_url && !publicationHttpsUrl(value.offer.redeem_online_url) && <small>链接待核对</small>}</dd></div><div className="mp-wide"><dt>优惠条款</dt><dd>{value.offer.terms_conditions || '未填写，审核时请确认是否适用'}</dd></div></dl>}{value.call_to_action && <dl><div><dt>行动按钮</dt><dd>{publicationActionLabels[value.call_to_action.action_type] || value.call_to_action.action_type}</dd></div><div><dt>按钮去向</dt><dd>{value.call_to_action.action_type === 'CALL' ? '使用 Google 门店现有电话，不另写电话号码' : value.call_to_action.url || '链接待补充'}</dd></div></dl>}{!value.call_to_action && value.topic_type !== 'OFFER' && <p className="mp-muted">未设置行动按钮</p>}{value.topic_type === 'OFFER' && <p className="mp-muted">Google 优惠卡使用优惠专属入口，不另加行动按钮。</p>}</section>;
}

/** The provider snapshot stores wall-clock parts, not an instant or IANA zone. */
function submittedLocalTime(date: { year?: number; month?: number; day?: number } | undefined, time: { hours?: number; minutes?: number; seconds?: number; nanos?: number } | undefined): string {
  const pad = (value: number, length = 2) => String(value).padStart(length, '0');
  const validDate = date && Number.isInteger(date.year) && date.year! >= 1 && date.year! <= 9999 && Number.isInteger(date.month) && date.month! >= 1 && date.month! <= 12 && Number.isInteger(date.day) && date.day! >= 1 && date.day! <= 31;
  const dateText = validDate ? `${pad(date.year!, 4)}-${pad(date.month!)}-${pad(date.day!)}` : '日期未保留';
  if (!time || !Number.isInteger(time.hours) || !Number.isInteger(time.minutes) || time.hours! < 0 || time.hours! > 23 || time.minutes! < 0 || time.minutes! > 59) return `${dateText} · 时间未保留`;
  const hour = time.hours!, minute = time.minutes!, second = time.seconds ?? 0, nanos = time.nanos ?? 0;
  if (![second, nanos].every(Number.isInteger) || second < 0 || second > 59 || nanos < 0 || nanos > 999999999) return `${dateText} · 时间待核对`;
  return `${dateText} ${pad(hour)}:${pad(minute)}${second || nanos ? `:${pad(second)}` : ''}${nanos ? `.${pad(nanos, 9).replace(/0+$/, '')}` : ''}`;
}

export function GooglePublicationHistoryPreview({ payload }: { payload: GbpPublicationPayload }) {
  const schedule = payload.event?.schedule;
  return <section className="media-publication" aria-label="本次提交的原始帖子设置"><header><strong>本次提交的帖子设置</strong><span>{payload.topicType ? publicationTopicLabels[payload.topicType] || '类型待核对' : '类型未保留'}</span></header><p className="mp-muted">以下为提交时保存的配置；活动起止为提交时的门店当地时间，不推算或换算时区。</p>{payload.event && <dl><div><dt>{payload.topicType === 'OFFER' ? '优惠标题' : '活动标题'}</dt><dd>{payload.event.title || '标题未保留'}</dd></div><div><dt>开始 · 门店当地时间</dt><dd>{submittedLocalTime(schedule?.startDate, schedule?.startTime)}</dd></div><div><dt>结束 · 门店当地时间</dt><dd>{submittedLocalTime(schedule?.endDate, schedule?.endTime)}</dd></div></dl>}{payload.offer && <dl><div><dt>优惠码</dt><dd>{payload.offer.couponCode || '未填写'}</dd></div><div><dt>在线兑换链接</dt><dd>{payload.offer.redeemOnlineUrl || '未填写'}</dd></div><div className="mp-wide"><dt>优惠条款</dt><dd>{payload.offer.termsConditions || '未填写'}</dd></div></dl>}{payload.callToAction && <dl><div><dt>行动按钮</dt><dd>{payload.callToAction.actionType ? publicationActionLabels[payload.callToAction.actionType] || payload.callToAction.actionType : '按钮类型未保留'}</dd></div><div><dt>按钮链接</dt><dd>{payload.callToAction.url || (payload.callToAction.actionType === 'CALL' ? '致电门店 · 原配置未附链接' : '未填写')}</dd></div></dl>}</section>;
}
