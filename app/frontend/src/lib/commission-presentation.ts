export type CommissionAmounts = {
  pending: number; confirmed: number; payable: number; paid: number;
  first_order: number; renewal: number; adjustments: number; entry_count: number;
};

type CommissionSummaryEntry = {
  id: number; partner_id?: number; partner_name?: string; partner_code?: string;
  currency: string; status: string; entry_type: string; commission_amount: number;
};

const emptyAmounts = (): CommissionAmounts => ({ pending: 0, confirmed: 0, payable: 0, paid: 0, first_order: 0, renewal: 0, adjustments: 0, entry_count: 0 });

function addEntry(bucket: CommissionAmounts, entry: CommissionSummaryEntry) {
  bucket.entry_count += 1;
  if (entry.entry_type === 'first_order') bucket.first_order += entry.commission_amount;
  if (entry.entry_type === 'renewal') bucket.renewal += entry.commission_amount;
  if (entry.entry_type === 'refund_reversal') bucket.adjustments += entry.commission_amount;
  if (entry.status === 'pending_confirmation') bucket.pending += entry.commission_amount;
  if (['confirmed', 'payable', 'paid'].includes(entry.status)) bucket.confirmed += entry.commission_amount;
  if (entry.status === 'payable') bucket.payable += entry.commission_amount;
  if (entry.status === 'paid') bucket.paid += entry.commission_amount;
}

// Aggregate existing ledger amounts for presentation only; never recalculate a commission.
export function summarizeCommissionEntries(entries: CommissionSummaryEntry[]) {
  const currencies: Record<string, CommissionAmounts> = {};
  for (const entry of entries) {
    if (entry.status === 'reversed') continue;
    addEntry(currencies[entry.currency] ||= emptyAmounts(), entry);
  }
  return currencies;
}

export function groupCommissionSettlements(entries: CommissionSummaryEntry[]) {
  const grouped = new Map<string, CommissionAmounts & { key: string; partner_id?: number; partner_name: string; partner_code?: string; currency: string }>();
  for (const entry of entries) {
    if (entry.status === 'reversed') continue;
    // Missing identity must not merge unrelated records that happen to share a name.
    const key = `${entry.partner_id ?? `unresolved-entry-${entry.id}`}::${entry.currency}`;
    const row = grouped.get(key) || { ...emptyAmounts(), key, partner_id: entry.partner_id, partner_name: entry.partner_name || '未命名渠道', partner_code: entry.partner_code, currency: entry.currency };
    addEntry(row, entry);
    grouped.set(key, row);
  }
  return [...grouped.values()].sort((a, b) => a.partner_name.localeCompare(b.partner_name) || (a.partner_id || 0) - (b.partner_id || 0) || a.currency.localeCompare(b.currency));
}

export function portalScopeParams(mode: string | undefined, partnerId?: number | null) {
  return mode === 'owner_readonly' && partnerId ? { partner_id: partnerId } : undefined;
}
