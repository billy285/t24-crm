export const PRIVATE_WORKSPACE_VIEWS = ['today', 'gmail', 'google_ads', 'funds', 'bofa', 'bofa_bank', 'stripe', 'manual', 'connections'] as const;
export type PrivateWorkspaceView = typeof PRIVATE_WORKSPACE_VIEWS[number];
export type PrivateWorkspacePanel = 'editor' | 'preferences' | 'snooze';

export type PrivateNavigationState = {
  session: string;
  parentKey: string;
  parentView: PrivateWorkspaceView;
  panelToken?: string;
};

/** Navigation metadata only. Private records, amounts and credentials never enter history state. */
export function privateNavigationState(value: unknown, session: string): PrivateNavigationState | null {
  if (!value || typeof value !== 'object') return null;
  const entry = (value as { privateWorkspace?: unknown }).privateWorkspace;
  if (!entry || typeof entry !== 'object') return null;
  const record = entry as Record<string, unknown>;
  if (record.session !== session || typeof record.parentKey !== 'string' || !record.parentKey
    || !PRIVATE_WORKSPACE_VIEWS.includes(record.parentView as PrivateWorkspaceView)) return null;
  if (record.panelToken !== undefined && (typeof record.panelToken !== 'string' || !/^panel-\d+$/.test(record.panelToken))) return null;
  return { session, parentKey: record.parentKey, parentView: record.parentView as PrivateWorkspaceView,
    ...(record.panelToken ? { panelToken: record.panelToken as string } : {}) };
}

export function privateBackTarget(state: PrivateNavigationState | null, knownKeys: ReadonlySet<string>) {
  if (state && knownKeys.has(state.parentKey)) return { history: true, view: state.parentView };
  return { history: false, view: 'today' } as const;
}
