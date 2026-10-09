import { parseBusinessDateTimeInput } from './business-date';

export type FollowUpDraft = { outcome: string; notes: string; next_follow_up_at: string };
export type FollowUpDraftScope = { userId: number; leadId: number; salesId?: number | null };
export type DraftPersistence = 'session' | 'page' | 'none';
const outcomes = new Set(['no_answer', 'callback', 'interested', 'appointment', 'not_interested', 'do_not_contact']);
const pageDrafts = new Map<string, { value: FollowUpDraft; savedAt: number; persistence: 'session' | 'page' }>();
const clearedDrafts = new Set<string>();
let currentUserId: number | undefined;

function keyFor(scope: FollowUpDraftScope) {
  if (currentUserId !== scope.userId) { pageDrafts.clear(); clearedDrafts.clear(); currentUserId = scope.userId; }
  if (!Number.isSafeInteger(scope.userId) || scope.userId <= 0 || !Number.isSafeInteger(scope.leadId) || scope.leadId <= 0) return null;
  return `t24.sales-followup.v1:${scope.userId}:${scope.salesId || 0}:${scope.leadId}`;
}

function valid(value: unknown): value is FollowUpDraft {
  if (!value || typeof value !== 'object') return false;
  const draft = value as FollowUpDraft;
  if (!outcomes.has(draft.outcome) || typeof draft.notes !== 'string' || draft.notes.length > 20000 || typeof draft.next_follow_up_at !== 'string') return false;
  if (draft.next_follow_up_at) {
    if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(draft.next_follow_up_at)) return false;
    try { parseBusinessDateTimeInput(draft.next_follow_up_at); } catch { return false; }
  }
  return true;
}

export function readFollowUpDraft(scope: FollowUpDraftScope) {
  const key = keyFor(scope);
  if (!key || clearedDrafts.has(key)) return null;
  const inPage = pageDrafts.get(key);
  if (inPage) return { ...inPage, value: { ...inPage.value } };
  try {
    const raw = sessionStorage.getItem(key);
    if (raw) {
      const saved = JSON.parse(raw);
      if (saved.version === 1 && valid(saved.value) && Number.isFinite(saved.savedAt) && saved.savedAt > 0) {
        return { value: saved.value as FollowUpDraft, savedAt: saved.savedAt as number, persistence: 'session' as const };
      }
    }
  } catch { /* Storage may be blocked; current-page drafts still work. */ }
  return null;
}

export function writeFollowUpDraft(scope: FollowUpDraftScope, value: FollowUpDraft): DraftPersistence {
  const key = keyFor(scope);
  if (!key || !valid(value)) return 'none';
  const saved = { value: { ...value }, savedAt: Date.now() };
  clearedDrafts.delete(key);
  try {
    sessionStorage.setItem(key, JSON.stringify({ version: 1, ...saved }));
    pageDrafts.set(key, { ...saved, persistence: 'session' });
    return 'session';
  } catch { pageDrafts.set(key, { ...saved, persistence: 'page' }); return 'page'; }
}

export function removeFollowUpDraft(scope: FollowUpDraftScope) {
  const key = keyFor(scope);
  if (!key) return false;
  pageDrafts.delete(key);
  clearedDrafts.add(key);
  try { sessionStorage.removeItem(key); return true; } catch {
    // Overwrite stale contents when deletion alone is blocked; never undo a successful server save.
    try { sessionStorage.setItem(key, JSON.stringify({ version: 1, discarded: true })); return true; } catch { return false; }
  }
}
