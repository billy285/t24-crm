import { lazy, Suspense, useState, useEffect, useMemo, useRef, type CSSProperties } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { client } from '../lib/api';
import { invokeWithAuth } from '@/lib/tokenStore';
import { useRole } from '../lib/role-context';
import { countries, getStatesForCountry, getCitiesForState, getCountryLabel, getStateLabel } from '../lib/country-state-data';
import { logOperation } from '../lib/operation-log-helper';
import { allStageLabels, issueStatusColors, issueStatusLabels, priorityColors, priorityLabels, serviceTypeLabels, taskStatusColors, taskStatusLabels, taskTypeLabels } from '../lib/service-board-config';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { Textarea } from '@/components/ui/textarea';
import { toast } from 'sonner';
import { Plus, Search, ArrowLeft, Phone, Mail, MapPin, Globe, Edit, Trash2, SlidersHorizontal, X, MessageSquarePlus, Columns3, AlertCircle, UserPlus, Users, ArrowRightLeft, RefreshCw, MoreHorizontal, Activity, Building2, CalendarClock, ChevronRight, ShieldCheck } from 'lucide-react';
import { NativeSelect } from '@/components/ui/native-select';
import ExportButton from '@/components/ExportButton';
import ConfirmDialog from '@/components/ConfirmDialog';
import MediaAccountsTab from '@/components/MediaAccountsTab';
import OperationLogsTab from '@/components/OperationLogsTab';
import CustomerAiCopyTab from '@/components/CustomerAiCopyTab';
import CustomerMaterialsTab from '@/components/CustomerMaterialsTab';
import CustomerOpportunitiesTab from '@/components/CustomerOpportunitiesTab';
import { loadSettings, generateNextCode, type CustomerCodeSettings } from '../lib/customer-code-settings';
import { saveRemoteAppConfig } from '../lib/app-config';
import {
  buildOptionKey,
  classifyPackageDisplay,
  customerPlatformLabels,
  platformLabels,
  sanitizeDictLabel,
  serializeDictEntries,
  useBusinessDicts,
  useDictConfig,
} from '../lib/dict-config';
import { getPaymentMethodLabel, getPaymentModeLabel, inferPaymentModeKey, normalizePaymentMethodKey } from '../lib/payment-utils';
import { businessDateKey } from '../lib/business-date';
import {
  computeSubscriptionStatus,
  decorateEffectiveSubscriptions,
  getSubscriptionRemainingDays,
} from '../lib/subscription-utils';
import { useAutoRefresh } from '../lib/use-auto-refresh';
import PageLoadState from '@/components/PageLoadState';
import { getLoadErrorMessage, loadWithRetry } from '../lib/load-utils';
import { getReturnLabel, getSafeInternalPath } from '../lib/navigation-state';
import { useIsMobile } from '@/hooks/use-mobile';

const ImportCustomers = lazy(() => import('@/components/ImportCustomers'));

const statusColors: Record<string, string> = { new: 'bg-blue-100 text-blue-700', following: 'bg-amber-100 text-amber-700', closed: 'bg-green-100 text-green-700', paused: 'bg-slate-100 text-slate-600', lost: 'bg-red-100 text-red-700' };
const levelColors: Record<string, string> = { high: 'bg-orange-100 text-orange-700', normal: 'bg-slate-100 text-slate-600', low: 'bg-gray-100 text-gray-500', vip: 'bg-purple-100 text-purple-700' };
const subStatusColors: Record<string, string> = { active: 'bg-green-100 text-green-700', expiring_soon: 'bg-amber-100 text-amber-700', expired: 'bg-red-100 text-red-700', paused: 'bg-slate-100 text-slate-600', lost: 'bg-red-100 text-red-700' };
const contactRoleLabels: Record<string, string> = { boss: '老板', manager: '经理', staff: '员工', other: '其他' };
const defaultLevelColorClass = 'bg-slate-100 text-slate-700';
const MANAGEMENT_FEE_KEY = 'management_fee';
const ADS_FEE_KEY = 'ads_fee';
const MIXED_MANAGEMENT_ADS_KEY = 'management_ads_mixed';
const DEFAULT_MANAGEMENT_DEDUCTION_RATE = 0.15;
const ADS_RECHARGE_DEDUCTION_RATE = 0.01;
const STRIPE_PLATFORM_FEE_RATE = 0.029;
const STRIPE_PLATFORM_FEE_FIXED = 0.3;
const CUSTOMER_PAGE_SIZE_OPTIONS = [20, 50, 100];
const customerTimestampFormatter = new Intl.DateTimeFormat('zh-CN', {
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hour12: false,
});
type CustomerAccessLevel = 'read_only' | 'read_write';
const lifecycleEventLabels: Record<string, string> = {
  started: '第一笔有效记账', pause: '暂停合作', pending_stop: '进入待确认停止',
  resume: '恢复合作', stop: '停止合作', reactivate: '重新合作', adjust_start: '修正合作开始日期',
};

type PaginationResult<T> = {
  items: T[];
  page: number;
  pageSize: number;
  total: number;
  totalPages: number;
  start: number;
  end: number;
};

const paginateList = <T,>(items: T[], page: number, pageSize: number): PaginationResult<T> => {
  const total = items.length;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const safePage = Math.min(Math.max(page || 1, 1), totalPages);
  const offset = (safePage - 1) * pageSize;
  return {
    items: items.slice(offset, offset + pageSize),
    page: safePage,
    pageSize,
    total,
    totalPages,
    start: total === 0 ? 0 : offset + 1,
    end: Math.min(offset + pageSize, total),
  };
};

const emptyForm = {
  customer_code: '', business_name: '', contact_name: '', phone: '', wechat: '', email: '',
  address: '', city: '', state: 'CA', country: 'US', industry: 'restaurant', website: '',
  google_business_link: '', facebook_link: '', instagram_link: '', yelp_link: '', tiktok_link: '',
  has_ordering_system: false, current_platform: '无', selected_platforms: [] as string[], interested_packages: [] as string[], monthly_orders: 0,
  interested_packages_snapshot: {} as Record<string, string>,
  source: 'phone', sales_person: '', sales_employee_id: '' as string | number, level: 'normal', status: 'new', notes: '',
};

type CustomerProjectDraft = {
  engagement_id?: number;
  business_line_code: string;
  product_code: string;
  product_name: string;
  package_name: string;
  status: string;
  billing_cycle: string;
  collection_method: string;
  currency: string;
  owner_employee_id: string;
  paid_started_at: string;
  stopped_at: string;
  stop_reason_code: string;
  stop_note: string;
};

const customerProjectLines: Record<string, { label: string; productCode: string; productName: string }> = {
  managed_service: { label: '代运营', productCode: 'managed_service_legacy', productName: '代运营服务' },
  restaurant_os: { label: '餐饮 OS', productCode: 'restaurant_os_legacy', productName: '餐饮 OS' },
  beauty_os: { label: '美业 OS', productCode: 'beauty_os_legacy', productName: '美业 OS' },
  one_time_project: { label: '一次性项目', productCode: 'one_time_legacy', productName: '一次性项目' },
};

const customerProjectStatuses: Record<string, string> = {
  pending_setup: '待开通', trial: '试用中', active_paid: '付费合作中', at_risk: '有流失风险',
  paused: '项目暂停', pending_stop: '待停止', stopped: '项目已停止', reactivated: '重新合作', completed: '一次性项目完成',
};

const activeCustomerProjectStatuses = new Set(['pending_setup', 'trial', 'active_paid', 'at_risk', 'paused', 'pending_stop', 'reactivated']);

const customerProjectStopReasons: Record<string, string> = {
  performance: '效果不满意', price: '价格问题', service: '服务问题', closed_business: '客户关店',
  business_difficulty: '客户经营困难', changed_provider: '更换服务商', seasonal_pause: '季节性暂停',
  payment: '付款问题', owner_change: '老板变更', data_correction: '历史数据修正', other: '其他',
};

const customerProjectBillingCycles: Record<string, string> = {
  monthly: '月付', quarterly: '季付', annual: '年付', one_time: '一次性',
};

const customerProjectCollectionMethods: Record<string, string> = {
  stripe_auto: 'Stripe 自动扣款', bank_transfer: '银行转账', check: '支票', zelle: 'Zelle', other: '其他',
};

function newCustomerProject(lineCode = 'managed_service'): CustomerProjectDraft {
  const line = customerProjectLines[lineCode] || customerProjectLines.managed_service;
  return {
    business_line_code: lineCode,
    product_code: line.productCode,
    product_name: line.productName,
    package_name: line.productName,
    status: 'pending_setup',
    billing_cycle: lineCode === 'one_time_project' ? 'one_time' : 'monthly',
    collection_method: 'other',
    currency: 'USD',
    owner_employee_id: '',
    paid_started_at: '',
    stopped_at: '',
    stop_reason_code: '',
    stop_note: '',
  };
}

const allColumns = [
  { key: 'customer_code', label: '编号', d: true }, { key: 'business_name', label: '商家名称', d: true },
  { key: 'contact_name', label: '联系人', d: true }, { key: 'phone', label: '电话', d: true },
  { key: 'state', label: '州/省', d: true }, { key: 'country', label: '国家', d: true },
  { key: 'industry', label: '行业', d: true }, { key: 'city', label: '城市', d: false },
  { key: 'status', label: '状态', d: true }, { key: 'level', label: '等级', d: true },
  { key: 'sales_person', label: '负责人', d: true }, { key: 'email', label: '邮箱', d: false },
  { key: 'wechat', label: '微信', d: false }, { key: 'source', label: '来源', d: false },
];

const COLS_KEY = 'crm_visible_columns';
const legacyDefaultColumns = ['customer_code', 'business_name', 'contact_name', 'phone', 'city', 'industry', 'status', 'level', 'sales_person'];
const preferredDefaultColumns = allColumns.filter(c => c.d).map(c => c.key);

function loadCols(): string[] {
  try {
    const s = localStorage.getItem(COLS_KEY);
    if (s) {
      const parsed = JSON.parse(s);
      if (Array.isArray(parsed)) {
        const validKeys = new Set(allColumns.map(col => col.key));
        const sanitized = parsed.filter((key): key is string => typeof key === 'string' && validKeys.has(key));
        const isLegacyDefault = sanitized.length === legacyDefaultColumns.length
          && legacyDefaultColumns.every(key => sanitized.includes(key))
          && !sanitized.includes('state')
          && !sanitized.includes('country');
        if (isLegacyDefault) {
          localStorage.setItem(COLS_KEY, JSON.stringify(preferredDefaultColumns));
          return preferredDefaultColumns;
        }
        return sanitized;
      }
    }
  } catch { /* */ }
  return preferredDefaultColumns;
}

const emptyAdvancedFilters = {
  customer_code: '',
  business_name: '',
  contact_name: '',
  phone: '',
  city: '',
  industry: '',
  status: '',
  level: '',
  sales_person: '',
  source: '',
  wechat: '',
  email: '',
  country: '',
  state: '',
};

const inlineSelectClassName = 'h-8 w-full min-w-[110px] rounded-md border border-slate-200 bg-white px-2 text-sm text-slate-700 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:cursor-not-allowed disabled:opacity-60';
const inlineInputClassName = 'h-8 w-full min-w-[110px] rounded-md border border-slate-200 bg-white px-2 text-sm text-slate-700 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:cursor-not-allowed disabled:opacity-60';
const customerDetailTabValues = new Set(['overview', 'info', 'timeline', 'contacts', 'opportunities', 'followups', 'deals', 'subscriptions', 'payments', 'renewals', 'materials', 'ai_copy', 'media', 'logs']);
const customerReminderMessages: Record<string, { title: string; description: string }> = {
  follow_up_today: { title: '今日跟进提醒', description: '这位客户今天需要继续跟进，已为你直接打开跟进记录。' },
  follow_up_overdue: { title: '逾期跟进提醒', description: '这位客户的计划跟进时间已过，建议尽快补跟进并更新下一次时间。' },
  no_follow_7d: { title: '长期未跟进提醒', description: '这位客户最近 7 天没有新的跟进记录，建议先补充沟通情况。' },
  renewal_due: { title: '续费提醒', description: '这位客户的服务临近到期，已为你打开续费信息方便处理。' },
  overdue_payment: { title: '欠费提醒', description: '这位客户存在未结清款项，已为你打开财务信息方便核对。' },
};

function buildInlineOptions(value: string | undefined, labels: Record<string, string>) {
  const options = Object.entries(labels).map(([key, label]) => ({ value: key, label }));
  if (value && !labels[value]) {
    options.unshift({ value, label: value });
  }
  return options;
}

function getLevelColorClass(level?: string) {
  return levelColors[level || ''] || defaultLevelColorClass;
}

function formatCustomerTimestamp(value: string | null) {
  if (!value) return '尚未完成加载';
  return customerTimestampFormatter.format(new Date(value));
}

function CustomerListLoadingState() {
  return (
    <div aria-live="polite" aria-label="客户资料加载中">
      <div className="grid gap-3 p-3 md:hidden">
        {[0, 1, 2].map(item => (
          <div key={item} className="animate-pulse rounded-xl border border-slate-200 bg-white p-4">
            <div className="flex items-start justify-between gap-4">
              <div className="space-y-2"><div className="h-4 w-36 rounded bg-slate-200" /><div className="h-3 w-20 rounded bg-slate-100" /></div>
              <div className="h-5 w-16 rounded-full bg-slate-100" />
            </div>
            <div className="mt-5 grid grid-cols-2 gap-4">
              {[0, 1, 2, 3].map(cell => <div key={cell} className="h-9 rounded bg-slate-100" />)}
            </div>
            <div className="mt-4 h-11 rounded-lg bg-slate-200" />
          </div>
        ))}
      </div>
      <div className="hidden animate-pulse md:block">
        <div className="grid grid-cols-6 gap-4 border-b border-slate-200 bg-slate-50 px-4 py-3">
          {[0, 1, 2, 3, 4, 5].map(item => <div key={item} className="h-3 rounded bg-slate-200" />)}
        </div>
        {[0, 1, 2, 3, 4, 5].map(row => (
          <div key={row} className="grid grid-cols-6 gap-4 border-b border-slate-100 px-4 py-4">
            {[0, 1, 2, 3, 4, 5].map(cell => <div key={cell} className="h-4 rounded bg-slate-100" />)}
          </div>
        ))}
      </div>
      <span className="sr-only">客户资料正在加载，完成后会自动显示真实数据。</span>
    </div>
  );
}

function parseMultiValue(value?: string | null) {
  return (value || '')
    .split(',')
    .map(item => item.trim())
    .filter(Boolean);
}

function parsePackageSnapshot(value?: string | null): Record<string, string> {
  if (!value) return {};
  try {
    const parsed = JSON.parse(value);
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return {};
    return Object.entries(parsed).reduce<Record<string, string>>((acc, [key, raw]) => {
      if (!key) return acc;
      if (typeof raw === 'string') {
        acc[key] = raw;
        return acc;
      }
      if (raw && typeof raw === 'object' && typeof (raw as any).label === 'string') {
        acc[key] = (raw as any).label;
      }
      return acc;
    }, {});
  } catch {
    return {};
  }
}

function serializePackageSnapshot(snapshot: Record<string, string>) {
  const normalized = Object.entries(snapshot).reduce<Record<string, string>>((acc, [key, label]) => {
    const safeLabel = normalizePackageLabel(label || key);
    if (key && safeLabel) acc[key] = safeLabel;
    return acc;
  }, {});
  return JSON.stringify(normalized);
}

type PackageDraft = { key: string; label: string; platforms: string[] };

function normalizePackageLabel(label: string) {
  return sanitizeDictLabel(label).replace(/\s+/g, ' ').trim();
}

function parsePackageNameInput(value: string) {
  return value
    .split(/[\n,，;；]+/)
    .map(normalizePackageLabel)
    .filter(Boolean);
}

function buildUniquePackageKey(label: string, usedKeys: Set<string>) {
  const baseKey = buildOptionKey(label);
  let key = baseKey;
  while (usedKeys.has(key)) {
    key = `${baseKey}_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`;
  }
  usedKeys.add(key);
  return key;
}

function appendPackageDrafts(baseDrafts: PackageDraft[], rawInput: string) {
  const labels = parsePackageNameInput(rawInput);
  const nextDrafts = [...baseDrafts];
  const usedKeys = new Set(nextDrafts.map(item => item.key));
  const seenLabels = new Set(
    nextDrafts
      .map(item => normalizePackageLabel(item.label).toLowerCase())
      .filter(Boolean)
  );
  const duplicates: string[] = [];

  labels.forEach(label => {
    const normalizedKey = label.toLowerCase();
    if (seenLabels.has(normalizedKey)) {
      if (!duplicates.includes(label)) duplicates.push(label);
      return;
    }
    seenLabels.add(normalizedKey);
    nextDrafts.push({ key: buildUniquePackageKey(label, usedKeys), label, platforms: [] });
  });

  return {
    drafts: nextDrafts,
    addedCount: nextDrafts.length - baseDrafts.length,
    duplicates,
  };
}

function getErrorDetail(err: any, fallback: string) {
  const message = err?.data?.detail || err?.response?.data?.detail || err?.message || '';
  if (/Network Error|Failed to fetch/i.test(message)) {
    return '网络连接失败，系统已自动重试但仍未成功。请强制刷新页面或重新登录后再保存。';
  }
  return message || fallback;
}

function formatCurrency(value: number) {
  return `$${Number(value || 0).toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 2 })}`;
}

function formatCurrencyByCode(value: number, currency?: string | null) {
  if (currency === 'CNY') {
    return `¥${Number(value || 0).toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 2 })}`;
  }
  return formatCurrency(value);
}

function roundMoney(value: number) {
  return Math.round(Number(value || 0) * 100) / 100;
}

function toMoneyNumber(value: any) {
  const n = Number(value || 0);
  return Number.isFinite(n) ? n : 0;
}

function getStoredMoney(value: any) {
  if (value === null || value === undefined || value === '') return null;
  const n = Number(value);
  return Number.isFinite(n) ? roundMoney(n) : null;
}

function normalizeCurrencyCode(currency?: string | null) {
  return currency === 'CNY' ? 'CNY' : 'USD';
}

function getPaymentYearMonth(payment: any) {
  const ym = (payment?.payment_date || payment?.created_at || '').slice(0, 7);
  return /^\d{4}-\d{2}$/.test(ym) ? ym : '';
}

function getDeductionRate(rates: Record<string, number>, ym: string) {
  return typeof rates[ym] === 'number' ? rates[ym] : DEFAULT_MANAGEMENT_DEDUCTION_RATE;
}

function isStripeSubscriptionPayment(payment: any) {
  const method = normalizePaymentMethodKey(payment?.payment_method);
  return method === 'stripe' || (inferPaymentModeKey(payment || {}) === 'subscription_auto' && !payment?.payment_method);
}

function calculateStripePlatformFee(payment: any) {
  const stored = getStoredMoney(payment?.stripe_fee_amount);
  if (stored !== null) return stored;
  const amount = toMoneyNumber(payment?.amount_paid);
  if (amount <= 0 || !isStripeSubscriptionPayment(payment)) return 0;
  return roundMoney(amount * STRIPE_PLATFORM_FEE_RATE + STRIPE_PLATFORM_FEE_FIXED);
}

function getManagementRevenueAmount(payment: any) {
  const stored = getStoredMoney(payment?.management_amount);
  if (stored !== null) return stored;
  return payment?.income_type === MANAGEMENT_FEE_KEY ? roundMoney(toMoneyNumber(payment?.amount_paid)) : 0;
}

function getAdsRechargeAmount(payment: any) {
  const stored = getStoredMoney(payment?.ads_recharge_amount);
  if (stored !== null) return stored;
  return payment?.income_type === ADS_FEE_KEY ? roundMoney(toMoneyNumber(payment?.amount_paid)) : 0;
}

function getPaymentDisplayIncomeType(payment: any) {
  return getManagementRevenueAmount(payment) > 0 && getAdsRechargeAmount(payment) > 0
    ? MIXED_MANAGEMENT_ADS_KEY
    : (payment?.income_type || 'other_income');
}

function buildCustomerPaymentFinanceLine(payment: any, deductionRates: Record<string, number>) {
  const amountPaid = roundMoney(toMoneyNumber(payment?.amount_paid));
  const managementAmount = getManagementRevenueAmount(payment);
  const adsRechargeAmount = getAdsRechargeAmount(payment);
  const otherAmount = roundMoney(Math.max(amountPaid - managementAmount - adsRechargeAmount, 0));
  const yearMonth = getPaymentYearMonth(payment);
  const managementRate = getDeductionRate(deductionRates, yearMonth);
  const managementDeduction = roundMoney(managementAmount * managementRate);
  const adsDeduction = roundMoney(adsRechargeAmount * ADS_RECHARGE_DEDUCTION_RATE);
  const stripeFee = calculateStripePlatformFee(payment);
  const feeAndDeduction = roundMoney(managementDeduction + adsDeduction + stripeFee);
  return {
    payment,
    yearMonth: yearMonth || '未归属月份',
    amountPaid,
    managementAmount,
    adsRechargeAmount,
    otherAmount,
    managementRate,
    managementDeduction,
    adsDeduction,
    stripeFee,
    feeAndDeduction,
    netBeforeCustomerCost: roundMoney(amountPaid - feeAndDeduction),
  };
}

function buildCustomerFinanceSummary(
  paymentItems: any[],
  expenseItems: any[],
  deductionRates: Record<string, number>,
) {
  const paymentLines = paymentItems.map(payment => buildCustomerPaymentFinanceLine(payment, deductionRates));
  const totals = paymentLines.reduce((acc, line) => {
    acc.revenue += line.amountPaid;
    acc.managementRevenue += line.managementAmount;
    acc.adsRevenue += line.adsRechargeAmount;
    acc.otherRevenue += line.otherAmount;
    acc.managementDeduction += line.managementDeduction;
    acc.adsDeduction += line.adsDeduction;
    acc.stripeFee += line.stripeFee;
    acc.feeAndDeduction += line.feeAndDeduction;
    acc.netBeforeCustomerCost += line.netBeforeCustomerCost;
    return acc;
  }, {
    revenue: 0,
    managementRevenue: 0,
    adsRevenue: 0,
    otherRevenue: 0,
    managementDeduction: 0,
    adsDeduction: 0,
    stripeFee: 0,
    feeAndDeduction: 0,
    netBeforeCustomerCost: 0,
  });

  const customerCostUsd = expenseItems
    .filter(item => normalizeCurrencyCode(item.currency) === 'USD')
    .reduce((sum, item) => sum + toMoneyNumber(item.amount), 0);
  const customerCostCny = expenseItems
    .filter(item => normalizeCurrencyCode(item.currency) === 'CNY')
    .reduce((sum, item) => sum + toMoneyNumber(item.amount), 0);

  const monthlyMap = new Map<string, {
    month: string;
    revenue: number;
    managementRevenue: number;
    adsRevenue: number;
    feeAndDeduction: number;
    customerCostUsd: number;
    profitUsd: number;
  }>();
  const getMonthBucket = (month: string) => {
    if (!monthlyMap.has(month)) {
      monthlyMap.set(month, {
        month,
        revenue: 0,
        managementRevenue: 0,
        adsRevenue: 0,
        feeAndDeduction: 0,
        customerCostUsd: 0,
        profitUsd: 0,
      });
    }
    return monthlyMap.get(month)!;
  };

  paymentLines.forEach(line => {
    const bucket = getMonthBucket(line.yearMonth);
    bucket.revenue += line.amountPaid;
    bucket.managementRevenue += line.managementAmount;
    bucket.adsRevenue += line.adsRechargeAmount;
    bucket.feeAndDeduction += line.feeAndDeduction;
  });

  expenseItems.forEach(expense => {
    if (normalizeCurrencyCode(expense.currency) !== 'USD') return;
    const month = /^\d{4}-\d{2}$/.test(expense.expense_month || '')
      ? expense.expense_month
      : (expense.expense_date || expense.created_at || '').slice(0, 7);
    const bucket = getMonthBucket(/^\d{4}-\d{2}$/.test(month) ? month : '未归属月份');
    bucket.customerCostUsd += toMoneyNumber(expense.amount);
  });

  const monthlyRows = Array.from(monthlyMap.values())
    .map(row => ({
      ...row,
      revenue: roundMoney(row.revenue),
      managementRevenue: roundMoney(row.managementRevenue),
      adsRevenue: roundMoney(row.adsRevenue),
      feeAndDeduction: roundMoney(row.feeAndDeduction),
      customerCostUsd: roundMoney(row.customerCostUsd),
      profitUsd: roundMoney(row.revenue - row.feeAndDeduction - row.customerCostUsd),
    }))
    .sort((a, b) => b.month.localeCompare(a.month));

  return {
    paymentLines,
    monthlyRows,
    totalRevenue: roundMoney(totals.revenue),
    managementRevenue: roundMoney(totals.managementRevenue),
    adsRevenue: roundMoney(totals.adsRevenue),
    otherRevenue: roundMoney(totals.otherRevenue),
    managementDeduction: roundMoney(totals.managementDeduction),
    adsDeduction: roundMoney(totals.adsDeduction),
    stripeFee: roundMoney(totals.stripeFee),
    feeAndDeduction: roundMoney(totals.feeAndDeduction),
    netBeforeCustomerCost: roundMoney(totals.netBeforeCustomerCost),
    customerCostUsd: roundMoney(customerCostUsd),
    customerCostCny: roundMoney(customerCostCny),
    profitUsd: roundMoney(totals.revenue - totals.feeAndDeduction - customerCostUsd),
  };
}

function computeSubscriptionState(subscription: any) {
  return computeSubscriptionStatus(subscription);
}

const subscriptionStatusView: Record<string, { label: string; cardClass: string; badgeClass: string }> = {
  active: { label: '正常', cardClass: 'border-slate-200 bg-slate-50', badgeClass: 'bg-green-100 text-green-700' },
  expiring_soon: { label: '即将到期', cardClass: 'border-amber-200 bg-amber-50', badgeClass: 'bg-amber-100 text-amber-700' },
  renewal_pending: { label: '待扣款确认', cardClass: 'border-cyan-200 bg-cyan-50', badgeClass: 'bg-cyan-100 text-cyan-700' },
  expired: { label: '已到期', cardClass: 'border-red-200 bg-red-50', badgeClass: 'bg-red-100 text-red-700' },
  renewed: { label: '已续费', cardClass: 'border-emerald-200 bg-emerald-50', badgeClass: 'bg-emerald-100 text-emerald-700' },
  paused: { label: '暂停', cardClass: 'border-slate-200 bg-slate-50', badgeClass: 'bg-slate-100 text-slate-600' },
  lost: { label: '流失', cardClass: 'border-red-200 bg-red-50', badgeClass: 'bg-red-100 text-red-700' },
  upgraded: { label: '已升级结束', cardClass: 'border-violet-200 bg-violet-50', badgeClass: 'bg-violet-100 text-violet-700' },
  stopped: { label: '停止续费', cardClass: 'border-slate-200 bg-slate-50', badgeClass: 'bg-slate-200 text-slate-700' },
};
const archivedSubscriptionStatuses = new Set(['stopped', 'lost', 'paused', 'upgraded', 'renewed']);

export default function Customers() {
  const navigate = useNavigate();
  const { role, employee, hasPermission, isAdmin, dataScope, canViewFinance } = useRole();
  const isMobile = useIsMobile();
  const businessToday = businessDateKey();
  const dictConfig = useDictConfig();
  const businessDicts = useBusinessDicts();
  const industryLabels = businessDicts.industries;
  const statusLabels = businessDicts.statuses;
  const levelLabels = businessDicts.levels;
  const sourceLabels = businessDicts.sources;
  const stageLabels = businessDicts.followUpStages;
  const productLabels = businessDicts.products;
  const incomeTypeLabels = businessDicts.incomeTypes;
  const customerPackageLabels = businessDicts.customerPackages;
  const cycleLabels = businessDicts.billingCycles;
  const payModeLabels = businessDicts.paymentModes;
  const payMethodLabels = businessDicts.paymentMethods;
  const customerExpenseTypeLabels = businessDicts.customerExpenseTypes;
  const subStatusLabels = businessDicts.subscriptionStatuses;
  const methodLabels = businessDicts.followUpMethods;
  const canManageDict = isAdmin || hasPermission('settings_edit');
  const canCreateFollowUp = isAdmin || hasPermission('follow_up_create');
  const canEditFollowUp = isAdmin || hasPermission('follow_up_edit');
  const canDeleteFollowUp = isAdmin || hasPermission('follow_up_delete');
  const canManageContacts = hasPermission('customer_edit');
  const canDeleteContacts = isAdmin || hasPermission('customer_delete');
  const [searchParams, setSearchParams] = useSearchParams();
  const [customers, setCustomers] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [customersLoadedAt, setCustomersLoadedAt] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [filterStatus, setFilterStatus] = useState('all');
  const [filterIndustry, setFilterIndustry] = useState('all');
  const [filterLevel, setFilterLevel] = useState('all');
  const [filterSource, setFilterSource] = useState('all');
  const [customerPage, setCustomerPage] = useState(1);
  const [customerPageSize, setCustomerPageSize] = useState(20);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [advFilters, setAdvFilters] = useState(emptyAdvancedFilters);
  const advFilterCount = Object.values(advFilters).filter(v => v.trim()).length;
  const primaryFilterCount = [filterStatus, filterIndustry, filterLevel, filterSource].filter(value => value !== 'all').length;
  const activeFilterCount = primaryFilterCount + advFilterCount;
  const [mobileFiltersOpen, setMobileFiltersOpen] = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [form, setForm] = useState(emptyForm);
  const [customerProjectForms, setCustomerProjectForms] = useState<CustomerProjectDraft[]>([]);
  const [customerProjectsLoading, setCustomerProjectsLoading] = useState(false);
  const [commissionPartners, setCommissionPartners] = useState<Array<{ id: number; partner_code: string; name: string; partner_type: string }>>([]);
  const [commissionPartnerId, setCommissionPartnerId] = useState('auto');
  const [commissionEffectiveFrom, setCommissionEffectiveFrom] = useState(businessToday);
  const [manualCityInput, setManualCityInput] = useState(false);
  const [selectedCustomer, setSelectedCustomer] = useState<any>(null);
  const [selectedCustomerTab, setSelectedCustomerTab] = useState('overview');
  const [followUps, setFollowUps] = useState<any[]>([]);
  const [deals, setDeals] = useState<any[]>([]);
  const [payments, setPayments] = useState<any[]>([]);
  const [customerExpenses, setCustomerExpenses] = useState<any[]>([]);
  const [customerDeductionRates, setCustomerDeductionRates] = useState<Record<string, number>>({});
  const [subscriptions, setSubscriptions] = useState<any[]>([]);
  const [customerProjects, setCustomerProjects] = useState<any[]>([]);
  const [productCatalog, setProductCatalog] = useState<any>({ business_lines: [], products: [], plans: [] });
  const [serviceProgresses, setServiceProgresses] = useState<any[]>([]);
  const [serviceTasks, setServiceTasks] = useState<any[]>([]);
  const [lifecycleDetail, setLifecycleDetail] = useState<any>(null);
  const [closureSyncing, setClosureSyncing] = useState(false);
  const [followUpPage, setFollowUpPage] = useState(1);
  const [followUpPageSize, setFollowUpPageSize] = useState(20);
  const [dealPage, setDealPage] = useState(1);
  const [dealPageSize, setDealPageSize] = useState(20);
  const [serviceInfoPage, setServiceInfoPage] = useState(1);
  const [serviceInfoPageSize, setServiceInfoPageSize] = useState(20);
  const [financeMonthlyPage, setFinanceMonthlyPage] = useState(1);
  const [financeMonthlyPageSize, setFinanceMonthlyPageSize] = useState(20);
  const [financePaymentPage, setFinancePaymentPage] = useState(1);
  const [financePaymentPageSize, setFinancePaymentPageSize] = useState(20);
  const [financeExpensePage, setFinanceExpensePage] = useState(1);
  const [financeExpensePageSize, setFinanceExpensePageSize] = useState(20);
  const [renewalPage, setRenewalPage] = useState(1);
  const [renewalPageSize, setRenewalPageSize] = useState(20);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailLoadError, setDetailLoadError] = useState<string | null>(null);
  const [detailLoadedAt, setDetailLoadedAt] = useState<string | null>(null);
  const detailRequestSeqRef = useRef(0);
  const activeDetailCustomerIdRef = useRef<number | null>(null);
  const [saving, setSaving] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<any>(null);
  const [deleting, setDeleting] = useState(false);
  const [codeSettings, setCodeSettings] = useState<CustomerCodeSettings>(loadSettings());
  const [duplicateWarning, setDuplicateWarning] = useState<string | null>(null);
  const [visibleCols, setVisibleCols] = useState<string[]>(loadCols());
  const [showColPicker, setShowColPicker] = useState(false);
  const [inlineEditMode, setInlineEditMode] = useState(false);
  const [showFollowForm, setShowFollowForm] = useState(false);
  const [savingFollow, setSavingFollow] = useState(false);
  const [editingFollowId, setEditingFollowId] = useState<number | null>(null);
  const [deleteFollowTarget, setDeleteFollowTarget] = useState<any>(null);
  const [deletingFollow, setDeletingFollow] = useState(false);
  const emptyFollowForm = { contact_method: 'phone', content: '', customer_needs: '', customer_pain_points: '', has_quoted: false, quote_plan: '', close_probability: 30, stage: 'communicating', next_follow_date: '' };
  const [followForm, setFollowForm] = useState(emptyFollowForm);

  // Owner contacts state
  const [contacts, setContacts] = useState<any[]>([]);
  const [showContactForm, setShowContactForm] = useState(false);
  const [editingContactId, setEditingContactId] = useState<number | null>(null);
  const [savingContact, setSavingContact] = useState(false);
  const [deleteContactTarget, setDeleteContactTarget] = useState<any>(null);
  const [deletingContact, setDeletingContact] = useState(false);
  const emptyContactForm = { contact_name: '', contact_phone: '', contact_role: 'boss', notes: '' };
  const [contactForm, setContactForm] = useState(emptyContactForm);

  // Dynamic industry labels
  const [showAddIndustry, setShowAddIndustry] = useState(false);
  const [newIndustryName, setNewIndustryName] = useState('');
  const [showLevelManager, setShowLevelManager] = useState(false);
  const [newLevelName, setNewLevelName] = useState('');
  const [levelDrafts, setLevelDrafts] = useState<Array<{ key: string; label: string }>>([]);
  const [savingLevels, setSavingLevels] = useState(false);
  const [showPackageManager, setShowPackageManager] = useState(false);
  const [newPackageName, setNewPackageName] = useState('');
  const [packageDrafts, setPackageDrafts] = useState<PackageDraft[]>([]);
  const [savingPackages, setSavingPackages] = useState(false);

  const getPackageLabelForSnapshot = (key: string, snapshot?: Record<string, string>) => (
    snapshot?.[key] || customerPackageLabels[key] || key
  );

  const getCustomerPackageLabel = (customer: any, key: string) => (
    customerPackageLabels[key] || getPackageLabelForSnapshot(key, parsePackageSnapshot(customer?.interested_packages_snapshot))
  );

  const getHistoricalPackageLabel = (customer: any, key: string) => {
    const historical = getPackageLabelForSnapshot(key, parsePackageSnapshot(customer?.interested_packages_snapshot));
    const active = customerPackageLabels[key] || historical;
    return historical !== active ? historical : '';
  };

  const getPackageClassification = (packageName?: string | null) => (
    classifyPackageDisplay(packageName, customerPackageLabels)
  );

  const packageOptionsForForm = useMemo(() => {
    const activeEntries = Object.entries(customerPackageLabels).map(([key, label]) => ({
      key,
      label,
      activeLabel: label,
      historical: false,
    }));
    const activeKeys = new Set(activeEntries.map(item => item.key));
    const historicalEntries = form.interested_packages
      .filter(key => !activeKeys.has(key))
      .map(key => ({
        key,
        label: form.interested_packages_snapshot[key] || key,
        activeLabel: '',
        historical: true,
      }));
    return [...activeEntries, ...historicalEntries];
  }, [customerPackageLabels, form.interested_packages, form.interested_packages_snapshot]);

  const platformOptionsForForm = useMemo(
    () => Object.entries(customerPlatformLabels).map(([key, label]) => ({ key, label })),
    [],
  );

  const formatSelectedPlatforms = (value?: string | string[] | null) => {
    const platforms = Array.isArray(value) ? value : parseMultiValue(value);
    return platforms.length > 0
      ? platforms.map(platform => customerPlatformLabels[platform] || platformLabels[platform] || platform).join('、')
      : '-';
  };

  const handleAddIndustry = async () => {
    const name = newIndustryName.trim();
    if (!name) { toast.error('请输入行业名称'); return; }
    if (!canManageDict) {
      toast.error('仅管理员可新增全局行业，请在系统设置中维护');
      return;
    }
    let key = buildOptionKey(name);
    if (industryLabels[key]) {
      key = `${key}_${Date.now()}`;
    }
    if (Object.values(industryLabels).includes(name)) {
      toast.error('该行业已存在'); return;
    }
    try {
      const nextDictConfig = {
        ...dictConfig,
        industries: serializeDictEntries({ ...industryLabels, [key]: name }),
      };
      await saveRemoteAppConfig('dict_config', nextDictConfig);
      setForm({ ...form, industry: key });
      setNewIndustryName('');
      setShowAddIndustry(false);
      toast.success(`已添加行业「${name}」`);
    } catch {
      toast.error('新增行业失败');
    }
  };

  const openLevelManager = () => {
    setLevelDrafts(Object.entries(levelLabels).map(([key, label]) => ({ key, label })));
    setNewLevelName('');
    setShowLevelManager(true);
  };

  const handleAddLevelDraft = () => {
    const label = newLevelName.trim();
    if (!label) { toast.error('请输入等级名称'); return; }
    if (levelDrafts.some(item => item.label.trim() === label)) {
      toast.error('该等级已存在');
      return;
    }
    let key = buildOptionKey(label);
    while (levelDrafts.some(item => item.key === key)) {
      key = `${key}_${Date.now()}`;
    }
    setLevelDrafts(prev => [...prev, { key, label }]);
    setNewLevelName('');
  };

  const handleRemoveLevelDraft = (key: string) => {
    if (levelDrafts.length <= 1) {
      toast.error('至少保留一个客户等级');
      return;
    }
    if (customers.some(customer => customer.level === key)) {
      toast.error('该等级已有客户在使用，请先调整客户等级后再删除');
      return;
    }
    const remaining = levelDrafts.filter(item => item.key !== key);
    setLevelDrafts(remaining);
    if (form.level === key) {
      setForm(prev => ({ ...prev, level: remaining[0]?.key || '' }));
    }
  };

  const handleSaveLevels = async () => {
    const normalizedEntries = levelDrafts.reduce<Record<string, string>>((acc, item) => {
      const label = item.label.trim();
      if (label) {
        acc[item.key] = label;
      }
      return acc;
    }, {});

    const labels = Object.values(normalizedEntries);
    if (labels.length === 0) {
      toast.error('请至少保留一个客户等级');
      return;
    }
    if (new Set(labels).size !== labels.length) {
      toast.error('客户等级名称不能重复');
      return;
    }

    setSavingLevels(true);
    try {
      const nextDictConfig = {
        ...dictConfig,
        levels: serializeDictEntries(normalizedEntries),
      };
      await saveRemoteAppConfig('dict_config', nextDictConfig);
      const firstLevelKey = Object.keys(normalizedEntries)[0] || '';
      if (!normalizedEntries[form.level]) {
        setForm(prev => ({ ...prev, level: firstLevelKey }));
      }
      setShowLevelManager(false);
      setNewLevelName('');
      toast.success('客户等级已更新');
    } catch (err: any) {
      toast.error(getErrorDetail(err, '保存客户等级失败'));
    } finally {
      setSavingLevels(false);
    }
  };

  const openPackageManager = () => {
    setPackageDrafts(Object.entries(customerPackageLabels).map(([key, label]) => ({
      key,
      label,
      platforms: [],
    })));
    setNewPackageName('');
    setShowPackageManager(true);
  };

  const savePackageDrafts = async (draftsToSave: PackageDraft[]) => {
    const normalizedEntries = draftsToSave.reduce<Record<string, string>>((acc, item) => {
      const label = normalizePackageLabel(item.label);
      if (label) {
        acc[item.key] = label;
      }
      return acc;
    }, {});

    const labels = Object.values(normalizedEntries);
    if (labels.length === 0) {
      throw new Error('请至少保留一个客户意向套餐');
    }
    if (new Set(labels.map(label => label.toLowerCase())).size !== labels.length) {
      throw new Error('套餐名称不能重复');
    }
    const nextDictConfig = {
      ...dictConfig,
      customerPackages: serializeDictEntries(normalizedEntries),
      customerPackagePlatforms: dictConfig.customerPackagePlatforms,
    };
    await saveRemoteAppConfig('dict_config', nextDictConfig);
    const savedDrafts = Object.entries(normalizedEntries).map(([key, label]) => ({ key, label, platforms: [] }));
    setPackageDrafts(savedDrafts);
    return savedDrafts;
  };

  const handleAddPackageDraft = async () => {
    if (savingPackages) return;
    const pendingLabel = newPackageName.trim();
    if (!pendingLabel) { toast.error('请输入套餐名称'); return; }

    const result = appendPackageDrafts(packageDrafts, pendingLabel);
    if (result.addedCount === 0) {
      toast.error(result.duplicates.length > 0 ? `套餐已存在：${result.duplicates.join('、')}` : '请输入套餐名称');
      return;
    }

    setSavingPackages(true);
    try {
      await savePackageDrafts(result.drafts);
      setNewPackageName('');
      toast.success(
        result.duplicates.length > 0
          ? `已添加 ${result.addedCount} 个套餐，已跳过重复：${result.duplicates.join('、')}`
          : `已添加 ${result.addedCount} 个套餐`
      );
    } catch (err: any) {
      toast.error(getErrorDetail(err, '添加客户意向套餐失败'));
    } finally {
      setSavingPackages(false);
    }
  };

  const handleRemovePackageDraft = (key: string) => {
    if (packageDrafts.length <= 1) {
      toast.error('至少保留一个客户意向套餐');
      return;
    }
    const remaining = packageDrafts.filter(item => item.key !== key);
    setPackageDrafts(remaining);
    if (customers.some(customer => parseMultiValue(customer.interested_packages).includes(key)) || form.interested_packages.includes(key)) {
      toast('该套餐会从新客户可选项中停用，已保存客户会继续按历史快照显示');
    }
  };

  const handleSavePackages = async () => {
    if (savingPackages) return;
    const pendingLabel = newPackageName.trim();
    const result = pendingLabel
      ? appendPackageDrafts(packageDrafts, pendingLabel)
      : { drafts: packageDrafts, addedCount: 0, duplicates: [] as string[] };

    if (pendingLabel && result.addedCount === 0) {
      toast.error(result.duplicates.length > 0 ? `套餐已存在：${result.duplicates.join('、')}` : '请输入套餐名称');
      return;
    }

    setSavingPackages(true);
    try {
      await savePackageDrafts(result.drafts);
      setShowPackageManager(false);
      setNewPackageName('');
      toast.success(
        result.duplicates.length > 0
          ? `客户意向套餐已更新，已跳过重复：${result.duplicates.join('、')}`
          : '客户意向套餐已更新'
      );
    } catch (err: any) {
      toast.error(getErrorDetail(err, '保存客户意向套餐失败'));
    } finally {
      setSavingPackages(false);
    }
  };

  const toggleInterestedPackage = (key: string, checked: boolean) => {
    setForm(prev => ({
      ...prev,
      interested_packages: checked
        ? Array.from(new Set([...prev.interested_packages, key]))
        : prev.interested_packages.filter(item => item !== key),
      interested_packages_snapshot: checked
        ? {
            ...prev.interested_packages_snapshot,
            [key]: prev.interested_packages_snapshot[key] || customerPackageLabels[key] || key,
          }
        : Object.fromEntries(Object.entries(prev.interested_packages_snapshot).filter(([itemKey]) => itemKey !== key)),
    }));
  };

  const toggleSelectedPlatform = (key: string, checked: boolean) => {
    setForm(prev => ({
      ...prev,
      selected_platforms: checked
        ? Array.from(new Set([...(prev.selected_platforms || []), key]))
        : (prev.selected_platforms || []).filter(item => item !== key),
    }));
  };

  // Employees list for sales person dropdown
  const [employeesList, setEmployeesList] = useState<any[]>([]);
  // Assign dialog state
  const [showAssignDialog, setShowAssignDialog] = useState(false);
  const [assignTarget, setAssignTarget] = useState<any>(null);
  const [assignEmployeeId, setAssignEmployeeId] = useState('');
  const [assigning, setAssigning] = useState(false);
  const [showAccessDialog, setShowAccessDialog] = useState(false);
  const [accessTarget, setAccessTarget] = useState<any>(null);
  const [accessMembers, setAccessMembers] = useState<Record<number, CustomerAccessLevel>>({});
  const [selectedCustomerIds, setSelectedCustomerIds] = useState<number[]>([]);
  const [focusedCustomerId, setFocusedCustomerId] = useState<number | null>(null);
  const [bulkAccessMode, setBulkAccessMode] = useState(false);
  const [accessSearch, setAccessSearch] = useState('');
  const [accessLoading, setAccessLoading] = useState(false);
  const [accessSaving, setAccessSaving] = useState(false);
  const [inlineSavingKey, setInlineSavingKey] = useState('');
  const [cityDrafts, setCityDrafts] = useState<Record<number, string>>({});
  const salesPersonOptions = useMemo(() => {
    const names = new Set<string>();
    customers.forEach(customer => {
      const name = customer.sales_person?.trim();
      if (name) names.add(name);
    });
    employeesList.forEach(emp => {
      const name = emp.name?.trim();
      if (name) names.add(name);
    });
    return Array.from(names).sort((a, b) => a.localeCompare(b, 'zh-CN')).map(name => ({ value: name, label: name }));
  }, [customers, employeesList]);

  // Advanced filter cascading state
  const advStates = advFilters.country ? getStatesForCountry(advFilters.country) : [];
  const advCities = advFilters.country && advFilters.state ? getCitiesForState(advFilters.country, advFilters.state) : [];
  const activeReminder = searchParams.get('reminder') || '';
  const activeReminderMessage = customerReminderMessages[activeReminder];
  const detailFromFinance = searchParams.get('from') === 'finance';
  const detailReturnTo = getSafeInternalPath(searchParams.get('returnTo'));
  const normalizeCustomerDetailTab = (tab?: string | null) => {
    if (tab === 'payments' && !canViewFinance) return 'overview';
    return tab && customerDetailTabValues.has(tab) ? tab : 'overview';
  };

  const clearCustomerDetailAssociations = () => {
    setFollowUps([]);
    setDeals([]);
    setPayments([]);
    setCustomerExpenses([]);
    setCustomerDeductionRates({});
    setSubscriptions([]);
    setCustomerProjects([]);
    setServiceProgresses([]);
    setServiceTasks([]);
    setContacts([]);
    setLifecycleDetail(null);
    setProductCatalog({ business_lines: [], products: [], plans: [] });
    setDetailLoadError(null);
    setDetailLoading(false);
    setDetailLoadedAt(null);
    setShowFollowForm(false);
    setEditingFollowId(null);
    setDeleteFollowTarget(null);
    setShowContactForm(false);
    setEditingContactId(null);
    setDeleteContactTarget(null);
  };

  const invalidateCustomerDetailRequests = () => {
    detailRequestSeqRef.current += 1;
    activeDetailCustomerIdRef.current = null;
  };

  useEffect(() => {
    const sp = searchParams.get('status');
    if (sp && statusLabels[sp]) setFilterStatus(sp);
    // Handle deep link from Sales page
    const detailId = searchParams.get('detail');
    const nextTab = normalizeCustomerDetailTab(searchParams.get('tab'));
    if (detailId && customers.length > 0) {
      const target = customers.find(c => c.id === Number(detailId));
      if (target) {
        setSelectedCustomerTab(nextTab);
        if (selectedCustomer?.id !== target.id) {
          openDetail(target, nextTab);
        }
      }
    }
  }, [searchParams, customers, selectedCustomer?.id, statusLabels, canViewFinance]);

  const toggleCol = (key: string) => {
    const nc = visibleCols.includes(key) ? visibleCols.filter(c => c !== key) : [...visibleCols, key];
    setVisibleCols(nc);
    localStorage.setItem(COLS_KEY, JSON.stringify(nc));
  };

  const reloadFollowUps = async (cid: number) => {
    const r = await client.entities.follow_ups.query({ query: { customer_id: cid }, sort: '-created_at', limit: 1000 });
    const items = r?.data?.items || [];
    if (activeDetailCustomerIdRef.current === cid) setFollowUps(items);
    return items;
  };

  const reloadContacts = async (cid: number) => {
    try {
      const r = await client.entities.customer_contacts.queryAll({ query: { customer_id: cid }, sort: '-created_at', limit: 50 });
      if (activeDetailCustomerIdRef.current === cid) setContacts(r?.data?.items || []);
    } catch (err) {
      console.error('Load contacts error:', err);
      if (activeDetailCustomerIdRef.current === cid) setContacts([]);
    }
  };

  const fetchCustomerDeductionRates = async (paymentItems: any[]) => {
    if (!canViewFinance) return {} as Record<string, number>;
    const months = Array.from(new Set(
      paymentItems
        .map(item => getPaymentYearMonth(item))
        .filter(Boolean)
    )).sort();
    if (months.length === 0) return {} as Record<string, number>;
    try {
      const res = isMobile
        ? await invokeWithAuth({
          url: '/api/v1/deductions-monthly',
          method: 'GET',
          data: { start: months[0], end: months[months.length - 1] },
        })
        : await invokeWithAuth({
          url: '/api/v1/deductions-monthly/ensure',
          method: 'POST',
          data: { months },
        });
      const rates: Record<string, number> = {};
      const requestedMonths = new Set(months);
      (res.data || []).forEach((row: any) => {
        if (row?.year_month && requestedMonths.has(row.year_month) && typeof row.rate === 'number') {
          rates[row.year_month] = row.rate;
        }
      });
      return rates;
    } catch (err) {
      console.warn('Load customer deduction rates failed:', err);
      return {} as Record<string, number>;
    }
  };

  const loadCustomerDetail = async (customerId: number, fallbackCustomer?: any) => {
    const requestSeq = ++detailRequestSeqRef.current;
    activeDetailCustomerIdRef.current = customerId;
    const isCurrentRequest = () => (
      detailRequestSeqRef.current === requestSeq
      && activeDetailCustomerIdRef.current === customerId
    );
    setDetailLoading(true);
    setDetailLoadError(null);
    try {
      const settledResults = await Promise.allSettled([
        client.entities.customers.query({ query: { id: customerId }, limit: 1 }),
        client.entities.follow_ups.query({ query: { customer_id: customerId }, sort: '-created_at', limit: 1000 }),
        client.entities.deals.query({ query: { customer_id: customerId }, sort: '-deal_date', limit: 1000 }),
        canViewFinance
          ? client.entities.payments.queryAll({ query: { customer_id: customerId }, sort: '-payment_date', limit: 1000 })
          : Promise.resolve({ data: { items: [] } }),
        canViewFinance
          ? client.entities.expenses.queryAll({ query: { customer_id: customerId }, sort: '-expense_date', limit: 1000 })
          : Promise.resolve({ data: { items: [] } }),
        client.entities.subscriptions.query({ query: { customer_id: customerId }, sort: '-created_at', limit: 1000 }),
        client.entities.service_progresses.queryAll({ query: { customer_id: customerId }, sort: '-last_update_time', limit: 1000 }),
        client.entities.service_tasks.queryAll({ query: { customer_id: customerId }, sort: '-created_at', limit: 1000 }),
        canViewFinance
          ? invokeWithAuth({ url: `/api/v1/customer-lifecycle/customers/${customerId}`, method: 'GET' })
          : Promise.resolve({ data: null }),
        invokeWithAuth({ url: `/api/v1/entities/customers/${customerId}/projects`, method: 'GET' }),
        role === 'sales' || role === 'sales_manager'
          ? Promise.resolve({ data: { business_lines: [], products: [], plans: [] } })
          : invokeWithAuth({ url: '/api/v1/product-plans', method: 'GET' }).catch(() => ({ data: { business_lines: [], products: [], plans: [] } })),
        client.entities.customer_contacts.queryAll({ query: { customer_id: customerId }, sort: '-created_at', limit: 50 })
          .catch(() => ({ data: { items: [] } })),
      ]);

      if (!isCurrentRequest()) return;
      const readSettled = (result: PromiseSettledResult<any>, fallback: any, label: string) => {
        if (result.status === 'fulfilled') return result.value;
        console.warn(`Load customer detail section failed: ${label}`, result.reason);
        return fallback;
      };
      const [customerResult, fuResult, dealResult, paymentResult, expenseResult, subscriptionResult, progressResult, taskResult, lifecycleResult, projectResult, catalogResult, contactResult] = settledResults;
      const emptyItems = { data: { items: [] } };
      const customerRes = readSettled(customerResult, emptyItems, 'customer');
      const fuRes = readSettled(fuResult, emptyItems, 'follow_ups');
      const dRes = readSettled(dealResult, emptyItems, 'deals');
      const pRes = readSettled(paymentResult, emptyItems, 'payments');
      const expenseRes = readSettled(expenseResult, emptyItems, 'expenses');
      const sRes = readSettled(subscriptionResult, emptyItems, 'subscriptions');
      const progressRes = readSettled(progressResult, emptyItems, 'service_progresses');
      const taskRes = readSettled(taskResult, emptyItems, 'service_tasks');
      const lifecycleRes = readSettled(lifecycleResult, { data: null }, 'lifecycle');
      const projectRes = readSettled(projectResult, emptyItems, 'projects');
      const catalogRes = readSettled(catalogResult, { data: { business_lines: [], products: [], plans: [] } }, 'catalog');
      const contactRes = readSettled(contactResult, emptyItems, 'contacts');
      const latestCustomer = customerRes?.data?.items?.[0] || fallbackCustomer || null;
      if (!latestCustomer && customerResult.status === 'rejected') {
        setDetailLoadError(getLoadErrorMessage(customerResult.reason));
      }
      const paymentItems = pRes?.data?.items || [];
      const deductionRates = await fetchCustomerDeductionRates(paymentItems);
      if (!isCurrentRequest()) return;

      if (latestCustomer) {
        setSelectedCustomer(latestCustomer);
        setCustomers(prev => prev.map(item => (item.id === latestCustomer.id ? { ...item, ...latestCustomer } : item)));
      }
      setFollowUps(fuRes?.data?.items || []);
      setDeals(dRes?.data?.items || []);
      setPayments(paymentItems);
      setCustomerExpenses(expenseRes?.data?.items || []);
      setCustomerDeductionRates(deductionRates);
      setSubscriptions(decorateEffectiveSubscriptions(sRes?.data?.items || []));
      setServiceProgresses(progressRes?.data?.items || []);
      setServiceTasks(taskRes?.data?.items || []);
      setLifecycleDetail(lifecycleRes?.data || null);
      setCustomerProjects(projectRes?.data?.items || []);
      setProductCatalog(catalogRes?.data || { business_lines: [], products: [], plans: [] });
      setContacts(contactRes?.data?.items || []);
      setDetailLoadedAt(new Date().toISOString());
    } catch (err) {
      console.error(err);
      if (isCurrentRequest()) setDetailLoadError(getLoadErrorMessage(err));
    } finally {
      if (isCurrentRequest()) setDetailLoading(false);
    }
  };

  const openEditFollow = (f: any) => {
    if (!canEditFollowUp) return;
    setFollowForm({ contact_method: f.contact_method || 'phone', content: f.content || '', customer_needs: f.customer_needs || '', customer_pain_points: f.customer_pain_points || '', has_quoted: f.has_quoted || false, quote_plan: f.quote_plan || '', close_probability: f.close_probability ?? 30, stage: f.stage || 'communicating', next_follow_date: f.next_follow_date ? f.next_follow_date.slice(0, 10) : '' });
    setEditingFollowId(f.id);
    setShowFollowForm(true);
  };

  const handleSaveFollow = async () => {
    if (editingFollowId ? !canEditFollowUp : !canCreateFollowUp) {
      toast.error('当前账号没有保存跟进记录的权限');
      return;
    }
    if (!followForm.content.trim()) { toast.error('请填写跟进内容'); return; }
    if (!selectedCustomer) return;
    setSavingFollow(true);
    try {
      const now = new Date().toISOString();
      const op = employee?.name || '管理员';
      if (editingFollowId) {
        await client.entities.follow_ups.update({ id: String(editingFollowId), data: { contact_method: followForm.contact_method, content: followForm.content, customer_needs: followForm.customer_needs, customer_pain_points: followForm.customer_pain_points, has_quoted: followForm.has_quoted, quote_plan: followForm.quote_plan, close_probability: followForm.close_probability, stage: followForm.stage, next_follow_date: followForm.next_follow_date || null, updated_at: now } });
        toast.success('跟进记录已更新');
        logOperation({ customerId: selectedCustomer.id, actionType: 'edit_follow_up', actionDetail: '编辑跟进记录', operatorName: op });
      } else {
        await client.entities.follow_ups.create({ data: { customer_id: selectedCustomer.id, contact_method: followForm.contact_method, content: followForm.content, customer_needs: followForm.customer_needs, customer_pain_points: followForm.customer_pain_points, has_quoted: followForm.has_quoted, quote_plan: followForm.quote_plan, close_probability: followForm.close_probability, stage: followForm.stage, next_follow_date: followForm.next_follow_date || null, employee_name: employee?.name || '', created_at: now } });
        toast.success('跟进记录已添加');
        logOperation({ customerId: selectedCustomer.id, actionType: 'create_follow_up', actionDetail: '新增跟进记录', operatorName: op });
      }
      setShowFollowForm(false); setEditingFollowId(null); setFollowForm(emptyFollowForm);
      const nextFollowUps = await reloadFollowUps(selectedCustomer.id);
      const followReminderType = searchParams.get('reminder') || '';
      if (['follow_up_today', 'follow_up_overdue', 'no_follow_7d'].includes(followReminderType)) {
        const nextParams = new URLSearchParams(searchParams);
        let shouldClearReminder = followReminderType === 'no_follow_7d';

        if (!shouldClearReminder) {
          const latestFollowUp = nextFollowUps[0];
          const latestNextDate = latestFollowUp?.next_follow_date?.slice(0, 10) || '';
          const todayStr = businessToday;
          if (followReminderType === 'follow_up_today') {
            shouldClearReminder = latestNextDate !== todayStr;
          } else if (followReminderType === 'follow_up_overdue') {
            shouldClearReminder = !latestNextDate || latestNextDate >= todayStr;
          }
        }

        if (shouldClearReminder) {
          nextParams.delete('reminder');
          setSearchParams(nextParams);
        }
      }
    } catch { toast.error('保存失败'); } finally { setSavingFollow(false); }
  };

  const handleDeleteFollow = async () => {
    if (!deleteFollowTarget || !selectedCustomer || !canDeleteFollowUp) return;
    setDeletingFollow(true);
    try {
      await client.entities.follow_ups.delete({ id: String(deleteFollowTarget.id) });
      toast.success('跟进记录已删除');
      logOperation({ customerId: selectedCustomer.id, actionType: 'delete_follow_up', actionDetail: '删除跟进记录', operatorName: employee?.name || '管理员' });
      setDeleteFollowTarget(null);
      await reloadFollowUps(selectedCustomer.id);
    } catch { toast.error('删除失败'); } finally { setDeletingFollow(false); }
  };

  // Contact CRUD
  const handleSaveContact = async () => {
    if (!canManageContacts) {
      toast.error('当前账号没有修改联系人的权限');
      return;
    }
    if (!contactForm.contact_name.trim()) { toast.error('请填写联系人姓名'); return; }
    if (!selectedCustomer) return;
    setSavingContact(true);
    try {
      if (editingContactId) {
        await client.entities.customer_contacts.update({ id: String(editingContactId), data: { contact_name: contactForm.contact_name, contact_phone: contactForm.contact_phone, contact_role: contactForm.contact_role, notes: contactForm.notes } });
        toast.success('联系人已更新');
      } else {
        await client.entities.customer_contacts.create({ data: { customer_id: selectedCustomer.id, contact_name: contactForm.contact_name, contact_phone: contactForm.contact_phone, contact_role: contactForm.contact_role, notes: contactForm.notes, created_at: new Date().toISOString() } });
        toast.success('联系人已添加');
      }
      setShowContactForm(false); setEditingContactId(null); setContactForm(emptyContactForm);
      await reloadContacts(selectedCustomer.id);
    } catch (err) { console.error(err); toast.error('保存失败'); } finally { setSavingContact(false); }
  };

  const handleDeleteContact = async () => {
    if (!deleteContactTarget || !selectedCustomer || !canDeleteContacts) return;
    setDeletingContact(true);
    try {
      await client.entities.customer_contacts.delete({ id: String(deleteContactTarget.id) });
      toast.success('联系人已删除');
      setDeleteContactTarget(null);
      await reloadContacts(selectedCustomer.id);
    } catch { toast.error('删除失败'); } finally { setDeletingContact(false); }
  };

  useEffect(() => { if (showForm) setCodeSettings(loadSettings()); }, [showForm]);

  useEffect(() => {
    if (!showForm || editingId) return;
    invokeWithAuth({ url: '/api/v1/commissions/assignment-options', method: 'GET' })
      .then(response => setCommissionPartners(response?.data?.items || []))
      .catch(() => setCommissionPartners([]));
  }, [showForm, editingId]);

  const loadEmployees = async () => {
    try {
      const res = await invokeWithAuth({
        url: '/api/v1/entities/employees/directory',
        method: 'GET',
        data: { query: JSON.stringify({ status: 'active' }), limit: 100 },
      });
      setEmployeesList(res?.data?.items || []);
    } catch (err) { console.error('Load employees error:', err); }
  };

  const loadCustomers = async () => {
    try {
      const res = await loadWithRetry(
        () => client.entities.customers.query({ limit: 1000, sort: '-created_at' }),
      );
      let items = res?.data?.items || [];
      if (dataScope === 'self' && employee) items = items.filter((c: any) => c.sales_person === employee.name || c.sales_employee_id === employee.id);
      setCustomers(items);
      setLoadError(null);
      setCustomersLoadedAt(new Date().toISOString());
    } catch (err) {
      console.error(err);
      setLoadError(getLoadErrorMessage(err));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    setLoading(true);
    void loadCustomers();
    void loadEmployees();
  }, [dataScope, employee?.id, employee?.name]);

  useAutoRefresh(async () => {
    await loadCustomers();
    await loadEmployees();
    const detailCustomerId = activeDetailCustomerIdRef.current;
    if (detailCustomerId) {
      const fallbackCustomer = selectedCustomer?.id === detailCustomerId ? selectedCustomer : undefined;
      await loadCustomerDetail(detailCustomerId, fallbackCustomer);
    }
  }, {
    intervalMs: 30000,
    enabled: !showForm && !showFollowForm && !showContactForm,
  });

  const reconcileSelectedCustomerClosure = async () => {
    if (!selectedCustomer?.id) return;
    setClosureSyncing(true);
    try {
      const response = await invokeWithAuth({
        url: `/api/v1/customer-lifecycle/customers/${selectedCustomer.id}/reconcile-closure`,
        method: 'POST',
      });
      const summary = response?.data?.closure_summary || {};
      toast.success(`状态闭环完成：停止项目 ${summary.stopped_projects || 0} 个，关闭续费 ${summary.stopped_subscriptions || 0} 条`);
      await loadCustomerDetail(selectedCustomer.id, selectedCustomer);
    } catch (error: any) {
      toast.error(getErrorDetail(error, '状态闭环失败'));
    } finally {
      setClosureSyncing(false);
    }
  };

  const checkDuplicate = (name: string, phone: string) => {
    if (!name && !phone) { setDuplicateWarning(null); return; }
    const dupes = customers.filter(c => {
      if (editingId && c.id === editingId) return false;
      return (name && c.business_name?.toLowerCase() === name.toLowerCase()) || (phone && c.phone === phone);
    });
    setDuplicateWarning(dupes.length > 0 ? `检测到可能重复: ${dupes.map((d: any) => d.business_name).join(', ')}` : null);
  };

  const filtered = useMemo(() => {
    return customers.filter(c => {
      let ms = true;
      if (search) {
        const q = search.toLowerCase().trim();
        ms = [c.customer_code, c.business_name, c.contact_name, c.phone, c.city, c.email, c.wechat, c.address, c.sales_person, c.country, c.state].some(f => (f || '').toLowerCase().includes(q));
      }
      const mst = filterStatus === 'all' || c.status === filterStatus;
      const mi = filterIndustry === 'all' || c.industry === filterIndustry;
      const ml = filterLevel === 'all' || c.level === filterLevel;
      const mso = filterSource === 'all' || c.source === filterSource;
      const af = advFilters;
      const ma = (!af.customer_code || (c.customer_code || '').toLowerCase().includes(af.customer_code.toLowerCase()))
        && (!af.business_name || (c.business_name || '').toLowerCase().includes(af.business_name.toLowerCase()))
        && (!af.contact_name || (c.contact_name || '').toLowerCase().includes(af.contact_name.toLowerCase()))
        && (!af.phone || (c.phone || '').includes(af.phone))
        && (!af.city || (c.city || '').toLowerCase().includes(af.city.toLowerCase()))
        && (!af.industry || c.industry === af.industry)
        && (!af.status || c.status === af.status)
        && (!af.level || c.level === af.level)
        && (!af.sales_person || c.sales_person === af.sales_person)
        && (!af.source || c.source === af.source)
        && (!af.wechat || (c.wechat || '').toLowerCase().includes(af.wechat.toLowerCase()))
        && (!af.email || (c.email || '').toLowerCase().includes(af.email.toLowerCase()))
        && (!af.country || c.country === af.country)
        && (!af.state || c.state === af.state);
      return ms && mst && mi && ml && mso && ma;
    });
  }, [customers, search, filterStatus, filterIndustry, filterLevel, filterSource, advFilters]);
  const paginatedCustomers = useMemo(
    () => paginateList(filtered, customerPage, customerPageSize),
    [filtered, customerPage, customerPageSize],
  );
  const customerStatusCounts = useMemo(() => customers.reduce<Record<string, number>>((counts, customer) => {
    const key = customer.status || 'unknown';
    counts[key] = (counts[key] || 0) + 1;
    return counts;
  }, {}), [customers]);
  const newCustomersThisMonth = useMemo(() => {
    const currentMonth = businessToday.slice(0, 7);
    return customers.filter(customer => String(customer.created_at || '').slice(0, 7) === currentMonth).length;
  }, [businessToday, customers]);
  const attentionCustomerCount = (customerStatusCounts.paused || 0) + (customerStatusCounts.lost || 0);
  const focusedCustomer = filtered.find(customer => customer.id === focusedCustomerId)
    || paginatedCustomers.items[0]
    || null;
  const focusedCustomerCompleteness = focusedCustomer ? Math.round(([
    focusedCustomer.business_name,
    focusedCustomer.contact_name,
    focusedCustomer.phone,
    focusedCustomer.email,
    focusedCustomer.address,
    focusedCustomer.city,
    focusedCustomer.state,
    focusedCustomer.country,
    focusedCustomer.industry,
    focusedCustomer.sales_person,
  ].filter(Boolean).length / 10) * 100) : 0;
  const focusedCustomerSuggestion = focusedCustomer?.status === 'lost'
    ? '先核对流失原因与历史服务记录'
    : focusedCustomer?.status === 'paused'
      ? '确认暂停原因和恢复合作条件'
      : focusedCustomer?.status === 'following'
        ? '查看最近跟进并确认下一步安排'
        : '打开客户详情核对服务与续费计划';

  useEffect(() => {
    setCustomerPage(1);
  }, [search, filterStatus, filterIndustry, filterLevel, filterSource, advFilters, customerPageSize]);

  useEffect(() => {
    if (filtered.length === 0) {
      if (focusedCustomerId !== null) setFocusedCustomerId(null);
      return;
    }
    if (!filtered.some(customer => customer.id === focusedCustomerId)) {
      setFocusedCustomerId(filtered[0].id);
    }
  }, [filtered, focusedCustomerId]);

  useEffect(() => {
    setFollowUpPage(1);
    setDealPage(1);
    setServiceInfoPage(1);
    setFinanceMonthlyPage(1);
    setFinancePaymentPage(1);
    setFinanceExpensePage(1);
    setRenewalPage(1);
  }, [selectedCustomer?.id]);

  useEffect(() => {
    setFollowUpPage(1);
    setDealPage(1);
    setServiceInfoPage(1);
    setFinanceMonthlyPage(1);
    setFinancePaymentPage(1);
    setFinanceExpensePage(1);
    setRenewalPage(1);
  }, [
    followUpPageSize,
    dealPageSize,
    serviceInfoPageSize,
    financeMonthlyPageSize,
    financePaymentPageSize,
    financeExpensePageSize,
    renewalPageSize,
  ]);

  const openCreate = () => { setForm({ ...emptyForm, selected_platforms: [], interested_packages: [], interested_packages_snapshot: {} }); setCustomerProjectForms([]); setCommissionPartnerId('auto'); setCommissionEffectiveFrom(businessToday); setManualCityInput(false); setEditingId(null); setDuplicateWarning(null); setShowForm(true); };
  const openEdit = async (c: any) => {
    const interestedPackages = parseMultiValue(c.interested_packages);
    const snapshot = parsePackageSnapshot(c.interested_packages_snapshot);
    interestedPackages.forEach(key => {
      if (!snapshot[key]) snapshot[key] = customerPackageLabels[key] || key;
    });
    setForm({ customer_code: c.customer_code || '', business_name: c.business_name || '', contact_name: c.contact_name || '', phone: c.phone || '', wechat: c.wechat || '', email: c.email || '', address: c.address || '', city: c.city || '', state: c.state || 'CA', country: c.country || 'US', industry: c.industry || 'restaurant', website: c.website || '', google_business_link: c.google_business_link || '', facebook_link: c.facebook_link || '', instagram_link: c.instagram_link || '', yelp_link: c.yelp_link || '', tiktok_link: c.tiktok_link || '', has_ordering_system: c.has_ordering_system || false, current_platform: c.current_platform || '无', selected_platforms: parseMultiValue(c.selected_platforms), interested_packages: interestedPackages, interested_packages_snapshot: snapshot, monthly_orders: c.monthly_orders || 0, source: c.source || 'phone', sales_person: c.sales_person || '', sales_employee_id: c.sales_employee_id || '', level: c.level || 'normal', status: c.status || 'new', notes: c.notes || '' });
    setManualCityInput(false);
    setEditingId(c.id); setDuplicateWarning(null); setShowForm(true);
    setCustomerProjectsLoading(true);
    try {
      const response = await invokeWithAuth({ url: `/api/v1/entities/customers/${c.id}/projects`, method: 'GET' });
      setCustomerProjectForms((response?.data?.items || []).map((row: any) => ({
        engagement_id: row.id,
        business_line_code: row.business_line_code,
        product_code: row.product_code,
        product_name: row.product_name,
        package_name: row.package_name || row.product_name,
        status: row.status || 'pending_setup',
        billing_cycle: row.billing_cycle || '',
        collection_method: row.collection_method || 'other',
        currency: row.currency || 'USD',
        owner_employee_id: row.owner_employee_id ? String(row.owner_employee_id) : '',
        paid_started_at: row.paid_started_at ? row.paid_started_at.slice(0, 10) : '',
        stopped_at: row.stopped_at ? row.stopped_at.slice(0, 10) : '',
        stop_reason_code: row.stop_reason_code || '',
        stop_note: row.stop_note || '',
      })));
    } catch (error: any) {
      toast.error(getErrorDetail(error, '合作项目加载失败'));
      setCustomerProjectForms([]);
    } finally {
      setCustomerProjectsLoading(false);
    }
  };

  const addCustomerProject = () => {
    const nextLine = Object.keys(customerProjectLines).find(code => !customerProjectForms.some(row => row.business_line_code === code));
    if (!nextLine) { toast.error('四类业务项目都已经添加'); return; }
    setCustomerProjectForms(rows => [...rows, newCustomerProject(nextLine)]);
  };

  const updateCustomerProject = (index: number, patch: Partial<CustomerProjectDraft>) => {
    setCustomerProjectForms(rows => rows.map((row, rowIndex) => {
      if (rowIndex !== index) return row;
      const next = { ...row, ...patch };
      if (patch.business_line_code) {
        const line = customerProjectLines[patch.business_line_code];
        next.product_code = line.productCode;
        next.product_name = line.productName;
        if (!next.package_name || next.package_name === row.product_name) next.package_name = line.productName;
        if (patch.business_line_code === 'one_time_project') next.billing_cycle = 'one_time';
      }
      return next;
    }));
  };

  const getNextAutoCode = (industry?: string) => {
    const ind = industry || form.industry || 'restaurant';
    return generateNextCode(codeSettings, ind, customers.map(c => c.customer_code).filter(Boolean));
  };

  const handleSave = async () => {
    if (!form.business_name || !form.contact_name || !form.phone) { toast.error('请填写必填字段'); return; }
    if (new Set(customerProjectForms.map(row => row.business_line_code)).size !== customerProjectForms.length) { toast.error('同一业务项目只能添加一次'); return; }
    if (customerProjectForms.some(row => !row.package_name.trim())) { toast.error('请填写每个合作项目的套餐或项目名称'); return; }
    if (customerProjectForms.some(row => ['active_paid', 'reactivated'].includes(row.status) && !row.paid_started_at)) { toast.error('付费合作中的项目必须填写第一笔有效收款日期'); return; }
    if (customerProjectForms.some(row => ['stopped', 'completed'].includes(row.status) && !row.stopped_at)) { toast.error('已停止或已完成项目必须填写结束日期'); return; }
    if (form.status === 'lost' && customerProjectForms.some(row => activeCustomerProjectStatuses.has(row.status))) { toast.error('客户标记流失前，请先停止所有合作项目；成交和收款历史无需删除'); return; }
    setSaving(true);
    try {
      const now = new Date().toISOString();
      const op = employee?.name || '管理员';
      const selectedPackageSnapshot = form.interested_packages.reduce<Record<string, string>>((acc, key) => {
        acc[key] = getPackageLabelForSnapshot(key, form.interested_packages_snapshot);
        return acc;
      }, {});
      const payload = {
        ...form,
        selected_platforms: form.selected_platforms.join(','),
        interested_packages: form.interested_packages.join(','),
        interested_packages_snapshot: serializePackageSnapshot(selectedPackageSnapshot),
        sales_employee_id: form.sales_employee_id === '' ? null : Number(form.sales_employee_id),
        monthly_orders: String(form.monthly_orders ?? '').trim() === '' ? null : Number(form.monthly_orders || 0),
      };
      const projects = customerProjectForms.map(row => ({
        ...row,
        owner_employee_id: row.owner_employee_id ? Number(row.owner_employee_id) : null,
        sales_employee_id: form.sales_employee_id === '' ? null : Number(form.sales_employee_id),
        paid_started_at: row.paid_started_at ? `${row.paid_started_at}T00:00:00Z` : null,
        stopped_at: row.stopped_at ? `${row.stopped_at}T00:00:00Z` : null,
        stop_reason_code: row.stop_reason_code || null,
        stop_note: row.stop_note || null,
        source_payment_ids: [],
        source_subscription_ids: [],
      }));
      if (editingId) {
        const updatedRes = await invokeWithAuth({ url: `/api/v1/entities/customers/${editingId}/with-projects`, method: 'PUT', data: { customer: { ...payload, updated_at: now }, projects } });
        const updatedCustomer = updatedRes?.data || { ...payload, id: editingId, updated_at: now };
        setCustomers(prev => prev.map(item => (item.id === editingId ? { ...item, ...updatedCustomer } : item)));
        toast.success('客户信息已更新');
        logOperation({ customerId: editingId, actionType: 'edit_customer', actionDetail: `编辑客户: ${form.business_name}`, operatorName: op });
      } else {
        const code = form.customer_code.trim() || getNextAutoCode(form.industry);
        if (customers.some(c => c.customer_code === code)) { toast.error(`编号「${code}」已存在`); setSaving(false); return; }
        const res = await invokeWithAuth({ url: '/api/v1/entities/customers/with-projects', method: 'POST', data: {
          customer: { ...payload, customer_code: code, created_at: now, updated_at: now },
          projects,
          commission_partner_id: commissionPartnerId === 'auto' ? null : Number(commissionPartnerId),
          commission_effective_from: commissionEffectiveFrom || now.slice(0, 10),
        } });
        if (res?.data) {
          setCustomers(prev => [res.data, ...prev]);
        }
        toast.success('客户创建成功');
        logOperation({ customerId: res?.data?.id, actionType: 'create_customer', actionDetail: `新增客户: ${form.business_name}`, operatorName: op });
      }
      setShowForm(false);
      await loadCustomers();
      if (editingId && selectedCustomer?.id === editingId) {
        await loadCustomerDetail(editingId, { ...selectedCustomer, ...payload, updated_at: now });
      }
    } catch (err: any) { toast.error(getErrorDetail(err, '保存失败')); } finally { setSaving(false); }
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await client.entities.customers.delete({ id: String(deleteTarget.id) });
      toast.success('客户已删除');
      setDeleteTarget(null);
      if (selectedCustomer?.id === deleteTarget.id) {
        invalidateCustomerDetailRequests();
        clearCustomerDetailAssociations();
        setSelectedCustomer(null);
      }
      loadCustomers();
    } catch { toast.error('删除失败'); } finally { setDeleting(false); }
  };

  const openAssign = (c: any) => {
    setAssignTarget(c);
    setAssignEmployeeId(c.sales_employee_id ? String(c.sales_employee_id) : '');
    setShowAssignDialog(true);
  };

  const eligibleAccessEmployees = useMemo(() => {
    const keyword = accessSearch.trim().toLowerCase();
    return employeesList
      .filter(emp => ['sales', 'sales_manager', 'ops', 'operations', 'design'].includes(emp.role))
      .filter(emp => !keyword || [emp.name, emp.employee_code, emp.department, emp.role].some(value => String(value || '').toLowerCase().includes(keyword)));
  }, [employeesList, accessSearch]);

  const openAccessManager = async (c: any) => {
    setAccessTarget(c);
    setBulkAccessMode(false);
    setAccessSearch('');
    setAccessMembers({});
    setShowAccessDialog(true);
    setAccessLoading(true);
    try {
      const employeePromise = employeesList.length > 0
        ? Promise.resolve(null)
        : invokeWithAuth({
          url: '/api/v1/entities/employees/directory',
          method: 'GET',
          data: { query: JSON.stringify({ status: 'active' }), limit: 200 },
        });
      const [response, employeeResponse] = await Promise.all([
        invokeWithAuth({ url: `/api/v1/entities/customers/${c.id}/access`, method: 'GET' }),
        employeePromise,
      ]);
      const directoryEmployees = employeeResponse?.data?.items || employeesList;
      if (employeeResponse) setEmployeesList(directoryEmployees);
      const loadedMembers = Object.fromEntries((response?.data?.members || []).map((item: any) => [
        Number(item.employee_id),
        item.access_level === 'read_only' ? 'read_only' : 'read_write',
      ])) as Record<number, CustomerAccessLevel>;
      const ownerEmployeeId = Number(c.sales_employee_id || directoryEmployees.find((item: any) => item.name === c.sales_person)?.id || 0);
      if (ownerEmployeeId) loadedMembers[ownerEmployeeId] = 'read_write';
      setAccessMembers(loadedMembers);
    } catch (error: any) {
      toast.error(getErrorDetail(error, '客户可见人员加载失败'));
      setShowAccessDialog(false);
    } finally {
      setAccessLoading(false);
    }
  };

  const openBulkAccessManager = async () => {
    if (!selectedCustomerIds.length) return;
    setAccessTarget(null);
    setBulkAccessMode(true);
    setAccessSearch('');
    setAccessMembers({});
    setShowAccessDialog(true);
    if (employeesList.length > 0) return;
    setAccessLoading(true);
    try {
      const response = await invokeWithAuth({
        url: '/api/v1/entities/employees/directory',
        method: 'GET',
        data: { query: JSON.stringify({ status: 'active' }), limit: 200 },
      });
      setEmployeesList(response?.data?.items || []);
    } catch (error: any) {
      toast.error(getErrorDetail(error, '团队成员加载失败'));
      setShowAccessDialog(false);
    } finally {
      setAccessLoading(false);
    }
  };

  const toggleAccessEmployee = (employeeId: number) => {
    setAccessMembers(current => {
      if (current[employeeId]) {
        return Object.fromEntries(Object.entries(current).filter(([id]) => Number(id) !== employeeId));
      }
      return { ...current, [employeeId]: 'read_write' };
    });
  };

  const setAccessLevel = (employeeId: number, accessLevel: CustomerAccessLevel) => {
    setAccessMembers(current => ({ ...current, [employeeId]: accessLevel }));
  };

  const selectedAccessMembers = Object.entries(accessMembers).map(([employeeId, accessLevel]) => ({
    employee_id: Number(employeeId),
    access_level: accessLevel,
  }));

  const saveCustomerAccess = async () => {
    if (!accessTarget) return;
    setAccessSaving(true);
    try {
      await invokeWithAuth({
        url: `/api/v1/entities/customers/${accessTarget.id}/access`,
        method: 'PUT',
        data: { members: selectedAccessMembers },
      });
      toast.success(`已更新「${accessTarget.business_name}」的可见人员`);
      logOperation({
        customerId: accessTarget.id,
        actionType: 'other',
        actionDetail: `更新客户团队成员：${selectedAccessMembers.length} 人`,
        operatorName: employee?.name || '管理员',
      });
      setShowAccessDialog(false);
      setAccessTarget(null);
    } catch (error: any) {
      toast.error(getErrorDetail(error, '保存客户可见人员失败'));
    } finally {
      setAccessSaving(false);
    }
  };

  const saveBulkCustomerAccess = async (operation: 'upsert' | 'remove') => {
    if (!selectedCustomerIds.length || !selectedAccessMembers.length) {
      toast.error('请至少选择一位团队成员');
      return;
    }
    setAccessSaving(true);
    try {
      const response = await invokeWithAuth({
        url: '/api/v1/entities/customers/access/bulk-update',
        method: 'POST',
        data: { customer_ids: selectedCustomerIds, operation, members: selectedAccessMembers },
      });
      toast.success(operation === 'remove'
        ? `已从 ${response.data?.customer_count || selectedCustomerIds.length} 位客户移除所选成员`
        : `已为 ${response.data?.customer_count || selectedCustomerIds.length} 位客户更新团队成员`);
      setShowAccessDialog(false);
      setSelectedCustomerIds([]);
      setAccessMembers({});
    } catch (error: any) {
      toast.error(getErrorDetail(error, operation === 'remove' ? '批量移除成员失败' : '批量添加成员失败'));
    } finally {
      setAccessSaving(false);
    }
  };

  const handleAssign = async () => {
    if (!assignTarget || !assignEmployeeId) { toast.error('请选择负责人'); return; }
    setAssigning(true);
    try {
      const emp = employeesList.find(e => e.id === Number(assignEmployeeId));
      if (!emp) { toast.error('员工不存在'); setAssigning(false); return; }
      const now = new Date().toISOString();
      const oldPerson = assignTarget.sales_person || '无';
      await client.entities.customers.update({
        id: String(assignTarget.id),
        data: { sales_person: emp.name, sales_employee_id: emp.id, updated_at: now },
      });
      toast.success(`已将「${assignTarget.business_name}」分配给 ${emp.name}`);
      logOperation({
        customerId: assignTarget.id,
        actionType: 'other',
        actionDetail: `分配负责人: ${oldPerson} → ${emp.name}`,
        operatorName: employee?.name || '管理员',
      });
      setShowAssignDialog(false);
      setAssignTarget(null);
      // Update selected customer if in detail view
      if (selectedCustomer?.id === assignTarget.id) {
        setSelectedCustomer({ ...selectedCustomer, sales_person: emp.name, sales_employee_id: emp.id });
      }
      loadCustomers();
    } catch { toast.error('分配失败'); } finally { setAssigning(false); }
  };

  const syncCustomerState = (customerId: number, updates: Record<string, any>) => {
    setCustomers(prev => prev.map(item => (item.id === customerId ? { ...item, ...updates } : item)));
    setSelectedCustomer(prev => (prev?.id === customerId ? { ...prev, ...updates } : prev));
  };

  const handleInlineCustomerUpdate = async (
    customer: any,
    updates: Record<string, any>,
    successMessage: string,
    actionDetail: string,
  ) => {
    const nextUpdates = Object.fromEntries(
      Object.entries(updates).filter(([key, value]) => (customer[key] ?? '') !== (value ?? '')),
    );
    if (Object.keys(nextUpdates).length === 0) {
      return;
    }

    const savingKey = `${customer.id}:${Object.keys(nextUpdates).join(',')}`;
    setInlineSavingKey(savingKey);
    try {
      await client.entities.customers.update({
        id: String(customer.id),
        data: { ...nextUpdates, updated_at: new Date().toISOString() },
      });
      syncCustomerState(customer.id, nextUpdates);
      toast.success(successMessage);
      logOperation({
        customerId: customer.id,
        actionType: 'edit_customer',
        actionDetail,
        operatorName: employee?.name || '管理员',
      });
    } catch (err) {
      console.error(err);
      toast.error('更新失败');
      throw err;
    } finally {
      setInlineSavingKey(current => (current === savingKey ? '' : current));
    }
  };

  const handleInlineCitySave = async (customer: any) => {
    const nextCity = (cityDrafts[customer.id] ?? customer.city ?? '').trim();
    try {
      await handleInlineCustomerUpdate(
        customer,
        { city: nextCity },
        '城市已更新',
        `快捷更新城市: ${customer.business_name} -> ${nextCity || '未填写'}`,
      );
      setCityDrafts(prev => {
        const next = { ...prev };
        delete next[customer.id];
        return next;
      });
    } catch {
      setCityDrafts(prev => ({ ...prev, [customer.id]: customer.city || '' }));
    }
  };

  const openDetail = async (c: any, nextTab = 'overview') => {
    detailRequestSeqRef.current += 1;
    activeDetailCustomerIdRef.current = c.id;
    setSelectedCustomerTab(normalizeCustomerDetailTab(nextTab));
    clearCustomerDetailAssociations();
    setSelectedCustomer(c);
    await loadCustomerDetail(c.id, c);
  };

  const closeDetail = () => {
    invalidateCustomerDetailRequests();
    clearCustomerDetailAssociations();
    setSelectedCustomer(null);
    setSelectedCustomerTab('overview');
    if (detailReturnTo) {
      navigate(detailReturnTo);
      return;
    }
    if (detailFromFinance) {
      const financeTab = searchParams.get('financeTab');
      navigate(`/finance${financeTab ? `?tab=${encodeURIComponent(financeTab)}` : ''}`);
      return;
    }
    if (searchParams.get('detail') || searchParams.get('tab') || searchParams.get('reminder') || searchParams.get('from') || searchParams.get('financeTab') || searchParams.get('returnTo')) {
      const nextParams = new URLSearchParams(searchParams);
      nextParams.delete('detail');
      nextParams.delete('tab');
      nextParams.delete('reminder');
      nextParams.delete('from');
      nextParams.delete('financeTab');
      nextParams.delete('returnTo');
      setSearchParams(nextParams);
    }
  };

  const handleDetailTabChange = (nextTab: string) => {
    const safeTab = normalizeCustomerDetailTab(nextTab);
    setSelectedCustomerTab(safeTab);
    if (searchParams.get('detail')) {
      const nextParams = new URLSearchParams(searchParams);
      nextParams.set('tab', safeTab);
      setSearchParams(nextParams);
    }
  };

  const countryStates = getStatesForCountry(form.country);
  const formCities = getCitiesForState(form.country, form.state);
  const formCityLabels = new Set(formCities.map(city => city.label));
  const isCustomFormCity = Boolean(form.city && formCities.length > 0 && !formCityLabels.has(form.city));
  const showManualCityField = formCities.length === 0 || manualCityInput || isCustomFormCity;
  const sharedCustomerDialogs = (
    <>
      <ConfirmDialog open={!!deleteTarget} onOpenChange={v => { if (!v) setDeleteTarget(null); }} title="确认删除客户" description={`确定要删除「${deleteTarget?.business_name}」吗？`} onConfirm={handleDelete} loading={deleting} />
      {canDeleteFollowUp && <ConfirmDialog open={!!deleteFollowTarget} onOpenChange={v => { if (!v) setDeleteFollowTarget(null); }} title="确认删除跟进记录" description="确定要删除这条跟进记录吗？" onConfirm={handleDeleteFollow} loading={deletingFollow} />}
      {canDeleteContacts && <ConfirmDialog open={!!deleteContactTarget} onOpenChange={v => { if (!v) setDeleteContactTarget(null); }} title="确认删除联系人" description={`确定要删除联系人「${deleteContactTarget?.contact_name}」吗？`} onConfirm={handleDeleteContact} loading={deletingContact} />}

      <Dialog open={showAssignDialog} onOpenChange={v => { if (!v) { setShowAssignDialog(false); setAssignTarget(null); } }}>
        <DialogContent className="max-w-md">
          <DialogHeader><DialogTitle>设置客户负责人</DialogTitle></DialogHeader>
          {assignTarget && (
            <div className="space-y-4">
              <div className="p-3 bg-slate-50 rounded-lg">
                <p className="text-sm font-medium">{assignTarget.business_name}</p>
                <p className="text-xs text-slate-500 mt-1">当前负责人: {assignTarget.sales_person || '未分配'}</p>
              </div>
              <div>
                <Label>选择新负责人</Label>
                <NativeSelect
                  value={assignEmployeeId}
                  onChange={setAssignEmployeeId}
                  options={[{ value: '', label: '请选择员工' }, ...employeesList.map(e => ({ value: String(e.id), label: `${e.name}${e.department ? ' - ' + e.department : ''}${e.role ? ' (' + e.role + ')' : ''}` }))]}
                />
              </div>
              <div className="flex justify-end gap-2">
                <Button variant="outline" onClick={() => { setShowAssignDialog(false); setAssignTarget(null); }}>取消</Button>
                <Button onClick={handleAssign} disabled={assigning || !assignEmployeeId} className="bg-indigo-600 hover:bg-indigo-700">{assigning ? '分配中...' : '确认分配'}</Button>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>

      <Dialog open={showAccessDialog} onOpenChange={open => { setShowAccessDialog(open); if (!open) { setAccessTarget(null); setBulkAccessMode(false); setAccessMembers({}); } }}>
        <DialogContent className="max-h-[85vh] max-w-xl overflow-y-auto">
          <DialogHeader><DialogTitle>{bulkAccessMode ? `批量管理 ${selectedCustomerIds.length} 位客户的团队成员` : '管理客户团队成员'}</DialogTitle></DialogHeader>
          <div className="space-y-4">
            <div className="rounded-xl border border-blue-200 bg-blue-50 p-3">
              <p className="text-sm font-semibold text-blue-900">{bulkAccessMode ? `已选择 ${selectedCustomerIds.length} 位客户` : accessTarget?.business_name}</p>
              <p className="mt-1 text-xs leading-5 text-blue-700">“只读”可以查看客户与服务资料但不能新增、编辑或删除；“可读写”可以协作维护。客户负责人始终可读写，团队成员权限不会改变负责人、业绩归属或分润。</p>
            </div>
            <div className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-xs leading-5 text-amber-800">
              财务明细始终只对老板、管理员和财务开放。受邀销售或运营仍看不到扣点、手续费、客户成本、利润及收款拆分。
            </div>
            <div className="relative">
              <Search className="absolute left-3 top-2.5 h-4 w-4 text-slate-400" />
              <Input value={accessSearch} onChange={event => setAccessSearch(event.target.value)} className="pl-9" placeholder="搜索员工姓名、编号、部门或角色" />
            </div>
            {accessLoading ? <p className="py-8 text-center text-sm text-slate-400">正在加载人员…</p> : (
              <div className="space-y-2">
                {eligibleAccessEmployees.map(emp => {
                  const selected = Boolean(accessMembers[emp.id]);
                  const isOwner = Number(accessTarget?.sales_employee_id) === Number(emp.id)
                    || (!accessTarget?.sales_employee_id && Boolean(accessTarget?.sales_person) && emp.name === accessTarget.sales_person);
                  return <div key={emp.id} className={`flex flex-col gap-3 rounded-xl border p-3 transition sm:flex-row sm:items-center sm:justify-between ${selected ? 'border-blue-300 bg-blue-50' : 'border-slate-200 bg-white hover:bg-slate-50'}`}>
                    <button type="button" disabled={isOwner} onClick={() => toggleAccessEmployee(emp.id)} className="flex min-w-0 flex-1 items-center gap-3 text-left disabled:cursor-default">
                      <span className={`flex h-5 w-5 shrink-0 items-center justify-center rounded border ${selected ? 'border-blue-600 bg-blue-600 text-white' : 'border-slate-300 bg-white'}`}>{selected ? '✓' : ''}</span>
                      <span className="min-w-0"><span className="block truncate text-sm font-medium text-slate-900">{emp.name}</span><span className="mt-1 block text-xs text-slate-500">{emp.employee_code || '无员工编号'} · {emp.department || emp.role || '未分组'}{isOwner ? ' · 当前负责人' : ''}</span></span>
                    </button>
                    {isOwner ? <Badge className="bg-blue-100 text-blue-700">负责人 · 可读写</Badge> : selected && <NativeSelect className="sm:w-28" value={accessMembers[emp.id]} onChange={value => setAccessLevel(emp.id, value as CustomerAccessLevel)} options={[{ value: 'read_write', label: '可读写' }, { value: 'read_only', label: '只读' }]} />}
                  </div>;
                })}
                {eligibleAccessEmployees.length === 0 && <p className="py-8 text-center text-sm text-slate-400">没有找到可邀请的员工</p>}
              </div>
            )}
            <div className="flex flex-col-reverse gap-2 sm:flex-row sm:items-center sm:justify-between">
              <p className="text-xs text-slate-500">已选择 {selectedAccessMembers.length} 人</p>
              <div className="flex flex-wrap justify-end gap-2"><Button variant="outline" onClick={() => setShowAccessDialog(false)}>取消</Button>{bulkAccessMode ? <><Button variant="outline" className="border-rose-200 text-rose-600 hover:bg-rose-50" onClick={() => void saveBulkCustomerAccess('remove')} disabled={accessLoading || accessSaving || !selectedAccessMembers.length}>批量移除</Button><Button onClick={() => void saveBulkCustomerAccess('upsert')} disabled={accessLoading || accessSaving || !selectedAccessMembers.length}>{accessSaving ? '处理中…' : '批量添加 / 更新'}</Button></> : <Button onClick={() => void saveCustomerAccess()} disabled={accessLoading || accessSaving}>{accessSaving ? '保存中…' : '保存团队成员'}</Button>}</div>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      <Dialog open={showForm} onOpenChange={setShowForm}>
        <DialogContent className="max-h-[calc(100dvh-1rem)] w-[calc(100vw-1rem)] max-w-4xl overflow-y-auto sm:max-h-[90vh]">
          <DialogHeader className="sticky top-0 z-20 -mx-6 -mt-6 border-b border-slate-200 bg-white px-6 py-4 sm:static sm:m-0 sm:border-0 sm:bg-transparent sm:p-0"><DialogTitle>{editingId ? '编辑客户' : '新增客户'}</DialogTitle></DialogHeader>
          {duplicateWarning && <div className="flex items-center gap-2 p-3 bg-amber-50 border border-amber-200 rounded-lg text-sm text-amber-700"><AlertCircle className="w-4 h-4 flex-shrink-0" />{duplicateWarning}</div>}
          <div data-testid="customer-form-grid" className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 sm:col-span-2">
              <p className="text-sm font-semibold text-slate-800">基本与联系信息</p>
              <p className="mt-1 text-xs text-slate-500">先填写客户识别和日常联系所需信息。</p>
            </div>
            <div className="sm:col-span-2">
              <Label>客户编号</Label>
              <div className="flex gap-2 items-center">
                <Input value={form.customer_code} onChange={e => setForm({ ...form, customer_code: e.target.value })} placeholder={editingId ? '修改编号' : `留空自动生成`} className="font-mono" />
                {!editingId && <Button type="button" size="sm" variant="outline" className="shrink-0 text-xs" onClick={() => setForm({ ...form, customer_code: getNextAutoCode(form.industry) })}>自动生成</Button>}
              </div>
            </div>
            <div><Label>商家名称 *</Label><Input value={form.business_name} onChange={e => { setForm({ ...form, business_name: e.target.value }); checkDuplicate(e.target.value, form.phone); }} /></div>
            <div><Label>联系人 *</Label><Input value={form.contact_name} onChange={e => setForm({ ...form, contact_name: e.target.value })} /></div>
            <div><Label>电话 *</Label><Input value={form.phone} onChange={e => { setForm({ ...form, phone: e.target.value }); checkDuplicate(form.business_name, e.target.value); }} /></div>
            <div><Label>微信/WhatsApp</Label><Input value={form.wechat} onChange={e => setForm({ ...form, wechat: e.target.value })} /></div>
            <div><Label>邮箱</Label><Input value={form.email} onChange={e => setForm({ ...form, email: e.target.value })} /></div>
            <div className="mt-1 rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 sm:col-span-2">
              <p className="text-sm font-semibold text-slate-800">地区与客户归类</p>
              <p className="mt-1 text-xs text-slate-500">补充客户所在地区、来源、等级和当前状态。</p>
            </div>
            <div>
              <Label>行业</Label>
              <div className="flex gap-1.5">
                <NativeSelect value={form.industry} onChange={v => setForm({ ...form, industry: v })} options={Object.entries(industryLabels).map(([k, v]) => ({ value: k, label: v }))} className="flex-1" />
                <Button type="button" size="sm" variant="outline" className="min-h-11 shrink-0 px-3 text-xs text-blue-600 hover:text-blue-700 sm:h-10 sm:min-h-0 sm:px-2" aria-label="添加行业分类" onClick={() => setShowAddIndustry(true)}><Plus className="w-3.5 h-3.5" /></Button>
              </div>
              {showAddIndustry && (
                <div className="mt-2 p-3 border border-blue-200 bg-blue-50/50 rounded-lg space-y-2">
                  <Label className="text-xs text-blue-700">添加新行业分类</Label>
                  <div className="flex gap-2">
                    <Input value={newIndustryName} onChange={e => setNewIndustryName(e.target.value)} placeholder="输入行业名称，如：教育" className="h-8 text-sm flex-1" onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); handleAddIndustry(); } }} />
                    <Button type="button" size="sm" className="min-h-11 bg-blue-600 text-xs hover:bg-blue-700 sm:h-8 sm:min-h-0" onClick={handleAddIndustry}>添加</Button>
                    <Button type="button" size="sm" variant="ghost" className="min-h-11 text-xs sm:h-8 sm:min-h-0" onClick={() => { setShowAddIndustry(false); setNewIndustryName(''); }}>取消</Button>
                  </div>
                </div>
              )}
            </div>
            <div><Label>国家</Label><NativeSelect value={form.country} onChange={v => { setManualCityInput(false); setForm({ ...form, country: v, state: getStatesForCountry(v)[0]?.code || '', city: '' }); }} options={countries.map(c => ({ value: c.code, label: `${c.labelCn} (${c.label})` }))} /></div>
            <div><Label>州/省</Label><NativeSelect value={form.state} onChange={v => { setManualCityInput(false); setForm({ ...form, state: v, city: '' }); }} options={countryStates.length > 0 ? countryStates.map(s => ({ value: s.code, label: s.code })) : [{ value: '', label: '请先选择国家' }]} /></div>
            <div>
              <Label>城市</Label>
              {formCities.length > 0 && (
                <NativeSelect
                  value={formCityLabels.has(form.city) && !manualCityInput ? form.city : ''}
                  onChange={v => {
                    if (v === '__manual__') {
                      setManualCityInput(true);
                      return;
                    }
                    setManualCityInput(false);
                    setForm({ ...form, city: v });
                  }}
                  options={[
                    { value: '', label: '请选择城市' },
                    ...formCities.map(ct => ({ value: ct.label, label: ct.label })),
                    { value: '__manual__', label: '列表没有，手动输入其他城市' },
                  ]}
                />
              )}
              {showManualCityField && (
                <Input
                  value={form.city}
                  onChange={e => setForm({ ...form, city: e.target.value })}
                  placeholder={formCities.length > 0 ? '输入其他城市名' : '输入城市名'}
                  className={formCities.length > 0 ? 'mt-2' : ''}
                />
              )}
            </div>
            <div><Label>地址</Label><Input value={form.address} onChange={e => setForm({ ...form, address: e.target.value })} /></div>
            <div><Label>来源</Label><NativeSelect value={form.source} onChange={v => setForm({ ...form, source: v })} options={Object.entries(sourceLabels).map(([k, v]) => ({ value: k, label: v }))} /></div>
            <div>
              <Label>等级</Label>
              <div className="flex gap-1.5">
                <NativeSelect value={form.level} onChange={v => setForm({ ...form, level: v })} options={Object.entries(levelLabels).map(([k, v]) => ({ value: k, label: v }))} className="flex-1" />
                <Button type="button" size="sm" variant="outline" className="min-h-11 shrink-0 px-3 text-xs text-blue-600 hover:text-blue-700 sm:h-10 sm:min-h-0 sm:px-2" aria-label="管理客户等级" onClick={openLevelManager}><Plus className="w-3.5 h-3.5" /></Button>
              </div>
              {showLevelManager && (
                <div className="mt-2 p-3 border border-blue-200 bg-blue-50/50 rounded-lg space-y-3">
                  <div className="flex items-center justify-between gap-2">
                    <Label className="text-xs text-blue-700">管理客户等级</Label>
                    <Button type="button" size="sm" variant="ghost" className="min-h-11 px-3 text-xs sm:h-7 sm:min-h-0 sm:px-2" aria-label="关闭客户等级管理" onClick={() => { setShowLevelManager(false); setNewLevelName(''); }}>
                      <X className="w-3.5 h-3.5" />
                    </Button>
                  </div>
                  <div className="space-y-2">
                    {levelDrafts.map((item) => (
                      <div key={item.key} className="flex items-center gap-2">
                        <Input
                          value={item.label}
                          onChange={e => setLevelDrafts(prev => prev.map(level => (level.key === item.key ? { ...level, label: e.target.value } : level)))}
                          className="h-8 text-sm flex-1"
                          placeholder="等级名称"
                        />
                        <Button
                          type="button"
                          size="sm"
                          variant="ghost"
                          className="h-11 w-11 p-0 text-slate-500 hover:text-red-600 sm:h-8 sm:w-8"
                          aria-label={`删除客户等级：${item.label}`}
                          onClick={() => handleRemoveLevelDraft(item.key)}
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </Button>
                      </div>
                    ))}
                  </div>
                  <div className="flex gap-2">
                    <Input
                      value={newLevelName}
                      onChange={e => setNewLevelName(e.target.value)}
                      placeholder="新增等级，例如：A类客户"
                      className="h-8 text-sm flex-1"
                      onKeyDown={e => {
                        if (e.key === 'Enter') {
                          e.preventDefault();
                          handleAddLevelDraft();
                        }
                      }}
                    />
                    <Button type="button" size="sm" className="min-h-11 bg-blue-600 text-xs hover:bg-blue-700 sm:h-8 sm:min-h-0" onClick={handleAddLevelDraft}>添加</Button>
                  </div>
                  <div className="flex justify-end gap-2">
                    <Button type="button" size="sm" variant="outline" className="min-h-11 text-xs sm:h-8 sm:min-h-0" onClick={() => { setShowLevelManager(false); setNewLevelName(''); }}>取消</Button>
                    <Button type="button" size="sm" className="min-h-11 bg-blue-600 text-xs hover:bg-blue-700 sm:h-8 sm:min-h-0" onClick={handleSaveLevels} disabled={savingLevels}>{savingLevels ? '保存中...' : '保存等级'}</Button>
                  </div>
                </div>
              )}
            </div>
            <div><Label>状态</Label><NativeSelect value={form.status} onChange={v => setForm({ ...form, status: v })} options={Object.entries(statusLabels).map(([k, v]) => ({ value: k, label: v }))} /></div>
            <div className="mt-1 rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 sm:col-span-2">
              <p className="text-sm font-semibold text-slate-800">合作项目与归属</p>
              <p className="mt-1 text-xs text-slate-500">记录负责人、分润归属和当前合作项目；历史记录仍按原规则保留。</p>
            </div>
            {!editingId && <div className="rounded-xl border border-emerald-200 bg-emerald-50/50 p-4 sm:col-span-2">
              <div>
                <Label className="text-sm font-semibold text-slate-800">客户来源与分润归属</Label>
                <p className="mt-1 text-xs leading-5 text-slate-500">首次保存时建立归属。自动模式会优先匹配“负责销售”对应的内部销售渠道，未匹配时归为公司直营；以后变更请到“渠道与分润中心”保留历史。</p>
              </div>
              <div className="mt-3 grid gap-3 sm:grid-cols-2">
                <div><Label className="text-xs">归属渠道</Label><NativeSelect value={commissionPartnerId} onChange={setCommissionPartnerId} options={[{ value: 'auto', label: '系统自动：内部销售 / 公司直营' }, ...commissionPartners.map(item => ({ value: String(item.id), label: `${item.name} · ${item.partner_code}` }))]} /></div>
                <div><Label className="text-xs">归属生效日期</Label><Input type="date" value={commissionEffectiveFrom} onChange={event => setCommissionEffectiveFrom(event.target.value)} /></div>
              </div>
            </div>}
            <div className="rounded-xl border border-blue-200 bg-blue-50/40 p-4 sm:col-span-2">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <Label className="text-sm font-semibold text-slate-800">合作项目（可多选）</Label>
                  <p className="mt-1 text-xs leading-5 text-slate-500">在客户首次录入时建立代运营、餐饮 OS、美业 OS 或一次性项目。尚未合作可以暂不添加；以后在这里继续增加项目。</p>
                </div>
                <Button type="button" size="sm" variant="outline" onClick={addCustomerProject} disabled={customerProjectForms.length >= 4 || customerProjectsLoading}>
                  <Plus className="mr-1 h-3.5 w-3.5" />增加合作项目
                </Button>
              </div>
              {customerProjectsLoading ? (
                <div className="py-6 text-center text-sm text-slate-400">正在加载客户合作项目…</div>
              ) : customerProjectForms.length === 0 ? (
                <div className="mt-4 rounded-lg border border-dashed border-blue-200 bg-white/70 px-4 py-5 text-center text-sm text-slate-500">当前未建立合作项目；客户资料仍可正常保存。</div>
              ) : (
                <div className="mt-4 space-y-3">
                  {form.status === 'lost' && customerProjectForms.some(row => activeCustomerProjectStatuses.has(row.status)) && (
                    <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
                      客户已选择“流失”，但仍有合作项目未停止。请把相关项目改为“项目已停止”并填写结束信息；历史成交和收款不会被删除。
                    </div>
                  )}
                  {customerProjectForms.map((project, index) => (
                    <div key={`${project.engagement_id || 'new'}-${index}`} className="rounded-xl border border-slate-200 bg-white p-4">
                      <div className="mb-3 flex items-center justify-between">
                        <p className="text-sm font-semibold text-slate-800">项目 {index + 1}</p>
                        {!project.engagement_id && <Button type="button" size="sm" variant="ghost" className="text-red-600" onClick={() => setCustomerProjectForms(rows => rows.filter((_row, rowIndex) => rowIndex !== index))}>移除</Button>}
                      </div>
                      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                        <div><Label className="text-xs">业务项目 *</Label><NativeSelect value={project.business_line_code} onChange={value => updateCustomerProject(index, { business_line_code: value })} options={Object.entries(customerProjectLines).map(([value, item]) => ({ value, label: item.label }))} /></div>
                        <div><Label className="text-xs">套餐/项目名称 *</Label><Input value={project.package_name} onChange={event => updateCustomerProject(index, { package_name: event.target.value })} placeholder="如：基础代运营、餐饮 OS 专业版" /></div>
                        <div><Label className="text-xs">项目状态 *</Label><NativeSelect value={project.status} onChange={value => updateCustomerProject(index, {
                          status: value,
                          stopped_at: ['stopped', 'completed'].includes(value) ? (project.stopped_at || businessToday) : '',
                          stop_reason_code: value === 'stopped' ? project.stop_reason_code : '',
                          stop_note: ['stopped', 'completed'].includes(value) ? project.stop_note : '',
                        })} options={Object.entries(customerProjectStatuses).map(([value, label]) => ({ value, label }))} /></div>
                        <div><Label className="text-xs">第一笔有效收款日期</Label><Input type="date" value={project.paid_started_at} max={businessToday} onChange={event => updateCustomerProject(index, { paid_started_at: event.target.value })} /></div>
                        <div><Label className="text-xs">收费周期</Label><NativeSelect value={project.billing_cycle} onChange={value => updateCustomerProject(index, { billing_cycle: value })} options={[{ value: '', label: '待确认' }, ...Object.entries(customerProjectBillingCycles).map(([value, label]) => ({ value, label }))]} /></div>
                        <div><Label className="text-xs">收款方式</Label><NativeSelect value={project.collection_method} onChange={value => updateCustomerProject(index, { collection_method: value })} options={Object.entries(customerProjectCollectionMethods).map(([value, label]) => ({ value, label }))} /></div>
                        <div><Label className="text-xs">币种</Label><Input value={project.currency} maxLength={3} onChange={event => updateCustomerProject(index, { currency: event.target.value.toUpperCase() })} /></div>
                        <div><Label className="text-xs">项目负责人</Label><NativeSelect value={project.owner_employee_id} onChange={value => updateCustomerProject(index, { owner_employee_id: value })} options={[{ value: '', label: '待分配' }, ...employeesList.map(employeeRow => ({ value: String(employeeRow.id), label: employeeRow.name }))]} /></div>
                        {['stopped', 'completed'].includes(project.status) && <div><Label className="text-xs">结束日期 *</Label><Input type="date" value={project.stopped_at} max={businessToday} onChange={event => updateCustomerProject(index, { stopped_at: event.target.value })} /></div>}
                        {project.status === 'stopped' && <div><Label className="text-xs">停止原因</Label><NativeSelect value={project.stop_reason_code} onChange={value => updateCustomerProject(index, { stop_reason_code: value })} options={[{ value: '', label: '待补充' }, ...Object.entries(customerProjectStopReasons).map(([value, label]) => ({ value, label }))]} /></div>}
                        {['stopped', 'completed'].includes(project.status) && <div className="sm:col-span-2"><Label className="text-xs">结束备注</Label><Input value={project.stop_note} onChange={event => updateCustomerProject(index, { stop_note: event.target.value })} placeholder="记录停止或完成背景，方便以后复盘" /></div>}
                      </div>
                      <p className="mt-3 text-xs text-slate-400">“付费合作中”必须填写第一笔有效收款日期；停止项目会同步关闭该项目关联的续费计划，但成交和收款历史永久保留。</p>
                    </div>
                  ))}
                </div>
              )}
            </div>
            <div className="sm:col-span-2">
              <Label>历史意向套餐（兼容旧资料）</Label>
              <div className="mt-1 space-y-2">
                <div className="flex items-start gap-1.5">
                  <div className="flex-1 rounded-md border border-slate-200 bg-slate-50 p-3">
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                      {packageOptionsForForm.map(({ key, label, activeLabel, historical }) => {
                        const checked = form.interested_packages.includes(key);
                        const savedLabel = checked ? getPackageLabelForSnapshot(key, form.interested_packages_snapshot) : '';
                        const displayLabel = activeLabel || label;
                        const isRenamedSnapshot = checked && activeLabel && savedLabel !== activeLabel;
                        return (
                        <label key={key} className="flex items-center gap-2 text-sm text-slate-700 cursor-pointer">
                          <input
                            type="checkbox"
                            checked={checked}
                            onChange={e => toggleInterestedPackage(key, e.target.checked)}
                            className="rounded"
                          />
                          <span>{displayLabel}</span>
                          {historical && <Badge className="bg-slate-100 text-slate-600 text-[10px]">历史已选</Badge>}
                          {isRenamedSnapshot && <Badge className="bg-amber-100 text-amber-700 text-[10px]">原记录：{savedLabel}</Badge>}
                        </label>
                        );
                      })}
                    </div>
                    <p className="text-xs text-slate-500 mt-3">
                      已选（当前归类）: {form.interested_packages.length > 0 ? form.interested_packages.map(item => customerPackageLabels[item] || getPackageLabelForSnapshot(item, form.interested_packages_snapshot)).join('、') : '未选择'}
                    </p>
                    <p className="mt-1 text-xs text-blue-600">新需求请保存客户后在“客户商机”中选择业务线、正式套餐和实际服务范围；这里仅保留历史资料。</p>
                  </div>
                  <Button type="button" size="sm" variant="outline" className="min-h-11 shrink-0 px-3 text-xs text-blue-600 hover:text-blue-700 sm:h-10 sm:min-h-0 sm:px-2" aria-label="管理合作套餐" onClick={openPackageManager}><Plus className="w-3.5 h-3.5" /></Button>
                </div>
                {showPackageManager && (
                  <div className="p-3 border border-blue-200 bg-blue-50/50 rounded-lg space-y-3">
                    <div className="flex items-center justify-between gap-2">
                      <Label className="text-xs text-blue-700">管理客户意向套餐</Label>
                      <Button type="button" size="sm" variant="ghost" className="min-h-11 px-3 text-xs sm:h-7 sm:min-h-0 sm:px-2" aria-label="关闭合作套餐管理" onClick={() => { setShowPackageManager(false); setNewPackageName(''); }}>
                        <X className="w-3.5 h-3.5" />
                      </Button>
                    </div>
                    <div className="space-y-2">
                      {packageDrafts.map((item) => (
                        <div key={item.key} className="rounded-md border border-slate-200 bg-white p-2">
                          <div className="flex items-center gap-2">
                            <Input
                              value={item.label}
                              onChange={e => setPackageDrafts(prev => prev.map(pkg => (pkg.key === item.key ? { ...pkg, label: e.target.value } : pkg)))}
                              className="h-8 text-sm flex-1"
                              placeholder="套餐名称，例如：基础套餐"
                            />
                            <Button
                              type="button"
                              size="sm"
                              variant="ghost"
                              className="h-11 w-11 p-0 text-slate-500 hover:text-red-600 sm:h-8 sm:w-8"
                              aria-label={`删除合作套餐：${item.label}`}
                              onClick={() => handleRemovePackageDraft(item.key)}
                            >
                              <Trash2 className="w-3.5 h-3.5" />
                            </Button>
                          </div>
                        </div>
                      ))}
                    </div>
                    <div className="flex gap-2">
                      <Input
                        value={newPackageName}
                        onChange={e => setNewPackageName(e.target.value)}
                        placeholder="新增套餐，例如：增值套餐"
                        className="h-8 text-sm flex-1"
                        onKeyDown={e => {
                          if (e.key === 'Enter' && !savingPackages) {
                            e.preventDefault();
                            void handleAddPackageDraft();
                          }
                        }}
                      />
                      <Button type="button" size="sm" className="min-h-11 bg-blue-600 text-xs hover:bg-blue-700 sm:h-8 sm:min-h-0" onClick={() => void handleAddPackageDraft()} disabled={savingPackages}>{savingPackages ? '保存中...' : '添加'}</Button>
                    </div>
                    <div className="flex justify-end gap-2">
                      <Button type="button" size="sm" variant="outline" className="min-h-11 text-xs sm:h-8 sm:min-h-0" onClick={() => { setShowPackageManager(false); setNewPackageName(''); }}>取消</Button>
                      <Button type="button" size="sm" className="min-h-11 bg-blue-600 text-xs hover:bg-blue-700 sm:h-8 sm:min-h-0" onClick={handleSavePackages} disabled={savingPackages}>{savingPackages ? '保存中...' : '保存套餐'}</Button>
                    </div>
                  </div>
                )}
              </div>
            </div>
            <div className="mt-1 rounded-xl border border-slate-200 bg-slate-50 p-4 sm:col-span-2">
              <div className="mb-3">
                <p className="text-sm font-semibold text-slate-800">平台与补充资料</p>
                <p className="mt-1 text-xs text-slate-500">记录客户现有平台、负责人和可选链接。</p>
              </div>
              <Label>客户现有平台（基础资料）</Label>
              <div className="mt-1 rounded-md border border-slate-200 bg-slate-50 p-3">
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                  {platformOptionsForForm.map(({ key, label }) => {
                    const checked = form.selected_platforms.includes(key);
                    return (
                      <label key={key} className="flex items-center gap-2 text-sm text-slate-700 cursor-pointer">
                        <input
                          type="checkbox"
                          checked={checked}
                          onChange={e => toggleSelectedPlatform(key, e.target.checked)}
                          className="rounded"
                        />
                        <span>{label}</span>
                      </label>
                    );
                  })}
                </div>
                <p className="text-xs text-slate-500 mt-3">
                  已选: {formatSelectedPlatforms(form.selected_platforms)}
                </p>
                <p className="mt-1 text-xs text-blue-600">这里只记录客户目前已有的平台，不代表 T24 实际代运营范围；实际运营平台随每个商机/订阅单独确认。</p>
              </div>
            </div>
            <div><Label>负责销售</Label><NativeSelect value={form.sales_employee_id ? String(form.sales_employee_id) : ''} onChange={v => { const emp = employeesList.find(e => e.id === Number(v)); setForm({ ...form, sales_person: emp?.name || '', sales_employee_id: v ? Number(v) : '' }); }} options={[{ value: '', label: '请选择负责人' }, ...employeesList.map(e => ({ value: String(e.id), label: `${e.name}${e.department ? ' - ' + e.department : ''}` }))]} /></div>
            <div><Label>官网</Label><Input value={form.website} onChange={e => setForm({ ...form, website: e.target.value })} /></div>
            <div><Label>客户平台现状备注</Label><Input value={form.current_platform} onChange={e => setForm({ ...form, current_platform: e.target.value })} placeholder="如：客户自营 Facebook，Google 暂未维护" /></div>
            <div className="mt-1 border-t border-slate-200 pt-3 sm:col-span-2">
              <h4 className="text-sm font-medium text-slate-600 mb-3">社交媒体链接</h4>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <div><Label className="text-xs">Facebook</Label><Input value={form.facebook_link} onChange={e => setForm({ ...form, facebook_link: e.target.value })} placeholder="https://facebook.com/..." /></div>
                <div><Label className="text-xs">Instagram</Label><Input value={form.instagram_link} onChange={e => setForm({ ...form, instagram_link: e.target.value })} placeholder="https://instagram.com/..." /></div>
                <div><Label className="text-xs">Google Business</Label><Input value={form.google_business_link} onChange={e => setForm({ ...form, google_business_link: e.target.value })} placeholder="https://business.google.com/..." /></div>
                <div><Label className="text-xs">Yelp</Label><Input value={form.yelp_link} onChange={e => setForm({ ...form, yelp_link: e.target.value })} placeholder="https://yelp.com/biz/..." /></div>
                <div><Label className="text-xs">TikTok</Label><Input value={form.tiktok_link} onChange={e => setForm({ ...form, tiktok_link: e.target.value })} placeholder="https://tiktok.com/@..." /></div>
              </div>
            </div>
            <div className="sm:col-span-2"><Label>备注</Label><Textarea value={form.notes} onChange={e => setForm({ ...form, notes: e.target.value })} rows={2} /></div>
          </div>
          <div data-testid="customer-form-actions" className="sticky bottom-0 z-20 -mx-6 -mb-6 mt-5 flex gap-2 border-t border-slate-200 bg-white/95 px-6 py-4 backdrop-blur sm:static sm:m-0 sm:justify-end sm:border-0 sm:bg-transparent sm:p-0">
            <Button variant="outline" onClick={() => setShowForm(false)} className="min-h-11 flex-1 sm:flex-none">取消</Button>
            <Button onClick={handleSave} disabled={saving} className="min-h-11 flex-1 bg-blue-600 hover:bg-blue-700 sm:flex-none">{saving ? '保存中...' : '保存'}</Button>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );

  const CustomerPaginationFooter = () => {
    if (paginatedCustomers.total === 0) return null;
    return (
      <div className="flex flex-col gap-3 border-t border-slate-100 px-4 py-3 text-sm text-slate-500 sm:flex-row sm:items-center sm:justify-between">
        <div>
          显示 {paginatedCustomers.start}-{paginatedCustomers.end} 条 / 共 {paginatedCustomers.total} 条
          {filtered.length !== customers.length ? `（筛选自 ${customers.length} 条）` : ''}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-slate-400">每页</span>
          <NativeSelect
            value={String(customerPageSize)}
            onChange={value => setCustomerPageSize(Number(value))}
            options={CUSTOMER_PAGE_SIZE_OPTIONS.map(size => ({ value: String(size), label: `${size} 条` }))}
            className="min-h-11 w-24 text-xs md:h-8 md:min-h-0"
          />
          <Button size="sm" variant="outline" className="min-h-11 md:h-8 md:min-h-0" onClick={() => setCustomerPage(1)} disabled={paginatedCustomers.page <= 1}>
            首页
          </Button>
          <Button size="sm" variant="outline" className="min-h-11 md:h-8 md:min-h-0" onClick={() => setCustomerPage(paginatedCustomers.page - 1)} disabled={paginatedCustomers.page <= 1}>
            上一页
          </Button>
          <span className="min-w-20 text-center text-xs text-slate-500">
            {paginatedCustomers.page} / {paginatedCustomers.totalPages} 页
          </span>
          <Button size="sm" variant="outline" className="min-h-11 md:h-8 md:min-h-0" onClick={() => setCustomerPage(paginatedCustomers.page + 1)} disabled={paginatedCustomers.page >= paginatedCustomers.totalPages}>
            下一页
          </Button>
          <Button size="sm" variant="outline" className="min-h-11 md:h-8 md:min-h-0" onClick={() => setCustomerPage(paginatedCustomers.totalPages)} disabled={paginatedCustomers.page >= paginatedCustomers.totalPages}>
            末页
          </Button>
        </div>
      </div>
    );
  };

  const DetailPaginationFooter = ({
    pagination,
    pageSize,
    onPageChange,
    onPageSizeChange,
    label = '记录',
  }: {
    pagination: PaginationResult<any>;
    pageSize: number;
    onPageChange: (page: number) => void;
    onPageSizeChange: (pageSize: number) => void;
    label?: string;
  }) => {
    if (pagination.total === 0) return null;
    return (
      <div className="mt-3 flex flex-col gap-3 rounded-lg border border-slate-100 bg-slate-50/70 px-3 py-2 text-sm text-slate-500 sm:flex-row sm:items-center sm:justify-between">
        <div>
          显示 {pagination.start}-{pagination.end} 条 / 共 {pagination.total} 条{label}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-slate-400">每页</span>
          <NativeSelect
            value={String(pageSize)}
            onChange={value => onPageSizeChange(Number(value))}
            options={CUSTOMER_PAGE_SIZE_OPTIONS.map(size => ({ value: String(size), label: `${size} 条` }))}
            className="min-h-11 w-24 text-xs md:h-8 md:min-h-0"
          />
          <Button size="sm" variant="outline" className="min-h-11 bg-white md:h-8 md:min-h-0" onClick={() => onPageChange(1)} disabled={pagination.page <= 1}>
            首页
          </Button>
          <Button size="sm" variant="outline" className="min-h-11 bg-white md:h-8 md:min-h-0" onClick={() => onPageChange(pagination.page - 1)} disabled={pagination.page <= 1}>
            上一页
          </Button>
          <span className="min-w-20 text-center text-xs text-slate-500">
            {pagination.page} / {pagination.totalPages} 页
          </span>
          <Button size="sm" variant="outline" className="min-h-11 bg-white md:h-8 md:min-h-0" onClick={() => onPageChange(pagination.page + 1)} disabled={pagination.page >= pagination.totalPages}>
            下一页
          </Button>
          <Button size="sm" variant="outline" className="min-h-11 bg-white md:h-8 md:min-h-0" onClick={() => onPageChange(pagination.totalPages)} disabled={pagination.page >= pagination.totalPages}>
            末页
          </Button>
        </div>
      </div>
    );
  };

  // ========== DETAIL VIEW ==========
  if (loading && customers.length === 0) {
    return <PageLoadState loading message="正在读取客户资料…" />;
  }
  if (loadError && customers.length === 0) {
    return (
      <PageLoadState
        error={loadError}
        onRetry={() => {
          setLoading(true);
          void loadCustomers();
        }}
      />
    );
  }

  if (selectedCustomer) {
    const c = selectedCustomer;
    const detailAddress = [
      c.address,
      c.city,
      c.country && c.state ? getStateLabel(c.country, c.state) : (c.state || ''),
      c.country ? getCountryLabel(c.country) : '',
    ].filter(Boolean).join(', ');
    const totalDealAmount = deals.reduce((sum, item) => sum + Number(item.deal_amount || 0), 0);
    const totalAmountDue = payments.reduce((sum, item) => sum + Number(item.amount_due || 0), 0);
    const totalAmountPaid = payments.reduce((sum, item) => sum + Number(item.amount_paid || 0), 0);
    const totalOutstanding = payments.reduce((sum, item) => sum + Number(item.outstanding_amount || 0), 0);
    const customerFinanceSummary = buildCustomerFinanceSummary(payments, customerExpenses, customerDeductionRates);
    const customerFinanceRecordCount = payments.length + customerExpenses.length;
    const latestPaymentDate = payments[0]?.payment_date?.slice(0, 10) || '-';
    const latestDealDate = deals[0]?.deal_date?.slice(0, 10) || '-';
    const renewalRows = subscriptions
      .map(item => {
        const status = computeSubscriptionState(item);
        const daysLeft = getSubscriptionRemainingDays(item);
        return { ...item, computed_status: status, days_left: daysLeft };
      })
      .sort((a, b) => {
        const aTime = a.end_date ? new Date(a.end_date).getTime() : Number.MAX_SAFE_INTEGER;
        const bTime = b.end_date ? new Date(b.end_date).getTime() : Number.MAX_SAFE_INTEGER;
        return aTime - bTime;
      });
    const currentServiceRows = renewalRows.filter(item => !archivedSubscriptionStatuses.has(item.computed_status));
    const historicalServiceRows = renewalRows.filter(item => archivedSubscriptionStatuses.has(item.computed_status));
    const activeSubscriptionCount = currentServiceRows.length;
    const activeCustomerProjectCount = customerProjects.filter(item => activeCustomerProjectStatuses.has(item.status)).length;
    const currentLifecycleStatus = lifecycleDetail?.cycles?.[0]?.status;
    const hasClosureMismatch = currentLifecycleStatus === 'stopped' && (activeSubscriptionCount > 0 || activeCustomerProjectCount > 0);
    const pendingServiceTasks = serviceTasks.filter(item => !['completed', 'cancelled'].includes(item.status || '')).length;
    const overdueServiceTasks = serviceTasks.filter(item => item.due_date && item.due_date.slice(0, 10) < businessToday && !['completed', 'cancelled'].includes(item.status || '')).length;
    const openServiceIssues = serviceProgresses.filter(item => item.issue_status && item.issue_status !== 'none' && !item.issue_resolved).length;
    const detailBusinessLineMap = Object.fromEntries((productCatalog.business_lines || []).map((item: any) => [item.id, item]));
    const detailProductMap = Object.fromEntries((productCatalog.products || []).map((item: any) => [item.id, item]));
    const detailPlanMap = Object.fromEntries((productCatalog.plans || []).map((item: any) => [item.id, item]));
    const paginatedFollowUps = paginateList(followUps, followUpPage, followUpPageSize);
    const paginatedDeals = paginateList(deals, dealPage, dealPageSize);
    const paginatedServiceInfo = paginateList(currentServiceRows, serviceInfoPage, serviceInfoPageSize);
    const paginatedFinanceMonthlyRows = paginateList(customerFinanceSummary.monthlyRows, financeMonthlyPage, financeMonthlyPageSize);
    const paginatedFinancePaymentLines = paginateList(customerFinanceSummary.paymentLines, financePaymentPage, financePaymentPageSize);
    const paginatedFinanceExpenses = paginateList(customerExpenses, financeExpensePage, financeExpensePageSize);
    const paginatedRenewals = paginateList(renewalRows, renewalPage, renewalPageSize);
    const upcomingRenewalCount = renewalRows.filter(item => item.computed_status === 'expiring_soon').length;
    const autoRenewCount = renewalRows.filter(item => item.auto_renew).length;
    const timelineEvents = [
      ...followUps.map((item: any) => ({ type: '跟进', title: item.follow_up_type || item.content || '客户跟进', detail: item.content || item.notes || '', date: item.follow_up_date || item.created_at, tone: 'blue' })),
      ...deals.map((item: any) => ({ type: '成交', title: item.package_name || item.deal_name || '成交记录', detail: item.amount ? `${item.amount} ${item.currency || 'USD'}` : '', date: item.deal_date || item.created_at, tone: 'emerald' })),
      ...payments.map((item: any) => ({ type: '收款', title: item.payment_type || '收款记录', detail: item.amount ? `${item.amount} ${item.currency || 'USD'}` : '', date: item.payment_date || item.created_at, tone: 'cyan' })),
      ...subscriptions.map((item: any) => ({ type: '服务/续费', title: item.package_name || '套餐服务', detail: `${item.start_date || '-'} 至 ${item.end_date || '-'}`, date: item.start_date || item.created_at, tone: 'amber' })),
      ...(lifecycleDetail?.events || []).map((item: any) => ({
        type: '生命周期',
        title: lifecycleEventLabels[item.event_type] || item.event_type,
        detail: item.reason_label || item.note || (item.source_id ? `${item.source_type} #${item.source_id}` : ''),
        date: item.effective_at || item.created_at,
        tone: item.event_type === 'stop' ? 'red' : item.event_type === 'reactivate' || item.event_type === 'resume' ? 'emerald' : 'violet',
      })),
    ].filter(item => item.date).sort((a, b) => String(b.date).localeCompare(String(a.date)));
    const reminderActionTab = activeReminder === 'overdue_payment'
      ? 'payments'
      : activeReminder === 'renewal_due'
        ? 'renewals'
        : activeReminder
          ? 'followups'
          : '';
    const secondaryDetailTabs = [
      { value: 'info', label: '基础信息' },
      { value: 'contacts', label: `联系人 (${contacts.length})` },
      { value: 'followups', label: `跟进记录 (${followUps.length})` },
      { value: 'deals', label: `成交记录 (${deals.length})` },
      { value: 'materials', label: '素材管理' },
      { value: 'ai_copy', label: 'AI 文案' },
      { value: 'media', label: '媒体账号' },
      { value: 'logs', label: '操作日志' },
    ];
    const secondaryDetailTabValues = new Set(secondaryDetailTabs.map(item => item.value));
    const customer360Actions: Array<{
      key: string;
      title: string;
      description: string;
      button: string;
      tone: string;
      onClick: () => void;
    }> = [];
    if (totalOutstanding > 0 && canViewFinance) customer360Actions.push({
      key: 'outstanding', title: `核对未结清款项 ${formatCurrency(totalOutstanding)}`,
      description: '确认应收、实收和退款记录，避免财务状态与服务状态不一致。', button: '核对财务',
      tone: 'border-rose-200 bg-rose-50', onClick: () => handleDetailTabChange('payments'),
    });
    if (upcomingRenewalCount > 0) customer360Actions.push({
      key: 'renewal', title: `${upcomingRenewalCount} 个套餐即将到期`,
      description: canViewFinance ? '核对收款方式、服务区间与下一次付款时间。' : '核对服务区间、续费方式与下一次续费时间。', button: '处理续费',
      tone: 'border-amber-200 bg-amber-50', onClick: () => handleDetailTabChange('renewals'),
    });
    if (overdueServiceTasks > 0) customer360Actions.push({
      key: 'overdue-task', title: `${overdueServiceTasks} 个服务任务已逾期`,
      description: '先确认卡点和负责人，再更新服务进度或完成结果。', button: '处理服务',
      tone: 'border-rose-200 bg-rose-50', onClick: () => handleDetailTabChange('subscriptions'),
    });
    if (openServiceIssues > 0) customer360Actions.push({
      key: 'service-issue', title: `${openServiceIssues} 个服务问题未解决`,
      description: '进入服务信息核对问题描述、处理人和结果。', button: '解决问题',
      tone: 'border-violet-200 bg-violet-50', onClick: () => handleDetailTabChange('subscriptions'),
    });
    if (canManageContacts && contacts.length === 0) customer360Actions.push({
      key: 'contact', title: '补充关键联系人', description: '至少记录老板或主要对接人，避免后续交付找不到人。', button: '添加联系人',
      tone: 'border-slate-200 bg-slate-50', onClick: () => { handleDetailTabChange('contacts'); setContactForm(emptyContactForm); setEditingContactId(null); setShowContactForm(true); },
    });
    if (canCreateFollowUp && followUps.length === 0) customer360Actions.push({
      key: 'followup', title: '补充首次跟进记录', description: '记录客户当前情况和下一步安排，让团队接手时不丢上下文。', button: '新增跟进',
      tone: 'border-slate-200 bg-slate-50', onClick: () => { handleDetailTabChange('followups'); setFollowForm(emptyFollowForm); setEditingFollowId(null); setShowFollowForm(true); },
    });

    return (
      <div className="app-page space-y-5">
        <div className="app-page-title items-start md:items-center">
          <div className="flex min-w-0 flex-wrap items-center gap-3">
          <Button variant="ghost" size="sm" onClick={closeDetail}><ArrowLeft className="w-4 h-4 mr-1" /> {detailReturnTo ? getReturnLabel(detailReturnTo) : detailFromFinance ? '返回财务' : '返回列表'}</Button>
          <div className="min-w-0">
            <p className="text-xs font-medium uppercase tracking-[0.14em] text-blue-600">客户详情</p>
            <h2 className="truncate text-xl font-bold text-slate-900">{c.business_name}</h2>
            <p className="mt-1 text-xs text-slate-500">编号 {c.customer_code || '-'} · 负责人 {c.sales_person || '-'} · 数据更新 {formatCustomerTimestamp(detailLoadedAt)}</p>
          </div>
          <Badge className={statusColors[c.status]}>{statusLabels[c.status]}</Badge>
          <Badge className={getLevelColorClass(c.level)}>{levelLabels[c.level]}</Badge>
          </div>
          <div className="flex w-full flex-wrap items-center gap-2 md:w-auto md:justify-end">
            {c.phone && <Button variant="outline" size="sm" className="min-h-11 flex-1 md:min-h-0 md:flex-none" asChild><a href={`tel:${c.phone}`}><Phone className="mr-1 h-3.5 w-3.5" /> 拨打电话</a></Button>}
            {canCreateFollowUp && <Button size="sm" className="min-h-11 flex-1 bg-blue-600 hover:bg-blue-700 md:min-h-0 md:flex-none" onClick={() => { handleDetailTabChange('followups'); setFollowForm(emptyFollowForm); setEditingFollowId(null); setShowFollowForm(true); }}><MessageSquarePlus className="mr-1 h-3.5 w-3.5" /> 新增跟进</Button>}
            {isAdmin && <Button variant="outline" size="sm" className="hidden md:inline-flex" onClick={() => void openAccessManager(c)}><Users className="mr-1 h-3.5 w-3.5" /> 管理团队成员</Button>}
            <Button variant="outline" size="sm" className="min-h-11 md:min-h-0" onClick={() => loadCustomerDetail(c.id, c)} disabled={detailLoading}>
              <RefreshCw className={`w-3.5 h-3.5 mr-1 ${detailLoading ? 'animate-spin' : ''}`} /> 刷新数据
            </Button>
          </div>
        </div>
        {activeReminderMessage && (
          <Card className="border-blue-200 bg-blue-50">
            <CardContent className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between">
              <div><p className="text-sm font-medium text-blue-700">{activeReminderMessage.title}</p><p className="text-xs text-blue-600 mt-1">{activeReminderMessage.description}</p></div>
              {reminderActionTab && <Button size="sm" onClick={() => handleDetailTabChange(reminderActionTab)}>立即处理</Button>}
            </CardContent>
          </Card>
        )}
        {detailLoadError && (
          <div className="flex flex-col gap-3 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 sm:flex-row sm:items-center sm:justify-between">
            <span>客户关联数据加载失败：{detailLoadError}</span>
            <Button size="sm" variant="outline" className="border-red-200 bg-white text-red-700 hover:bg-red-100" onClick={() => loadCustomerDetail(c.id, c)}>重新加载</Button>
          </div>
        )}
        {hasClosureMismatch && (
          <div className="flex flex-col gap-3 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 sm:flex-row sm:items-center sm:justify-between">
            <div><p className="font-semibold">客户已停止，但仍有项目或续费显示合作中</p><p className="mt-1 text-xs text-red-600">同步只关闭未来合作与扣款，不会删除成交、收款或历史服务。</p></div>
            {isAdmin && <Button size="sm" className="shrink-0 bg-red-600 hover:bg-red-700" disabled={closureSyncing} onClick={() => void reconcileSelectedCustomerClosure()}>{closureSyncing ? '同步中…' : '一键同步闭环'}</Button>}
          </div>
        )}
        <Tabs value={selectedCustomerTab} onValueChange={handleDetailTabChange} className="w-full">
          <div className="mb-3 flex flex-col gap-2 lg:flex-row lg:items-center">
          <div className="-mx-1 overflow-x-auto px-1 pb-1 md:hidden">
            <TabsList aria-label="客户手机主导航" className="h-auto w-max min-w-full justify-start gap-1 bg-slate-100 p-1">
              <TabsTrigger value="overview" className="min-h-11 shrink-0 px-3 text-sm">客户 360</TabsTrigger>
              <TabsTrigger value="timeline" className="min-h-11 shrink-0 px-3 text-sm">时间线</TabsTrigger>
              <TabsTrigger value="opportunities" className="min-h-11 shrink-0 px-3 text-sm">客户商机</TabsTrigger>
              <TabsTrigger value="subscriptions" className="min-h-11 shrink-0 px-3 text-sm">服务信息</TabsTrigger>
              {canViewFinance && <TabsTrigger value="payments" className="min-h-11 shrink-0 px-3 text-sm">财务信息</TabsTrigger>}
              <TabsTrigger value="renewals" className="min-h-11 shrink-0 px-3 text-sm">续费信息</TabsTrigger>
            </TabsList>
          </div>
          <label className="md:hidden">
            <span className="sr-only">更多资料与工具</span>
            <NativeSelect
              value={secondaryDetailTabValues.has(selectedCustomerTab) ? selectedCustomerTab : ''}
              onChange={value => { if (value) handleDetailTabChange(value); }}
              options={[{ value: '', label: '更多资料与工具' }, ...secondaryDetailTabs]}
              className="w-full"
            />
          </label>
          <TabsList className="hidden h-auto max-w-full flex-wrap justify-start gap-1 bg-slate-100 p-1 md:flex">
            <TabsTrigger value="overview" className="shrink-0 text-xs">客户 360</TabsTrigger>
            <TabsTrigger value="timeline" className="shrink-0 text-xs">时间线 ({detailLoading ? '…' : timelineEvents.length})</TabsTrigger>
            <TabsTrigger value="opportunities" className="shrink-0 text-xs">客户商机</TabsTrigger>
            <TabsTrigger value="subscriptions" className="shrink-0 text-xs">服务信息 ({detailLoading ? '…' : currentServiceRows.length})</TabsTrigger>
            {canViewFinance && <TabsTrigger value="payments" className="shrink-0 text-xs">财务信息 ({detailLoading ? '…' : customerFinanceRecordCount})</TabsTrigger>}
            <TabsTrigger value="renewals" className="shrink-0 text-xs">续费信息 ({detailLoading ? '…' : renewalRows.length})</TabsTrigger>
          </TabsList>
          <NativeSelect
            value={secondaryDetailTabValues.has(selectedCustomerTab) ? selectedCustomerTab : ''}
            onChange={value => { if (value) handleDetailTabChange(value); }}
            options={[{ value: '', label: '更多资料与工具' }, ...secondaryDetailTabs]}
            className="hidden h-9 w-full md:block lg:w-48"
          />
          </div>

          <TabsContent value="overview">
            <div className="grid gap-4 xl:grid-cols-[1.2fr_0.8fr]">
              <div className="space-y-4">
                <Card className="border-slate-200"><CardContent className="p-5">
                  <div className="flex flex-wrap items-center justify-between gap-3"><div><h3 className="text-base font-semibold text-slate-900">下一步动作</h3><p className="mt-1 text-xs text-slate-500">提醒已转换成可直接处理的动作，不再需要先去别的页面找记录。</p></div><Badge className={customer360Actions.length ? 'bg-amber-100 text-amber-800' : 'bg-emerald-100 text-emerald-700'}>{customer360Actions.length ? `${customer360Actions.length} 项待处理` : '当前无风险事项'}</Badge></div>
                  {customer360Actions.length === 0 ? <div className="mt-4 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-5 text-sm text-emerald-800">客户资料、服务和财务状态目前没有发现需要立即处理的问题。</div> : <div className="mt-4 space-y-2">{customer360Actions.slice(0, 6).map(action => <div key={action.key} className={`flex flex-col gap-3 rounded-xl border p-3 sm:flex-row sm:items-center ${action.tone}`}><div className="min-w-0 flex-1"><p className="text-sm font-medium text-slate-900">{action.title}</p><p className="mt-1 text-xs text-slate-600">{action.description}</p></div><Button size="sm" variant="outline" className="shrink-0 bg-white" onClick={action.onClick}>{action.button}</Button></div>)}</div>}
                </CardContent></Card>

                <Card className="border-slate-200"><CardContent className="p-5">
                  <div className="flex flex-wrap items-center justify-between gap-3"><div><h3 className="text-base font-semibold text-slate-900">当前合作与交付</h3><p className="mt-1 text-xs text-slate-500">项目、套餐和服务任务统一查看。</p></div><Button size="sm" variant="outline" onClick={() => handleDetailTabChange('subscriptions')}>查看服务明细</Button></div>
                  <div className="mt-4 grid gap-3 sm:grid-cols-3"><div className="rounded-xl bg-blue-50 p-3"><p className="text-xs text-blue-700">合作中项目</p><p className="mt-1 text-xl font-semibold text-blue-900">{activeCustomerProjectCount}</p></div><div className="rounded-xl bg-slate-50 p-3"><p className="text-xs text-slate-500">在服套餐</p><p className="mt-1 text-xl font-semibold text-slate-900">{activeSubscriptionCount}</p></div><div className="rounded-xl bg-slate-50 p-3"><p className="text-xs text-slate-500">待处理服务任务</p><p className="mt-1 text-xl font-semibold text-slate-900">{pendingServiceTasks}</p></div></div>
                </CardContent></Card>

                <Card className="border-slate-200"><CardContent className="p-5">
                  <div className="flex items-center justify-between gap-3"><div><h3 className="text-base font-semibold text-slate-900">最近动态</h3><p className="mt-1 text-xs text-slate-500">跟进、成交、收款、服务和生命周期的统一时间线。</p></div><Button size="sm" variant="ghost" onClick={() => handleDetailTabChange('timeline')}>查看全部</Button></div>
                  {timelineEvents.length === 0 ? <div className="app-empty mt-4">暂无历史事件</div> : <div className="mt-4 divide-y divide-slate-100">{timelineEvents.slice(0, 5).map((event, index) => <div key={`${event.type}-${event.date}-${index}`} className="flex items-start gap-3 py-3"><Badge variant="outline" className="shrink-0">{event.type}</Badge><div className="min-w-0 flex-1"><p className="truncate text-sm font-medium text-slate-800">{event.title}</p>{event.detail && <p className="mt-1 truncate text-xs text-slate-500">{event.detail}</p>}</div><span className="shrink-0 text-xs text-slate-400">{String(event.date).slice(0, 10)}</span></div>)}</div>}
                </CardContent></Card>
              </div>

              <div className="space-y-4">
                <Card className="border-slate-200"><CardContent className="p-5">
                  <h3 className="text-base font-semibold text-slate-900">客户摘要</h3>
                  <div className="mt-4 space-y-3 text-sm"><div className="flex justify-between gap-4"><span className="text-slate-500">客户编号</span><span className="font-medium text-slate-800">{c.customer_code || '-'}</span></div><div className="flex justify-between gap-4"><span className="text-slate-500">负责人</span><span className="font-medium text-slate-800">{c.sales_person || '-'}</span></div><div className="flex justify-between gap-4"><span className="text-slate-500">联系人</span><span className="font-medium text-slate-800">{c.contact_name || '-'}</span></div><div className="flex justify-between gap-4"><span className="text-slate-500">电话</span><span className="font-medium text-slate-800">{c.phone || '-'}</span></div><div className="flex justify-between gap-4"><span className="text-slate-500">地区</span><span className="text-right font-medium text-slate-800">{detailAddress || '-'}</span></div></div>
                  <div className="mt-4 flex flex-wrap gap-2">{canManageContacts && <Button size="sm" variant="outline" onClick={() => handleDetailTabChange('info')}>编辑基础资料</Button>}{canCreateFollowUp && <Button size="sm" variant="outline" onClick={() => { handleDetailTabChange('followups'); setFollowForm(emptyFollowForm); setEditingFollowId(null); setShowFollowForm(true); }}>新增跟进</Button>}<Button size="sm" variant="outline" onClick={() => handleDetailTabChange('opportunities')}>管理新商机</Button></div>
                </CardContent></Card>

                <Card className="border-slate-200"><CardContent className="p-5">
                  <div className="flex items-center justify-between gap-3"><h3 className="text-base font-semibold text-slate-900">经营摘要</h3>{canViewFinance && <Button size="sm" variant="ghost" onClick={() => handleDetailTabChange('payments')}>财务明细</Button>}</div>
                  <div className="mt-4 space-y-3">{canViewFinance && <><div className="flex items-end justify-between border-b border-slate-100 pb-3"><div><p className="text-xs text-slate-500">累计成交</p><p className="mt-1 text-xl font-semibold text-slate-900">{formatCurrency(totalDealAmount)}</p></div><span className="text-xs text-slate-400">最近 {latestDealDate}</span></div><div className="flex items-end justify-between border-b border-slate-100 pb-3"><div><p className="text-xs text-slate-500">累计实收</p><p className="mt-1 text-xl font-semibold text-emerald-700">{formatCurrency(totalAmountPaid)}</p></div><span className="text-xs text-slate-400">最近 {latestPaymentDate}</span></div><div className="flex items-end justify-between"><div><p className="text-xs text-slate-500">当前未结清</p><p className={`mt-1 text-xl font-semibold ${totalOutstanding > 0 ? 'text-rose-700' : 'text-slate-900'}`}>{formatCurrency(totalOutstanding)}</p></div><span className="text-xs text-slate-400">累计应收 {formatCurrency(totalAmountDue)}</span></div></>}{!canViewFinance && <p className="rounded-lg bg-slate-50 p-3 text-xs text-slate-500">当前角色仅显示合作、服务和续费状态；成交金额、收款、手续费、扣点、成本与利润均不可见。</p>}</div>
                </CardContent></Card>

                <Card className="border-slate-200"><CardContent className="p-5"><h3 className="text-base font-semibold text-slate-900">续费摘要</h3><div className="mt-4 grid grid-cols-2 gap-3"><div className="rounded-xl bg-amber-50 p-3"><p className="text-xs text-amber-700">即将到期</p><p className="mt-1 text-xl font-semibold text-amber-900">{upcomingRenewalCount}</p></div><div className="rounded-xl bg-slate-50 p-3"><p className="text-xs text-slate-500">自动续费</p><p className="mt-1 text-xl font-semibold text-slate-900">{autoRenewCount}</p></div></div><Button className="mt-4 w-full" variant="outline" onClick={() => handleDetailTabChange('renewals')}>查看续费与收款状态</Button></CardContent></Card>
              </div>
            </div>
          </TabsContent>

          <TabsContent value="timeline">
            <Card className="border-slate-200"><CardContent className="p-5">
              <div className="mb-4 flex items-center justify-between gap-3">
                <div><h3 className="text-sm font-semibold text-slate-800">客户全生命周期</h3><p className="mt-1 text-xs text-slate-500">集中查看跟进、成交、收款、服务和续费记录</p></div>
                <Badge className="bg-slate-100 text-slate-600">{timelineEvents.length} 条记录</Badge>
              </div>
              {timelineEvents.length === 0 ? <div className="app-empty">暂无历史事件</div> : (
                <div className="relative space-y-3 before:absolute before:bottom-2 before:left-[11px] before:top-2 before:w-px before:bg-slate-200">
                  {timelineEvents.map((event, index) => (
                    <div key={`${event.type}-${event.date}-${index}`} className="relative flex gap-3">
                      <span className={`z-10 mt-1 h-2.5 w-2.5 shrink-0 rounded-full ring-4 ring-white ${event.tone === 'red' ? 'bg-red-500' : event.tone === 'violet' ? 'bg-violet-500' : event.tone === 'emerald' ? 'bg-emerald-500' : event.tone === 'cyan' ? 'bg-cyan-500' : event.tone === 'amber' ? 'bg-amber-500' : 'bg-blue-500'}`} />
                      <div className="min-w-0 flex-1 rounded-xl border border-slate-200 bg-slate-50/70 px-3 py-2.5">
                        <div className="flex flex-wrap items-center justify-between gap-2"><div className="flex items-center gap-2"><Badge className="bg-white text-slate-600">{event.type}</Badge><span className="text-sm font-medium text-slate-800">{event.title}</span></div><span className="text-xs text-slate-400">{String(event.date).slice(0, 16)}</span></div>
                        {event.detail && <p className="mt-1 truncate text-xs text-slate-500">{event.detail}</p>}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </CardContent></Card>
          </TabsContent>

          <TabsContent value="opportunities">
            <CustomerOpportunitiesTab customer={c} />
          </TabsContent>

          <TabsContent value="info">
            <Card className="border-slate-200"><CardContent className="p-5">
              <div className="flex justify-end mb-4 gap-2">
                {hasPermission('customer_assign') && <Button size="sm" variant="outline" className="text-indigo-600 hover:text-indigo-700 hover:bg-indigo-50" onClick={() => openAssign(c)}><ArrowRightLeft className="w-3 h-3 mr-1" /> 分配负责人</Button>}
                {hasPermission('customer_edit') && <Button size="sm" variant="outline" onClick={() => openEdit(c)}><Edit className="w-3 h-3 mr-1" /> 编辑</Button>}
                {hasPermission('customer_delete') && <Button size="sm" variant="outline" className="text-red-600 hover:text-red-700 hover:bg-red-50" onClick={() => setDeleteTarget(c)}><Trash2 className="w-3 h-3 mr-1" /> 删除</Button>}
              </div>
              <div className="grid md:grid-cols-2 gap-x-8 gap-y-3 text-sm">
                <div className="flex gap-2"><span className="text-slate-500 w-24 shrink-0">客户编号:</span><span>{c.customer_code}</span></div>
                <div className="flex gap-2"><span className="text-slate-500 w-24 shrink-0">行业类型:</span><span>{industryLabels[c.industry] || c.industry}</span></div>
                <div className="flex gap-2 items-center"><Phone className="w-3 h-3 text-slate-400" /><span>{c.phone}</span></div>
                <div className="flex gap-2 items-center"><Mail className="w-3 h-3 text-slate-400" /><span>{c.email || '-'}</span></div>
                <div className="flex gap-2"><span className="text-slate-500 w-24 shrink-0">微信:</span><span>{c.wechat || '-'}</span></div>
                <div className="flex gap-2"><span className="text-slate-500 w-24 shrink-0">来源:</span><span>{sourceLabels[c.source] || c.source}</span></div>
                <div className="flex gap-2"><span className="text-slate-500 w-24 shrink-0">国家:</span><span>{c.country ? getCountryLabel(c.country) : '-'}</span></div>
                <div className="flex gap-2"><span className="text-slate-500 w-24 shrink-0">州/省:</span><span>{c.country && c.state ? getStateLabel(c.country, c.state) : (c.state || '-')}</span></div>
                <div className="flex gap-2 items-center col-span-2"><MapPin className="w-3 h-3 text-slate-400" /><span>{[c.address, c.city, c.state, c.country].filter(Boolean).join(', ')}</span></div>
                {c.website && <div className="flex gap-2 items-center col-span-2"><Globe className="w-3 h-3 text-slate-400" /><a href={c.website} target="_blank" rel="noreferrer" className="text-blue-600 hover:underline">{c.website}</a></div>}
                <div className="flex gap-2"><span className="text-slate-500 w-24 shrink-0">负责销售:</span><span>{c.sales_person || '-'}</span></div>
                <div className="flex gap-2"><span className="text-slate-500 w-24 shrink-0">平台现状:</span><span>{c.current_platform || '-'}</span></div>
                <div className="flex gap-2 col-span-2"><span className="text-slate-500 w-24 shrink-0">客户已有平台:</span><span>{formatSelectedPlatforms(c.selected_platforms)}</span></div>
                <div className="flex gap-2 col-span-2"><span className="text-slate-500 w-24 shrink-0">套餐归类:</span><span>{parseMultiValue(c.interested_packages).length > 0 ? parseMultiValue(c.interested_packages).map(item => getCustomerPackageLabel(c, item)).join('、') : '-'}{parseMultiValue(c.interested_packages).some(item => getHistoricalPackageLabel(c, item)) && <span className="ml-2 text-xs text-slate-400">（历史：{parseMultiValue(c.interested_packages).map(item => getHistoricalPackageLabel(c, item)).filter(Boolean).join('、')}）</span>}</span></div>
                <div className="flex gap-2"><span className="text-slate-500 w-24 shrink-0">月订单量:</span><span>{c.monthly_orders || 0}</span></div>
                <div className="flex gap-2"><span className="text-slate-500 w-24 shrink-0">已有点餐:</span><span>{c.has_ordering_system ? '是' : '否'}</span></div>
              </div>
              <div className="mt-4 pt-4 border-t border-slate-100">
                <h4 className="text-sm font-medium text-slate-600 mb-2">社交媒体链接</h4>
                <div className="grid md:grid-cols-2 gap-2 text-sm">
                  {c.facebook_link && <a href={c.facebook_link} target="_blank" rel="noreferrer" className="text-blue-600 hover:underline flex items-center gap-1"><Globe className="w-3 h-3" /> Facebook</a>}
                  {c.instagram_link && <a href={c.instagram_link} target="_blank" rel="noreferrer" className="text-pink-600 hover:underline flex items-center gap-1"><Globe className="w-3 h-3" /> Instagram</a>}
                  {c.google_business_link && <a href={c.google_business_link} target="_blank" rel="noreferrer" className="text-green-600 hover:underline flex items-center gap-1"><Globe className="w-3 h-3" /> Google Business</a>}
                  {c.yelp_link && <a href={c.yelp_link} target="_blank" rel="noreferrer" className="text-red-600 hover:underline flex items-center gap-1"><Globe className="w-3 h-3" /> Yelp</a>}
                  {c.tiktok_link && <a href={c.tiktok_link} target="_blank" rel="noreferrer" className="text-slate-800 hover:underline flex items-center gap-1"><Globe className="w-3 h-3" /> TikTok</a>}
                  {!c.facebook_link && !c.instagram_link && !c.google_business_link && !c.yelp_link && !c.tiktok_link && <span className="text-slate-400">暂无</span>}
                </div>
              </div>
              {c.notes && <div className="mt-4 p-3 bg-slate-50 rounded text-slate-600 text-sm">{c.notes}</div>}
            </CardContent></Card>
          </TabsContent>

          {/* ========== CONTACTS TAB ========== */}
          <TabsContent value="contacts">
            <Card className="border-slate-200"><CardContent className="p-5">
              <div className="flex items-center justify-between mb-4">
                <span className="text-sm font-medium text-slate-600 flex items-center gap-2"><Users className="w-4 h-4" /> 联系人信息</span>
                {canManageContacts && <Button size="sm" onClick={() => { setContactForm(emptyContactForm); setEditingContactId(null); setShowContactForm(true); }} className="bg-blue-600 hover:bg-blue-700"><UserPlus className="w-3.5 h-3.5 mr-1" /> 添加联系人</Button>}
              </div>
              {canManageContacts && showContactForm && (
                <div className="mb-4 p-4 border border-blue-200 bg-blue-50/50 rounded-lg space-y-3">
                  <span className="text-sm font-medium text-blue-700">{editingContactId ? '编辑联系人' : '添加联系人'}</span>
                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                    <div><Label className="text-xs">姓名 *</Label><Input value={contactForm.contact_name} onChange={e => setContactForm({ ...contactForm, contact_name: e.target.value })} placeholder="联系人姓名" /></div>
                    <div><Label className="text-xs">手机号</Label><Input value={contactForm.contact_phone} onChange={e => setContactForm({ ...contactForm, contact_phone: e.target.value })} placeholder="手机号码" /></div>
                    <div><Label className="text-xs">角色</Label><NativeSelect value={contactForm.contact_role} onChange={v => setContactForm({ ...contactForm, contact_role: v })} options={Object.entries(contactRoleLabels).map(([k, v]) => ({ value: k, label: v }))} /></div>
                    <div><Label className="text-xs">备注</Label><Input value={contactForm.notes} onChange={e => setContactForm({ ...contactForm, notes: e.target.value })} placeholder="备注信息" /></div>
                  </div>
                  <div className="flex justify-end gap-2">
                    <Button variant="outline" size="sm" onClick={() => { setShowContactForm(false); setEditingContactId(null); }}>取消</Button>
                    <Button size="sm" onClick={handleSaveContact} disabled={savingContact} className="bg-blue-600 hover:bg-blue-700">{savingContact ? '保存中...' : '保存'}</Button>
                  </div>
                </div>
              )}
              {contacts.length === 0 && !showContactForm ? <p className="text-sm text-slate-400 text-center py-8">{canManageContacts ? '暂无联系人信息，点击“添加联系人”开始添加' : '暂无联系人信息'}</p> : (
                <div className="space-y-3">{contacts.map((ct: any) => (
                  <div key={ct.id} className="p-3 bg-slate-50 rounded-lg group">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-3">
                        <div className="w-9 h-9 rounded-full bg-blue-100 flex items-center justify-center text-blue-600 font-medium text-sm">{(ct.contact_name || '?')[0]}</div>
                        <div>
                          <div className="flex items-center gap-2">
                            <span className="font-medium text-sm">{ct.contact_name}</span>
                            <Badge variant="secondary" className="text-xs">{contactRoleLabels[ct.contact_role] || ct.contact_role}</Badge>
                          </div>
                          <div className="flex items-center gap-3 text-xs text-slate-500 mt-0.5">
                            {ct.contact_phone && <span className="flex items-center gap-1"><Phone className="w-3 h-3" />{ct.contact_phone}</span>}
                            {ct.notes && <span>{ct.notes}</span>}
                          </div>
                        </div>
                      </div>
                      {(canManageContacts || canDeleteContacts) && <div className="flex gap-1 opacity-100 transition-opacity md:opacity-0 md:group-focus-within:opacity-100 md:group-hover:opacity-100">
                        {canManageContacts && <Button aria-label={`编辑联系人：${ct.contact_name}`} size="sm" variant="ghost" className="h-11 w-11 p-0 text-slate-500 hover:text-blue-600 md:h-7 md:w-7" onClick={() => { setContactForm({ contact_name: ct.contact_name || '', contact_phone: ct.contact_phone || '', contact_role: ct.contact_role || 'boss', notes: ct.notes || '' }); setEditingContactId(ct.id); setShowContactForm(true); }}><Edit className="w-3.5 h-3.5" /></Button>}
                        {canDeleteContacts && <Button aria-label={`删除联系人：${ct.contact_name}`} size="sm" variant="ghost" className="h-11 w-11 p-0 text-slate-500 hover:text-red-600 md:h-7 md:w-7" onClick={() => setDeleteContactTarget(ct)}><Trash2 className="w-3.5 h-3.5" /></Button>}
                      </div>}
                    </div>
                  </div>
                ))}</div>
              )}
            </CardContent></Card>
          </TabsContent>

          <TabsContent value="followups">
            <Card className="border-slate-200"><CardContent className="p-5">
              <div className="flex items-center justify-between mb-4">
                <span className="text-sm font-medium text-slate-600">跟进记录</span>
                {canCreateFollowUp && <Button size="sm" onClick={() => { setFollowForm(emptyFollowForm); setEditingFollowId(null); setShowFollowForm(true); }} className="bg-blue-600 hover:bg-blue-700"><MessageSquarePlus className="w-3.5 h-3.5 mr-1" /> 新增跟进</Button>}
              </div>
              {showFollowForm && (editingFollowId ? canEditFollowUp : canCreateFollowUp) && (
                <div className="mb-4 p-4 border border-blue-200 bg-blue-50/50 rounded-lg space-y-3">
                  <span className="text-sm font-medium text-blue-700">{editingFollowId ? '编辑跟进' : '新增跟进'}</span>
                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                    <div><Label className="text-xs">方式</Label><NativeSelect value={followForm.contact_method} onChange={v => setFollowForm({ ...followForm, contact_method: v })} options={Object.entries(methodLabels).map(([k, v]) => ({ value: k, label: v }))} /></div>
                    <div><Label className="text-xs">阶段</Label><NativeSelect value={followForm.stage} onChange={v => setFollowForm({ ...followForm, stage: v })} options={Object.entries(stageLabels).map(([k, v]) => ({ value: k, label: v }))} /></div>
                  </div>
                  <div><Label className="text-xs">内容 *</Label><Textarea value={followForm.content} onChange={e => setFollowForm({ ...followForm, content: e.target.value })} rows={3} placeholder="跟进详情..." /></div>
                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                    <div><Label className="text-xs">需求</Label><Input value={followForm.customer_needs} onChange={e => setFollowForm({ ...followForm, customer_needs: e.target.value })} /></div>
                    <div><Label className="text-xs">痛点</Label><Input value={followForm.customer_pain_points} onChange={e => setFollowForm({ ...followForm, customer_pain_points: e.target.value })} /></div>
                  </div>
                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                    <div><Label className="text-xs">成交概率 ({followForm.close_probability}%)</Label><Input type="range" min={0} max={100} step={10} value={followForm.close_probability} onChange={e => setFollowForm({ ...followForm, close_probability: Number(e.target.value) })} /></div>
                    <div><Label className="text-xs">下次跟进</Label><Input type="date" value={followForm.next_follow_date} onChange={e => setFollowForm({ ...followForm, next_follow_date: e.target.value })} /></div>
                  </div>
                  <div className="flex items-center gap-3">
                    <label className="flex items-center gap-2 text-xs"><input type="checkbox" checked={followForm.has_quoted} onChange={e => setFollowForm({ ...followForm, has_quoted: e.target.checked })} className="rounded" />已报价</label>
                    {followForm.has_quoted && <Input placeholder="报价方案" value={followForm.quote_plan} onChange={e => setFollowForm({ ...followForm, quote_plan: e.target.value })} className="flex-1 h-8 text-sm" />}
                  </div>
                  <div className="flex justify-end gap-2">
                    <Button variant="outline" size="sm" onClick={() => { setShowFollowForm(false); setEditingFollowId(null); }}>取消</Button>
                    <Button size="sm" onClick={handleSaveFollow} disabled={savingFollow} className="bg-blue-600 hover:bg-blue-700">{savingFollow ? '保存中...' : '保存'}</Button>
                  </div>
                </div>
              )}
              {followUps.length === 0 && !showFollowForm ? <p className="text-sm text-slate-400 text-center py-8">暂无跟进记录</p> : (
                <>
                  <div className="space-y-4">{paginatedFollowUps.items.map((f: any) => (
                    <div key={f.id} className="border-l-2 border-blue-300 pl-4 py-2 group">
                      <div className="flex items-center gap-2 mb-1">
                        <span className="text-xs text-slate-500">{f.created_at?.slice(0, 16)}</span>
                        <Badge variant="secondary" className="text-xs">{stageLabels[f.stage] || f.stage}</Badge>
                        <span className="text-xs text-slate-400">{f.employee_name} · {methodLabels[f.contact_method] || f.contact_method}</span>
                        {(canEditFollowUp || canDeleteFollowUp) && <div className="ml-auto flex gap-1 opacity-100 transition-opacity md:opacity-0 md:group-focus-within:opacity-100 md:group-hover:opacity-100">
                          {canEditFollowUp && <Button aria-label="编辑跟进记录" size="sm" variant="ghost" className="h-11 w-11 p-0 text-slate-500 hover:text-blue-600 md:h-6 md:w-6" onClick={() => openEditFollow(f)}><Edit className="w-3.5 h-3.5" /></Button>}
                          {canDeleteFollowUp && <Button aria-label="删除跟进记录" size="sm" variant="ghost" className="h-11 w-11 p-0 text-slate-500 hover:text-red-600 md:h-6 md:w-6" onClick={() => setDeleteFollowTarget(f)}><Trash2 className="w-3.5 h-3.5" /></Button>}
                        </div>}
                      </div>
                      <p className="text-sm text-slate-700">{f.content}</p>
                      {f.customer_needs && <p className="text-xs text-slate-500 mt-1">需求: {f.customer_needs}</p>}
                      {f.customer_pain_points && <p className="text-xs text-slate-500 mt-1">痛点: {f.customer_pain_points}</p>}
                      {f.close_probability != null && <p className="text-xs text-slate-500 mt-1">概率: {f.close_probability}%</p>}
                      {f.has_quoted && <p className="text-xs text-green-600 mt-1">已报价: {f.quote_plan}</p>}
                      {f.next_follow_date && <p className="text-xs text-amber-600 mt-1">下次跟进: {f.next_follow_date.slice(0, 10)}</p>}
                    </div>
                  ))}</div>
                  <DetailPaginationFooter pagination={paginatedFollowUps} pageSize={followUpPageSize} onPageChange={setFollowUpPage} onPageSizeChange={setFollowUpPageSize} label="跟进记录" />
                </>
              )}
            </CardContent></Card>
          </TabsContent>

          <TabsContent value="deals">
            <Card className="border-slate-200"><CardContent className="p-5">
              {deals.length === 0 ? <p className="text-sm text-slate-400 text-center py-8">暂无成交记录</p> : (
                <>
                  <div className="space-y-3">{paginatedDeals.items.map((d: any) => (
                    <div key={d.id} className="p-3 bg-slate-50 rounded-lg">
                  <div className="flex items-center justify-between mb-2"><span className="font-medium text-sm">{getPackageClassification(d.package_name).currentLabel}</span>{canViewFinance && d.deal_amount != null && <span className="text-green-600 font-bold">${d.deal_amount}</span>}</div>
                      {getPackageClassification(d.package_name).changed && <p className="mb-2 text-xs text-slate-400">历史成交原名：{getPackageClassification(d.package_name).historicalLabel}</p>}
                      <div className="grid grid-cols-2 gap-1 text-xs text-slate-500">
                        <span>产品: {productLabels[d.product_type] || d.product_type}</span><span>周期: {cycleLabels[d.billing_cycle] || d.billing_cycle}</span>
                        <span>成交日: {d.deal_date?.slice(0, 10)}</span><span>销售: {d.sales_name}</span>
                        {canViewFinance && <span>付款: {d.is_paid ? '✅ 已付' : '❌ 未付'}</span>}<span>交接: {d.is_handed_over ? '✅ 已交接' : '⏳ 待交接'}</span>
                      </div>
                    </div>
                  ))}</div>
                  <DetailPaginationFooter pagination={paginatedDeals} pageSize={dealPageSize} onPageChange={setDealPage} onPageSizeChange={setDealPageSize} label="成交记录" />
                </>
              )}
            </CardContent></Card>
          </TabsContent>

          <TabsContent value="subscriptions">
            <Card className="border-slate-200"><CardContent className="p-5">
              {subscriptions.length === 0 ? <p className="text-sm text-slate-400 text-center py-8">暂无套餐</p> : (
                <>
                  {currentServiceRows.length === 0 ? <p className="text-sm text-slate-400 text-center py-8">暂无当前服务套餐</p> : <>
                    <div className="mb-3"><p className="text-sm font-semibold text-slate-700">当前服务</p><p className="mt-1 text-xs text-slate-400">这里只显示仍需运营、续费或收款的套餐。</p></div>
                    <div className="space-y-3">{paginatedServiceInfo.items.map((s: any) => {
                      const statusView = subscriptionStatusView[s.computed_status] || subscriptionStatusView.active;
                      return <div key={s.id} className={`rounded-lg border p-3 ${statusView.cardClass}`}>
                        <div className="flex items-center justify-between mb-2"><span className="font-medium text-sm">{getPackageClassification(s.package_name).currentLabel}</span><Badge className={statusView.badgeClass}>{subStatusLabels[s.computed_status] || statusView.label}</Badge></div>
                        {getPackageClassification(s.package_name).changed && <p className="mb-2 text-xs text-slate-400">历史服务原名：{getPackageClassification(s.package_name).historicalLabel}</p>}
                        <div className="grid grid-cols-2 gap-1 text-xs text-slate-500">
                          {canViewFinance && <span>价格: ${s.package_price}/{cycleLabels[s.billing_cycle] || s.billing_cycle}</span>}<span>续费方式: {s.auto_renew ? '自动续费' : '手动续费'}</span>
                          <span>开始: {s.start_date?.slice(0, 10)}</span><span>到期: {s.end_date?.slice(0, 10)}</span>
                        </div>
                      </div>;
                    })}</div>
                    <DetailPaginationFooter pagination={paginatedServiceInfo} pageSize={serviceInfoPageSize} onPageChange={setServiceInfoPage} onPageSizeChange={setServiceInfoPageSize} label="当前服务" />
                  </>}
                  {historicalServiceRows.length > 0 && <details className="mt-5 rounded-xl border border-slate-200 bg-slate-50/70">
                    <summary className="cursor-pointer px-4 py-3 text-sm font-semibold text-slate-600">历史套餐（{historicalServiceRows.length}）</summary>
                    <div className="space-y-3 border-t border-slate-200 p-3">{historicalServiceRows.map((s: any) => {
                      const statusView = subscriptionStatusView[s.computed_status] || subscriptionStatusView.stopped;
                      return <div key={s.id} className={`rounded-lg border p-3 ${statusView.cardClass}`}>
                        <div className="flex items-center justify-between gap-2"><span className="font-medium text-sm">{getPackageClassification(s.package_name).currentLabel}</span><Badge className={statusView.badgeClass}>{subStatusLabels[s.computed_status] || statusView.label}</Badge></div>
                        <p className="mt-1 text-xs text-slate-400">历史套餐，不再参与当前服务与续费提醒；历史收款仍保留。</p>
                        <div className="mt-2 grid grid-cols-2 gap-1 text-xs text-slate-500">{canViewFinance && <span>价格: ${s.package_price}/{cycleLabels[s.billing_cycle] || s.billing_cycle}</span>}<span>期间: {s.start_date?.slice(0, 10) || '-'} 至 {s.end_date?.slice(0, 10) || '-'}</span></div>
                      </div>;
                    })}</div>
                  </details>}
                </>
              )}
            </CardContent></Card>
          </TabsContent>

          {canViewFinance && (
            <TabsContent value="payments">
              <Card className="border-slate-200"><CardContent className="p-5">
                {customerFinanceRecordCount === 0 ? <p className="text-sm text-slate-400 text-center py-8">暂无财务记录</p> : (
                  <div className="space-y-5">
                    <div className="grid grid-cols-2 xl:grid-cols-6 gap-3">
                      <div className="rounded-lg bg-slate-50 p-3"><p className="text-xs text-slate-500">累计应收</p><p className="text-lg font-semibold text-slate-800">{formatCurrency(totalAmountDue)}</p></div>
                      <div className="rounded-lg bg-green-50 p-3"><p className="text-xs text-green-700">累计实收</p><p className="text-lg font-semibold text-green-700">{formatCurrency(totalAmountPaid)}</p></div>
                      <div className="rounded-lg bg-blue-50 p-3"><p className="text-xs text-blue-700">管理费收入</p><p className="text-lg font-semibold text-blue-700">{formatCurrency(customerFinanceSummary.managementRevenue)}</p></div>
                      <div className="rounded-lg bg-orange-50 p-3"><p className="text-xs text-orange-700">投流收入</p><p className="text-lg font-semibold text-orange-700">{formatCurrency(customerFinanceSummary.adsRevenue)}</p></div>
                      <div className="rounded-lg bg-amber-50 p-3"><p className="text-xs text-amber-700">USD客户成本</p><p className="text-lg font-semibold text-amber-700">{formatCurrency(customerFinanceSummary.customerCostUsd)}</p></div>
                      <div className={customerFinanceSummary.profitUsd >= 0 ? 'rounded-lg bg-emerald-50 p-3' : 'rounded-lg bg-red-50 p-3'}>
                        <p className={customerFinanceSummary.profitUsd >= 0 ? 'text-xs text-emerald-700' : 'text-xs text-red-700'}>累计利润 USD</p>
                        <p className={customerFinanceSummary.profitUsd >= 0 ? 'text-lg font-semibold text-emerald-700' : 'text-lg font-semibold text-red-700'}>
                          {formatCurrency(customerFinanceSummary.profitUsd)}
                        </p>
                      </div>
                    </div>

                    <div className="rounded-lg border border-blue-100 bg-blue-50/70 p-3 text-xs leading-6 text-blue-800">
                      利润口径：实收 {formatCurrency(customerFinanceSummary.totalRevenue)}
                      {' - '}Stripe手续费 {formatCurrency(customerFinanceSummary.stripeFee)}
                      {' - '}管理费扣点 {formatCurrency(customerFinanceSummary.managementDeduction)}
                      {' - '}投流1%扣点 {formatCurrency(customerFinanceSummary.adsDeduction)}
                      {' - '}USD客户成本 {formatCurrency(customerFinanceSummary.customerCostUsd)}
                      {' = '}利润 {formatCurrency(customerFinanceSummary.profitUsd)}。
                      {customerFinanceSummary.customerCostCny > 0 && (
                        <span className="ml-1 text-amber-700">另有人民币成本 {formatCurrencyByCode(customerFinanceSummary.customerCostCny, 'CNY')}，暂不混入美元利润。</span>
                      )}
                    </div>

                    <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
                      <div className="rounded-lg bg-slate-50 p-3"><p className="text-xs text-slate-500">其他收入</p><p className="text-base font-semibold text-slate-700">{formatCurrency(customerFinanceSummary.otherRevenue)}</p></div>
                      <div className="rounded-lg bg-cyan-50 p-3"><p className="text-xs text-cyan-700">Stripe手续费</p><p className="text-base font-semibold text-cyan-700">{formatCurrency(customerFinanceSummary.stripeFee)}</p></div>
                      <div className="rounded-lg bg-violet-50 p-3"><p className="text-xs text-violet-700">总扣点/手续费</p><p className="text-base font-semibold text-violet-700">{formatCurrency(customerFinanceSummary.feeAndDeduction)}</p></div>
                      <div className="rounded-lg bg-red-50 p-3"><p className="text-xs text-red-700">当前尾款</p><p className="text-base font-semibold text-red-700">{formatCurrency(totalOutstanding)}</p></div>
                    </div>

                    <div>
                      <h4 className="text-sm font-semibold text-slate-700 mb-2">按月收入成本利润</h4>
                      {customerFinanceSummary.monthlyRows.length === 0 ? <p className="text-sm text-slate-400 py-4">暂无按月汇总</p> : (
                        <div className="overflow-x-auto">
                          <table className="w-full text-sm">
                            <thead>
                              <tr className="border-b text-left text-slate-500">
                                <th className="pb-2 font-medium">月份</th>
                                <th className="pb-2 font-medium">收入</th>
                                <th className="pb-2 font-medium">管理费</th>
                                <th className="pb-2 font-medium">投流</th>
                                <th className="pb-2 font-medium">扣点/手续费</th>
                                <th className="pb-2 font-medium">USD成本</th>
                                <th className="pb-2 font-medium">利润</th>
                              </tr>
                            </thead>
                            <tbody>
                              {paginatedFinanceMonthlyRows.items.map(row => (
                                <tr key={row.month} className="border-b border-slate-100">
                                  <td className="py-2 text-slate-600">{row.month}</td>
                                  <td className="py-2 font-medium">{formatCurrency(row.revenue)}</td>
                                  <td className="py-2 text-blue-600">{row.managementRevenue > 0 ? formatCurrency(row.managementRevenue) : '-'}</td>
                                  <td className="py-2 text-orange-600">{row.adsRevenue > 0 ? formatCurrency(row.adsRevenue) : '-'}</td>
                                  <td className="py-2 text-violet-600">{row.feeAndDeduction > 0 ? formatCurrency(row.feeAndDeduction) : '-'}</td>
                                  <td className="py-2 text-amber-600">{row.customerCostUsd > 0 ? formatCurrency(row.customerCostUsd) : '-'}</td>
                                  <td className={row.profitUsd >= 0 ? 'py-2 font-semibold text-emerald-600' : 'py-2 font-semibold text-red-600'}>{formatCurrency(row.profitUsd)}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                          <DetailPaginationFooter pagination={paginatedFinanceMonthlyRows} pageSize={financeMonthlyPageSize} onPageChange={setFinanceMonthlyPage} onPageSizeChange={setFinanceMonthlyPageSize} label="月份" />
                        </div>
                      )}
                    </div>

                    <div>
                      <h4 className="text-sm font-semibold text-slate-700 mb-2">收款记录拆分</h4>
                      {payments.length === 0 ? <p className="text-sm text-slate-400 py-4">暂无收款记录</p> : (
                        <div className="overflow-x-auto">
                          <table className="w-full text-sm">
                            <thead>
                              <tr className="border-b text-left text-slate-500">
                                <th className="pb-2 font-medium">产品</th>
                                <th className="pb-2 font-medium">收入类型</th>
                                <th className="pb-2 font-medium">实收</th>
                                <th className="pb-2 font-medium">拆分</th>
                                <th className="pb-2 font-medium">扣点/手续费</th>
                                <th className="pb-2 font-medium">净收入</th>
                                <th className="pb-2 font-medium">欠款</th>
                                <th className="pb-2 font-medium">方式</th>
                                <th className="pb-2 font-medium">日期</th>
                              </tr>
                            </thead>
                            <tbody>{paginatedFinancePaymentLines.items.map(line => {
                              const p = line.payment;
                              const displayIncomeType = getPaymentDisplayIncomeType(p);
                              return (
                                <tr key={p.id} className="border-b border-slate-100 align-top">
                                  <td className="py-2 max-w-[170px] truncate">{p.product_name}</td>
                                  <td className="py-2">{incomeTypeLabels[displayIncomeType] || displayIncomeType || '-'}</td>
                                  <td className="py-2 text-green-600 font-medium">{formatCurrency(line.amountPaid)}</td>
                                  <td className="py-2">
                                    <div className="space-y-1 text-xs text-slate-600">
                                      <div>管理费: <span className="font-medium text-blue-600">{line.managementAmount > 0 ? formatCurrency(line.managementAmount) : '-'}</span></div>
                                      <div>投流费: <span className="font-medium text-orange-600">{line.adsRechargeAmount > 0 ? formatCurrency(line.adsRechargeAmount) : '-'}</span></div>
                                      {line.otherAmount > 0 && <div>其他: <span className="font-medium">{formatCurrency(line.otherAmount)}</span></div>}
                                    </div>
                                  </td>
                                  <td className="py-2">
                                    <div className="space-y-1 text-xs text-slate-600">
                                      <div>管理扣点: {line.managementDeduction > 0 ? `${formatCurrency(line.managementDeduction)} (${Math.round(line.managementRate * 100)}%)` : '-'}</div>
                                      <div>投流扣点: {line.adsDeduction > 0 ? `${formatCurrency(line.adsDeduction)} (1%)` : '-'}</div>
                                      <div>Stripe: {line.stripeFee > 0 ? formatCurrency(line.stripeFee) : '-'}</div>
                                    </div>
                                  </td>
                                  <td className={line.netBeforeCustomerCost >= 0 ? 'py-2 font-semibold text-emerald-600' : 'py-2 font-semibold text-red-600'}>{formatCurrency(line.netBeforeCustomerCost)}</td>
                                  <td className="py-2">{(p.outstanding_amount || 0) > 0 ? <span className="text-red-600">{formatCurrency(p.outstanding_amount)}</span> : '-'}</td>
                                  <td className="py-2 text-slate-500">
                                    <div>{getPaymentModeLabel(p, payModeLabels)}</div>
                                    <div className="text-xs">{getPaymentMethodLabel(p, payMethodLabels)}</div>
                                  </td>
                                  <td className="py-2 text-slate-500">{p.payment_date?.slice(0, 10)}</td>
                                </tr>
                              );
                            })}</tbody>
                          </table>
                          <DetailPaginationFooter pagination={paginatedFinancePaymentLines} pageSize={financePaymentPageSize} onPageChange={setFinancePaymentPage} onPageSizeChange={setFinancePaymentPageSize} label="收款记录" />
                        </div>
                      )}
                    </div>

                    <div>
                      <h4 className="text-sm font-semibold text-slate-700 mb-2">客户支出记录</h4>
                      {customerExpenses.length === 0 ? <p className="text-sm text-slate-400 py-4">暂无客户支出记录</p> : (
                        <div className="overflow-x-auto"><table className="w-full text-sm"><thead><tr className="border-b text-left text-slate-500"><th className="pb-2 font-medium">费用类型</th><th className="pb-2 font-medium">金额</th><th className="pb-2 font-medium">利润口径</th><th className="pb-2 font-medium">月份</th><th className="pb-2 font-medium">日期</th><th className="pb-2 font-medium">备注</th></tr></thead>
                        <tbody>{paginatedFinanceExpenses.items.map((e: any) => (<tr key={e.id} className="border-b border-slate-100"><td className="py-2">{customerExpenseTypeLabels[e.expense_type] || e.expense_type || '-'}</td><td className="py-2 text-amber-600 font-medium">{formatCurrencyByCode(e.amount, e.currency)}</td><td className="py-2 text-xs text-slate-500">{normalizeCurrencyCode(e.currency) === 'USD' ? '计入USD利润' : '单独记录'}</td><td className="py-2 text-slate-500">{e.expense_month || '-'}</td><td className="py-2 text-slate-500">{e.expense_date?.slice(0, 10) || '-'}</td><td className="py-2 text-slate-500 max-w-[240px] truncate">{e.notes || '-'}</td></tr>))}</tbody></table><DetailPaginationFooter pagination={paginatedFinanceExpenses} pageSize={financeExpensePageSize} onPageChange={setFinanceExpensePage} onPageSizeChange={setFinanceExpensePageSize} label="客户支出记录" /></div>
                      )}
                    </div>
                  </div>
                )}
              </CardContent></Card>
            </TabsContent>
          )}

          <TabsContent value="renewals">
            <Card className="border-slate-200"><CardContent className="p-5">
              {subscriptions.length === 0 ? <p className="text-sm text-slate-400 text-center py-8">暂无续费信息</p> : (
                <>
                  <div className="space-y-3">{paginatedRenewals.items.map((s: any) => {
                    const computedStatus = s.computed_status || computeSubscriptionState(s);
                    const statusView = subscriptionStatusView[computedStatus] || subscriptionStatusView.active;
                    const remainDays = s.days_left ?? getSubscriptionRemainingDays(s);
                    const businessLine = detailBusinessLineMap[s.business_line_id];
                    const linkedProduct = detailProductMap[s.product_id];
                    const linkedPlan = detailPlanMap[s.product_plan_id];
                    const actualPlatforms = (() => {
                      if (!s.selected_platforms) return [];
                      try { const value = JSON.parse(s.selected_platforms); return Array.isArray(value) ? value : parseMultiValue(s.selected_platforms); }
                      catch { return parseMultiValue(s.selected_platforms); }
                    })();
                    return (<div key={s.id} className={`p-3 rounded-lg border ${statusView.cardClass}`}>
                      <div className="flex items-center justify-between mb-2"><span className="font-medium text-sm">{getPackageClassification(s.package_name).currentLabel}</span><Badge className={statusView.badgeClass}>{subStatusLabels[computedStatus] || statusView.label}</Badge></div>
                      {getPackageClassification(s.package_name).changed && <p className="mb-2 text-xs text-slate-400">历史服务原名：{getPackageClassification(s.package_name).historicalLabel}</p>}
                      <div className="mb-2 flex flex-wrap gap-1"><Badge variant="outline" className={businessLine ? 'border-blue-200 bg-white text-blue-700' : 'border-amber-200 bg-white text-amber-700'}>{businessLine?.name || '业务待确认'}</Badge>{linkedProduct && <Badge variant="secondary">{linkedProduct.name}</Badge>}{linkedPlan && linkedPlan.name !== s.package_name && <Badge variant="secondary">{linkedPlan.name}</Badge>}</div>
                      <div className="grid grid-cols-2 gap-1 text-xs text-slate-500">{canViewFinance && <span>金额: {s.package_price == null ? '-' : `${s.package_price} ${linkedPlan?.default_currency || 'USD'}`}</span>}<span>周期: {customerProjectBillingCycles[s.billing_cycle] || s.billing_cycle || '-'}</span><span>到期: {s.end_date?.slice(0, 10) || '-'}</span><span>自动续费: {s.auto_renew ? '是' : '否'}</span><span>续费负责: {s.renewal_person || '-'}</span><span>{canViewFinance ? '下次付款' : '下次续费'}: {s.next_payment_date?.slice(0, 10) || '-'}</span></div>
                      <p className={`mt-2 text-xs ${actualPlatforms.length > 0 ? 'text-slate-600' : 'text-amber-600'}`}>{actualPlatforms.length > 0 ? `实际服务：${formatSelectedPlatforms(actualPlatforms)}` : businessLine?.code === 'managed_service' ? '实际运营平台待确认' : businessLine ? '服务范围按项目确认' : '历史套餐待归类，不影响历史收款'}</p>
                      <div className={`text-xs mt-2 ${
                        remainDays == null
                          ? 'text-slate-400'
                          : remainDays <= 0
                            ? 'text-red-600 font-medium'
                            : remainDays <= 7
                              ? 'text-amber-600 font-medium'
                              : 'text-slate-500'
                      }`}>
                        {remainDays == null
                          ? '剩余: -'
                          : remainDays <= 0
                            ? `已逾期 ${Math.abs(remainDays)} 天`
                            : `剩余 ${remainDays} 天`}
                      </div>
                    </div>);
                  })}</div>
                  <DetailPaginationFooter pagination={paginatedRenewals} pageSize={renewalPageSize} onPageChange={setRenewalPage} onPageSizeChange={setRenewalPageSize} label="续费记录" />
                </>
              )}
            </CardContent></Card>
          </TabsContent>

          <TabsContent value="ai_copy">
            <CustomerAiCopyTab key={`ai-copy-${c.id}`} customer={c} />
          </TabsContent>

          <TabsContent value="materials">
            <CustomerMaterialsTab key={`materials-${c.id}`} customerId={c.id} customerName={c.business_name} />
          </TabsContent>

          <TabsContent value="media">
            <Card className="border-slate-200"><CardContent className="p-5"><MediaAccountsTab customerId={c.id} customerName={c.business_name} /></CardContent></Card>
          </TabsContent>

          <TabsContent value="logs">
            <Card className="border-slate-200"><CardContent className="p-5"><OperationLogsTab customerId={c.id} /></CardContent></Card>
          </TabsContent>
        </Tabs>
        {sharedCustomerDialogs}
      </div>
    );
  }

  // ========== LIST VIEW ==========
  return (
    <div className="app-page customer-360-page space-y-4">
      <div className="customer-360-hero">
        <div className="customer-360-hero-copy">
          <p className="customer-360-kicker">T24 MARKETING · CUSTOMER 360</p>
          <h2>客户管理</h2>
          <p>统一管理客户、服务、合同与续费</p>
        </div>
        <div className="customer-360-hero-actions">
          {!isMobile && <div className="flex flex-wrap items-center gap-1 rounded-xl border border-white/10 bg-white/[0.06] p-1">
            {hasPermission('customer_create') && (
              <Suspense fallback={null}>
                <ImportCustomers existingCustomers={customers} onImportComplete={loadCustomers} />
              </Suspense>
            )}
            {hasPermission('customer_export') && <ExportButton data={filtered.map(c => ({ ...c, industry_label: industryLabels[c.industry] || c.industry, status_label: statusLabels[c.status] || c.status, level_label: levelLabels[c.level] || c.level, source_label: sourceLabels[c.source] || c.source, country_label: c.country ? getCountryLabel(c.country) : '' }))}
            columns={[{ key: 'customer_code', label: '编号' }, { key: 'business_name', label: '商家名称' }, { key: 'contact_name', label: '联系人' }, { key: 'phone', label: '电话' }, { key: 'email', label: '邮箱' }, { key: 'industry_label', label: '行业' }, { key: 'city', label: '城市' }, { key: 'state', label: '州' }, { key: 'country_label', label: '国家' }, { key: 'status_label', label: '状态' }, { key: 'level_label', label: '等级' }, { key: 'source_label', label: '来源' }, { key: 'sales_person', label: '负责销售' }, { key: 'facebook_link', label: 'Facebook' }, { key: 'instagram_link', label: 'Instagram' }, { key: 'google_business_link', label: 'Google Business' }, { key: 'yelp_link', label: 'Yelp' }, { key: 'tiktok_link', label: 'TikTok' }, { key: 'notes', label: '备注' }]}
            filename={`客户列表_${businessToday}`} sheetName="客户列表" />}
            <Button variant="ghost" size="sm" className="h-9 gap-1.5 text-slate-200 hover:bg-white/10 hover:text-white" onClick={() => setShowColPicker(!showColPicker)}><Columns3 className="w-4 h-4" /> 列设置</Button>
            {hasPermission('customer_edit') && (
              <Button
                variant={inlineEditMode ? 'default' : 'ghost'}
                size="sm"
                className={`h-9 gap-1.5 ${inlineEditMode ? 'bg-violet-500 text-white hover:bg-violet-400' : 'text-slate-200 hover:bg-white/10 hover:text-white'}`}
                onClick={() => setInlineEditMode(value => !value)}
              >
                <Edit className="w-4 h-4" /> {inlineEditMode ? '退出快捷编辑' : '快捷编辑'}
              </Button>
            )}
          </div>}
          {hasPermission('customer_create') && <Button onClick={openCreate} className="flex-1 bg-blue-600 shadow-lg shadow-blue-950/30 hover:bg-blue-500 sm:flex-none"><Plus className="w-4 h-4 mr-1" /> 新增客户</Button>}
        </div>
        <div className="customer-360-metrics">
          <div><span className="customer-360-metric-icon is-blue"><Building2 /></span><p>客户总数<strong>{customers.length}</strong><small>当前可访问</small></p></div>
          <div><span className="customer-360-metric-icon is-green"><ShieldCheck /></span><p>已成交<strong>{customerStatusCounts.closed || 0}</strong><small>正式合作客户</small></p></div>
          <div><span className="customer-360-metric-icon is-rose"><Activity /></span><p>需关注<strong>{attentionCustomerCount}</strong><small>暂停与流失</small></p></div>
          <div><span className="customer-360-metric-icon is-cyan"><CalendarClock /></span><p>本月新增<strong>{newCustomersThisMonth}</strong><small>按创建日期统计</small></p></div>
          <div className="customer-360-distribution">
            <p>客户生命周期分布</p>
            <div className="customer-360-distribution-bar" aria-label="客户生命周期分布">
              <span className="is-green" style={{ width: `${customers.length ? ((customerStatusCounts.closed || 0) / customers.length) * 100 : 0}%` }} />
              <span className="is-amber" style={{ width: `${customers.length ? ((customerStatusCounts.following || 0) / customers.length) * 100 : 0}%` }} />
              <span className="is-slate" style={{ width: `${customers.length ? ((customerStatusCounts.paused || 0) / customers.length) * 100 : 0}%` }} />
              <span className="is-rose" style={{ width: `${customers.length ? ((customerStatusCounts.lost || 0) / customers.length) * 100 : 0}%` }} />
            </div>
            <small>成交 {customerStatusCounts.closed || 0} · 跟进 {customerStatusCounts.following || 0} · 暂停 {customerStatusCounts.paused || 0} · 流失 {customerStatusCounts.lost || 0}</small>
          </div>
        </div>
        {isMobile && <p className="relative z-10 mt-3 text-xs text-slate-400">批量导入、敏感数据导出、列设置和快捷编辑请在电脑端处理。</p>}
      </div>

      {showColPicker && (
        <Card className="border-slate-200"><CardContent className="p-3">
          <div className="flex items-center justify-between mb-2"><span className="text-sm font-medium text-slate-600">自定义显示列</span><Button variant="ghost" size="sm" className="h-7 text-xs" onClick={() => setShowColPicker(false)}><X className="w-3 h-3" /></Button></div>
          <div className="flex flex-wrap gap-2">{allColumns.map(col => (<label key={col.key} className="flex items-center gap-1.5 text-xs cursor-pointer"><input type="checkbox" checked={visibleCols.includes(col.key)} onChange={() => toggleCol(col.key)} className="rounded" />{col.label}</label>))}</div>
        </CardContent></Card>
      )}

      <div className="customer-360-segments -mx-1 flex flex-nowrap gap-1.5 overflow-x-auto px-1 pb-1 sm:mx-0 sm:flex-wrap sm:overflow-visible sm:px-1 sm:pb-1">
        <Button variant={filterStatus === 'all' ? 'default' : 'outline'} size="sm" className={`min-h-11 shrink-0 text-xs md:h-8 md:min-h-0 ${filterStatus === 'all' ? 'bg-blue-600 hover:bg-blue-700 text-white' : ''}`} onClick={() => setFilterStatus('all')}>全部 {customers.length}</Button>
        {Object.entries(statusLabels).map(([k, v]) => (
          <Button key={k} variant={filterStatus === k ? 'default' : 'outline'} size="sm" className={`min-h-11 shrink-0 text-xs md:h-8 md:min-h-0 ${filterStatus === k ? 'bg-blue-600 hover:bg-blue-700 text-white' : ''}`} onClick={() => setFilterStatus(k)}>{v} {customers.filter(customer => customer.status === k).length}</Button>
        ))}
      </div>

      {inlineEditMode && (
        <div className="rounded-lg border border-violet-200 bg-violet-50 px-3 py-2 text-xs text-violet-700">
          快捷编辑已开启：行业、状态和等级修改后会立即保存。完成后请退出快捷编辑，避免误操作。
        </div>
      )}

      {!isMobile && isAdmin && selectedCustomerIds.length > 0 && (
        <Card className="border-blue-200 bg-blue-50/70"><CardContent className="flex flex-wrap items-center justify-between gap-3 p-3">
          <div><p className="text-sm font-semibold text-blue-950">已选择 {selectedCustomerIds.length} 位客户</p><p className="mt-1 text-xs text-blue-700">可同时添加、更新或移除团队成员，成员权限逐人设置。</p></div>
          <div className="flex gap-2"><Button variant="outline" onClick={() => setSelectedCustomerIds([])}>取消选择</Button><Button onClick={() => void openBulkAccessManager()}><Users className="mr-2 h-4 w-4" />批量管理团队成员</Button></div>
        </CardContent></Card>
      )}

      <div className="customer-360-toolbar space-y-3">
        <div className="flex gap-2 md:gap-3">
          <div className="relative flex-1"><Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" /><Input placeholder="搜索编号、名称、联系人、电话..." value={search} onChange={e => setSearch(e.target.value)} className="pl-9" /></div>
          <Button variant="outline" size="sm" className="h-11 shrink-0 gap-1.5 md:hidden" onClick={() => setMobileFiltersOpen(true)}>
            <SlidersHorizontal className="h-4 w-4" />筛选{activeFilterCount > 0 && <Badge className="ml-0.5 h-5 min-w-[20px] bg-blue-600 px-1.5 text-xs text-white">{activeFilterCount}</Badge>}
          </Button>
          <NativeSelect value={filterStatus} onChange={setFilterStatus} className="hidden w-[120px] md:block" options={[{ value: 'all', label: '全部状态' }, ...Object.entries(statusLabels).map(([k, v]) => ({ value: k, label: v }))]} />
          <NativeSelect value={filterIndustry} onChange={setFilterIndustry} className="hidden w-[120px] md:block" options={[{ value: 'all', label: '全部行业' }, ...Object.entries(industryLabels).map(([k, v]) => ({ value: k, label: v }))]} />
          <NativeSelect value={filterLevel} onChange={setFilterLevel} className="hidden w-[120px] md:block" options={[{ value: 'all', label: '全部等级' }, ...Object.entries(levelLabels).map(([k, v]) => ({ value: k, label: v }))]} />
          <NativeSelect value={filterSource} onChange={setFilterSource} className="hidden w-[120px] md:block" options={[{ value: 'all', label: '全部来源' }, ...Object.entries(sourceLabels).map(([k, v]) => ({ value: k, label: v }))]} />
          <Button variant={showAdvanced ? 'default' : 'outline'} size="sm" className={`hidden h-10 shrink-0 gap-1.5 md:inline-flex ${showAdvanced ? 'bg-blue-600 hover:bg-blue-700 text-white' : ''}`} onClick={() => setShowAdvanced(!showAdvanced)}>
            <SlidersHorizontal className="w-4 h-4" /> 高级{advFilterCount > 0 && <Badge className="ml-1 bg-white text-blue-600 hover:bg-white h-5 min-w-[20px] px-1.5 text-xs">{advFilterCount}</Badge>}
          </Button>
        </div>
        {showAdvanced && (
          <div className="border-t border-slate-200 pt-3">
            <div className="flex items-center justify-between mb-3"><span className="text-sm font-medium text-slate-600">精确筛选</span>{advFilterCount > 0 && <Button variant="ghost" size="sm" className="h-7 text-xs text-slate-500 hover:text-red-600 gap-1" onClick={() => setAdvFilters(emptyAdvancedFilters)}><X className="w-3 h-3" /> 清除</Button>}</div>
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
              <div><label className="text-xs text-slate-500 mb-1 block">编号</label><Input placeholder="客户编号" value={advFilters.customer_code} onChange={e => setAdvFilters({ ...advFilters, customer_code: e.target.value })} className="h-9 text-sm" /></div>
              <div><label className="text-xs text-slate-500 mb-1 block">商家名称</label><Input placeholder="商家名称" value={advFilters.business_name} onChange={e => setAdvFilters({ ...advFilters, business_name: e.target.value })} className="h-9 text-sm" /></div>
              <div><label className="text-xs text-slate-500 mb-1 block">联系人</label><Input placeholder="联系人" value={advFilters.contact_name} onChange={e => setAdvFilters({ ...advFilters, contact_name: e.target.value })} className="h-9 text-sm" /></div>
              <div><label className="text-xs text-slate-500 mb-1 block">电话</label><Input placeholder="电话" value={advFilters.phone} onChange={e => setAdvFilters({ ...advFilters, phone: e.target.value })} className="h-9 text-sm" /></div>
              <div>
                <label className="text-xs text-slate-500 mb-1 block">行业</label>
                <NativeSelect value={advFilters.industry} onChange={v => setAdvFilters({ ...advFilters, industry: v })} options={[{ value: '', label: '全部行业' }, ...Object.entries(industryLabels).map(([k, v]) => ({ value: k, label: v }))]} />
              </div>
              <div>
                <label className="text-xs text-slate-500 mb-1 block">状态</label>
                <NativeSelect value={advFilters.status} onChange={v => setAdvFilters({ ...advFilters, status: v })} options={[{ value: '', label: '全部状态' }, ...Object.entries(statusLabels).map(([k, v]) => ({ value: k, label: v }))]} />
              </div>
              <div>
                <label className="text-xs text-slate-500 mb-1 block">等级</label>
                <NativeSelect value={advFilters.level} onChange={v => setAdvFilters({ ...advFilters, level: v })} options={[{ value: '', label: '全部等级' }, ...Object.entries(levelLabels).map(([k, v]) => ({ value: k, label: v }))]} />
              </div>
              <div>
                <label className="text-xs text-slate-500 mb-1 block">负责人</label>
                <NativeSelect value={advFilters.sales_person} onChange={v => setAdvFilters({ ...advFilters, sales_person: v })} options={[{ value: '', label: '全部负责人' }, ...salesPersonOptions]} />
              </div>
              <div>
                <label className="text-xs text-slate-500 mb-1 block">来源</label>
                <NativeSelect value={advFilters.source} onChange={v => setAdvFilters({ ...advFilters, source: v })} options={[{ value: '', label: '全部来源' }, ...Object.entries(sourceLabels).map(([k, v]) => ({ value: k, label: v }))]} />
              </div>
              <div><label className="text-xs text-slate-500 mb-1 block">微信</label><Input placeholder="微信" value={advFilters.wechat} onChange={e => setAdvFilters({ ...advFilters, wechat: e.target.value })} className="h-9 text-sm" /></div>
              <div><label className="text-xs text-slate-500 mb-1 block">邮箱</label><Input placeholder="邮箱" value={advFilters.email} onChange={e => setAdvFilters({ ...advFilters, email: e.target.value })} className="h-9 text-sm" /></div>
              <div>
                <label className="text-xs text-slate-500 mb-1 block">国家</label>
                <NativeSelect value={advFilters.country} onChange={v => setAdvFilters({ ...advFilters, country: v, state: '', city: '' })} options={[{ value: '', label: '全部国家' }, ...countries.map(c => ({ value: c.code, label: `${c.labelCn} (${c.label})` }))]} />
              </div>
              <div>
                <label className="text-xs text-slate-500 mb-1 block">州/省</label>
                <NativeSelect value={advFilters.state} onChange={v => setAdvFilters({ ...advFilters, state: v, city: '' })} options={[{ value: '', label: advFilters.country ? '全部州/省' : '请先选择国家' }, ...advStates.map(s => ({ value: s.code, label: s.code }))]} />
              </div>
              <div>
                <label className="text-xs text-slate-500 mb-1 block">城市</label>
                {advCities.length > 0 ? (
                  <NativeSelect value={advFilters.city} onChange={v => setAdvFilters({ ...advFilters, city: v })} options={[{ value: '', label: '全部城市' }, ...advCities.map(ct => ({ value: ct.label, label: ct.label }))]} />
                ) : (
                  <Input placeholder={advFilters.state ? '输入城市名' : '请先选择州/省'} value={advFilters.city} onChange={e => setAdvFilters({ ...advFilters, city: e.target.value })} className="h-9 text-sm" />
                )}
              </div>
            </div>
          </div>
        )}
      </div>

      <Sheet open={mobileFiltersOpen} onOpenChange={setMobileFiltersOpen}>
        <SheetContent side="bottom" className="max-h-[86vh] overflow-y-auto rounded-t-2xl px-5 pb-8 md:hidden">
          <SheetHeader className="text-left">
            <SheetTitle>筛选客户</SheetTitle>
            <SheetDescription>选择常用条件后即可返回客户列表。</SheetDescription>
          </SheetHeader>
          <div className="mt-5 grid gap-4">
            <div><Label className="text-xs text-slate-500">状态</Label><NativeSelect value={filterStatus} onChange={setFilterStatus} className="mt-1 w-full" options={[{ value: 'all', label: '全部状态' }, ...Object.entries(statusLabels).map(([k, v]) => ({ value: k, label: v }))]} /></div>
            <div><Label className="text-xs text-slate-500">行业</Label><NativeSelect value={filterIndustry} onChange={setFilterIndustry} className="mt-1 w-full" options={[{ value: 'all', label: '全部行业' }, ...Object.entries(industryLabels).map(([k, v]) => ({ value: k, label: v }))]} /></div>
            <div className="grid grid-cols-2 gap-3">
              <div><Label className="text-xs text-slate-500">等级</Label><NativeSelect value={filterLevel} onChange={setFilterLevel} className="mt-1 w-full" options={[{ value: 'all', label: '全部等级' }, ...Object.entries(levelLabels).map(([k, v]) => ({ value: k, label: v }))]} /></div>
              <div><Label className="text-xs text-slate-500">来源</Label><NativeSelect value={filterSource} onChange={setFilterSource} className="mt-1 w-full" options={[{ value: 'all', label: '全部来源' }, ...Object.entries(sourceLabels).map(([k, v]) => ({ value: k, label: v }))]} /></div>
            </div>
            <Button variant="outline" onClick={() => { setShowAdvanced(true); setMobileFiltersOpen(false); }}><SlidersHorizontal className="mr-2 h-4 w-4" />打开精确筛选{advFilterCount > 0 ? `（${advFilterCount}）` : ''}</Button>
            {activeFilterCount > 0 && <Button variant="ghost" className="text-slate-600" onClick={() => { setFilterStatus('all'); setFilterIndustry('all'); setFilterLevel('all'); setFilterSource('all'); setAdvFilters(emptyAdvancedFilters); }}>清除全部筛选</Button>}
            <Button className="bg-blue-600 hover:bg-blue-700" onClick={() => setMobileFiltersOpen(false)}>查看 {filtered.length} 位客户</Button>
          </div>
        </SheetContent>
      </Sheet>

      <div className="customer-360-workspace">
        <section className="min-w-0 space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-slate-500">
            <span className="font-medium text-slate-700">客户目录 · 共 {filtered.length} 条{filtered.length !== customers.length ? `（筛选自 ${customers.length} 条）` : ''}</span>
            <span className="inline-flex items-center gap-1.5"><span className={`h-1.5 w-1.5 rounded-full ${loadError ? 'bg-rose-500' : loading ? 'bg-amber-500' : 'bg-emerald-500'}`} />{loading ? '正在同步客户资料' : loadError ? '同步失败，保留上次结果' : `数据更新 ${formatCustomerTimestamp(customersLoadedAt)}`}</span>
          </div>

      <Card className="app-card customer-360-directory"><CardContent className="p-0">
        {loading ? <CustomerListLoadingState />
        : filtered.length === 0 ? <p className="text-center text-slate-400 py-12">暂无匹配的客户</p>
        : (
          <>
          <div className="grid gap-3 p-3 md:hidden">
            {paginatedCustomers.items.map(c => (
              <div key={c.id} className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
                <div className="flex items-start justify-between gap-3">
                  <button type="button" className="min-w-0 text-left" onClick={() => openDetail(c)}>
                    <p className="truncate font-semibold text-blue-700">{c.business_name || '-'}</p>
                    <p className="mt-1 text-xs text-slate-400">{c.customer_code || `客户#${c.id}`}</p>
                  </button>
                  <div className="flex shrink-0 flex-wrap justify-end gap-1">
                    <Badge className={`text-xs ${statusColors[c.status] || ''}`}>{statusLabels[c.status] || c.status || '-'}</Badge>
                    <Badge className={`text-xs ${getLevelColorClass(c.level)}`}>{levelLabels[c.level] || c.level || '-'}</Badge>
                  </div>
                </div>
                <div className="mt-3 grid grid-cols-2 gap-3 text-sm">
                  <div><p className="text-xs text-slate-400">联系人</p><p className="mt-1 text-slate-700">{c.contact_name || '-'}</p></div>
                  <div><p className="text-xs text-slate-400">负责人</p><p className="mt-1 text-slate-700">{c.sales_person || '-'}</p></div>
                  <div><p className="text-xs text-slate-400">行业 / 地区</p><p className="mt-1 text-slate-700">{industryLabels[c.industry] || c.industry || '-'} · {c.state || '-'}</p></div>
                  <div><p className="text-xs text-slate-400">电话</p>{c.phone ? <a className="mt-1 block text-blue-600" href={`tel:${c.phone}`}>{c.phone}</a> : <p className="mt-1 text-slate-400">-</p>}</div>
                </div>
                <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-slate-100 pt-3">
                  <Button size="sm" className="min-h-11 flex-1 bg-blue-600 hover:bg-blue-700 md:min-h-0" onClick={() => openDetail(c)}>查看客户</Button>
                  {(isAdmin || hasPermission('customer_assign') || hasPermission('customer_edit') || hasPermission('customer_delete')) && (
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button size="sm" variant="outline" className="h-11 min-w-11 px-2.5 md:h-8 md:min-w-0" aria-label={`更多客户操作：${c.business_name}`}><MoreHorizontal className="h-4 w-4" /></Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end" className="w-44">
                        {isAdmin && <DropdownMenuItem onSelect={() => { void openAccessManager(c); }}><Users className="mr-2 h-4 w-4" />管理团队成员</DropdownMenuItem>}
                        {hasPermission('customer_assign') && <DropdownMenuItem onSelect={() => openAssign(c)}><ArrowRightLeft className="mr-2 h-4 w-4" />分配负责人</DropdownMenuItem>}
                        {hasPermission('customer_edit') && <DropdownMenuItem onSelect={() => openEdit(c)}><Edit className="mr-2 h-4 w-4" />编辑客户</DropdownMenuItem>}
                        {hasPermission('customer_delete') && <DropdownMenuSeparator />}
                        {hasPermission('customer_delete') && <DropdownMenuItem className="text-red-600 focus:bg-red-50 focus:text-red-700" onSelect={() => setDeleteTarget(c)}><Trash2 className="mr-2 h-4 w-4" />删除客户</DropdownMenuItem>}
                      </DropdownMenuContent>
                    </DropdownMenu>
                  )}
                </div>
              </div>
            ))}
          </div>
          <div className="hidden max-h-[calc(100vh-280px)] overflow-auto md:block"><table className="w-full text-sm"><thead className="sticky top-0 z-10 bg-slate-50 shadow-[0_1px_0_0_rgb(226,232,240)]"><tr className="text-left text-slate-500">
            {isAdmin && <th className="w-12 px-4 py-3"><input type="checkbox" aria-label="选择本页客户" checked={paginatedCustomers.items.length > 0 && paginatedCustomers.items.every(customer => selectedCustomerIds.includes(customer.id))} onChange={event => setSelectedCustomerIds(current => event.target.checked ? Array.from(new Set([...current, ...paginatedCustomers.items.map(customer => customer.id)])) : current.filter(id => !paginatedCustomers.items.some(customer => customer.id === id)))} /></th>}
            {visibleCols.includes('customer_code') && <th className="px-4 py-3 font-medium">编号</th>}
            {visibleCols.includes('business_name') && <th className="px-4 py-3 font-medium">商家名称</th>}
            {visibleCols.includes('contact_name') && <th className="px-4 py-3 font-medium">联系人</th>}
            {visibleCols.includes('phone') && <th className="px-4 py-3 font-medium">电话</th>}
            {visibleCols.includes('state') && <th className="px-4 py-3 font-medium hidden md:table-cell">州/省</th>}
            {visibleCols.includes('country') && <th className="px-4 py-3 font-medium hidden md:table-cell">国家</th>}
            {visibleCols.includes('industry') && <th className="px-4 py-3 font-medium hidden md:table-cell">行业</th>}
            {visibleCols.includes('city') && <th className="px-4 py-3 font-medium hidden md:table-cell">城市</th>}
            {visibleCols.includes('status') && <th className="px-4 py-3 font-medium">状态</th>}
            {visibleCols.includes('level') && <th className="px-4 py-3 font-medium hidden lg:table-cell">等级</th>}
            {visibleCols.includes('sales_person') && <th className="px-4 py-3 font-medium hidden lg:table-cell">负责人</th>}
            {visibleCols.includes('email') && <th className="px-4 py-3 font-medium hidden lg:table-cell">邮箱</th>}
            {visibleCols.includes('wechat') && <th className="px-4 py-3 font-medium hidden lg:table-cell">微信</th>}
            {visibleCols.includes('source') && <th className="px-4 py-3 font-medium hidden lg:table-cell">来源</th>}
            <th className="w-28 px-4 py-3 text-right font-medium">操作</th>
          </tr></thead>
          <tbody>{paginatedCustomers.items.map(c => (
            <tr key={c.id} onMouseEnter={() => setFocusedCustomerId(c.id)} className={`border-b border-slate-100 cursor-pointer transition-colors ${focusedCustomer?.id === c.id ? 'customer-360-row-active' : 'hover:bg-slate-50'}`}>
              {isAdmin && <td className="px-4 py-3" onClick={event => event.stopPropagation()}><input type="checkbox" aria-label={`选择客户 ${c.business_name}`} checked={selectedCustomerIds.includes(c.id)} onChange={event => setSelectedCustomerIds(current => event.target.checked ? [...current, c.id] : current.filter(id => id !== c.id))} /></td>}
              {visibleCols.includes('customer_code') && <td className="px-4 py-3 text-slate-500 text-xs font-mono" onClick={() => openDetail(c)}>{c.customer_code || '-'}</td>}
              {visibleCols.includes('business_name') && <td className="px-4 py-3 font-medium text-blue-600" onClick={() => openDetail(c)}>{c.business_name}</td>}
              {visibleCols.includes('contact_name') && <td className="px-4 py-3" onClick={() => openDetail(c)}>{c.contact_name}</td>}
              {visibleCols.includes('phone') && <td className="px-4 py-3 text-slate-500" onClick={() => openDetail(c)}>{c.phone}</td>}
              {visibleCols.includes('state') && <td className="px-4 py-3 text-slate-500 hidden md:table-cell" onClick={() => openDetail(c)}>{c.state || '-'}</td>}
              {visibleCols.includes('country') && <td className="px-4 py-3 text-slate-500 hidden md:table-cell" onClick={() => openDetail(c)}>{c.country || '-'}</td>}
              {visibleCols.includes('industry') && (
                <td className="px-4 py-3 hidden md:table-cell" onClick={() => !(hasPermission('customer_edit') && inlineEditMode) && openDetail(c)}>
                  {hasPermission('customer_edit') && inlineEditMode ? (
                    <div onClick={e => e.stopPropagation()} onPointerDown={e => e.stopPropagation()}>
                      <select
                        value={c.industry || ''}
                        disabled={inlineSavingKey === `${c.id}:industry`}
                        onChange={e => {
                          const nextValue = e.target.value;
                          void handleInlineCustomerUpdate(
                            c,
                            { industry: nextValue },
                            '行业已更新',
                            `快捷更新行业: ${c.business_name} -> ${industryLabels[nextValue] || nextValue}`,
                          );
                        }}
                        className={inlineSelectClassName}
                      >
                        {buildInlineOptions(c.industry, industryLabels).map(option => (
                          <option key={option.value} value={option.value}>{option.label}</option>
                        ))}
                      </select>
                    </div>
                  ) : (
                    industryLabels[c.industry] || c.industry || '-'
                  )}
                </td>
              )}
              {visibleCols.includes('city') && (
                <td className="px-4 py-3 text-slate-500 hidden md:table-cell" onClick={() => !(hasPermission('customer_edit') && inlineEditMode) && openDetail(c)}>
                  {hasPermission('customer_edit') && inlineEditMode ? (
                    <div onClick={e => e.stopPropagation()} onPointerDown={e => e.stopPropagation()}>
                      {getCitiesForState(c.country || 'US', c.state || '').length > 0 ? (
                        <select
                          value={c.city || ''}
                          disabled={inlineSavingKey === `${c.id}:city`}
                          onChange={e => {
                            void handleInlineCustomerUpdate(
                              c,
                              { city: e.target.value },
                              '城市已更新',
                              `快捷更新城市: ${c.business_name} -> ${e.target.value || '未填写'}`,
                            );
                          }}
                          className={inlineSelectClassName}
                        >
                          <option value="">请选择城市</option>
                          {getCitiesForState(c.country || 'US', c.state || '').map(city => (
                            <option key={city.label} value={city.label}>{city.label}</option>
                          ))}
                        </select>
                      ) : (
                        <Input
                          value={cityDrafts[c.id] ?? c.city ?? ''}
                          disabled={inlineSavingKey === `${c.id}:city`}
                          onChange={e => setCityDrafts(prev => ({ ...prev, [c.id]: e.target.value }))}
                          onBlur={() => { void handleInlineCitySave(c); }}
                          onKeyDown={e => {
                            if (e.key === 'Enter') {
                              e.preventDefault();
                              void handleInlineCitySave(c);
                            }
                          }}
                          className={inlineInputClassName}
                          placeholder="输入城市"
                        />
                      )}
                    </div>
                  ) : (
                    c.city || '-'
                  )}
                </td>
              )}
              {visibleCols.includes('status') && (
                <td className="px-4 py-3" onClick={() => !(hasPermission('customer_edit') && inlineEditMode) && openDetail(c)}>
                  {hasPermission('customer_edit') && inlineEditMode ? (
                    <div onClick={e => e.stopPropagation()} onPointerDown={e => e.stopPropagation()}>
                      <select
                        value={c.status || ''}
                        disabled={inlineSavingKey === `${c.id}:status`}
                        onChange={e => {
                          const nextValue = e.target.value;
                          void handleInlineCustomerUpdate(
                            c,
                            { status: nextValue },
                            '状态已更新',
                            `快捷更新状态: ${c.business_name} -> ${statusLabels[nextValue] || nextValue}`,
                          );
                        }}
                        className={`${inlineSelectClassName} ${statusColors[c.status] || ''}`}
                      >
                        {buildInlineOptions(c.status, statusLabels).map(option => (
                          <option key={option.value} value={option.value}>{option.label}</option>
                        ))}
                      </select>
                    </div>
                  ) : (
                    <Badge className={`text-xs ${statusColors[c.status]}`}>{statusLabels[c.status]}</Badge>
                  )}
                </td>
              )}
              {visibleCols.includes('level') && (
                <td className="px-4 py-3 hidden lg:table-cell" onClick={() => !(hasPermission('customer_edit') && inlineEditMode) && openDetail(c)}>
                  {hasPermission('customer_edit') && inlineEditMode ? (
                    <div onClick={e => e.stopPropagation()} onPointerDown={e => e.stopPropagation()}>
                      <select
                        value={c.level || ''}
                        disabled={inlineSavingKey === `${c.id}:level`}
                        onChange={e => {
                          const nextValue = e.target.value;
                          void handleInlineCustomerUpdate(
                            c,
                            { level: nextValue },
                            '等级已更新',
                            `快捷更新等级: ${c.business_name} -> ${levelLabels[nextValue] || nextValue}`,
                          );
                        }}
                        className={`${inlineSelectClassName} ${getLevelColorClass(c.level)}`}
                      >
                        {buildInlineOptions(c.level, levelLabels).map(option => (
                          <option key={option.value} value={option.value}>{option.label}</option>
                        ))}
                      </select>
                    </div>
                  ) : (
                    <Badge className={`text-xs ${getLevelColorClass(c.level)}`}>{levelLabels[c.level]}</Badge>
                  )}
                </td>
              )}
              {visibleCols.includes('sales_person') && <td className="px-4 py-3 text-slate-500 hidden lg:table-cell" onClick={() => openDetail(c)}>{c.sales_person || '-'}</td>}
              {visibleCols.includes('email') && <td className="px-4 py-3 text-slate-500 hidden lg:table-cell" onClick={() => openDetail(c)}>{c.email || '-'}</td>}
              {visibleCols.includes('wechat') && <td className="px-4 py-3 text-slate-500 hidden lg:table-cell" onClick={() => openDetail(c)}>{c.wechat || '-'}</td>}
              {visibleCols.includes('source') && <td className="px-4 py-3 text-slate-500 hidden lg:table-cell" onClick={() => openDetail(c)}>{sourceLabels[c.source] || c.source}</td>}
              <td className="px-4 py-3">
                <div className="flex items-center justify-end gap-1">
                  <Button size="sm" variant="ghost" className="h-8 px-2 text-xs text-blue-600" onClick={() => openDetail(c)}>查看</Button>
                  {(isAdmin || hasPermission('customer_assign') || hasPermission('customer_edit') || hasPermission('customer_delete')) && (
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button size="sm" variant="ghost" className="h-8 w-8 p-0 text-slate-500 hover:text-blue-600" aria-label={`更多客户操作：${c.business_name}`}><MoreHorizontal className="h-4 w-4" /></Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end" className="w-44">
                        {isAdmin && <DropdownMenuItem onSelect={() => { void openAccessManager(c); }}><Users className="mr-2 h-4 w-4" />管理团队成员</DropdownMenuItem>}
                        {hasPermission('customer_assign') && <DropdownMenuItem onSelect={() => openAssign(c)}><ArrowRightLeft className="mr-2 h-4 w-4" />分配负责人</DropdownMenuItem>}
                        {hasPermission('customer_edit') && <DropdownMenuItem onSelect={() => openEdit(c)}><Edit className="mr-2 h-4 w-4" />编辑客户</DropdownMenuItem>}
                        {hasPermission('customer_delete') && <DropdownMenuSeparator />}
                        {hasPermission('customer_delete') && <DropdownMenuItem className="text-red-600 focus:bg-red-50 focus:text-red-700" onSelect={() => setDeleteTarget(c)}><Trash2 className="mr-2 h-4 w-4" />删除客户</DropdownMenuItem>}
                      </DropdownMenuContent>
                    </DropdownMenu>
                  )}
                </div>
              </td>
            </tr>
          ))}</tbody></table></div>
          </>
        )}
        {filtered.length > 0 && <CustomerPaginationFooter />}
      </CardContent></Card>
        </section>

        <aside className="customer-360-preview" aria-label="客户 360 预览">
          <div className="customer-360-preview-head"><div><p>客户 360°</p><span>基础资料快速预览</span></div><MoreHorizontal className="h-4 w-4 text-slate-400" /></div>
          {focusedCustomer ? (
            <>
              <div className="customer-360-identity">
                <span className="customer-360-avatar">{String(focusedCustomer.business_name || '客').trim().slice(0, 1).toUpperCase()}</span>
                <div className="min-w-0"><h3>{focusedCustomer.business_name || '未命名客户'}</h3><p>#{focusedCustomer.customer_code || focusedCustomer.id}</p></div>
                <Badge className={getLevelColorClass(focusedCustomer.level)}>{levelLabels[focusedCustomer.level] || focusedCustomer.level || '未分级'}</Badge>
              </div>
              <div className="customer-360-contact-grid">
                <div><Phone /><span>电话<strong>{focusedCustomer.phone || '未填写'}</strong></span></div>
                <div><MapPin /><span>地区<strong>{[focusedCustomer.state, focusedCustomer.country].filter(Boolean).join(' · ') || '未填写'}</strong></span></div>
                <div><Building2 /><span>行业<strong>{industryLabels[focusedCustomer.industry] || focusedCustomer.industry || '未填写'}</strong></span></div>
                <div><Users /><span>负责人<strong>{focusedCustomer.sales_person || '未分配'}</strong></span></div>
              </div>
              <div className="customer-360-score-card">
                <div className="customer-360-score" style={{ '--score': `${focusedCustomerCompleteness * 3.6}deg` } as CSSProperties}><span>{focusedCustomerCompleteness}<small>%</small></span></div>
                <div><p>资料完整度</p><strong>{focusedCustomerCompleteness >= 80 ? '基础资料较完整' : focusedCustomerCompleteness >= 50 ? '仍有资料待补充' : '建议优先补齐资料'}</strong><small>根据联系人、地区、行业和负责人等基础字段计算</small></div>
              </div>
              <div className="customer-360-lifecycle">
                <div className="flex items-center justify-between"><p>当前生命周期</p><Badge className={statusColors[focusedCustomer.status] || 'bg-slate-100 text-slate-700'}>{statusLabels[focusedCustomer.status] || focusedCustomer.status || '未设置'}</Badge></div>
                <div className="customer-360-steps"><span className="is-done">建立档案</span><span className={['following', 'closed', 'paused', 'lost'].includes(focusedCustomer.status) ? 'is-done' : ''}>持续跟进</span><span className={focusedCustomer.status === 'closed' ? 'is-done' : ''}>正式合作</span></div>
              </div>
              <div className="customer-360-next-action"><div><CalendarClock /><span><small>建议下一步</small><strong>{focusedCustomerSuggestion}</strong></span></div><p>合同、服务、回款与续费数据请进入客户详情查看，列表页不做推测。</p></div>
              <Button className="w-full bg-blue-600 hover:bg-blue-700" onClick={() => openDetail(focusedCustomer)}>查看客户详情<ChevronRight className="ml-1 h-4 w-4" /></Button>
            </>
          ) : <div className="py-16 text-center text-sm text-slate-400">暂无可预览客户</div>}
        </aside>
      </div>

      {sharedCustomerDialogs}
    </div>
  );
}
