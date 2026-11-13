export type CustomerWorkQueueItem = {
  key: string;
  category: 'handoff' | 'delivery' | 'renewal';
  title: string;
  customerId: number;
  customerName: string;
  href: string;
  waitingDays?: number;
};

const positiveId = (value: unknown): number | undefined => {
  if (typeof value !== 'number' && (typeof value !== 'string' || !/^[1-9]\d*$/.test(value))) return undefined;
  const result = Number(value);
  return Number.isSafeInteger(result) && result > 0 ? result : undefined;
};
const nonempty = (value: unknown) => typeof value === 'string' && value.trim() ? value.trim() : '';
const ownerKinds = new Map<string, CustomerWorkQueueItem['category']>([
  ['pending_receipt', 'handoff'], ['pending_access', 'handoff'], ['pending_operations', 'handoff'],
  ['kickoff_missing', 'delivery'], ['kickoff_overdue', 'delivery'], ['kickoff_blocked', 'delivery'],
  ['renewal_attention', 'renewal'],
]);

/** Links are only navigation; the existing destination still authorizes every action. */
function ownerHref(item: Record<string, unknown>, customerId: number, kind: string): string {
  const handoffId = positiveId(item.handoff_id);
  if (kind === 'pending_access') return `/customers?detail=${customerId}&access=invite`;
  if (kind === 'pending_receipt' && handoffId) return `/sales-leads?view=handoffs&status=pending_payment&handoff=${handoffId}&action=finance`;
  if (kind === 'pending_operations' && handoffId) return `/sales-leads?view=handoffs&status=pending_operations&handoff=${handoffId}`;
  if (kind.startsWith('kickoff_') && handoffId) return `/operations-workbench?view=kickoffs&handoff=${handoffId}`;
  if (kind !== 'renewal_attention') return '';
  // Renewal records can link either a handoff or an explicitly matched customer.
  const href = nonempty(item.href);
  if (!href.startsWith('/') || href.startsWith('//') || href.includes('\\') || [...href].some(character => character.charCodeAt(0) <= 32)) return '';
  try {
    const url = new URL(href, 'https://t24-crm.local');
    if (url.origin !== 'https://t24-crm.local') return '';
    if (url.pathname === '/customers' && positiveId(url.searchParams.get('detail')) === customerId && url.searchParams.get('tab') === 'renewals') return href;
    if (url.pathname === '/sales-leads' && url.searchParams.get('view') === 'handoffs' && handoffId && positiveId(url.searchParams.get('handoff')) === handoffId) return href;
    if (url.pathname === '/operations-workbench' && url.searchParams.get('view') === 'renewals') return href;
    if (url.pathname === '/finance' && url.searchParams.get('tab') === 'stripe_reconciliation' && url.searchParams.get('stripe_view') === 'reviews'
      && (!url.searchParams.has('stripe_review') || positiveId(url.searchParams.get('stripe_review')))) return href;
  } catch { /* A malformed source link is not a navigable action. */ }
  return '';
}

export function buildCustomerWorkQueueItems({ source, items, visibleCustomers }: {
  source: 'owner' | 'handoffs';
  items: unknown;
  visibleCustomers: readonly { id: number | string; business_name?: string }[];
}): CustomerWorkQueueItem[] {
  const customers = new Map(visibleCustomers.flatMap(customer => {
    const customerId = positiveId(customer.id);
    return customerId ? [[customerId, customer] as const] : [];
  }));
  const result: CustomerWorkQueueItem[] = [];
  const seen = new Set<string>();
  const add = (item: Record<string, unknown>, customerId: number, key: string, category: CustomerWorkQueueItem['category'], title: string, href: string) => {
    if (seen.has(key)) return;
    seen.add(key);
    result.push({ key, category, title, customerId, customerName: nonempty(customers.get(customerId)?.business_name) || `客户 #${customerId}`, href,
      waitingDays: typeof item.waiting_days === 'number' && Number.isFinite(item.waiting_days) && item.waiting_days >= 0 ? item.waiting_days : undefined });
  };
  for (const value of Array.isArray(items) ? items : []) {
    if (!value || typeof value !== 'object' || Array.isArray(value)) continue;
    const item = value as Record<string, unknown>, customerId = positiveId(item.customer_id);
    if (!customerId || !customers.has(customerId)) continue;
    if (source === 'owner') {
      const kind = nonempty(item.kind), category = ownerKinds.get(kind), recordId = nonempty(item.id);
      if (!category || !recordId) continue;
      add(item, customerId, `owner:${recordId}`, category, nonempty(item.title) || '事项待核对', ownerHref(item, customerId, kind));
    } else {
      const handoffId = positiveId(item.id);
      if (!handoffId) continue;
      const href = `/sales-leads?view=handoffs&handoff=${handoffId}`;
      if (item.pending_payment === true) add(item, customerId, `handoff:${handoffId}:payment`, 'handoff', '成交收款待老板核对', href);
      if (item.pending_operations === true) add(item, customerId, `handoff:${handoffId}:operations`, 'handoff', `${nonempty(item.operations_owner_name) || '指定运营'}尚未确认接收`, href);
      // The server normally withholds this flag from non-owners; do not invent it.
      if (item.pending_access === true) add(item, customerId, `handoff:${handoffId}:access`, 'handoff', '客户交付权限待老板邀请', href);
    }
  }
  return result;
}

/** One request generation and AbortSignal must agree with the live actor/scope/session. */
export class CustomerWorkQueueRequestGuard {
  private sequence = 0;
  private controller: AbortController | null = null;
  begin(scope: string, session: string) {
    this.invalidate();
    this.controller = new AbortController();
    return { sequence: this.sequence, scope, session, signal: this.controller.signal };
  }
  current(request: { sequence: number; scope: string; session: string; signal: AbortSignal }, scope: string, session: string) {
    return !request.signal.aborted && request.sequence === this.sequence && request.scope === scope && request.session === session;
  }
  invalidate() { this.sequence += 1; this.controller?.abort(); this.controller = null; }
}
