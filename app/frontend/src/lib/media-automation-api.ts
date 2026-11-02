import { monthlyApi, validMonthlyMonth, validMonthlyPlatform, type MonthlyPlatform } from './media-monthly-api';

export type AutomationJobStatus = 'running' | 'generated' | 'existing' | 'blocked' | 'unknown' | 'failed' | 'missed';
export type AutomationJob = { id: number; request_id: string; month: string; status: AutomationJobStatus; run_id: number | null; message: string; created_at: string; updated_at: string };
export type AutomationPolicy = { id: number; revision: number; enabled: boolean; lead_days: number; timezone: string; local_time: '09:00'; profile_revision: number; source_signature: string; runtime_fingerprint: string; confirmed_at: string | null; updated_at: string };
export type AutomationSetup = {
  customer: { id: number; name: string }; platform: MonthlyPlatform; policy: AutomationPolicy | null;
  next_target_month: string; next_run_at: string | null; timezone: string | null; source_signature: string | null;
  runtime: { enabled: boolean; provider: string; model: string; destination_host: string; fingerprint: string | null };
  notice: { version: 'monthly-autoprep-v1'; text: string; send_fields: string[] };
  eligibility: { can_enable: boolean; gaps: string[] };
  worker: { enabled: boolean; max_per_tick: number; owner_daily_limit: number; global_daily_limit: number };
  latest_job: AutomationJob | null; recent_jobs: AutomationJob[]; automatic_publish: false; receipt_request_id?: string;
};
export type AutomationSave = { request_id: string; expected_revision: number; enabled: boolean; lead_days: number; local_time: '09:00'; source_signature: string; runtime_fingerprint: string; confirmed: boolean; notice_version: 'monthly-autoprep-v1' };
export type AutomationReceipt = { request_id: string; customer_id: number; platform: MonthlyPlatform; result: AutomationSetup; current_revision: number };
export type AutomationOverviewJob = AutomationJob & { customer_id: number; customer_name: string; platform: MonthlyPlatform };
export type AutomationOverview = { automatic_publish: false; worker: AutomationSetup['worker']; period_start: string; period_end: string; counts: { policies: number; enabled: number; blocked: number; unknown: number; generated: number }; recent_jobs: AutomationOverviewJob[]; attention_jobs: AutomationOverviewJob[]; attention_total: number };

const positive = (value: unknown): value is number => Number.isSafeInteger(value) && Number(value) > 0;
const count = (value: unknown): value is number => Number.isSafeInteger(value) && Number(value) >= 0;
const text = (value: unknown): value is string => typeof value === 'string';
const hash = (value: unknown): value is string => text(value) && /^[a-f0-9]{64}$/.test(value);
const uuid = (value: unknown): value is string => text(value) && /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i.test(value);
const instant = (value: unknown): value is string => text(value) && /(?:Z|[+-]\d{2}:\d{2})$/.test(value) && Number.isFinite(Date.parse(value));
const strings = (value: unknown): value is string[] => Array.isArray(value) && value.length <= 100 && value.every(text);
const zone = (value: unknown) => { if (!text(value)) return false; try { new Intl.DateTimeFormat('en-US', { timeZone: value }).format(); return true; } catch { return false; } };
function need(value: unknown, message = '自动准备资料尚未完整返回，请重新读取。'): asserts value { if (!value) throw new Error(message); }

export function verifiedAutomationJob(value: AutomationJob): AutomationJob {
  need(value && positive(value.id) && uuid(value.request_id) && validMonthlyMonth(value.month) && ['running', 'generated', 'existing', 'blocked', 'unknown', 'failed', 'missed'].includes(value.status) && (value.run_id === null || positive(value.run_id)) && text(value.message) && instant(value.created_at) && instant(value.updated_at));
  if (value.status === 'generated' || value.status === 'existing') need(positive(value.run_id), '自动准备结果尚未关联原月度草案。');
  return value;
}
export function verifiedAutomationSetup(value: AutomationSetup, customerId: number, platform: MonthlyPlatform): AutomationSetup {
  need(value && positive(customerId) && value.customer?.id === customerId && text(value.customer.name) && validMonthlyPlatform(platform) && value.platform === platform && value.automatic_publish === false, '自动准备范围与当前商家或平台不一致。');
  need(value.policy === null || value.policy && positive(value.policy.id) && positive(value.policy.revision) && typeof value.policy.enabled === 'boolean' && Number.isSafeInteger(value.policy.lead_days) && value.policy.lead_days >= 3 && value.policy.lead_days <= 14 && zone(value.policy.timezone) && value.policy.local_time === '09:00' && positive(value.policy.profile_revision) && hash(value.policy.source_signature) && hash(value.policy.runtime_fingerprint) && (value.policy.confirmed_at === null || instant(value.policy.confirmed_at)) && instant(value.policy.updated_at));
  need(validMonthlyMonth(value.next_target_month) && (value.next_run_at === null || instant(value.next_run_at)) && (value.timezone === null || zone(value.timezone)) && (value.source_signature === null || hash(value.source_signature)));
  need(value.runtime && typeof value.runtime.enabled === 'boolean' && text(value.runtime.provider) && text(value.runtime.model) && text(value.runtime.destination_host) && (value.runtime.fingerprint === null || hash(value.runtime.fingerprint)) && value.notice?.version === 'monthly-autoprep-v1' && text(value.notice.text) && strings(value.notice.send_fields));
  need(value.eligibility && typeof value.eligibility.can_enable === 'boolean' && strings(value.eligibility.gaps) && (!value.eligibility.can_enable || value.runtime.enabled && hash(value.runtime.fingerprint) && hash(value.source_signature)));
  need(value.worker && typeof value.worker.enabled === 'boolean' && positive(value.worker.max_per_tick) && positive(value.worker.owner_daily_limit) && positive(value.worker.global_daily_limit));
  need((value.latest_job === null || !!verifiedAutomationJob(value.latest_job)) && Array.isArray(value.recent_jobs) && value.recent_jobs.length <= 12 && value.recent_jobs.every(row => !!verifiedAutomationJob(row)) && new Set(value.recent_jobs.map(row => row.id)).size === value.recent_jobs.length);
  need(value.receipt_request_id === undefined || uuid(value.receipt_request_id));
  return value;
}
export function verifiedAutomationSaved(value: AutomationSetup, customerId: number, platform: MonthlyPlatform, body: AutomationSave): AutomationSetup {
  const result = verifiedAutomationSetup(value, customerId, platform);
  need(result.receipt_request_id === body.request_id && result.policy && result.policy.revision === body.expected_revision + 1 && result.policy.enabled === body.enabled && result.policy.lead_days === body.lead_days && result.policy.local_time === body.local_time, '自动准备保存回执与本次规则不一致，请查询原请求。');
  if (body.enabled) need(result.policy.source_signature === body.source_signature && result.policy.runtime_fingerprint === body.runtime_fingerprint, '本次自动准备使用的资料或文字服务已变化，请查询原请求。');
  return result;
}
export function verifiedAutomationReceipt(value: AutomationReceipt, customerId: number, platform: MonthlyPlatform, body: AutomationSave): AutomationReceipt {
  need(value && value.request_id === body.request_id && value.customer_id === customerId && value.platform === platform && count(value.current_revision), '原保存回执与当前商家或平台不一致。');
  verifiedAutomationSaved({ ...value.result, receipt_request_id: value.request_id }, customerId, platform, body);
  need(value.current_revision >= value.result.policy!.revision, '自动准备规则版本尚未核实。');
  return value;
}
export async function readAutomation(customerId: number, platform: MonthlyPlatform, signal?: AbortSignal) { return verifiedAutomationSetup(await monthlyApi<AutomationSetup>(`/customers/${customerId}/automation?platform=${platform}`, 'GET', undefined, signal), customerId, platform); }
export async function saveAutomation(customerId: number, platform: MonthlyPlatform, body: AutomationSave) { return verifiedAutomationSaved(await monthlyApi<AutomationSetup>(`/customers/${customerId}/automation?platform=${platform}`, 'PUT', body), customerId, platform, body); }
export async function recoverAutomation(customerId: number, platform: MonthlyPlatform, body: AutomationSave) { return verifiedAutomationReceipt(await monthlyApi<AutomationReceipt>(`/automation/requests/${body.request_id}`), customerId, platform, body); }

export function verifiedAutomationOverview(value: AutomationOverview): AutomationOverview {
  need(value && value.automatic_publish === false && value.worker && typeof value.worker.enabled === 'boolean' && positive(value.worker.max_per_tick) && positive(value.worker.owner_daily_limit) && positive(value.worker.global_daily_limit));
  need(instant(value.period_start) && instant(value.period_end) && Date.parse(value.period_end) > Date.parse(value.period_start) && value.counts && ['policies', 'enabled', 'blocked', 'unknown', 'generated'].every(key => count(value.counts[key as keyof AutomationOverview['counts']])) && value.counts.enabled <= value.counts.policies);
  const jobs = (rows: AutomationOverviewJob[]) => Array.isArray(rows) && rows.length <= 20 && rows.every(job => !!verifiedAutomationJob(job) && positive(job.customer_id) && text(job.customer_name) && validMonthlyPlatform(job.platform)) && new Set(rows.map(job => job.id)).size === rows.length;
  need(jobs(value.recent_jobs) && jobs(value.attention_jobs) && value.attention_jobs.every(job => ['blocked', 'unknown', 'failed', 'missed'].includes(job.status)) && count(value.attention_total) && value.attention_total === value.counts.blocked + value.counts.unknown && value.attention_total >= value.attention_jobs.length);
  return value;
}

export const automationJobLabels: Record<AutomationJobStatus, string> = { running: '正在准备', generated: '草案已生成 · 等待审核', existing: '沿用已有草案', blocked: '资料需核对', unknown: '生成结果待核对', failed: '准备未成功', missed: '已错过准备窗口' };
/** Current confirmed merchant zone also exists before the first policy is saved. */
export const automationTimezone = (value: AutomationSetup): string => value.timezone || value.policy?.timezone || 'UTC';
/** The server's next target uses this merchant's confirmed zone, not the browser's month. */
export function automationCurrentMonth(value: AutomationSetup): string {
  const [year, month] = value.next_target_month.split('-').map(Number), previous = new Date(Date.UTC(year, month - 2, 1));
  return `${previous.getUTCFullYear()}-${String(previous.getUTCMonth() + 1).padStart(2, '0')}`;
}
export function automationState(value: AutomationSetup): { label: string; tone: 'ready' | 'waiting' | 'warning' | 'neutral' } {
  if (value.policy?.enabled && (!value.eligibility.can_enable || value.policy.source_signature !== value.source_signature || value.policy.runtime_fingerprint !== value.runtime.fingerprint)) return { label: '资料变化 · 等待核对', tone: 'warning' };
  if (value.latest_job && ['blocked', 'unknown', 'failed', 'missed'].includes(value.latest_job.status)) return { label: '需要处理', tone: 'warning' };
  if (value.latest_job && ['generated', 'existing'].includes(value.latest_job.status)) return { label: '草案待审核', tone: 'waiting' };
  if (value.policy?.enabled && value.worker.enabled && value.eligibility.can_enable) return { label: '自动准备已开启', tone: 'ready' };
  if (value.policy?.enabled && !value.worker.enabled) return { label: '规则已保存 · 服务待启用', tone: 'waiting' };
  if (value.policy?.enabled) return { label: '资料变化 · 等待核对', tone: 'warning' };
  return { label: value.policy ? '自动准备已暂停' : '自动准备未设置', tone: 'neutral' };
}
