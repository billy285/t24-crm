export type ServiceDetailTab = 'overview' | 'tasks' | 'timeline';

export interface ServiceDetailTarget {
  progressId: number;
  tab: ServiceDetailTab;
  taskId: number | null;
  key: string;
}

function positiveId(value: string | null): number | null {
  if (!value || !/^[1-9]\d*$/.test(value)) return null;
  const id = Number(value);
  return Number.isSafeInteger(id) ? id : null;
}

/** A location hint only. Callers must resolve it against their authorized rows. */
export function readServiceDetailTarget(params: URLSearchParams): ServiceDetailTarget | null {
  const progressId = positiveId(params.get('progress_id'));
  if (progressId === null) return null;
  const requestedTab = params.get('detail_tab');
  const tab: ServiceDetailTab = requestedTab === 'overview' || requestedTab === 'timeline' ? requestedTab : 'tasks';
  const taskId = tab === 'tasks' ? positiveId(params.get('task_id')) : null;
  return { progressId, tab, taskId, key: `${progressId}:${tab}:${taskId || ''}` };
}
