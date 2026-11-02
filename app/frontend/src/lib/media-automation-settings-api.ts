import { invokeWithAuth } from './tokenStore';
import { validMonthlyMonth, validMonthlyPlatform, type MonthlyPlatform } from './media-monthly-api';

export type SettingsIndustry = 'restaurant' | 'beauty' | 'general';
export type SettingsGroup = 'cadence' | 'writing' | 'content';
export type SettingsRules = {
  weekdays: number[]; local_time: string; language: 'en' | 'zh_en'; include_prices: boolean;
  forbidden_claims: string[]; content_mix: { featured: number; discovery: number; business: number };
  tone: 'friendly' | 'professional' | 'lively';
};
export type SettingsDocument = {
  industry: SettingsIndustry; timezone: string | null; defaults: SettingsRules;
  platform_overrides: Partial<Record<MonthlyPlatform, Partial<SettingsRules>>>;
  template_key?: string; template_revision?: number;
};
export type SettingsVersion = { revision: number; effective_from_month: string; document: SettingsDocument; created_at: string };
export type UnifiedSettings = {
  customer: { id: number; name: string; cooperation_active: boolean }; revision: number;
  version: SettingsVersion | null; effective_version: SettingsVersion | null; document: SettingsDocument;
  sources: { platform: MonthlyPlatform; profile_ready: boolean; menu_count: number; image_count: number; timezone: string | null }[];
  month: string; new_batches_only: true; publications_changed: false;
};
export type SettingsTemplate = { id: string; revision: number; name: string; builtin: boolean; document: SettingsDocument };
export type SettingsCustomer = { id: number; name: string; industry: SettingsIndustry };
export type SettingsPreviewBody = {
  request_id: string; kind: 'edit' | 'copy'; month: string; customer_id: number; expected_revision: number;
  document?: SettingsDocument; target_ids: number[]; platforms: MonthlyPlatform[]; groups: SettingsGroup[];
};
export type SettingsImpact = {
  customer_id: number; name: string; before_revision: number; after_revision: number; effective_from_month: string;
  document_after: SettingsDocument; changed_fields: string[];
  platforms: { platform: MonthlyPlatform; before_count: number | null; proposed_count: number | null; timezone: string | null; existing_batches: number; source_ready: boolean; content_mix: SettingsRules['content_mix'] }[];
  protected: { batches: number; reviewed: number; scheduled: number }; auto_policies_need_reconfirmation: number;
  accounts_materials_permissions_copied: false;
};
export type SettingsPreview = {
  id: string; request_id: string; preview_hash: string; expires_at: string; kind: 'edit' | 'copy'; month: string;
  targets: SettingsImpact[]; new_batches_only: true; publications_changed: false; menus_images_accounts_permissions_copied: false;
};
export type SettingsApplyBody = { request_id: string; preview_hash: string; confirmed: true };
export type SettingsSaved = {
  request_id: string; preview_id: string; saved: { customer_id: number; revision: number; effective_from_month: string }[];
  new_batches_only: true; existing_batches_changed: false; publications_changed: false;
};
export type SettingsTemplateBody = { request_id: string; name: string; document: SettingsDocument };
export type SettingsTemplateSaved = { request_id: string; template: SettingsTemplate; customers_changed: false };

export const settingsIndustries = [{ value: 'restaurant', label: '餐厅' }, { value: 'beauty', label: '美业' }, { value: 'general', label: '通用' }] as const;
export const settingsGroups = [{ value: 'cadence', label: '发布频率与时间' }, { value: 'writing', label: '语言、语气、价格与禁写内容' }, { value: 'content', label: '内容比例' }] as const;
const platforms: MonthlyPlatform[] = ['google_business', 'facebook', 'instagram'];
const ruleKeys = ['weekdays', 'local_time', 'language', 'include_prices', 'forbidden_claims', 'content_mix', 'tone'];
const positive = (v: unknown): v is number => Number.isSafeInteger(v) && Number(v) > 0;
const count = (v: unknown): v is number => Number.isSafeInteger(v) && Number(v) >= 0;
const text = (v: unknown): v is string => typeof v === 'string';
const uuid = (v: unknown): v is string => text(v) && /^[a-f\d]{8}-[a-f\d]{4}-[a-f\d]{4}-[a-f\d]{4}-[a-f\d]{12}$/i.test(v);
const hash = (v: unknown): v is string => text(v) && /^[a-f\d]{64}$/.test(v);
const instant = (v: unknown) => text(v) && /(?:Z|[+-]\d{2}:\d{2})$/.test(v) && Number.isFinite(Date.parse(v));
const zone = (v: unknown) => { if (!text(v)) return false; try { new Intl.DateTimeFormat('en', { timeZone: v }).format(); return true; } catch { return false; } };
const record = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
const industry = (v: unknown) => settingsIndustries.some(row => row.value === v);
const unique = (v: unknown[]) => new Set(v).size === v.length;
function need(v: unknown, message = '自动化设置返回不完整，请重新读取。'): asserts v { if (!v) throw new Error(message); }
const keysOnly = (value: Record<string, unknown>, keys: string[]) => Object.keys(value).every(key => keys.includes(key));

export function verifiedSettingsRules(value: SettingsRules): SettingsRules {
  need(record(value) && keysOnly(value, ruleKeys));
  need(Array.isArray(value.weekdays) && value.weekdays.length >= 1 && value.weekdays.length <= 7 && unique(value.weekdays) && value.weekdays.every(day => Number.isSafeInteger(day) && day >= 1 && day <= 7), '请选择不重复的周一至周日，至少一天。');
  need(text(value.local_time) && /^(?:[01]\d|2[0-3]):[0-5]\d$/.test(value.local_time), '请选择有效的当地发布时间。');
  need(['en', 'zh_en'].includes(value.language) && ['friendly', 'professional', 'lively'].includes(value.tone) && typeof value.include_prices === 'boolean');
  need(Array.isArray(value.forbidden_claims) && value.forbidden_claims.length <= 20 && value.forbidden_claims.every(row => text(row) && row.trim().length > 0 && row.length <= 100), '禁写内容最多20项，每项1—100字。');
  need(record(value.content_mix) && keysOnly(value.content_mix, ['featured', 'discovery', 'business']) && ['featured', 'discovery', 'business'].every(key => count(value.content_mix[key as keyof SettingsRules['content_mix']]) && value.content_mix[key as keyof SettingsRules['content_mix']] <= 100) && Object.values(value.content_mix).reduce((total, n) => total + n, 0) === 100, '三类内容比例合计须为100%。');
  return value;
}
export function verifiedSettingsDocument(value: SettingsDocument): SettingsDocument {
  need(record(value) && keysOnly(value, ['industry', 'timezone', 'defaults', 'platform_overrides', 'template_key', 'template_revision']) && industry(value.industry) && (value.timezone === null || zone(value.timezone)) && record(value.platform_overrides));
  verifiedSettingsRules(value.defaults);
  for (const [platform, override] of Object.entries(value.platform_overrides)) { need(validMonthlyPlatform(platform) && record(override) && keysOnly(override, ruleKeys)); verifiedSettingsRules({ ...value.defaults, ...override }); }
  need(value.template_key === undefined || text(value.template_key) && value.template_key.length > 0 && value.template_key.length <= 80);
  need(value.template_revision === undefined || positive(value.template_revision));
  return value;
}
const verifiedVersion = (value: SettingsVersion | null) => value === null || value && positive(value.revision) && validMonthlyMonth(value.effective_from_month) && instant(value.created_at) && !!verifiedSettingsDocument(value.document);
export function verifiedUnifiedSettings(value: UnifiedSettings, customerId: number, month: string): UnifiedSettings {
  need(value && value.customer?.id === customerId && positive(customerId) && text(value.customer.name) && typeof value.customer.cooperation_active === 'boolean' && count(value.revision) && value.month === month && validMonthlyMonth(month) && value.new_batches_only === true && value.publications_changed === false, '自动化设置与当前商家或月份不一致。');
  verifiedSettingsDocument(value.document); need(verifiedVersion(value.version) && verifiedVersion(value.effective_version));
  need((value.version?.revision || 0) === value.revision && (!value.effective_version || value.effective_version.revision <= value.revision && value.effective_version.effective_from_month <= month));
  need(Array.isArray(value.sources) && value.sources.length === 3 && unique(value.sources.map(row => row.platform)) && value.sources.every(row => validMonthlyPlatform(row.platform) && typeof row.profile_ready === 'boolean' && count(row.menu_count) && count(row.image_count) && (row.timezone === null || zone(row.timezone))));
  return value;
}
export function verifiedSettingsTemplate(value: SettingsTemplate): SettingsTemplate {
  need(value && text(value.id) && (['restaurant', 'beauty', 'general'].includes(value.id) || uuid(value.id)) && positive(value.revision) && text(value.name) && value.name.trim().length > 0 && value.name.length <= 80 && typeof value.builtin === 'boolean');
  verifiedSettingsDocument(value.document); need(value.document.timezone === null, '模板不可携带门店时区。'); return value;
}
export const copySettingsTemplate = (template: SettingsTemplate, current: SettingsDocument): SettingsDocument => {
  verifiedSettingsTemplate(template);
  return { ...structuredClone(template.document), timezone: current.timezone, template_key: template.id, template_revision: template.revision };
};
export const resolvedSettingsRules = (document: SettingsDocument, platform: MonthlyPlatform): SettingsRules => ({ ...document.defaults, ...document.platform_overrides[platform] });
export function settingsDocumentError(document: SettingsDocument): string { try { verifiedSettingsDocument(document); return ''; } catch (cause) { return cause instanceof Error ? cause.message : '请核对自动化规则。'; } }

export function verifiedSettingsPreviewBody(body: SettingsPreviewBody): SettingsPreviewBody {
  need(record(body) && keysOnly(body, ['request_id', 'kind', 'month', 'customer_id', 'expected_revision', 'document', 'target_ids', 'platforms', 'groups']) && uuid(body.request_id) && validMonthlyMonth(body.month) && positive(body.customer_id) && count(body.expected_revision));
  need(Array.isArray(body.target_ids) && Array.isArray(body.platforms) && Array.isArray(body.groups));
  if (body.kind === 'edit') need(body.document && !!verifiedSettingsDocument(body.document) && !body.target_ids.length && !body.platforms.length && !body.groups.length);
  else need(body.kind === 'copy' && body.document === undefined && body.target_ids.length >= 1 && body.target_ids.length <= 30 && unique(body.target_ids) && body.target_ids.every(id => positive(id) && id !== body.customer_id) && body.platforms.length >= 1 && body.platforms.length <= 3 && unique(body.platforms) && body.platforms.every(validMonthlyPlatform) && body.groups.length >= 1 && body.groups.length <= 3 && unique(body.groups) && body.groups.every(group => settingsGroups.some(row => row.value === group)), '请选择最多30家其它商家、平台和通用规则范围。');
  return body;
}
export function verifiedSettingsPreview(value: SettingsPreview, body: SettingsPreviewBody): SettingsPreview {
  verifiedSettingsPreviewBody(body);
  need(value && uuid(value.id) && value.request_id === body.request_id && hash(value.preview_hash) && instant(value.expires_at) && value.kind === body.kind && value.month === body.month && value.new_batches_only === true && value.publications_changed === false && value.menus_images_accounts_permissions_copied === false, '影响预览与本次设置请求不一致。');
  const ids = body.kind === 'edit' ? [body.customer_id] : body.target_ids;
  need(Array.isArray(value.targets) && value.targets.length === ids.length && unique(value.targets.map(row => row.customer_id)) && value.targets.every(row => ids.includes(row.customer_id)), '影响预览包含未选择的商家或缺少目标商家。');
  for (const row of value.targets) {
    need(text(row.name) && count(row.before_revision) && row.after_revision === row.before_revision + 1 && row.effective_from_month === body.month && row.accounts_materials_permissions_copied === false && count(row.auto_policies_need_reconfirmation));
    if (body.kind === 'edit') need(row.before_revision === body.expected_revision, '影响预览来源版本与当前商家不一致。');
    verifiedSettingsDocument(row.document_after); need(Array.isArray(row.changed_fields) && row.changed_fields.every(text));
    need(row.protected && ['batches', 'reviewed', 'scheduled'].every(key => count(row.protected[key as keyof SettingsImpact['protected']])));
    need(Array.isArray(row.platforms) && row.platforms.length === 3 && unique(row.platforms.map(p => p.platform)) && row.platforms.every(p => validMonthlyPlatform(p.platform) && (p.before_count === null || count(p.before_count)) && (p.proposed_count === null || count(p.proposed_count)) && (p.timezone === null || zone(p.timezone)) && count(p.existing_batches) && typeof p.source_ready === 'boolean' && !!verifiedSettingsRules({ ...resolvedSettingsRules(row.document_after, p.platform), content_mix: p.content_mix })));
  }
  return value;
}
export function verifiedSettingsSaved(value: SettingsSaved, preview: SettingsPreview, body: SettingsApplyBody): SettingsSaved {
  need(value && value.request_id === body.request_id && value.preview_id === preview.id && body.preview_hash === preview.preview_hash && body.confirmed === true && value.new_batches_only === true && value.existing_batches_changed === false && value.publications_changed === false, '保存回执与原影响预览不一致，请查询原请求。');
  need(Array.isArray(value.saved) && value.saved.length === preview.targets.length && unique(value.saved.map(row => row.customer_id)) && value.saved.every(row => preview.targets.some(target => target.customer_id === row.customer_id && row.revision === target.after_revision && row.effective_from_month === target.effective_from_month)), '保存回执商家、版本或月份与原预览不一致。');
  return value;
}
const canonical = (v: unknown): string => JSON.stringify(v, (_key, value) => record(value) ? Object.fromEntries(Object.keys(value).sort().map(key => [key, value[key]])) : value);
export function verifiedSettingsTemplateSaved(value: SettingsTemplateSaved, body: SettingsTemplateBody): SettingsTemplateSaved {
  need(value && value.request_id === body.request_id && value.customers_changed === false && value.template?.builtin === false && value.template.name === body.name);
  verifiedSettingsTemplate(value.template);
  need(canonical({ industry: value.template.document.industry, defaults: value.template.document.defaults, platform_overrides: value.template.document.platform_overrides }) === canonical({ industry: body.document.industry, defaults: body.document.defaults, platform_overrides: body.document.platform_overrides }), '模板回执与原规则不一致。');
  return value;
}
export async function settingsApi<T>(path: string, method: 'GET' | 'POST' = 'GET', data?: unknown, signal?: AbortSignal): Promise<T> { const result = await invokeWithAuth({ url: `/api/v1/media-automation-settings${path}`, method, ...(data === undefined ? {} : { data }), ...(signal ? { options: { signal } } : {}) }); return result.data as T; }
export async function readUnifiedSettings(customerId: number, month: string, signal?: AbortSignal) { return verifiedUnifiedSettings(await settingsApi<UnifiedSettings>(`/customers/${customerId}?month=${encodeURIComponent(month)}`, 'GET', undefined, signal), customerId, month); }
export async function readSettingsTemplates(signal?: AbortSignal) { const value = await settingsApi<{ items: SettingsTemplate[]; templates_are_copied_not_live_linked: true }>('/templates', 'GET', undefined, signal); need(value?.templates_are_copied_not_live_linked === true && Array.isArray(value.items) && value.items.length <= 103 && unique(value.items.map(row => row.id))); value.items.forEach(verifiedSettingsTemplate); return value.items; }
export async function readSettingsCustomers(search: string, afterId: number, signal?: AbortSignal) { const value = await settingsApi<{ items: SettingsCustomer[]; next_after: number | null }>(`/customers?search=${encodeURIComponent(search)}&after_id=${afterId}`, 'GET', undefined, signal); need(value && Array.isArray(value.items) && value.items.length <= 50 && unique(value.items.map(row => row.id)) && value.items.every(row => positive(row.id) && row.id > afterId && text(row.name) && industry(row.industry)) && (value.next_after === null || positive(value.next_after) && value.next_after > afterId)); return value; }
export async function previewSettings(body: SettingsPreviewBody) { verifiedSettingsPreviewBody(body); return verifiedSettingsPreview(await settingsApi<SettingsPreview>('/previews', 'POST', body), body); }
export async function applySettings(preview: SettingsPreview, body: SettingsApplyBody) { need(uuid(preview.id) && uuid(body.request_id) && hash(body.preview_hash) && body.preview_hash === preview.preview_hash && body.confirmed === true); return verifiedSettingsSaved(await settingsApi<SettingsSaved>(`/previews/${preview.id}/apply`, 'POST', body), preview, body); }
export async function saveSettingsTemplate(body: SettingsTemplateBody) { need(uuid(body.request_id) && text(body.name) && body.name.trim().length > 0 && body.name.length <= 80 && body.document.timezone === null); verifiedSettingsDocument(body.document); return verifiedSettingsTemplateSaved(await settingsApi<SettingsTemplateSaved>('/templates', 'POST', body), body); }
export const readSettingsRequest = <T,>(requestId: string) => { need(uuid(requestId), '原请求编号无法核实。'); return settingsApi<T>(`/requests/${requestId}`); };
export const settingsPlatforms = platforms;
