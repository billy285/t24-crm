import { readCachedAppConfig, writeCachedAppConfig } from './app-config';

// ==================== 权限系统核心配置 ====================

// 系统角色类型
export type SystemRole = 'super_admin' | 'admin' | 'sales' | 'sales_manager' | 'ops' | 'design' | 'finance';

export const systemRoleLabels: Record<SystemRole, string> = {
  super_admin: '超级管理员',
  admin: '管理员',
  sales: '销售',
  sales_manager: '销售主管',
  ops: '运营',
  design: '设计',
  finance: '财务',
};

// 页面路径定义
export const PAGE_PATHS = {
  dashboard: '/',
  merchant_pool: '/merchant-pool',
  sales_leads: '/sales-leads',
  sales_workbench: '/sales-workbench',
  sales_knowledge: '/sales-knowledge',
  customers: '/customers',
  sales: '/sales',
  deals: '/deals',
  customer_lifecycle: '/customer-lifecycle',
  management_decisions: '/management-decisions',
  finance: '/finance',
  commissions: '/commissions',
  payroll: '/payroll',
  tasks: '/tasks',
  service_board: '/service-board',
  callbacks: '/callbacks',
  employees: '/employees',
  settings: '/settings',
  permissions: '/permissions',
} as const;

export const pageLabels: Record<string, string> = {
  '/': '仪表盘',
  '/merchant-pool': '待清洗商家池',
  '/sales-leads': '电话销售中心',
  '/sales-workbench': '每日拨打工作台',
  '/sales-knowledge': '销售知识库',
  '/customers': '客户管理',
  '/sales': '成交客户管理',
  '/deals': '成交管理',
  '/customer-lifecycle': '客户生命周期',
  '/management-decisions': '经营分类与项目',
  '/finance': '财务管理',
  '/commissions': '渠道与分润',
  '/payroll': '工资表',
  '/tasks': '任务协作',
  '/service-board': '服务进度看板',
  '/callbacks': '电话回访',
  '/employees': '员工管理',
  '/settings': '系统设置',
  '/permissions': '权限设置',
};

// 按钮权限 key
export type ButtonPermission =
  | 'customer_create' | 'customer_edit' | 'customer_delete' | 'customer_export'
  | 'customer_assign' | 'customer_transfer'
  | 'view_password' | 'copy_password'
  | 'employee_create' | 'employee_edit' | 'employee_disable' | 'employee_reset_password'
  | 'deal_create' | 'deal_edit'
  | 'payment_create' | 'payment_edit'
  | 'task_create' | 'task_edit' | 'task_delete'
  | 'follow_up_create' | 'follow_up_edit' | 'follow_up_delete'
  | 'media_account_create' | 'media_account_edit' | 'media_account_delete'
  | 'settings_edit' | 'permission_edit';

export const buttonPermissionLabels: Record<ButtonPermission, string> = {
  customer_create: '新增客户',
  customer_edit: '编辑客户',
  customer_delete: '删除客户',
  customer_export: '导出客户',
  customer_assign: '分配客户',
  customer_transfer: '转移客户',
  view_password: '查看密码',
  copy_password: '复制密码',
  employee_create: '新增员工',
  employee_edit: '编辑员工',
  employee_disable: '停用员工',
  employee_reset_password: '重置密码',
  deal_create: '新增成交',
  deal_edit: '编辑成交',
  payment_create: '录入收款',
  payment_edit: '编辑收款',
  task_create: '新增任务',
  task_edit: '编辑任务',
  task_delete: '删除任务',
  follow_up_create: '新增跟进',
  follow_up_edit: '编辑跟进',
  follow_up_delete: '删除跟进',
  media_account_create: '新增媒体账号',
  media_account_edit: '编辑媒体账号',
  media_account_delete: '删除媒体账号',
  settings_edit: '修改系统设置',
  permission_edit: '修改权限设置',
};

// 数据范围
export type DataScope = 'self' | 'department' | 'all';

export const dataScopeLabels: Record<DataScope, string> = {
  self: '仅自己',
  department: '本部门',
  all: '全部',
};

// 角色权限配置接口
export interface RolePermissionConfig {
  pages: string[];           // 可访问的页面路径
  buttons: ButtonPermission[]; // 可用的按钮权限
  dataScope: DataScope;       // 数据范围
  sensitiveFields: {          // 敏感信息权限
    viewPassword: boolean;
    copyPassword: boolean;
    viewFinance: boolean;
  };
}

// 默认角色权限配置
export const defaultRolePermissions: Record<SystemRole, RolePermissionConfig> = {
  super_admin: {
    pages: ['/', '/merchant-pool', '/sales-leads', '/sales-workbench', '/sales-knowledge', '/customers', '/sales', '/deals', '/customer-lifecycle', '/management-decisions', '/finance', '/commissions', '/payroll', '/tasks', '/service-board', '/callbacks', '/employees', '/settings', '/permissions'],
    buttons: [
      'customer_create', 'customer_edit', 'customer_delete', 'customer_export',
      'customer_assign', 'customer_transfer',
      'view_password', 'copy_password',
      'employee_create', 'employee_edit', 'employee_disable', 'employee_reset_password',
      'deal_create', 'deal_edit',
      'payment_create', 'payment_edit',
      'task_create', 'task_edit', 'task_delete',
      'follow_up_create', 'follow_up_edit', 'follow_up_delete',
      'media_account_create', 'media_account_edit', 'media_account_delete',
      'settings_edit', 'permission_edit',
    ],
    dataScope: 'all',
    sensitiveFields: { viewPassword: true, copyPassword: true, viewFinance: true },
  },
  admin: {
    pages: ['/', '/merchant-pool', '/sales-leads', '/sales-workbench', '/sales-knowledge', '/customers', '/sales', '/deals', '/customer-lifecycle', '/management-decisions', '/finance', '/commissions', '/payroll', '/tasks', '/service-board', '/callbacks', '/employees', '/settings', '/permissions'],
    buttons: [
      'customer_create', 'customer_edit', 'customer_delete', 'customer_export',
      'customer_assign', 'customer_transfer',
      'view_password', 'copy_password',
      'employee_create', 'employee_edit', 'employee_disable', 'employee_reset_password',
      'deal_create', 'deal_edit',
      'payment_create', 'payment_edit',
      'task_create', 'task_edit', 'task_delete',
      'follow_up_create', 'follow_up_edit', 'follow_up_delete',
      'media_account_create', 'media_account_edit', 'media_account_delete',
      'settings_edit', 'permission_edit',
    ],
    dataScope: 'all',
    sensitiveFields: { viewPassword: true, copyPassword: true, viewFinance: true },
  },
  sales: {
    pages: ['/merchant-pool', '/sales-leads', '/sales-workbench', '/sales-knowledge'],
    buttons: [],
    dataScope: 'self',
    sensitiveFields: { viewPassword: false, copyPassword: false, viewFinance: false },
  },
  sales_manager: {
    pages: ['/sales-leads', '/sales-workbench', '/sales-knowledge'],
    buttons: [],
    dataScope: 'department',
    sensitiveFields: { viewPassword: false, copyPassword: false, viewFinance: false },
  },
  ops: {
    pages: ['/', '/customers', '/tasks', '/service-board'],
    buttons: [
      'customer_edit',
      'task_create', 'task_edit',
      'media_account_create', 'media_account_edit',
      'follow_up_create', 'follow_up_edit',
    ],
    dataScope: 'all',
    sensitiveFields: { viewPassword: false, copyPassword: false, viewFinance: false },
  },
  design: {
    pages: ['/', '/tasks'],
    buttons: [
      'task_edit',
    ],
    dataScope: 'self',
    sensitiveFields: { viewPassword: false, copyPassword: false, viewFinance: false },
  },
  finance: {
    pages: ['/', '/finance', '/commissions', '/payroll', '/customers', '/customer-lifecycle', '/management-decisions', '/service-board'],
    buttons: [
      'payment_create', 'payment_edit',
      'customer_export',
    ],
    dataScope: 'all',
    sensitiveFields: { viewPassword: false, copyPassword: false, viewFinance: true },
  },
};

// ==================== 权限存储与读取 ====================

const PERMISSIONS_STORAGE_KEY = 'crm_role_permissions';
const PERMISSIONS_VERSION_KEY = 'crm_role_permissions_version';
// Bump this version whenever default permissions change (e.g., new pages added)
const CURRENT_PERMISSIONS_VERSION = 11;

function uniq<T>(items: T[]): T[] {
  return Array.from(new Set(items));
}

export function normalizeRolePermissions(
  config?: Partial<Record<SystemRole, Partial<RolePermissionConfig>>>
): Record<SystemRole, RolePermissionConfig> {
  const normalized = {} as Record<SystemRole, RolePermissionConfig>;

  for (const role of Object.keys(defaultRolePermissions) as SystemRole[]) {
    const merged = {
      ...defaultRolePermissions[role],
      ...(config?.[role] || {}),
      sensitiveFields: {
        ...defaultRolePermissions[role].sensitiveFields,
        ...(config?.[role]?.sensitiveFields || {}),
      },
    };

    const isPhoneSalesRole = role === 'sales';
    const isPhoneSalesManager = role === 'sales_manager';
    const pages = isPhoneSalesRole
      ? ['/sales-leads', '/sales-workbench', '/sales-knowledge']
      : isPhoneSalesManager
        ? ['/merchant-pool', '/sales-leads', '/sales-workbench', '/sales-knowledge']
      : uniq(merged.pages || defaultRolePermissions[role].pages);
    if (role === 'admin' || role === 'super_admin') {
      if (!pages.includes('/merchant-pool')) pages.push('/merchant-pool');
      if (!pages.includes('/sales-leads')) pages.push('/sales-leads');
      if (!pages.includes('/sales-workbench')) pages.push('/sales-workbench');
      if (!pages.includes('/sales-knowledge')) pages.push('/sales-knowledge');
    }
    normalized[role] = {
      pages,
      buttons: uniq((merged.buttons || defaultRolePermissions[role].buttons) as ButtonPermission[]),
      dataScope: merged.dataScope || defaultRolePermissions[role].dataScope,
      sensitiveFields: merged.sensitiveFields,
    };
  }

  return normalized;
}

export function loadRolePermissions(): Record<SystemRole, RolePermissionConfig> {
  const parsed = readCachedAppConfig<Partial<Record<SystemRole, Partial<RolePermissionConfig>>>>(
    'role_permissions',
    defaultRolePermissions
  );
  const normalized = normalizeRolePermissions(parsed);
  // Preserve existing custom permissions while migrating newly added pages.
  const savedVersion = Number(localStorage.getItem(PERMISSIONS_VERSION_KEY) || 0);
  if (savedVersion < CURRENT_PERMISSIONS_VERSION) {
    for (const role of ['super_admin', 'admin', 'finance'] as SystemRole[]) {
      if (!normalized[role].pages.includes('/payroll')) normalized[role].pages.push('/payroll');
      if (!normalized[role].pages.includes('/customer-lifecycle')) normalized[role].pages.push('/customer-lifecycle');
      if (!normalized[role].pages.includes('/management-decisions')) normalized[role].pages.push('/management-decisions');
      if (!normalized[role].pages.includes('/commissions')) normalized[role].pages.push('/commissions');
    }
    for (const role of ['super_admin', 'admin'] as SystemRole[]) {
      if (!normalized[role].pages.includes('/merchant-pool')) normalized[role].pages.push('/merchant-pool');
      if (!normalized[role].pages.includes('/sales-leads')) normalized[role].pages.push('/sales-leads');
      if (!normalized[role].pages.includes('/sales-workbench')) normalized[role].pages.push('/sales-workbench');
      if (!normalized[role].pages.includes('/sales-knowledge')) normalized[role].pages.push('/sales-knowledge');
    }
    localStorage.setItem(PERMISSIONS_VERSION_KEY, String(CURRENT_PERMISSIONS_VERSION));
  }
  return normalized;
}

export function saveRolePermissions(config: Record<SystemRole, RolePermissionConfig>): void {
  writeCachedAppConfig('role_permissions', normalizeRolePermissions(config));
  localStorage.setItem(PERMISSIONS_VERSION_KEY, String(CURRENT_PERMISSIONS_VERSION));
}

// ==================== 权限检查工具函数 ====================

// Map old role names to new system roles
function mapToSystemRole(role: string): SystemRole {
  const normalizedRole = String(role || '').trim().toLowerCase();
  const mapping: Record<string, SystemRole> = {
    boss: 'super_admin',
    owner: 'super_admin',
    super_admin: 'super_admin',
    superadmin: 'super_admin',
    '超级管理员': 'super_admin',
    '老板': 'super_admin',
    admin: 'admin',
    administrator: 'admin',
    system_admin: 'admin',
    systemadmin: 'admin',
    '系统管理员': 'admin',
    '管理员': 'admin',
    sales: 'sales',
    sale: 'sales',
    '销售': 'sales',
    '销售人员': 'sales',
    sales_manager: 'sales_manager',
    salesmanager: 'sales_manager',
    '销售主管': 'sales_manager',
    '销售经理': 'sales_manager',
    ops: 'ops',
    operations: 'ops',
    operation: 'ops',
    '运营': 'ops',
    '运营部': 'ops',
    design: 'design',
    designer: 'design',
    '设计': 'design',
    '设计部': 'design',
    finance: 'finance',
    financial: 'finance',
    '财务': 'finance',
    '财务部': 'finance',
  };
  return mapping[normalizedRole] || 'sales';
}

export function getPermissions(role: string): RolePermissionConfig {
  const systemRole = mapToSystemRole(role);
  const allPerms = loadRolePermissions();
  return allPerms[systemRole] || defaultRolePermissions.sales;
}

export function canAccessPage(role: string, path: string): boolean {
  if (!role) return true; // No role = treat as super_admin
  // Payroll is an independent finance worksheet. Keep its access available for
  // finance administrators even when an older cached permission config exists.
  if (path === '/payroll' && ['super_admin', 'admin', 'finance'].includes(mapToSystemRole(role))) return true;
  if (path === '/customer-lifecycle' && ['super_admin', 'admin', 'finance'].includes(mapToSystemRole(role))) return true;
  if (path === '/management-decisions' && ['super_admin', 'admin', 'finance'].includes(mapToSystemRole(role))) return true;
  if (path === '/commissions' && ['super_admin', 'admin', 'finance'].includes(mapToSystemRole(role))) return true;
  const perms = getPermissions(role);
  return perms.pages.includes(path);
}

export function hasButtonPermission(role: string, permission: ButtonPermission): boolean {
  if (!role) return true; // No role = treat as super_admin
  const perms = getPermissions(role);
  return perms.buttons.includes(permission);
}

export function getDataScope(role: string): DataScope {
  if (!role) return 'all';
  const perms = getPermissions(role);
  return perms.dataScope;
}

export function canViewSensitive(role: string, field: keyof RolePermissionConfig['sensitiveFields']): boolean {
  if (!role) return true;
  const perms = getPermissions(role);
  return perms.sensitiveFields[field];
}

export function isAdminRole(role: string): boolean {
  const sr = mapToSystemRole(role);
  return sr === 'super_admin' || sr === 'admin';
}

export { mapToSystemRole };
