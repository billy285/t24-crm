import type { LucideIcon } from 'lucide-react';
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
  paths: string[];
  icon: LucideIcon;
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
  { label: '老板今日工作台', paths: ['/', '/company-roadmap'], icon: LayoutDashboard },
  {
    label: '销售中心',
    paths: ['/sales-workbench', '/merchant-pool', '/sales-leads', '/sales-knowledge'],
    icon: Headphones,
  },
  { label: '客户中心', paths: ['/customers', '/sales', '/deals', '/customer-lifecycle'], icon: Users },
  { label: '任务与交付', paths: ['/operations-workbench', '/tasks', '/service-board', '/callbacks'], icon: ListTodo },
  { label: '财务与结算', paths: ['/finance', '/rmb-profit', '/management-decisions', '/commissions', '/payroll'], icon: DollarSign },
  { label: '我的客户与分润', paths: ['/partner-portal'], icon: BadgeDollarSign },
  { label: '组织与设置', paths: ['/employees', '/settings', '/permissions'], icon: Settings },
];

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
    paths: ['/finance', '/rmb-profit', '/commissions', '/payroll'],
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

export function getRoleTodayPath(role?: string | null): string {
  if (role === 'sales_partner') return '/partner-portal';
  if (role === 'sales' || role === 'sales_manager') return '/sales-workbench';
  if (role === 'ops') return '/operations-workbench';
  return '/';
}

export function getRolePendingPath(role?: string | null): string {
  if (role === 'finance') return '/finance?tab=subscriptions';
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
