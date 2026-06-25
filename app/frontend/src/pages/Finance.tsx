import { useState, useEffect, useMemo } from 'react';
import { client } from '../lib/api';
import { invokeWithAuth } from '@/lib/tokenStore';
import { useRole } from '../lib/role-context';
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
  ArrowUpRight, ArrowDownRight, Wallet
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
import { buildOptionKey, serializeDictEntries, useBusinessDicts, useDictConfig } from '../lib/dict-config';
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

// ─── Constants ───────────────────────────────────────────────────────
const incomeTypeLabels: Record<string, string> = {
  management_fee: '管理费', ads_fee: '投流费', website_fee: '网站费',
  ordering_fee: '点餐系统费', renewal_fee: '续费收入', other_income: '其他收入',
};
const INCOME_TYPE_COLORS: Record<string, string> = {
  management_fee: '#3b82f6', ads_fee: '#f59e0b', website_fee: '#10b981',
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
  expired: 'bg-red-100 text-red-700', paused: 'bg-slate-100 text-slate-600', lost: 'bg-red-100 text-red-700',
};

const PIE_COLORS = ['#3b82f6', '#ef4444', '#f59e0b', '#10b981', '#8b5cf6', '#ec4899', '#06b6d4', '#f97316', '#6366f1'];

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
const getCompanyExpenseCurrency = (expense: any): CurrencyCode => normalizeCurrency(expense?.currency, 'CNY');
const formatMoney = (amount: number, currency: CurrencyCode) => (currency === 'CNY' ? fmtRMB(amount) : fmt(amount));
const roundMoney = (amount: number) => Math.round(Number(amount || 0) * 100) / 100;

const MANAGEMENT_FEE_KEY = 'management_fee';
const ADS_FEE_KEY = 'ads_fee';
const ADS_RECHARGE_DEDUCTION_RATE = 0.01;

type MonthlyFinanceBucket = {
  revenue: number;
  managementRevenue: number;
  adsRevenue: number;
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
    map[ym] = { revenue: 0, managementRevenue: 0, adsRevenue: 0, customerCost: 0, operatingCostUsd: 0, cost: 0 };
  }
  return map[ym];
};

const buildMonthlyFinanceBuckets = (paymentsList: any[], customerExpenses: any[], companyExpenseList: any[] = []) => {
  const map: Record<string, MonthlyFinanceBucket> = {};

  paymentsList.forEach((payment) => {
    const ym = (payment.payment_date || '').slice(0, 7);
    if (!/^\d{4}-\d{2}$/.test(ym)) return;
    const bucket = getOrCreateMonthlyFinanceBucket(map, ym);
    const amount = Number(payment.amount_paid || 0);
    bucket.revenue += amount;
    if (payment.income_type === MANAGEMENT_FEE_KEY) {
      bucket.managementRevenue += amount;
    }
    if (payment.income_type === ADS_FEE_KEY) {
      bucket.adsRevenue += amount;
    }
  });

  customerExpenses.forEach((expense) => {
    const ym = (expense.expense_month || '').slice(0, 7);
    if (!/^\d{4}-\d{2}$/.test(ym)) return;
    const bucket = getOrCreateMonthlyFinanceBucket(map, ym);
    const amount = Number(expense.amount || 0);
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
  const { isAdmin, hasPermission, employee } = useRole();
  const dictConfig = useDictConfig();
  const {
    paymentModes: payModeLabels,
    paymentMethods: payMethodLabels,
    billingCycles: cycleLabels,
    customerExpenseTypes: customerExpenseTypeLabels,
    companyExpenseTypes: companyExpenseTypeLabels,
    subscriptionStatuses: subStatusLabels,
    customerPackages: customerPackageLabels,
  } = useBusinessDicts();
  const operatorName = employee?.name || '管理员';
  const canManageCustomerExpenseTypes = isAdmin || hasPermission('settings_edit');
  const canManageCompanyExpenseTypes = isAdmin || hasPermission('settings_edit');
  const canManageCustomerPackages = isAdmin || hasPermission('settings_edit');
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
  const [exporting, setExporting] = useState(false);
  const doExport = async (fmt: 'csv'|'xlsx') => {
    try {
      setExporting(true);
      const today = new Date();
      const todayStr = today.toISOString().slice(0, 10);
      let start = '';
      let end = '';

      if (dateFilterMode === 'custom' && (filterStartDate || filterEndDate)) {
        start = filterStartDate || '';
        end = filterEndDate || '';
      } else if (dateFilterMode === 'today') {
        start = todayStr;
        end = todayStr;
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
    coverage_start: '', coverage_end: '', has_invoice: false, notes: '',
  };
  const [payForm, setPayForm] = useState(emptyPayForm);
  const [showPaymentPackageManager, setShowPaymentPackageManager] = useState(false);
  const [paymentPackageDrafts, setPaymentPackageDrafts] = useState<Array<{ key: string; label: string }>>([]);
  const [newPaymentPackageName, setNewPaymentPackageName] = useState('');
  const [savingPaymentPackages, setSavingPaymentPackages] = useState(false);

  // Customer expense form
  const [showExpenseForm, setShowExpenseForm] = useState(false);
  const [editingExpenseId, setEditingExpenseId] = useState<number | null>(null);
  const [savingExpense, setSavingExpense] = useState(false);
  const [expenseMonth, setExpenseMonth] = useState(() => {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
  });
  const emptyExpenseForm = { customer_id: '', expense_type: defaultCustomerExpenseType, amount: '', expense_month: expenseMonth, notes: '' };
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
  const [deleteExpenseTarget, setDeleteExpenseTarget] = useState<any>(null);
  const [deletingExpense, setDeletingExpense] = useState(false);
  const [deleteCompanyExpenseTarget, setDeleteCompanyExpenseTarget] = useState<any>(null);
  const [deletingCompanyExpense, setDeletingCompanyExpense] = useState(false);

  // Date filter
  type DateFilterMode = 'all' | 'today' | 'custom';
  const [dateFilterMode, setDateFilterMode] = useState<DateFilterMode>('all');
  const [filterStartDate, setFilterStartDate] = useState('');
  const [filterEndDate, setFilterEndDate] = useState('');

  // ─── Load Data (resilient - each query independent) ───────────────

  useEffect(() => { loadData(); }, []);

  const loadData = async () => {
    try {
      // Load each data source independently so one failure doesn't block others
      const [pItems, sItems, cItems, dItems, eItems, ceItems] = await Promise.all([
        safeQuery(() => client.entities.payments.queryAll({ limit: 500, sort: '-payment_date' })),
        safeQuery(() => client.entities.subscriptions.query({ limit: 500, sort: '-end_date' })),
        safeQuery(() => client.entities.customers.query({ limit: 500 })),
        safeQuery(() => client.entities.deals.query({ limit: 500, sort: '-deal_date' })),
        safeQuery(() => client.entities.expenses.queryAll({ limit: 500, sort: '-created_at' })),
        safeQuery(() => client.entities.company_expenses.queryAll({ limit: 500, sort: '-created_at' })),
      ]);
      setPayments(pItems);
      setSubscriptions(decorateEffectiveSubscriptions(sItems));
      setCustomers(cItems);
      setDeals(dItems);
      setExpenses(eItems);
      setCompanyExpenses(ceItems);
      try {
        const months = new Set<string>();
        [...pItems, ...eItems].forEach((it: any) => {
          const ym = (it.payment_date || it.expense_month || it.created_at || '').slice(0,7);
          if (/^\d{4}-\d{2}$/.test(ym)) months.add(ym);
        });
        if (months.size > 0) {
          const arr = Array.from(months).sort();
          const start = arr[0];
          const end = arr[arr.length - 1];
          const res = await invokeWithAuth({ url: '/api/v1/deductions-monthly', method: 'GET', data: { start, end } });
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
    if (dateFilterMode === 'all') return items;
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    if (dateFilterMode === 'today') {
      const todayStr = today.toISOString().slice(0, 10);
      return items.filter(i => i[dateField]?.slice(0, 10) === todayStr);
    }
    return items.filter(i => {
      const d = i[dateField]?.slice(0, 10);
      if (!d) return false;
      if (filterStartDate && d < filterStartDate) return false;
      if (filterEndDate && d > filterEndDate) return false;
      return true;
    });
  };

  const filteredPayments = filterByDate(payments, 'payment_date');
  const filteredSubscriptions = useMemo(() => {
    if (dateFilterMode === 'all') return subscriptions;
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    if (dateFilterMode === 'today') {
      const todayStr = today.toISOString().slice(0, 10);
      return subscriptions.filter(s => s.created_at?.slice(0, 10) === todayStr || s.start_date?.slice(0, 10) === todayStr);
    }
    return subscriptions.filter(s => {
      const d = s.start_date?.slice(0, 10) || s.created_at?.slice(0, 10);
      if (!d) return false;
      if (filterStartDate && d < filterStartDate) return false;
      if (filterEndDate && d > filterEndDate) return false;
      return true;
    });
  }, [subscriptions, dateFilterMode, filterStartDate, filterEndDate]);

  const filteredExpenses = expenses.filter(e => !expenseMonth || e.expense_month === expenseMonth);
  const filteredCompanyExpenses = companyExpenses.filter(e => {
    const matchesMonth = !companyExpenseMonth || e.expense_month === companyExpenseMonth;
    const matchesCurrency = companyExpenseCurrencyFilter === 'all' || getCompanyExpenseCurrency(e) === companyExpenseCurrencyFilter;
    return matchesMonth && matchesCurrency;
  });
  const monthlyFinanceBuckets = useMemo(() => buildMonthlyFinanceBuckets(payments, expenses, companyExpenses), [payments, expenses, companyExpenses]);

  // ─── Stats ───────────────────────────────────────────────────────
  const now = new Date();
  const currentMonthKey = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;
  const currentMonthFinance = monthlyFinanceBuckets[currentMonthKey] || { revenue: 0, managementRevenue: 0, adsRevenue: 0, customerCost: 0, operatingCostUsd: 0, cost: 0 };
  const currentMonthDeductionRate = getDeductionRate(deductionRates, currentMonthKey);
  const currentMonthProfit = calculateMonthlyProfit(currentMonthFinance, currentMonthDeductionRate);
  const monthlyIncome = currentMonthFinance.revenue;
  const monthlyCustomerExpense = currentMonthFinance.customerCost; // USD direct customer costs
  const monthlyCompanyExpenseUsd = currentMonthFinance.operatingCostUsd; // USD operating costs
  const monthlyCompanyExpenseCny = companyExpenses
    .filter(e => e.expense_month === currentMonthKey && getCompanyExpenseCurrency(e) === 'CNY')
    .reduce((s, e) => s + Number(e.amount || 0), 0); // CNY operating costs, not mixed into USD profit
  // USD profit includes USD customer costs and USD operating costs. CNY remains separate until FX conversion is added.
  const monthlyProfitUsd = currentMonthProfit.profit;
  const totalOutstanding = payments.reduce((s, p) => s + (p.outstanding_amount || 0), 0);
  const expiringSubs = subscriptions.filter(s => s.status === 'expiring_soon' || s.status === 'expired');
  const activeSubs = subscriptions.filter(s => s.status === 'active').length;

  // Expense summaries
  const totalCustomerExpense = filteredExpenses.reduce((s, e) => s + (e.amount || 0), 0);
  const customerExpenseByType = useMemo(() => {
    const map: Record<string, number> = {};
    filteredExpenses.forEach(e => { map[e.expense_type] = (map[e.expense_type] || 0) + (e.amount || 0); });
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
  const monthlyTrendData = useMemo(() => {
    const months: { key: string; label: string; income: number; customerExp: number; companyExpUsd: number; companyExpCny: number; profitUsd: number }[] = [];
    for (let i = 11; i >= 0; i--) {
      const d = new Date(now.getFullYear(), now.getMonth() - i, 1);
      const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
      const label = `${d.getMonth() + 1}月`;
      const bucket = monthlyFinanceBuckets[key] || { revenue: 0, managementRevenue: 0, adsRevenue: 0, customerCost: 0, operatingCostUsd: 0, cost: 0 };
      const income = bucket.revenue;
      const custExp = bucket.customerCost; // USD
      const compExpUsd = bucket.operatingCostUsd; // USD operating costs
      const compExpCny = companyExpenses
        .filter(e => e.expense_month === key && getCompanyExpenseCurrency(e) === 'CNY')
        .reduce((s, e) => s + Number(e.amount || 0), 0); // CNY operating costs
      const rate = getDeductionRate(deductionRates, key);
      const { profit } = calculateMonthlyProfit(bucket, rate);
      months.push({ key, label, income, customerExp: custExp, companyExpUsd: compExpUsd, companyExpCny: compExpCny, profitUsd: roundMoney(profit) });
    }
    return months;
  }, [companyExpenses, deductionRates, monthlyFinanceBuckets, now]);

  // ─── Monthly Detail (USD by default, no cross-currency mix) ───────────────────
  const monthlyDetail = useMemo(() => {
    const today = new Date();
    const todayStr = today.toISOString().slice(0, 10);
    let start = '';
    let end = '';

    if (dateFilterMode === 'custom' && (filterStartDate || filterEndDate)) {
      start = filterStartDate || '';
      end = filterEndDate || '';
    } else if (dateFilterMode === 'today') {
      start = todayStr;
      end = todayStr;
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
        management_rate: bucket.managementRevenue > 0 ? rate : 0,
        ads_recharge_rate: bucket.adsRevenue > 0 ? ADS_RECHARGE_DEDUCTION_RATE : 0,
        management_deduction_amount: Math.round(managementDeduction * 100) / 100,
        ads_recharge_deduction_amount: Math.round(adsDeduction * 100) / 100,
        deduction_rate: Math.round(effectiveRate * 10000) / 10000,
        deduction_amount: Math.round(deductionAmount * 100) / 100,
        customer_cost: Math.round(bucket.customerCost * 100) / 100,
        operating_cost_usd: Math.round(bucket.operatingCostUsd * 100) / 100,
        cost: Math.round(cost * 100) / 100,
        profit: Math.round(profit * 100) / 100,
      };
    });

    return { rows, range: { start, end } };
  }, [payments, expenses, companyExpenses, deductionRates, dateFilterMode, filterStartDate, filterEndDate]);


  const incomeByTypeData = useMemo(() => {
    const map: Record<string, number> = {};
    payments.forEach(p => {
      const t = p.income_type || 'other_income';
      map[t] = (map[t] || 0) + (p.amount_paid || 0);
    });
    return Object.entries(map).map(([type, value]) => ({
      name: incomeTypeLabels[type] || type, type, value: Math.round(value * 100) / 100,
    })).sort((a, b) => b.value - a.value);
  }, [payments]);

  const productRevenueData = useMemo(() => {
    const map: Record<string, number> = {};
    payments.forEach(p => {
      if (!p.product_name) return;
      const names = p.product_name.split('、');
      const share = (p.amount_paid || 0) / (names.length || 1);
      names.forEach((name: string) => {
        const trimmed = name.trim();
        if (trimmed) map[trimmed] = (map[trimmed] || 0) + share;
      });
    });
    return Object.entries(map).map(([name, value]) => ({ name, value: Math.round(value * 100) / 100 })).sort((a, b) => b.value - a.value);
  }, [payments]);

  const customerRevenueData = useMemo(() => {
    const map: Record<string, number> = {};
    payments.forEach(p => { const name = p.customer_name || '未知客户'; map[name] = (map[name] || 0) + (p.amount_paid || 0); });
    return Object.entries(map).map(([name, value]) => ({ name, value: Math.round(value * 100) / 100 })).sort((a, b) => b.value - a.value).slice(0, 10);
  }, [payments]);

  const payMethodData = useMemo(() => {
    const countMap: Record<string, number> = {};
    const amountMap: Record<string, number> = {};
    payments.forEach(p => {
      const method = normalizePaymentMethodKey(p.payment_method);
      countMap[method] = (countMap[method] || 0) + 1;
      amountMap[method] = (amountMap[method] || 0) + (p.amount_paid || 0);
    });
    return Object.entries(countMap).map(([method, count]) => ({
      name: payMethodLabels[method] || method, method, count,
      amount: Math.round((amountMap[method] || 0) * 100) / 100,
    })).sort((a, b) => b.amount - a.amount);
  }, [payMethodLabels, payments]);

  const payModeData = useMemo(() => {
    const countMap: Record<string, number> = {};
    const amountMap: Record<string, number> = {};
    payments.forEach((payment) => {
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
  }, [payModeLabels, payments]);

  // ─── Customer map for lookups ────────────────────────────────────
  const customerMap = useMemo(() => Object.fromEntries(customers.map(c => [c.id, c])), [customers]);

  // ─── Payment CRUD ────────────────────────────────────────────────
  const openEditPayment = (p: any) => {
    const names = p.product_name ? p.product_name.split('、').map((s: string) => s.trim()).filter(Boolean) : [];
    setPayForm({
      customer_id: String(p.customer_id || ''), product_names: names,
      income_type: p.income_type || 'management_fee',
      amount_due: String(p.amount_due || ''), amount_paid: String(p.amount_paid || ''),
      payment_mode: inferPaymentModeKey(p),
      payment_method: normalizePaymentMethodKey(p.payment_method),
      billing_cycle: p.billing_cycle || 'monthly',
      coverage_start: p.coverage_start?.slice(0, 10) || '', coverage_end: p.coverage_end?.slice(0, 10) || '',
      has_invoice: p.has_invoice || false, notes: p.notes || '',
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
      const coverageStartISO = toISODatetime(payForm.coverage_start);
      const coverageEndISO = toISODatetime(payForm.coverage_end);
      const normalizedPaymentMethod = normalizePaymentMethodKey(payForm.payment_method);
      const payload: Record<string, any> = {
        customer_id: Number(payForm.customer_id),
        customer_name: cust?.business_name || '',
        income_type: payForm.income_type,
        product_name: payForm.product_names.join('、'),
        amount_due: amountDue, amount_paid: amountPaid,
        payment_mode: payForm.payment_mode,
        payment_method: normalizedPaymentMethod,
        billing_cycle: payForm.billing_cycle,
        coverage_start: coverageStartISO, coverage_end: coverageEndISO,
        has_invoice: payForm.has_invoice,
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
        toast.success('收款记录已更新');
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
        toast.success('收款记录已添加');
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
          const subStartDate = coverageStartISO || matchingSub?.start_date || paymentDateISO;
          const subBaseData = {
            customer_id: Number(payForm.customer_id),
            customer_name: cust?.business_name || '',
            package_name: payForm.product_names.join('、'),
            package_price: amountDue,
            billing_cycle: payForm.billing_cycle,
            start_date: subStartDate,
            end_date: coverageEndISO,
            auto_renew: false,
            renewal_person: cust?.sales_person || matchingSub?.renewal_person || '',
            last_payment_date: paymentDateISO,
            next_payment_date: coverageEndISO,
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
      loadData();
    } catch (err: any) {
      const detail = err?.data?.detail || err?.response?.data?.detail || err?.message || '保存失败';
      toast.error(`保存失败: ${detail}`);
      console.error(err);
    } finally { setSaving(false); }
  };

  // ─── Customer Expense CRUD ───────────────────────────────────────
  const openEditExpense = (e: any) => {
    setExpenseForm({
      customer_id: String(e.customer_id || ''), expense_type: e.expense_type || 'management_fee',
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
      loadData();
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
      setDeleteExpenseTarget(null); loadData();
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
      loadData();
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
      setDeleteCompanyExpenseTarget(null); loadData();
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
      setDeleteTarget(null); loadData();
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
            {(['all', 'today', 'custom'] as DateFilterMode[]).map(mode => (
              <Button key={mode} size="sm"
                variant={dateFilterMode === mode ? 'default' : 'outline'}
                className={dateFilterMode === mode ? 'bg-blue-600 hover:bg-blue-700 text-white' : ''}
                onClick={() => { setDateFilterMode(mode); if (mode !== 'custom') { setFilterStartDate(''); setFilterEndDate(''); } }}
              >
                {mode === 'all' && '全部'}
                {mode === 'today' && <><CalendarDays className="w-3.5 h-3.5 mr-1" />今天</>}
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
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
        <Card className="border-slate-200">
          <CardContent className="p-3 flex items-center gap-3">
            <div className="w-9 h-9 rounded-lg bg-green-50 flex items-center justify-center"><ArrowUpRight className="w-4 h-4 text-green-600" /></div>
            <div><p className="text-[11px] text-slate-500">本月收入</p><p className="text-base font-bold text-green-600">{fmt(monthlyIncome)}</p></div>
          </CardContent>
        </Card>
        {/* 本月运营支出 */}
        <Card className="border-slate-200">
          <CardContent className="p-3 flex items-center gap-3">
            <div className="w-9 h-9 rounded-lg bg-red-50 flex items-center justify-center"><ArrowDownRight className="w-4 h-4 text-red-600" /></div>
            <div>
              <p className="text-[11px] text-slate-500">本月运营支出</p>
              <p className="text-base font-bold text-red-600">{fmt(monthlyCompanyExpenseUsd)}</p>
              <p className="text-[11px] text-slate-400">{fmtRMB(monthlyCompanyExpenseCny)} 单独统计</p>
            </div>
          </CardContent>
        </Card>
        {/* 本月客户成本(USD) */}
        <Card className="border-slate-200">
          <CardContent className="p-3 flex items-center gap-3">
            <div className="w-9 h-9 rounded-lg bg-amber-50 flex items-center justify-center"><ArrowDownRight className="w-4 h-4 text-amber-600" /></div>
            <div><p className="text-[11px] text-slate-500">本月客户成本 (USD)</p><p className="text-base font-bold text-amber-600">{fmt(monthlyCustomerExpense)}</p></div>
          </CardContent>
        </Card>
        <Card className="border-slate-200">
          <CardContent className="p-3 flex items-center gap-3">
            <div className={`w-9 h-9 rounded-lg ${monthlyProfitUsd >= 0 ? 'bg-emerald-50' : 'bg-red-50'} flex items-center justify-center`}>
              <Wallet className={`w-4 h-4 ${monthlyProfitUsd >= 0 ? 'text-emerald-600' : 'text-red-600'}`} />
            </div>
            <div><p className="text-[11px] text-slate-500">本月利润 (USD)</p><p className={`text-base font-bold ${monthlyProfitUsd >= 0 ? 'text-emerald-600' : 'text-red-600'}`}>{fmt(monthlyProfitUsd)}</p></div>
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
            <div><p className="text-[11px] text-slate-500">到期提醒</p><p className="text-base font-bold">{expiringSubs.length}</p></div>
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
      <Tabs defaultValue="income" className="w-full">
        <TabsList className="bg-slate-100 flex-wrap h-auto gap-1 p-1">
          <TabsTrigger value="income" className="text-xs sm:text-sm"><DollarSign className="w-3.5 h-3.5 mr-1 hidden sm:inline" />收入管理 ({filteredPayments.length})</TabsTrigger>
          <TabsTrigger value="customer_expense" className="text-xs sm:text-sm"><Users className="w-3.5 h-3.5 mr-1 hidden sm:inline" />客户支出 ({filteredExpenses.length})</TabsTrigger>
          <TabsTrigger value="company_expense" className="text-xs sm:text-sm"><Building2 className="w-3.5 h-3.5 mr-1 hidden sm:inline" />运营支出 ({filteredCompanyExpenses.length})</TabsTrigger>
          <TabsTrigger value="subscriptions" className="text-xs sm:text-sm"><Receipt className="w-3.5 h-3.5 mr-1 hidden sm:inline" />套餐续费 ({filteredSubscriptions.length})</TabsTrigger>
          <TabsTrigger value="charts" className="text-xs sm:text-sm"><PieChartIcon className="w-3.5 h-3.5 mr-1 hidden sm:inline" />数据分析</TabsTrigger>
          <TabsTrigger value="monthly_detail" className="text-xs sm:text-sm">按月明细</TabsTrigger>
        </TabsList>

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
                        <th className="px-3 py-2.5 font-medium">欠款</th>
                        <th className="px-3 py-2.5 font-medium hidden md:table-cell">模式</th>
                        <th className="px-3 py-2.5 font-medium hidden lg:table-cell">方式</th>
                        <th className="px-3 py-2.5 font-medium hidden md:table-cell">日期</th>
                        <th className="px-3 py-2.5 font-medium hidden lg:table-cell">发票</th>
                        <th className="px-3 py-2.5 font-medium w-20">操作</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredPayments.map(p => (
                        <tr key={p.id} className="border-b border-slate-100 hover:bg-slate-50">
                          <td className="px-3 py-2.5 font-medium">{p.customer_name || customerMap[p.customer_id]?.business_name || '-'}</td>
                          <td className="px-3 py-2.5">
                            <Badge style={{ backgroundColor: `${INCOME_TYPE_COLORS[p.income_type] || '#94a3b8'}20`, color: INCOME_TYPE_COLORS[p.income_type] || '#94a3b8' }} className="text-xs">
                              {incomeTypeLabels[p.income_type] || p.income_type || '-'}
                            </Badge>
                          </td>
                          <td className="px-3 py-2.5 max-w-[160px] truncate">{p.product_name}</td>
                          <td className="px-3 py-2.5">{fmt(p.amount_due)}</td>
                          <td className="px-3 py-2.5 text-green-600 font-medium">{fmt(p.amount_paid)}</td>
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
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
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
                  <p className="text-xs text-slate-500">总费用</p>
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
                        <th className="px-3 py-2.5 font-medium">月份</th>
                        <th className="px-3 py-2.5 font-medium hidden md:table-cell">备注</th>
                        <th className="px-3 py-2.5 font-medium w-20">操作</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredExpenses.map(e => (
                        <tr key={e.id} className="border-b border-slate-100 hover:bg-slate-50">
                          <td className="px-3 py-2.5 font-medium">{e.customer_name || customerMap[e.customer_id]?.business_name || '-'}</td>
                          <td className="px-3 py-2.5">
                            <Badge style={{ backgroundColor: `${pickColorByKey(e.expense_type, PIE_COLORS, CUSTOMER_EXPENSE_COLORS)}20`, color: pickColorByKey(e.expense_type, PIE_COLORS, CUSTOMER_EXPENSE_COLORS) }} className="text-xs">
                              {customerExpenseTypeLabels[e.expense_type] || e.expense_type}
                            </Badge>
                          </td>
                          <td className="px-3 py-2.5 font-medium">{fmt(e.amount || 0)}</td>
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
                      {filteredCompanyExpenses.map(e => {
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
                        <th className="px-3 py-2.5 font-medium">剩余天数</th>
                        <th className="px-3 py-2.5 font-medium">状态</th>
                        <th className="px-3 py-2.5 font-medium hidden lg:table-cell">续费负责</th>
                        <th className="px-3 py-2.5 font-medium w-16">操作</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredSubscriptions.map(s => {
                        const remainDays = getSubscriptionRemainingDays(s);
                        return (
                          <tr key={s.id} className={`border-b border-slate-100 hover:bg-slate-50 ${remainDays !== null && remainDays <= 0 ? 'bg-red-50/50' : remainDays !== null && remainDays <= 7 ? 'bg-amber-50/50' : ''}`}>
                            <td className="px-3 py-2.5 font-medium">{s.customer_name}</td>
                            <td className="px-3 py-2.5">{s.package_name}</td>
                            <td className="px-3 py-2.5">{fmt(s.package_price)}</td>
                            <td className="px-3 py-2.5 text-slate-500">{cycleLabels[s.billing_cycle] || s.billing_cycle}</td>
                            <td className="px-3 py-2.5 text-slate-500 hidden md:table-cell">{s.end_date?.slice(0, 10)}</td>
                            <td className="px-3 py-2.5">
                              {remainDays !== null ? (
                                remainDays <= 0 ? <span className="text-red-600 font-medium">已过期 {Math.abs(remainDays)} 天</span>
                                : remainDays <= 7 ? <span className="text-amber-600 font-medium">⚠️ 剩余 {remainDays} 天</span>
                                : <span className="text-slate-600">{remainDays} 天</span>
                              ) : '-'}
                            </td>
                            <td className="px-3 py-2.5"><Badge className={`text-xs ${subStatusColors[s.status]}`}>{subStatusLabels[s.status] || s.status}</Badge></td>
                            <td className="px-3 py-2.5 text-slate-500 hidden lg:table-cell">{s.renewal_person || '-'}</td>
                            <td className="px-3 py-2.5">
                              <Button size="sm" variant="ghost" className="h-7 w-7 p-0 text-slate-500 hover:text-red-600" onClick={() => setDeleteTarget({ type: 'subscription', item: s })}><Trash2 className="w-3.5 h-3.5" /></Button>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
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
                          companyExpUsd: '运营支出(USD)',
                          companyExpCny: '运营支出(CNY)',
                          profitUsd: '利润(USD)',
                        };
                        return <span className="text-xs text-slate-600">{labels[value] || value}</span>;
                      }} />
                      <Bar dataKey="income" fill="#10b981" radius={[4, 4, 0, 0]} maxBarSize={24} />
                      <Bar dataKey="customerExp" fill="#f59e0b" radius={[4, 4, 0, 0]} maxBarSize={24} />
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
                        <th className="px-3 py-2.5 font-medium">管理费扣点率</th>
                        <th className="px-3 py-2.5 font-medium">管理费扣点</th>
                        <th className="px-3 py-2.5 font-medium">投流充值 1%</th>
                        <th className="px-3 py-2.5 font-medium">总扣点</th>
                        <th className="px-3 py-2.5 font-medium">客户成本</th>
                        <th className="px-3 py-2.5 font-medium">USD运营支出</th>
                        <th className="px-3 py-2.5 font-medium">总成本 (cost)</th>
                        <th className="px-3 py-2.5 font-medium">利润 (profit)</th>
                      </tr>
                    </thead>
                    <tbody>
                      {monthlyDetail.rows.map((r: any) => (
                        <tr key={r.month} className="border-b border-slate-100 hover:bg-slate-50">
                          <td className="px-3 py-2.5 font-medium">{r.month}</td>
                          <td className="px-3 py-2.5">{fmt(r.revenue_gross)}</td>
                          <td className="px-3 py-2.5">{r.management_rate > 0 ? `${Math.round(r.management_rate * 100)}%` : '-'}</td>
                          <td className="px-3 py-2.5">{fmt(r.management_deduction_amount)}</td>
                          <td className="px-3 py-2.5">{fmt(r.ads_recharge_deduction_amount)}</td>
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
              <Label>收入类型 *</Label>
              <NativeSelect value={payForm.income_type} onChange={v => setPayForm({ ...payForm, income_type: v })}
                options={Object.entries(incomeTypeLabels).map(([k, v]) => ({ value: k, label: v }))} />
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
            <div className="grid grid-cols-2 gap-4">
              <div>
                <Label>收款模式</Label>
                <NativeSelect
                  value={payForm.payment_mode}
                  onChange={v => setPayForm({ ...payForm, payment_mode: v })}
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
