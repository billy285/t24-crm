import type { LucideIcon } from 'lucide-react';
import { financeNavigationItems, normalizeFinanceTab } from './finance-navigation';
import {
  Activity,
  BadgeDollarSign,
  BookOpen,
  ClipboardList,
  Database,
  DollarSign,
  Handshake,
  Headphones,
  LayoutDashboard,
  ListTodo,
  PhoneCall,
  Settings,
  ShieldCheck,
  Target,
  TrendingUp,
  UserCog,
  Users,
} from 'lucide-react';

export type MobileBusinessAppKey =
  | 'strategy'
  | 'sales'
  | 'customers'
  | 'delivery'
  | 'finance'
  | 'organization'
  | 'partner';

export interface AppNavigationItem {
  path: string;
  label: string;
  icon: LucideIcon;
}

export interface AppNavigationSection {
  label: string;
  railLabel: string;
  description: string;
  paths: string[];
  icon: LucideIcon;
}

export interface DesktopNavigationItem extends AppNavigationItem {
  group: string;
  tab?: string;
}

export interface DesktopNavigationSection extends AppNavigationSection {
  items: DesktopNavigationItem[];
}

export interface MobileBusinessAppDefinition {
  key: MobileBusinessAppKey;
  label: string;
  description: string;
  icon: LucideIcon;
  paths: string[];
  tone: 'indigo' | 'blue' | 'cyan' | 'violet' | 'emerald' | 'slate';
}

export const appNavigationItems: AppNavigationItem[] = [
  { path: '/', label: '老板今日工作台', icon: LayoutDashboard },
  { path: '/company-roadmap', label: '公司战略与里程碑', icon: Target },
  { path: '/merchant-pool', label: '待清洗商家池', icon: Database },
  { path: '/sales-leads', label: '电话销售中心', icon: Headphones },
  { path: '/sales-workbench', label: '销售今日工作台', icon: Headphones },
  { path: '/operations-workbench', label: '运营今日工作台', icon: ListTodo },
  { path: '/sales-knowledge', label: '销售知识库', icon: BookOpen },
  { path: '/customers', label: '客户管理', icon: Users },
  { path: '/sales', label: '成交客户', icon: Handshake },
  { path: '/deals', label: '成交管理', icon: Handshake },
  { path: '/customer-lifecycle', label: '客户生命周期', icon: Activity },
  { path: '/management-decisions', label: '经营健康与决策', icon: BadgeDollarSign },
  { path: '/finance', label: '财务管理', icon: DollarSign },
  { path: '/rmb-profit', label: '人民币利润预估', icon: TrendingUp },
  { path: '/commissions', label: '渠道与分润', icon: BadgeDollarSign },
  { path: '/settings/deduction', label: '月度扣点比例', icon: Settings },
  { path: '/partner-portal', label: '我的客户与分润', icon: BadgeDollarSign },
  { path: '/payroll', label: '工资表', icon: ClipboardList },
  { path: '/tasks', label: '任务协作', icon: ListTodo },
  { path: '/service-board', label: '服务进度看板', icon: ClipboardList },
  { path: '/callbacks', label: '电话回访', icon: PhoneCall },
  { path: '/employees', label: '员工管理', icon: UserCog },
  { path: '/settings', label: '系统设置', icon: Settings },
  { path: '/permissions', label: '权限设置', icon: ShieldCheck },
];

export const appNavigationSections: AppNavigationSection[] = [
  { label: '老板今日工作台', railLabel: '工作台', description: '今日重点与经营方向', paths: ['/', '/company-roadmap'], icon: LayoutDashboard },
  {
    label: '销售中心',
    railLabel: '销售中心',
    description: '线索、拨打与销售跟进',
    paths: ['/sales-workbench', '/merchant-pool', '/sales-leads', '/sales-knowledge'],
    icon: Headphones,
  },
  { label: '客户中心', railLabel: '客户中心', description: '客户关系与成交进展', paths: ['/customers', '/sales', '/deals', '/customer-lifecycle'], icon: Users },
  { label: '任务与交付', railLabel: '任务交付', description: '任务协作、服务与回访', paths: ['/operations-workbench', '/tasks', '/service-board', '/callbacks'], icon: ListTodo },
  { label: '财务与结算', railLabel: '财务结算', description: '收款、续费与账目管理', paths: ['/finance', '/rmb-profit', '/management-decisions', '/settings/deduction', '/payroll'], icon: DollarSign },
  { label: '渠道与分润', railLabel: '渠道分润', description: '渠道合作与分润进展', paths: ['/commissions', '/partner-portal'], icon: BadgeDollarSign },
  { label: '组织与设置', railLabel: '组织设置', description: '员工、权限与系统配置', paths: ['/employees', '/settings', '/permissions'], icon: Settings },
];

export function getDesktopNavigationSections(canAccess: (path: string) => boolean): DesktopNavigationSection[] {
  return appNavigationSections.map(section => ({
    ...section,
    items: section.paths.flatMap((path): DesktopNavigationItem[] => {
      if (!canAccess(path)) return [];
      if (path === '/finance') return financeNavigationItems.map(item => ({ ...item, path }));
      const item = appNavigationItems.find(entry => entry.path === path);
      return item ? [{ ...item, group: section.paths.includes('/finance') ? '分析与设置' : '功能导航' }] : [];
    }),
  })).filter(section => section.items.length > 0);
}

export function isDesktopNavigationItemActive(item: DesktopNavigationItem, pathname: string, search: string) {
  return item.path === pathname && (!item.tab || item.tab === normalizeFinanceTab(new URLSearchParams(search).get('tab')));
}

export function getDesktopNavigationHref(item: DesktopNavigationItem, pathname = '', search = '') {
  if (!item.tab) return item.path;
  // Preserve finance's existing query context when changing tabs, as its tab bar does.
  const params = new URLSearchParams(pathname === '/finance' ? search : '');
  if (item.tab === 'overview') params.delete('tab');
  else params.set('tab', item.tab);
  return `${item.path}${params.size ? `?${params.toString()}` : ''}`;
}

export const mobileBusinessApps: MobileBusinessAppDefinition[] = [
  {
    key: 'strategy',
    label: '经营中心',
    description: '经营、现金与里程碑',
    icon: Target,
    paths: ['/', '/company-roadmap', '/management-decisions'],
    tone: 'indigo',
  },
  {
    key: 'sales',
    label: '销售中心',
    description: '线索、拨打与跟进',
    icon: Headphones,
    paths: ['/sales-workbench', '/merchant-pool', '/sales-leads', '/sales-knowledge'],
    tone: 'blue',
  },
  {
    key: 'customers',
    label: '客户中心',
    description: '客户 360 与生命周期',
    icon: Users,
    paths: ['/customers', '/sales', '/deals', '/customer-lifecycle'],
    tone: 'cyan',
  },
  {
    key: 'delivery',
    label: '任务交付',
    description: '任务、服务与回访',
    icon: ListTodo,
    paths: ['/operations-workbench', '/tasks', '/service-board', '/callbacks'],
    tone: 'violet',
  },
  {
    key: 'finance',
    label: '财务结算',
    description: '收款、续费与分润',
    icon: DollarSign,
    paths: ['/finance', '/rmb-profit', '/commissions', '/settings/deduction', '/payroll'],
    tone: 'emerald',
  },
  {
    key: 'organization',
    label: '组织设置',
    description: '员工、权限与系统',
    icon: Settings,
    paths: ['/employees', '/settings', '/permissions'],
    tone: 'slate',
  },
];

export const partnerBusinessApp: MobileBusinessAppDefinition = {
  key: 'partner',
  label: '我的客户与分润',
  description: '客户合作、续费与分润状态',
  icon: BadgeDollarSign,
  paths: ['/partner-portal'],
  tone: 'blue',
};

const mobileAppByKey = new Map(mobileBusinessApps.map(app => [app.key, app]));

const mobileRoleAppPaths: Record<string, Partial<Record<MobileBusinessAppKey, string[]>>> = {
  super_admin: {
    strategy: ['/', '/company-roadmap', '/management-decisions'],
    sales: ['/sales-workbench', '/merchant-pool', '/sales-leads', '/sales-knowledge'],
    customers: ['/customers', '/deals', '/customer-lifecycle'],
    delivery: ['/operations-workbench', '/tasks', '/service-board', '/callbacks'],
    finance: ['/finance', '/rmb-profit', '/payroll'],
    organization: ['/employees'],
  },
  admin: {
    strategy: ['/', '/company-roadmap', '/management-decisions'],
    sales: ['/sales-workbench', '/merchant-pool', '/sales-leads', '/sales-knowledge'],
    customers: ['/customers', '/deals', '/customer-lifecycle'],
    delivery: ['/operations-workbench', '/tasks', '/service-board', '/callbacks'],
    finance: ['/finance', '/rmb-profit', '/payroll'],
    organization: ['/employees'],
  },
  sales: {
    sales: ['/sales-workbench', '/sales-leads', '/sales-knowledge'],
    customers: ['/customers'],
    delivery: ['/tasks'],
  },
  sales_manager: {
    sales: ['/sales-workbench', '/sales-leads', '/merchant-pool', '/sales-knowledge'],
    customers: ['/customers'],
    delivery: ['/tasks'],
  },
  ops: {
    delivery: ['/operations-workbench', '/tasks', '/service-board', '/callbacks'],
    customers: ['/customers'],
  },
  design: {
    delivery: ['/tasks'],
    customers: ['/customers'],
  },
  finance: {
    finance: ['/finance', '/rmb-profit', '/payroll'],
    customers: ['/customers'],
    strategy: ['/'],
  },
};

/**
 * Mobile is a focused execution surface, not a miniature copy of desktop admin.
 * Global settings, permissions and other high-impact bulk tools stay on desktop.
 */
export function getMobileBusinessApps(role?: string | null): MobileBusinessAppDefinition[] {
  if (role === 'sales_partner') return [partnerBusinessApp];

  const configured = mobileRoleAppPaths[role || ''] || mobileRoleAppPaths.super_admin;
  return Object.entries(configured).flatMap(([key, paths]) => {
    const definition = mobileAppByKey.get(key as MobileBusinessAppKey);
    if (!definition || !paths?.length) return [];
    return [{ ...definition, paths }];
  });
}

export function getRoleTodayPath(role?: string | null): string {
  if (role === 'sales_partner') return '/partner-portal';
  if (role === 'sales' || role === 'sales_manager') return '/sales-workbench';
  if (role === 'ops') return '/operations-workbench';
  return '/';
}

export function getRolePendingPath(role?: string | null): string {
  if (role === 'finance') return '/finance';
  if (role === 'sales_partner') return '/partner-portal';
  if (role === 'sales' || role === 'sales_manager') return '/sales-leads';
  if (role === 'ops' || role === 'design') return '/tasks?view=mine';
  return '/tasks?view=system&source=system';
}

export function getDesktopLoginPath(role?: string | null): string {
  if (role === 'sales_partner') return '/partner-portal';
  if (role === 'sales' || role === 'sales_manager') return '/sales-leads';
  return '/';
}
