/** UI scope only: server authorization remains authoritative. */
export function mediaProviderScope(identity: string, customerId?: number, platformFilter?: string): string {
  if (customerId === undefined && (!platformFilter || platformFilter === 'all')) return identity;
  return `${identity}:merchant:${customerId === undefined ? 'all' : customerId}:platform:${platformFilter || 'all'}`;
}
export function mediaScopedBindings<T extends { customer_id: number; platform?: string }>(rows: T[], customerId?: number, platformFilter?: string): T[] {
  return rows.filter(row => (customerId === undefined || row.customer_id === customerId) && (!platformFilter || platformFilter === 'all' || row.platform === undefined && platformFilter === 'google_business' || row.platform === platformFilter));
}
