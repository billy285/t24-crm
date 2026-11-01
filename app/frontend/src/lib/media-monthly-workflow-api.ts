import { invokeWithAuth } from './tokenStore';
import { verifiedPublicationImage, type PublicationImage } from './media-publication-images';
import { MONTHLY_PILOT_CUSTOMER_ID, MONTHLY_PILOT_MONTH, monthlyRules, monthlySlotIds, monthlySlotMatches, validMonthlyMonth, type MonthlyRules, type MonthlyRun, type MonthlyMaterial } from './media-monthly-api';

export type MonthlyWorkflowKind = 'prepare' | 'review' | 'schedule' | 'cancel';
export type MonthlyWorkflowPacket = {
  id: number; revision: number; status: 'prepared' | 'reviewed' | 'scheduled' | 'cancelled';
  preview_hash: string; source_hash: string; reviewed_at: string | null; expires_at: string;
  created_at: string; updated_at: string;
};
export type MonthlyWorkflowSchedule = {
  id: number; revision: number; binding_id: number; task_id: number; timezone: string;
  status: string; message: string; action_id: string | null; planned_at: string;
};
export type MonthlyWorkflowItem = {
  item_id: number; slot_id: string; title: string; content: string; owner_summary: string;
  proposed_publish_at: string; timezone: string; revision: number; copy_hash: string;
  material_id: number | null; image_version_id: string | null; image_sha256: string | null;
  publication_image: PublicationImage | null; quality_warnings: string[];
  task_id: number | null; schedule: MonthlyWorkflowSchedule | null;
};
export type MonthlyWorkflowAlert = {
  key: string; version: string; run_id: number; level: 'warning' | 'error'; status: string; title: string; message: string;
  item_id: number | null; task_id: number | null; schedule_id: number | null; action_id: string | null;
};
export type MonthlyWorkflowBinding = { id: number; revision: number; customer_id: number; customer_name: string; title: string; primary_operator_id: number | null; primary_operator_name: string | null };
export type MonthlyWorkflow = {
  run_id: number; customer_id: number; month: string; rules: MonthlyRules; run_revision: number; source_stale: boolean;
  history_frozen?: boolean;
  workflow: MonthlyWorkflowPacket | null; items: MonthlyWorkflowItem[]; materials: MonthlyMaterial[];
  binding: MonthlyWorkflowBinding | null; current_binding?: MonthlyWorkflowBinding | null;
  delivery: { enabled: boolean; can_manage: boolean; notice: string; activated_at: string | null };
  scheduler: { enabled: boolean; activation_from: string | null };
  checks: { key: string; state: 'ready' | 'blocked' | 'pending'; message: string }[];
  alerts: MonthlyWorkflowAlert[];
  counts: Record<'total' | 'scheduled' | 'succeeded' | 'blocked' | 'unknown' | 'missed' | 'cancelled', number>;
  capabilities: { is_owner: true; can_prepare: boolean; can_review: boolean; can_schedule: boolean; can_cancel: boolean };
  request_receipt?: { request_id: string; kind: MonthlyWorkflowKind; workflow_revision: number; result_hash: string };
};
export type MonthlyPrepareBody = {
  request_id: string; expected_run_revision: number; expected_workflow_revision: number;
  items: { item_id: number; image_version_id: string; rights_confirmed: true }[]; facts_confirmed: true;
};
export type MonthlyReviewBody = { request_id: string; expected_revision: number; preview_hash: string; confirmed: true };
export type MonthlyScheduleBody = { request_id: string; expected_revision: number; preview_hash: string; publication_confirmed: true; confirmation_version: 'monthly-publication-v1' };
export type MonthlyCancelBody = { request_id: string; expected_revision: number; reason: string };
export type MonthlyWorkflowMutation =
  | { kind: 'prepare'; body: MonthlyPrepareBody }
  | { kind: 'review'; body: MonthlyReviewBody }
  | { kind: 'schedule'; body: MonthlyScheduleBody }
  | { kind: 'cancel'; body: MonthlyCancelBody };

const positive = (value: unknown): value is number => Number.isSafeInteger(value) && Number(value) > 0;
const count = (value: unknown): value is number => Number.isSafeInteger(value) && Number(value) >= 0;
const text = (value: unknown): value is string => typeof value === 'string';
const optionalId = (value: unknown) => value === null || positive(value);
const nullableText = (value: unknown) => value === null || text(value);
const hash = (value: unknown): value is string => text(value) && /^[a-f0-9]{64}$/.test(value);
const imageId = (value: unknown): value is string => text(value) && /^[a-f0-9]{32}$/.test(value);
const uuid = (value: unknown): value is string => text(value) && /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(value);
const instant = (value: unknown): value is string => text(value) && /(?:Z|[+-]\d{2}:\d{2})$/.test(value) && Number.isFinite(Date.parse(value));
const optionalInstant = (value: unknown) => value === null || instant(value);
const strings = (value: unknown): value is string[] => Array.isArray(value) && value.length <= 100 && value.every(text);
const kinds = new Set<MonthlyWorkflowKind>(['prepare', 'review', 'schedule', 'cancel']);
const scheduleStates = new Set(['scheduled', 'dispatching', 'pending', 'accepted', 'succeeded', 'unknown', 'rejected', 'failed', 'blocked', 'missed', 'cancelled']);

function need(value: unknown, message = '月度审核与发布资料不完整，请重新读取。'): asserts value { if (!value) throw new Error(message); }

function verifyMaterials(values: MonthlyMaterial[], customerId: number) {
  need(Array.isArray(values) && values.length <= 200 && values.every(value => value && positive(value.id) && text(value.title) && optionalId(value.linked_item_id) && nullableText(value.approval_status) && nullableText(value.copyright_status) && hash(value.fingerprint) && optionalId(value.width) && optionalId(value.height) && nullableText(value.quality_warning) && typeof value.needs_quality_confirmation === 'boolean' && Array.isArray(value.image_versions) && value.image_versions.length <= 100 && value.image_versions.every(image => !!verifiedPublicationImage(image, customerId, value.id))));
  need(new Set(values.map(value => value.id)).size === values.length);
}

export function verifiedMonthlyWorkflow(value: MonthlyWorkflow, runId: number, expected?: Pick<MonthlyRun, 'customer_id' | 'month' | 'profile_snapshot'>): MonthlyWorkflow {
  const customerId = expected?.customer_id ?? MONTHLY_PILOT_CUSTOMER_ID, month = expected?.month ?? MONTHLY_PILOT_MONTH;
  const legacyRules: MonthlyRules = { timezone: 'America/Chicago', weekdays: [2, 4, 6], local_time: '11:00', posts_per_week: 3, language: 'en', forbidden_claims: [], include_prices: false, generic_mode: true };
  // Only the persisted original pilot has a legacy response without an explicit rule snapshot.
  const rules = monthlyRules(value?.rules ?? (customerId === MONTHLY_PILOT_CUSTOMER_ID && month === MONTHLY_PILOT_MONTH ? expected?.profile_snapshot.rules ?? legacyRules : undefined as unknown as MonthlyRules));
  const slots = monthlySlotIds(month, rules);
  if (expected) { const original = expected.profile_snapshot.rules; need(rules.timezone === original.timezone && rules.local_time === original.local_time && rules.posts_per_week === original.posts_per_week && rules.language === original.language && rules.include_prices === original.include_prices && rules.generic_mode === original.generic_mode && [...rules.weekdays].sort().join(',') === [...original.weekdays].sort().join(',') && JSON.stringify(rules.forbidden_claims) === JSON.stringify(original.forbidden_claims), '月度审核规则与当前批次不一致。'); }
  need(positive(runId) && value && value.run_id === runId && value.customer_id === customerId && positive(customerId) && value.month === month && validMonthlyMonth(month) && positive(value.run_revision) && typeof value.source_stale === 'boolean', '本月审核清单与当前商家、月份或批次不一致。');
  const packet = value.workflow;
  need(packet === null || positive(packet.id) && positive(packet.revision) && ['prepared', 'reviewed', 'scheduled', 'cancelled'].includes(packet.status) && hash(packet.preview_hash) && hash(packet.source_hash) && optionalInstant(packet.reviewed_at) && instant(packet.expires_at) && instant(packet.created_at) && instant(packet.updated_at));
  const binding = value.binding;
  const verifiedBinding = (entry: MonthlyWorkflowBinding | null) => entry === null || entry && positive(entry.id) && positive(entry.revision) && entry.customer_id === customerId && text(entry.customer_name) && text(entry.title) && optionalId(entry.primary_operator_id) && nullableText(entry.primary_operator_name);
  need(verifiedBinding(binding) && (value.current_binding === undefined || verifiedBinding(value.current_binding)) && (value.history_frozen === undefined || typeof value.history_frozen === 'boolean'));
  need(Array.isArray(value.items) && slots.length > 0 && value.items.length === slots.length && new Set(value.items.map(item => item.item_id)).size === slots.length && new Set(value.items.map(item => item.slot_id)).size === slots.length);
  const imageIdentities = new Map<string, string>();
  value.items.forEach(item => {
    need(item && positive(item.item_id) && monthlySlotMatches(item, month, rules) && positive(item.revision) && text(item.title) && item.title.length > 0 && item.title.length <= 200 && text(item.content) && item.content.length > 0 && item.content.length <= 1500 && text(item.owner_summary) && item.owner_summary.length > 0 && item.owner_summary.length <= 300 && hash(item.copy_hash) && optionalId(item.material_id) && (item.image_version_id === null || imageId(item.image_version_id)) && (item.image_sha256 === null || hash(item.image_sha256)) && strings(item.quality_warnings) && optionalId(item.task_id));
    need(item.publication_image === null || positive(item.material_id) && !!verifiedPublicationImage(item.publication_image, customerId, item.material_id) && item.publication_image.id === item.image_version_id && item.publication_image.image_sha256 === item.image_sha256, '实际配图与本月审核清单不一致，请重新核对。');
    if (item.publication_image) {
      const image = item.publication_image;
      const identity = JSON.stringify([image.customer_id, image.material_id, image.source_sha256, image.image_sha256, image.width, image.height, image.byte_size, image.rights_basis, image.status, image.preview_path]);
      need(!imageIdentities.has(image.id) || imageIdentities.get(image.id) === identity, '同一图片版本的核对资料不一致，请重新读取。');
      imageIdentities.set(image.id, identity);
    }
    const schedule = item.schedule;
    need(schedule === null || schedule && positive(schedule.id) && positive(schedule.revision) && positive(item.task_id) && schedule.task_id === item.task_id && !!binding && schedule.binding_id === binding.id && schedule.timezone === item.timezone && instant(schedule.planned_at) && Date.parse(schedule.planned_at) === Date.parse(item.proposed_publish_at) && scheduleStates.has(schedule.status) && text(schedule.message) && (schedule.action_id === null || uuid(schedule.action_id)), '正式排期与当前门店、任务或建议日期不一致。');
  });
  verifyMaterials(value.materials, customerId);
  need(value.delivery && typeof value.delivery.enabled === 'boolean' && typeof value.delivery.can_manage === 'boolean' && text(value.delivery.notice) && optionalInstant(value.delivery.activated_at) && value.scheduler && typeof value.scheduler.enabled === 'boolean' && optionalInstant(value.scheduler.activation_from));
  need(Array.isArray(value.checks) && value.checks.length <= 100 && value.checks.every(check => check && text(check.key) && ['ready', 'blocked', 'pending'].includes(check.state) && text(check.message)) && new Set(value.checks.map(check => check.key)).size === value.checks.length);
  need(Array.isArray(value.alerts) && value.alerts.length <= 100 && value.alerts.every(alert => alert && text(alert.key) && text(alert.version) && alert.run_id === runId && ['warning', 'error'].includes(alert.level) && text(alert.status) && text(alert.title) && text(alert.message) && optionalId(alert.item_id) && optionalId(alert.task_id) && optionalId(alert.schedule_id) && nullableText(alert.action_id)) && new Set(value.alerts.map(alert => alert.key)).size === value.alerts.length);
  need(value.counts && ['total', 'scheduled', 'succeeded', 'blocked', 'unknown', 'missed', 'cancelled'].every(key => count(value.counts[key as keyof MonthlyWorkflow['counts']]) && value.counts[key as keyof MonthlyWorkflow['counts']] <= slots.length) && value.counts.total === slots.length);
  need(value.capabilities?.is_owner === true && ['can_prepare', 'can_review', 'can_schedule', 'can_cancel'].every(key => typeof value.capabilities[key as keyof MonthlyWorkflow['capabilities']] === 'boolean'));
  const receipt = value.request_receipt;
  need(receipt === undefined || receipt && uuid(receipt.request_id) && kinds.has(receipt.kind) && positive(receipt.workflow_revision) && hash(receipt.result_hash));
  return value;
}

export function monthlyWorkflowImages(value: MonthlyWorkflow): PublicationImage[] {
  const result = new Map<string, PublicationImage>();
  value.items.forEach(item => { if (item.publication_image) result.set(`${item.publication_image.id}:${item.publication_image.image_sha256}`, item.publication_image); });
  return [...result.values()];
}

export function monthlyWorkflowCopiesMatch(before: MonthlyWorkflow, after: MonthlyWorkflow): boolean {
  return before.items.length === after.items.length && before.items.every(item => {
    const result = after.items.find(candidate => candidate.item_id === item.item_id);
    return !!result && result.title === item.title && result.content === item.content && result.owner_summary === item.owner_summary && result.copy_hash === item.copy_hash && result.proposed_publish_at === item.proposed_publish_at && result.timezone === item.timezone;
  });
}

export function monthlyWorkflowMutationMatches(after: MonthlyWorkflow, before: MonthlyWorkflow, mutation: MonthlyWorkflowMutation): boolean {
  const receipt = after.request_receipt, packet = after.workflow;
  if (after.customer_id !== before.customer_id || after.month !== before.month || after.run_id !== before.run_id || !receipt || receipt.request_id !== mutation.body.request_id || receipt.kind !== mutation.kind || !packet || receipt.workflow_revision !== packet.revision || !monthlyWorkflowCopiesMatch(before, after)) return false;
  if (mutation.kind === 'prepare') return packet.status === 'prepared' && packet.revision > mutation.body.expected_workflow_revision && after.items.every(item => mutation.body.items.some(selected => selected.item_id === item.item_id && selected.image_version_id === item.image_version_id));
  if (packet.revision <= mutation.body.expected_revision || mutation.kind !== 'cancel' && packet.preview_hash !== mutation.body.preview_hash) return false;
  if (mutation.kind === 'review') return packet.status === 'reviewed' && after.items.every(item => positive(item.task_id) && item.schedule === null);
  if (mutation.kind === 'schedule') return packet.status === 'scheduled' && after.items.every(item => item.schedule !== null && ['scheduled', 'dispatching', 'pending', 'accepted', 'succeeded'].includes(item.schedule.status));
  return packet.status === 'cancelled' && after.items.every(item => {
    const original = before.items.find(candidate => candidate.item_id === item.item_id);
    if (!original || original.task_id !== item.task_id) return false;
    if (!original.schedule) return item.schedule === null;
    return !!item.schedule && item.schedule.id === original.schedule.id && item.schedule.task_id === original.schedule.task_id && item.schedule.binding_id === original.schedule.binding_id && item.schedule.planned_at === original.schedule.planned_at && item.schedule.timezone === original.schedule.timezone && item.schedule.status !== 'scheduled';
  });
}

export async function monthlyWorkflowApi<T>(path: string, method: 'GET' | 'POST' = 'GET', data?: unknown, signal?: AbortSignal): Promise<T> {
  const response = await invokeWithAuth({ url: `/api/v1/media-monthly${path}`, method, ...(data === undefined ? {} : { data }), ...(signal ? { options: { signal } } : {}) });
  return response.data as T;
}
