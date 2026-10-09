import type { SalesCallValues } from '@/components/SalesCallRecord';
import { emptyContact } from '@/lib/sales-intelligence';
import { wasExplicitlyLoggedOut } from '@/lib/auth-storage';

export type SalesCallDraftScope = { userId?: number; salesId?: number; leadId?: number; taskId?: number; date: string; supplemental?: boolean };
export type DraftPersistence = 'session' | 'memory';
export type SalesCallDraft = { values: SalesCallValues; restored: boolean; persistence: DraftPersistence; invalid?: boolean };
const memory = new Map<string, string | null>();
let memoryOwner: number | undefined;
const positiveId = (value?: number) => typeof value === 'number' && Number.isSafeInteger(value) && value > 0;
export const emptySalesCallValues = (): SalesCallValues => ({ outcome: '', notes: '', nextFollowUpAt: '' });

export function setSalesCallDraftOwner(userId?: number) {
  if (memoryOwner !== userId || wasExplicitlyLoggedOut()) memory.clear();
  memoryOwner = userId;
}
export function clearSalesCallDraftMemory() { memory.clear(); memoryOwner = undefined; }
export function salesCallDraftKey(scope: SalesCallDraftScope): string | null {
  if (![scope.userId, scope.salesId, scope.leadId, scope.taskId].every(positiveId) || !/^\d{4}-\d{2}-\d{2}$/.test(scope.date)) return null;
  setSalesCallDraftOwner(scope.userId);
  return `t24:sales-call-draft:v2:${scope.userId}:${scope.salesId}:${scope.leadId}:${scope.date}:${scope.supplemental ? 'followup' : 'task'}:${scope.taskId}`;
}
export function legacySalesCallDraftKey(scope: SalesCallDraftScope): string | undefined {
  if (!salesCallDraftKey(scope)) return undefined;
  return `t24:sales-call-draft:v1:${scope.userId}:${scope.salesId}:${scope.date}:${scope.supplemental ? 'supplemental:' : ''}${scope.taskId}`;
}
function validKey(key: string | null): key is string {
  if (!key || !/^t24:sales-call-draft:v2:\d+:\d+:\d+:\d{4}-\d{2}-\d{2}:(?:task|followup):\d+$/.test(key)) return false;
  const parts = key.split(':');
  if (![3, 4, 5, 8].map(index => Number(parts[index])).every(positiveId)) return false;
  setSalesCallDraftOwner(Number(parts[3]));
  return !wasExplicitlyLoggedOut();
}
function matchingLegacyKey(key: string, legacyKey?: string) {
  const parts = key.split(':');
  // The server's task ID is an immutable lead association. Only its exact old owner/workday key can migrate.
  const expected = `t24:sales-call-draft:v1:${parts[3]}:${parts[4]}:${parts[6]}:${parts[7] === 'followup' ? 'supplemental:' : ''}${parts[8]}`;
  return legacyKey === expected ? legacyKey : undefined;
}
const boundedString = (value: unknown, limit: number) => typeof value === 'string' && value.length <= limit;
function parseValues(raw: string, options: { value: string }[], legacy = false): SalesCallValues | null {
  try {
    if (raw.length > 20000) return null;
    const draft = JSON.parse(raw);
    const values = draft?.values;
    if (legacy ? draft?.version !== undefined && draft.version !== 1 : draft?.version !== 2) return null;
    if (!Number.isFinite(draft?.updatedAt) || draft.updatedAt <= 0 || draft.updatedAt > Date.now() + 60000 || !values || typeof values !== 'object' || Array.isArray(values)) return null;
    if (!boundedString(values.outcome, 40) || (values.outcome && !options.some(option => option.value === values.outcome)) || !boundedString(values.notes, 10000) || !boundedString(values.nextFollowUpAt, 40) || values.nextFollowUpAt && !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?$/.test(values.nextFollowUpAt)) return null;
    const result: SalesCallValues = { outcome: values.outcome, notes: values.notes, nextFollowUpAt: values.nextFollowUpAt };
    if (values.contactDetails !== undefined) {
      const contact = values.contactDetails;
      if (!contact || typeof contact !== 'object' || Array.isArray(contact)) return null;
      if (contact.reached_person !== undefined && !['unknown', 'gatekeeper', 'decision_maker'].includes(contact.reached_person)) return null;
      const details = { ...emptyContact };
      for (const field of ['rejection_reason', 'need_summary', 'next_step'] as const) {
        if (contact[field] !== undefined && !boundedString(contact[field], 2000)) return null;
        details[field] = contact[field] || '';
      }
      details.reached_person = contact.reached_person || 'unknown';
      result.contactDetails = details;
    }
    return result;
  } catch { return null; }
}
export function hasSalesCallDraft(values: SalesCallValues) {
  return Boolean(values.outcome || values.notes || values.nextFollowUpAt || values.contactDetails && (values.contactDetails.reached_person !== 'unknown' || values.contactDetails.rejection_reason || values.contactDetails.need_summary || values.contactDetails.next_step));
}
export function writeSalesCallDraft(key: string | null, values: SalesCallValues): DraftPersistence {
  if (!validKey(key)) return 'memory';
  const raw = JSON.stringify({ version: 2, updatedAt: Date.now(), values });
  memory.set(key, raw);
  try { sessionStorage.setItem(key, raw); return 'session'; } catch { return 'memory'; }
}
export function readSalesCallDraft(key: string | null, options: { value: string }[], legacyKey?: string): SalesCallDraft {
  const empty = { values: emptySalesCallValues(), restored: false, persistence: 'session' as const };
  if (!validKey(key)) return { ...empty, persistence: 'memory' };
  legacyKey = matchingLegacyKey(key, legacyKey);
  let raw: string | null = null;
  let legacy = false;
  let persistence: DraftPersistence = 'session';
  try { raw = sessionStorage.getItem(key); } catch { persistence = 'memory'; }
  // A failed removal is tombstoned for this page runtime, so it cannot resurrect a saved/discarded draft.
  if (memory.has(key)) raw = memory.get(key) || null;
  if (!raw && !memory.has(key) && legacyKey) {
    try { raw = sessionStorage.getItem(legacyKey); legacy = Boolean(raw); } catch { persistence = 'memory'; }
  }
  if (!raw) return { ...empty, persistence };
  if (raw.length <= 256) {
    try {
      const marker = JSON.parse(raw);
      if (marker?.version === 2 && marker.cleared === true && marker.values === undefined && Number.isFinite(marker.updatedAt) && marker.updatedAt > 0) return { ...empty, persistence };
    } catch { /* Malformed drafts are handled below without deleting evidence. */ }
  }
  const values = parseValues(raw, options, legacy);
  if (!values) return { ...empty, persistence, invalid: true };
  if (legacy) persistence = writeSalesCallDraft(key, values);
  return { values, restored: hasSalesCallDraft(values), persistence };
}
export function removeSalesCallDraft(key: string | null, legacyKey?: string): boolean {
  if (!validKey(key)) return false;
  legacyKey = matchingLegacyKey(key, legacyKey);
  memory.set(key, null);
  let removed = true;
  for (const target of [key, legacyKey].filter((value): value is string => Boolean(value))) {
    try { sessionStorage.removeItem(target); }
    catch {
      // Some restricted stores permit replacement but reject removal. Persist a content-free tombstone.
      try { sessionStorage.setItem(target, JSON.stringify({ version: 2, updatedAt: Date.now(), cleared: true })); }
      catch { removed = false; }
    }
  }
  return removed;
}

export function readSalesWorkbenchFocus(userId?: number, salesId?: number, date?: string): { taskId: number; leadId: number } | null {
  if (!positiveId(userId) || !positiveId(salesId) || !date || !/^\d{4}-\d{2}-\d{2}$/.test(date)) return null;
  setSalesCallDraftOwner(userId);
  const key = `t24:sales-workbench:focus:v2:${userId}:${salesId}:${date}`;
  let raw: string | null = null;
  try { raw = sessionStorage.getItem(key); } catch { /* The runtime fallback is scoped to the same owner. */ }
  if (memory.has(key)) raw = memory.get(key) || null;
  try {
    const value = JSON.parse(raw || 'null');
    return value && positiveId(value.taskId) && positiveId(value.leadId) ? { taskId: value.taskId, leadId: value.leadId } : null;
  } catch { return null; }
}
export function writeSalesWorkbenchFocus(userId: number | undefined, salesId: number | undefined, date: string, taskId: number, leadId: number) {
  if (![userId, salesId, taskId, leadId].every(positiveId) || !/^\d{4}-\d{2}-\d{2}$/.test(date) || wasExplicitlyLoggedOut()) return;
  setSalesCallDraftOwner(userId);
  const key = `t24:sales-workbench:focus:v2:${userId}:${salesId}:${date}`;
  const raw = JSON.stringify({ taskId, leadId });
  memory.set(key, raw);
  try { sessionStorage.setItem(key, raw); } catch { /* Switching routes can still restore this page runtime. */ }
}
