/** Name/id shells stay visible even when basic profile fields are not shared. */
export const CUSTOMER_SHELL_LIST_QUERY = { limit: 1000, sort: '-id' } as const;

export type CustomerAccessLevel = 'none' | 'read_only' | 'read_write';
export type CustomerModule = 'basic' | 'followups' | 'delivery' | 'materials';
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
};

export const customerModuleLabels: Record<CustomerModule, string> = {
  basic: '客户资料', followups: '沟通跟进', delivery: '项目与交付', materials: '素材与账号',
};
export const customerAccessLabels: Record<CustomerAccessLevel, string> = { none: '不可见', read_only: '只读', read_write: '可编辑' };
export const customerFinanceLabels: Record<CustomerFinanceAccess, string> = { none: '不开放', status: '收款状态', receipts: '收款明细', profit: '成本与利润' };
const denied: CustomerEffectivePermissions = {
  access_level: 'none', modules: { basic: {read: false, write: false}, followups: {read: false, write: false}, delivery: {read: false, write: false}, materials: {read: false, write: false} },
  finance_access: 'none', can_delete: false, can_export: false, can_reassign: false, can_manage_access: false, reveal_secrets: false, sources: [], explicit: false,
};

/** UI consumes the server decision. Missing/old metadata never grants access. */
export function customerPermissions(customer: { effective_permissions?: Partial<CustomerEffectivePermissions> } | null | undefined): CustomerEffectivePermissions {
  const value = customer?.effective_permissions;
  if (!value || !['none', 'read_only', 'read_write'].includes(value.access_level || '')) return denied;
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

export function customerCanReadTab(customer: any, tab: string) {
  const permission = customerPermissions(customer);
  if (permission.access_level === 'none') return false;
  if (['overview', 'timeline'].includes(tab)) return true;
  if (tab === 'payments') return permission.finance_access !== 'none';
  if (tab === 'logs') return permission.can_manage_access;
  if (['materials', 'ai_copy', 'media'].includes(tab)) return permission.modules.materials.read;
  if (['subscriptions', 'renewals', 'deals'].includes(tab)) return permission.modules.delivery.read;
  if (['followups', 'opportunities'].includes(tab)) return permission.modules.followups.read;
  return permission.modules.basic.read;
}

export function editableCustomerPayload(payload: Record<string, unknown>, canReassign: boolean) {
  // Access and private notes are separate endpoints; normal editing never changes them.
  const forbidden = new Set(['effective_permissions', 'private_notes', 'access_level', 'members']);
  if (!canReassign) { forbidden.add('sales_person'); forbidden.add('sales_employee_id'); }
  return Object.fromEntries(Object.entries(payload).filter(([key]) => !forbidden.has(key)));
}

/** Deleting a whole customer can affect linked finance; it is owner-only. */
export function customerCanDeleteCustomer(customer: any, role: string | undefined) {
  return role === 'super_admin' && customerPermissions(customer).can_delete;
}
