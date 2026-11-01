export type MonthlyAttention = {
  customer_id: 20;
  run_id: number | null;
  items: { key: string; version: string; level: 'warning' | 'error'; status: string; title: string; message: string }[];
  counts: Record<'attention' | 'total' | 'blocked' | 'unknown' | 'missed' | 'failed' | 'pending_confirmation', number>;
};

export function verifiedMonthlyAttention(value: MonthlyAttention): MonthlyAttention {
  const count = (entry: unknown) => Number.isSafeInteger(entry) && Number(entry) >= 0;
  const positive = (entry: unknown) => Number.isSafeInteger(entry) && Number(entry) > 0;
  const text = (entry: unknown, max: number) => typeof entry === 'string' && entry.length > 0 && entry.length <= max;
  if (!value || value.customer_id !== 20 || !(value.run_id === null || positive(value.run_id)) ||
      !Array.isArray(value.items) || value.items.length > 100 || !value.counts ||
      !['attention', 'total', 'blocked', 'unknown', 'missed', 'failed', 'pending_confirmation'].every(key => count(value.counts[key as keyof MonthlyAttention['counts']])) ||
      !value.items.every(item => item && text(item.key, 240) && /^[a-f0-9]{64}$/.test(item.version) &&
        ['warning', 'error'].includes(item.level) && text(item.status, 100) && text(item.title, 240) && text(item.message, 1200)) ||
      new Set(value.items.map(item => item.key)).size !== value.items.length ||
      value.counts.total !== value.items.length || value.counts.attention !== value.items.length ||
      value.counts.blocked + value.counts.unknown + value.counts.missed + value.counts.failed !== value.counts.attention ||
      value.counts.pending_confirmation > 1 ||
      (value.items.length > 0 || value.counts.pending_confirmation > 0) && value.run_id === null) {
    throw new Error('月度提醒返回的商家、批次或状态不完整，请重新读取。');
  }
  return value;
}
