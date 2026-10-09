import type { LucideIcon } from 'lucide-react';
import { Building2, ClipboardCheck, Handshake, Headphones, Target, UsersRound, Wallet } from 'lucide-react';
import { appNavigationItems } from './app-navigation';
import { financeNavigationItems } from './finance-navigation';

export type MobileMoreGroupKey = 'sales' | 'customers' | 'delivery' | 'finance' | 'channels' | 'strategy' | 'organization';

export interface MobileMoreItem {
  path: string;
  href: string;
  label: string;
  desktopOnly?: boolean;
}

export interface MobileMoreSection {
  label: string;
  items: MobileMoreItem[];
}

export interface MobileMoreGroup {
  key: MobileMoreGroupKey;
  label: string;
  icon: LucideIcon;
  sections: MobileMoreSection[];
}

// These administrative tools remain on desktop, matching the mobile launcher.
// Listing them here makes the directory complete without enabling new actions.
const desktopOnlyPaths = new Set(['/settings', '/permissions', '/settings/deduction', '/payroll']);
// Finance currently renders these four mobile views. Other existing tabs keep
// their desktop designation instead of silently opening the mobile overview.
const mobileFinanceTabs = new Set(['overview', 'income', 'subscriptions', 'receivables']);
const labels: Record<string, string> = {
  '/': '今日经营',
  '/company-roadmap': '公司战略',
  '/management-decisions': '经营决策',
  '/customer-lifecycle': '客户周期',
  '/operations-workbench': '运营工作台',
  '/service-board': '服务进度',
};
const navigationByPath = new Map(appNavigationItems.map(item => [item.path, item]));

function page(path: string): MobileMoreItem {
  return {
    path,
    href: path,
    label: labels[path] || navigationByPath.get(path)!.label,
    ...(desktopOnlyPaths.has(path) ? { desktopOnly: true } : {}),
  };
}

function financeTab(tab: string): MobileMoreItem {
  const item = financeNavigationItems.find(entry => entry.tab === tab)!;
  return {
    path: '/finance',
    href: tab === 'overview' ? '/finance' : `/finance?tab=${tab}`,
    label: tab === 'overview' ? '财务总览' : item.label,
    ...(!mobileFinanceTabs.has(tab) ? { desktopOnly: true } : {}),
  };
}

const mobileMoreGroups: MobileMoreGroup[] = [
  {
    key: 'sales', label: '销售中心', icon: Headphones,
    sections: [{ label: '销售工作', items: ['/sales-workbench', '/sales-leads', '/merchant-pool', '/sales-knowledge'].map(page) }],
  },
  {
    key: 'customers', label: '客户中心', icon: UsersRound,
    sections: [{ label: '客户业务', items: ['/customers', '/deals', '/sales', '/customer-lifecycle'].map(page) }],
  },
  {
    key: 'delivery', label: '任务交付', icon: ClipboardCheck,
    sections: [{ label: '交付工作', items: ['/operations-workbench', '/tasks', '/service-board', '/callbacks'].map(page) }],
  },
  {
    key: 'finance', label: '财务结算', icon: Wallet,
    sections: [
      { label: '日常账目', items: ['overview', 'income', 'subscriptions', 'receivables'].map(financeTab) },
      { label: '明细与分析', items: ['monthly_detail', 'customer_profit', 'refunds', 'ad_funds', 'customer_expense', 'company_expense', 'charts'].map(financeTab) },
      { label: '财务设置', items: ['/rmb-profit', '/payroll', '/settings/deduction'].map(page) },
    ],
  },
  {
    key: 'channels', label: '渠道分润', icon: Handshake,
    sections: [{ label: '渠道合作', items: ['/commissions', '/partner-portal'].map(page) }],
  },
  {
    key: 'strategy', label: '经营中心', icon: Target,
    sections: [{ label: '经营管理', items: ['/', '/company-roadmap', '/management-decisions'].map(page) }],
  },
  {
    key: 'organization', label: '组织设置', icon: Building2,
    sections: [
      { label: '团队管理', items: ['/employees'].map(page) },
      { label: '系统管理', items: ['/settings', '/permissions'].map(page) },
    ],
  },
];

/** Navigation metadata only. Permissions and business routes retain their existing checks. */
export function getMobileMoreGroups(canAccess: (path: string) => boolean): MobileMoreGroup[] {
  return mobileMoreGroups.map(group => ({
    ...group,
    sections: group.sections.map(section => ({
      ...section,
      items: section.items.filter(item => canAccess(item.path)),
    })).filter(section => section.items.length > 0),
  })).filter(group => group.sections.length > 0);
}

export function getMobileMoreGroupPath(key: MobileMoreGroupKey) {
  return `/more?group=${key}`;
}
