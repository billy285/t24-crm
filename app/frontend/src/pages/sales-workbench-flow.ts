// Selection only: callers must supply the current server-authorized queue.
export type RequestedSalesLead = number | 'invalid' | null;
type QueueTask = { task_id: number; task_status: string; lead: { id: number } };

export function parseRequestedSalesLead(raw: string | null): RequestedSalesLead {
  if (raw === null) return null;
  const id = Number(raw);
  return /^\d+$/.test(raw) && Number.isSafeInteger(id) && id > 0 ? id : 'invalid';
}

export function resolveRequestedSalesLead<T extends QueueTask>(requested: RequestedSalesLead, authorized: T[] | null, visible: T[]) {
  if (requested === null) return { kind: 'none' as const, task: null };
  if (requested === 'invalid') return { kind: 'invalid' as const, task: null };
  if (authorized === null) return { kind: 'loading' as const, task: null };
  const task = authorized.find(item => item.lead.id === requested);
  if (!task) return { kind: 'missing' as const, task: null };
  if (!visible.some(item => item.task_id === task.task_id && item.lead.id === requested)) return { kind: 'filtered' as const, task: null };
  return { kind: 'ready' as const, task };
}

export function nextSalesWorkbenchTask<T extends QueueTask>(queue: T[], saved: QueueTask, authorized: T[] = queue): T | null {
  const position = queue.findIndex(item => item.task_id === saved.task_id && item.lead.id === saved.lead.id);
  const ordered = position < 0 ? queue : [...queue.slice(position + 1), ...queue.slice(0, position)];
  for (const candidate of ordered) {
    if (candidate.task_id === saved.task_id) continue;
    const current = authorized.find(item => item.task_id === candidate.task_id && item.lead.id === candidate.lead.id);
    if (current && current.task_status !== 'completed') return current;
  }
  return null;
}
