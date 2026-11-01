import { workspacePlatformLabels, workspaceRange, type WorkspaceStatusFilter } from './media-workspace-api';

// Preferences contain filters only. Never persist merchant records, platform
// credentials, grants or a previously selected merchant as access evidence.
export type WorkspacePreferences = { version: 1; platform: string; status: WorkspaceStatusFilter; operatorId: number | null; from: string; to: string };
const statuses = new Set(['all', 'attention', 'review', 'unassigned', 'no_schedule']);
const key = (identity: string) => `t24:media-workspace:filters:v1:${encodeURIComponent(identity)}`;
function verified(value: unknown): WorkspacePreferences | null {
  if (!value || typeof value !== 'object') return null;
  const row = value as WorkspacePreferences;
  if (row.version !== 1 || row.platform !== 'all' && !Object.prototype.hasOwnProperty.call(workspacePlatformLabels, row.platform) || !statuses.has(row.status) || row.operatorId !== null && (!Number.isSafeInteger(row.operatorId) || row.operatorId < 1)) return null;
  try { workspaceRange(row.from, row.to); } catch { return null; }
  return { version: 1, platform: row.platform, status: row.status, operatorId: row.operatorId, from: row.from, to: row.to };
}
export function readWorkspacePreferences(identity: string, storage?: Pick<Storage, 'getItem'>): WorkspacePreferences | null {
  try { const raw = (storage || window.localStorage).getItem(key(identity)); return raw ? verified(JSON.parse(raw)) : null; } catch { return null; }
}
export function saveWorkspacePreferences(identity: string, value: WorkspacePreferences, storage?: Pick<Storage, 'setItem'>): boolean {
  const safe = verified(value); if (!safe) return false;
  try { (storage || window.localStorage).setItem(key(identity), JSON.stringify(safe)); return true; } catch { return false; }
}
