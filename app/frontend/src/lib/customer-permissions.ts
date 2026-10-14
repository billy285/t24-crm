/** Name/id shells stay visible even when basic profile fields are not shared. */
export const CUSTOMER_SHELL_LIST_QUERY = { limit: 1000, sort: '-id' } as const;

export type CustomerAccessLevel = 'none' | 'read_only' | 'read_write';
export type CustomerModule = 'basic' | 'contacts' | 'followups' | 'opportunities' | 'delivery' | 'renewals' | 'deals' | 'materials';
export type CustomerFinanceAccess = 'none' | 'status' | 'receipts' | 'profit';
export type CustomerEffectivePermissions = {
  access_level: CustomerAccessLevel;
  modules: Record<CustomerModule, { read: boolean; write: boolean }>;
  finance_access: CustomerFinanceAccess;
  can_delete: boolean;
  can_export: boolean;
  can_reassign: boolean;
  can_manage_access: boolean;
  reveal_secrets: boolean;
  sources: Array<{ code: string; label: string }>;
  explicit: boolean;
  invitation_status?: string;
  invitation_source?: string;
};

export const customerModuleLabels: Record<CustomerModule, string> = {
  basic: '基础信息', contacts: '联系人', followups: '跟进记录', opportunities: '客户商机',
  delivery: '服务交付', renewals: '续费信息', deals: '成交记录', materials: '素材与账号',
};
export const customerAccessLabels: Record<CustomerAccessLevel, string> = { none: '不可见', read_only: '只读', read_write: '可编辑' };
export const customerFinanceLabels: Record<CustomerFinanceAccess, string> = { none: '不开放', status: '收款状态', receipts: '收款明细', profit: '成本与利润' };
const denied: CustomerEffectivePermissions = {
  access_level: 'none', modules: Object.fromEntries(Object.keys(customerModuleLabels).map(key => [key, {read: false, write: false}])) as CustomerEffectivePermissions['modules'],
  finance_access: 'none', can_delete: false, can_export: false, can_reassign: false, can_manage_access: false, reveal_secrets: false, sources: [], explicit: false,
};

/** UI consumes the server decision. Missing/old metadata never grants access. */
export function customerPermissions(customer: { effective_permissions?: Partial<CustomerEffectivePermissions> } | null | undefined): CustomerEffectivePermissions {
  const value = customer?.effective_permissions;
  if (!value || !['none', 'read_only', 'read_write'].includes(value.access_level || '')) return denied;
  if (value.can_manage_access !== true && (value.invitation_status !== 'active' || value.invitation_source !== 'owner_invitation')) return { ...denied, explicit: value.explicit === true, sources: Array.isArray(value.sources) ? value.sources : [] };
  if (value.access_level === 'none') return { ...denied, explicit: value.explicit === true, sources: Array.isArray(value.sources) ? value.sources : [] };
  const modules = Object.fromEntries(Object.keys(customerModuleLabels).map(key => {
    const item = value.modules?.[key as CustomerModule];
    return [key, {read: value.access_level !== 'none' && item?.read === true, write: value.access_level === 'read_write' && item?.read === true && item?.write === true}];
  })) as CustomerEffectivePermissions['modules'];
  return { ...denied, ...value, modules, sources: Array.isArray(value.sources) ? value.sources : [], finance_access: value.finance_access && value.finance_access in customerFinanceLabels ? value.finance_access : 'none' };
}

export function customerCan(customer: any, module: CustomerModule, action: 'read' | 'write' = 'read') {
  return customerPermissions(customer).modules[module][action];
}

export const customerTabLabels: Record<string, string> = {
  info: '基础信息', contacts: '联系人', followups: '跟进记录', opportunities: '客户商机',
  subscriptions: '服务交付', renewals: '续费信息', deals: '成交记录', materials: '素材管理',
  ai_copy: 'AI 文案', media: '媒体账号', payments: '财务信息',
};
export function customerCanReadTab(customer: any, tab: string) {
  const permission = customerPermissions(customer);
  if (permission.access_level === 'none') return false;
  if (['overview', 'timeline', 'logs'].includes(tab)) return permission.can_manage_access;
  if (tab === 'payments') return permission.finance_access !== 'none';
  const module: CustomerModule | undefined = ({info:'basic', contacts:'contacts', followups:'followups', opportunities:'opportunities', subscriptions:'delivery', renewals:'renewals', deals:'deals', materials:'materials', ai_copy:'materials', media:'materials'} as Record<string, CustomerModule>)[tab];
  return module ? permission.modules[module].read : false;
}
export function customerDefaultTab(customer: any) {
  if (customerCanReadTab(customer, 'overview')) return 'overview';
  return Object.keys(customerTabLabels).find(tab => customerCanReadTab(customer, tab)) || '';
}
export function customerVisibleTabs(customer: any) {
  return Object.entries(customerTabLabels).filter(([tab]) => customerCanReadTab(customer, tab)).map(([value,label]) => ({value,label}));
}

export function editableCustomerPayload(payload: Record<string, unknown>, canReassign: boolean, ownerNotes = false) {
  // Access and private notes are separate endpoints; normal editing never changes them.
  const forbidden = new Set(['effective_permissions', 'private_notes', 'access_level', 'members']);
  if (!ownerNotes) forbidden.add('notes');
  if (!canReassign) { forbidden.add('sales_person'); forbidden.add('sales_employee_id'); }
  return Object.fromEntries(Object.entries(payload).filter(([key]) => !forbidden.has(key)));
}

/** Deleting a whole customer can affect linked finance; it is owner-only. */
export function customerCanDeleteCustomer(customer: any, role: string | undefined) {
  return role === 'super_admin' && customerPermissions(customer).can_delete;
}

export function customerCreationFeedback(customer: any) {
  const canOpen = customerPermissions(customer).access_level !== 'none';
  return { canOpen, message: canOpen ? '客户创建成功' : '客户已创建，等待老板授权查看' };
}
