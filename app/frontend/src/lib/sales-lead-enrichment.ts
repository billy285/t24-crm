import { parsePhoneNumber } from '@/lib/phone-format';

export type EnrichmentVerification = 'pending' | 'confirmed';
export type EnrichmentSource = 'call' | 'manual';
export type EnrichmentContact = {
  id: string;
  name: string | null;
  role: string | null;
  phone: string | null;
  email: string | null;
  wechat: string | null;
  verification: EnrichmentVerification;
};
export type EnrichmentFields = {
  business_name: string;
  industry: string | null;
  city: string | null;
  state: string | null;
  country: string | null;
  address: string | null;
  website: string | null;
  store_phone: string;
  contacts: EnrichmentContact[];
  preferred_contact_id: string | null;
  interest_product_ids: number[];
  need_summary: string | null;
  best_contact_time: string | null;
  verification: EnrichmentVerification;
};
export type EnrichmentResponse = EnrichmentFields & {
  lead_id: number;
  revision: number;
  lead_updated_at: string;
  updated_by_name: string | null;
  updated_at: string | null;
  can_edit: boolean;
  read_only_reason: string | null;
  warnings: string[];
};
export type EnrichmentUpdate = EnrichmentFields & {
  expected_revision: number;
  expected_lead_updated_at: string;
  source: EnrichmentSource;
};
export type EnrichmentProduct = { id: number; name: string };
export type EnrichmentCatalog = { items: EnrichmentProduct[] };
export type EnrichmentHistoryItem = {
  id: number;
  revision: number;
  source: EnrichmentSource;
  changed_fields: string[];
  before?: Partial<EnrichmentFields> | null;
  after?: Partial<EnrichmentFields> | null;
  actor_name: string | null;
  created_at: string;
};
export type EnrichmentHistoryEntry = EnrichmentHistoryItem;
export type EnrichmentHistory = { items: EnrichmentHistoryItem[]; total: number; skip?: number; limit?: number };

const nullableText = (value: unknown) => typeof value === 'string' ? value : null;
const verification = (value: unknown): EnrichmentVerification => value === 'confirmed' ? 'confirmed' : 'pending';
const textFields = ['industry', 'city', 'state', 'country', 'address', 'website', 'need_summary', 'best_contact_time'] as const;

/** Whitelist the editable snapshot. Never spread server metadata into a PUT. */
function editableFields(value: Partial<EnrichmentFields>, leadId = 0): EnrichmentFields {
  const contacts = (Array.isArray(value.contacts) ? value.contacts : []).map((contact, index) => ({
    id: typeof contact.id === 'string' && contact.id ? contact.id : `legacy-${leadId}-${index + 1}`,
    name: nullableText(contact.name), role: nullableText(contact.role), phone: nullableText(contact.phone),
    email: nullableText(contact.email), wechat: nullableText(contact.wechat), verification: verification(contact.verification),
  }));
  return {
    business_name: typeof value.business_name === 'string' ? value.business_name : '',
    store_phone: typeof value.store_phone === 'string' ? value.store_phone : '',
    ...Object.fromEntries(textFields.map(key => [key, nullableText(value[key])])) as Pick<EnrichmentFields, typeof textFields[number]>,
    contacts,
    preferred_contact_id: typeof value.preferred_contact_id === 'string' ? value.preferred_contact_id : null,
    interest_product_ids: [...new Set((Array.isArray(value.interest_product_ids) ? value.interest_product_ids : []).filter(id => Number.isSafeInteger(id) && id > 0))],
    verification: verification(value.verification),
  };
}

export function normalizeEnrichmentResponse(value: EnrichmentResponse): EnrichmentResponse {
  return {
    ...editableFields(value, value.lead_id), lead_id: value.lead_id, revision: value.revision,
    lead_updated_at: value.lead_updated_at, updated_by_name: nullableText(value.updated_by_name), updated_at: nullableText(value.updated_at),
    can_edit: value.can_edit === true, read_only_reason: nullableText(value.read_only_reason),
    warnings: Array.isArray(value.warnings) ? value.warnings.filter(item => typeof item === 'string') : [],
  };
}

export function toEnrichmentUpdate(value: EnrichmentResponse, source: EnrichmentSource = 'call'): EnrichmentUpdate {
  return { ...editableFields(value, value.lead_id), expected_revision: value.revision, expected_lead_updated_at: value.lead_updated_at, source };
}

export function normalizeEnrichmentUpdate(value: EnrichmentUpdate): EnrichmentUpdate {
  return { ...editableFields(value), expected_revision: value.expected_revision, expected_lead_updated_at: value.expected_lead_updated_at, source: value.source === 'manual' ? 'manual' : 'call' };
}

export function createEnrichmentContact(): EnrichmentContact {
  const id = globalThis.crypto?.randomUUID?.() || `contact-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
  return { id, name: '', role: '', phone: '', email: '', wechat: '', verification: 'pending' };
}

export function removeEnrichmentContact(value: EnrichmentUpdate, contactId: string): EnrichmentUpdate {
  return { ...value, contacts: value.contacts.filter(contact => contact.id !== contactId), preferred_contact_id: value.preferred_contact_id === contactId ? null : value.preferred_contact_id };
}

export function enrichmentDraftSignature(value: EnrichmentUpdate | null): string {
  return value ? JSON.stringify(normalizeEnrichmentUpdate(value)) : '';
}

export function validateEnrichmentUpdate(value: EnrichmentUpdate): string[] {
  const errors: string[] = [];
  if (!value.business_name.trim()) errors.push('请填写商家名称');
  if (!value.store_phone.trim()) errors.push('请填写门店号码');
  else if (value.verification === 'confirmed' && !parsePhoneNumber(value.store_phone, value.country).isValid) errors.push('门店号码无效；请核对国家和号码，或标为待确认');
  if (!Number.isInteger(value.expected_revision) || value.expected_revision < 0 || !value.expected_lead_updated_at) errors.push('资料版本缺失，请重新读取后再保存');
  if (value.contacts.length > 20) errors.push('最多记录 20 位联系人');
  if (value.interest_product_ids.length > 30) errors.push('最多选择 30 个意向产品');
  if (value.website?.includes(':') && !/^https?:\/\//i.test(value.website)) errors.push('网站仅支持 http 或 https 地址');
  const ids = new Set<string>();
  value.contacts.forEach((contact, index) => {
    if (!contact.id || ids.has(contact.id)) errors.push(`联系人 ${index + 1} 标识重复，请移除后重新添加`);
    ids.add(contact.id);
    if (![contact.name, contact.phone, contact.email, contact.wechat].some(text => text?.trim())) errors.push(`联系人 ${index + 1} 至少填写姓名、电话、邮箱或微信之一`);
    if (contact.email?.trim() && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(contact.email.trim())) errors.push(`联系人 ${index + 1} 邮箱格式不正确`);
    if (contact.verification === 'confirmed' && contact.phone?.trim() && !parsePhoneNumber(contact.phone, value.country).isValid) errors.push(`联系人 ${index + 1} 电话无效；请核对或标为待确认`);
  });
  if (value.preferred_contact_id && !ids.has(value.preferred_contact_id)) errors.push('首选联系人已移除，请重新选择');
  return errors;
}

export const enrichmentFieldLabels: Record<string, string> = {
  business_name: '商家名称', store_phone: '门店号码', contacts: '联系人', preferred_contact_id: '首选联系人',
  interest_product_ids: '意向产品', need_summary: '真实需求', best_contact_time: '适合联系时间', verification: '核实状态',
  industry: '行业', city: '城市', state: '州 / 省', country: '国家 / 地区', address: '地址', website: '网站',
};

/** Warnings are deliberately generic: duplicate checks must not reveal another lead. */
export function enrichmentWarningText(warnings: readonly string[]): string | null {
  if (!warnings.length) return null;
  const messages: string[] = [];
  if (warnings.some(item => /duplicat|重复/i.test(item))) messages.push('号码可能与现有资料重复，请核对本商家资料。此处不展示其他商家信息。');
  if (warnings.some(item => /产品.*停用|product.*inactive|inactive.*product/i.test(item))) messages.push('已选意向产品已停用，请取消目录外产品并重新选择后保存。');
  return messages.join(' ') || '部分资料仍待核对。格式不完整或无效的号码暂不能拨打，请核对后更新。';
}
