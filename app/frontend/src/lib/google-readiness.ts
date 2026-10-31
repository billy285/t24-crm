import { googleBusinessApi, verifiedGbpAction, verifiedGbpBinding, type GbpAction, type GbpBinding, type GbpReadyTask } from './google-business-api';
import type { GpmSchedule } from './google-management-api';

export type GbpPublicationEntry = { key: number; customerId: number; taskId: number; preview?: boolean };
export type GbpWorkspaceEntry = { key: number; bindingId?: number; customerId?: number; kind?: 'bind' | 'grants'; taskId?: number; preview?: boolean };
export type GbpReadiness = {
  binding: GbpBinding;
  task: { id: number; customer_id: number; title: string; status: string; revision: number; assignee_id: number; assignee_name: string; due_at: string; timezone: string } | null;
  checks: { key: string; label: string; status: 'passed' | 'pending' | 'blocked'; message: string }[];
  image_delivery: { enabled: boolean; scope: 'owner_account'; notice: string };
  active_action: GbpAction | null;
  active_schedule: GpmSchedule | null;
  can_open_publish: boolean;
  can_open_schedule: boolean;
};
const id = (value: unknown) => Number.isSafeInteger(value) && Number(value) > 0;
const time = (value: unknown) => typeof value === 'string' && Number.isFinite(Date.parse(value));
const scheduleStatuses = new Set(['scheduled', 'dispatching', 'accepted', 'succeeded', 'failed', 'unknown', 'blocked', 'cancelled', 'missed']);

/** A checklist is advisory; the existing publish/schedule endpoints recheck every guard. */
export function verifiedGoogleReadiness(value: GbpReadiness, bindingId: number, customerId: number, taskId?: number): GbpReadiness {
  if (!value || verifiedGbpBinding(value.binding).id !== bindingId || value.binding.customer_id !== customerId || !Array.isArray(value.checks)
    || value.checks.length < 1 || value.checks.length > 30 || value.checks.some(row => !row || typeof row.key !== 'string' || !row.key || typeof row.label !== 'string' || !['passed', 'pending', 'blocked'].includes(row.status) || typeof row.message !== 'string')
    || new Set(value.checks.map(row => row.key)).size !== value.checks.length
    || !value.image_delivery || typeof value.image_delivery.enabled !== 'boolean' || value.image_delivery.scope !== 'owner_account' || typeof value.image_delivery.notice !== 'string'
    || !Object.prototype.hasOwnProperty.call(value, 'task') || !Object.prototype.hasOwnProperty.call(value, 'active_action') || !Object.prototype.hasOwnProperty.call(value, 'active_schedule')
    || typeof value.can_open_publish !== 'boolean' || typeof value.can_open_schedule !== 'boolean') throw new Error('开工检查返回不完整，请重新核对。');
  if (value.task && (!id(value.task.id) || !id(value.task.revision) || !id(value.task.assignee_id) || value.task.customer_id !== customerId || typeof value.task.title !== 'string' || typeof value.task.status !== 'string' || typeof value.task.assignee_name !== 'string' || !time(value.task.due_at) || typeof value.task.timezone !== 'string')) throw new Error('任务检查范围不一致，请重新核对。');
  if (taskId && value.task?.id !== taskId) throw new Error('开工检查的任务编号不一致。');
  if (value.active_action) {
    verifiedGbpAction(value.active_action);
    if (value.active_action.binding_id !== bindingId || value.active_action.customer_id !== customerId || taskId && value.active_action.task_id !== taskId) throw new Error('Google 结果检查范围不一致。');
  }
  const schedule = value.active_schedule;
  if (schedule && (!id(schedule.id) || !id(schedule.revision) || schedule.binding_id !== bindingId || taskId && schedule.task_id !== taskId || !scheduleStatuses.has(schedule.status) || !time(schedule.planned_at) || typeof schedule.timezone !== 'string' || typeof schedule.message !== 'string')) throw new Error('Google 排期检查范围不一致。');
  return value;
}

export async function readGoogleReadiness(binding: GbpBinding, taskId?: number): Promise<GbpReadiness> {
  const query = taskId ? `?task_id=${taskId}` : '';
  return verifiedGoogleReadiness(await googleBusinessApi<GbpReadiness>(`/bindings/${binding.id}/readiness${query}`), binding.id, binding.customer_id, taskId);
}

export function googleTaskPublishBlock(task: GbpReadyTask): string | null {
  if (task.publish_blocked_reason) return task.publish_blocked_reason;
  if (!task.content.trim()) return '正文尚未填写，需退回任务补齐并重新审核。';
  if (task.content.length > 1500) return '正文超过 Google 帖子 1500 字限制，需修改并重新审核。';
  if (task.material_id && !task.has_public_image) return '配图版本、公开投递或素材授权尚未满足发布条件。';
  if (task.image_version_id && (!task.publication_image || task.publication_image.id !== task.image_version_id || task.publication_image.status !== 'ready')) return '固定配图或审核版本已变化，请重新核对。';
  return null;
}

export function googleTaskReadyToPublish(task: GbpReadyTask, binding: GbpBinding, readiness: GbpReadiness | null): boolean {
  return binding.active && binding.permissions.can_publish && !googleTaskPublishBlock(task) && !!readiness && readiness.can_open_publish
    && readiness.binding.active && readiness.binding.permissions.can_publish && readiness.binding.id === binding.id && readiness.binding.revision === binding.revision && readiness.binding.customer_id === binding.customer_id
    && readiness.task?.id === task.id && readiness.task.customer_id === binding.customer_id && readiness.task.revision === task.revision && readiness.task.status === 'ready';
}
