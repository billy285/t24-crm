import { normalizeEnrichmentUpdate, type EnrichmentUpdate } from './sales-lead-enrichment';
import { wasExplicitlyLoggedOut } from './auth-storage';

type Scope = { userId?: number; salesId?: number; leadId?: number; taskId?: number; date: string };
const memory = new Map<string, string | null>();
let owner: number | undefined;
const positive = (id?: number) => Number.isSafeInteger(id) && Number(id) > 0;
export function salesEnrichmentDraftKey(scope: Scope): string | null {
  if (owner !== scope.userId || wasExplicitlyLoggedOut()) { memory.clear(); owner = scope.userId; }
  if (wasExplicitlyLoggedOut() || ![scope.userId, scope.salesId, scope.leadId, scope.taskId].every(positive) || !/^\d{4}-\d{2}-\d{2}$/.test(scope.date)) return null;
  return `t24:sales-enrichment:v1:${scope.userId}:${scope.salesId}:${scope.leadId}:${scope.taskId}:${scope.date}`;
}
function validKey(key: string | null): key is string {
  return Boolean(key && /^t24:sales-enrichment:v1:\d+:\d+:\d+:\d+:\d{4}-\d{2}-\d{2}$/.test(key) && !wasExplicitlyLoggedOut());
}
export function readEnrichmentDraft(key: string | null): EnrichmentUpdate | null {
  if (!validKey(key)) return null;
  let raw = memory.get(key) || null;
  if (!memory.has(key)) try { raw = sessionStorage.getItem(key); } catch { /* Runtime fallback stays account scoped. */ }
  if (!raw || raw.length > 60000) return null;
  try {
    const value = JSON.parse(raw);
    const draft = value?.draft;
    if (value.version !== 1 || !Number.isFinite(value.savedAt) || value.savedAt > Date.now() + 60000 || Date.now() - value.savedAt > 7 * 86400000) return null;
    if (!draft || typeof draft !== 'object' || !Number.isSafeInteger(draft.expected_revision) || draft.expected_revision < 0 || typeof draft.expected_lead_updated_at !== 'string' || !Number.isFinite(Date.parse(draft.expected_lead_updated_at))) return null;
    if (!Array.isArray(draft.contacts) || draft.contacts.length > 20 || !draft.contacts.every((c: any) => c && typeof c.id === 'string' && c.id.length <= 100)) return null;
    if (!Array.isArray(draft.interest_product_ids) || draft.interest_product_ids.length > 50 || !draft.interest_product_ids.every((id: unknown) => typeof id === 'number' && Number.isSafeInteger(id) && id > 0)) return null;
    if (typeof draft.business_name !== 'string' || typeof draft.store_phone !== 'string') return null;
    return normalizeEnrichmentUpdate(draft as EnrichmentUpdate);
  } catch { return null; }
}
export function writeEnrichmentDraft(key: string | null, draft: EnrichmentUpdate): 'session' | 'memory' {
  if (!validKey(key)) return 'memory';
  const raw = JSON.stringify({ version: 1, savedAt: Date.now(), draft });
  memory.set(key, raw);
  try { sessionStorage.setItem(key, raw); return 'session'; } catch { return 'memory'; }
}
export function removeEnrichmentDraft(key: string | null): boolean {
  if (!validKey(key)) return false;
  memory.set(key, null);
  try { sessionStorage.removeItem(key); return true; }
  catch {
    try { sessionStorage.setItem(key, JSON.stringify({ version: 1, cleared: true })); return true; }
    catch { return false; }
  }
}
