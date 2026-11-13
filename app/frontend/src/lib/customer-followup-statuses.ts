import type { BusinessDictConfig } from './dict-config';

export type CustomerFollowUpStatusConfig = Pick<BusinessDictConfig, 'customerFollowUpStatuses' | 'customerFollowUpStatusArchive' | 'followUpStages'>;
export type CustomerFollowUpStatusFields = Pick<BusinessDictConfig, 'customerFollowUpStatuses' | 'customerFollowUpStatusArchive'>;
export interface CustomerFollowUpStatusEntry { key: string; label: string; active: boolean }

const opportunityStageLabels: Record<string, string> = { initial: '初步意向', needs_confirmed: '需求确认', quoted: '已报价', negotiating: '商务沟通', payment_pending: '待收款' };
const ownLabel = (labels: Record<string, string>, key: string) => Object.prototype.hasOwnProperty.call(labels, key) ? labels[key] : undefined;

function readEntries(value: string | undefined): Array<[string, string]> {
  return (typeof value === 'string' ? value : '').split(',').filter(item => item.trim()).filter(item => item.indexOf(':') > 0).map(item => {
    const separator = item.indexOf(':');
    return [item.slice(0, separator).trim(), item.slice(separator + 1).trim()] as [string, string];
  }).filter(([key, label]) => Boolean(key && label));
}

export function getCustomerFollowUpStatusEntries(config: CustomerFollowUpStatusFields): CustomerFollowUpStatusEntry[] {
  const active = readEntries(config.customerFollowUpStatuses);
  const keys = new Set(active.map(([key]) => key));
  return [...active.map(([key, label]) => ({ key, label, active: true })), ...readEntries(config.customerFollowUpStatusArchive).filter(([key]) => !keys.has(key)).map(([key, label]) => ({ key, label, active: false }))];
}

export function validateCustomerFollowUpStatusEntries(entries: CustomerFollowUpStatusEntry[]): string {
  if (!entries.some(entry => entry.active)) return '至少保留一个启用的客户服务阶段。';
  const keys = new Set<string>(), labels = new Set<string>();
  for (const entry of entries) {
    if (!/^[a-z][a-z0-9_]{0,63}$/.test(entry.key)) return '阶段标识无效，请重新读取后重试。';
    if (keys.has(entry.key)) return '阶段标识不能重复。';
    const label = entry.label.trim();
    if (!label || Array.from(label).length > 40) return '阶段名称须为 1–40 个字。';
    if (/[,:，：]/.test(label) || Array.from(label).some(character => character !== ' ' && /[\p{C}\p{Z}]/u.test(character))) return '阶段名称不能包含中英文逗号、冒号或不可见控制字符。';
    const normalized = label.toLowerCase();
    if (labels.has(normalized)) return '阶段名称不能重复，停用的阶段也请使用不同名称。';
    keys.add(entry.key); labels.add(normalized);
  }
  return '';
}

export function serializeCustomerFollowUpStatusEntries(entries: CustomerFollowUpStatusEntry[]): CustomerFollowUpStatusFields {
  const error = validateCustomerFollowUpStatusEntries(entries);
  if (error) throw new Error(error);
  const serialize = (active: boolean) => entries.filter(entry => entry.active === active).map(entry => `${entry.key}:${entry.label.trim()}`).join(',');
  return { customerFollowUpStatuses: serialize(true), customerFollowUpStatusArchive: serialize(false) };
}

export function createCustomerFollowUpStatusKey(entries: CustomerFollowUpStatusEntry[], label: string): string {
  let hash = 0;
  for (const character of label) hash = (Math.imul(hash, 31) + character.codePointAt(0)!) >>> 0;
  const base = `service_${hash.toString(36)}`;
  let key = base, suffix = 2;
  while (entries.some(entry => entry.key === key)) key = `${base}_${suffix++}`;
  return key;
}

export function getDefaultCustomerFollowUpStatus(config: CustomerFollowUpStatusFields): string {
  return getCustomerFollowUpStatusEntries(config).find(entry => entry.active)?.key || '';
}

export function getCustomerFollowUpStatusLabel(config: CustomerFollowUpStatusConfig, stage: string | null | undefined, opportunityId?: number | null): string {
  if (!stage) return '未记录';
  const legacy = Object.fromEntries(readEntries(config.followUpStages));
  if (opportunityId != null) return ownLabel(opportunityStageLabels, stage) || ownLabel(legacy, stage) || stage;
  const entries = getCustomerFollowUpStatusEntries(config);
  return entries.find(entry => entry.key === stage)?.label || ownLabel(legacy, stage) || stage;
}

export function getCustomerFollowUpStatusOptions(config: CustomerFollowUpStatusConfig, currentStage?: string | null, opportunityId?: number | null): Array<{ value: string; label: string }> {
  if (opportunityId != null) return currentStage ? [{ value: currentStage, label: getCustomerFollowUpStatusLabel(config, currentStage, opportunityId) }] : [{ value: '', label: '未记录' }];
  const entries = getCustomerFollowUpStatusEntries(config);
  const options = entries.filter(entry => entry.active).map(entry => ({ value: entry.key, label: entry.label }));
  if (currentStage != null && !options.some(option => option.value === currentStage)) {
    const archived = entries.some(entry => !entry.active && entry.key === currentStage);
    options.unshift({ value: currentStage, label: `${archived ? '已停用' : '历史阶段'}：${getCustomerFollowUpStatusLabel(config, currentStage)}` });
  }
  return options;
}
