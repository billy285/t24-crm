import { invokeWithAuth } from '@/lib/tokenStore';
import { getSafeInternalPath } from '@/lib/navigation-state';

export type FollowThroughCoverage = { scope?: string; note?: string; linked_subscriptions?: number; unconnected_subscriptions?: number; webhook_configured?: boolean; latest_event_at?: string | null };
export type OwnerException = { id: string; kind: string; title: string; business_name?: string; customer_id?: number; handoff_id?: number; waiting_days?: number; severity?: string; href?: string };
export type OwnerExceptionOverview = { counts: Record<string, number>; items: OwnerException[]; coverage: FollowThroughCoverage; generated_at?: string };
export type RenewalSignal = { kind: string; status?: string; label?: string; invoice_id?: string; subscription_id?: string; event_at?: string; amount?: number; currency?: string };
export type RenewalObservation = { id: number | string; handoff_id?: number; customer_id?: number; business_name?: string; package_name?: string; billing_cycle?: string; due_date?: string; days_until_due?: number; connection_status: 'linked' | 'unconnected'; status: string; status_label?: string; latest_event_at?: string; signals: RenewalSignal[]; href?: string };
export type RenewalObservations = { items: RenewalObservation[]; counts: Record<string, number>; coverage: FollowThroughCoverage };
export type KickoffItem = { key: string; title: string; status: 'pending' | 'blocked' | 'completed'; due_date?: string; note?: string; evidence?: string; completed_on?: string | null; updated_by_name?: string; updated_at?: string };
export type KickoffSummary = { handoff_id: number; customer_id: number; business_name?: string; package_name?: string; selected_platforms?: string[]; operations_owner_name?: string; operations_status?: string; service_start_date?: string; service_end_date?: string; initialized: boolean; can_edit: boolean; read_only_reason?: string; status: 'missing' | 'in_progress' | 'overdue' | 'completed'; completed_count: number; blocked_count?: number; total_count: number; first_delivery_due_date?: string; revision?: number; href?: string };
export type KickoffDetail = KickoffSummary & { items: KickoffItem[]; audit: { id: number; item_key?: string; action?: string; actor_name?: string; created_at?: string; before?: unknown; after?: unknown }[] };
export type KickoffList = { items: KickoffSummary[]; counts: Record<string, number> };
export type KickoffDraft = { status: KickoffItem['status']; due_date: string; note: string; evidence: string; completed_on: string };

export async function followThroughApi<T>(path: string, method: 'GET' | 'POST' | 'PATCH' = 'GET', data?: unknown): Promise<T> {
  const response = await invokeWithAuth({ url: `/api/v1/service-follow-through${path}`, method, data });
  return response.data as T;
}

export function followThroughError(error: any, fallback: string) {
  const detail = error?.data?.detail ?? error?.response?.data?.detail;
  return typeof detail === 'string' ? detail : typeof detail?.message === 'string' ? detail.message : fallback;
}

export function followThroughAccessDenied(error: any) {
  return [401, 403, 404].includes(Number(error?.response?.status || error?.data?.status || error?.status));
}

// Server links remain subject to route authorization and cannot leave the CRM.
export function followThroughHref(value?: string) {
  const safe = getSafeInternalPath(value);
  if (!safe) return '';
  const path = new URL(safe, 'https://t24-crm.local').pathname;
  return ['/operations-workbench', '/sales-leads', '/customers', '/finance'].includes(path) ? safe : '';
}

export function followThroughDate(value?: string | null) {
  if (!value) return '尚无记录';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false });
}

/** Handoff service periods have an exclusive end date. */
export function kickoffLastServiceDate(value?: string) {
  if (!value || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return undefined;
  const date = new Date(`${value}T00:00:00Z`);
  if (Number.isNaN(date.getTime())) return undefined;
  date.setUTCDate(date.getUTCDate() - 1);
  return date.toISOString().slice(0, 10);
}
