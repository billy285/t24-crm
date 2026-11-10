export function financeEntryListQuery(filters: { page: number; limit: number; status: string; q: string; kind: string; start: string; end: string }) {
  const query = new URLSearchParams({ skip: String((filters.page - 1) * filters.limit), limit: String(filters.limit) });
  if (filters.status !== 'all') query.set('status', filters.status);
  for (const key of ['q', 'kind', 'start', 'end'] as const) {
    if (filters[key]) query.set(key, filters[key]);
  }
  return query;
}

export function changeFinanceEntryListFilters(current: URLSearchParams, changes: Record<string, string>) {
  const next = new URLSearchParams(current);
  Object.entries(changes).forEach(([key, value]) => {
    if (value.trim()) next.set(key, value.trim()); else next.delete(key);
  });
  next.set('page', '1');
  return next;
}
