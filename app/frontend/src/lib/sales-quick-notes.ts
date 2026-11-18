import { invokeWithAuth } from '@/lib/tokenStore';

export const quickNoteIndustries = {
  all: '全行业通用',
  restaurant: '仅餐厅',
  beauty: '仅美业',
} as const;

export type QuickNoteIndustry = keyof typeof quickNoteIndustries;

export type SalesQuickNoteTemplate = {
  id: string;
  label: string;
  text: string;
  industry: QuickNoteIndustry;
  enabled: boolean;
  remind_do_not_contact: boolean;
};

export type SalesQuickNotes = { revision: string; templates: SalesQuickNoteTemplate[] };

function defaultNote(id: string, label: string, text: string, remindDoNotContact = false): SalesQuickNoteTemplate {
  return { id, label, text, industry: 'all', enabled: true, remind_do_not_contact: remindDoNotContact };
}

export const defaultSalesQuickNotes = [
  defaultNote('no_answer', '本次未接通', '本次未接通。'),
  defaultNote('gatekeeper', '前台／老板不在', '前台接听，老板不在。'),
  defaultNote('english', '英文沟通', '对方讲英文，暂未能有效沟通。'),
  defaultNote('owner_interested', '老板有兴趣／忙', '老板有兴趣，目前比较忙。'),
  defaultNote('materials', '先看资料', '希望先看资料，关注：____。'),
  defaultNote('existing_provider', '已有服务商', '已有服务商，补充：____。'),
  defaultNote('not_now', '暂时不需要', '暂时不需要，原因：____。'),
  defaultNote('do_not_contact', '要求不再联系', '对方明确要求不再联系。', true),
];

const endpoint = '/api/v1/app-config/sales/quick-note-templates';

function readConfig(value: unknown): SalesQuickNotes {
  const config = value as SalesQuickNotes | null;
  if (!config || !/^[a-f0-9]{64}$/.test(config.revision) || !Array.isArray(config.templates) ||
      !config.templates.every(item => item && typeof item.id === 'string' && typeof item.label === 'string' && typeof item.text === 'string' &&
        Object.prototype.hasOwnProperty.call(quickNoteIndustries, item.industry) && typeof item.enabled === 'boolean' && typeof item.remind_do_not_contact === 'boolean')) {
    throw new Error('快捷备注配置暂时无法读取');
  }
  return config;
}

export async function readSalesQuickNotes(): Promise<SalesQuickNotes> {
  const { data } = await invokeWithAuth({ url: endpoint, method: 'GET', options: { headers: { 'Cache-Control': 'no-cache' } } });
  return readConfig(data);
}

export async function saveSalesQuickNotes(expectedRevision: string, templates: SalesQuickNoteTemplate[]): Promise<SalesQuickNotes> {
  const { data } = await invokeWithAuth({
    url: endpoint, method: 'PATCH', data: { expected_revision: expectedRevision, templates },
  });
  return readConfig(data);
}
