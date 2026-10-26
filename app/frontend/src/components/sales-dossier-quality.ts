import type { SalesDossier } from '@/lib/sales-lead-dossier';

export type DossierQualityHint = {
  key: 'contact' | 'phone' | 'interest' | 'next_action';
  kind: 'missing' | 'to_understand' | 'to_arrange';
  label: string;
  detail: string;
};

const hasText = (value: string | null | undefined) => Boolean(value?.trim());

/** Presentation hints use only the current, server-authorized dossier snapshot. */
export function dossierQualityHints(data: Pick<SalesDossier, 'enrichment' | 'summary' | 'insight'>): DossierQualityHint[] {
  const { enrichment, summary, insight } = data;
  const hints: DossierQualityHint[] = [];
  if (!enrichment.contacts.some(contact => hasText(contact.name))) {
    hints.push({ key: 'contact', kind: 'missing', label: enrichment.contacts.length ? '联系人姓名未填写' : '联系人未填写', detail: '沟通时补充联系人姓名与身份。' });
  }
  if (!hasText(enrichment.store_phone) && !enrichment.contacts.some(contact => hasText(contact.phone))) {
    hints.push({ key: 'phone', kind: 'missing', label: '联系电话未填写', detail: '补充门店或联系人号码，是否可拨打仍以联系保护与号码核验为准。' });
  }
  if (!enrichment.interest_product_ids.length) {
    hints.push({ key: 'interest', kind: 'to_understand', label: '意向产品待了解', detail: '尚未明确意向，可在沟通后补充，不必先猜选产品。' });
  }
  if (['follow_up', 'interested'].includes(insight.status)) {
    const missingStep = !hasText(summary.next_step);
    const missingTime = !hasText(summary.next_action_at || insight.next_follow_up_at);
    if (missingStep || missingTime) {
      hints.push({
        key: 'next_action', kind: 'to_arrange', label: '下一步待安排',
        detail: missingStep && missingTime ? '下一步内容与联系时间尚未填写。' : missingStep ? '下一步内容尚未填写，现有约定时间保持不变。' : '下一步已有记录，联系时间尚未约定。',
      });
    }
  }
  return hints;
}
