import { wasExplicitlyLoggedOut } from './auth-storage';

export const salesWorkspaceFilters = ['all', 'overdue', 'unfinished', 'callback', 'interested', 'appointment'] as const;
export type SalesWorkspaceFilter = typeof salesWorkspaceFilters[number];
export type SalesWorkspaceViewState = { date: string; selectedSalesId: string; filter: SalesWorkspaceFilter; teamView: boolean };
export type SalesWorkspaceQueueScope = { userId?: number; role: string; salesId?: number; date: string };

const viewPrefix = 't24:sales-workspace-view:v1:';
const queuePrefix = 't24:sales-workspace-queue:v1:';
const roles = ['super_admin', 'admin', 'sales', 'sales_manager'];
const memory = new Map<string, string>();
let ignoreStoredState = false;
const positiveId = (value?: number) => typeof value === 'number' && Number.isSafeInteger(value) && value > 0;
const validOwner = (userId?: number, role?: string) => positiveId(userId) && roles.includes(role || '') && !wasExplicitlyLoggedOut();

export function isSalesWorkspaceDate(value: unknown): value is string {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const parsed = new Date(`${value}T00:00:00Z`);
  return Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value;
}

export function isSalesWorkspaceFilter(value: unknown): value is SalesWorkspaceFilter {
  return typeof value === 'string' && salesWorkspaceFilters.includes(value as SalesWorkspaceFilter);
}

const validSalesId = (value: unknown): value is string => value === '' || typeof value === 'string' && /^\d+$/.test(value) && positiveId(Number(value));
const viewKey = (userId: number, role: string) => `${viewPrefix}${userId}:${role}`;
const queueKey = (scope: SalesWorkspaceQueueScope) => `${queuePrefix}${scope.userId}:${scope.role}:${scope.salesId}:${scope.date}`;

function read(key: string): Record<string, any> | null {
  try {
    const raw = memory.get(key) ?? (ignoreStoredState ? null : window.sessionStorage.getItem(key));
    if (!raw || raw.length > 5000) return null;
    const value = JSON.parse(raw);
    return value && typeof value === 'object' && !Array.isArray(value) && value.version === 1
      && Number.isFinite(value.updatedAt) && value.updatedAt > 0 && value.updatedAt <= Date.now() + 60000 ? value : null;
  } catch { return null; }
}

function write(key: string, value: Record<string, unknown>) {
  const raw = JSON.stringify({ version: 1, updatedAt: Date.now(), ...value });
  memory.set(key, raw);
  try { window.sessionStorage.setItem(key, raw); } catch { /* Route changes can still restore this runtime. */ }
}

export function readSalesWorkspaceViewState(userId: number | undefined, role: string, day: string): SalesWorkspaceViewState | null {
  if (!validOwner(userId, role) || !isSalesWorkspaceDate(day)) return null;
  const value = read(viewKey(userId!, role));
  const view = value?.view;
  if (value?.userId !== userId || value?.role !== role || value?.savedOn !== day || !view
    || !isSalesWorkspaceDate(view.date) || !validSalesId(view.selectedSalesId)
    || !isSalesWorkspaceFilter(view.filter) || typeof view.teamView !== 'boolean') return null;
  return { date: view.date, selectedSalesId: view.selectedSalesId, filter: view.filter, teamView: view.teamView };
}

export function writeSalesWorkspaceViewState(userId: number | undefined, role: string, day: string, view: SalesWorkspaceViewState) {
  if (!validOwner(userId, role) || !isSalesWorkspaceDate(day) || !isSalesWorkspaceDate(view.date)
    || !validSalesId(view.selectedSalesId) || !isSalesWorkspaceFilter(view.filter) || typeof view.teamView !== 'boolean') return;
  write(viewKey(userId!, role), { userId, role, savedOn: day, view });
}

export function readSalesWorkspaceQueueQuery(scope: SalesWorkspaceQueueScope, day: string): string {
  if (!validOwner(scope.userId, scope.role) || !positiveId(scope.salesId) || !isSalesWorkspaceDate(scope.date)) return '';
  const value = read(queueKey(scope));
  return value?.userId === scope.userId && value?.role === scope.role && value?.salesId === scope.salesId
    && value?.date === scope.date && value?.savedOn === day && typeof value.query === 'string' && value.query.length <= 200 ? value.query : '';
}

export function writeSalesWorkspaceQueueQuery(scope: SalesWorkspaceQueueScope, day: string, query: string) {
  if (!validOwner(scope.userId, scope.role) || !positiveId(scope.salesId) || !isSalesWorkspaceDate(scope.date)
    || !isSalesWorkspaceDate(day) || typeof query !== 'string' || query.length > 200) return;
  write(queueKey(scope), { ...scope, savedOn: day, query });
}

export function clearSalesWorkspaceViewState(): void {
  // Suppress old persisted entries in this runtime even when privacy settings
  // reject both removal and replacement. Auth logout must never be blocked.
  memory.clear();
  ignoreStoredState = true;
  try {
    const storage = window.sessionStorage;
    const keys: string[] = [];
    for (let index = 0; index < storage.length; index++) {
      const key = storage.key(index);
      if (key && (key.startsWith(viewPrefix) || key.startsWith(queuePrefix))) keys.push(key);
    }
    for (const key of keys) {
      try { storage.removeItem(key); }
      catch {
        try { storage.setItem(key, JSON.stringify({ version: 1, cleared: true, updatedAt: Date.now() })); }
        catch { /* Current-runtime suppression remains active. */ }
      }
    }
  } catch { /* Storage access itself can be unavailable. */ }
}
