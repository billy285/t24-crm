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

type ContactSchedule = { local_time?: string | null; next_window_at?: string | null; in_contact_window?: boolean | null };

export function localQueueSchedule(context: ContactSchedule): string {
  const { local_time: local, next_window_at: next, in_contact_window: within } = context;
  if (!local) return '时区待确认';
  // The service emits merchant-local ISO times including their UTC offset.
  const opening = next ? `${local.slice(0,10) === next.slice(0,10) ? '今天' : next.slice(5,10)} ${next.slice(11,16)} 起建议联系` : '';
  return [`当地 ${local.slice(11,16)}`, within ? '建议联系时段内' : opening].filter(Boolean).join(' · ');
}
