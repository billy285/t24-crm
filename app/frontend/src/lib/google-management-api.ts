import { googleBusinessApi } from './google-business-api';
import { mediaUtcToLocal } from './media-operations-api';

export type GpmLifecycle = 'unbound' | 'active' | 'paused' | 'stopped';
export const gpmLifecycleLabels: Record<GpmLifecycle, string> = { unbound: '待绑定', active: '管理中', paused: '已暂停', stopped: '已结束' };
export type GpmScheduler = { enabled: boolean; activation_from: string | null };
export type GpmMerchant = {
  customer_id: number; customer_name: string; customer_status: string; industry: string | null; region: string | null;
  cooperation_eligible: boolean; cooperation_reason: string | null; binding_id: number | null; revision: number | null;
  lifecycle: GpmLifecycle; primary_operator_id: number | null; primary_operator_name: string | null;
  connection_id: number | null; connection_needs_reconnect: boolean; location_name: string | null; eligible_assignee_ids: number[];
};
export type GpmPortfolio = {
  items: GpmMerchant[]; total: number; summary: Record<GpmLifecycle, number>;
  assignees: { id: number; name: string; eligible_customer_ids: number[] }[]; scheduler: GpmScheduler;
};
export type GpmAssignmentPreview = {
  preview_id: string; expires_at: string; employee_id: number; eligible_count: number; ineligible_count: number;
  items: { binding_id: number; customer_id: number; customer_name: string; revision: number; eligible: boolean; reason: string | null; customer_permissions_url: string }[];
};
export type GpmAssignmentResult = { request_id: string; applied_count: number; skipped_count: number; items: { binding_id: number; applied: boolean; reason: string | null; customer_permissions_url: string }[] };
export type GpmScheduleStatus = 'scheduled' | 'dispatching' | 'accepted' | 'succeeded' | 'failed' | 'unknown' | 'blocked' | 'cancelled' | 'missed';
export const gpmScheduleLabels: Record<GpmScheduleStatus, string> = {
  scheduled: '已排期', dispatching: '正在提交', accepted: 'Google 处理中', succeeded: '已公开', failed: '发布失败', unknown: '结果待确认', blocked: '已暂停', cancelled: '已取消', missed: '错过排期',
};
export type GpmSchedule = { id: number; revision: number; binding_id?: number; task_id?: number; planned_at: string; timezone: string; status: GpmScheduleStatus; message: string; action_id: number | null };
export type GpmCalendarTask = { task_id: number; title: string; customer_id: number; customer_name: string; binding_id: number | null; assignee_id: number; assignee_name: string; status: string; due_at: string; timezone: string; revision: number; schedule: GpmSchedule | null; can_schedule?: boolean; schedule_blocked_reason?: string | null };
export type GpmCalendar = { items: GpmCalendarTask[]; scheduler: GpmScheduler; from: string; to: string };
export type GpmCounters = { reply_succeeded: number; post_succeeded: number; pending: number; accepted: number; unknown: number; failed: number; rejected: number; draft?: number; in_review?: number; ready?: number; completed?: number; blocked?: number };
export type GpmStatistics = {
  from: string; to: string; totals: GpmCounters;
  employees: (GpmCounters & { employee_id: number; employee_name: string })[];
  basis: 'provider_confirmation_and_internal_tasks_separate'; legacy_success_time_fallback_count?: number;
  records?: { id: number; binding_id: number; customer_name: string; kind: 'review_reply' | 'post_publish'; actor_name: string; status: string; provider_state: string | null; confirmed_at: string | null; created_at: string; provider_url: string | null; content?: string | null }[];
};
const id = (value: unknown) => Number.isSafeInteger(value) && Number(value) > 0;
const textOrNull = (value: unknown) => value === null || typeof value === 'string';
const count = (value: unknown) => Number.isSafeInteger(value) && Number(value) >= 0;
export function verifiedPortfolio(value: GpmPortfolio): GpmPortfolio {
  if (!value || !Array.isArray(value.items) || !Array.isArray(value.assignees) || !count(value.total) || !value.summary || !value.scheduler || typeof value.scheduler.enabled !== 'boolean') throw new Error('商家管理资料返回不完整，请重新读取。');
  if (value.items.some(row => !id(row.customer_id) || typeof row.customer_name !== 'string' || !Object.prototype.hasOwnProperty.call(gpmLifecycleLabels, row.lifecycle) || typeof row.cooperation_eligible !== 'boolean' || typeof row.connection_needs_reconnect !== 'boolean' || ![row.industry, row.region, row.cooperation_reason, row.primary_operator_name, row.location_name].every(textOrNull) || !Array.isArray(row.eligible_assignee_ids) || row.binding_id !== null && (!id(row.binding_id) || !id(row.revision)))) throw new Error('商家状态返回不完整，请重新读取。');
  if (Object.keys(gpmLifecycleLabels).some(key => !count(value.summary[key as GpmLifecycle])) || value.assignees.some(row => !id(row.id) || typeof row.name !== 'string')) throw new Error('商家汇总返回不完整。');
  return value;
}
export function verifiedAssignmentPreview(value: GpmAssignmentPreview): GpmAssignmentPreview {
  if (!value || typeof value.preview_id !== 'string' || !/^[\da-f-]{36}$/i.test(value.preview_id) || !Number.isFinite(Date.parse(value.expires_at)) || !id(value.employee_id) || !count(value.eligible_count) || !count(value.ineligible_count) || !Array.isArray(value.items)
    || value.items.some(row => !id(row.binding_id) || !id(row.customer_id) || !id(row.revision) || typeof row.customer_name !== 'string' || typeof row.eligible !== 'boolean')
    || value.eligible_count + value.ineligible_count !== value.items.length) throw new Error('权限变更预览返回不完整，请重新预览。');
  return value;
}
export function verifiedCalendar(value: GpmCalendar): GpmCalendar {
  if (!value || !Array.isArray(value.items) || !value.scheduler || typeof value.scheduler.enabled !== 'boolean' || value.items.some(row => !id(row.task_id) || !id(row.customer_id) || !id(row.revision) || typeof row.title !== 'string' || typeof row.timezone !== 'string' || !Number.isFinite(Date.parse(row.due_at)) || row.schedule && (!id(row.schedule.id) || !id(row.schedule.revision) || !Object.prototype.hasOwnProperty.call(gpmScheduleLabels, row.schedule.status) || !Number.isFinite(Date.parse(row.schedule.planned_at)) || typeof row.schedule.timezone !== 'string'))) throw new Error('内容日历返回不完整，请重新读取。');
  return value;
}
export function verifiedStatistics(value: GpmStatistics): GpmStatistics {
  const keys = ['reply_succeeded', 'post_succeeded', 'pending', 'accepted', 'unknown', 'failed', 'rejected'] as const;
  if (!value || value.basis !== 'provider_confirmation_and_internal_tasks_separate' || !value.totals || keys.some(key => !count(value.totals[key])) || !Array.isArray(value.employees)
    || value.employees.some(row => !id(row.employee_id) || typeof row.employee_name !== 'string' || keys.some(key => !count(row[key]))) || value.records !== undefined && (!Array.isArray(value.records) || value.records.some(row => !id(row.id) || !id(row.binding_id) || typeof row.customer_name !== 'string' || !['review_reply', 'post_publish'].includes(row.kind) || typeof row.actor_name !== 'string' || typeof row.status !== 'string' || !textOrNull(row.provider_url) || row.content !== undefined && !textOrNull(row.content)))) throw new Error('运营统计返回不完整，请重新读取。');
  return value;
}
export const readPortfolio = async (params: URLSearchParams) => verifiedPortfolio(await googleBusinessApi<GpmPortfolio>(`/portfolio?${params}`));
export const readCalendar = async (params: URLSearchParams) => verifiedCalendar(await googleBusinessApi<GpmCalendar>(`/calendar?${params}`));
export const readStatistics = async (params: URLSearchParams) => verifiedStatistics(await googleBusinessApi<GpmStatistics>(`/statistics?${params}`));
export function managementToday(now = new Date()): string { return mediaUtcToLocal(now.toISOString(), 'Asia/Shanghai').slice(0, 10); }
export function shiftDate(value: string, days: number): string { const date = new Date(`${value}T12:00:00Z`); date.setUTCDate(date.getUTCDate() + days); return date.toISOString().slice(0, 10); }
export function managementDateRange(from: string, through: string): { from: string; to: string } {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(from) || !/^\d{4}-\d{2}-\d{2}$/.test(through) || from > through) throw new Error('请选择有效的开始和结束日期。');
  const start = new Date(`${from}T00:00:00+08:00`), end = new Date(`${shiftDate(through, 1)}T00:00:00+08:00`);
  if (!Number.isFinite(start.getTime()) || !Number.isFinite(end.getTime()) || mediaUtcToLocal(start.toISOString(), 'Asia/Shanghai').slice(0, 10) !== from || mediaUtcToLocal(new Date(`${through}T00:00:00+08:00`).toISOString(), 'Asia/Shanghai').slice(0, 10) !== through || end.getTime() - start.getTime() > 366 * 86400_000) throw new Error('时间范围最多为 366 天。');
  return { from: start.toISOString(), to: end.toISOString() };
}
export function calendarDates(anchor: string, view: 'week' | 'month'): string[] {
  const date = new Date(`${view === 'month' ? `${anchor.slice(0, 7)}-01` : anchor}T12:00:00Z`);
  const monday = shiftDate(date.toISOString().slice(0, 10), -((date.getUTCDay() + 6) % 7));
  return Array.from({ length: view === 'month' ? 42 : 7 }, (_, index) => shiftDate(monday, index));
}
export function calendarTaskDate(row: GpmCalendarTask): string { return mediaUtcToLocal(row.schedule?.planned_at || row.due_at, 'Asia/Shanghai').slice(0, 10); }
export function customerPermissionUrl(value: string, customerId?: number): string {
  try { const parsed = new URL(value, 'https://t24-crm.com'); if (parsed.origin === 'https://t24-crm.com' && parsed.pathname === '/customers') return parsed.pathname + parsed.search; } catch { /* use the known customer route */ }
  return customerId ? `/customers?detail=${customerId}` : '/customers';
}
