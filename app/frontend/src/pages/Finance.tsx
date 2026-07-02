import { useState, useEffect, useMemo } from 'react';
import { client } from '../lib/api';
import { invokeWithAuth } from '@/lib/tokenStore';
import { useRole } from '../lib/role-context';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Textarea } from '@/components/ui/textarea';
import { Switch } from '@/components/ui/switch';
import { toast } from 'sonner';
import {
  Plus, DollarSign, AlertTriangle, Clock, TrendingUp, TrendingDown,
  Edit, Trash2, CalendarDays, Filter, Receipt, Building2, Users, PieChartIcon,
  ArrowUpRight, ArrowDownRight, Wallet, CheckCircle2
} from 'lucide-react';
import { NativeSelect } from '@/components/ui/native-select';
import {
  LineChart, Line, BarChart, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, PieChart, Pie, Cell, Legend
} from 'recharts';
import ExportButton from '@/components/ExportButton';
import { exportProfitMonthlyCsv, exportProfitMonthlyXlsx } from '../lib/api';
import ConfirmDialog from '@/components/ConfirmDialog';
import { saveRemoteAppConfig } from '../lib/app-config';
import { buildOptionKey, sanitizeDictLabel, serializeDictEntries, useBusinessDicts, useDictConfig } from '../lib/dict-config';
import { logOperation } from '../lib/operation-log-helper';
import {
  AUTO_PAYMENT_METHOD_KEYS,
  getPaymentMethodLabel,
  getPaymentModeLabel,
  inferPaymentModeKey,
  normalizePaymentMethodKey,
  normalizePaymentMethodOptions,
} from '../lib/payment-utils';
import {
  computeSubscriptionStatus,
  decorateEffectiveSubscriptions,
  findMatchingSubscription,
  getSubscriptionRemainingDays,
} from '../lib/subscription-utils';
import { useAutoRefresh } from '../lib/use-auto-refresh';

// ─── Constants ───────────────────────────────────────────────────────
const defaultIncomeTypeLabels: Record<string, string> = {
  management_fee: '管理费', ads_fee: '投流费', management_ads_mixed: '管理费+投流费', website_fee: '网站费',
  ordering_fee: '点餐系统费', renewal_fee: '续费收入', other_income: '其他收入',
};
const INCOME_TYPE_COLORS: Record<string, string> = {
  management_fee: '#3b82f6', ads_fee: '#f59e0b', management_ads_mixed: '#0f766e', website_fee: '#10b981',
  ordering_fee: '#8b5cf6', renewal_fee: '#06b6d4', other_income: '#94a3b8',
};

const CUSTOMER_EXPENSE_COLORS: Record<string, string> = {
  ads_fee: '#f59e0b', website_fee: '#10b981', domain_fee: '#6366f1', hosting_fee: '#0ea5e9',
  design_fee: '#8b5cf6', management_fee: '#3b82f6', other: '#94a3b8',
};

const COMPANY_EXPENSE_COLORS: Record<string, string> = {
  salary: '#ef4444', internet: '#3b82f6', phone: '#10b981', rent: '#f59e0b',
  software: '#8b5cf6', ai_tools: '#6366f1', cloud_services: '#0ea5e9', operations_tools: '#14b8a6',
  recruitment: '#ec4899', travel: '#06b6d4', other_company: '#94a3b8',
};

const PAY_METHOD_COLORS: Record<string, string> = {
  stripe: '#06b6d4',
  check: '#3b82f6',
  zelle: '#8b5cf6',
  apple_cash: '#0f172a',
  venmo: '#2563eb',
  wire: '#f59e0b',
  cash: '#10b981',
  credit_card: '#ef4444',
  other: '#94a3b8',
};
const PAYMENT_MODE_COLORS: Record<string, string> = {
  subscription_auto: '#06b6d4',
  manual_collection: '#64748b',
};
const subStatusColors: Record<string, string> = {
  active: 'bg-green-100 text-green-700', expiring_soon: 'bg-amber-100 text-amber-700',
  renewal_pending: 'bg-cyan-100 text-cyan-700',
  expired: 'bg-red-100 text-red-700', paused: 'bg-slate-100 text-slate-600', lost: 'bg-red-100 text-red-700',
  renewed: 'bg-emerald-100 text-emerald-700',
  upgraded: 'bg-violet-100 text-violet-700',
  stopped: 'bg-slate-100 text-slate-600',
};
const subscriptionStatusFallbackLabels: Record<string, string> = {
  active: '正常',
  expiring_soon: '即将到期',
  renewal_pending: '待扣款确认',
  expired: '已到期',
  renewed: '已续费',
  upgraded: '已升级结束',
  stopped: '停止续费',
  paused: '暂停',
  lost: '流失',
};

const PIE_COLORS = ['#3b82f6', '#ef4444', '#f59e0b', '#10b981', '#8b5cf6', '#ec4899', '#06b6d4', '#f97316', '#6366f1'];
const financeTabValues = new Set(['overview', 'customer_profit', 'receivables', 'income', 'customer_expense', 'company_expense', 'subscriptions', 'charts', 'monthly_detail']);
type DateFilterMode = 'all' | 'today' | 'this_month' | 'last_month' | 'custom';
type FinancePageKey = 'customer_profit' | 'receivables' | 'income' | 'customer_expense' | 'company_expense' | 'subscriptions' | 'monthly_detail';
type PaginationResult<T> = {
  items: T[];
  page: number;
  pageSize: number;
  total: number;
  totalPages: number;
  start: number;
  end: number;
};
const PAGE_SIZE_OPTIONS = [20, 50, 100];
const defaultFinancePages: Record<FinancePageKey, number> = {
  customer_profit: 1,
  receivables: 1,
  income: 1,
  customer_expense: 1,
  company_expense: 1,
  subscriptions: 1,
  monthly_detail: 1,
};

const formatDateOnlyLocal = (date: Date) => (
  `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
);

const getMonthRange = (baseDate: Date, offset = 0) => {
  const start = new Date(baseDate.getFullYear(), baseDate.getMonth() + offset, 1);
  const end = new Date(baseDate.getFullYear(), baseDate.getMonth() + offset + 1, 0);
  return { start: formatDateOnlyLocal(start), end: formatDateOnlyLocal(end) };
};

const getDateFilterRange = (
  mode: DateFilterMode,
  customStart: string,
  customEnd: string,
  baseDate = new Date(),
) => {
  if (mode === 'today') {
    const today = formatDateOnlyLocal(baseDate);
    return { start: today, end: today };
  }
  if (mode === 'this_month') return getMonthRange(baseDate, 0);
  if (mode === 'last_month') return getMonthRange(baseDate, -1);
  if (mode === 'custom' && (customStart || customEnd)) {
    return { start: customStart, end: customEnd };
  }
  return null;
};

const getMonthKeysInRange = (start: string, end: string) => {
  if (!start && !end) return [];
  const fallback = start || end;
  const startDate = new Date(`${start || `${fallback.slice(0, 7)}-01`}T00:00:00`);
  const endDate = new Date(`${end || start || fallback}T00:00:00`);
  if (Number.isNaN(startDate.getTime()) || Number.isNaN(endDate.getTime())) return [];
  const cursor = new Date(startDate.getFullYear(), startDate.getMonth(), 1);
  const last = new Date(endDate.getFullYear(), endDate.getMonth(), 1);
  const months: string[] = [];
  while (cursor <= last) {
    months.push(`${cursor.getFullYear()}-${String(cursor.getMonth() + 1).padStart(2, '0')}`);
    cursor.setMonth(cursor.getMonth() + 1);
  }
  return months;
};

const isDateInRange = (value: string | null | undefined, range: { start: string; end: string } | null) => {
  if (!range) return true;
  const date = value?.slice(0, 10);
  if (!date) return false;
  if (range.start && date < range.start) return false;
  if (range.end && date > range.end) return false;
  return true;
};

const isMonthInRange = (value: string | null | undefined, range: { start: string; end: string } | null) => {
  if (!range) return true;
  const month = value?.slice(0, 7);
  if (!/^\d{4}-\d{2}$/.test(month || '')) return false;
  const startMonth = range.start?.slice(0, 7);
  const endMonth = range.end?.slice(0, 7);
  if (startMonth && month! < startMonth) return false;
  if (endMonth && month! > endMonth) return false;
  return true;
};

const paginateList = <T,>(items: T[], page: number, pageSize: number): PaginationResult<T> => {
  const total = items.length;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const safePage = Math.min(Math.max(page || 1, 1), totalPages);
  const offset = (safePage - 1) * pageSize;
  const pageItems = items.slice(offset, offset + pageSize);
  return {
    items: pageItems,
    page: safePage,
    pageSize,
    total,
    totalPages,
    start: total === 0 ? 0 : offset + 1,
    end: Math.min(offset + pageSize, total),
  };
};

const pickColorByKey = (key: string, palette: string[], fixedColors?: Record<string, string>) => {
  if (fixedColors?.[key]) return fixedColors[key];
  let hash = 0;
  for (let i = 0; i < key.length; i += 1) {
    hash = ((hash << 5) - hash) + key.charCodeAt(i);
    hash |= 0;
  }
  return palette[Math.abs(hash) % palette.length] || '#94a3b8';
};

// ─── Helper: format currency ─────────────────────────────────────────
const fmt = (n: number) => `$${n.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 2 })}`;
const fmtRMB = (n: number) => `¥${n.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 2 })}`;
type CurrencyCode = 'USD' | 'CNY';
const currencyLabels: Record<CurrencyCode, string> = { USD: '美元 USD', CNY: '人民币 CNY' };
const normalizeCurrency = (currency?: string | null, fallback: CurrencyCode = 'USD'): CurrencyCode => (
  currency === 'CNY' || currency === 'USD' ? currency : fallback
);
const getCustomerExpenseCurrency = (expense: any): CurrencyCode => normalizeCurrency(expense?.currency, 'USD');
const getCompanyExpenseCurrency = (expense: any): CurrencyCode => normalizeCurrency(expense?.currency, 'CNY');
const formatMoney = (amount: number, currency: CurrencyCode) => (currency === 'CNY' ? fmtRMB(amount) : fmt(amount));
const roundMoney = (amount: number) => Math.round(Number(amount || 0) * 100) / 100;

const MANAGEMENT_FEE_KEY = 'management_fee';
const ADS_FEE_KEY = 'ads_fee';
const MIXED_MANAGEMENT_ADS_KEY = 'management_ads_mixed';
const PROTECTED_INCOME_TYPE_KEYS = new Set([MANAGEMENT_FEE_KEY, ADS_FEE_KEY, MIXED_MANAGEMENT_ADS_KEY]);
const ADS_RECHARGE_DEDUCTION_RATE = 0.01;
const STRIPE_PLATFORM_FEE_RATE = 0.029;
const STRIPE_PLATFORM_FEE_FIXED = 0.3;

const toMoneyNumber = (value: any) => {
  const amount = Number(value);
  return Number.isFinite(amount) ? amount : 0;
};

const getStoredMoney = (value: any): number | null => {
  if (value === null || value === undefined || value === '') return null;
  const amount = Number(value);
  return Number.isFinite(amount) ? roundMoney(amount) : null;
};

type MonthlyFinanceBucket = {
  revenue: number;
  managementRevenue: number;
  adsRevenue: number;
  stripePlatformFee: number;
  customerCost: number;
  operatingCostUsd: number;
  cost: number;
};

const getDeductionRate = (rates: Record<string, number>, ym: string) => (
  typeof rates[ym] === 'number' ? rates[ym] : 0.15
);

const getOrCreateMonthlyFinanceBucket = (
  map: Record<string, MonthlyFinanceBucket>,
  ym: string,
): MonthlyFinanceBucket => {
  if (!map[ym]) {
    map[ym] = { revenue: 0, managementRevenue: 0, adsRevenue: 0, stripePlatformFee: 0, customerCost: 0, operatingCostUsd: 0, cost: 0 };
  }
  return map[ym];
};

const isStripeSubscriptionPayment = (payment: any) => {
  const method = normalizePaymentMethodKey(payment?.payment_method);
  return method === 'stripe' || (inferPaymentModeKey(payment || {}) === 'subscription_auto' && !payment?.payment_method);
};

const calculateStripePlatformFeeFromValues = (
  amountPaid: number,
  paymentMode?: string | null,
  paymentMethod?: string | null,
) => {
  const amount = toMoneyNumber(amountPaid);
  const method = normalizePaymentMethodKey(paymentMethod);
  const isStripe = method === 'stripe' || (paymentMode === 'subscription_auto' && !paymentMethod);
  if (amount <= 0 || !isStripe) return 0;
  return roundMoney(amount * STRIPE_PLATFORM_FEE_RATE + STRIPE_PLATFORM_FEE_FIXED);
};

const calculateStripePlatformFee = (payment: any) => {
  const stored = getStoredMoney(payment?.stripe_fee_amount);
  if (stored !== null) return stored;
  const amount = toMoneyNumber(payment?.amount_paid);
  if (amount <= 0 || !isStripeSubscriptionPayment(payment)) return 0;
  return calculateStripePlatformFeeFromValues(amount, payment?.payment_mode, payment?.payment_method);
};

const getManagementRevenueAmount = (payment: any) => {
  const stored = getStoredMoney(payment?.management_amount);
  if (stored !== null) return stored;
  return payment?.income_type === MANAGEMENT_FEE_KEY ? toMoneyNumber(payment?.amount_paid) : 0;
};

const getAdsRechargeAmount = (payment: any) => {
  const stored = getStoredMoney(payment?.ads_recharge_amount);
  if (stored !== null) return stored;
  return payment?.income_type === ADS_FEE_KEY ? toMoneyNumber(payment?.amount_paid) : 0;
};

const isManagementAdsMixedPayment = (payment: any) => (
  getManagementRevenueAmount(payment) > 0 && getAdsRechargeAmount(payment) > 0
);

const getPaymentDisplayIncomeType = (payment: any) => (
  isManagementAdsMixedPayment(payment) ? MIXED_MANAGEMENT_ADS_KEY : (payment?.income_type || 'other_income')
);

const inferSubscriptionIncomeType = (packageName?: string | null) => {
  const normalized = String(packageName || '').toLowerCase();
  if (normalized.includes('广告') || normalized.includes('ads')) return ADS_FEE_KEY;
  if (normalized.includes('点餐') || normalized.includes('ordering')) return 'ordering_fee';
  if (normalized.includes('网站') || normalized.includes('官网') || normalized.includes('website')) return 'website_fee';
  return MANAGEMENT_FEE_KEY;
};

const buildMonthlyFinanceBuckets = (paymentsList: any[], customerExpenses: any[], companyExpenseList: any[] = []) => {
  const map: Record<string, MonthlyFinanceBucket> = {};

  paymentsList.forEach((payment) => {
    const ym = (payment.payment_date || '').slice(0, 7);
    if (!/^\d{4}-\d{2}$/.test(ym)) return;
    const bucket = getOrCreateMonthlyFinanceBucket(map, ym);
    const amount = toMoneyNumber(payment.amount_paid);
    const stripeFee = calculateStripePlatformFee(payment);
    bucket.revenue += amount;
    bucket.stripePlatformFee += stripeFee;
    bucket.cost += stripeFee;
    bucket.managementRevenue += getManagementRevenueAmount(payment);
    bucket.adsRevenue += getAdsRechargeAmount(payment);
  });

  customerExpenses.forEach((expense) => {
    const ym = (expense.expense_month || '').slice(0, 7);
    if (!/^\d{4}-\d{2}$/.test(ym)) return;
    if (normalizeCurrency(expense.currency, 'USD') !== 'USD') return;
    const bucket = getOrCreateMonthlyFinanceBucket(map, ym);
    const amount = toMoneyNumber(expense.amount);
    bucket.customerCost += amount;
    bucket.cost += amount;
  });

  companyExpenseList.forEach((expense) => {
    const ym = (expense.expense_month || '').slice(0, 7);
    if (!/^\d{4}-\d{2}$/.test(ym)) return;
    if (getCompanyExpenseCurrency(expense) !== 'USD') return;
    const bucket = getOrCreateMonthlyFinanceBucket(map, ym);
    const amount = Number(expense.amount || 0);
    bucket.operatingCostUsd += amount;
    bucket.cost += amount;
  });

  return map;
};

const calculateMonthlyProfit = (bucket: MonthlyFinanceBucket, rate: number) => {
  const managementDeduction = bucket.managementRevenue * rate;
  const adsDeduction = bucket.adsRevenue * ADS_RECHARGE_DEDUCTION_RATE;
  const deductionAmount = managementDeduction + adsDeduction;
  return {
    managementDeduction,
    adsDeduction,
    deductionAmount,
    effectiveRate: bucket.revenue > 0 ? deductionAmount / bucket.revenue : 0,
    profit: bucket.revenue - deductionAmount - bucket.cost,
  };
};


// ─── Helper: convert date string to ISO datetime ─────────────────────
const toISODatetime = (dateStr: string | null | undefined): string | null => {
  if (!dateStr) return null;
  // If already an ISO datetime string, return as-is
  if (dateStr.includes('T')) return dateStr;
  // Convert "YYYY-MM-DD" to full ISO datetime
  try {
    return new Date(dateStr + 'T00:00:00.000Z').toISOString();
  } catch {
    return null;
  }
};

const toDateOnly = (value?: string | null) => {
  if (!value) return '';
  if (/^\d{4}-\d{2}-\d{2}/.test(value)) return value.slice(0, 10);
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '' : date.toISOString().slice(0, 10);
};

const addBillingCycle = (dateStr: string, cycle?: string | null) => {
  const base = new Date(`${dateStr}T00:00:00.000Z`);
  if (Number.isNaN(base.getTime())) return '';
  const next = new Date(base);
  switch (cycle) {
    case 'annual':
      next.setUTCFullYear(next.getUTCFullYear() + 1);
      break;
    case 'semi_annual':
      next.setUTCMonth(next.getUTCMonth() + 6);
      break;
    case 'quarterly':
      next.setUTCMonth(next.getUTCMonth() + 3);
      break;
    case 'monthly':
    default:
      next.setUTCMonth(next.getUTCMonth() + 1);
      break;
  }
  return next.toISOString().slice(0, 10);
};

const getDaysBetweenToday = (dateStr?: string | null) => {
  if (!dateStr) return null;
  const date = new Date(`${dateStr.slice(0, 10)}T00:00:00`);
  if (Number.isNaN(date.getTime())) return null;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return Math.floor((today.getTime() - date.getTime()) / (1000 * 60 * 60 * 24));
};

const parsePackageLabels = (value?: string | null) => (
  (value || '')
    .split(/[、,，]/)
    .map(item => item.trim())
    .filter(Boolean)
);

const parseMultiValue = (value?: string | null) => (
  (value || '')
    .split(',')
    .map(item => item.trim())
    .filter(Boolean)
);

// ─── Helper: safe query ─────────────────────────────────────────────
const safeQuery = async (queryFn: () => Promise<any>): Promise<any[]> => {
  try {
    const res = await queryFn();
    return res?.data?.items || [];
  } catch (err) {
    console.error('Query failed:', err);
    return [];
  }
};

export default function Finance() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const { isAdmin, hasPermission, employee } = useRole();
  const dictConfig = useDictConfig();
  const {
    paymentModes: payModeLabels,
    paymentMethods: payMethodLabels,
    billingCycles: cycleLabels,
    incomeTypes: configuredIncomeTypeLabels,
    customerExpenseTypes: customerExpenseTypeLabels,
    companyExpenseTypes: companyExpenseTypeLabels,
    subscriptionStatuses: subStatusLabels,
    customerPackages: customerPackageLabels,
  } = useBusinessDicts();
  const operatorName = employee?.name || '管理员';
  const incomeTypeLabels = useMemo(() => {
    const configured = Object.keys(configuredIncomeTypeLabels).length > 0 ? configuredIncomeTypeLabels : defaultIncomeTypeLabels;
    return {
      [MANAGEMENT_FEE_KEY]: defaultIncomeTypeLabels[MANAGEMENT_FEE_KEY],
      [ADS_FEE_KEY]: defaultIncomeTypeLabels[ADS_FEE_KEY],
      [MIXED_MANAGEMENT_ADS_KEY]: defaultIncomeTypeLabels[MIXED_MANAGEMENT_ADS_KEY],
      ...configured,
    };
  }, [configuredIncomeTypeLabels]);
  const canManageCustomerExpenseTypes = isAdmin || hasPermission('settings_edit');
  const canManageCompanyExpenseTypes = isAdmin || hasPermission('settings_edit');
  const canManageIncomeTypes = isAdmin || hasPermission('settings_edit');
  const canManageCustomerPackages = isAdmin || hasPermission('settings_edit');
  const incomeTypeOptions = useMemo(
    () => Object.entries(incomeTypeLabels).map(([value, label]) => ({ value, label })),
    [incomeTypeLabels],
  );
  const customerExpenseTypeOptions = useMemo(
    () => Object.entries(customerExpenseTypeLabels).map(([value, label]) => ({ value, label })),
    [customerExpenseTypeLabels],
  );
  const defaultCustomerExpenseType = customerExpenseTypeOptions[0]?.value || 'ads_fee';
  const companyExpenseTypeOptions = useMemo(
    () => Object.entries(companyExpenseTypeLabels).map(([value, label]) => ({ value, label })),
    [companyExpenseTypeLabels],
  );
  const defaultCompanyExpenseType = companyExpenseTypeOptions[0]?.value || 'salary';
  const normalizeFinanceTab = (tab?: string | null) => (tab && financeTabValues.has(tab) ? tab : 'overview');
  const [activeFinanceTab, setActiveFinanceTab] = useState(() => normalizeFinanceTab(searchParams.get('tab')));
  const [exporting, setExporting] = useState(false);
  const doExport = async (fmt: 'csv'|'xlsx') => {
    try {
      setExporting(true);
      const today = new Date();
      let start = '';
      let end = '';

      const selectedRange = getDateFilterRange(dateFilterMode, filterStartDate, filterEndDate, today);
      if (selectedRange) {
        start = selectedRange.start;
        end = selectedRange.end;
      } else {
        const dates: string[] = [];
        payments.forEach((p: any) => { const d = p.payment_date?.slice(0, 10); if (d) dates.push(d); });
        expenses.forEach((e: any) => { const ym = e.expense_month; if (ym && /^\d{4}-\d{2}$/.test(ym)) dates.push(`${ym}-01`); });
        if (dates.length > 0) {
          dates.sort();
          start = dates[0];
          end = dates[dates.length - 1];
        } else {
          const y = today.getFullYear();
          const m = String(today.getMonth() + 1).padStart(2, '0');
          start = `${y}-${m}-01`;
          end = new Date(y, today.getMonth() + 1, 0).toISOString().slice(0, 10);
        }
      }

      const fn = fmt === 'csv' ? exportProfitMonthlyCsv : exportProfitMonthlyXlsx;
      const res = await fn({ start, end });
      const blob = res.data as Blob;
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      const nn = (s: string) => s.replace(/-/g, '');
      a.download = fmt === 'csv'
        ? `profit-monthly_${nn(start)}-${nn(end)}.csv`
        : `profit-monthly_${nn(start)}-${nn(end)}.xlsx`;
      a.click();
      window.URL.revokeObjectURL(url);
    } catch (e: any) {
      const detail = e?.data?.detail || e?.message || '导出失败';
      console.error('export failed', e);
      toast.error(detail);
    } finally {
      setExporting(false);
    }
  };;
  // ─── State ───────────────────────────────────────────────────────
  const [payments, setPayments] = useState<any[]>([]);
  const [subscriptions, setSubscriptions] = useState<any[]>([]);
  const [customers, setCustomers] = useState<any[]>([]);
  const [deals, setDeals] = useState<any[]>([]);
  const [expenses, setExpenses] = useState<any[]>([]);
  const [companyExpenses, setCompanyExpenses] = useState<any[]>([]);
  const [deductionRates, setDeductionRates] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(true);

  // Payment form
  const [showPaymentForm, setShowPaymentForm] = useState(false);
  const [saving, setSaving] = useState(false);
  const [editingPayId, setEditingPayId] = useState<number | null>(null);
  const emptyPayForm = {
    customer_id: '', product_names: [] as string[], income_type: 'management_fee',
    amount_due: '', amount_paid: '', payment_mode: 'manual_collection', payment_method: 'zelle', billing_cycle: 'monthly',
    management_amount: '', ads_recharge_amount: '', transaction_reference: '',
    coverage_start: '', coverage_end: '', has_invoice: false, sync_to_deal: false, notes: '',
  };
  const [payForm, setPayForm] = useState(emptyPayForm);
  const paymentIncomeTypeOptions = useMemo(() => {
    const options = [...incomeTypeOptions];
    if (payForm.income_type && !incomeTypeLabels[payForm.income_type]) {
      options.unshift({ value: payForm.income_type, label: `${payForm.income_type}（历史类型）` });
    }
    return options;
  }, [incomeTypeOptions, incomeTypeLabels, payForm.income_type]);
  const [showPaymentPackageManager, setShowPaymentPackageManager] = useState(false);
  const [paymentPackageDrafts, setPaymentPackageDrafts] = useState<Array<{ key: string; label: string }>>([]);
  const [newPaymentPackageName, setNewPaymentPackageName] = useState('');
  const [savingPaymentPackages, setSavingPaymentPackages] = useState(false);
  const [showIncomeTypeManager, setShowIncomeTypeManager] = useState(false);
  const [incomeTypeDrafts, setIncomeTypeDrafts] = useState<Array<{ key: string; label: string }>>([]);
  const [newIncomeTypeName, setNewIncomeTypeName] = useState('');
  const [savingIncomeTypes, setSavingIncomeTypes] = useState(false);

  // Customer expense form
  const [showExpenseForm, setShowExpenseForm] = useState(false);
  const [editingExpenseId, setEditingExpenseId] = useState<number | null>(null);
  const [savingExpense, setSavingExpense] = useState(false);
  const [expenseMonth, setExpenseMonth] = useState(() => {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
  });
  const emptyExpenseForm = { customer_id: '', expense_type: defaultCustomerExpenseType, currency: 'USD' as CurrencyCode, amount: '', expense_month: expenseMonth, notes: '' };
  const [expenseForm, setExpenseForm] = useState(emptyExpenseForm);
  const [showCustomerExpenseTypeManager, setShowCustomerExpenseTypeManager] = useState(false);
  const [newCustomerExpenseTypeName, setNewCustomerExpenseTypeName] = useState('');
  const [customerExpenseTypeDrafts, setCustomerExpenseTypeDrafts] = useState<Array<{ key: string; label: string }>>([]);
  const [savingCustomerExpenseTypes, setSavingCustomerExpenseTypes] = useState(false);

  // Company expense form
  const [showCompanyExpenseForm, setShowCompanyExpenseForm] = useState(false);
  const [editingCompanyExpenseId, setEditingCompanyExpenseId] = useState<number | null>(null);
  const [savingCompanyExpense, setSavingCompanyExpense] = useState(false);
  const [companyExpenseMonth, setCompanyExpenseMonth] = useState(() => {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
  });
  const emptyCompanyExpenseForm = { category: defaultCompanyExpenseType, currency: 'USD' as CurrencyCode, amount: '', expense_month: companyExpenseMonth, expense_date: '', notes: '' };
  const [companyExpenseForm, setCompanyExpenseForm] = useState(emptyCompanyExpenseForm);
  const [companyExpenseCurrencyFilter, setCompanyExpenseCurrencyFilter] = useState<'all' | CurrencyCode>('all');
  const [showCompanyExpenseTypeManager, setShowCompanyExpenseTypeManager] = useState(false);
  const [newCompanyExpenseTypeName, setNewCompanyExpenseTypeName] = useState('');
  const [companyExpenseTypeDrafts, setCompanyExpenseTypeDrafts] = useState<Array<{ key: string; label: string }>>([]);
  const [savingCompanyExpenseTypes, setSavingCompanyExpenseTypes] = useState(false);

  // Delete targets
  const [deleteTarget, setDeleteTarget] = useState<{ type: 'payment' | 'subscription'; item: any } | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [confirmingRenewalId, setConfirmingRenewalId] = useState<number | null>(null);
  const [updatingSubscriptionId, setUpdatingSubscriptionId] = useState<number | null>(null);
  const [deleteExpenseTarget, setDeleteExpenseTarget] = useState<any>(null);
  const [deletingExpense, setDeletingExpense] = useState(false);
  const [deleteCompanyExpenseTarget, setDeleteCompanyExpenseTarget] = useState<any>(null);
  const [deletingCompanyExpense, setDeletingCompanyExpense] = useState(false);

  // Date filter
  const [dateFilterMode, setDateFilterMode] = useState<DateFilterMode>('all');
  const [filterStartDate, setFilterStartDate] = useState('');
  const [filterEndDate, setFilterEndDate] = useState('');
  const [pageSize, setPageSize] = useState(20);
  const [financePages, setFinancePages] = useState<Record<FinancePageKey, number>>({ ...defaultFinancePages });
  const activeDateRange = useMemo(
    () => getDateFilterRange(dateFilterMode, filterStartDate, filterEndDate),
    [dateFilterMode, filterStartDate, filterEndDate],
  );

  useEffect(() => {
    setFinancePages({ ...defaultFinancePages });
  }, [dateFilterMode, filterStartDate, filterEndDate, expenseMonth, companyExpenseMonth, companyExpenseCurrencyFilter, pageSize]);

  // ─── Load Data (resilient - each query independent) ───────────────

  useEffect(() => { loadData(); }, []);

  const loadData = async () => {
    try {
      // Load each data source independently so one failure doesn't block others
      const [pItems, sItems, cItems, dItems, eItems, ceItems] = await Promise.all([
        safeQuery(() => client.entities.payments.queryAll({ limit: 1000, sort: '-payment_date' })),
        safeQuery(() => client.entities.subscriptions.query({ limit: 1000, sort: '-end_date' })),
        safeQuery(() => client.entities.customers.query({ limit: 1000 })),
        safeQuery(() => client.entities.deals.query({ limit: 1000, sort: '-deal_date' })),
        safeQuery(() => client.entities.expenses.queryAll({ limit: 1000, sort: '-created_at' })),
        safeQuery(() => client.entities.company_expenses.queryAll({ limit: 1000, sort: '-created_at' })),
      ]);
      setPayments(pItems);
      setSubscriptions(decorateEffectiveSubscriptions(sItems));
      setCustomers(cItems);
      setDeals(dItems);
      setExpenses(eItems);
      setCompanyExpenses(ceItems);
      try {
        const months = new Set<string>();
        [...pItems, ...eItems, ...ceItems].forEach((it: any) => {
          const ym = (it.payment_date || it.expense_month || it.created_at || '').slice(0,7);
          if (/^\d{4}-\d{2}$/.test(ym)) months.add(ym);
        });
        if (months.size > 0) {
          const arr = Array.from(months).sort();
          const start = arr[0];
          const end = arr[arr.length - 1];
          let res;
          try {
            res = await invokeWithAuth({ url: '/api/v1/deductions-monthly/ensure', method: 'POST', data: { months: arr } });
          } catch (ensureErr) {
            console.warn('ensure rates failed, fallback to list', ensureErr);
            res = await invokeWithAuth({ url: '/api/v1/deductions-monthly', method: 'GET', data: { start, end } });
          }
          const map: Record<string, number> = {};
          (res.data || []).forEach((r: any) => { map[r.year_month] = r.rate; });
          setDeductionRates(map);
        }
      } catch (e) { console.warn('load rates failed', e); }
    } catch (err) {
      console.error('loadData error:', err);
    } finally {
      setLoading(false);
    }
  };

  useAutoRefresh(loadData, { intervalMs: 30000 });

  useEffect(() => {
    if (!editingPayId && !incomeTypeLabels[payForm.income_type] && payForm.income_type !== MANAGEMENT_FEE_KEY) {
      setPayForm(prev => ({ ...prev, income_type: MANAGEMENT_FEE_KEY, management_amount: '', ads_recharge_amount: '' }));
    }
  }, [editingPayId, payForm.income_type, incomeTypeLabels]);

  useEffect(() => {
    const managementAmount = toMoneyNumber(payForm.management_amount);
    const adsRechargeAmount = toMoneyNumber(payForm.ads_recharge_amount);
    if (managementAmount > 0 && adsRechargeAmount > 0 && payForm.income_type !== MIXED_MANAGEMENT_ADS_KEY) {
      setPayForm(prev => ({ ...prev, income_type: MIXED_MANAGEMENT_ADS_KEY }));
    }
  }, [payForm.management_amount, payForm.ads_recharge_amount, payForm.income_type]);

  const openIncomeTypeManager = () => {
    setIncomeTypeDrafts(Object.entries(incomeTypeLabels).map(([key, label]) => ({ key, label })));
    setNewIncomeTypeName('');
    setShowIncomeTypeManager(true);
  };

  const handleAddIncomeTypeDraft = () => {
    const label = sanitizeDictLabel(newIncomeTypeName).replace(/\s+/g, ' ').trim();
    if (!label) {
      toast.error('请输入收入类型名称');
      return;
    }
    if (incomeTypeDrafts.some(item => item.label.trim() === label)) {
      toast.error('该收入类型已存在');
      return;
    }
    let key = buildOptionKey(label);
    while (incomeTypeDrafts.some(item => item.key === key)) {
      key = `${key}_${Date.now()}`;
    }
    setIncomeTypeDrafts(prev => [...prev, { key, label }]);
    setNewIncomeTypeName('');
  };

  const handleRemoveIncomeTypeDraft = (key: string) => {
    if (PROTECTED_INCOME_TYPE_KEYS.has(key)) {
      toast.error('管理费、投流费、管理费+投流费关联财务扣点规则，不能删除');
      return;
    }
    if (incomeTypeDrafts.length <= PROTECTED_INCOME_TYPE_KEYS.size) {
      toast.error('至少保留管理费、投流费、管理费+投流费');
      return;
    }
    const remaining = incomeTypeDrafts.filter(item => item.key !== key);
    setIncomeTypeDrafts(remaining);
    if (payForm.income_type === key) {
      setPayForm(prev => ({ ...prev, income_type: MANAGEMENT_FEE_KEY, management_amount: '', ads_recharge_amount: '' }));
    }
  };

  const handleSaveIncomeTypes = async () => {
    const normalizedEntries = incomeTypeDrafts.reduce<Record<string, string>>((acc, item) => {
      const label = sanitizeDictLabel(item.label).replace(/\s+/g, ' ').trim();
      if (label) {
        acc[item.key] = label;
      }
      return acc;
    }, {});
    if (!normalizedEntries[MANAGEMENT_FEE_KEY] || !normalizedEntries[ADS_FEE_KEY] || !normalizedEntries[MIXED_MANAGEMENT_ADS_KEY]) {
      toast.error('必须保留管理费、投流费、管理费+投流费三个系统收入类型');
      return;
    }
    const labels = Object.values(normalizedEntries);
    if (labels.length === 0) {
      toast.error('请至少保留一个收入类型');
      return;
    }
    if (new Set(labels.map(label => label.toLowerCase())).size !== labels.length) {
      toast.error('收入类型名称不能重复');
      return;
    }

    setSavingIncomeTypes(true);
    try {
      const nextDictConfig = {
        ...dictConfig,
        incomeTypes: serializeDictEntries(normalizedEntries),
      };
      await saveRemoteAppConfig('dict_config', nextDictConfig);
      if (!normalizedEntries[payForm.income_type]) {
        setPayForm(prev => ({ ...prev, income_type: MANAGEMENT_FEE_KEY, management_amount: '', ads_recharge_amount: '' }));
      }
      setShowIncomeTypeManager(false);
      setNewIncomeTypeName('');
      toast.success('收入类型已更新');
    } catch (err: any) {
      const detail = err?.data?.detail || err?.message || '保存收入类型失败';
      toast.error(detail);
    } finally {
      setSavingIncomeTypes(false);
    }
  };

  useEffect(() => {
    if (!customerExpenseTypeLabels[expenseForm.expense_type] && expenseForm.expense_type !== defaultCustomerExpenseType) {
      setExpenseForm(prev => ({ ...prev, expense_type: defaultCustomerExpenseType }));
    }
  }, [defaultCustomerExpenseType, expenseForm.expense_type, customerExpenseTypeLabels]);

  const openCustomerExpenseTypeManager = () => {
    setCustomerExpenseTypeDrafts(Object.entries(customerExpenseTypeLabels).map(([key, label]) => ({ key, label })));
    setNewCustomerExpenseTypeName('');
    setShowCustomerExpenseTypeManager(true);
  };

  const handleAddCustomerExpenseTypeDraft = () => {
    const label = newCustomerExpenseTypeName.trim();
    if (!label) {
      toast.error('请输入客户支出类型名称');
      return;
    }
    if (customerExpenseTypeDrafts.some(item => item.label.trim() === label)) {
      toast.error('该客户支出类型已存在');
      return;
    }
    let key = buildOptionKey(label);
    while (customerExpenseTypeDrafts.some(item => item.key === key)) {
      key = `${key}_${Date.now()}`;
    }
    setCustomerExpenseTypeDrafts(prev => [...prev, { key, label }]);
    setNewCustomerExpenseTypeName('');
  };

  const handleRemoveCustomerExpenseTypeDraft = (key: string) => {
    if (customerExpenseTypeDrafts.length <= 1) {
      toast.error('至少保留一个客户支出类型');
      return;
    }
    if (expenses.some(item => item.expense_type === key)) {
      toast.error('该客户支出类型已有记录在使用，请先调整历史记录后再删除');
      return;
    }
    const remaining = customerExpenseTypeDrafts.filter(item => item.key !== key);
    setCustomerExpenseTypeDrafts(remaining);
    if (expenseForm.expense_type === key) {
      setExpenseForm(prev => ({ ...prev, expense_type: remaining[0]?.key || defaultCustomerExpenseType }));
    }
  };

  const handleSaveCustomerExpenseTypes = async () => {
    const normalizedEntries = customerExpenseTypeDrafts.reduce<Record<string, string>>((acc, item) => {
      const label = item.label.trim();
      if (label) {
        acc[item.key] = label;
      }
      return acc;
    }, {});
    const labels = Object.values(normalizedEntries);
    if (labels.length === 0) {
      toast.error('请至少保留一个客户支出类型');
      return;
    }
    if (new Set(labels).size !== labels.length) {
      toast.error('客户支出类型名称不能重复');
      return;
    }

    setSavingCustomerExpenseTypes(true);
    try {
      const nextDictConfig = {
        ...dictConfig,
        customerExpenseTypes: serializeDictEntries(normalizedEntries),
      };
      await saveRemoteAppConfig('dict_config', nextDictConfig);
      const fallbackKey = Object.keys(normalizedEntries)[0] || defaultCustomerExpenseType;
      if (!normalizedEntries[expenseForm.expense_type]) {
        setExpenseForm(prev => ({ ...prev, expense_type: fallbackKey }));
      }
      setShowCustomerExpenseTypeManager(false);
      setNewCustomerExpenseTypeName('');
      toast.success('客户支出类型已更新');
    } catch (err: any) {
      const detail = err?.data?.detail || err?.message || '保存客户支出类型失败';
      toast.error(detail);
    } finally {
      setSavingCustomerExpenseTypes(false);
    }
  };

  useEffect(() => {
    if (!companyExpenseTypeLabels[companyExpenseForm.category]) {
      setCompanyExpenseForm(prev => ({ ...prev, category: defaultCompanyExpenseType }));
    }
  }, [companyExpenseForm.category, companyExpenseTypeLabels, defaultCompanyExpenseType]);

  const openCompanyExpenseTypeManager = () => {
    setCompanyExpenseTypeDrafts(Object.entries(companyExpenseTypeLabels).map(([key, label]) => ({ key, label })));
    setNewCompanyExpenseTypeName('');
    setShowCompanyExpenseTypeManager(true);
  };

  const handleAddCompanyExpenseTypeDraft = () => {
    const label = newCompanyExpenseTypeName.trim();
    if (!label) {
      toast.error('请输入支出类型名称');
      return;
    }
    if (companyExpenseTypeDrafts.some(item => item.label.trim() === label)) {
      toast.error('该支出类型已存在');
      return;
    }
    let key = buildOptionKey(label);
    while (companyExpenseTypeDrafts.some(item => item.key === key)) {
      key = `${key}_${Date.now()}`;
    }
    setCompanyExpenseTypeDrafts(prev => [...prev, { key, label }]);
    setNewCompanyExpenseTypeName('');
  };

  const handleRemoveCompanyExpenseTypeDraft = (key: string) => {
    if (companyExpenseTypeDrafts.length <= 1) {
      toast.error('至少保留一个运营支出类型');
      return;
    }
    if (companyExpenses.some(item => item.category === key)) {
      toast.error('该支出类型已有记录在使用，请先调整历史记录后再删除');
      return;
    }
    const remaining = companyExpenseTypeDrafts.filter(item => item.key !== key);
    setCompanyExpenseTypeDrafts(remaining);
    if (companyExpenseForm.category === key) {
      setCompanyExpenseForm(prev => ({ ...prev, category: remaining[0]?.key || defaultCompanyExpenseType }));
    }
  };

  const handleSaveCompanyExpenseTypes = async () => {
    const normalizedEntries = companyExpenseTypeDrafts.reduce<Record<string, string>>((acc, item) => {
      const label = item.label.trim();
      if (label) {
        acc[item.key] = label;
      }
      return acc;
    }, {});
    const labels = Object.values(normalizedEntries);
    if (labels.length === 0) {
      toast.error('请至少保留一个运营支出类型');
      return;
    }
    if (new Set(labels).size !== labels.length) {
      toast.error('运营支出类型名称不能重复');
      return;
    }

    setSavingCompanyExpenseTypes(true);
    try {
      const nextDictConfig = {
        ...dictConfig,
        companyExpenseTypes: serializeDictEntries(normalizedEntries),
      };
      await saveRemoteAppConfig('dict_config', nextDictConfig);
      const fallbackKey = Object.keys(normalizedEntries)[0] || defaultCompanyExpenseType;
      if (!normalizedEntries[companyExpenseForm.category]) {
        setCompanyExpenseForm(prev => ({ ...prev, category: fallbackKey }));
      }
      setShowCompanyExpenseTypeManager(false);
      setNewCompanyExpenseTypeName('');
      toast.success('运营支出类型已更新');
    } catch (err: any) {
      const detail = err?.data?.detail || err?.message || '保存运营支出类型失败';
      toast.error(detail);
    } finally {
      setSavingCompanyExpenseTypes(false);
    }
  };

  const openPaymentPackageManager = () => {
    setPaymentPackageDrafts(Object.entries(customerPackageLabels).map(([key, label]) => ({ key, label })));
    setNewPaymentPackageName('');
    setShowPaymentPackageManager(true);
  };

  const handleAddPaymentPackageDraft = () => {
    const label = newPaymentPackageName.trim();
    if (!label) {
      toast.error('请输入套餐名称');
      return;
    }
    if (paymentPackageDrafts.some(item => item.label.trim() === label)) {
      toast.error('该套餐已存在');
      return;
    }
    let key = buildOptionKey(label);
    while (paymentPackageDrafts.some(item => item.key === key)) {
      key = `${key}_${Date.now()}`;
    }
    setPaymentPackageDrafts(prev => [...prev, { key, label }]);
    setNewPaymentPackageName('');
  };

  const handleRemovePaymentPackageDraft = (key: string) => {
    if (paymentPackageDrafts.length <= 1) {
      toast.error('至少保留一个套餐');
      return;
    }
    const label = paymentPackageDrafts.find(item => item.key === key)?.label || customerPackageLabels[key];
    const usedInCustomers = customers.some(customer => parseMultiValue(customer.interested_packages).includes(key));
    const usedInDeals = !!label && deals.some(item => parsePackageLabels(item.package_name).includes(label));
    const usedInPayments = !!label && payments.some(item => parsePackageLabels(item.product_name).includes(label));
    const usedInSubscriptions = !!label && subscriptions.some(item => parsePackageLabels(item.package_name).includes(label));
    if (usedInCustomers || usedInDeals || usedInPayments || usedInSubscriptions) {
      toast.error('该套餐已有客户、成交或财务记录在使用，请先调整历史数据后再删除');
      return;
    }
    const remaining = paymentPackageDrafts.filter(item => item.key !== key);
    const remainingLabels = new Set(remaining.map(item => item.label));
    setPaymentPackageDrafts(remaining);
    setPayForm(prev => ({
      ...prev,
      product_names: prev.product_names.filter(item => remainingLabels.has(item)),
    }));
  };

  const handleSavePaymentPackages = async () => {
    const normalizedEntries = paymentPackageDrafts.reduce<Record<string, string>>((acc, item) => {
      const label = item.label.trim();
      if (label) {
        acc[item.key] = label;
      }
      return acc;
    }, {});
    const labels = Object.values(normalizedEntries);
    if (labels.length === 0) {
      toast.error('请至少保留一个套餐');
      return;
    }
    if (new Set(labels).size !== labels.length) {
      toast.error('套餐名称不能重复');
      return;
    }

    setSavingPaymentPackages(true);
    try {
      const nextDictConfig = {
        ...dictConfig,
        customerPackages: serializeDictEntries(normalizedEntries),
      };
      await saveRemoteAppConfig('dict_config', nextDictConfig);
      const allowedLabels = new Set(Object.values(normalizedEntries));
      setPayForm(prev => ({
        ...prev,
        product_names: prev.product_names.filter(item => allowedLabels.has(item)),
      }));
      setShowPaymentPackageManager(false);
      setNewPaymentPackageName('');
      toast.success('收款套餐已更新');
    } catch (err: any) {
      const detail = err?.data?.detail || err?.message || '保存套餐失败';
      toast.error(detail);
    } finally {
      setSavingPaymentPackages(false);
    }
  };

  const paymentModeOptions = useMemo(
    () => Object.entries(payModeLabels).map(([value, label]) => ({ value, label })),
    [payModeLabels],
  );

  const paymentMethodOptions = useMemo(
    () => normalizePaymentMethodOptions(payMethodLabels),
    [payMethodLabels],
  );

  const paymentPackageOptions = useMemo(() => {
    const seen = new Set<string>();
    const options: Array<{ value: string; label: string }> = [];
    Object.values(customerPackageLabels).forEach((label) => {
      if (!label || seen.has(label)) return;
      seen.add(label);
      options.push({ value: label, label });
    });
    payForm.product_names.forEach((label) => {
      if (!label || seen.has(label)) return;
      seen.add(label);
      options.push({ value: label, label });
    });
    return options;
  }, [customerPackageLabels, payForm.product_names]);

  const manualPaymentMethodOptions = useMemo(
    () => paymentMethodOptions.filter((option) => !AUTO_PAYMENT_METHOD_KEYS.has(option.value)),
    [paymentMethodOptions],
  );

  const defaultSubscriptionPaymentMethod = paymentMethodOptions.find((option) => AUTO_PAYMENT_METHOD_KEYS.has(option.value))?.value || 'stripe';
  const defaultManualPaymentMethod = manualPaymentMethodOptions.find((option) => option.value === 'zelle')?.value
    || manualPaymentMethodOptions[0]?.value
    || 'other';

  const availablePaymentMethodOptions = useMemo(() => (
    payForm.payment_mode === 'subscription_auto'
      ? paymentMethodOptions.filter((option) => AUTO_PAYMENT_METHOD_KEYS.has(option.value))
      : manualPaymentMethodOptions
  ), [manualPaymentMethodOptions, payForm.payment_mode, paymentMethodOptions]);

  useEffect(() => {
    const allowedValues = new Set(availablePaymentMethodOptions.map((option) => option.value));
    const normalizedCurrentMethod = normalizePaymentMethodKey(payForm.payment_method);
    if (allowedValues.has(normalizedCurrentMethod)) {
      if (normalizedCurrentMethod !== payForm.payment_method) {
        setPayForm((prev) => ({ ...prev, payment_method: normalizedCurrentMethod }));
      }
      return;
    }
    setPayForm((prev) => ({
      ...prev,
      payment_method: prev.payment_mode === 'subscription_auto' ? defaultSubscriptionPaymentMethod : defaultManualPaymentMethod,
    }));
  }, [
    availablePaymentMethodOptions,
    defaultManualPaymentMethod,
    defaultSubscriptionPaymentMethod,
    payForm.payment_method,
    payForm.payment_mode,
  ]);

  // ─── Filtering ───────────────────────────────────────────────────
  const filterByDate = (items: any[], dateField: string) => {
    if (!activeDateRange) return items;
    return items.filter(i => isDateInRange(i[dateField], activeDateRange));
  };

  const filteredPayments = filterByDate(payments, 'payment_date');
  const filteredSubscriptions = useMemo(() => {
    if (!activeDateRange) return subscriptions;
    return subscriptions.filter(s => (
      isDateInRange(s.start_date || s.created_at, activeDateRange)
      || isDateInRange(s.next_payment_date || s.end_date, activeDateRange)
    ));
  }, [subscriptions, activeDateRange]);

  const filteredExpenses = expenses.filter(e => (
    activeDateRange ? isMonthInRange(e.expense_month, activeDateRange) : (!expenseMonth || e.expense_month === expenseMonth)
  ));
  const filteredCompanyExpenses = companyExpenses.filter(e => {
    const matchesMonth = activeDateRange
      ? isMonthInRange(e.expense_month, activeDateRange)
      : (!companyExpenseMonth || e.expense_month === companyExpenseMonth);
    const matchesCurrency = companyExpenseCurrencyFilter === 'all' || getCompanyExpenseCurrency(e) === companyExpenseCurrencyFilter;
    return matchesMonth && matchesCurrency;
  });
  const summaryCustomerExpenses = useMemo(
    () => (activeDateRange ? expenses.filter(e => isMonthInRange(e.expense_month, activeDateRange)) : expenses),
    [activeDateRange, expenses],
  );
  const summaryCompanyExpenses = useMemo(
    () => (activeDateRange ? companyExpenses.filter(e => isMonthInRange(e.expense_month, activeDateRange)) : companyExpenses),
    [activeDateRange, companyExpenses],
  );
  const paginatedPayments = useMemo(
    () => paginateList(filteredPayments, financePages.income, pageSize),
    [filteredPayments, financePages.income, pageSize],
  );
  const paginatedExpenses = useMemo(
    () => paginateList(filteredExpenses, financePages.customer_expense, pageSize),
    [filteredExpenses, financePages.customer_expense, pageSize],
  );
  const paginatedCompanyExpenses = useMemo(
    () => paginateList(filteredCompanyExpenses, financePages.company_expense, pageSize),
    [filteredCompanyExpenses, financePages.company_expense, pageSize],
  );
  const paginatedSubscriptions = useMemo(
    () => paginateList(filteredSubscriptions, financePages.subscriptions, pageSize),
    [filteredSubscriptions, financePages.subscriptions, pageSize],
  );
  const monthlyFinanceBuckets = useMemo(() => buildMonthlyFinanceBuckets(payments, expenses, companyExpenses), [payments, expenses, companyExpenses]);

  // ─── Stats ───────────────────────────────────────────────────────
  const now = new Date();
  const currentMonthKey = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;
  const summaryFinanceBuckets = useMemo(
    () => buildMonthlyFinanceBuckets(filteredPayments, summaryCustomerExpenses, summaryCompanyExpenses),
    [filteredPayments, summaryCustomerExpenses, summaryCompanyExpenses],
  );
  const summaryFinance = useMemo(() => (
    Object.values(summaryFinanceBuckets).reduce<MonthlyFinanceBucket>((acc, bucket) => ({
      revenue: roundMoney(acc.revenue + bucket.revenue),
      managementRevenue: roundMoney(acc.managementRevenue + bucket.managementRevenue),
      adsRevenue: roundMoney(acc.adsRevenue + bucket.adsRevenue),
      stripePlatformFee: roundMoney(acc.stripePlatformFee + bucket.stripePlatformFee),
      customerCost: roundMoney(acc.customerCost + bucket.customerCost),
      operatingCostUsd: roundMoney(acc.operatingCostUsd + bucket.operatingCostUsd),
      cost: roundMoney(acc.cost + bucket.cost),
    }), { revenue: 0, managementRevenue: 0, adsRevenue: 0, stripePlatformFee: 0, customerCost: 0, operatingCostUsd: 0, cost: 0 })
  ), [summaryFinanceBuckets]);
  const summaryProfitUsd = useMemo(() => roundMoney(
    Object.entries(summaryFinanceBuckets).reduce((sum, [monthKey, bucket]) => (
      sum + calculateMonthlyProfit(bucket, getDeductionRate(deductionRates, monthKey)).profit
    ), 0),
  ), [deductionRates, summaryFinanceBuckets]);
  const summaryCompanyExpenseCny = useMemo(() => roundMoney(
    summaryCompanyExpenses
      .filter(e => getCompanyExpenseCurrency(e) === 'CNY')
      .reduce((s, e) => s + Number(e.amount || 0), 0),
  ), [summaryCompanyExpenses]);
  const summaryPeriodLabel = dateFilterMode === 'all'
    ? '总'
    : dateFilterMode === 'today'
      ? '今日'
      : dateFilterMode === 'last_month'
        ? '上月'
        : dateFilterMode === 'custom'
          ? '筛选期'
          : '本月';
  const totalOutstanding = payments.reduce((s, p) => s + (p.outstanding_amount || 0), 0);
  const renewalPendingSubs = subscriptions.filter(s => s.status === 'renewal_pending').length;
  const expiringSubs = subscriptions.filter(s => s.status === 'expiring_soon' || s.status === 'expired' || s.status === 'renewal_pending');
  const activeSubs = subscriptions.filter(s => s.status === 'active').length;

  // Expense summaries
  const totalCustomerExpense = filteredExpenses
    .filter(e => getCustomerExpenseCurrency(e) === 'USD')
    .reduce((s, e) => s + (e.amount || 0), 0);
  const customerExpenseByType = useMemo(() => {
    const map: Record<string, number> = {};
    filteredExpenses
      .filter(e => getCustomerExpenseCurrency(e) === 'USD')
      .forEach(e => { map[e.expense_type] = (map[e.expense_type] || 0) + (e.amount || 0); });
    return Object.entries(map).map(([type, amount]) => ({
      type, name: customerExpenseTypeLabels[type] || type, amount: Math.round(amount * 100) / 100,
    })).sort((a, b) => b.amount - a.amount);
  }, [filteredExpenses]);

  const totalCompanyExpenseByCurrency = useMemo(() => ({
    USD: roundMoney(filteredCompanyExpenses.filter(e => getCompanyExpenseCurrency(e) === 'USD').reduce((s, e) => s + Number(e.amount || 0), 0)),
    CNY: roundMoney(filteredCompanyExpenses.filter(e => getCompanyExpenseCurrency(e) === 'CNY').reduce((s, e) => s + Number(e.amount || 0), 0)),
  }), [filteredCompanyExpenses]);
  const companyExpenseByType = useMemo(() => {
    const map: Record<string, { type: string; currency: CurrencyCode; amount: number }> = {};
    filteredCompanyExpenses.forEach(e => {
      const currency = getCompanyExpenseCurrency(e);
      const type = e.category || 'other_company';
      const key = `${currency}:${type}`;
      map[key] = map[key] || { type, currency, amount: 0 };
      map[key].amount += Number(e.amount || 0);
    });
    return Object.values(map).map(item => ({
      ...item,
      name: companyExpenseTypeLabels[item.type] || item.type,
      amount: roundMoney(item.amount),
    })).sort((a, b) => a.currency.localeCompare(b.currency) || b.amount - a.amount);
  }, [companyExpenseTypeLabels, filteredCompanyExpenses]);

  // ─── Chart Data ──────────────────────────────────────────────────
  const chartPayments = filteredPayments;
  const chartExpenses = useMemo(
    () => (activeDateRange ? expenses.filter(e => isMonthInRange(e.expense_month, activeDateRange)) : expenses),
    [activeDateRange, expenses],
  );
  const chartCompanyExpenses = useMemo(
    () => (activeDateRange ? companyExpenses.filter(e => isMonthInRange(e.expense_month, activeDateRange)) : companyExpenses),
    [activeDateRange, companyExpenses],
  );
  const chartMonthlyFinanceBuckets = useMemo(
    () => (activeDateRange
      ? buildMonthlyFinanceBuckets(chartPayments, chartExpenses, chartCompanyExpenses)
      : monthlyFinanceBuckets),
    [activeDateRange, chartPayments, chartExpenses, chartCompanyExpenses, monthlyFinanceBuckets],
  );
  const chartMonthKeys = useMemo(() => {
    if (activeDateRange) return getMonthKeysInRange(activeDateRange.start, activeDateRange.end);
    const months: string[] = [];
    for (let i = 11; i >= 0; i--) {
      const d = new Date(now.getFullYear(), now.getMonth() - i, 1);
      months.push(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`);
    }
    return months;
  }, [activeDateRange, now]);

  const monthlyTrendData = useMemo(() => {
    const months: { key: string; label: string; income: number; customerExp: number; stripeFee: number; companyExpUsd: number; companyExpCny: number; profitUsd: number }[] = [];
    chartMonthKeys.forEach((key) => {
      const monthNumber = Number(key.slice(5, 7));
      const label = `${monthNumber}月`;
      const bucket = chartMonthlyFinanceBuckets[key] || { revenue: 0, managementRevenue: 0, adsRevenue: 0, stripePlatformFee: 0, customerCost: 0, operatingCostUsd: 0, cost: 0 };
      const income = bucket.revenue;
      const custExp = bucket.customerCost; // USD
      const stripeFee = bucket.stripePlatformFee;
      const compExpUsd = bucket.operatingCostUsd; // USD operating costs
      const compExpCny = chartCompanyExpenses
        .filter(e => e.expense_month === key && getCompanyExpenseCurrency(e) === 'CNY')
        .reduce((s, e) => s + Number(e.amount || 0), 0); // CNY operating costs
      const rate = getDeductionRate(deductionRates, key);
      const { profit } = calculateMonthlyProfit(bucket, rate);
      months.push({ key, label, income, customerExp: custExp, stripeFee, companyExpUsd: compExpUsd, companyExpCny: compExpCny, profitUsd: roundMoney(profit) });
    });
    return months;
  }, [chartCompanyExpenses, chartMonthKeys, chartMonthlyFinanceBuckets, deductionRates]);

  // ─── Monthly Detail (USD by default, no cross-currency mix) ───────────────────
  const monthlyDetail = useMemo(() => {
    const today = new Date();
    let start = '';
    let end = '';

    if (activeDateRange) {
      start = activeDateRange.start;
      end = activeDateRange.end;
    } else {
      const dates: string[] = [];
      payments.forEach((p: any) => { const d = p.payment_date?.slice(0, 10); if (d) dates.push(d); });
      expenses.forEach((e: any) => { const ym = e.expense_month; if (ym && /^\d{4}-\d{2}$/.test(ym)) dates.push(`${ym}-01`); });
      if (dates.length > 0) {
        dates.sort();
        start = dates[0];
        end = dates[dates.length - 1];
      } else {
        const y = today.getFullYear();
        const m = String(today.getMonth() + 1).padStart(2, '0');
        start = `${y}-${m}-01`;
        end = new Date(y, today.getMonth() + 1, 0).toISOString().slice(0, 10);
      }
    }

    const inRange = (ym: string) => {
      const ymStart = start ? start.slice(0, 7) : null;
      const ymEnd = end ? end.slice(0, 7) : null;
      if (ymStart && ym < ymStart) return false;
      if (ymEnd && ym > ymEnd) return false;
      return true;
    };

    const scopedPayments = payments.filter((payment: any) => {
      const ym = payment.payment_date?.slice(0, 7);
      return /^\d{4}-\d{2}$/.test(ym || '') && inRange(ym!);
    });
    const scopedExpenses = expenses.filter((expense: any) => {
      const ym = expense.expense_month;
      return /^\d{4}-\d{2}$/.test(ym || '') && inRange(ym!);
    });
    const scopedCompanyExpenses = companyExpenses.filter((expense: any) => {
      const ym = expense.expense_month;
      return /^\d{4}-\d{2}$/.test(ym || '') && inRange(ym!);
    });
    const map = buildMonthlyFinanceBuckets(scopedPayments, scopedExpenses, scopedCompanyExpenses);

    const rows = Object.keys(map).sort().map(ym => {
      const bucket = map[ym];
      const revenue = bucket.revenue;
      const cost = bucket.cost;
      const rate = getDeductionRate(deductionRates, ym);
      const {
        managementDeduction,
        adsDeduction,
        deductionAmount,
        effectiveRate,
        profit,
      } = calculateMonthlyProfit(bucket, rate);
      return {
        month: ym,
        revenue_gross: Math.round(revenue * 100) / 100,
        management_revenue: Math.round(bucket.managementRevenue * 100) / 100,
        ads_recharge_revenue: Math.round(bucket.adsRevenue * 100) / 100,
        management_rate: bucket.managementRevenue > 0 ? rate : 0,
        ads_recharge_rate: bucket.adsRevenue > 0 ? ADS_RECHARGE_DEDUCTION_RATE : 0,
        management_deduction_amount: Math.round(managementDeduction * 100) / 100,
        ads_recharge_deduction_amount: Math.round(adsDeduction * 100) / 100,
        deduction_rate: Math.round(effectiveRate * 10000) / 10000,
        deduction_amount: Math.round(deductionAmount * 100) / 100,
        stripe_platform_fee: Math.round(bucket.stripePlatformFee * 100) / 100,
        customer_cost: Math.round(bucket.customerCost * 100) / 100,
        operating_cost_usd: Math.round(bucket.operatingCostUsd * 100) / 100,
        cost: Math.round(cost * 100) / 100,
        profit: Math.round(profit * 100) / 100,
      };
    });

    return { rows, range: { start, end } };
  }, [payments, expenses, companyExpenses, deductionRates, activeDateRange]);

  const paginatedMonthlyDetail = useMemo(
    () => paginateList(monthlyDetail.rows, financePages.monthly_detail, pageSize),
    [monthlyDetail.rows, financePages.monthly_detail, pageSize],
  );


  const incomeByTypeData = useMemo(() => {
    const map: Record<string, number> = {};
    chartPayments.forEach(p => {
      const t = p.income_type || 'other_income';
      const amountPaid = toMoneyNumber(p.amount_paid);
      const managementAmount = getManagementRevenueAmount(p);
      const adsRechargeAmount = getAdsRechargeAmount(p);
      const splitAmount = managementAmount + adsRechargeAmount;
      if (managementAmount > 0) {
        map[MANAGEMENT_FEE_KEY] = (map[MANAGEMENT_FEE_KEY] || 0) + managementAmount;
      }
      if (adsRechargeAmount > 0) {
        map[ADS_FEE_KEY] = (map[ADS_FEE_KEY] || 0) + adsRechargeAmount;
      }
      const remainder = roundMoney(amountPaid - splitAmount);
      if (remainder > 0.01) {
        map[t] = (map[t] || 0) + remainder;
      } else if (splitAmount <= 0) {
        map[t] = (map[t] || 0) + amountPaid;
      }
    });
    return Object.entries(map).map(([type, value]) => ({
      name: incomeTypeLabels[type] || type, type, value: Math.round(value * 100) / 100,
    })).sort((a, b) => b.value - a.value);
  }, [chartPayments, incomeTypeLabels]);

  const productRevenueData = useMemo(() => {
    const map: Record<string, number> = {};
    chartPayments.forEach(p => {
      if (!p.product_name) return;
      const names = p.product_name.split('、');
      const share = (p.amount_paid || 0) / (names.length || 1);
      names.forEach((name: string) => {
        const trimmed = name.trim();
        if (trimmed) map[trimmed] = (map[trimmed] || 0) + share;
      });
    });
    return Object.entries(map).map(([name, value]) => ({ name, value: Math.round(value * 100) / 100 })).sort((a, b) => b.value - a.value);
  }, [chartPayments]);

  const customerRevenueData = useMemo(() => {
    const map: Record<string, number> = {};
    chartPayments.forEach(p => { const name = p.customer_name || '未知客户'; map[name] = (map[name] || 0) + (p.amount_paid || 0); });
    return Object.entries(map).map(([name, value]) => ({ name, value: Math.round(value * 100) / 100 })).sort((a, b) => b.value - a.value).slice(0, 10);
  }, [chartPayments]);

  const payMethodData = useMemo(() => {
    const countMap: Record<string, number> = {};
    const amountMap: Record<string, number> = {};
    chartPayments.forEach(p => {
      const method = normalizePaymentMethodKey(p.payment_method);
      countMap[method] = (countMap[method] || 0) + 1;
      amountMap[method] = (amountMap[method] || 0) + (p.amount_paid || 0);
    });
    return Object.entries(countMap).map(([method, count]) => ({
      name: payMethodLabels[method] || method, method, count,
      amount: Math.round((amountMap[method] || 0) * 100) / 100,
    })).sort((a, b) => b.amount - a.amount);
  }, [payMethodLabels, chartPayments]);

  const payModeData = useMemo(() => {
    const countMap: Record<string, number> = {};
    const amountMap: Record<string, number> = {};
    chartPayments.forEach((payment) => {
      const mode = inferPaymentModeKey(payment);
      countMap[mode] = (countMap[mode] || 0) + 1;
      amountMap[mode] = (amountMap[mode] || 0) + (payment.amount_paid || 0);
    });
    return Object.entries(countMap).map(([mode, count]) => ({
      mode,
      count,
      amount: Math.round((amountMap[mode] || 0) * 100) / 100,
      name: payModeLabels[mode] || mode,
    })).sort((a, b) => b.amount - a.amount);
  }, [payModeLabels, chartPayments]);

  // ─── Customer map for lookups ────────────────────────────────────
  const customerMap = useMemo(() => Object.fromEntries(customers.map(c => [c.id, c])), [customers]);

  const overviewPayments = filteredPayments;
  const overviewCustomerExpenses = useMemo(
    () => (activeDateRange ? expenses.filter(e => isMonthInRange(e.expense_month, activeDateRange)) : expenses),
    [activeDateRange, expenses],
  );
  const overviewCompanyExpenses = useMemo(
    () => (activeDateRange ? companyExpenses.filter(e => isMonthInRange(e.expense_month, activeDateRange)) : companyExpenses),
    [activeDateRange, companyExpenses],
  );

  const customerProfitRows = useMemo(() => {
    const rows: Record<string, {
      customerId: number | null;
      customerName: string;
      revenue: number;
      managementRevenue: number;
      adsRevenue: number;
      otherRevenue: number;
      stripeFee: number;
      managementDeduction: number;
      adsDeduction: number;
      customerCostUsd: number;
      customerCostCny: number;
      outstanding: number;
      paymentCount: number;
      latestPaymentDate: string;
    }> = {};

    const ensureRow = (customerId: any, customerName?: string | null) => {
      const id = Number(customerId) || null;
      const key = id ? String(id) : `name:${customerName || '未知客户'}`;
      if (!rows[key]) {
        rows[key] = {
          customerId: id,
          customerName: customerName || (id ? customerMap[id]?.business_name : '') || '未知客户',
          revenue: 0,
          managementRevenue: 0,
          adsRevenue: 0,
          otherRevenue: 0,
          stripeFee: 0,
          managementDeduction: 0,
          adsDeduction: 0,
          customerCostUsd: 0,
          customerCostCny: 0,
          outstanding: 0,
          paymentCount: 0,
          latestPaymentDate: '',
        };
      }
      return rows[key];
    };

    overviewPayments.forEach((payment: any) => {
      const row = ensureRow(payment.customer_id, payment.customer_name);
      const amountPaid = toMoneyNumber(payment.amount_paid);
      const managementAmount = getManagementRevenueAmount(payment);
      const adsAmount = getAdsRechargeAmount(payment);
      const otherAmount = Math.max(0, amountPaid - managementAmount - adsAmount);
      const ym = (payment.payment_date || '').slice(0, 7);
      const rate = getDeductionRate(deductionRates, ym);
      const outstanding = getStoredMoney(payment.outstanding_amount) ?? Math.max(0, toMoneyNumber(payment.amount_due) - amountPaid);

      row.revenue += amountPaid;
      row.managementRevenue += managementAmount;
      row.adsRevenue += adsAmount;
      row.otherRevenue += otherAmount;
      row.stripeFee += calculateStripePlatformFee(payment);
      row.managementDeduction += managementAmount * rate;
      row.adsDeduction += adsAmount * ADS_RECHARGE_DEDUCTION_RATE;
      row.outstanding += outstanding;
      row.paymentCount += 1;
      const paymentDate = payment.payment_date?.slice(0, 10) || '';
      if (paymentDate && paymentDate > row.latestPaymentDate) row.latestPaymentDate = paymentDate;
    });

    overviewCustomerExpenses.forEach((expense: any) => {
      const row = ensureRow(expense.customer_id, expense.customer_name);
      const amount = toMoneyNumber(expense.amount);
      if (getCustomerExpenseCurrency(expense) === 'USD') {
        row.customerCostUsd += amount;
      } else {
        row.customerCostCny += amount;
      }
    });

    return Object.values(rows)
      .map(row => {
        const totalFee = row.stripeFee + row.managementDeduction + row.adsDeduction;
        const profit = row.revenue - totalFee - row.customerCostUsd;
        return {
          ...row,
          revenue: roundMoney(row.revenue),
          managementRevenue: roundMoney(row.managementRevenue),
          adsRevenue: roundMoney(row.adsRevenue),
          otherRevenue: roundMoney(row.otherRevenue),
          stripeFee: roundMoney(row.stripeFee),
          managementDeduction: roundMoney(row.managementDeduction),
          adsDeduction: roundMoney(row.adsDeduction),
          customerCostUsd: roundMoney(row.customerCostUsd),
          customerCostCny: roundMoney(row.customerCostCny),
          outstanding: roundMoney(row.outstanding),
          totalFee: roundMoney(totalFee),
          profit: roundMoney(profit),
          profitRate: row.revenue > 0 ? profit / row.revenue : 0,
        };
      })
      .sort((a, b) => b.profit - a.profit);
  }, [customerMap, deductionRates, overviewCustomerExpenses, overviewPayments]);

  const receivableRows = useMemo(() => (
    overviewPayments
      .map((payment: any) => {
        const amountDue = toMoneyNumber(payment.amount_due);
        const amountPaid = toMoneyNumber(payment.amount_paid);
        const outstanding = getStoredMoney(payment.outstanding_amount) ?? Math.max(0, amountDue - amountPaid);
        const paymentDate = payment.payment_date?.slice(0, 10) || '';
        return {
          ...payment,
          amountDue,
          amountPaid,
          outstanding: roundMoney(outstanding),
          paymentDate,
          overdueDays: Math.max(0, getDaysBetweenToday(paymentDate) || 0),
          customerName: payment.customer_name || customerMap[payment.customer_id]?.business_name || '未知客户',
          salesPerson: customerMap[payment.customer_id]?.sales_person || '-',
        };
      })
      .filter(row => row.outstanding > 0)
      .sort((a, b) => b.overdueDays - a.overdueDays || b.outstanding - a.outstanding)
  ), [customerMap, overviewPayments]);

  const ownerOverview = useMemo(() => {
    const buckets = buildMonthlyFinanceBuckets(overviewPayments, overviewCustomerExpenses, overviewCompanyExpenses);
    const totals = Object.entries(buckets).reduce((acc, [ym, bucket]) => {
      const rate = getDeductionRate(deductionRates, ym);
      const profit = calculateMonthlyProfit(bucket, rate);
      acc.revenue += bucket.revenue;
      acc.managementRevenue += bucket.managementRevenue;
      acc.adsRevenue += bucket.adsRevenue;
      acc.customerCostUsd += bucket.customerCost;
      acc.companyCostUsd += bucket.operatingCostUsd;
      acc.stripeFee += bucket.stripePlatformFee;
      acc.deduction += profit.deductionAmount;
      acc.profitUsd += profit.profit;
      return acc;
    }, {
      revenue: 0,
      managementRevenue: 0,
      adsRevenue: 0,
      customerCostUsd: 0,
      companyCostUsd: 0,
      stripeFee: 0,
      deduction: 0,
      profitUsd: 0,
    });
    const companyCostCny = overviewCompanyExpenses
      .filter(expense => getCompanyExpenseCurrency(expense) === 'CNY')
      .reduce((sum, expense) => sum + toMoneyNumber(expense.amount), 0);
    const outstanding = receivableRows.reduce((sum, row) => sum + row.outstanding, 0);
    const totalReceivableDue = receivableRows.reduce((sum, row) => sum + row.amountDue, 0);
    return {
      revenue: roundMoney(totals.revenue),
      managementRevenue: roundMoney(totals.managementRevenue),
      adsRevenue: roundMoney(totals.adsRevenue),
      customerCostUsd: roundMoney(totals.customerCostUsd),
      companyCostUsd: roundMoney(totals.companyCostUsd),
      companyCostCny: roundMoney(companyCostCny),
      stripeFee: roundMoney(totals.stripeFee),
      deduction: roundMoney(totals.deduction),
      profitUsd: roundMoney(totals.profitUsd),
      outstanding: roundMoney(outstanding),
      totalReceivableDue: roundMoney(totalReceivableDue),
      receivableCount: receivableRows.length,
      profitRate: totals.revenue > 0 ? totals.profitUsd / totals.revenue : 0,
    };
  }, [deductionRates, overviewCompanyExpenses, overviewCustomerExpenses, overviewPayments, receivableRows]);

  const renewalForecast = useMemo(() => {
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const withinDays = (days: number) => {
      const end = new Date(today);
      end.setDate(end.getDate() + days);
      const rows = subscriptions.filter((subscription: any) => {
        const status = computeSubscriptionStatus(subscription);
        if (['stopped', 'lost', 'paused', 'upgraded'].includes(status)) return false;
        const dateValue = (subscription.next_payment_date || subscription.end_date || '').slice(0, 10);
        if (!dateValue) return false;
        const date = new Date(`${dateValue}T00:00:00`);
        return !Number.isNaN(date.getTime()) && date >= today && date <= end;
      });
      return {
        count: rows.length,
        amount: roundMoney(rows.reduce((sum, item) => sum + toMoneyNumber(item.package_price), 0)),
      };
    };
    return {
      d7: withinDays(7),
      d30: withinDays(30),
      d60: withinDays(60),
    };
  }, [subscriptions]);

  const paginatedCustomerProfitRows = useMemo(
    () => paginateList(customerProfitRows, financePages.customer_profit, pageSize),
    [customerProfitRows, financePages.customer_profit, pageSize],
  );
  const paginatedReceivableRows = useMemo(
    () => paginateList(receivableRows, financePages.receivables, pageSize),
    [receivableRows, financePages.receivables, pageSize],
  );

  useEffect(() => {
    setActiveFinanceTab(normalizeFinanceTab(searchParams.get('tab')));
  }, [searchParams]);

  const handleFinanceTabChange = (nextTab: string) => {
    const safeTab = normalizeFinanceTab(nextTab);
    setActiveFinanceTab(safeTab);
    const nextParams = new URLSearchParams(searchParams);
    if (safeTab === 'overview') {
      nextParams.delete('tab');
    } else {
      nextParams.set('tab', safeTab);
    }
    setSearchParams(nextParams);
  };

  const openCustomerDetail = (customerId: string | number | null | undefined, tab = 'info', returnFinanceTab = activeFinanceTab) => {
    const id = Number(customerId);
    if (!id) {
      toast.error('这条记录没有绑定客户，无法跳转');
      return;
    }
    navigate(`/customers?detail=${id}&tab=${tab}&from=finance&financeTab=${returnFinanceTab}`);
  };

  const derivePaymentIncomeSplit = (
    incomeType: string,
    amountPaid: number,
    managementRaw: any,
    adsRaw: any,
  ) => {
    const hasManualManagement = managementRaw !== '' && managementRaw !== null && managementRaw !== undefined;
    const hasManualAds = adsRaw !== '' && adsRaw !== null && adsRaw !== undefined;
    if (hasManualManagement || hasManualAds) {
      return {
        managementAmount: hasManualManagement ? roundMoney(toMoneyNumber(managementRaw)) : 0,
        adsRechargeAmount: hasManualAds ? roundMoney(toMoneyNumber(adsRaw)) : 0,
      };
    }
    if (incomeType === MANAGEMENT_FEE_KEY) {
      return { managementAmount: roundMoney(amountPaid), adsRechargeAmount: 0 };
    }
    if (incomeType === ADS_FEE_KEY) {
      return { managementAmount: 0, adsRechargeAmount: roundMoney(amountPaid) };
    }
    return { managementAmount: 0, adsRechargeAmount: 0 };
  };

  const buildPaymentFinancePayload = () => {
    const amountPaid = roundMoney(toMoneyNumber(payForm.amount_paid));
    const { managementAmount, adsRechargeAmount } = derivePaymentIncomeSplit(
      payForm.income_type,
      amountPaid,
      payForm.management_amount,
      payForm.ads_recharge_amount,
    );
    const stripeFeeAmount = calculateStripePlatformFeeFromValues(
      amountPaid,
      payForm.payment_mode,
      normalizePaymentMethodKey(payForm.payment_method),
    );
    const resolvedIncomeType = managementAmount > 0 && adsRechargeAmount > 0
      ? MIXED_MANAGEMENT_ADS_KEY
      : payForm.income_type;
    return {
      income_type: resolvedIncomeType,
      management_amount: managementAmount,
      ads_recharge_amount: adsRechargeAmount,
      stripe_fee_amount: stripeFeeAmount,
      net_amount: roundMoney(Math.max(amountPaid - stripeFeeAmount, 0)),
    };
  };

  const getSubscriptionStatusLabel = (status?: string | null) => (
    subStatusLabels[status || ''] || subscriptionStatusFallbackLabels[status || ''] || status || '-'
  );

  // ─── Payment CRUD ────────────────────────────────────────────────
  const openEditPayment = (p: any) => {
    const names = p.product_name ? p.product_name.split('、').map((s: string) => s.trim()).filter(Boolean) : [];
    const displayIncomeType = getPaymentDisplayIncomeType(p);
    setPayForm({
      customer_id: String(p.customer_id || ''), product_names: names,
      income_type: displayIncomeType || 'management_fee',
      amount_due: String(p.amount_due || ''), amount_paid: String(p.amount_paid || ''),
      payment_mode: inferPaymentModeKey(p),
      payment_method: normalizePaymentMethodKey(p.payment_method),
      billing_cycle: p.billing_cycle || 'monthly',
      management_amount: p.management_amount ?? '',
      ads_recharge_amount: p.ads_recharge_amount ?? '',
      transaction_reference: p.transaction_reference || '',
      coverage_start: p.coverage_start?.slice(0, 10) || '', coverage_end: p.coverage_end?.slice(0, 10) || '',
      has_invoice: p.has_invoice || false, sync_to_deal: false, notes: p.notes || '',
    });
    setEditingPayId(p.id);
    setShowPaymentForm(true);
  };

  const handleSavePayment = async () => {
    if (!payForm.customer_id || !payForm.amount_due || !payForm.amount_paid) { toast.error('请填写必填字段'); return; }
    if (payForm.product_names.length === 0) { toast.error('请至少选择一个产品'); return; }
    setSaving(true);
    try {
      const cust = customers.find(c => c.id === Number(payForm.customer_id));
      const amountDue = Number(payForm.amount_due);
      const amountPaid = Number(payForm.amount_paid);
      if (!Number.isFinite(amountDue) || !Number.isFinite(amountPaid) || amountDue < 0 || amountPaid < 0) {
        toast.error('金额必须是大于等于 0 的数字');
        return;
      }
      const financeAmounts = buildPaymentFinancePayload();
      if (financeAmounts.management_amount < 0 || financeAmounts.ads_recharge_amount < 0) {
        toast.error('管理费金额和投流金额不能为负数');
        return;
      }
      if (financeAmounts.management_amount + financeAmounts.ads_recharge_amount > amountPaid + 0.01) {
        toast.error('管理费金额 + 投流充值金额不能大于实收金额');
        return;
      }
      if (payForm.income_type === MIXED_MANAGEMENT_ADS_KEY && (financeAmounts.management_amount <= 0 || financeAmounts.ads_recharge_amount <= 0)) {
        toast.error('管理费+投流费需要同时填写管理费金额和投流充值金额');
        return;
      }
      const coverageStartISO = toISODatetime(payForm.coverage_start);
      const coverageEndISO = toISODatetime(payForm.coverage_end);
      const normalizedPaymentMethod = normalizePaymentMethodKey(payForm.payment_method);
      const payload: Record<string, any> = {
        customer_id: Number(payForm.customer_id),
        customer_name: cust?.business_name || '',
        product_name: payForm.product_names.join('、'),
        amount_due: amountDue, amount_paid: amountPaid,
        ...financeAmounts,
        currency: 'USD',
        payment_mode: payForm.payment_mode,
        payment_method: normalizedPaymentMethod,
        transaction_reference: payForm.transaction_reference || null,
        billing_cycle: payForm.billing_cycle,
        coverage_start: coverageStartISO, coverage_end: coverageEndISO,
        has_invoice: payForm.has_invoice,
        sync_to_deal: payForm.sync_to_deal,
        outstanding_amount: Math.max(0, amountDue - amountPaid),
        expense_month: payForm.coverage_start ? payForm.coverage_start.slice(0, 7) : currentMonthKey,
        notes: payForm.notes || null,
      };
      if (editingPayId) {
        await invokeWithAuth({
          url: `/api/v1/entities/payments/${editingPayId}`,
          method: 'PUT',
          data: payload,
        });
        toast.success(payForm.sync_to_deal ? '收款记录已更新，并已同步成交' : '收款记录已更新');
        void logOperation({
          customerId: Number(payForm.customer_id),
          actionType: 'edit_payment',
          actionDetail: `编辑收款：${cust?.business_name || ''} ${payForm.product_names.join('、')} ${fmt(amountPaid)}`,
          operatorName,
        });
      } else {
        payload.payment_date = new Date().toISOString();
        payload.created_at = new Date().toISOString();
        await invokeWithAuth({
          url: '/api/v1/entities/payments',
          method: 'POST',
          data: payload,
        });
        toast.success(payForm.sync_to_deal ? '收款记录已添加，并已同步成交' : '收款记录已添加');
        void logOperation({
          customerId: Number(payForm.customer_id),
          actionType: 'create_payment',
          actionDetail: `新增收款：${cust?.business_name || ''} ${payForm.product_names.join('、')} ${fmt(amountPaid)}`,
          operatorName,
        });
      }
      // Auto-create or update subscription
      if (coverageEndISO) {
        try {
          const matchingSub = findMatchingSubscription(subscriptions, {
            customerId: Number(payForm.customer_id),
            packageName: payForm.product_names,
          });
          const paymentDateISO = payload.payment_date || new Date().toISOString();
          const isAutoSubscription = payForm.payment_mode === 'subscription_auto' || normalizedPaymentMethod === 'stripe';
          const subStartDate = coverageStartISO || matchingSub?.start_date || paymentDateISO;
          const subBaseData = {
            customer_id: Number(payForm.customer_id),
            customer_name: cust?.business_name || '',
            package_name: payForm.product_names.join('、'),
            package_price: amountDue,
            billing_cycle: payForm.billing_cycle,
            start_date: subStartDate,
            end_date: coverageEndISO,
            auto_renew: isAutoSubscription,
            renewal_person: cust?.sales_person || matchingSub?.renewal_person || '',
            last_payment_date: paymentDateISO,
            next_payment_date: coverageEndISO,
            renewal_result: isAutoSubscription ? 'stripe_subscription_confirmed' : 'manual_payment_confirmed',
            updated_at: new Date().toISOString(),
          };
          const subData = {
            ...subBaseData,
            status: computeSubscriptionStatus(subBaseData),
          };

          if (matchingSub) {
            await client.entities.subscriptions.update({
              id: String(matchingSub.id),
              data: subData,
            });
            void logOperation({
              customerId: Number(payForm.customer_id),
              actionType: 'edit_subscription',
              actionDetail: `同步套餐续费：${cust?.business_name || ''} ${payForm.product_names.join('、')} 截止 ${payForm.coverage_end || ''}`,
              operatorName,
            });
          } else {
            await client.entities.subscriptions.create({
              data: { ...subData, created_at: new Date().toISOString() },
            });
            void logOperation({
              customerId: Number(payForm.customer_id),
              actionType: 'create_subscription',
              actionDetail: `新增套餐续费：${cust?.business_name || ''} ${payForm.product_names.join('、')} 截止 ${payForm.coverage_end || ''}`,
              operatorName,
            });
          }
        } catch (subErr) {
          console.error('Auto-create/update subscription failed:', subErr);
          toast.error('收款已保存，但套餐续费同步失败，请检查续费信息');
        }
      }
      setShowPaymentForm(false); setEditingPayId(null); setPayForm(emptyPayForm);
      await loadData();
    } catch (err: any) {
      const detail = err?.data?.detail || err?.response?.data?.detail || err?.message || '保存失败';
      toast.error(`保存失败: ${detail}`);
      console.error(err);
    } finally { setSaving(false); }
  };

  const handleConfirmSubscriptionRenewal = async (subscription: any) => {
    if (!subscription?.id) return;
    const amount = Number(subscription.package_price || 0);
    if (amount <= 0) {
      toast.error('该套餐缺少续费金额，无法自动生成收入');
      return;
    }
    const todayDateOnly = new Date().toISOString().slice(0, 10);
    const rawDueBaseDate =
      toDateOnly(subscription.next_payment_date)
      || toDateOnly(subscription.end_date)
      || todayDateOnly;
    const dueBaseDate = rawDueBaseDate < todayDateOnly ? todayDateOnly : rawDueBaseDate;
    const nextPaymentDate = addBillingCycle(dueBaseDate, subscription.billing_cycle || 'monthly');
    if (!nextPaymentDate) {
      toast.error('无法识别计费周期，请先检查套餐续费信息');
      return;
    }

    const existingEndDate = toDateOnly(subscription.end_date);
    const nextServiceEndDate = existingEndDate && existingEndDate > nextPaymentDate ? existingEndDate : nextPaymentDate;
    const paymentDateISO = new Date().toISOString();
    const customerName = subscription.customer_name || customerMap[subscription.customer_id]?.business_name || '';
    const packageName = subscription.package_name || '订阅套餐';
    const incomeType = inferSubscriptionIncomeType(packageName);
    const { managementAmount, adsRechargeAmount } = derivePaymentIncomeSplit(incomeType, amount, '', '');
    const stripeFeeAmount = calculateStripePlatformFeeFromValues(amount, 'subscription_auto', 'stripe');

    setConfirmingRenewalId(Number(subscription.id));
    try {
      await invokeWithAuth({
        url: '/api/v1/entities/payments',
        method: 'POST',
        data: {
          customer_id: Number(subscription.customer_id),
          customer_name: customerName,
          income_type: incomeType,
          product_name: packageName,
          amount_due: amount,
          amount_paid: amount,
          management_amount: managementAmount,
          ads_recharge_amount: adsRechargeAmount,
          stripe_fee_amount: stripeFeeAmount,
          net_amount: roundMoney(Math.max(amount - stripeFeeAmount, 0)),
          currency: 'USD',
          payment_date: paymentDateISO,
          payment_mode: 'subscription_auto',
          payment_method: 'stripe',
          billing_cycle: subscription.billing_cycle || 'monthly',
          coverage_start: toISODatetime(dueBaseDate),
          coverage_end: toISODatetime(nextPaymentDate),
          has_invoice: false,
          outstanding_amount: 0,
          expense_month: paymentDateISO.slice(0, 7),
          recorded_by: operatorName,
          notes: `Stripe订阅续费确认：${packageName}，覆盖 ${dueBaseDate} 至 ${nextPaymentDate}。手续费按 2.9% + $0.30 自动计入报表成本。`,
          created_at: paymentDateISO,
        },
      });

      const nextSubscriptionPayload = {
        package_price: amount,
        billing_cycle: subscription.billing_cycle || 'monthly',
        auto_renew: true,
        last_payment_date: paymentDateISO,
        next_payment_date: toISODatetime(nextPaymentDate),
        end_date: toISODatetime(nextServiceEndDate),
        status: computeSubscriptionStatus({
          ...subscription,
          auto_renew: true,
          next_payment_date: toISODatetime(nextPaymentDate),
          end_date: toISODatetime(nextServiceEndDate),
          status: 'active',
        }),
        renewal_result: 'stripe_subscription_confirmed',
        updated_at: paymentDateISO,
      };

      await invokeWithAuth({
        url: `/api/v1/entities/subscriptions/${subscription.id}`,
        method: 'PUT',
        data: nextSubscriptionPayload,
      });

      void logOperation({
        customerId: Number(subscription.customer_id),
        actionType: 'confirm_subscription_renewal',
        actionDetail: `确认Stripe订阅续费：${customerName} ${packageName} ${fmt(amount)}，下次付款 ${nextPaymentDate}`,
        operatorName,
      });

      toast.success(`已确认续费，下次付款时间：${nextPaymentDate}`);
      await loadData();
    } catch (err: any) {
      const detail = err?.data?.detail || err?.response?.data?.detail || err?.message || '确认续费失败';
      toast.error(`确认续费失败: ${detail}`);
      console.error('Confirm subscription renewal failed:', err);
    } finally {
      setConfirmingRenewalId(null);
    }
  };

  const handleToggleSubscriptionAutoRenew = async (subscription: any, enabled: boolean) => {
    if (!subscription?.id) return;

    const now = new Date().toISOString();
    const nextPaymentDate = enabled
      ? toISODatetime(toDateOnly(subscription.next_payment_date) || toDateOnly(subscription.end_date))
      : null;
    const payload = enabled
      ? {
          auto_renew: true,
          next_payment_date: nextPaymentDate,
          status: computeSubscriptionStatus({
            ...subscription,
            auto_renew: true,
            next_payment_date: nextPaymentDate,
            status: 'active',
          }),
          renewal_result: 'auto_renew_enabled',
          updated_at: now,
        }
      : {
          auto_renew: false,
          next_payment_date: null,
          status: 'stopped',
          renewal_result: 'auto_renew_disabled',
          updated_at: now,
        };

    setUpdatingSubscriptionId(Number(subscription.id));
    try {
      await invokeWithAuth({
        url: `/api/v1/entities/subscriptions/${subscription.id}`,
        method: 'PUT',
        data: payload,
      });

      void logOperation({
        customerId: Number(subscription.customer_id),
        actionType: enabled ? 'enable_subscription_auto_renew' : 'disable_subscription_auto_renew',
        actionDetail: `${enabled ? '开启' : '关闭'}套餐续费开关：${subscription.customer_name || customerMap[subscription.customer_id]?.business_name || ''} ${subscription.package_name || ''}`,
        operatorName,
      });

      setSubscriptions(prev => decorateEffectiveSubscriptions(prev.map(item => (
        String(item.id) === String(subscription.id) ? { ...item, ...payload } : item
      ))));
      toast.success(enabled ? '已开启续费开关，到期后会进入待确认续费' : '已停止续费提醒，历史收款不受影响');
      await loadData();
    } catch (err: any) {
      const detail = err?.data?.detail || err?.response?.data?.detail || err?.message || '更新续费开关失败';
      toast.error(`更新续费开关失败: ${detail}`);
      console.error('Toggle subscription auto renew failed:', err);
    } finally {
      setUpdatingSubscriptionId(null);
    }
  };

  // ─── Customer Expense CRUD ───────────────────────────────────────
  const openEditExpense = (e: any) => {
    setExpenseForm({
      customer_id: String(e.customer_id || ''), expense_type: e.expense_type || 'management_fee',
      currency: getCustomerExpenseCurrency(e),
      amount: String(e.amount || ''), expense_month: e.expense_month || expenseMonth, notes: e.notes || '',
    });
    setEditingExpenseId(e.id);
    setShowExpenseForm(true);
  };

  const handleSaveExpense = async () => {
    if (!expenseForm.customer_id || !expenseForm.amount) { toast.error('请填写必填字段'); return; }
    setSavingExpense(true);
    try {
      const cust = customers.find(c => c.id === Number(expenseForm.customer_id));
      const payload: Record<string, any> = {
        customer_id: Number(expenseForm.customer_id), customer_name: cust?.business_name || '',
        expense_type: expenseForm.expense_type, expense_category: 'customer',
        currency: expenseForm.currency,
        amount: Number(expenseForm.amount), expense_month: expenseForm.expense_month,
        notes: expenseForm.notes || null,
      };
      if (editingExpenseId) {
        await invokeWithAuth({
          url: `/api/v1/entities/expenses/${editingExpenseId}`,
          method: 'PUT',
          data: payload,
        });
        toast.success('费用记录已更新');
        void logOperation({
          customerId: Number(expenseForm.customer_id),
          actionType: 'edit_customer_expense',
          actionDetail: `编辑客户支出：${cust?.business_name || ''} ${customerExpenseTypeLabels[expenseForm.expense_type] || expenseForm.expense_type} ${fmt(Number(expenseForm.amount))}`,
          operatorName,
        });
      } else {
        payload.payment_date = new Date().toISOString();
        payload.created_at = new Date().toISOString();
        await invokeWithAuth({
          url: '/api/v1/entities/expenses',
          method: 'POST',
          data: payload,
        });
        toast.success('费用记录已添加');
        void logOperation({
          customerId: Number(expenseForm.customer_id),
          actionType: 'create_customer_expense',
          actionDetail: `新增客户支出：${cust?.business_name || ''} ${customerExpenseTypeLabels[expenseForm.expense_type] || expenseForm.expense_type} ${fmt(Number(expenseForm.amount))}`,
          operatorName,
        });
      }
      setShowExpenseForm(false); setEditingExpenseId(null); setExpenseForm(emptyExpenseForm);
      await loadData();
    } catch (err: any) {
      const detail = err?.data?.detail || err?.response?.data?.detail || err?.message || '保存失败';
      toast.error(`保存失败: ${detail}`);
      console.error(err);
    } finally { setSavingExpense(false); }
  };

  const handleDeleteExpense = async () => {
    if (!deleteExpenseTarget) return;
    setDeletingExpense(true);
    try {
      await invokeWithAuth({
        url: `/api/v1/entities/expenses/${deleteExpenseTarget.id}`,
        method: 'DELETE',
      });
      toast.success('费用记录已删除');
      void logOperation({
        customerId: deleteExpenseTarget.customer_id || undefined,
        actionType: 'delete_customer_expense',
        actionDetail: `删除客户支出：${deleteExpenseTarget.customer_name || ''} ${customerExpenseTypeLabels[deleteExpenseTarget.expense_type] || deleteExpenseTarget.expense_type} ${fmt(Number(deleteExpenseTarget.amount || 0))}`,
        operatorName,
      });
      setDeleteExpenseTarget(null); await loadData();
    } catch (err) { toast.error('删除失败'); console.error(err); } finally { setDeletingExpense(false); }
  };

  // ─── Company Expense CRUD ────────────────────────────────────────
  const openEditCompanyExpense = (e: any) => {
    setCompanyExpenseForm({
      category: e.category || defaultCompanyExpenseType, amount: String(e.amount || ''),
      currency: getCompanyExpenseCurrency(e),
      expense_month: e.expense_month || companyExpenseMonth,
      expense_date: e.expense_date?.slice(0, 10) || '', notes: e.notes || '',
    });
    setEditingCompanyExpenseId(e.id);
    setShowCompanyExpenseForm(true);
  };

  const handleSaveCompanyExpense = async () => {
    if (!companyExpenseForm.amount) { toast.error('请填写金额'); return; }
    setSavingCompanyExpense(true);
    try {
      const payload: Record<string, any> = {
        category: companyExpenseForm.category,
        category_name: companyExpenseTypeLabels[companyExpenseForm.category] || companyExpenseForm.category,
        amount: Number(companyExpenseForm.amount),
        currency: companyExpenseForm.currency,
        expense_month: companyExpenseForm.expense_month,
        expense_date: toISODatetime(companyExpenseForm.expense_date) || new Date().toISOString(),
        notes: companyExpenseForm.notes || null,
      };
      const formattedAmount = formatMoney(Number(companyExpenseForm.amount), companyExpenseForm.currency);
      if (editingCompanyExpenseId) {
        await invokeWithAuth({
          url: `/api/v1/entities/company_expenses/${editingCompanyExpenseId}`,
          method: 'PUT',
          data: payload,
        });
        toast.success('运营支出已更新');
        void logOperation({
          actionType: 'edit_company_expense',
          actionDetail: `编辑运营支出：${companyExpenseTypeLabels[companyExpenseForm.category] || companyExpenseForm.category} ${formattedAmount}`,
          operatorName,
        });
      } else {
        payload.created_at = new Date().toISOString();
        await invokeWithAuth({
          url: '/api/v1/entities/company_expenses',
          method: 'POST',
          data: payload,
        });
        toast.success('运营支出已添加');
        void logOperation({
          actionType: 'create_company_expense',
          actionDetail: `新增运营支出：${companyExpenseTypeLabels[companyExpenseForm.category] || companyExpenseForm.category} ${formattedAmount}`,
          operatorName,
        });
      }
      setShowCompanyExpenseForm(false); setEditingCompanyExpenseId(null); setCompanyExpenseForm(emptyCompanyExpenseForm);
      await loadData();
    } catch (err: any) {
      const detail = err?.data?.detail || err?.response?.data?.detail || err?.message || '保存失败';
      toast.error(`保存失败: ${detail}`);
      console.error(err);
    } finally { setSavingCompanyExpense(false); }
  };

  const handleDeleteCompanyExpense = async () => {
    if (!deleteCompanyExpenseTarget) return;
    setDeletingCompanyExpense(true);
    try {
      await invokeWithAuth({
        url: `/api/v1/entities/company_expenses/${deleteCompanyExpenseTarget.id}`,
        method: 'DELETE',
      });
      toast.success('运营支出已删除');
      const currency = getCompanyExpenseCurrency(deleteCompanyExpenseTarget);
      void logOperation({
        actionType: 'delete_company_expense',
        actionDetail: `删除运营支出：${companyExpenseTypeLabels[deleteCompanyExpenseTarget.category] || deleteCompanyExpenseTarget.category} ${formatMoney(Number(deleteCompanyExpenseTarget.amount || 0), currency)}`,
        operatorName,
      });
      setDeleteCompanyExpenseTarget(null); await loadData();
    } catch (err) { toast.error('删除失败'); console.error(err); } finally { setDeletingCompanyExpense(false); }
  };

  // ─── Delete payment/subscription ─────────────────────────────────
  const handleDeleteRecord = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      if (deleteTarget.type === 'payment') {
        await invokeWithAuth({
          url: `/api/v1/entities/payments/${deleteTarget.item.id}`,
          method: 'DELETE',
        });
        toast.success('收款记录已删除');
        void logOperation({
          customerId: deleteTarget.item.customer_id || undefined,
          actionType: 'delete_payment',
          actionDetail: `删除收款：${deleteTarget.item.customer_name || ''} ${deleteTarget.item.product_name || ''} ${fmt(Number(deleteTarget.item.amount_paid || 0))}`,
          operatorName,
        });
      } else {
        await invokeWithAuth({
          url: `/api/v1/entities/subscriptions/${deleteTarget.item.id}`,
          method: 'DELETE',
        });
        toast.success('套餐记录已删除');
        void logOperation({
          customerId: deleteTarget.item.customer_id || undefined,
          actionType: 'delete_subscription',
          actionDetail: `删除套餐续费：${deleteTarget.item.customer_name || ''} ${deleteTarget.item.package_name || ''}`,
          operatorName,
        });
      }
      setDeleteTarget(null); await loadData();
    } catch (err) { toast.error('删除失败'); console.error(err); } finally { setDeleting(false); }
  };

  // ─── Date Filter Component ──────────────────────────────────────
  const DateFilterBar = () => (
    <Card className="border-slate-200">
      <CardContent className="p-3">
        <div className="flex flex-col sm:flex-row items-start sm:items-center gap-3">
          <div className="flex items-center gap-1.5 text-sm text-slate-600">
            <Filter className="w-4 h-4" />
            <span className="font-medium">时间筛选：</span>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {(['all', 'today', 'this_month', 'last_month', 'custom'] as DateFilterMode[]).map(mode => (
              <Button key={mode} size="sm"
                variant={dateFilterMode === mode ? 'default' : 'outline'}
                className={dateFilterMode === mode ? 'bg-blue-600 hover:bg-blue-700 text-white' : ''}
                onClick={() => { setDateFilterMode(mode); if (mode !== 'custom') { setFilterStartDate(''); setFilterEndDate(''); } }}
              >
                {mode === 'all' && '全部'}
                {mode === 'today' && <><CalendarDays className="w-3.5 h-3.5 mr-1" />今天</>}
                {mode === 'this_month' && '本月'}
                {mode === 'last_month' && '上月'}
                {mode === 'custom' && '自定义时间段'}
              </Button>
            ))}
            {dateFilterMode === 'custom' && (
              <div className="flex items-center gap-2">
                <Input type="date" value={filterStartDate} onChange={e => setFilterStartDate(e.target.value)} className="h-8 w-36 text-sm" />
                <span className="text-slate-400 text-sm">至</span>
                <Input type="date" value={filterEndDate} onChange={e => setFilterEndDate(e.target.value)} className="h-8 w-36 text-sm" />
                {(filterStartDate || filterEndDate) && (
                  <Button size="sm" variant="ghost" className="h-8 text-xs text-slate-500" onClick={() => { setFilterStartDate(''); setFilterEndDate(''); }}>清除</Button>
                )}
              </div>
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  );

  const PaginationFooter = ({ pageKey, data }: { pageKey: FinancePageKey; data: PaginationResult<any> }) => {
    if (data.total === 0) return null;
    const setPage = (page: number) => {
      setFinancePages(prev => ({ ...prev, [pageKey]: page }));
    };
    return (
      <div className="flex flex-col gap-3 border-t border-slate-100 px-3 py-3 text-sm text-slate-500 sm:flex-row sm:items-center sm:justify-between">
        <div>
          显示 {data.start}-{data.end} 条 / 共 {data.total} 条
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-slate-400">每页</span>
          <NativeSelect
            value={String(pageSize)}
            onChange={value => setPageSize(Number(value))}
            options={PAGE_SIZE_OPTIONS.map(size => ({ value: String(size), label: `${size} 条` }))}
            className="h-8 w-24 text-xs"
          />
          <Button size="sm" variant="outline" className="h-8" onClick={() => setPage(1)} disabled={data.page <= 1}>
            首页
          </Button>
          <Button size="sm" variant="outline" className="h-8" onClick={() => setPage(data.page - 1)} disabled={data.page <= 1}>
            上一页
          </Button>
          <span className="min-w-20 text-center text-xs text-slate-500">
            {data.page} / {data.totalPages} 页
          </span>
          <Button size="sm" variant="outline" className="h-8" onClick={() => setPage(data.page + 1)} disabled={data.page >= data.totalPages}>
            下一页
          </Button>
          <Button size="sm" variant="outline" className="h-8" onClick={() => setPage(data.totalPages)} disabled={data.page >= data.totalPages}>
            末页
          </Button>
        </div>
      </div>
    );
  };

  // ─── Customer select options ─────────────────────────────────────
  const customerOptions = useMemo(() => {
    return customers.map(c => ({
      value: String(c.id),
      label: `${c.business_name}${c.contact_name ? ' - ' + c.contact_name : ''}`,
    }));
  }, [customers]);

  // Handler for customer select in payment form
  const handlePayCustomerChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const val = e.target.value;
    const selectedCustomer = customers.find(customer => String(customer.id) === val);
    const suggestedPackages = parseMultiValue(selectedCustomer?.interested_packages)
      .map(key => customerPackageLabels[key])
      .filter(Boolean);
    setPayForm(prev => ({
      ...prev,
      customer_id: val,
      product_names: prev.product_names.length > 0 ? prev.product_names : suggestedPackages,
    }));
  };

  // Handler for customer select in expense form
  const handleExpenseCustomerChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const val = e.target.value;
    setExpenseForm(prev => ({ ...prev, customer_id: val }));
  };

  // ─── Render ──────────────────────────────────────────────────────
  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
        <h2 className="text-xl font-semibold text-slate-800">财务管理</h2>
        <div className="flex gap-2 flex-wrap ml-auto">
          <Button size="sm" variant="outline" onClick={() => doExport('csv')} disabled={exporting}>导出 CSV</Button>
          <Button size="sm" onClick={() => doExport('xlsx')} disabled={exporting} className="bg-blue-600 hover:bg-blue-700">导出 Excel</Button>
        </div>



























      </div>

      <DateFilterBar />

      {/* Overview Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-8 gap-3">
        <Card className="border-slate-200">
          <CardContent className="p-3 flex items-center gap-3">
            <div className="w-9 h-9 rounded-lg bg-green-50 flex items-center justify-center"><ArrowUpRight className="w-4 h-4 text-green-600" /></div>
            <div><p className="text-[11px] text-slate-500">{summaryPeriodLabel}收入</p><p className="text-base font-bold text-green-600">{fmt(summaryFinance.revenue)}</p></div>
          </CardContent>
        </Card>
        {/* 运营支出 */}
        <Card className="border-slate-200">
          <CardContent className="p-3 flex items-center gap-3">
            <div className="w-9 h-9 rounded-lg bg-red-50 flex items-center justify-center"><ArrowDownRight className="w-4 h-4 text-red-600" /></div>
            <div>
              <p className="text-[11px] text-slate-500">{summaryPeriodLabel}运营支出</p>
              <p className="text-base font-bold text-red-600">{fmt(summaryFinance.operatingCostUsd)}</p>
              <p className="text-[11px] text-slate-400">{fmtRMB(summaryCompanyExpenseCny)} 单独统计</p>
            </div>
          </CardContent>
        </Card>
        {/* 客户成本(USD) */}
        <Card className="border-slate-200">
          <CardContent className="p-3 flex items-center gap-3">
            <div className="w-9 h-9 rounded-lg bg-amber-50 flex items-center justify-center"><ArrowDownRight className="w-4 h-4 text-amber-600" /></div>
            <div><p className="text-[11px] text-slate-500">{summaryPeriodLabel}客户成本 (USD)</p><p className="text-base font-bold text-amber-600">{fmt(summaryFinance.customerCost)}</p></div>
          </CardContent>
        </Card>
        <Card className="border-slate-200">
          <CardContent className="p-3 flex items-center gap-3">
            <div className="w-9 h-9 rounded-lg bg-cyan-50 flex items-center justify-center"><Receipt className="w-4 h-4 text-cyan-600" /></div>
            <div>
              <p className="text-[11px] text-slate-500">Stripe手续费</p>
              <p className="text-base font-bold text-cyan-600">{fmt(summaryFinance.stripePlatformFee)}</p>
              <p className="text-[11px] text-slate-400">2.9% + $0.30/笔</p>
            </div>
          </CardContent>
        </Card>
        <Card className="border-slate-200">
          <CardContent className="p-3 flex items-center gap-3">
            <div className={`w-9 h-9 rounded-lg ${summaryProfitUsd >= 0 ? 'bg-emerald-50' : 'bg-red-50'} flex items-center justify-center`}>
              <Wallet className={`w-4 h-4 ${summaryProfitUsd >= 0 ? 'text-emerald-600' : 'text-red-600'}`} />
            </div>
            <div><p className="text-[11px] text-slate-500">{summaryPeriodLabel}利润 (USD)</p><p className={`text-base font-bold ${summaryProfitUsd >= 0 ? 'text-emerald-600' : 'text-red-600'}`}>{fmt(summaryProfitUsd)}</p></div>
          </CardContent>
        </Card>
        <Card className="border-slate-200">
          <CardContent className="p-3 flex items-center gap-3">
            <div className="w-9 h-9 rounded-lg bg-red-50 flex items-center justify-center"><AlertTriangle className="w-4 h-4 text-red-600" /></div>
            <div><p className="text-[11px] text-slate-500">总欠款</p><p className="text-base font-bold text-red-600">{fmt(totalOutstanding)}</p></div>
          </CardContent>
        </Card>
        <Card className="border-slate-200">
          <CardContent className="p-3 flex items-center gap-3">
            <div className="w-9 h-9 rounded-lg bg-amber-50 flex items-center justify-center"><Clock className="w-4 h-4 text-amber-600" /></div>
            <div>
              <p className="text-[11px] text-slate-500">到期提醒</p>
              <p className="text-base font-bold">{expiringSubs.length}</p>
              {renewalPendingSubs > 0 && <p className="text-[11px] text-cyan-600">待扣款确认 {renewalPendingSubs}</p>}
            </div>
          </CardContent>
        </Card>
        <Card className="border-slate-200">
          <CardContent className="p-3 flex items-center gap-3">
            <div className="w-9 h-9 rounded-lg bg-blue-50 flex items-center justify-center"><TrendingUp className="w-4 h-4 text-blue-600" /></div>
            <div><p className="text-[11px] text-slate-500">活跃订阅</p><p className="text-base font-bold">{activeSubs}</p></div>
          </CardContent>
        </Card>
      </div>

      {/* Main Tabs */}
      <Tabs value={activeFinanceTab} onValueChange={handleFinanceTabChange} className="w-full">
        <TabsList className="bg-slate-100 flex-wrap h-auto gap-1 p-1">
          <TabsTrigger value="overview" className="text-xs sm:text-sm"><Wallet className="w-3.5 h-3.5 mr-1 hidden sm:inline" />老板总览</TabsTrigger>
          <TabsTrigger value="customer_profit" className="text-xs sm:text-sm"><TrendingUp className="w-3.5 h-3.5 mr-1 hidden sm:inline" />客户利润 ({customerProfitRows.length})</TabsTrigger>
          <TabsTrigger value="receivables" className="text-xs sm:text-sm"><AlertTriangle className="w-3.5 h-3.5 mr-1 hidden sm:inline" />应收欠款 ({receivableRows.length})</TabsTrigger>
          <TabsTrigger value="income" className="text-xs sm:text-sm"><DollarSign className="w-3.5 h-3.5 mr-1 hidden sm:inline" />收入管理 ({filteredPayments.length})</TabsTrigger>
          <TabsTrigger value="customer_expense" className="text-xs sm:text-sm"><Users className="w-3.5 h-3.5 mr-1 hidden sm:inline" />客户支出 ({filteredExpenses.length})</TabsTrigger>
          <TabsTrigger value="company_expense" className="text-xs sm:text-sm"><Building2 className="w-3.5 h-3.5 mr-1 hidden sm:inline" />运营支出 ({filteredCompanyExpenses.length})</TabsTrigger>
          <TabsTrigger value="subscriptions" className="text-xs sm:text-sm"><Receipt className="w-3.5 h-3.5 mr-1 hidden sm:inline" />套餐续费 ({filteredSubscriptions.length})</TabsTrigger>
          <TabsTrigger value="charts" className="text-xs sm:text-sm"><PieChartIcon className="w-3.5 h-3.5 mr-1 hidden sm:inline" />数据分析</TabsTrigger>
          <TabsTrigger value="monthly_detail" className="text-xs sm:text-sm">按月明细</TabsTrigger>
        </TabsList>

        <TabsContent value="overview">
          <div className="space-y-4">
            <div className="grid grid-cols-2 xl:grid-cols-4 gap-3">
              <Card className="border-slate-200"><CardContent className="p-4">
                <p className="text-xs text-slate-500">筛选范围实收</p>
                <p className="mt-1 text-2xl font-bold text-green-600">{fmt(ownerOverview.revenue)}</p>
                <p className="mt-1 text-xs text-slate-400">管理费 {fmt(ownerOverview.managementRevenue)} · 投流 {fmt(ownerOverview.adsRevenue)}</p>
              </CardContent></Card>
              <Card className="border-slate-200"><CardContent className="p-4">
                <p className="text-xs text-slate-500">筛选范围利润 USD</p>
                <p className={`mt-1 text-2xl font-bold ${ownerOverview.profitUsd >= 0 ? 'text-emerald-600' : 'text-red-600'}`}>{fmt(ownerOverview.profitUsd)}</p>
                <p className="mt-1 text-xs text-slate-400">利润率 {(ownerOverview.profitRate * 100).toFixed(1)}%</p>
              </CardContent></Card>
              <Card className="border-slate-200"><CardContent className="p-4">
                <p className="text-xs text-slate-500">扣点/手续费</p>
                <p className="mt-1 text-2xl font-bold text-violet-600">{fmt(ownerOverview.deduction + ownerOverview.stripeFee)}</p>
                <p className="mt-1 text-xs text-slate-400">扣点 {fmt(ownerOverview.deduction)} · Stripe {fmt(ownerOverview.stripeFee)}</p>
              </CardContent></Card>
              <Card className="border-slate-200"><CardContent className="p-4">
                <p className="text-xs text-slate-500">应收未收</p>
                <p className="mt-1 text-2xl font-bold text-red-600">{fmt(ownerOverview.outstanding)}</p>
                <p className="mt-1 text-xs text-slate-400">{ownerOverview.receivableCount} 笔需要跟进</p>
              </CardContent></Card>
            </div>

            <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
              <Card className="border-slate-200 xl:col-span-2">
                <CardHeader className="pb-2"><CardTitle className="text-base">老板行动清单</CardTitle></CardHeader>
                <CardContent className="space-y-3">
                  <div className="grid md:grid-cols-3 gap-3">
                    <div className="rounded-lg bg-amber-50 p-3">
                      <p className="text-xs text-amber-700">客户成本 USD</p>
                      <p className="mt-1 text-lg font-bold text-amber-700">{fmt(ownerOverview.customerCostUsd)}</p>
                      <p className="text-xs text-amber-600">直接影响单客利润</p>
                    </div>
                    <div className="rounded-lg bg-red-50 p-3">
                      <p className="text-xs text-red-700">运营支出 USD</p>
                      <p className="mt-1 text-lg font-bold text-red-700">{fmt(ownerOverview.companyCostUsd)}</p>
                      <p className="text-xs text-red-600">{fmtRMB(ownerOverview.companyCostCny)} 单独统计</p>
                    </div>
                    <div className="rounded-lg bg-blue-50 p-3">
                      <p className="text-xs text-blue-700">30天续费预测</p>
                      <p className="mt-1 text-lg font-bold text-blue-700">{fmt(renewalForecast.d30.amount)}</p>
                      <p className="text-xs text-blue-600">{renewalForecast.d30.count} 个套餐</p>
                    </div>
                  </div>
                  <div className="grid md:grid-cols-3 gap-3 text-sm">
                    <button type="button" onClick={() => handleFinanceTabChange('receivables')} className="rounded-lg border border-red-100 bg-white p-3 text-left hover:bg-red-50">
                      <p className="font-medium text-red-700">先收款</p>
                      <p className="mt-1 text-xs text-slate-500">处理 {ownerOverview.receivableCount} 笔欠款，金额 {fmt(ownerOverview.outstanding)}</p>
                    </button>
                    <button type="button" onClick={() => handleFinanceTabChange('customer_profit')} className="rounded-lg border border-emerald-100 bg-white p-3 text-left hover:bg-emerald-50">
                      <p className="font-medium text-emerald-700">看利润</p>
                      <p className="mt-1 text-xs text-slate-500">找出赚钱客户和亏损客户</p>
                    </button>
                    <button type="button" onClick={() => handleFinanceTabChange('subscriptions')} className="rounded-lg border border-blue-100 bg-white p-3 text-left hover:bg-blue-50">
                      <p className="font-medium text-blue-700">盯续费</p>
                      <p className="mt-1 text-xs text-slate-500">7天 {fmt(renewalForecast.d7.amount)} · 60天 {fmt(renewalForecast.d60.amount)}</p>
                    </button>
                  </div>
                </CardContent>
              </Card>

              <Card className="border-slate-200">
                <CardHeader className="pb-2"><CardTitle className="text-base">客户利润 Top 5</CardTitle></CardHeader>
                <CardContent className="space-y-2">
                  {customerProfitRows.length === 0 ? (
                    <p className="py-8 text-center text-sm text-slate-400">暂无客户利润数据</p>
                  ) : customerProfitRows.slice(0, 5).map((row, index) => (
                    <button
                      key={`${row.customerId || row.customerName}-${index}`}
                      type="button"
                      onClick={() => row.customerId && openCustomerDetail(row.customerId, 'payments')}
                      className="flex w-full items-center justify-between rounded-lg bg-slate-50 px-3 py-2 text-left hover:bg-slate-100"
                    >
                      <div className="min-w-0">
                        <p className="truncate text-sm font-medium text-slate-700">{index + 1}. {row.customerName}</p>
                        <p className="text-xs text-slate-400">收入 {fmt(row.revenue)} · 成本 {fmt(row.customerCostUsd + row.totalFee)}</p>
                      </div>
                      <p className={row.profit >= 0 ? 'text-sm font-bold text-emerald-600' : 'text-sm font-bold text-red-600'}>{fmt(row.profit)}</p>
                    </button>
                  ))}
                </CardContent>
              </Card>
            </div>
          </div>
        </TabsContent>

        <TabsContent value="customer_profit">
          <Card className="border-slate-200">
            <CardContent className="p-0">
              {customerProfitRows.length === 0 ? (
                <p className="text-center text-slate-400 py-12">暂无客户利润数据</p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead><tr className="border-b bg-slate-50 text-left text-slate-500">
                      <th className="px-3 py-2.5 font-medium">客户</th>
                      <th className="px-3 py-2.5 font-medium">实收</th>
                      <th className="px-3 py-2.5 font-medium hidden lg:table-cell">管理费</th>
                      <th className="px-3 py-2.5 font-medium hidden lg:table-cell">投流</th>
                      <th className="px-3 py-2.5 font-medium">扣点/手续费</th>
                      <th className="px-3 py-2.5 font-medium">客户成本</th>
                      <th className="px-3 py-2.5 font-medium">利润</th>
                      <th className="px-3 py-2.5 font-medium hidden md:table-cell">利润率</th>
                      <th className="px-3 py-2.5 font-medium hidden md:table-cell">欠款</th>
                    </tr></thead>
                    <tbody>
                      {paginatedCustomerProfitRows.items.map(row => (
                        <tr key={`${row.customerId || row.customerName}`} className="border-b border-slate-100 hover:bg-slate-50">
                          <td className="px-3 py-2.5 font-medium">
                            {row.customerId ? (
                              <Button type="button" variant="link" className="h-auto p-0 text-left font-medium text-blue-600" onClick={() => openCustomerDetail(row.customerId, 'payments')}>
                                {row.customerName}
                              </Button>
                            ) : row.customerName}
                            <p className="text-xs text-slate-400">{row.paymentCount} 笔收款 · 最近 {row.latestPaymentDate || '-'}</p>
                          </td>
                          <td className="px-3 py-2.5 text-green-600 font-medium">{fmt(row.revenue)}</td>
                          <td className="px-3 py-2.5 hidden lg:table-cell">{fmt(row.managementRevenue)}</td>
                          <td className="px-3 py-2.5 hidden lg:table-cell">{fmt(row.adsRevenue)}</td>
                          <td className="px-3 py-2.5 text-violet-600">{fmt(row.totalFee)}</td>
                          <td className="px-3 py-2.5 text-amber-600">
                            {fmt(row.customerCostUsd)}
                            {row.customerCostCny > 0 && <p className="text-xs text-slate-400">{fmtRMB(row.customerCostCny)}</p>}
                          </td>
                          <td className={row.profit >= 0 ? 'px-3 py-2.5 font-bold text-emerald-600' : 'px-3 py-2.5 font-bold text-red-600'}>{fmt(row.profit)}</td>
                          <td className="px-3 py-2.5 hidden md:table-cell">{(row.profitRate * 100).toFixed(1)}%</td>
                          <td className="px-3 py-2.5 hidden md:table-cell">{row.outstanding > 0 ? <span className="text-red-600">{fmt(row.outstanding)}</span> : '-'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              {customerProfitRows.length > 0 && <PaginationFooter pageKey="customer_profit" data={paginatedCustomerProfitRows} />}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="receivables">
          <Card className="border-slate-200">
            <CardContent className="p-0">
              {receivableRows.length === 0 ? (
                <p className="text-center text-slate-400 py-12">暂无应收欠款</p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead><tr className="border-b bg-slate-50 text-left text-slate-500">
                      <th className="px-3 py-2.5 font-medium">客户</th>
                      <th className="px-3 py-2.5 font-medium">产品</th>
                      <th className="px-3 py-2.5 font-medium">应收</th>
                      <th className="px-3 py-2.5 font-medium">实收</th>
                      <th className="px-3 py-2.5 font-medium">欠款</th>
                      <th className="px-3 py-2.5 font-medium">欠款天数</th>
                      <th className="px-3 py-2.5 font-medium hidden md:table-cell">负责人</th>
                      <th className="px-3 py-2.5 font-medium hidden md:table-cell">日期</th>
                    </tr></thead>
                    <tbody>
                      {paginatedReceivableRows.items.map(row => (
                        <tr key={row.id} className="border-b border-slate-100 hover:bg-slate-50">
                          <td className="px-3 py-2.5 font-medium">
                            <Button type="button" variant="link" className="h-auto p-0 text-left font-medium text-blue-600" onClick={() => openCustomerDetail(row.customer_id, 'payments')}>
                              {row.customerName}
                            </Button>
                          </td>
                          <td className="px-3 py-2.5 max-w-[180px] truncate">{row.product_name || '-'}</td>
                          <td className="px-3 py-2.5">{fmt(row.amountDue)}</td>
                          <td className="px-3 py-2.5 text-green-600">{fmt(row.amountPaid)}</td>
                          <td className="px-3 py-2.5 font-bold text-red-600">{fmt(row.outstanding)}</td>
                          <td className="px-3 py-2.5">
                            <Badge className={row.overdueDays >= 30 ? 'bg-red-100 text-red-700' : row.overdueDays >= 7 ? 'bg-amber-100 text-amber-700' : 'bg-slate-100 text-slate-600'}>
                              {row.overdueDays} 天
                            </Badge>
                          </td>
                          <td className="px-3 py-2.5 hidden md:table-cell">{row.salesPerson}</td>
                          <td className="px-3 py-2.5 hidden md:table-cell text-slate-500">{row.paymentDate || '-'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              {receivableRows.length > 0 && <PaginationFooter pageKey="receivables" data={paginatedReceivableRows} />}
            </CardContent>
          </Card>
        </TabsContent>

        {/* ── Income Tab ── */}
        <TabsContent value="income">
          <Card className="border-slate-200">
            <CardContent className="p-0">
              {loading ? (
                <div className="flex items-center justify-center py-12"><div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600" /></div>
              ) : filteredPayments.length === 0 ? (
                <p className="text-center text-slate-400 py-12">{dateFilterMode !== 'all' ? '该时间段内暂无收款记录' : '暂无收款记录，点击右上角「录入收款」开始添加'}</p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b bg-slate-50 text-left text-slate-500">
                        <th className="px-3 py-2.5 font-medium">客户</th>
                        <th className="px-3 py-2.5 font-medium">收入类型</th>
                        <th className="px-3 py-2.5 font-medium">产品</th>
                        <th className="px-3 py-2.5 font-medium">应收</th>
                        <th className="px-3 py-2.5 font-medium">实收</th>
                        <th className="px-3 py-2.5 font-medium hidden xl:table-cell">管理费</th>
                        <th className="px-3 py-2.5 font-medium hidden xl:table-cell">投流充值</th>
                        <th className="px-3 py-2.5 font-medium hidden lg:table-cell">Stripe手续费</th>
                        <th className="px-3 py-2.5 font-medium hidden xl:table-cell">净入账</th>
                        <th className="px-3 py-2.5 font-medium">欠款</th>
                        <th className="px-3 py-2.5 font-medium hidden md:table-cell">模式</th>
                        <th className="px-3 py-2.5 font-medium hidden lg:table-cell">方式</th>
                        <th className="px-3 py-2.5 font-medium hidden md:table-cell">日期</th>
                        <th className="px-3 py-2.5 font-medium hidden lg:table-cell">发票</th>
                        <th className="px-3 py-2.5 font-medium w-20">操作</th>
                      </tr>
                    </thead>
                    <tbody>
                      {paginatedPayments.items.map(p => {
                        const displayIncomeType = getPaymentDisplayIncomeType(p);
                        return (
                        <tr key={p.id} className="border-b border-slate-100 hover:bg-slate-50">
                          <td className="px-3 py-2.5 font-medium">
                            <Button
                              type="button"
                              variant="link"
                              className="h-auto p-0 text-left font-medium text-blue-600 hover:text-blue-700"
                              onClick={() => openCustomerDetail(p.customer_id, 'payments')}
                            >
                              {p.customer_name || customerMap[p.customer_id]?.business_name || '-'}
                            </Button>
                          </td>
                          <td className="px-3 py-2.5">
                            <Badge style={{ backgroundColor: `${INCOME_TYPE_COLORS[displayIncomeType] || '#94a3b8'}20`, color: INCOME_TYPE_COLORS[displayIncomeType] || '#94a3b8' }} className="text-xs">
                              {incomeTypeLabels[displayIncomeType] || displayIncomeType || '-'}
                            </Badge>
                          </td>
                          <td className="px-3 py-2.5 max-w-[160px] truncate">{p.product_name}</td>
                          <td className="px-3 py-2.5">{fmt(p.amount_due)}</td>
                          <td className="px-3 py-2.5 text-green-600 font-medium">{fmt(p.amount_paid)}</td>
                          <td className="px-3 py-2.5 hidden xl:table-cell">{getManagementRevenueAmount(p) > 0 ? fmt(getManagementRevenueAmount(p)) : '-'}</td>
                          <td className="px-3 py-2.5 hidden xl:table-cell">{getAdsRechargeAmount(p) > 0 ? fmt(getAdsRechargeAmount(p)) : '-'}</td>
                          <td className="px-3 py-2.5 text-cyan-600 hidden lg:table-cell">
                            {calculateStripePlatformFee(p) > 0 ? fmt(calculateStripePlatformFee(p)) : '-'}
                          </td>
                          <td className="px-3 py-2.5 hidden xl:table-cell">{fmt(getStoredMoney(p.net_amount) ?? Math.max(Number(p.amount_paid || 0) - calculateStripePlatformFee(p), 0))}</td>
                          <td className="px-3 py-2.5">{(p.outstanding_amount || 0) > 0 ? <span className="text-red-600 font-medium">{fmt(p.outstanding_amount)}</span> : '-'}</td>
                          <td className="px-3 py-2.5 hidden md:table-cell">
                            <Badge
                              style={{
                                backgroundColor: `${PAYMENT_MODE_COLORS[inferPaymentModeKey(p)] || '#94a3b8'}20`,
                                color: PAYMENT_MODE_COLORS[inferPaymentModeKey(p)] || '#94a3b8',
                              }}
                              className="text-xs"
                            >
                              {getPaymentModeLabel(p, payModeLabels)}
                            </Badge>
                          </td>
                          <td className="px-3 py-2.5 text-slate-500 hidden lg:table-cell">{getPaymentMethodLabel(p, payMethodLabels)}</td>
                          <td className="px-3 py-2.5 text-slate-500 hidden md:table-cell">{p.payment_date?.slice(0, 10)}</td>
                          <td className="px-3 py-2.5 hidden lg:table-cell">{p.has_invoice ? '✅' : '-'}</td>
                          <td className="px-3 py-2.5">
                            <div className="flex gap-1">
                              <Button size="sm" variant="ghost" className="h-7 w-7 p-0 text-slate-500 hover:text-blue-600" onClick={() => openEditPayment(p)}><Edit className="w-3.5 h-3.5" /></Button>
                              <Button size="sm" variant="ghost" className="h-7 w-7 p-0 text-slate-500 hover:text-red-600" onClick={() => setDeleteTarget({ type: 'payment', item: p })}><Trash2 className="w-3.5 h-3.5" /></Button>
                            </div>
                          </td>
                        </tr>
                      );})}
                    </tbody>
                  </table>
                </div>
              )}
              {filteredPayments.length > 0 && <PaginationFooter pageKey="income" data={paginatedPayments} />}
            </CardContent>
          </Card>
        </TabsContent>

        {/* ── Customer Expense Tab ── */}
        <TabsContent value="customer_expense">
          <Card className="border-slate-200">
            <CardContent className="p-4">
              <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 mb-4">
                <div className="flex items-center gap-3">
                  <div className="flex items-center gap-2">
                    <Users className="w-4 h-4 text-slate-500" />
                    <span className="text-sm font-medium text-slate-600">费用月份:</span>
                    <Input type="month" value={expenseMonth} onChange={e => setExpenseMonth(e.target.value)} className="w-[180px] h-9" />
                  </div>
                  {expenseMonth && <Button variant="ghost" size="sm" className="h-8 text-xs text-slate-500" onClick={() => setExpenseMonth('')}>查看全部</Button>}
                </div>
                <div className="flex items-center gap-2">
                  {canManageCustomerExpenseTypes && (
                    <Button type="button" variant="outline" size="sm" onClick={openCustomerExpenseTypeManager}>
                      管理类型
                    </Button>
                  )}
                  <Button size="sm" onClick={() => { setExpenseForm({ ...emptyExpenseForm, expense_month: expenseMonth }); setEditingExpenseId(null); setShowExpenseForm(true); }} className="bg-blue-600 hover:bg-blue-700">
                    <Plus className="w-4 h-4 mr-1" /> 录入客户支出
                  </Button>
                </div>
              </div>

              {/* Summary */}
              <div className="grid grid-cols-2 sm:grid-cols-5 gap-3 mb-4">
                <div className="p-3 bg-slate-50 rounded-lg">
                  <p className="text-xs text-slate-500">总费用 USD</p>
                  <p className="text-lg font-bold text-slate-800">{fmt(totalCustomerExpense)}</p>
                </div>
                {customerExpenseByType.map(et => (
                  <div key={et.type} className="p-3 bg-slate-50 rounded-lg">
                    <p className="text-xs text-slate-500">{et.name}</p>
                    <p className="text-lg font-bold" style={{ color: pickColorByKey(et.type, PIE_COLORS, CUSTOMER_EXPENSE_COLORS) }}>{fmt(et.amount)}</p>
                  </div>
                ))}
              </div>

              {filteredExpenses.length === 0 ? (
                <p className="text-center text-slate-400 py-12">{expenseMonth ? `${expenseMonth} 暂无客户支出记录` : '暂无客户支出记录'}</p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b bg-slate-50 text-left text-slate-500">
                        <th className="px-3 py-2.5 font-medium">客户</th>
                        <th className="px-3 py-2.5 font-medium">费用类型</th>
                        <th className="px-3 py-2.5 font-medium">金额</th>
                        <th className="px-3 py-2.5 font-medium">币种</th>
                        <th className="px-3 py-2.5 font-medium">月份</th>
                        <th className="px-3 py-2.5 font-medium hidden md:table-cell">备注</th>
                        <th className="px-3 py-2.5 font-medium w-20">操作</th>
                      </tr>
                    </thead>
                    <tbody>
                      {paginatedExpenses.items.map(e => (
                        <tr key={e.id} className="border-b border-slate-100 hover:bg-slate-50">
                          <td className="px-3 py-2.5 font-medium">
                            <Button
                              type="button"
                              variant="link"
                              className="h-auto p-0 text-left font-medium text-blue-600 hover:text-blue-700"
                              onClick={() => openCustomerDetail(e.customer_id, 'payments')}
                            >
                              {e.customer_name || customerMap[e.customer_id]?.business_name || '-'}
                            </Button>
                          </td>
                          <td className="px-3 py-2.5">
                            <Badge style={{ backgroundColor: `${pickColorByKey(e.expense_type, PIE_COLORS, CUSTOMER_EXPENSE_COLORS)}20`, color: pickColorByKey(e.expense_type, PIE_COLORS, CUSTOMER_EXPENSE_COLORS) }} className="text-xs">
                              {customerExpenseTypeLabels[e.expense_type] || e.expense_type}
                            </Badge>
                          </td>
                          <td className="px-3 py-2.5 font-medium">{formatMoney(Number(e.amount || 0), getCustomerExpenseCurrency(e))}</td>
                          <td className="px-3 py-2.5 text-slate-500">{getCustomerExpenseCurrency(e)}</td>
                          <td className="px-3 py-2.5 text-slate-500">{e.expense_month}</td>
                          <td className="px-3 py-2.5 text-slate-500 hidden md:table-cell max-w-[200px] truncate">{e.notes || '-'}</td>
                          <td className="px-3 py-2.5">
                            <div className="flex gap-1">
                              <Button size="sm" variant="ghost" className="h-7 w-7 p-0 text-slate-500 hover:text-blue-600" onClick={() => openEditExpense(e)}><Edit className="w-3.5 h-3.5" /></Button>
                              <Button size="sm" variant="ghost" className="h-7 w-7 p-0 text-slate-500 hover:text-red-600" onClick={() => setDeleteExpenseTarget(e)}><Trash2 className="w-3.5 h-3.5" /></Button>
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              {filteredExpenses.length > 0 && <PaginationFooter pageKey="customer_expense" data={paginatedExpenses} />}
            </CardContent>
          </Card>
        </TabsContent>

        {/* ── Company Expense Tab ── */}
        <TabsContent value="company_expense">
          <Card className="border-slate-200">
            <CardContent className="p-4">
              <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 mb-4">
                <div className="flex items-center gap-3">
                  <div className="flex items-center gap-2">
                    <Building2 className="w-4 h-4 text-slate-500" />
                    <span className="text-sm font-medium text-slate-600">支出月份:</span>
                    <Input type="month" value={companyExpenseMonth} onChange={e => setCompanyExpenseMonth(e.target.value)} className="w-[180px] h-9" />
                  </div>
                  <NativeSelect
                    value={companyExpenseCurrencyFilter}
                    onChange={v => setCompanyExpenseCurrencyFilter(v as 'all' | CurrencyCode)}
                    options={[
                      { value: 'all', label: '全部币种' },
                      { value: 'USD', label: '美元 USD' },
                      { value: 'CNY', label: '人民币 CNY' },
                    ]}
                    className="w-[150px]"
                  />
                  {companyExpenseMonth && <Button variant="ghost" size="sm" className="h-8 text-xs text-slate-500" onClick={() => setCompanyExpenseMonth('')}>查看全部</Button>}
                </div>
                <div className="flex items-center gap-2">
                  {canManageCompanyExpenseTypes && (
                    <Button type="button" variant="outline" size="sm" onClick={openCompanyExpenseTypeManager}>
                      管理类型
                    </Button>
                  )}
                  <Button size="sm" onClick={() => { setCompanyExpenseForm({ ...emptyCompanyExpenseForm, category: defaultCompanyExpenseType, currency: companyExpenseCurrencyFilter === 'all' ? 'USD' : companyExpenseCurrencyFilter, expense_month: companyExpenseMonth }); setEditingCompanyExpenseId(null); setShowCompanyExpenseForm(true); }} className="bg-blue-600 hover:bg-blue-700">
                    <Plus className="w-4 h-4 mr-1" /> 录入运营支出
                  </Button>
                </div>
              </div>

              {/* Summary */}
              <div className="grid grid-cols-2 sm:grid-cols-5 gap-3 mb-4">
                <div className="p-3 bg-slate-50 rounded-lg">
                  <p className="text-xs text-slate-500">总支出 USD</p>
                  <p className="text-lg font-bold text-slate-800">{fmt(totalCompanyExpenseByCurrency.USD)}</p>
                  <p className="text-[11px] text-slate-400">计入 USD 利润</p>
                </div>
                <div className="p-3 bg-slate-50 rounded-lg">
                  <p className="text-xs text-slate-500">总支出 CNY</p>
                  <p className="text-lg font-bold text-slate-800">{fmtRMB(totalCompanyExpenseByCurrency.CNY)}</p>
                  <p className="text-[11px] text-slate-400">暂不混入美元利润</p>
                </div>
                {companyExpenseByType.map(et => (
                  <div key={`${et.currency}:${et.type}`} className="p-3 bg-slate-50 rounded-lg">
                    <p className="text-xs text-slate-500">{et.name} · {et.currency}</p>
                    <p className="text-lg font-bold" style={{ color: pickColorByKey(et.type, PIE_COLORS, COMPANY_EXPENSE_COLORS) }}>{formatMoney(et.amount, et.currency)}</p>
                  </div>
                ))}
              </div>

              {filteredCompanyExpenses.length === 0 ? (
                <p className="text-center text-slate-400 py-12">{companyExpenseMonth ? `${companyExpenseMonth} 暂无运营支出记录` : '暂无运营支出记录'}</p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b bg-slate-50 text-left text-slate-500">
                        <th className="px-3 py-2.5 font-medium">支出类型</th>
                        <th className="px-3 py-2.5 font-medium">金额</th>
                        <th className="px-3 py-2.5 font-medium">币种</th>
                        <th className="px-3 py-2.5 font-medium">月份</th>
                        <th className="px-3 py-2.5 font-medium hidden md:table-cell">支出日期</th>
                        <th className="px-3 py-2.5 font-medium hidden md:table-cell">备注</th>
                        <th className="px-3 py-2.5 font-medium w-20">操作</th>
                      </tr>
                    </thead>
                    <tbody>
                      {paginatedCompanyExpenses.items.map(e => {
                        const currency = getCompanyExpenseCurrency(e);
                        return (
                        <tr key={e.id} className="border-b border-slate-100 hover:bg-slate-50">
                          <td className="px-3 py-2.5">
                            <Badge
                              style={{
                                backgroundColor: `${pickColorByKey(e.category, PIE_COLORS, COMPANY_EXPENSE_COLORS)}20`,
                                color: pickColorByKey(e.category, PIE_COLORS, COMPANY_EXPENSE_COLORS),
                              }}
                              className="text-xs"
                            >
                              {companyExpenseTypeLabels[e.category] || e.category_name || e.category}
                            </Badge>
                          </td>
                          <td className="px-3 py-2.5 font-medium">{formatMoney(Number(e.amount || 0), currency)}</td>
                          <td className="px-3 py-2.5 text-slate-500">{currency}</td>
                          <td className="px-3 py-2.5 text-slate-500">{e.expense_month}</td>
                          <td className="px-3 py-2.5 text-slate-500 hidden md:table-cell">{e.expense_date?.slice(0, 10) || '-'}</td>
                          <td className="px-3 py-2.5 text-slate-500 hidden md:table-cell max-w-[200px] truncate">{e.notes || '-'}</td>
                          <td className="px-3 py-2.5">
                            <div className="flex gap-1">
                              <Button size="sm" variant="ghost" className="h-7 w-7 p-0 text-slate-500 hover:text-blue-600" onClick={() => openEditCompanyExpense(e)}><Edit className="w-3.5 h-3.5" /></Button>
                              <Button size="sm" variant="ghost" className="h-7 w-7 p-0 text-slate-500 hover:text-red-600" onClick={() => setDeleteCompanyExpenseTarget(e)}><Trash2 className="w-3.5 h-3.5" /></Button>
                            </div>
                          </td>
                        </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
              {filteredCompanyExpenses.length > 0 && <PaginationFooter pageKey="company_expense" data={paginatedCompanyExpenses} />}
            </CardContent>
          </Card>
        </TabsContent>

        {/* ── Subscriptions Tab ── */}
        <TabsContent value="subscriptions">
          <Card className="border-slate-200">
            <CardContent className="p-0">
              {filteredSubscriptions.length === 0 ? (
                <p className="text-center text-slate-400 py-12">{dateFilterMode !== 'all' ? '该时间段内暂无套餐信息' : '暂无套餐信息'}</p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b bg-slate-50 text-left text-slate-500">
                        <th className="px-3 py-2.5 font-medium">客户</th>
                        <th className="px-3 py-2.5 font-medium">套餐</th>
                        <th className="px-3 py-2.5 font-medium">价格</th>
                        <th className="px-3 py-2.5 font-medium">周期</th>
                        <th className="px-3 py-2.5 font-medium hidden md:table-cell">到期日</th>
                        <th className="px-3 py-2.5 font-medium">续费开关</th>
                        <th className="px-3 py-2.5 font-medium">剩余天数</th>
                        <th className="px-3 py-2.5 font-medium">状态</th>
                        <th className="px-3 py-2.5 font-medium hidden lg:table-cell">续费负责</th>
                        <th className="px-3 py-2.5 font-medium w-40">操作</th>
                      </tr>
                    </thead>
                    <tbody>
                      {paginatedSubscriptions.items.map(s => {
                        const remainDays = getSubscriptionRemainingDays(s);
                        return (
                          <tr key={s.id} className={`border-b border-slate-100 hover:bg-slate-50 ${remainDays !== null && remainDays <= 0 ? 'bg-red-50/50' : remainDays !== null && remainDays <= 7 ? 'bg-amber-50/50' : ''}`}>
                            <td className="px-3 py-2.5 font-medium">
                              <Button
                                type="button"
                                variant="link"
                                className="h-auto p-0 text-left font-medium text-blue-600 hover:text-blue-700"
                                onClick={() => openCustomerDetail(s.customer_id, 'renewals')}
                              >
                                {s.customer_name || customerMap[s.customer_id]?.business_name || '-'}
                              </Button>
                            </td>
                            <td className="px-3 py-2.5">{s.package_name}</td>
                            <td className="px-3 py-2.5">{fmt(s.package_price)}</td>
                            <td className="px-3 py-2.5 text-slate-500">{cycleLabels[s.billing_cycle] || s.billing_cycle}</td>
                            <td className="px-3 py-2.5 text-slate-500 hidden md:table-cell">{s.end_date?.slice(0, 10)}</td>
                            <td className="px-3 py-2.5">
                              <div className="flex min-w-32 flex-col gap-1.5">
                                <div className="flex items-center gap-2">
                                  <Switch
                                    checked={Boolean(s.auto_renew)}
                                    onCheckedChange={checked => handleToggleSubscriptionAutoRenew(s, checked)}
                                    disabled={updatingSubscriptionId === Number(s.id)}
                                  />
                                  <span className="text-xs font-medium text-slate-700">
                                    {s.auto_renew ? '订阅续费' : '停止续费'}
                                  </span>
                                </div>
                                {s.auto_renew ? (
                                  <Badge className="w-fit bg-cyan-100 text-cyan-700 text-xs">到期确认续费</Badge>
                                ) : (
                                  <span className="text-xs text-slate-400">不会自动进入续费确认</span>
                                )}
                                {s.next_payment_date && <div className="text-xs text-slate-400">下次付款: {s.next_payment_date.slice(0, 10)}</div>}
                              </div>
                            </td>
                            <td className="px-3 py-2.5">
                              {remainDays !== null ? (
                                remainDays <= 0 ? <span className="text-red-600 font-medium">已过期 {Math.abs(remainDays)} 天</span>
                                : remainDays <= 7 ? <span className="text-amber-600 font-medium">⚠️ 剩余 {remainDays} 天</span>
                                : <span className="text-slate-600">{remainDays} 天</span>
                              ) : '-'}
                            </td>
                            <td className="px-3 py-2.5"><Badge className={`text-xs ${subStatusColors[s.status] || subStatusColors.active}`}>{getSubscriptionStatusLabel(s.status)}</Badge></td>
                            <td className="px-3 py-2.5 text-slate-500 hidden lg:table-cell">{s.renewal_person || '-'}</td>
                            <td className="px-3 py-2.5">
                              <div className="flex items-center gap-1.5">
                                {s.auto_renew && s.status === 'renewal_pending' && (
                                  <Button
                                    size="sm"
                                    className="h-7 bg-cyan-600 px-2 text-xs hover:bg-cyan-700"
                                    onClick={() => handleConfirmSubscriptionRenewal(s)}
                                    disabled={confirmingRenewalId === Number(s.id)}
                                  >
                                    <CheckCircle2 className="w-3.5 h-3.5 mr-1" />
                                    {confirmingRenewalId === Number(s.id) ? '确认中' : '确认续费'}
                                  </Button>
                                )}
                                <Button size="sm" variant="ghost" className="h-7 w-7 p-0 text-slate-500 hover:text-red-600" onClick={() => setDeleteTarget({ type: 'subscription', item: s })}><Trash2 className="w-3.5 h-3.5" /></Button>
                              </div>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
              {filteredSubscriptions.length > 0 && <PaginationFooter pageKey="subscriptions" data={paginatedSubscriptions} />}
            </CardContent>
          </Card>
        </TabsContent>

        {/* ── Charts Tab ── */}
        <TabsContent value="charts">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {/* Income vs Expense Trend */}
            <Card className="border-slate-200 lg:col-span-2">
              <CardHeader className="pb-2">
                <CardTitle className="text-base font-semibold text-slate-700">收支趋势（近12个月）</CardTitle>
              </CardHeader>
              <CardContent>
                {payments.length === 0 ? (
                  <p className="text-center text-slate-400 py-12">暂无数据</p>
                ) : (
                  <ResponsiveContainer width="100%" height={320}>
                    <BarChart data={monthlyTrendData} margin={{ top: 5, right: 20, left: 0, bottom: 5 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                      <XAxis dataKey="label" tick={{ fontSize: 12, fill: '#64748b' }} />
                      <YAxis tick={{ fontSize: 12, fill: '#64748b' }} tickFormatter={(v) => `$${v >= 1000 ? `${(v / 1000).toFixed(0)}k` : v}`} />
                      <Tooltip
                        contentStyle={{ borderRadius: 8, border: '1px solid #e2e8f0', boxShadow: '0 2px 8px rgba(0,0,0,0.08)' }}
                        formatter={(value: number, name: string) => {
                          const labels: Record<string, string> = {
                            income: '收入(USD)',
                            customerExp: '客户支出(USD)',
                            stripeFee: 'Stripe手续费(USD)',
                            companyExpUsd: '运营支出(USD)',
                            companyExpCny: '运营支出(CNY)',
                            profitUsd: '利润(USD)',
                          };
                          const formatted = name === 'companyExpCny' ? fmtRMB(value) : fmt(value);
                          return [formatted, labels[name] || name];
                        }}
                      />
                      <Legend formatter={(value) => {
                        const labels: Record<string, string> = {
                          income: '收入(USD)',
                          customerExp: '客户支出(USD)',
                          stripeFee: 'Stripe手续费(USD)',
                          companyExpUsd: '运营支出(USD)',
                          companyExpCny: '运营支出(CNY)',
                          profitUsd: '利润(USD)',
                        };
                        return <span className="text-xs text-slate-600">{labels[value] || value}</span>;
                      }} />
                      <Bar dataKey="income" fill="#10b981" radius={[4, 4, 0, 0]} maxBarSize={24} />
                      <Bar dataKey="customerExp" fill="#f59e0b" radius={[4, 4, 0, 0]} maxBarSize={24} />
                      <Bar dataKey="stripeFee" fill="#06b6d4" radius={[4, 4, 0, 0]} maxBarSize={24} />
                      <Bar dataKey="companyExpUsd" fill="#ef4444" radius={[4, 4, 0, 0]} maxBarSize={24} />
                      <Bar dataKey="companyExpCny" fill="#94a3b8" radius={[4, 4, 0, 0]} maxBarSize={24} />
                      <Line type="monotone" dataKey="profitUsd" stroke="#3b82f6" strokeWidth={2.5} dot={{ r: 3 }} />
                    </BarChart>
                  </ResponsiveContainer>
                )}
              </CardContent>
            </Card>

            {/* Income by Type Pie */}
            <Card className="border-slate-200">
              <CardHeader className="pb-2">
                <CardTitle className="text-base font-semibold text-slate-700">收入类型分布</CardTitle>
              </CardHeader>
              <CardContent>
                {incomeByTypeData.length === 0 ? (
                  <p className="text-center text-slate-400 py-12">暂无数据</p>
                ) : (
                  <ResponsiveContainer width="100%" height={300}>
                    <PieChart>
                      <Pie data={incomeByTypeData} cx="50%" cy="50%" innerRadius={60} outerRadius={100} paddingAngle={2} dataKey="value"
                        label={({ name, percent }) => `${name} ${(percent * 100).toFixed(0)}%`}
                        labelLine={{ stroke: '#94a3b8', strokeWidth: 1 }}>
                        {incomeByTypeData.map((d) => (
                          <Cell key={d.type} fill={INCOME_TYPE_COLORS[d.type] || PIE_COLORS[0]} />
                        ))}
                      </Pie>
                      <Tooltip contentStyle={{ borderRadius: 8, border: '1px solid #e2e8f0' }} formatter={(value: number) => [fmt(value), '收入']} />
                    </PieChart>
                  </ResponsiveContainer>
                )}
              </CardContent>
            </Card>

            {/* Product Revenue Pie */}
            <Card className="border-slate-200">
              <CardHeader className="pb-2">
                <CardTitle className="text-base font-semibold text-slate-700">产品收入占比</CardTitle>
              </CardHeader>
              <CardContent>
                {productRevenueData.length === 0 ? (
                  <p className="text-center text-slate-400 py-12">暂无数据</p>
                ) : (
                  <ResponsiveContainer width="100%" height={300}>
                    <PieChart>
                      <Pie data={productRevenueData} cx="50%" cy="50%" innerRadius={60} outerRadius={100} paddingAngle={2} dataKey="value"
                        label={({ name, percent }) => `${name} ${(percent * 100).toFixed(0)}%`}
                        labelLine={{ stroke: '#94a3b8', strokeWidth: 1 }}>
                        {productRevenueData.map((_, index) => (
                          <Cell key={`cell-${index}`} fill={PIE_COLORS[index % PIE_COLORS.length]} />
                        ))}
                      </Pie>
                      <Tooltip contentStyle={{ borderRadius: 8, border: '1px solid #e2e8f0' }} formatter={(value: number) => [fmt(value), '收入']} />
                      <Legend verticalAlign="bottom" height={36} formatter={(value) => <span className="text-xs text-slate-600">{value}</span>} />
                    </PieChart>
                  </ResponsiveContainer>
                )}
              </CardContent>
            </Card>

            {/* Payment Mode Summary */}
            <Card className="border-slate-200">
              <CardHeader className="pb-2">
                <CardTitle className="text-base font-semibold text-slate-700">收款模式结构</CardTitle>
              </CardHeader>
              <CardContent>
                {payModeData.length === 0 ? (
                  <p className="text-center text-slate-400 py-12">暂无数据</p>
                ) : (
                  <div className="space-y-3">
                    {payModeData.map((mode) => (
                      <div key={mode.mode} className="flex items-center justify-between p-3 rounded-lg bg-slate-50">
                        <div className="flex items-center gap-2">
                          <span
                            className="w-3 h-3 rounded-full"
                            style={{ backgroundColor: PAYMENT_MODE_COLORS[mode.mode] || '#94a3b8' }}
                          />
                          <span className="text-sm font-medium text-slate-700">{mode.name}</span>
                        </div>
                        <div className="text-right">
                          <div className="text-sm font-semibold text-slate-800">{fmt(mode.amount)}</div>
                          <div className="text-xs text-slate-500">{mode.count} 笔</div>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>

            {/* Payment Method Pie */}
            <Card className="border-slate-200">
              <CardHeader className="pb-2">
                <CardTitle className="text-base font-semibold text-slate-700">收款渠道分布</CardTitle>
              </CardHeader>
              <CardContent>
                {payMethodData.length === 0 ? (
                  <p className="text-center text-slate-400 py-12">暂无数据</p>
                ) : (
                  <>
                    <ResponsiveContainer width="100%" height={260}>
                      <PieChart>
                        <Pie data={payMethodData} cx="50%" cy="50%" innerRadius={55} outerRadius={90} paddingAngle={2} dataKey="amount"
                          label={({ name, percent }) => `${name} ${(percent * 100).toFixed(0)}%`}
                          labelLine={{ stroke: '#94a3b8', strokeWidth: 1 }}>
                          {payMethodData.map((d) => (
                            <Cell key={`pm-${d.method}`} fill={PAY_METHOD_COLORS[d.method] || '#94a3b8'} />
                          ))}
                        </Pie>
                        <Tooltip contentStyle={{ borderRadius: 8, border: '1px solid #e2e8f0' }}
                          formatter={(value: number, _name: string, props: any) => {
                            const entry = props.payload;
                            return [`${fmt(value)}（${entry.count}笔）`, entry.name];
                          }} />
                      </PieChart>
                    </ResponsiveContainer>
                    <div className="mt-2 space-y-1.5">
                      {payMethodData.map(d => {
                        const totalAmount = payMethodData.reduce((s, x) => s + x.amount, 0);
                        const pct = totalAmount > 0 ? ((d.amount / totalAmount) * 100).toFixed(1) : '0';
                        return (
                          <div key={d.method} className="flex items-center justify-between text-xs px-1">
                            <div className="flex items-center gap-2">
                              <span className="w-2.5 h-2.5 rounded-full inline-block" style={{ backgroundColor: PAY_METHOD_COLORS[d.method] || '#94a3b8' }} />
                              <span className="text-slate-600">{d.name}</span>
                            </div>
                            <div className="flex items-center gap-3">
                              <span className="text-slate-500">{d.count}笔</span>
                              <span className="font-medium text-slate-700 w-20 text-right">{fmt(d.amount)}</span>
                              <span className="text-slate-400 w-12 text-right">{pct}%</span>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </>
                )}
              </CardContent>
            </Card>

            {/* Customer Revenue Ranking */}
            <Card className="border-slate-200">
              <CardHeader className="pb-2">
                <CardTitle className="text-base font-semibold text-slate-700">客户收入排行榜（Top 10）</CardTitle>
              </CardHeader>
              <CardContent>
                {customerRevenueData.length === 0 ? (
                  <p className="text-center text-slate-400 py-12">暂无数据</p>
                ) : (
                  <ResponsiveContainer width="100%" height={Math.max(260, customerRevenueData.length * 36 + 40)}>
                    <BarChart data={customerRevenueData} layout="vertical" margin={{ top: 5, right: 30, left: 20, bottom: 5 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" horizontal={false} />
                      <XAxis type="number" tick={{ fontSize: 12, fill: '#64748b' }} tickFormatter={(v) => `$${v >= 1000 ? `${(v / 1000).toFixed(0)}k` : v}`} />
                      <YAxis type="category" dataKey="name" tick={{ fontSize: 11, fill: '#334155' }} width={110} />
                      <Tooltip contentStyle={{ borderRadius: 8, border: '1px solid #e2e8f0' }} formatter={(value: number) => [fmt(value), '收入金额']} cursor={{ fill: 'rgba(59, 130, 246, 0.06)' }} />
                      <Bar dataKey="value" radius={[0, 6, 6, 0]} maxBarSize={28}>
                        {customerRevenueData.map((_, index) => (
                          <Cell key={`bar-${index}`} fill={index === 0 ? '#f59e0b' : index === 1 ? '#3b82f6' : index === 2 ? '#10b981' : '#94a3b8'} />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                )}
              </CardContent>
            </Card>

            {/* Company Expense Breakdown */}
            <Card className="border-slate-200 lg:col-span-2">
              <CardHeader className="pb-2">
                <CardTitle className="text-base font-semibold text-slate-700">运营支出明细</CardTitle>
              </CardHeader>
              <CardContent>
                {companyExpenseByType.length === 0 ? (
                  <p className="text-center text-slate-400 py-12">暂无运营支出数据</p>
                ) : (
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <ResponsiveContainer width="100%" height={260}>
                      <PieChart>
                        <Pie data={companyExpenseByType.map(d => ({ name: `${d.name} (${d.currency})`, value: d.amount, type: d.type, currency: d.currency }))} cx="50%" cy="50%" innerRadius={55} outerRadius={90} paddingAngle={2} dataKey="value"
                          label={({ name, percent }) => `${name} ${(percent * 100).toFixed(0)}%`}
                          labelLine={{ stroke: '#94a3b8', strokeWidth: 1 }}>
                          {companyExpenseByType.map((d) => (
                            <Cell key={`${d.currency}:${d.type}`} fill={pickColorByKey(d.type, PIE_COLORS, COMPANY_EXPENSE_COLORS)} />
                          ))}
                        </Pie>
                        <Tooltip
                          contentStyle={{ borderRadius: 8, border: '1px solid #e2e8f0' }}
                          formatter={(value: number, _name: string, props: any) => [formatMoney(value, props.payload.currency), '支出']}
                        />
                      </PieChart>
                    </ResponsiveContainer>
                    <div className="space-y-2">
                      {companyExpenseByType.map(d => {
                        const currencyTotal = totalCompanyExpenseByCurrency[d.currency] || 0;
                        const pct = currencyTotal > 0 ? ((d.amount / currencyTotal) * 100).toFixed(1) : '0';
                        return (
                          <div key={`${d.currency}:${d.type}`} className="flex items-center justify-between p-2 bg-slate-50 rounded-lg">
                            <div className="flex items-center gap-2">
                              <span className="w-3 h-3 rounded-full" style={{ backgroundColor: pickColorByKey(d.type, PIE_COLORS, COMPANY_EXPENSE_COLORS) }} />
                              <span className="text-sm text-slate-700">{d.name} · {d.currency}</span>
                            </div>
                            <div className="flex items-center gap-3">
                              <span className="text-sm font-medium text-slate-800">{formatMoney(d.amount, d.currency)}</span>
                              <span className="text-xs text-slate-500 w-12 text-right">{pct}%</span>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        </TabsContent>
        {/* ── Monthly Detail Tab ── */}
        <TabsContent value="monthly_detail">
          <Card className="border-slate-200">
            <CardHeader className="pb-2">
              <CardTitle className="text-base font-semibold text-slate-700">
                按月明细 <span className="ml-2 text-xs align-middle text-slate-400">(默认币种: USD)</span>
              </CardTitle>
              <p className="text-xs text-slate-500">
                管理费按月度扣点比例计算；投流费按充值金额扣 1%。
              </p>
            </CardHeader>
            <CardContent className="p-0">
              {loading ? (
                <div className="flex items-center justify-center py-12">
                  <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600" />
                </div>
              ) : monthlyDetail.rows.length === 0 ? (
                <p className="text-center text-slate-400 py-12">
                  {dateFilterMode !== 'all' ? '该时间段内暂无按月明细' : '暂无按月明细数据'}
                </p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b bg-slate-50 text-left text-slate-500">
                        <th className="px-3 py-2.5 font-medium">月份</th>
                        <th className="px-3 py-2.5 font-medium">收入 (revenue_gross)</th>
                        <th className="px-3 py-2.5 font-medium">管理费收入</th>
                        <th className="px-3 py-2.5 font-medium">投流充值收入</th>
                        <th className="px-3 py-2.5 font-medium">管理费扣点率</th>
                        <th className="px-3 py-2.5 font-medium">管理费扣点</th>
                        <th className="px-3 py-2.5 font-medium">投流充值 1%</th>
                        <th className="px-3 py-2.5 font-medium">Stripe手续费</th>
                        <th className="px-3 py-2.5 font-medium">总扣点</th>
                        <th className="px-3 py-2.5 font-medium">客户成本</th>
                        <th className="px-3 py-2.5 font-medium">USD运营支出</th>
                        <th className="px-3 py-2.5 font-medium">总成本 (cost)</th>
                        <th className="px-3 py-2.5 font-medium">利润 (profit)</th>
                      </tr>
                    </thead>
                    <tbody>
                      {paginatedMonthlyDetail.items.map((r: any) => (
                        <tr key={r.month} className="border-b border-slate-100 hover:bg-slate-50">
                          <td className="px-3 py-2.5 font-medium">{r.month}</td>
                          <td className="px-3 py-2.5">{fmt(r.revenue_gross)}</td>
                          <td className="px-3 py-2.5">{fmt(r.management_revenue || 0)}</td>
                          <td className="px-3 py-2.5">{fmt(r.ads_recharge_revenue || 0)}</td>
                          <td className="px-3 py-2.5">{r.management_rate > 0 ? `${Math.round(r.management_rate * 100)}%` : '-'}</td>
                          <td className="px-3 py-2.5">{fmt(r.management_deduction_amount)}</td>
                          <td className="px-3 py-2.5">{fmt(r.ads_recharge_deduction_amount)}</td>
                          <td className="px-3 py-2.5">{fmt(r.stripe_platform_fee || 0)}</td>
                          <td className="px-3 py-2.5">{fmt(r.deduction_amount)}</td>
                          <td className="px-3 py-2.5">{fmt(r.customer_cost || 0)}</td>
                          <td className="px-3 py-2.5">{fmt(r.operating_cost_usd || 0)}</td>
                          <td className="px-3 py-2.5">{fmt(r.cost)}</td>
                          <td className="px-3 py-2.5 font-semibold" style={{ color: r.profit >= 0 ? '#059669' : '#ef4444' }}>
                            {fmt(r.profit)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              {monthlyDetail.rows.length > 0 && <PaginationFooter pageKey="monthly_detail" data={paginatedMonthlyDetail} />}
            </CardContent>
          </Card>
        </TabsContent>

      </Tabs>

      {/* ── Dialogs ── */}

      {/* Payment Form */}
      <Dialog open={showPaymentForm} onOpenChange={(v) => { setShowPaymentForm(v); if (!v) { setEditingPayId(null); setPayForm(emptyPayForm); } }}>
        <DialogContent className="max-w-lg max-h-[85vh] overflow-y-auto">
          <DialogHeader><DialogTitle>{editingPayId ? '编辑收款记录' : '录入收款'}</DialogTitle></DialogHeader>
          <div className="space-y-4">
            <div>
              <Label>选择客户 *</Label>
              {customers.length === 0 ? (
                <p className="text-sm text-amber-600 mt-1">暂无客户数据，请先在「客户管理」中添加客户</p>
              ) : (
                <div className="relative">
                  <select
                    value={payForm.customer_id}
                    onChange={handlePayCustomerChange}
                    className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 pr-8 text-sm ring-offset-background focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2"
                  >
                    <option value="">-- 请选择客户 --</option>
                    {customerOptions.map(opt => (
                      <option key={opt.value} value={opt.value}>{opt.label}</option>
                    ))}
                  </select>
                </div>
              )}
            </div>
            <div>
              <div className="flex items-center justify-between gap-2">
                <Label>收入类型 *</Label>
                {canManageIncomeTypes && (
                  <Button type="button" variant="outline" size="sm" className="h-8 shrink-0" onClick={openIncomeTypeManager}>
                    管理类型
                  </Button>
                )}
              </div>
              <NativeSelect
                value={payForm.income_type}
                onChange={v => setPayForm({ ...payForm, income_type: v, management_amount: '', ads_recharge_amount: '' })}
                options={paymentIncomeTypeOptions}
              />
            </div>
            <div>
              <div className="flex items-center justify-between gap-2">
                <Label>产品名称 *（可多选）</Label>
                {canManageCustomerPackages && (
                  <Button type="button" variant="outline" size="sm" className="h-8 shrink-0" onClick={openPaymentPackageManager}>
                    管理套餐
                  </Button>
                )}
              </div>
              {paymentPackageOptions.length === 0 ? (
                <p className="mt-2 text-sm text-amber-600">暂无可选套餐，请先添加套餐。</p>
              ) : (
                <div className="grid grid-cols-2 gap-2 mt-2 p-3 border rounded-md bg-slate-50">
                  {paymentPackageOptions.map(opt => (
                    <label key={opt.value} className="flex items-center gap-2 cursor-pointer text-sm hover:text-blue-600">
                      <input type="checkbox" className="rounded border-slate-300"
                        checked={payForm.product_names.includes(opt.value)}
                        onChange={(e) => {
                          if (e.target.checked) setPayForm({ ...payForm, product_names: [...payForm.product_names, opt.value] });
                          else setPayForm({ ...payForm, product_names: payForm.product_names.filter(n => n !== opt.value) });
                        }} />
                      {opt.label}
                    </label>
                  ))}
                </div>
              )}
              {payForm.product_names.length > 0 && <p className="text-xs text-slate-500 mt-1">已选: {payForm.product_names.join('、')}</p>}
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div><Label>应收金额 *</Label><Input type="number" value={payForm.amount_due} onChange={e => setPayForm({ ...payForm, amount_due: e.target.value })} placeholder="0.00" /></div>
              <div><Label>实收金额 *</Label><Input type="number" value={payForm.amount_paid} onChange={e => setPayForm({ ...payForm, amount_paid: e.target.value })} placeholder="0.00" /></div>
            </div>
            <div className="rounded-lg border border-blue-100 bg-blue-50/60 p-3">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <Label className="text-sm font-medium text-blue-900">收入拆分</Label>
                  <p className="mt-1 text-xs text-blue-700">
                    客户一笔付款里同时包含管理费和投流费时，填写下面两项金额，系统会自动归类为「管理费+投流费」。
                  </p>
                </div>
                <Badge className="bg-white text-blue-700">历史金额固定</Badge>
              </div>
              <div className="mt-3 grid grid-cols-2 gap-3">
                <div>
                  <Label className="text-xs text-slate-600">管理费收入金额</Label>
                  <Input
                    type="number"
                    value={payForm.management_amount}
                    onChange={e => setPayForm({ ...payForm, management_amount: e.target.value })}
                    placeholder={payForm.income_type === MANAGEMENT_FEE_KEY ? payForm.amount_paid || '自动全部计入管理费' : '填写管理费部分'}
                  />
                </div>
                <div>
                  <Label className="text-xs text-slate-600">投流充值金额</Label>
                  <Input
                    type="number"
                    value={payForm.ads_recharge_amount}
                    onChange={e => setPayForm({ ...payForm, ads_recharge_amount: e.target.value })}
                    placeholder={payForm.income_type === ADS_FEE_KEY ? payForm.amount_paid || '自动全部计入投流费' : '填写投流充值部分'}
                  />
                </div>
              </div>
              {(() => {
                const preview = buildPaymentFinancePayload();
                const unallocatedAmount = roundMoney(toMoneyNumber(payForm.amount_paid) - preview.management_amount - preview.ads_recharge_amount);
                return (
                  <p className="mt-2 text-xs text-blue-700">
                    当前计算：管理费 {fmt(preview.management_amount)}，投流充值 {fmt(preview.ads_recharge_amount)}，
                    未拆分 {unallocatedAmount > 0 ? fmt(unallocatedAmount) : '$0'}，
                    Stripe手续费 {preview.stripe_fee_amount > 0 ? fmt(preview.stripe_fee_amount) : '$0'}。
                  </p>
                );
              })()}
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <Label>收款模式</Label>
                <div className="mb-2 rounded-lg border border-cyan-100 bg-cyan-50 px-3 py-2">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <Label className="text-sm font-medium text-cyan-900">这笔收款开启订阅续费</Label>
                      <p className="mt-1 text-xs text-cyan-700">
                        开启后默认按 Stripe 订阅处理，到期进入待确认续费；关闭后按手动收款，不产生 Stripe 手续费。
                      </p>
                    </div>
                    <Switch
                      checked={payForm.payment_mode === 'subscription_auto'}
                      onCheckedChange={checked => setPayForm({
                        ...payForm,
                        payment_mode: checked ? 'subscription_auto' : 'manual_collection',
                        payment_method: checked ? defaultSubscriptionPaymentMethod : defaultManualPaymentMethod,
                      })}
                    />
                  </div>
                </div>
                <NativeSelect
                  value={payForm.payment_mode}
                  onChange={v => setPayForm({
                    ...payForm,
                    payment_mode: v,
                    payment_method: v === 'subscription_auto' ? defaultSubscriptionPaymentMethod : defaultManualPaymentMethod,
                  })}
                  options={paymentModeOptions}
                />
              </div>
              <div>
                <Label>收款方式</Label>
                <NativeSelect
                  value={normalizePaymentMethodKey(payForm.payment_method)}
                  onChange={v => setPayForm({ ...payForm, payment_method: v })}
                  options={availablePaymentMethodOptions}
                />
              </div>
            </div>
            <div>
              <Label>流水 / 支票 / Stripe 编号</Label>
              <Input
                value={payForm.transaction_reference}
                onChange={e => setPayForm({ ...payForm, transaction_reference: e.target.value })}
                placeholder="可选，例如 Stripe invoice、支票号、转账备注"
              />
            </div>
            <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-500">
              {payForm.payment_mode === 'subscription_auto'
                ? '自动订阅适合 Stripe 每月主动扣款客户，系统会将这类收入单独归类。'
                : '手动收款适合支票、Zelle、Apple Cash、Venmo 等线下或手机转账客户。'}
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <Label>计费周期</Label>
                <NativeSelect value={payForm.billing_cycle} onChange={v => setPayForm({ ...payForm, billing_cycle: v })}
                  options={Object.entries(cycleLabels).map(([k, v]) => ({ value: k, label: v }))} />
              </div>
              <div className="flex items-center gap-2 pt-6"><Switch checked={payForm.has_invoice} onCheckedChange={v => setPayForm({ ...payForm, has_invoice: v })} /><Label>已开票</Label></div>
            </div>
            <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-3">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <Label className="text-sm font-medium text-amber-900">同步为成交记录</Label>
                  <p className="mt-1 text-xs leading-relaxed text-amber-700">
                    默认关闭。补录历史流水、Stripe续费、支票或转账收入不会影响成交数据；只有确认为新成交或首款时再打开。
                  </p>
                </div>
                <Switch
                  checked={payForm.sync_to_deal}
                  onCheckedChange={v => setPayForm({ ...payForm, sync_to_deal: v })}
                />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div><Label>覆盖开始</Label><Input type="date" value={payForm.coverage_start} onChange={e => setPayForm({ ...payForm, coverage_start: e.target.value })} /></div>
              <div><Label>覆盖结束</Label><Input type="date" value={payForm.coverage_end} onChange={e => setPayForm({ ...payForm, coverage_end: e.target.value })} /></div>
            </div>
            <div><Label>备注</Label><Textarea value={payForm.notes} onChange={e => setPayForm({ ...payForm, notes: e.target.value })} rows={2} /></div>
          </div>
          <div className="flex justify-end gap-2 mt-4">
            <Button variant="outline" onClick={() => setShowPaymentForm(false)}>取消</Button>
            <Button onClick={handleSavePayment} disabled={saving} className="bg-blue-600 hover:bg-blue-700">{saving ? '保存中...' : '保存'}</Button>
          </div>
        </DialogContent>
      </Dialog>

      <Dialog open={showIncomeTypeManager} onOpenChange={(v) => { setShowIncomeTypeManager(v); if (!v) setNewIncomeTypeName(''); }}>
        <DialogContent className="max-w-lg max-h-[85vh] overflow-y-auto">
          <DialogHeader><DialogTitle>管理收入类型</DialogTitle></DialogHeader>
          <div className="space-y-4">
            <div className="flex items-center gap-2">
              <Input
                value={newIncomeTypeName}
                onChange={e => setNewIncomeTypeName(e.target.value)}
                placeholder="新增类型，例如：设计费、拍摄费"
                onKeyDown={e => {
                  if (e.key === 'Enter') {
                    e.preventDefault();
                    handleAddIncomeTypeDraft();
                  }
                }}
              />
              <Button type="button" size="sm" className="bg-blue-600 hover:bg-blue-700" onClick={handleAddIncomeTypeDraft}>
                添加
              </Button>
            </div>
            <div className="space-y-2">
              {incomeTypeDrafts.map(item => {
                const protectedType = PROTECTED_INCOME_TYPE_KEYS.has(item.key);
                return (
                  <div key={item.key} className="flex items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
                    <div className="min-w-0 flex-1">
                      <Input
                        value={item.label}
                        onChange={e => setIncomeTypeDrafts(prev => prev.map(type => (type.key === item.key ? { ...type, label: e.target.value } : type)))}
                        className="h-8 bg-white text-sm"
                        disabled={protectedType}
                      />
                      <p className="mt-1 text-xs text-slate-400">
                        {item.key}
                        {protectedType ? ' · 系统扣点类型，不能删除或改名' : ''}
                      </p>
                    </div>
                    {protectedType ? (
                      <Badge className="bg-blue-100 text-blue-700 text-xs">系统</Badge>
                    ) : (
                      <Button type="button" variant="ghost" size="sm" className="h-8 w-8 p-0 text-slate-500 hover:text-red-600" onClick={() => handleRemoveIncomeTypeDraft(item.key)}>
                        <Trash2 className="w-4 h-4" />
                      </Button>
                    )}
                  </div>
                );
              })}
            </div>
            <p className="text-xs text-slate-500">
              管理费会参与管理费扣点，投流费会参与投流 1% 扣点；「管理费+投流费」用于一笔收款同时包含两类金额，其他收入类型只作为普通收入分类统计。
            </p>
          </div>
          <div className="flex justify-end gap-2 mt-4">
            <Button variant="outline" onClick={() => setShowIncomeTypeManager(false)}>取消</Button>
            <Button onClick={handleSaveIncomeTypes} disabled={savingIncomeTypes} className="bg-blue-600 hover:bg-blue-700">
              {savingIncomeTypes ? '保存中...' : '保存类型'}
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      <Dialog open={showPaymentPackageManager} onOpenChange={(v) => { setShowPaymentPackageManager(v); if (!v) setNewPaymentPackageName(''); }}>
        <DialogContent className="max-w-lg max-h-[85vh] overflow-y-auto">
          <DialogHeader><DialogTitle>管理收款套餐</DialogTitle></DialogHeader>
          <div className="space-y-4">
            <div className="flex items-center gap-2">
              <Input
                value={newPaymentPackageName}
                onChange={e => setNewPaymentPackageName(e.target.value)}
                placeholder="新增套餐，例如：Google商家管理"
                onKeyDown={e => {
                  if (e.key === 'Enter') {
                    e.preventDefault();
                    handleAddPaymentPackageDraft();
                  }
                }}
              />
              <Button type="button" size="sm" className="bg-blue-600 hover:bg-blue-700" onClick={handleAddPaymentPackageDraft}>
                添加
              </Button>
            </div>
            <div className="space-y-2">
              {paymentPackageDrafts.map(item => (
                <div key={item.key} className="flex items-center justify-between gap-3 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-slate-700">{item.label}</p>
                    <p className="text-xs text-slate-400">{item.key}</p>
                  </div>
                  <Button type="button" variant="ghost" size="sm" className="h-8 w-8 p-0 text-slate-500 hover:text-red-600" onClick={() => handleRemovePaymentPackageDraft(item.key)}>
                    <Trash2 className="w-4 h-4" />
                  </Button>
                </div>
              ))}
            </div>
            <p className="text-xs text-slate-500">这里维护的套餐会同步用于客户意向套餐、成交录入和财务收款选择。</p>
          </div>
          <div className="flex justify-end gap-2 mt-4">
            <Button variant="outline" onClick={() => setShowPaymentPackageManager(false)}>取消</Button>
            <Button onClick={handleSavePaymentPackages} disabled={savingPaymentPackages} className="bg-blue-600 hover:bg-blue-700">
              {savingPaymentPackages ? '保存中...' : '保存套餐'}
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      <Dialog open={showCustomerExpenseTypeManager} onOpenChange={(v) => { setShowCustomerExpenseTypeManager(v); if (!v) setNewCustomerExpenseTypeName(''); }}>
        <DialogContent className="max-w-lg max-h-[85vh] overflow-y-auto">
          <DialogHeader><DialogTitle>管理客户支出类型</DialogTitle></DialogHeader>
          <div className="space-y-4">
            <div className="flex items-center gap-2">
              <Input
                value={newCustomerExpenseTypeName}
                onChange={e => setNewCustomerExpenseTypeName(e.target.value)}
                placeholder="新增类型，例如：域名费"
                onKeyDown={e => {
                  if (e.key === 'Enter') {
                    e.preventDefault();
                    handleAddCustomerExpenseTypeDraft();
                  }
                }}
              />
              <Button type="button" size="sm" className="bg-blue-600 hover:bg-blue-700" onClick={handleAddCustomerExpenseTypeDraft}>
                添加
              </Button>
            </div>
            <div className="space-y-2">
              {customerExpenseTypeDrafts.map(item => (
                <div key={item.key} className="flex items-center justify-between gap-3 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-slate-700">{item.label}</p>
                    <p className="text-xs text-slate-400">{item.key}</p>
                  </div>
                  <Button type="button" variant="ghost" size="sm" className="h-8 w-8 p-0 text-slate-500 hover:text-red-600" onClick={() => handleRemoveCustomerExpenseTypeDraft(item.key)}>
                    <Trash2 className="w-4 h-4" />
                  </Button>
                </div>
              ))}
            </div>
            <p className="text-xs text-slate-500">客户支出类型用于绑定具体客户的成本，例如投流成本、网站成本、域名费、主机/服务器费。</p>
          </div>
          <div className="flex justify-end gap-2 mt-4">
            <Button variant="outline" onClick={() => setShowCustomerExpenseTypeManager(false)}>取消</Button>
            <Button onClick={handleSaveCustomerExpenseTypes} disabled={savingCustomerExpenseTypes} className="bg-blue-600 hover:bg-blue-700">
              {savingCustomerExpenseTypes ? '保存中...' : '保存'}
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      {/* Customer Expense Form */}
      <Dialog open={showExpenseForm} onOpenChange={(v) => { setShowExpenseForm(v); if (!v) { setEditingExpenseId(null); setExpenseForm(emptyExpenseForm); } }}>
        <DialogContent className="max-w-lg max-h-[85vh] overflow-y-auto">
          <DialogHeader><DialogTitle>{editingExpenseId ? '编辑客户支出' : '录入客户支出'}</DialogTitle></DialogHeader>
          <div className="space-y-4">
            <div>
              <Label>选择客户 *</Label>
              {customers.length === 0 ? (
                <p className="text-sm text-amber-600 mt-1">暂无客户数据，请先在「客户管理」中添加客户</p>
              ) : (
                <div className="relative">
                  <select
                    value={expenseForm.customer_id}
                    onChange={handleExpenseCustomerChange}
                    className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 pr-8 text-sm ring-offset-background focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2"
                  >
                    <option value="">-- 请选择客户 --</option>
                    {customerOptions.map(opt => (
                      <option key={opt.value} value={opt.value}>{opt.label}</option>
                    ))}
                  </select>
                </div>
              )}
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <div className="flex items-center justify-between gap-2">
                  <Label>费用类型 *</Label>
                  {canManageCustomerExpenseTypes && (
                    <Button type="button" variant="outline" size="sm" className="h-8 shrink-0" onClick={openCustomerExpenseTypeManager}>
                      管理
                    </Button>
                  )}
                </div>
                <NativeSelect
                  value={expenseForm.expense_type}
                  onChange={v => setExpenseForm({ ...expenseForm, expense_type: v })}
                  options={customerExpenseTypeOptions}
                  className="mt-1"
                />
              </div>
              <div>
                <Label>金额 *</Label>
                <Input type="number" value={expenseForm.amount} onChange={e => setExpenseForm({ ...expenseForm, amount: e.target.value })} placeholder="0.00" />
              </div>
            </div>
            <div>
              <Label>币种</Label>
              <NativeSelect
                value={expenseForm.currency}
                onChange={v => setExpenseForm({ ...expenseForm, currency: normalizeCurrency(v, 'USD') })}
                options={Object.entries(currencyLabels).map(([value, label]) => ({ value, label }))}
              />
              <p className="mt-1 text-xs text-slate-500">客户成本默认按 USD 进入利润；如选择 CNY，会保留记录但不混入 USD 利润。</p>
            </div>
            <div>
              <Label>费用月份</Label>
              <Input type="month" value={expenseForm.expense_month} onChange={e => setExpenseForm({ ...expenseForm, expense_month: e.target.value })} />
            </div>
            <div><Label>备注</Label><Textarea value={expenseForm.notes} onChange={e => setExpenseForm({ ...expenseForm, notes: e.target.value })} rows={2} /></div>
          </div>
          <div className="flex justify-end gap-2 mt-4">
            <Button variant="outline" onClick={() => setShowExpenseForm(false)}>取消</Button>
            <Button onClick={handleSaveExpense} disabled={savingExpense} className="bg-blue-600 hover:bg-blue-700">{savingExpense ? '保存中...' : '保存'}</Button>
          </div>
        </DialogContent>
      </Dialog>

      {/* Company Expense Form */}
      <Dialog open={showCompanyExpenseForm} onOpenChange={(v) => { setShowCompanyExpenseForm(v); if (!v) { setEditingCompanyExpenseId(null); setCompanyExpenseForm(emptyCompanyExpenseForm); } }}>
        <DialogContent className="max-w-lg max-h-[85vh] overflow-y-auto">
          <DialogHeader><DialogTitle>{editingCompanyExpenseId ? '编辑运营支出' : '录入运营支出'}</DialogTitle></DialogHeader>
          <div className="space-y-4">
            <div>
              <Label>支出类型 *</Label>
              <div className="flex items-center gap-2">
                <NativeSelect
                  value={companyExpenseForm.category}
                  onChange={v => setCompanyExpenseForm({ ...companyExpenseForm, category: v })}
                  options={companyExpenseTypeOptions}
                />
                {canManageCompanyExpenseTypes && (
                  <Button type="button" variant="outline" size="sm" className="shrink-0" onClick={openCompanyExpenseTypeManager}>
                    管理
                  </Button>
                )}
              </div>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <Label>金额 *</Label>
                <Input type="number" value={companyExpenseForm.amount} onChange={e => setCompanyExpenseForm({ ...companyExpenseForm, amount: e.target.value })} placeholder="0.00" />
              </div>
              <div>
                <Label>币种 *</Label>
                <NativeSelect
                  value={companyExpenseForm.currency}
                  onChange={v => setCompanyExpenseForm({ ...companyExpenseForm, currency: normalizeCurrency(v) })}
                  options={Object.entries(currencyLabels).map(([value, label]) => ({ value, label }))}
                />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <Label>支出日期</Label>
                <Input type="date" value={companyExpenseForm.expense_date} onChange={e => setCompanyExpenseForm({ ...companyExpenseForm, expense_date: e.target.value })} />
              </div>
              <div>
                <Label>支出月份</Label>
                <Input type="month" value={companyExpenseForm.expense_month} onChange={e => setCompanyExpenseForm({ ...companyExpenseForm, expense_month: e.target.value })} />
              </div>
            </div>
            <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-500">
              USD 运营支出会计入美元利润；CNY 支出会单独统计，暂不和美元利润混算。
            </div>
            <div><Label>备注</Label><Textarea value={companyExpenseForm.notes} onChange={e => setCompanyExpenseForm({ ...companyExpenseForm, notes: e.target.value })} rows={2} /></div>
          </div>
          <div className="flex justify-end gap-2 mt-4">
            <Button variant="outline" onClick={() => setShowCompanyExpenseForm(false)}>取消</Button>
            <Button onClick={handleSaveCompanyExpense} disabled={savingCompanyExpense} className="bg-blue-600 hover:bg-blue-700">{savingCompanyExpense ? '保存中...' : '保存'}</Button>
          </div>
        </DialogContent>
      </Dialog>

      <Dialog open={showCompanyExpenseTypeManager} onOpenChange={(v) => { setShowCompanyExpenseTypeManager(v); if (!v) setNewCompanyExpenseTypeName(''); }}>
        <DialogContent className="max-w-lg max-h-[85vh] overflow-y-auto">
          <DialogHeader><DialogTitle>管理运营支出类型</DialogTitle></DialogHeader>
          <div className="space-y-4">
            <div className="flex items-center gap-2">
              <Input
                value={newCompanyExpenseTypeName}
                onChange={e => setNewCompanyExpenseTypeName(e.target.value)}
                placeholder="新增类型，例如：AI工具费、法务费"
                onKeyDown={e => {
                  if (e.key === 'Enter') {
                    e.preventDefault();
                    handleAddCompanyExpenseTypeDraft();
                  }
                }}
              />
              <Button type="button" size="sm" className="bg-blue-600 hover:bg-blue-700" onClick={handleAddCompanyExpenseTypeDraft}>
                添加
              </Button>
            </div>
            <div className="space-y-2">
              {companyExpenseTypeDrafts.map(item => (
                <div key={item.key} className="flex items-center justify-between gap-3 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-slate-700">{item.label}</p>
                    <p className="text-xs text-slate-400">{item.key}</p>
                  </div>
                  <Button type="button" variant="ghost" size="sm" className="h-8 w-8 p-0 text-slate-500 hover:text-red-600" onClick={() => handleRemoveCompanyExpenseTypeDraft(item.key)}>
                    <Trash2 className="w-4 h-4" />
                  </Button>
                </div>
              ))}
            </div>
          </div>
          <div className="flex justify-end gap-2 mt-4">
            <Button variant="outline" onClick={() => setShowCompanyExpenseTypeManager(false)}>取消</Button>
            <Button onClick={handleSaveCompanyExpenseTypes} disabled={savingCompanyExpenseTypes} className="bg-blue-600 hover:bg-blue-700">
              {savingCompanyExpenseTypes ? '保存中...' : '保存'}
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      {/* Confirm Dialogs */}
      <ConfirmDialog open={!!deleteTarget} onOpenChange={(v) => { if (!v) setDeleteTarget(null); }}
        title={deleteTarget?.type === 'payment' ? '确认删除收款记录' : '确认删除套餐记录'}
        description={`确定要删除「${deleteTarget?.item?.customer_name}」的${deleteTarget?.type === 'payment' ? '收款' : '套餐'}记录吗？`}
        onConfirm={handleDeleteRecord} loading={deleting} />

      <ConfirmDialog open={!!deleteExpenseTarget} onOpenChange={(v) => { if (!v) setDeleteExpenseTarget(null); }}
        title="确认删除客户支出记录"
        description={`确定要删除「${deleteExpenseTarget?.customer_name}」的${customerExpenseTypeLabels[deleteExpenseTarget?.expense_type] || ''}支出记录吗？`}
        onConfirm={handleDeleteExpense} loading={deletingExpense} />

      <ConfirmDialog open={!!deleteCompanyExpenseTarget} onOpenChange={(v) => { if (!v) setDeleteCompanyExpenseTarget(null); }}
        title="确认删除运营支出记录"
        description={`确定要删除「${companyExpenseTypeLabels[deleteCompanyExpenseTarget?.category] || deleteCompanyExpenseTarget?.category_name || deleteCompanyExpenseTarget?.category || ''}」的运营支出记录吗？`}
        onConfirm={handleDeleteCompanyExpense} loading={deletingCompanyExpense} />
    </div>
  );
}
