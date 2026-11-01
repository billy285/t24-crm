import { invokeWithAuth } from './tokenStore';
import { verifiedPublicationImage, type PublicationImage } from './media-publication-images';

export const MONTHLY_PILOT_CUSTOMER_ID = 20;
export const MONTHLY_PILOT_MONTH = '2026-11';
export type MonthlyFacts = { public_name: string; location: string; highlights: string[] };
export type MonthlyRules = { timezone: string; weekdays: number[]; local_time: string; posts_per_week: number; language: 'en' | 'zh_en'; forbidden_claims: string[]; include_prices: boolean; generic_mode: boolean };
export type MonthlyImageSelection = { material_id: number; image_version_id: string | null; menu_item_id: number | null; quality_confirmed?: boolean };
export type MonthlyProfile = { id: number; customer_id: number; revision: number; public_facts: MonthlyFacts; rules: MonthlyRules; menu_item_ids: number[]; images: MonthlyImageSelection[] };
export type MonthlyProfileInput = Omit<MonthlyProfile, 'id' | 'customer_id' | 'revision'> & { expected_revision: number; confirmed_facts: true };
export type MonthlyMenu = { id: number; name: string; category: string | null; price: string | null; selling_points: string | null; status: string | null; fingerprint: string };
export type MonthlyMaterial = { id: number; title: string; linked_item_id: number | null; approval_status: string | null; copyright_status: string | null; image_versions: PublicationImage[]; fingerprint: string; width: number | null; height: number | null; quality_warning: string | null; needs_quality_confirmation: boolean };
export type MonthlySetup = { month?: string; slots?: { slot_id: string; proposed_publish_at: string; timezone: string }[]; customer: { id: number; name: string }; profile: MonthlyProfile | null; menu_items: MonthlyMenu[]; materials: MonthlyMaterial[]; runtime: { enabled: boolean; provider: string; model: string; destination_host: string; fingerprint: string }; input_hash: string | null; gaps: string[]; capabilities: { is_owner: true; can_generate: boolean; cooperation_active?: boolean; read_only_reason?: string | null }; notice: { version: 'monthly-text-v1'; text: string; send_fields?: string[] } };
export type MonthlyItem = { id: number; slot_id: string; title: string; content: string; proposed_publish_at: string; timezone: string; material_id: number | null; image_version_id: string | null; image_sha256: string | null; menu_item_ids: number[]; revision: number; copy_hash: string; task_id: number | null; quality_warnings: string[]; owner_summary: string };
export type MonthlyRun = { id: number; customer_id: number; month: string; status: 'generating' | 'generated' | 'failed' | 'unknown' | 'adopted'; revision: number; input_hash: string; ai_used: boolean; message: string; profile_snapshot: { public_facts: MonthlyFacts; rules: MonthlyRules }; items: MonthlyItem[]; preview_hash: string | null; adoptable: boolean; canonical_request_id: string };
export type MonthlyConsent = { confirmed: true; notice_version: 'monthly-text-v1'; input_hash: string; runtime_fingerprint: string };
export type MonthlyCreate = { request_id: string; expected_profile_revision: number; month: string; input_hash: string; consent: MonthlyConsent };
export const validMonthlyMonth = (value: unknown): value is string => typeof value === 'string' && /^(20\d{2})-(0[1-9]|1[0-2])$/.test(value);
export function currentMonthlyMonth(): string { return new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit' }).format(new Date()).slice(0, 7); }
export function monthlySlotIds(month: string, rules: MonthlyRules): string[] {
  if (!validMonthlyMonth(month)) return [];
  const [year, number] = month.split('-').map(Number), last = new Date(Date.UTC(year, number, 0)).getUTCDate();
  return Array.from({ length: last }, (_, index) => index + 1).filter(day => rules.weekdays.includes(new Date(Date.UTC(year, number - 1, day)).getUTCDay() || 7)).map(day => `${month.replace('-', '')}${String(day).padStart(2, '0')}`);
}
export function monthlySlotMatches(item: { slot_id: string; proposed_publish_at: string; timezone: string }, month: string, rules: MonthlyRules): boolean {
  if (item.timezone !== rules.timezone || !instant(item.proposed_publish_at) || !monthlySlotIds(month, rules).includes(item.slot_id)) return false;
  try {
    const parts = new Intl.DateTimeFormat('en-CA', { timeZone: rules.timezone, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23' }).formatToParts(new Date(item.proposed_publish_at));
    const get = (key: string) => parts.find(part => part.type === key)?.value;
    return `${get('year')}${get('month')}${get('day')}` === item.slot_id && `${get('hour')}:${get('minute')}` === rules.local_time && get('second') === '00' && new Date(item.proposed_publish_at).getUTCMilliseconds() === 0;
  } catch { return false; }
}
const positive = (value: unknown): value is number => Number.isSafeInteger(value) && Number(value) > 0;
const text = (value: unknown): value is string => typeof value === 'string';
const nullableText = (value: unknown) => value === null || text(value);
const hash = (value: unknown): value is string => text(value) && /^[a-f0-9]{64}$/.test(value);
const ids = (value: unknown): value is number[] => Array.isArray(value) && value.length <= 100 && value.every(positive) && new Set(value).size === value.length;
const list = (value: unknown): value is string[] => Array.isArray(value) && value.length <= 100 && value.every(text);
const instant = (value: unknown): value is string => text(value) && /(?:Z|[+-]\d{2}:\d{2})$/.test(value) && Number.isFinite(Date.parse(value));
function need(value: unknown, message = '月度准备资料不完整，请重新读取。'): asserts value { if (!value) throw new Error(message); }
export function monthlyFacts(value: MonthlyFacts): MonthlyFacts { need(value && text(value.public_name) && text(value.location) && list(value.highlights)); return value; }
export function monthlyRules(value: MonthlyRules): MonthlyRules {
  need(value && text(value.timezone) && value.timezone.length <= 100 && Array.isArray(value.weekdays) && value.weekdays.length >= 1 && value.weekdays.length <= 7 && value.weekdays.every(day => Number.isSafeInteger(day) && day >= 1 && day <= 7) && new Set(value.weekdays).size === value.weekdays.length && typeof value.local_time === 'string' && /^([01]\d|2[0-3]):[0-5]\d$/.test(value.local_time) && value.posts_per_week === value.weekdays.length && ['en', 'zh_en'].includes(value.language) && list(value.forbidden_claims) && typeof value.include_prices === 'boolean' && typeof value.generic_mode === 'boolean');
  try { new Intl.DateTimeFormat('en-US', { timeZone: value.timezone }).format(); } catch { need(false, '门店时区无效，请重新核对。'); }
  return value;
}
export function monthlyImageSelection(value: MonthlyImageSelection): MonthlyImageSelection { need(value && positive(value.material_id) && (value.image_version_id === null || text(value.image_version_id) && /^[a-f0-9]{32}$/.test(value.image_version_id)) && (value.menu_item_id === null || positive(value.menu_item_id)) && (value.quality_confirmed === undefined || typeof value.quality_confirmed === 'boolean')); return value; }
export function verifiedMonthlySetup(value: MonthlySetup, customerId: number, expectedMonth?: string): MonthlySetup {
  need(positive(customerId) && value && value.customer?.id === customerId && text(value.customer.name) && value.capabilities?.is_owner === true && typeof value.capabilities.can_generate === 'boolean', '当前月度准备仅向老板开放，并须匹配当前商家。');
  need(expectedMonth === undefined || validMonthlyMonth(expectedMonth) && value.month === expectedMonth, '准备资料与当前工作月份不一致，请重新读取。');
  need((value.capabilities.cooperation_active === undefined || typeof value.capabilities.cooperation_active === 'boolean') && (value.capabilities.read_only_reason === undefined || nullableText(value.capabilities.read_only_reason)) && (value.capabilities.cooperation_active !== false || value.capabilities.can_generate === false), '客户合作状态与月度操作范围不一致，请重新核对。');
  need(value.profile === null || positive(value.profile.id) && value.profile.customer_id === customerId && positive(value.profile.revision) && !!monthlyFacts(value.profile.public_facts) && !!monthlyRules(value.profile.rules) && ids(value.profile.menu_item_ids) && Array.isArray(value.profile.images) && value.profile.images.length <= 50 && value.profile.images.every(monthlyImageSelection));
  need(Array.isArray(value.menu_items) && value.menu_items.length <= 1000 && value.menu_items.every(item => item && positive(item.id) && text(item.name) && nullableText(item.category) && nullableText(item.price) && nullableText(item.selling_points) && nullableText(item.status) && hash(item.fingerprint)) && new Set(value.menu_items.map(item => item.id)).size === value.menu_items.length);
  need(Array.isArray(value.materials) && value.materials.length <= 200 && value.materials.every(item => item && positive(item.id) && text(item.title) && (item.linked_item_id === null || positive(item.linked_item_id)) && nullableText(item.approval_status) && nullableText(item.copyright_status) && hash(item.fingerprint) && Array.isArray(item.image_versions) && item.image_versions.length <= 100 && item.image_versions.every(image => !!verifiedPublicationImage(image, customerId, item.id)) && (item.width === null || positive(item.width)) && (item.height === null || positive(item.height)) && nullableText(item.quality_warning) && typeof item.needs_quality_confirmation === 'boolean') && new Set(value.materials.map(item => item.id)).size === value.materials.length);
  need(value.runtime && typeof value.runtime.enabled === 'boolean' && text(value.runtime.provider) && text(value.runtime.model) && text(value.runtime.destination_host) && hash(value.runtime.fingerprint) && (value.input_hash === null || hash(value.input_hash)) && list(value.gaps) && value.notice?.version === 'monthly-text-v1' && text(value.notice.text) && (value.notice.send_fields === undefined || list(value.notice.send_fields)));
  return value;
}
export function verifiedMonthlyRun(value: MonthlyRun, customerId: number, expectedId?: number, expectedMonth?: string): MonthlyRun {
  need(value && positive(value.id) && (expectedId === undefined || value.id === expectedId) && value.customer_id === customerId && positive(customerId) && validMonthlyMonth(value.month) && (expectedMonth === undefined || value.month === expectedMonth) && ['generating', 'generated', 'failed', 'unknown', 'adopted'].includes(value.status) && positive(value.revision) && hash(value.input_hash) && typeof value.ai_used === 'boolean' && typeof value.adoptable === 'boolean' && text(value.canonical_request_id) && /^[a-f0-9-]{36}$/.test(value.canonical_request_id) && text(value.message) && value.profile_snapshot && !!monthlyFacts(value.profile_snapshot.public_facts) && !!monthlyRules(value.profile_snapshot.rules), '草案与当前商家或月份不一致，请重新核对。');
  need(Array.isArray(value.items) && value.items.length <= 31 && (!['generated', 'adopted'].includes(value.status) || value.items.length === monthlySlotIds(value.month, value.profile_snapshot.rules).length) && value.items.every(item => item && positive(item.id) && text(item.slot_id) && monthlySlotMatches(item, value.month, value.profile_snapshot.rules) && text(item.title) && text(item.content) && instant(item.proposed_publish_at) && item.timezone === value.profile_snapshot.rules.timezone && (item.material_id === null || positive(item.material_id)) && (item.image_version_id === null || text(item.image_version_id) && /^[a-f0-9]{32}$/.test(item.image_version_id)) && (item.image_sha256 === null || hash(item.image_sha256)) && ids(item.menu_item_ids) && positive(item.revision) && hash(item.copy_hash) && (item.task_id === null || positive(item.task_id)) && list(item.quality_warnings) && text(item.owner_summary)) && new Set(value.items.map(item => item.id)).size === value.items.length && new Set(value.items.map(item => item.slot_id)).size === value.items.length && (value.preview_hash === null || hash(value.preview_hash)));
  if (value.status === 'adopted') need(value.items.every(item => positive(item.task_id)), '草案尚未完整关联任务，请读取原请求结果。');
  return value;
}
export function verifiedMonthlyRuns(value: { items: MonthlyRun[] }, customerId: number, expectedMonth?: string) { need(value && Array.isArray(value.items) && value.items.length <= 50 && new Set(value.items.map(run => run.id)).size === value.items.length); value.items.forEach(run => verifiedMonthlyRun(run, customerId, undefined, expectedMonth)); return value; }
export async function monthlyApi<T>(path: string, method: 'GET' | 'POST' | 'PUT' | 'PATCH' = 'GET', data?: unknown, signal?: AbortSignal): Promise<T> {
  const options = { ...(signal ? { signal } : {}), ...(method === 'POST' && /^\/customers\/[1-9]\d*\/runs$/.test(path) ? { timeout: 150_000 } : {}) };
  const response = await invokeWithAuth({ url: `/api/v1/media-monthly${path}`, method, ...(data === undefined ? {} : { data }), ...(Object.keys(options).length ? { options } : {}) });
  return response.data as T;
}
export function profileMatches(profile: MonthlyProfile | null, body: MonthlyProfileInput): boolean { if (!profile || profile.revision <= body.expected_revision) return false; const normalized = (value: unknown): unknown => Array.isArray(value) ? value.map(normalized) : value && typeof value === 'object' ? Object.fromEntries(Object.entries(value).filter(([, v]) => v !== undefined).sort(([a], [b]) => a.localeCompare(b)).map(([key, item]) => [key, normalized(item)])) : value; return JSON.stringify(normalized({ public_facts: profile.public_facts, rules: profile.rules, menu_item_ids: profile.menu_item_ids, images: profile.images })) === JSON.stringify(normalized({ public_facts: body.public_facts, rules: body.rules, menu_item_ids: body.menu_item_ids, images: body.images })); }
