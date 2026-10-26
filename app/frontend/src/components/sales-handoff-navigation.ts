import { buildReturnLink, getSafeInternalPath } from '@/lib/navigation-state';
import { followThroughHref, type OwnerException } from '@/lib/service-follow-through';

const positiveId = (value?: number) => Number.isSafeInteger(value) && Number(value) > 0;

/** Preserve the selected queue and its original source when returning from customer authorization. */
export function salesHandoffReturnPath(currentPath: string, status: string, handoffId?: number | null) {
  const safe = getSafeInternalPath(currentPath, '/sales-leads?view=handoffs');
  const target = new URL(safe, 'https://t24-crm.local');
  target.searchParams.set('view', 'handoffs');
  target.searchParams.set('status', status);
  if (positiveId(handoffId ?? undefined)) target.searchParams.set('handoff', String(handoffId));
  return `${target.pathname}${target.search}${target.hash}`;
}

export function salesHandoffCustomerHref(customerId: number, returnPath: string, invite = false) {
  if (!positiveId(customerId)) return '';
  return buildReturnLink(`/customers?detail=${customerId}${invite ? '&access=invite' : ''}`, returnPath);
}

export function salesHandoffQueueHref(handoffId: number, returnPath: string, action?: 'finance' | 'ack') {
  if (!positiveId(handoffId)) return '';
  return buildReturnLink(`/sales-leads?view=handoffs&handoff=${handoffId}${action ? `&action=${action}` : ''}`, returnPath);
}

/** This selects a destination only. Destination pages retain every existing authorization and confirmation. */
export function ownerExceptionTaskHref(item: OwnerException) {
  const safe = followThroughHref(item.href);
  if (!safe) return '';
  if (item.kind === 'pending_access' && positiveId(item.customer_id)) return `/customers?detail=${item.customer_id}&access=invite`;
  if (item.kind === 'pending_receipt' && positiveId(item.handoff_id)) return `/sales-leads?view=handoffs&status=pending_payment&handoff=${item.handoff_id}&action=finance`;
  return safe;
}
