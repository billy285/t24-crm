import {
  ArrowDownRight, ArrowRightLeft, Building2, CalendarDays, DollarSign,
  PieChart, Receipt, TrendingUp, Users, Wallet,
} from 'lucide-react';

/** Presentation metadata for the existing finance tabs; no additional routes or permissions. */
export const financeNavigationItems = [
  { tab: 'overview', label: '老板总览', group: '常用操作', icon: Wallet, description: '掌握收入、成本、利润和待处理事项' },
  { tab: 'income', label: '收入管理', group: '常用操作', icon: DollarSign, description: '查询收款记录，核对到账与收入明细' },
  { tab: 'subscriptions', label: '套餐续费', group: '常用操作', icon: Receipt, description: '跟进套餐到期、待扣款与续费事项' },
  { tab: 'monthly_detail', label: '按月明细', group: '常用操作', icon: CalendarDays, description: '逐月核对收入、支出与利润，完成月度关账' },
  { tab: 'customer_profit', label: '客户利润', group: '财务明细', icon: TrendingUp, description: '按客户核对收入、成本与利润' },
  { tab: 'receivables', label: '应收欠款', group: '财务明细', icon: Users, description: '查看客户应收与欠款，跟进待收款项' },
  { tab: 'refunds', label: '退款记录', group: '财务明细', icon: ArrowDownRight, description: '查询退款明细，核对实际退款日期与金额' },
  { tab: 'ad_funds', label: '投流月结', group: '财务明细', icon: ArrowRightLeft, description: '核对投流资金、广告实支与月结记录' },
  { tab: 'customer_expense', label: '客户支出', group: '财务明细', icon: Receipt, description: '查询并核对客户相关支出' },
  { tab: 'company_expense', label: '运营支出', group: '财务明细', icon: Building2, description: '查询并核对公司日常运营支出' },
  { tab: 'charts', label: '数据分析', group: '分析与设置', icon: PieChart, description: '查看收入、成本与利润的变化趋势' },
];

const financeTabValues = new Set(financeNavigationItems.map(item => item.tab));

export const normalizeFinanceTab = (tab?: string | null) => (
  tab && financeTabValues.has(tab) ? tab : 'overview'
);

export function getFinanceNavigationItem(tab?: string | null) {
  return financeNavigationItems.find(item => item.tab === normalizeFinanceTab(tab))!;
}
