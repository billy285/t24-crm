import { invokeWithAuth } from '@/lib/tokenStore';
import type { LeadInsight } from '@/lib/sales-intelligence';
import type { EnrichmentResponse, EnrichmentProduct, EnrichmentHistoryEntry } from '@/lib/sales-lead-enrichment';

export type DossierSummary = {
  revision: number; need_summary: string; objections: string; promises: string; next_step: string;
  decision_maker: string; latest_conclusion: string; next_action_at: string | null;
  updated_by_name?: string | null; updated_at?: string | null;
};
export type DossierGrant = {
  employee_id: number; employee_name: string; access: 'view' | 'collaborate'; status?: string; revision?: number; employee_active?: boolean;
  invited_by_name?: string; invited_at?: string; created_at?: string;
};
export type DossierCandidate = { id: number; name: string; role?: string; status?: string };
export type DossierHandoff = {
  id: number; from_employee_id?: number; to_employee_id?: number; from_name?: string; to_name?: string;
  from_sales_name?: string; to_sales_name?: string; reason?: string; summary?: Partial<DossierSummary>; handoff_summary?: string; status?: string;
  created_at: string; acknowledged_at?: string | null; acknowledged_by_name?: string; note?: string;
};
export type DossierOriginal = {
  id?: number; business_name?: string; phone?: string; contact_name?: string; industry?: string;
  country?: string; state?: string; city?: string; address?: string; website?: string;
  data_source?: string; collected_at?: string; business_status?: string; pool_status?: string;
  isolation_reason?: string; duplicate_of_id?: number; existing_customer_id?: number;
};
export type SalesDossier = {
  insight: LeadInsight;
  enrichment: EnrichmentResponse;
  summary: DossierSummary;
  protection: { can_contact: boolean; reason: string; cooldown_until?: string | null; phones?: string[]; protected_phones?: string[] };
  original: DossierOriginal | null;
  permissions: { can_edit: boolean; can_edit_summary: boolean; can_invite: boolean; can_transfer: boolean; can_ack: boolean; can_review: boolean; can_edit_profile: boolean; can_release_protection?: boolean };
  grants: DossierGrant[]; handoffs: DossierHandoff[]; candidates: DossierCandidate[];
  catalog?: EnrichmentProduct[]; enrichment_history?: EnrichmentHistoryEntry[];
};
export type SharedDossier = {
  id: number; lead_id?: number; business_name: string; industry?: string; state?: string; city?: string;
  owner_name?: string; owner?: string; access: 'view' | 'collaborate'; last_contact_at?: string; next_follow_up_at?: string;
};
export async function dossierApi<T>(path = '', method: 'GET' | 'PUT' | 'POST' | 'DELETE' = 'GET', data?: unknown): Promise<T> {
  const response = await invokeWithAuth({ url: `/api/v1/sales-lead-dossiers${path}`, method, data });
  return response.data as T;
}
