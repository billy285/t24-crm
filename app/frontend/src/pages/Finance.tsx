import { useState, useEffect, useMemo } from 'react';
import { client } from '../lib/api';
import { invokeWithAuth } from '@/lib/tokenStore';
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

// ─── Constants ───────────────────────────────────────────────────────
const incomeTypeLabels: Record<string, string> = {
  management_fee: '管理费', ads_fee: '投流费', website_fee: '网站费',
  ordering_fee: '点餐系统费', renewal_fee: '续费收入', other_income: '其他收入',
};
const INCOME_TYPE_COLORS: Record<string, string> = {
  management_fee: '#3b82f6', ads_fee: '#f59e0b', website_fee: '#10b981',
  ordering_fee: '#8b5cf6', renewal_fee: '#06b6d4', other_income: '#94a3b8',
};

const customerExpenseTypeLabels: Record<string, string> = {
  management_fee: '管理费', ads_fee: '投流费', website_fee: '网站费', other: '其他',
};
const CUSTOMER_EXPENSE_COLORS: Record<string, string> = {
  management_fee: '#3b82f6', ads_fee: '#f59e0b', website_fee: '#10b981', other: '#94a3b8',
};

const companyExpenseTypeLabels: Record<string, string> = {
  salary: '工资', internet: '网络费', phone: '电话费', rent: '办公室租金',
  software: '软件订阅费', recruitment: '招聘费', travel: '差旅费', other_company: '其他支出',
};
const COMPANY_EXPENSE_COLORS: Record<string, string> = {
  salary: '#ef4444', internet: '#3b82f6', phone: '#10b981', rent: '#f59e0b',
  software: '#8b5cf6', recruitment: '#ec4899', travel: '#06b6d4', other_company: '#94a3b8',
};

const productOptions = [
  { value: 'Google商家', label: 'Google商家' },
  { value: 'Facebook商家', label: 'Facebook商家' },
  { value: 'Instagram商家', label: 'Instagram商家' },
  { value: 'Yelp商家', label: 'Yelp商家' },
  { value: 'Tiktok商家', label: 'Tiktok商家' },
  { value: '小红书商家', label: '小红书商家' },
  { value: '品牌官网', label: '品牌官网' },
  { value: 'Google Ads', label: 'Google Ads' },
  { value: 'Meta Ads', label: 'Meta Ads' },
];

const payMethodLabels: Record<string, string> = {
  cash: '现金', check: '支票', zelle: 'Zelle', wire: '电汇',
  credit_card: '信用卡', subscription_debit: '订阅扣款', other: '其他',
};
const PAY_METHOD_COLORS: Record<string, string> = {
  cash: '#10b981', check: '#3b82f6', zelle: '#8b5cf6', wire: '#f59e0b',
  credit_card: '#ef4444', subscription_debit: '#06b6d4', other: '#94a3b8',
};
const cycleLabels: Record<string, string> = {
  monthly: '月付', quarterly: '季付', semi_annual: '半年付', annual: '年付',
};
const subStatusLabels: Record<string, string> = {
  active: '正常', expiring_soon: '即将到期', expired: '已到期', paused: '暂停', lost: '流失',
};
const subStatusColors: Record<string, string> = {
  active: 'bg-green-100 text-green-700', expiring_soon: 'bg-amber-100 text-amber-700',
  expired: 'bg-red-100 text-red-700', paused: 'bg-slate-100 text-slate-600', lost: 'bg-red-100 text-red-700',
};

const PIE_COLORS = ['#3b82f6', '#ef4444', '#f59e0b', '#10b981', '#8b5cf6', '#ec4899', '#06b6d4', '#f97316', '#6366f1'];

// ─── Helper: format currency ─────────────────────────────────────────
const fmt = (n: number) => `$${n.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 2 })}`;
const fmtRMB = (n: number) => `¥${n.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 2 })}`;

// Compute profit (USD) with monthly deduction rates
function computeProfitUSD(paymentsList: any[], customerExpensesUSD: any[]) {
  // group revenue by YYYY-MM
  const byMonth: Record<string, { revenue: number; custExp: number }> = {};
  for (const p of paymentsList) {
    const ym = (p.payment_date || '').slice(0,7);
    if (!/^\d{4}-\d{2}$/.test(ym)) continue;
    byMonth[ym] = byMonth[ym] || { revenue: 0, custExp: 0 };
    byMonth[ym].revenue += Number(p.amount_paid || 0);
  }
  for (const e of customerExpensesUSD) {
    const ym = (e.expense_month || '').slice(0,7);
    if (!/^\d{4}-\d{2}$/.test(ym)) continue;
    byMonth[ym] = byMonth[ym] || { revenue: 0, custExp: 0 };
    byMonth[ym].custExp += Number(e.amount || 0);
  }
  let total = 0;
  for (const ym of Object.keys(byMonth)) {
    const r = byMonth[ym];
    const rate = (deductionRates && typeof deductionRates[ym] === 'number') ? deductionRates[ym] : 0.15; // default 15%
    total += (r.revenue * (1 - rate)) - r.custExp;
  }
  return total;
}


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
    amount_due: '', amount_paid: '', payment_method: 'zelle', billing_cycle: 'monthly',
    coverage_start: '', coverage_end: '', has_invoice: false, notes: '',
  };
  const [payForm, setPayForm] = useState(emptyPayForm);

  // Customer expense form
  const [showExpenseForm, setShowExpenseForm] = useState(false);
  const [editingExpenseId, setEditingExpenseId] = useState<number | null>(null);
  const [savingExpense, setSavingExpense] = useState(false);
  const [expenseMonth, setExpenseMonth] = useState(() => {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
  });
  const emptyExpenseForm = { customer_id: '', expense_type: 'management_fee', amount: '', expense_month: expenseMonth, notes: '' };
  const [expenseForm, setExpenseForm] = useState(emptyExpenseForm);

  // Company expense form
  const [showCompanyExpenseForm, setShowCompanyExpenseForm] = useState(false);
  const [editingCompanyExpenseId, setEditingCompanyExpenseId] = useState<number | null>(null);
  const [savingCompanyExpense, setSavingCompanyExpense] = useState(false);
  const [companyExpenseMonth, setCompanyExpenseMonth] = useState(() => {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
  });
  const emptyCompanyExpenseForm = { category: 'salary', amount: '', expense_month: companyExpenseMonth, expense_date: '', notes: '' };
  const [companyExpenseForm, setCompanyExpenseForm] = useState(emptyCompanyExpenseForm);

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

  const computeSubStatus = (sub: any): string => {
    if (!sub.end_date) return sub.status || 'active';
    if (sub.status === 'paused' || sub.status === 'lost') return sub.status;
    const endDate = new Date(sub.end_date);
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const diffDays = Math.ceil((endDate.getTime() - today.getTime()) / 86400000);
    if (diffDays <= 0) return 'expired';
    if (diffDays <= 7) return 'expiring_soon';
    return 'active';
  };

  const loadData = async () => {
    try {
      // Load each data source independently so one failure doesn't block others
      const [pItems, sItems, cItems, eItems, ceItems] = await Promise.all([
        safeQuery(() => client.entities.payments.queryAll({ limit: 500, sort: '-payment_date' })),
        safeQuery(() => client.entities.subscriptions.query({ limit: 500, sort: '-end_date' })),
        safeQuery(() => client.entities.customers.query({ limit: 500 })),
        safeQuery(() => client.entities.expenses.queryAll({ limit: 500, sort: '-created_at' })),
        safeQuery(() => client.entities.company_expenses.queryAll({ limit: 500, sort: '-created_at' })),
      ]);
      setPayments(pItems);
      setSubscriptions(sItems.map((s: any) => ({ ...s, status: computeSubStatus(s) })));
      setCustomers(cItems);
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
  const filteredCompanyExpenses = companyExpenses.filter(e => !companyExpenseMonth || e.expense_month === companyExpenseMonth);

  // ─── Stats ───────────────────────────────────────────────────────
  const now = new Date();
  const currentMonthKey = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;
  const monthlyIncome = payments.filter(p => p.payment_date?.slice(0, 7) === currentMonthKey).reduce((s, p) => s + (p.amount_paid || 0), 0);
  const monthlyCustomerExpense = expenses.filter(e => e.expense_month === currentMonthKey).reduce((s, e) => s + (e.amount || 0), 0); // USD
  const monthlyCompanyExpense = companyExpenses.filter(e => e.expense_month === currentMonthKey).reduce((s, e) => s + (e.amount || 0), 0); // CNY
  // IMPORTANT: Do not mix currencies. Profit here is USD-only: income (USD) - customer expense (USD).
  const monthlyProfitUsd = monthlyIncome - monthlyCustomerExpense;
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

  const totalCompanyExpense = filteredCompanyExpenses.reduce((s, e) => s + (e.amount || 0), 0);
  const companyExpenseByType = useMemo(() => {
    const map: Record<string, number> = {};
    filteredCompanyExpenses.forEach(e => { map[e.category] = (map[e.category] || 0) + (e.amount || 0); });
    return Object.entries(map).map(([type, amount]) => ({
      type, name: companyExpenseTypeLabels[type] || type, amount: Math.round(amount * 100) / 100,
    })).sort((a, b) => b.amount - a.amount);
  }, [filteredCompanyExpenses]);

  // ─── Chart Data ──────────────────────────────────────────────────
  const monthlyTrendData = useMemo(() => {
    const months: { key: string; label: string; income: number; customerExp: number; companyExp: number; profitUsd: number }[] = [];
    for (let i = 11; i >= 0; i--) {
      const d = new Date(now.getFullYear(), now.getMonth() - i, 1);
      const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
      const label = `${d.getMonth() + 1}月`;
      const income = payments.filter(p => p.payment_date?.slice(0, 7) === key).reduce((s, p) => s + (p.amount_paid || 0), 0);
      const custExp = expenses.filter(e => e.expense_month === key).reduce((s, e) => s + (e.amount || 0), 0); // USD
      const compExp = companyExpenses.filter(e => e.expense_month === key).reduce((s, e) => s + (e.amount || 0), 0); // CNY
      // Do not mix currencies. Profit is USD-only.
      months.push({ key, label, income, customerExp: custExp, companyExp: compExp, profitUsd: income - custExp });
    }
    return months;
  }, [payments, expenses, companyExpenses]);

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

    const map: Record<string, { revenue: number; cost: number }> = {};
    payments.forEach((p: any) => {
      const ym = p.payment_date?.slice(0, 7);
      if (!/^\d{4}-\d{2}$/.test(ym || '')) return;
      if (!inRange(ym!)) return;
      map[ym!] = map[ym!] || { revenue: 0, cost: 0 };
      map[ym!].revenue += Number(p.amount_paid || 0);
    });
    expenses.forEach((e: any) => {
      const ym = e.expense_month;
      if (!/^\d{4}-\d{2}$/.test(ym || '')) return;
      if (!inRange(ym!)) return;
      map[ym!] = map[ym!] || { revenue: 0, cost: 0 };
      map[ym!].cost += Number(e.amount || 0);
    });

    const rows = Object.keys(map).sort().map(ym => {
      const revenue = map[ym].revenue;
      const cost = map[ym].cost;
      const rate = (deductionRates && typeof deductionRates[ym] === 'number') ? deductionRates[ym] : 0.15;
      const deduction_amount = revenue * rate;
      const profit = revenue - deduction_amount - cost;
      return {
        month: ym,
        revenue_gross: Math.round(revenue * 100) / 100,
        deduction_rate: rate,
        deduction_amount: Math.round(deduction_amount * 100) / 100,
        cost: Math.round(cost * 100) / 100,
        profit: Math.round(profit * 100) / 100,
      };
    });

    return { rows, range: { start, end } };
  }, [payments, expenses, deductionRates, dateFilterMode, filterStartDate, filterEndDate]);


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
      const method = p.payment_method || 'other';
      countMap[method] = (countMap[method] || 0) + 1;
      amountMap[method] = (amountMap[method] || 0) + (p.amount_paid || 0);
    });
    return Object.entries(countMap).map(([method, count]) => ({
      name: payMethodLabels[method] || method, method, count,
      amount: Math.round((amountMap[method] || 0) * 100) / 100,
    })).sort((a, b) => b.amount - a.amount);
  }, [payments]);

  // ─── Customer map for lookups ────────────────────────────────────
  const customerMap = useMemo(() => Object.fromEntries(customers.map(c => [c.id, c])), [customers]);

  // ─── Payment CRUD ────────────────────────────────────────────────
  const openEditPayment = (p: any) => {
    const names = p.product_name ? p.product_name.split('、').map((s: string) => s.trim()).filter(Boolean) : [];
    setPayForm({
      customer_id: String(p.customer_id || ''), product_names: names,
      income_type: p.income_type || 'management_fee',
      amount_due: String(p.amount_due || ''), amount_paid: String(p.amount_paid || ''),
      payment_method: p.payment_method || 'zelle', billing_cycle: p.billing_cycle || 'monthly',
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
      const payload: Record<string, any> = {
        customer_id: Number(payForm.customer_id),
        customer_name: cust?.business_name || '',
        income_type: payForm.income_type,
        product_name: payForm.product_names.join('、'),
        amount_due: amountDue, amount_paid: amountPaid,
        payment_method: payForm.payment_method, billing_cycle: payForm.billing_cycle,
        coverage_start: coverageStartISO, coverage_end: coverageEndISO,
        has_invoice: payForm.has_invoice,
        outstanding_amount: Math.max(0, amountDue - amountPaid),
        expense_month: payForm.coverage_start ? payForm.coverage_start.slice(0, 7) : currentMonthKey,
        notes: payForm.notes || null,
      };
      if (editingPayId) {
        await client.entities.payments.update({ id: String(editingPayId), data: payload });
        toast.success('收款记录已更新');
      } else {
        payload.payment_date = new Date().toISOString();
        payload.created_at = new Date().toISOString();
        await client.entities.payments.create({ data: payload });
        toast.success('收款记录已添加');
      }
      // Auto-create or update subscription
      if (coverageEndISO) {
        try {
          const endDate = new Date(coverageEndISO);
          const today = new Date(); today.setHours(0, 0, 0, 0);
          const diffDays = Math.ceil((endDate.getTime() - today.getTime()) / 86400000);
          let status = 'active';
          if (diffDays <= 0) status = 'expired';
          else if (diffDays <= 7) status = 'expiring_soon';

          const subData = {
            customer_id: Number(payForm.customer_id), customer_name: cust?.business_name || '',
            package_name: payForm.product_names.join('、'), package_price: amountDue,
            billing_cycle: payForm.billing_cycle,
            start_date: coverageStartISO || new Date().toISOString(),
            end_date: coverageEndISO, status, auto_renew: false,
            renewal_person: '', next_payment_date: coverageEndISO,
          };

          if (editingPayId) {
            // When editing a payment, find the existing subscription for this customer and update it
            const existingSubs = subscriptions.filter(
              s => s.customer_id === Number(payForm.customer_id)
            );
            // Find the most recent subscription that matches the customer
            const matchingSub = existingSubs.length > 0
              ? existingSubs.sort((a: any, b: any) => (b.id || 0) - (a.id || 0))[0]
              : null;

            if (matchingSub) {
              await client.entities.subscriptions.update({
                id: String(matchingSub.id),
                data: subData,
              });
            } else {
              // No existing subscription found, create a new one
              await client.entities.subscriptions.create({
                data: { ...subData, created_at: new Date().toISOString() },
              });
            }
          } else {
            // Creating a new payment, create a new subscription
            await client.entities.subscriptions.create({
              data: { ...subData, created_at: new Date().toISOString() },
            });
          }
        } catch (subErr) { console.error('Auto-create/update subscription failed:', subErr); }
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
        await client.entities.expenses.update({ id: String(editingExpenseId), data: payload });
        toast.success('费用记录已更新');
      } else {
        payload.payment_date = new Date().toISOString();
        payload.created_at = new Date().toISOString();
        await client.entities.expenses.create({ data: payload });
        toast.success('费用记录已添加');
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
      await client.entities.expenses.delete({ id: String(deleteExpenseTarget.id) });
      toast.success('费用记录已删除'); setDeleteExpenseTarget(null); loadData();
    } catch (err) { toast.error('删除失败'); console.error(err); } finally { setDeletingExpense(false); }
  };

  // ─── Company Expense CRUD ────────────────────────────────────────
  const openEditCompanyExpense = (e: any) => {
    setCompanyExpenseForm({
      category: e.category || 'salary', amount: String(e.amount || ''),
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
        expense_month: companyExpenseForm.expense_month,
        expense_date: toISODatetime(companyExpenseForm.expense_date) || new Date().toISOString(),
        notes: companyExpenseForm.notes || null,
      };
      if (editingCompanyExpenseId) {
        await client.entities.company_expenses.update({ id: String(editingCompanyExpenseId), data: payload });
        toast.success('公司支出已更新');
      } else {
        payload.created_at = new Date().toISOString();
        await client.entities.company_expenses.create({ data: payload });
        toast.success('公司支出已添加');
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
      await client.entities.company_expenses.delete({ id: String(deleteCompanyExpenseTarget.id) });
      toast.success('公司支出已删除'); setDeleteCompanyExpenseTarget(null); loadData();
    } catch (err) { toast.error('删除失败'); console.error(err); } finally { setDeletingCompanyExpense(false); }
  };

  // ─── Delete payment/subscription ─────────────────────────────────
  const handleDeleteRecord = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      if (deleteTarget.type === 'payment') {
        await client.entities.payments.delete({ id: String(deleteTarget.item.id) });
        toast.success('收款记录已删除');
      } else {
        await client.entities.subscriptions.delete({ id: String(deleteTarget.item.id) });
        toast.success('套餐记录已删除');
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
    setPayForm(prev => ({ ...prev, customer_id: val }));
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
        {/* 本月公司支出(CNY) */}
        <Card className="border-slate-200">
          <CardContent className="p-3 flex items-center gap-3">
            <div className="w-9 h-9 rounded-lg bg-red-50 flex items-center justify-center"><ArrowDownRight className="w-4 h-4 text-red-600" /></div>
            <div><p className="text-[11px] text-slate-500">本月公司支出 (CNY)</p><p className="text-base font-bold text-red-600">{fmtRMB(monthlyCompanyExpense)}</p></div>
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
          <TabsTrigger value="company_expense" className="text-xs sm:text-sm"><Building2 className="w-3.5 h-3.5 mr-1 hidden sm:inline" />公司支出 ({filteredCompanyExpenses.length})</TabsTrigger>
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
                        <th className="px-3 py-2.5 font-medium hidden md:table-cell">方式</th>
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
                          <td className="px-3 py-2.5 text-slate-500 hidden md:table-cell">{payMethodLabels[p.payment_method] || p.payment_method}</td>
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
                <Button size="sm" onClick={() => { setExpenseForm({ ...emptyExpenseForm, expense_month: expenseMonth }); setEditingExpenseId(null); setShowExpenseForm(true); }} className="bg-blue-600 hover:bg-blue-700">
                  <Plus className="w-4 h-4 mr-1" /> 录入客户支出
                </Button>
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
                    <p className="text-lg font-bold" style={{ color: CUSTOMER_EXPENSE_COLORS[et.type] || '#64748b' }}>{fmt(et.amount)}</p>
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
                            <Badge style={{ backgroundColor: `${CUSTOMER_EXPENSE_COLORS[e.expense_type] || '#94a3b8'}20`, color: CUSTOMER_EXPENSE_COLORS[e.expense_type] || '#94a3b8' }} className="text-xs">
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
                  {companyExpenseMonth && <Button variant="ghost" size="sm" className="h-8 text-xs text-slate-500" onClick={() => setCompanyExpenseMonth('')}>查看全部</Button>}
                </div>
                <Button size="sm" onClick={() => { setCompanyExpenseForm({ ...emptyCompanyExpenseForm, expense_month: companyExpenseMonth }); setEditingCompanyExpenseId(null); setShowCompanyExpenseForm(true); }} className="bg-blue-600 hover:bg-blue-700">
                  <Plus className="w-4 h-4 mr-1" /> 录入公司支出
                </Button>
              </div>

              {/* Summary */}
              <div className="grid grid-cols-2 sm:grid-cols-5 gap-3 mb-4">
                <div className="p-3 bg-slate-50 rounded-lg">
                  <p className="text-xs text-slate-500">总支出</p>
                  <p className="text-lg font-bold text-slate-800">{fmtRMB(totalCompanyExpense)}</p>
                </div>
                {companyExpenseByType.map(et => (
                  <div key={et.type} className="p-3 bg-slate-50 rounded-lg">
                    <p className="text-xs text-slate-500">{et.name}</p>
                    <p className="text-lg font-bold" style={{ color: COMPANY_EXPENSE_COLORS[et.type] || '#64748b' }}>{fmtRMB(et.amount)}</p>
                  </div>
                ))}
              </div>

              {filteredCompanyExpenses.length === 0 ? (
                <p className="text-center text-slate-400 py-12">{companyExpenseMonth ? `${companyExpenseMonth} 暂无公司支出记录` : '暂无公司支出记录'}</p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b bg-slate-50 text-left text-slate-500">
                        <th className="px-3 py-2.5 font-medium">支出类型</th>
                        <th className="px-3 py-2.5 font-medium">金额</th>
                        <th className="px-3 py-2.5 font-medium">月份</th>
                        <th className="px-3 py-2.5 font-medium hidden md:table-cell">支出日期</th>
                        <th className="px-3 py-2.5 font-medium hidden md:table-cell">备注</th>
                        <th className="px-3 py-2.5 font-medium w-20">操作</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredCompanyExpenses.map(e => (
                        <tr key={e.id} className="border-b border-slate-100 hover:bg-slate-50">
                          <td className="px-3 py-2.5">
                            <Badge style={{ backgroundColor: `${COMPANY_EXPENSE_COLORS[e.category] || '#94a3b8'}20`, color: COMPANY_EXPENSE_COLORS[e.category] || '#94a3b8' }} className="text-xs">
                              {companyExpenseTypeLabels[e.category] || e.category_name || e.category}
                            </Badge>
                          </td>
                          <td className="px-3 py-2.5 font-medium">{fmtRMB(e.amount || 0)}</td>
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
                      ))}
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
                        const endDate = s.end_date ? new Date(s.end_date) : null;
                        const today = new Date(); today.setHours(0, 0, 0, 0);
                        const remainDays = endDate ? Math.ceil((endDate.getTime() - today.getTime()) / 86400000) : null;
                        return (
                          <tr key={s.id} className={`border-b border-slate-100 hover:bg-slate-50 ${s.status === 'expiring_soon' ? 'bg-amber-50/50' : s.status === 'expired' ? 'bg-red-50/50' : ''}`}>
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
                          const labels: Record<string, string> = { income: '收入(USD)', customerExp: '客户支出(USD)', companyExp: '公司支出(CNY)', profitUsd: '利润(USD)' };
                          const formatted = name === 'companyExp' ? fmtRMB(value) : fmt(value);
                          return [formatted, labels[name] || name];
                        }}
                      />
                      <Legend formatter={(value) => {
                        const labels: Record<string, string> = { income: '收入(USD)', customerExp: '客户支出(USD)', companyExp: '公司支出(CNY)', profitUsd: '利润(USD)' };
                        return <span className="text-xs text-slate-600">{labels[value] || value}</span>;
                      }} />
                      <Bar dataKey="income" fill="#10b981" radius={[4, 4, 0, 0]} maxBarSize={24} />
                      <Bar dataKey="customerExp" fill="#f59e0b" radius={[4, 4, 0, 0]} maxBarSize={24} />
                      <Bar dataKey="companyExp" fill="#ef4444" radius={[4, 4, 0, 0]} maxBarSize={24} />
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

            {/* Payment Method Pie */}
            <Card className="border-slate-200">
              <CardHeader className="pb-2">
                <CardTitle className="text-base font-semibold text-slate-700">支付方式分布</CardTitle>
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
                <CardTitle className="text-base font-semibold text-slate-700">公司支出明细</CardTitle>
              </CardHeader>
              <CardContent>
                {companyExpenseByType.length === 0 ? (
                  <p className="text-center text-slate-400 py-12">暂无公司支出数据</p>
                ) : (
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <ResponsiveContainer width="100%" height={260}>
                      <PieChart>
                        <Pie data={companyExpenseByType.map(d => ({ name: d.name, value: d.amount, type: d.type }))} cx="50%" cy="50%" innerRadius={55} outerRadius={90} paddingAngle={2} dataKey="value"
                          label={({ name, percent }) => `${name} ${(percent * 100).toFixed(0)}%`}
                          labelLine={{ stroke: '#94a3b8', strokeWidth: 1 }}>
                          {companyExpenseByType.map((d) => (
                            <Cell key={d.type} fill={COMPANY_EXPENSE_COLORS[d.type] || '#94a3b8'} />
                          ))}
                        </Pie>
                        <Tooltip contentStyle={{ borderRadius: 8, border: '1px solid #e2e8f0' }} formatter={(value: number) => [fmtRMB(value), '支出']} />
                      </PieChart>
                    </ResponsiveContainer>
                    <div className="space-y-2">
                      {companyExpenseByType.map(d => {
                        const pct = totalCompanyExpense > 0 ? ((d.amount / totalCompanyExpense) * 100).toFixed(1) : '0';
                        return (
                          <div key={d.type} className="flex items-center justify-between p-2 bg-slate-50 rounded-lg">
                            <div className="flex items-center gap-2">
                              <span className="w-3 h-3 rounded-full" style={{ backgroundColor: COMPANY_EXPENSE_COLORS[d.type] || '#94a3b8' }} />
                              <span className="text-sm text-slate-700">{d.name}</span>
                            </div>
                            <div className="flex items-center gap-3">
                              <span className="text-sm font-medium text-slate-800">{fmtRMB(d.amount)}</span>
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
                        <th className="px-3 py-2.5 font-medium">收入收入 (revenue_gross)</th>
                        <th className="px-3 py-2.5 font-medium">扣点率</th>
                        <th className="px-3 py-2.5 font-medium">扣点金额</th>
                        <th className="px-3 py-2.5 font-medium">成本 (cost)</th>
                        <th className="px-3 py-2.5 font-medium">利润 (profit)</th>
                      </tr>
                    </thead>
                    <tbody>
                      {monthlyDetail.rows.map((r: any) => (
                        <tr key={r.month} className="border-b border-slate-100 hover:bg-slate-50">
                          <td className="px-3 py-2.5 font-medium">{r.month}</td>
                          <td className="px-3 py-2.5">{fmt(r.revenue_gross)}</td>
                          <td className="px-3 py-2.5">{Math.round(r.deduction_rate * 100)}%</td>
                          <td className="px-3 py-2.5">{fmt(r.deduction_amount)}</td>
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
              <Label>产品名称 *（可多选）</Label>
              <div className="grid grid-cols-3 gap-2 mt-2 p-3 border rounded-md bg-slate-50">
                {productOptions.map(opt => (
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
              {payForm.product_names.length > 0 && <p className="text-xs text-slate-500 mt-1">已选: {payForm.product_names.join('、')}</p>}
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div><Label>应收金额 *</Label><Input type="number" value={payForm.amount_due} onChange={e => setPayForm({ ...payForm, amount_due: e.target.value })} placeholder="0.00" /></div>
              <div><Label>实收金额 *</Label><Input type="number" value={payForm.amount_paid} onChange={e => setPayForm({ ...payForm, amount_paid: e.target.value })} placeholder="0.00" /></div>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <Label>支付方式</Label>
                <NativeSelect value={payForm.payment_method} onChange={v => setPayForm({ ...payForm, payment_method: v })}
                  options={Object.entries(payMethodLabels).map(([k, label]) => ({ value: k, label }))} />
              </div>
              <div>
                <Label>周期类型</Label>
                <NativeSelect value={payForm.billing_cycle} onChange={v => setPayForm({ ...payForm, billing_cycle: v })}
                  options={Object.entries(cycleLabels).map(([k, v]) => ({ value: k, label: v }))} />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div><Label>覆盖开始</Label><Input type="date" value={payForm.coverage_start} onChange={e => setPayForm({ ...payForm, coverage_start: e.target.value })} /></div>
              <div><Label>覆盖结束</Label><Input type="date" value={payForm.coverage_end} onChange={e => setPayForm({ ...payForm, coverage_end: e.target.value })} /></div>
            </div>
            <div className="flex items-center gap-2"><Switch checked={payForm.has_invoice} onCheckedChange={v => setPayForm({ ...payForm, has_invoice: v })} /><Label>已开票</Label></div>
            <div><Label>备注</Label><Textarea value={payForm.notes} onChange={e => setPayForm({ ...payForm, notes: e.target.value })} rows={2} /></div>
          </div>
          <div className="flex justify-end gap-2 mt-4">
            <Button variant="outline" onClick={() => setShowPaymentForm(false)}>取消</Button>
            <Button onClick={handleSavePayment} disabled={saving} className="bg-blue-600 hover:bg-blue-700">{saving ? '保存中...' : '保存'}</Button>
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
                <Label>费用类型 *</Label>
                <NativeSelect value={expenseForm.expense_type} onChange={v => setExpenseForm({ ...expenseForm, expense_type: v })}
                  options={Object.entries(customerExpenseTypeLabels).map(([k, v]) => ({ value: k, label: v }))} />
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
          <DialogHeader><DialogTitle>{editingCompanyExpenseId ? '编辑公司支出' : '录入公司支出'}</DialogTitle></DialogHeader>
          <div className="space-y-4">
            <div>
              <Label>支出类型 *</Label>
              <NativeSelect value={companyExpenseForm.category} onChange={v => setCompanyExpenseForm({ ...companyExpenseForm, category: v })}
                options={Object.entries(companyExpenseTypeLabels).map(([k, v]) => ({ value: k, label: v }))} />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <Label>金额 *</Label>
                <Input type="number" value={companyExpenseForm.amount} onChange={e => setCompanyExpenseForm({ ...companyExpenseForm, amount: e.target.value })} placeholder="0.00" />
              </div>
              <div>
                <Label>支出日期</Label>
                <Input type="date" value={companyExpenseForm.expense_date} onChange={e => setCompanyExpenseForm({ ...companyExpenseForm, expense_date: e.target.value })} />
              </div>
            </div>
            <div>
              <Label>支出月份</Label>
              <Input type="month" value={companyExpenseForm.expense_month} onChange={e => setCompanyExpenseForm({ ...companyExpenseForm, expense_month: e.target.value })} />
            </div>
            <div><Label>备注</Label><Textarea value={companyExpenseForm.notes} onChange={e => setCompanyExpenseForm({ ...companyExpenseForm, notes: e.target.value })} rows={2} /></div>
          </div>
          <div className="flex justify-end gap-2 mt-4">
            <Button variant="outline" onClick={() => setShowCompanyExpenseForm(false)}>取消</Button>
            <Button onClick={handleSaveCompanyExpense} disabled={savingCompanyExpense} className="bg-blue-600 hover:bg-blue-700">{savingCompanyExpense ? '保存中...' : '保存'}</Button>
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
        title="确认删除公司支出记录"
        description={`确定要删除「${companyExpenseTypeLabels[deleteCompanyExpenseTarget?.category] || ''}」的公司支出记录吗？`}
        onConfirm={handleDeleteCompanyExpense} loading={deletingCompanyExpense} />
    </div>
  );
}