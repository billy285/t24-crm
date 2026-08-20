import { useState, useEffect, useMemo } from 'react';
import { client } from '../lib/api';
import { useRole } from '../lib/role-context';
import { invokeWithAuth } from '../lib/tokenStore';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { NativeSelect } from '@/components/ui/native-select';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { useNavigate } from 'react-router-dom';
import {
  Users, UserPlus, Handshake, AlertTriangle, DollarSign,
  Clock, TrendingUp, ListTodo, Bell, CalendarClock, CreditCard, PackageCheck,
  Palette, CheckCircle2, Timer, PhoneCall, Target, PhoneForwarded,
  CalendarCheck2, ShieldAlert, FileCheck2, Banknote, ArrowRight,
  Activity, Database, Gauge, RefreshCw, Layers3, CircleDollarSign, Workflow, ChevronDown
} from 'lucide-react';
import { useBusinessDicts } from '../lib/dict-config';
import { decorateEffectiveSubscriptions } from '../lib/subscription-utils';
import { useAutoRefresh } from '../lib/use-auto-refresh';
import PageLoadState from '@/components/PageLoadState';
import { getLoadErrorMessage } from '../lib/load-utils';

interface Reminder {
  id: string;
  type: 'follow_up' | 'renewal' | 'overdue_payment' | 'pending_task' | 'no_follow_7d' | 'callback';
  title: string;
  description: string;
  urgency: 'high' | 'medium' | 'low';
  date?: string;
  link?: string;
}

type SalesManagementDashboard = {
  target_date: string;
  metrics: {
    assigned: number; completed: number; completion_rate: number; calls: number;
    connected: number; connection_rate: number; interested: number; interest_rate: number;
    appointments: number; appointment_rate: number; converted: number; conversion_rate: number;
  };
  owner_attention?: {
    high_intent_stale: number; due_followups: number; overdue_followups: number;
    pending_quotes: number; unpaid_handoffs: number;
  };
  deal_pipeline?: {
    pending_quotes: number; approved_quotes: number; approved_quote_amount: number;
    confirmed_received_amount: number; unpaid_handoffs: number;
  };
};

type SalesPerformanceItem = {
  rank: number; sales_employee_id: number; salesperson: string; score: number; confidence: string;
  metrics: {
    assigned: number; completed: number; calls: number; connected: number; interested: number;
    appointments: number; conversions: number; completion_rate: number; connection_rate: number;
    interest_rate: number; note_quality_rate: number; overdue_followups: number;
  };
  suggestions: string[];
};

type SalesPerformanceDashboard = {
  period: { days: number; start_date: string; end_date: string };
  items: SalesPerformanceItem[];
};

type SalesRecoveryOverview = {
  summary: { recoverable: number; watch: number; protected: number; extended: number; extension_requests: number };
};

type PayrollSummary = { items: { month: string; status: 'draft' | 'confirmed' | 'paid'; currency: string }[]; pending_count: number };

type OwnerCockpit = {
  as_of: string;
  period: { month: string; today: string };
  finance: {
    month: string;
    USD: {
      gross_receipts: number; refund_amount: number; net_receipts: number;
      service_revenue: number; ads_client_funds: number; recognized_ad_spread: number;
      deduction_amount: number; stripe_platform_fee: number; channel_commission: number; cost: number; profit: number;
    };
    company_cost_cny: number;
    currency_policy: string;
  };
  customers: {
    active_projects: number; at_risk_projects: number; stopped_this_month: number;
    business_lines: { code: string; name: string; active_projects: number }[];
  };
  execution: { open_tasks: number; overdue_tasks: number; system_tasks: number; completed_this_month: number };
  delivery: { active_service_records: number; overdue_service_tasks: number; unresolved_service_issues: number; overdue_callbacks: number };
  quality: { open: number; in_progress: number; resolved: number; open_task_count: number; category_counts: Record<string, number>; severity_counts: Record<string, number> };
  automation: {
    last_run: null | { status: string; detected_count: number; completed_at?: string };
    schedule: { enabled: boolean; timezone: string; hour: number; next_run_at: string; auto_stop_enabled: boolean };
  };
  decisions: { key: string; level: 'critical' | 'high' | 'medium'; title: string; count: number; description: string; link: string }[];
  decision_state: 'healthy' | 'attention';
};

const buildReminderLink = (path: string, params: Record<string, string | number | null | undefined>) => {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== null && value !== undefined && String(value).trim() !== '') {
      query.set(key, String(value));
    }
  });
  const queryString = query.toString();
  return queryString ? `${path}?${queryString}` : path;
};

export default function Dashboard() {
  const { role, employee, isAdmin, canAccess } = useRole();
  const { statuses: statusLabels } = useBusinessDicts();
  const navigate = useNavigate();
  const [data, setData] = useState<any>({});
  const [reminders, setReminders] = useState<Reminder[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [hasLoaded, setHasLoaded] = useState(false);
  const [salesPeriod, setSalesPeriod] = useState<1 | 7 | 30>(7);
  const [showMoreOwnerDetails, setShowMoreOwnerDetails] = useState(false);
  const [salesManagement, setSalesManagement] = useState<SalesManagementDashboard | null>(null);
  const [salesPerformance, setSalesPerformance] = useState<SalesPerformanceDashboard | null>(null);
  const [salesRecovery, setSalesRecovery] = useState<SalesRecoveryOverview | null>(null);
  const [salesCockpitLoading, setSalesCockpitLoading] = useState(false);
  const [payrollSummary, setPayrollSummary] = useState<PayrollSummary | null>(null);
  const [ownerCockpit, setOwnerCockpit] = useState<OwnerCockpit | null>(null);
  const [ownerCockpitLoading, setOwnerCockpitLoading] = useState(false);
  const [ownerCockpitAttempted, setOwnerCockpitAttempted] = useState(false);
  const now = new Date();
  const [lbYear, setLbYear] = useState<string>(String(now.getFullYear()));
  const [lbMonth, setLbMonth] = useState<string>(String(now.getMonth() + 1));

  const effectiveRole = role || 'super_admin';
  const isSales = effectiveRole === 'sales';
  const isOps = effectiveRole === 'ops';
  const isDesign = effectiveRole === 'design';
  const isFinance = effectiveRole === 'finance';
  const isAdm = isAdmin;

  useEffect(() => { loadDashboard(); }, []);

  const loadDashboard = async () => {
    try {
      const queries: Promise<any>[] = [];
      // Keep the response slot stable without requesting task data for roles
      // that cannot open the task module (for example Finance).
      queries.push(canAccess('/tasks')
        ? client.entities.tasks.query({ limit: 200 })
        : Promise.resolve({ data: { items: [] } }));

      if (isAdm || isSales || isOps || isFinance) {
        queries.push(client.entities.customers.query({ limit: 200 }));
      } else {
        queries.push(Promise.resolve({ data: { items: [] } }));
      }

      if (isAdm || isSales) {
        queries.push(client.entities.deals.query({ limit: 200 }));
        queries.push(client.entities.follow_ups.query({ limit: 200, sort: '-created_at' }));
      } else {
        queries.push(Promise.resolve({ data: { items: [] } }));
        queries.push(Promise.resolve({ data: { items: [] } }));
      }

      if (isAdm || isFinance) {
        queries.push(client.entities.subscriptions.query({ limit: 200 }));
        queries.push(client.entities.payments.queryAll({ limit: 200 }));
        queries.push(client.entities.expenses.queryAll({ limit: 200 }));           // 客户支出 (USD)
        queries.push(client.entities.company_expenses.queryAll({ limit: 200 }));   // 公司支出 (CNY)
      } else {
        queries.push(Promise.resolve({ data: { items: [] } }));
        queries.push(Promise.resolve({ data: { items: [] } }));
        queries.push(Promise.resolve({ data: { items: [] } }));
        queries.push(Promise.resolve({ data: { items: [] } }));
      }

      if (isAdm) {
        queries.push(client.entities.employees.queryAll({ limit: 200 }));
      } else {
        queries.push(Promise.resolve({ data: { items: [] } }));
      }

      // Load callbacks for admin and sales
      if (isAdm || isSales) {
        queries.push(client.apiCall.invoke({
          url: '/api/v1/entities/customer_callbacks',
          method: 'GET',
          data: { limit: 200, sort: '-callback_date' },
        }));
      } else {
        queries.push(Promise.resolve({ data: { items: [] } }));
      }

      const [tasksRes, customersRes, dealsRes, followUpsRes, subsRes, paymentsRes, expensesRes, companyExpensesRes, employeesRes, callbacksRes] = await Promise.all(queries);

      let tasks = tasksRes?.data?.items || [];
      let customers = customersRes?.data?.items || [];
      let deals = dealsRes?.data?.items || [];
      const followUps = followUpsRes?.data?.items || [];
      const subs = decorateEffectiveSubscriptions(subsRes?.data?.items || []);
      const payments = paymentsRes?.data?.items || [];
      const expenses = expensesRes?.data?.items || [];
      const companyExpenses = companyExpensesRes?.data?.items || [];
      const allEmployees = employeesRes?.data?.items || [];
      let callbacksList = callbacksRes?.data?.items || [];

      // Filter callbacks by employee for self-scoped roles
      if ((isSales) && employee) {
        callbacksList = callbacksList.filter((cb: any) => cb.employee_name === employee.name);
      }

      // Filter by employee for self-scoped roles
      if ((isSales || isOps || isDesign) && employee) {
        tasks = tasks.filter((t: any) => t.assignee_name === employee.name);
        if (isSales) {
          customers = customers.filter((c: any) => c.sales_person === employee.name || c.sales_employee_id === employee.id);
          deals = deals.filter((d: any) => d.sales_name === employee.name);
        }
        if (isOps) {
          customers = customers.filter((c: any) => c.ops_person === employee.name || c.sales_person === employee.name);
        }
      }

      const now = new Date();
      const monthStart = new Date(now.getFullYear(), now.getMonth(), 1);
      const sevenDaysAgo = new Date(now.getTime() - 7 * 86400000);
      const currentMonthKey = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;

      const totalCustomers = customers.length;
      const followingCustomers = customers.filter((c: any) => c.status === 'following').length;
      const closedThisMonth = deals.filter((d: any) => new Date(d.deal_date) >= monthStart).length;
      const lostCustomers = customers.filter((c: any) => c.status === 'lost').length;
      const newThisMonth = customers.filter((c: any) => new Date(c.created_at) >= monthStart).length;

      const expiringSoon = subs.filter((s: any) => s.status === 'expiring_soon').length;

      const monthlyPayments = payments.filter((p: any) => new Date(p.payment_date) >= monthStart);
      const monthlyRevenue = monthlyPayments.reduce((sum: number, p: any) => sum + (p.amount_paid || 0), 0);
      const overduePayments = payments.filter((p: any) => (p.outstanding_amount || 0) > 0).length;
      const totalOutstanding = payments.filter((p: any) => (p.outstanding_amount || 0) > 0).reduce((s: number, p: any) => s + (p.outstanding_amount || 0), 0);

      const pendingTasks = tasks.filter((t: any) => t.status === 'pending' || t.status === 'in_progress').length;
      const completedTasks = tasks.filter((t: any) => t.status === 'completed').length;
      const delayedTasks = tasks.filter((t: any) => t.status === 'delayed').length;

      const monthlyDealAmount = deals.filter((d: any) => new Date(d.deal_date) >= monthStart).reduce((s: number, d: any) => s + (d.deal_amount || 0), 0);

      // Expired not renewed
      const expiredNotRenewed = subs.filter((s: any) => s.status === 'expired').length;

      const monthlyCustomerExpenseUSD = (expenses || []).filter((e: any) => e.expense_month === currentMonthKey).reduce((s: number, e: any) => s + (e.amount || 0), 0);
      const monthlyCompanyExpenseCNY = (companyExpenses || []).filter((e: any) => e.expense_month === currentMonthKey).reduce((s: number, e: any) => s + (e.amount || 0), 0);

      setData({
        totalCustomers, followingCustomers, closedThisMonth, lostCustomers, newThisMonth,
        expiringSoon, monthlyRevenue, overduePayments, totalOutstanding,
        pendingTasks, completedTasks, delayedTasks, monthlyDealAmount,
        expiredNotRenewed,
        customers, deals, tasks, followUps, subs, payments, allEmployees, callbacksList,
        monthlyCustomerExpenseUSD,
        monthlyCompanyExpenseCNY,
      });
      setLoadError(null);
      setHasLoaded(true);

      // Build reminders
      buildReminders(customers, followUps, subs, payments, tasks, now, sevenDaysAgo, callbacksList);
    } catch (err) {
      console.error('Failed to load dashboard:', err);
      setLoadError(getLoadErrorMessage(err));
    } finally {
      setLoading(false);
    }
  };

  const loadSalesCockpit = async (period: 1 | 7 | 30 = salesPeriod) => {
    if (!isAdm) return;
    setSalesCockpitLoading(true);
    try {
      const [managementRes, performanceRes, recoveryRes] = await Promise.all([
        invokeWithAuth({ url: '/api/v1/sales-leads/dashboard/management', method: 'GET' }),
        invokeWithAuth({ url: `/api/v1/sales-leads/dashboard/performance?days=${period}`, method: 'GET' }),
        invokeWithAuth({ url: '/api/v1/sales-leads/recovery/overview', method: 'GET' }),
      ]);
      setSalesManagement(managementRes.data || null);
      setSalesPerformance(performanceRes.data || null);
      setSalesRecovery(recoveryRes.data || null);
    } catch (error) {
      console.error('Failed to load sales owner cockpit:', error);
    } finally {
      setSalesCockpitLoading(false);
    }
  };

  const loadOwnerCockpit = async () => {
    if (!isAdm) return;
    setOwnerCockpitLoading(true);
    try {
      const response = await invokeWithAuth({ url: '/api/v1/management-decisions/owner-cockpit', method: 'GET' });
      setOwnerCockpit(response.data || null);
    } catch (error) {
      console.error('Failed to load owner cockpit:', error);
      setOwnerCockpit(null);
    } finally {
      setOwnerCockpitLoading(false);
      setOwnerCockpitAttempted(true);
    }
  };

  useEffect(() => {
    if (isAdm && showMoreOwnerDetails) void loadSalesCockpit(salesPeriod);
  }, [isAdm, salesPeriod, showMoreOwnerDetails]);

  useEffect(() => {
    if (isAdm) void loadOwnerCockpit();
  }, [isAdm]);

  useEffect(() => {
    if (!isAdm && !isFinance) return;
    if (isAdm && !showMoreOwnerDetails) return;
    void invokeWithAuth({ url: '/api/v1/payroll/summary', method: 'GET' })
      .then(response => setPayrollSummary(response.data || null))
      .catch(() => setPayrollSummary(null));
  }, [isAdm, isFinance, showMoreOwnerDetails]);

  useAutoRefresh(() => {
    void loadDashboard();
    if (isAdm) void loadOwnerCockpit();
  }, { intervalMs: 30000 });

  const buildReminders = (customers: any[], followUps: any[], subs: any[], payments: any[], tasks: any[], now: Date, sevenDaysAgo: Date, callbacksList?: any[]) => {
    const newReminders: Reminder[] = [];
    const customerMap = Object.fromEntries(customers.map((c: any) => [c.id, c]));
    const todayStr = now.toISOString().slice(0, 10);
    const latestFollowUps = Object.values(
      followUps.reduce<Record<string, any>>((acc, followUp) => {
        const customerId = String(followUp.customer_id || '');
        if (!customerId) return acc;
        const currentBest = acc[customerId];
        if (!currentBest || (followUp.created_at || '') > (currentBest.created_at || '')) {
          acc[customerId] = followUp;
        }
        return acc;
      }, {}),
    );

    // Today's follow-ups
    if (isAdm || isSales) {
      const todayFollowUps = latestFollowUps.filter((f: any) =>
        f.next_follow_date?.slice(0, 10) === todayStr && f.stage !== 'closed' && f.stage !== 'lost'
      );
      todayFollowUps.slice(0, 5).forEach((f: any) => {
        const cust = customerMap[f.customer_id];
        newReminders.push({
          id: `fu-today-${f.id}`, type: 'follow_up', urgency: 'high',
          title: `今日待跟进: ${cust?.business_name || '未知客户'}`,
          description: f.content?.slice(0, 50) || '请及时跟进',
          date: todayStr,
          link: buildReminderLink('/customers', {
            status: 'following',
            detail: f.customer_id,
            tab: 'followups',
            reminder: 'follow_up_today',
          }),
        });
      });

      // Overdue follow-ups
      const overdueFollowUps = latestFollowUps.filter((f: any) =>
        f.next_follow_date && new Date(f.next_follow_date) < now && f.next_follow_date?.slice(0, 10) !== todayStr && f.stage !== 'closed' && f.stage !== 'lost'
      );
      overdueFollowUps.slice(0, 5).forEach((f: any) => {
        const cust = customerMap[f.customer_id];
        newReminders.push({
          id: `fu-${f.id}`, type: 'follow_up', urgency: 'high',
          title: `逾期跟进: ${cust?.business_name || '未知客户'}`,
          description: `计划跟进日期 ${f.next_follow_date?.slice(0, 10)} 已过期`,
          date: f.next_follow_date?.slice(0, 10),
          link: buildReminderLink('/customers', {
            status: 'following',
            detail: f.customer_id,
            tab: 'followups',
            reminder: 'follow_up_overdue',
          }),
        });
      });

      // 7-day no follow-up
      const customerLastFollowUp: Record<number, string> = {};
      latestFollowUps.forEach((f: any) => {
        if (!customerLastFollowUp[f.customer_id] || f.created_at > customerLastFollowUp[f.customer_id]) {
          customerLastFollowUp[f.customer_id] = f.created_at;
        }
      });
      const noFollowUp7d = customers.filter((c: any) => {
        if (c.status === 'closed' || c.status === 'lost' || c.status === 'paused') return false;
        const lastFu = customerLastFollowUp[c.id];
        if (!lastFu) return true;
        return new Date(lastFu) < sevenDaysAgo;
      });
      noFollowUp7d.slice(0, 5).forEach((c: any) => {
        const lastDate = customerLastFollowUp[c.id]?.slice(0, 10) || '从未跟进';
        newReminders.push({
          id: `nofu-${c.id}`, type: 'no_follow_7d', urgency: 'medium',
          title: `7天未跟进: ${c.business_name}`,
          description: `上次跟进: ${lastDate}`,
          link: buildReminderLink('/customers', {
            status: 'following',
            detail: c.id,
            tab: 'followups',
            reminder: 'no_follow_7d',
          }),
        });
      });
    }

    // Expiring subscriptions
    if (isAdm || isFinance) {
      const expiringSubs = [...subs]
        .filter((s: any) => s.status === 'expiring_soon')
        .sort((a: any, b: any) => new Date(a.end_date || 0).getTime() - new Date(b.end_date || 0).getTime());
      expiringSubs.slice(0, 5).forEach((s: any) => {
        const cust = customerMap[s.customer_id];
        newReminders.push({
          id: `sub-${s.id}`, type: 'renewal', urgency: 'high',
          title: `即将到期: ${cust?.business_name || '未知客户'}`,
          description: `${s.package_name} 将于 ${s.end_date?.slice(0, 10)} 到期`,
          date: s.end_date?.slice(0, 10),
          link: buildReminderLink('/customers', {
            detail: s.customer_id,
            tab: 'renewals',
            reminder: 'renewal_due',
          }),
        });
      });

      // Overdue payments
      const overduePaymentsList = payments.filter((p: any) => (p.outstanding_amount || 0) > 0);
      overduePaymentsList.slice(0, 5).forEach((p: any) => {
        const cust = customerMap[p.customer_id];
        newReminders.push({
          id: `pay-${p.id}`, type: 'overdue_payment', urgency: 'high',
          title: `欠费: ${cust?.business_name || '未知客户'}`,
          description: `${p.product_name} 欠款 $${p.outstanding_amount}`,
          link: buildReminderLink('/customers', {
            detail: p.customer_id,
            tab: 'payments',
            reminder: 'overdue_payment',
          }),
        });
      });
    }

    // Callback reminders
    if ((isAdm || isSales) && callbacksList && callbacksList.length > 0) {
      const todayStr2 = now.toISOString().slice(0, 10);
      const todayCallbacks = callbacksList.filter((cb: any) =>
        cb.status === 'pending' && cb.callback_date?.slice(0, 10) === todayStr2
      );
      todayCallbacks.slice(0, 3).forEach((cb: any) => {
        const cust = customerMap[cb.customer_id];
        newReminders.push({
          id: `cb-today-${cb.id}`, type: 'callback', urgency: 'high',
          title: `今日回访: ${cust?.business_name || '未知客户'}`,
          description: cb.content?.slice(0, 50) || '请及时回访',
          date: todayStr2,
          link: buildReminderLink('/callbacks', {
            customer_id: cb.customer_id,
            status: 'pending',
            schedule: 'today',
            reminder: 'callback_today',
          }),
        });
      });

      const overdueCallbacks = callbacksList.filter((cb: any) =>
        cb.status === 'pending' && cb.callback_date && cb.callback_date.slice(0, 10) < todayStr2
      );
      overdueCallbacks.slice(0, 3).forEach((cb: any) => {
        const cust = customerMap[cb.customer_id];
        newReminders.push({
          id: `cb-overdue-${cb.id}`, type: 'callback', urgency: 'high',
          title: `逾期回访: ${cust?.business_name || '未知客户'}`,
          description: `计划回访日期 ${cb.callback_date?.slice(0, 10)} 已过期`,
          date: cb.callback_date?.slice(0, 10),
          link: buildReminderLink('/callbacks', {
            customer_id: cb.customer_id,
            status: 'pending',
            schedule: 'overdue',
            reminder: 'callback_overdue',
          }),
        });
      });
    }

    // Delayed tasks
    const delayedTasks = tasks.filter((t: any) => t.status === 'delayed');
    delayedTasks.slice(0, 3).forEach((t: any) => {
      newReminders.push({
        id: `task-${t.id}`, type: 'pending_task', urgency: 'high',
        title: `延期任务: ${t.title}`,
        description: `负责人: ${t.assignee_name || '-'}`,
        date: t.due_date?.slice(0, 10),
        link: buildReminderLink('/tasks', {
          task_id: t.id,
          status: 'delayed',
          search: t.title || '',
          reminder: 'delayed_task',
        }),
      });
    });

    const urgencyOrder = { high: 0, medium: 1, low: 2 };
    newReminders.sort((a, b) => urgencyOrder[a.urgency] - urgencyOrder[b.urgency]);
    setReminders(newReminders);
  };

  const statusColors: Record<string, string> = {
    new: 'bg-blue-100 text-blue-700', following: 'bg-amber-100 text-amber-700',
    closed: 'bg-green-100 text-green-700', paused: 'bg-slate-100 text-slate-600', lost: 'bg-red-100 text-red-700',
  };
  const urgencyColors: Record<string, string> = {
    high: 'border-l-red-500 bg-red-50', medium: 'border-l-amber-500 bg-amber-50', low: 'border-l-blue-500 bg-blue-50',
  };
  const urgencyTextColors: Record<string, string> = {
    high: 'text-red-700', medium: 'text-amber-700', low: 'text-blue-700',
  };
  const reminderIcons: Record<string, any> = {
    follow_up: CalendarClock, renewal: Clock, overdue_payment: CreditCard, pending_task: PackageCheck, no_follow_7d: AlertTriangle, callback: PhoneCall,
  };
  const taskStatusLabels: Record<string, string> = { pending: '待处理', in_progress: '进行中', completed: '已完成', delayed: '延期' };
  const priorityLabels: Record<string, string> = { high: '高', medium: '中', low: '低' };
  const priorityColors: Record<string, string> = {
    high: 'bg-red-100 text-red-700', medium: 'bg-amber-100 text-amber-700', low: 'bg-slate-100 text-slate-600',
  };

  // Sales leaderboard - must be before any early returns
  const lbYearOptions = useMemo(() => {
    const deals = data.deals || [];
    const years = new Set<number>();
    deals.forEach((d: any) => { if (d.deal_date) years.add(new Date(d.deal_date).getFullYear()); });
    const currentYear = new Date().getFullYear();
    years.add(currentYear);
    return Array.from(years).sort((a, b) => b - a);
  }, [data.deals]);

  const salesLeaderboard = useMemo(() => {
    const deals = data.deals || [];
    const filtered = deals.filter((d: any) => {
      if (!d.deal_date) return false;
      if (lbYear === 'all') return true;
      const dt = new Date(d.deal_date);
      if (dt.getFullYear() !== Number(lbYear)) return false;
      if (lbMonth === 'all') return true;
      return (dt.getMonth() + 1) === Number(lbMonth);
    });
    const salesMap: Record<string, { name: string; count: number; amount: number }> = {};
    filtered.forEach((d: any) => {
      const name = d.sales_name || '未知';
      if (!salesMap[name]) salesMap[name] = { name, count: 0, amount: 0 };
      salesMap[name].count++;
      salesMap[name].amount += d.deal_amount || 0;
    });
    return Object.values(salesMap).sort((a, b) => b.amount - a.amount).slice(0, 5);
  }, [data.deals, lbYear, lbMonth]);

  if (isAdm && !ownerCockpitAttempted) {
    return <PageLoadState loading message="正在生成老板经营摘要…" />;
  }
  if (!isAdm && loading) {
    return <PageLoadState loading message="正在汇总客户、任务与财务数据…" />;
  }
  if (loadError && !hasLoaded && !ownerCockpit) {
    return <PageLoadState error={loadError} onRetry={() => { setLoading(true); void loadDashboard(); }} />;
  }

  // ==================== ROLE-SPECIFIC DASHBOARDS ====================

  const renderStatCard = (label: string, value: string | number, icon: any, color: string, bgColor: string, link: string) => (
    <Card key={label} className="border-slate-200 cursor-pointer hover:shadow-md hover:border-blue-200 transition-all" onClick={() => navigate(link)}>
      <CardContent className="p-4">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-xs text-slate-500 mb-1">{label}</p>
            <p className="text-2xl font-bold text-slate-800">{value}</p>
          </div>
          <div className={`w-10 h-10 rounded-lg ${bgColor} flex items-center justify-center`}>
            {icon}
          </div>
        </div>
      </CardContent>
    </Card>
  );

  const renderReminders = () => {
    if (reminders.length === 0) return null;
    return (
      <Card className="border-slate-200">
        <CardHeader className="pb-3">
          <CardTitle className="text-base font-semibold flex items-center gap-2">
            <Bell className="w-4 h-4 text-red-500" /> 智能提醒 ({reminders.length})
          </CardTitle>
          <p className="text-xs text-slate-500">
            自动汇总跟进、回访、欠费、续费和延期任务。点击后会直接进入对应客户或待处理页面。
          </p>
        </CardHeader>
        <CardContent className="pt-0">
          <div className="space-y-2 max-h-64 overflow-y-auto">
            {reminders.slice(0, 10).map((r) => {
              const Icon = reminderIcons[r.type] || Bell;
              return (
                <div key={r.id} className={`flex items-start gap-3 p-2.5 rounded-lg border-l-4 cursor-pointer hover:opacity-80 transition-opacity ${urgencyColors[r.urgency]}`}
                  onClick={() => r.link && navigate(r.link)}>
                  <Icon className={`w-4 h-4 mt-0.5 flex-shrink-0 ${urgencyTextColors[r.urgency]}`} />
                  <div className="flex-1 min-w-0">
                    <p className={`text-sm font-medium ${urgencyTextColors[r.urgency]}`}>{r.title}</p>
                    <p className="text-xs text-slate-500">{r.description}</p>
                  </div>
                  <span className="text-xs text-blue-600 font-medium flex-shrink-0 self-center">去处理</span>
                  {r.date && <span className="text-xs text-slate-400 flex-shrink-0">{r.date}</span>}
                </div>
              );
            })}
          </div>
        </CardContent>
      </Card>
    );
  };

  const renderOwnerCommandCenter = () => {
    if (!isAdm) return null;
    if (!ownerCockpit && ownerCockpitLoading) {
      return <Card className="border-slate-200"><CardContent className="flex h-52 items-center justify-center text-sm text-slate-500"><RefreshCw className="mr-2 h-4 w-4 animate-spin" />正在生成老板经营摘要...</CardContent></Card>;
    }
    if (!ownerCockpit) {
      return <Card className="border-amber-200 bg-amber-50"><CardContent className="flex items-center justify-between gap-4 p-4"><div><p className="font-semibold text-amber-900">老板经营摘要暂时无法读取</p><p className="mt-1 text-xs text-amber-700">客户与任务基础数据仍可继续使用，请稍后刷新。</p></div><Button variant="outline" size="sm" onClick={() => void loadOwnerCockpit()}>重新读取</Button></CardContent></Card>;
    }

    const usd = ownerCockpit.finance.USD;
    const lastRunAt = ownerCockpit.automation.last_run?.completed_at
      ? new Date(ownerCockpit.automation.last_run.completed_at).toLocaleString('zh-CN', { hour12: false })
      : '尚未完成扫描';
    const nextRunAt = ownerCockpit.automation.schedule?.next_run_at
      ? new Date(ownerCockpit.automation.schedule.next_run_at).toLocaleString('zh-CN', { hour12: false })
      : '-';
    const decisionTone: Record<string, string> = {
      critical: 'border-rose-200 bg-rose-50 text-rose-800',
      high: 'border-amber-200 bg-amber-50 text-amber-800',
      medium: 'border-blue-200 bg-blue-50 text-blue-800',
    };
    const decisionLabel: Record<string, string> = { critical: '立即处理', high: '优先处理', medium: '尽快完善' };
    const topMetrics = [
      { label: `${ownerCockpit.period.month} 经营利润 USD`, value: `$${usd.profit.toLocaleString()}`, helper: `服务收入 $${usd.service_revenue.toLocaleString()} · 渠道佣金 $${Number(usd.channel_commission || 0).toLocaleString()}`, icon: CircleDollarSign, tone: usd.profit < 0 ? 'text-rose-700 bg-rose-50' : 'text-emerald-700 bg-emerald-50', link: '/finance?tab=monthly_detail' },
      { label: '本月净收款 USD', value: `$${usd.net_receipts.toLocaleString()}`, helper: `客户投流资金 $${usd.ads_client_funds.toLocaleString()}（不计收入）`, icon: Banknote, tone: 'text-blue-700 bg-blue-50', link: '/finance?tab=income' },
      { label: '当前合作项目', value: ownerCockpit.customers.active_projects, helper: `${ownerCockpit.customers.at_risk_projects} 个风险 · 本月停止 ${ownerCockpit.customers.stopped_this_month}`, icon: Layers3, tone: 'text-violet-700 bg-violet-50', link: '/customer-lifecycle' },
      { label: '系统推动中的任务', value: ownerCockpit.execution.system_tasks, helper: `全部任务中 ${ownerCockpit.execution.overdue_tasks} 个已逾期`, icon: Workflow, tone: 'text-orange-700 bg-orange-50', link: '/tasks?source=system' },
    ];
    const ownerShortcuts = [
      { label: '公司战略', helper: '现金安全、阶段目标与下一步', path: '/company-roadmap' },
      { label: '客户中心', helper: '客户、成交与生命周期', path: '/customers' },
      { label: '财务与结算', helper: '收款、成本、续费与分润', path: '/finance' },
      { label: '销售中心', helper: '拨打、商机与销售执行', path: '/sales-workbench' },
    ];

    return (
      <section className="space-y-4">
        <Card className="stitch-command-deck">
          <CardContent className="p-0">
            <div className="stitch-command-status">
              <div className="flex min-w-0 items-center gap-2"><Gauge className="h-4 w-4 text-blue-300" /><span>T24 Owner Command Center</span><span className="hidden text-slate-500 sm:inline">/ 今日经营快照</span></div>
              <div className="flex items-center gap-2 text-[11px] text-slate-300"><span className={`h-2 w-2 rounded-full ${ownerCockpit.decision_state === 'healthy' ? 'bg-emerald-400' : 'bg-amber-400'}`} />数据截至 {new Date(ownerCockpit.as_of).toLocaleString('zh-CN', { hour12: false })}</div>
            </div>
            <div className="grid xl:grid-cols-[1.42fr_0.82fr]">
              <div className="p-5 md:p-7">
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-blue-600">经营总览</p>
                <h2 className="mt-2 text-lg font-semibold tracking-[-0.02em] text-slate-800">今天先看结果，再看风险，最后确认谁来处理</h2>
                <div className="mt-3 flex flex-col justify-between gap-5 lg:flex-row lg:items-end">
                  <div><p className="text-sm text-slate-500">{ownerCockpit.period.month} 经营利润 USD</p><button type="button" onClick={() => navigate('/finance?tab=monthly_detail')} className="mt-1 text-left text-5xl font-bold tracking-[-0.06em] text-slate-950 transition hover:text-blue-700 md:text-6xl">{topMetrics[0].value}</button><p className="mt-3 max-w-lg text-sm leading-6 text-slate-500">{ownerCockpit.finance.currency_policy}</p></div>
                  <div className={`rounded-2xl border px-4 py-3 ${ownerCockpit.decision_state === 'healthy' ? 'border-emerald-200 bg-emerald-50 text-emerald-800' : 'border-amber-200 bg-amber-50 text-amber-900'}`}>
                    <div className="flex items-center gap-2">{ownerCockpit.decision_state === 'healthy' ? <CheckCircle2 className="h-4 w-4 text-emerald-600" /> : <ShieldAlert className="h-4 w-4 text-amber-600" />}<span className="text-sm font-semibold">{ownerCockpit.decision_state === 'healthy' ? '经营闭环正常' : `${ownerCockpit.decisions.length} 类事项待处理`}</span></div><p className="mt-1 text-[11px] opacity-70">每项均可追溯到业务页面</p>
                  </div>
                </div>
                <div className="mt-7 grid gap-px overflow-hidden rounded-2xl border border-slate-200 bg-slate-200 sm:grid-cols-3">
                  {topMetrics.slice(1).map(item => {
                    const Icon = item.icon;
                    return <button key={item.label} type="button" onClick={() => navigate(item.link)} className="bg-white p-4 text-left transition hover:bg-blue-50"><div className={`flex h-8 w-8 items-center justify-center rounded-lg ${item.tone}`}><Icon className="h-4 w-4" /></div><p className="mt-4 text-xs text-slate-500">{item.label}</p><p className="mt-1 text-2xl font-bold tracking-[-0.03em] text-slate-950">{item.value}</p><p className="mt-1 text-[11px] leading-5 text-slate-500">{item.helper}</p></button>;
                  })}
                </div>
              </div>
              <aside className="stitch-decision-rail">
                <div className="flex items-center justify-between"><div><p className="text-xs font-semibold uppercase tracking-[0.16em] text-blue-200">Decision queue</p><h3 className="mt-1 text-lg font-semibold text-white">今天必须拍板</h3></div><Button size="sm" variant="outline" className="border-white/15 bg-white/10 text-white hover:bg-white/20 hover:text-white" onClick={() => navigate('/tasks?source=system')}>全部任务</Button></div>
                <div className="mt-5 space-y-2">{ownerCockpit.decisions.slice(0, 4).map(item => <button key={item.key} type="button" onClick={() => navigate(item.link)} className="stitch-decision-row"><span className={`mt-1 h-2 w-2 shrink-0 rounded-full ${item.level === 'critical' ? 'bg-rose-400' : item.level === 'high' ? 'bg-amber-300' : 'bg-blue-300'}`} /><span className="min-w-0 flex-1"><span className="block text-[10px] font-semibold tracking-wide text-slate-400">{decisionLabel[item.level]}</span><span className="mt-1 block text-sm font-semibold text-white">{item.title}</span><span className="mt-1 block truncate text-[11px] text-slate-400">{item.description}</span></span><span className="rounded-full bg-white/10 px-2 py-1 text-sm font-bold text-white">{item.count}</span></button>)}{ownerCockpit.decisions.length === 0 && <div className="rounded-xl border border-emerald-400/25 bg-emerald-400/10 p-4 text-sm text-emerald-100">当前没有需要老板拍板的异常事项</div>}</div>
              </aside>
            </div>
            <div className="grid border-t border-slate-200/80 bg-slate-50/80 px-4 py-2 sm:grid-cols-2 xl:grid-cols-4">
              {ownerShortcuts.map(item => <button key={item.path} type="button" onClick={() => navigate(item.path)} className="group flex items-center justify-between rounded-lg px-3 py-2.5 text-left transition hover:bg-white"><span><span className="block text-sm font-semibold text-slate-700 group-hover:text-blue-700">{item.label}</span><span className="mt-0.5 block text-[11px] text-slate-500">{item.helper}</span></span><ArrowRight className="h-4 w-4 text-slate-400 group-hover:text-blue-600" /></button>)}
            </div>
          </CardContent>
        </Card>

        <div className="grid gap-4 xl:grid-cols-[1.3fr_0.7fr]">
          <Card className="stitch-section-card">
            <CardHeader className="pb-3"><div className="flex items-center justify-between"><div><CardTitle className="flex items-center gap-2 text-base"><Activity className="h-4 w-4 text-rose-500" />老板今天需要推动</CardTitle><p className="mt-1 text-xs text-slate-500">按影响程度排序，点击直接进入处理页面。</p></div><Button size="sm" variant="outline" onClick={() => navigate('/tasks?source=system')}>查看系统任务</Button></div></CardHeader>
            <CardContent>
              <div className="grid gap-2 md:grid-cols-2">
                {ownerCockpit.decisions.map(item => <button key={item.key} type="button" onClick={() => navigate(item.link)} className={`rounded-xl border p-3 text-left transition hover:shadow-sm ${decisionTone[item.level]}`}><div className="flex items-start justify-between gap-3"><div><span className="text-[10px] font-semibold uppercase tracking-wide opacity-70">{decisionLabel[item.level]}</span><p className="mt-1 text-sm font-semibold">{item.title}</p></div><span className="rounded-full bg-white px-2.5 py-1 text-sm font-bold shadow-sm">{item.count}</span></div><p className="mt-2 text-xs leading-5 opacity-80">{item.description}</p></button>)}
                {ownerCockpit.decisions.length === 0 && <div className="col-span-2 rounded-xl bg-emerald-50 p-8 text-center text-sm text-emerald-700"><CheckCircle2 className="mx-auto mb-2 h-7 w-7" />当前没有需要老板推动的异常事项</div>}
              </div>
            </CardContent>
          </Card>

          <Card className="stitch-section-card">
            <CardHeader className="pb-3"><CardTitle className="flex items-center gap-2 text-base"><Database className="h-4 w-4 text-blue-600" />自动化与数据可信度</CardTitle></CardHeader>
            <CardContent className="space-y-4">
              <div className="grid grid-cols-2 gap-2">
                <button type="button" onClick={() => navigate('/management-decisions?section=quality')} className="rounded-lg bg-rose-50 p-3 text-left"><p className="text-xs text-rose-600">开放问题</p><p className="mt-1 text-xl font-bold text-rose-800">{ownerCockpit.quality.open + ownerCockpit.quality.in_progress}</p></button>
                <button type="button" onClick={() => navigate('/tasks?source=system')} className="rounded-lg bg-blue-50 p-3 text-left"><p className="text-xs text-blue-600">关联任务</p><p className="mt-1 text-xl font-bold text-blue-800">{ownerCockpit.quality.open_task_count}</p></button>
                <button type="button" onClick={() => navigate('/service-board')} className="rounded-lg bg-amber-50 p-3 text-left"><p className="text-xs text-amber-600">交付逾期</p><p className="mt-1 text-xl font-bold text-amber-800">{ownerCockpit.delivery.overdue_service_tasks}</p></button>
                <button type="button" onClick={() => navigate('/callbacks?status=pending&schedule=overdue')} className="rounded-lg bg-violet-50 p-3 text-left"><p className="text-xs text-violet-600">逾期回访</p><p className="mt-1 text-xl font-bold text-violet-800">{ownerCockpit.delivery.overdue_callbacks}</p></button>
              </div>
              <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs text-slate-600"><div className="flex items-center justify-between"><span>每日扫描</span><Badge className={ownerCockpit.automation.schedule.enabled ? 'bg-emerald-100 text-emerald-700 hover:bg-emerald-100' : 'bg-slate-200 text-slate-600 hover:bg-slate-200'}>{ownerCockpit.automation.schedule.enabled ? '已开启' : '未开启'}</Badge></div><p className="mt-2">上次：{lastRunAt}</p><p className="mt-1">下次：{nextRunAt}</p><p className="mt-2 text-[11px] text-slate-400">只提醒、建任务和追踪结果，不会自动停止客户。</p></div>
            </CardContent>
          </Card>
        </div>

        <Card className="stitch-section-card">
          <CardHeader className="pb-3"><div className="flex items-center justify-between"><div><CardTitle className="text-base">业务结构与团队执行</CardTitle><p className="mt-1 text-xs text-slate-500">用于判断当前人力应该投向获客、交付还是客户留存。</p></div><Button size="sm" variant="outline" onClick={() => navigate('/management-decisions')}>查看经营决策</Button></div></CardHeader>
          <CardContent>
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
              <div className="rounded-xl border border-slate-200 p-4"><p className="text-xs text-slate-500">在合作项目构成</p><div className="mt-3 space-y-2">{ownerCockpit.customers.business_lines.map(line => <div key={line.code} className="flex items-center justify-between text-sm"><span className="text-slate-600">{line.name}</span><span className="font-bold text-slate-900">{line.active_projects}</span></div>)}{ownerCockpit.customers.business_lines.length === 0 && <p className="text-sm text-slate-400">尚无已确认项目</p>}</div></div>
              <div className="rounded-xl border border-slate-200 p-4"><p className="text-xs text-slate-500">任务执行</p><p className="mt-2 text-2xl font-bold text-slate-900">{ownerCockpit.execution.completed_this_month}</p><p className="mt-1 text-xs text-slate-500">本月已完成 · 当前待办 {ownerCockpit.execution.open_tasks}</p></div>
              <div className="rounded-xl border border-slate-200 p-4"><p className="text-xs text-slate-500">客户交付</p><p className="mt-2 text-2xl font-bold text-slate-900">{ownerCockpit.delivery.active_service_records}</p><p className="mt-1 text-xs text-slate-500">服务记录 · 未解决问题 {ownerCockpit.delivery.unresolved_service_issues}</p></div>
              <div className="rounded-xl border border-slate-200 p-4"><p className="text-xs text-slate-500">人民币公司支出</p><p className="mt-2 text-2xl font-bold text-slate-900">¥{ownerCockpit.finance.company_cost_cny.toLocaleString()}</p><p className="mt-1 text-xs text-slate-500">与美元利润分开，不做临时汇率换算</p></div>
            </div>
          </CardContent>
        </Card>
      </section>
    );
  };

  const renderSalesOwnerCockpit = () => {
    if (!isAdm) return null;
    if (!salesManagement && salesCockpitLoading) {
      return <Card className="border-slate-200"><CardContent className="flex h-40 items-center justify-center text-sm text-slate-500">正在汇总电话销售经营数据...</CardContent></Card>;
    }
    if (!salesManagement) return null;

    const people = salesPerformance?.items || [];
    const periodTotals = people.reduce((totals, item) => ({
      assigned: totals.assigned + item.metrics.assigned,
      completed: totals.completed + item.metrics.completed,
      calls: totals.calls + item.metrics.calls,
      connected: totals.connected + item.metrics.connected,
      interested: totals.interested + item.metrics.interested,
      appointments: totals.appointments + item.metrics.appointments,
      converted: totals.converted + item.metrics.conversions,
    }), { assigned: 0, completed: 0, calls: 0, connected: 0, interested: 0, appointments: 0, converted: 0 });
    const rawMetrics = periodTotals;
    const metrics = {
      ...rawMetrics,
      completion_rate: Math.round(periodTotals.completed / Math.max(periodTotals.assigned, 1) * 1000) / 10,
      connection_rate: Math.round(periodTotals.connected / Math.max(periodTotals.calls, 1) * 1000) / 10,
      interest_rate: Math.round(periodTotals.interested / Math.max(periodTotals.connected, 1) * 1000) / 10,
      appointment_rate: Math.round(periodTotals.appointments / Math.max(periodTotals.interested, 1) * 1000) / 10,
    };
    const attention = salesManagement.owner_attention || { high_intent_stale: 0, due_followups: 0, overdue_followups: 0, pending_quotes: 0, unpaid_handoffs: 0 };
    const pipeline = salesManagement.deal_pipeline || { pending_quotes: 0, approved_quotes: 0, approved_quote_amount: 0, confirmed_received_amount: 0, unpaid_handoffs: 0 };
    const lowExecution = people.filter(item => item.metrics.assigned > 0 && item.metrics.completion_rate < 80).length;
    const weakNotes = people.filter(item => item.metrics.calls >= 5 && item.metrics.note_quality_rate < 70).length;
    const funnel = [
      { label: '已分配', value: metrics.assigned, color: 'bg-slate-700' },
      { label: '已记录通话', value: metrics.calls, color: 'bg-blue-600' },
      { label: '已接通', value: metrics.connected, color: 'bg-cyan-500' },
      { label: '有意向', value: metrics.interested, color: 'bg-amber-500' },
      { label: '已预约', value: metrics.appointments, color: 'bg-violet-500' },
      { label: '转正式客户', value: metrics.converted, color: 'bg-emerald-600' },
    ];
    const funnelBase = Math.max(...funnel.map(item => item.value), 1);
    const salesMetricCards = [
      { label: '已分配任务', value: metrics.assigned, helper: `${metrics.completed} 条已完成`, icon: Target, tone: 'text-slate-700 bg-slate-100', link: '/sales-workbench' },
      { label: '任务记录完成率', value: `${metrics.completion_rate}%`, helper: `${metrics.calls} 条员工保存记录`, icon: PhoneCall, tone: 'text-blue-700 bg-blue-50', link: '/sales-workbench' },
      { label: '接通率', value: `${metrics.connection_rate}%`, helper: `${metrics.connected} 次有效接通`, icon: PhoneForwarded, tone: 'text-cyan-700 bg-cyan-50', link: '/sales-leads' },
      { label: '意向率', value: `${metrics.interest_rate}%`, helper: `${metrics.interested} 个有意向`, icon: TrendingUp, tone: 'text-amber-700 bg-amber-50', link: '/sales-leads' },
      { label: '预约率', value: `${metrics.appointment_rate}%`, helper: `${metrics.appointments} 个已预约`, icon: CalendarCheck2, tone: 'text-violet-700 bg-violet-50', link: '/sales-leads' },
      { label: '转正式客户', value: metrics.converted, helper: '仅统计确认转入', icon: Handshake, tone: 'text-emerald-700 bg-emerald-50', link: '/sales-leads' },
      { label: '待审批报价', value: pipeline.pending_quotes, helper: `${pipeline.approved_quotes} 份已批准`, icon: FileCheck2, tone: 'text-orange-700 bg-orange-50', link: '/sales-leads' },
      { label: '售前确认收款', value: `$${pipeline.confirmed_received_amount.toLocaleString()}`, helper: `已批报价 $${pipeline.approved_quote_amount.toLocaleString()}`, icon: Banknote, tone: 'text-emerald-700 bg-emerald-50', link: '/sales-leads' },
    ];
    const ownerTodos = [
      { label: '高意向超过24小时未推进', count: attention.high_intent_stale, tone: 'text-rose-700 bg-rose-50 border-rose-100' },
      { label: '已经逾期的回访', count: attention.overdue_followups, tone: 'text-rose-700 bg-rose-50 border-rose-100' },
      { label: '今天必须完成的回访', count: attention.due_followups, tone: 'text-amber-700 bg-amber-50 border-amber-100' },
      { label: '成交交接仍未收全款', count: attention.unpaid_handoffs, tone: 'text-orange-700 bg-orange-50 border-orange-100' },
      { label: '任务完成率低于80%的销售', count: lowExecution, tone: 'text-blue-700 bg-blue-50 border-blue-100' },
      { label: '通话备注质量需要改善', count: weakNotes, tone: 'text-violet-700 bg-violet-50 border-violet-100' },
      { label: '可回收或待跟进线索', count: (salesRecovery?.summary.recoverable || 0) + (salesRecovery?.summary.watch || 0), tone: 'text-slate-700 bg-slate-50 border-slate-200' },
    ].filter(item => item.count > 0);

    return (
      <section className="space-y-4">
        <Card className="overflow-hidden border-slate-200 bg-gradient-to-br from-slate-950 via-slate-900 to-blue-950 text-white shadow-lg">
          <CardContent className="p-5 md:p-6">
            <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
              <div>
                <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.18em] text-cyan-300"><TrendingUp className="h-4 w-4" />销售老板驾驶舱</div>
                <h3 className="mt-2 text-xl font-semibold">从员工记录、跟进纪律到正式成交，一眼看清销售推进效率</h3>
                <p className="mt-1 text-xs text-slate-300">拨号辅助不作为真实通话证明；销售数据与正式财务分开，绩效只作管理参考。</p>
              </div>
              <div className="flex rounded-lg bg-white/10 p-1">
                {([{ value: 1, label: '今日' }, { value: 7, label: '近7天' }, { value: 30, label: '近30天' }] as const).map(option => (
                  <button key={option.value} type="button" onClick={() => setSalesPeriod(option.value)} className={`rounded-md px-3 py-1.5 text-xs font-medium transition ${salesPeriod === option.value ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-300 hover:text-white'}`}>{option.label}</button>
                ))}
              </div>
            </div>
            <div className="mt-5 grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-8">
              {salesMetricCards.map(item => {
                const Icon = item.icon;
                return <button key={item.label} type="button" onClick={() => navigate(item.link)} className="rounded-xl border border-white/10 bg-white/[0.07] p-3 text-left transition hover:-translate-y-0.5 hover:bg-white/[0.12]"><div className={`mb-3 flex h-8 w-8 items-center justify-center rounded-lg ${item.tone}`}><Icon className="h-4 w-4" /></div><p className="text-xs text-slate-300">{item.label}</p><p className="mt-1 text-xl font-bold text-white">{item.value}</p><p className="mt-1 truncate text-[11px] text-slate-400">{item.helper}</p></button>;
              })}
            </div>
          </CardContent>
        </Card>

        <div className="grid gap-4 xl:grid-cols-[1.15fr_0.85fr]">
          <Card className="border-slate-200">
            <CardHeader className="pb-3"><CardTitle className="flex items-center justify-between text-base"><span>销售转化漏斗</span><Button size="sm" variant="outline" onClick={() => navigate('/sales-leads')}>进入电话销售中心 <ArrowRight className="ml-1 h-3.5 w-3.5" /></Button></CardTitle></CardHeader>
            <CardContent className="space-y-3">
              {funnel.map((item, index) => <div key={item.label} className="grid grid-cols-[76px_1fr_44px] items-center gap-3"><span className="text-xs font-medium text-slate-600">{item.label}</span><div className="h-7 overflow-hidden rounded-md bg-slate-100"><div className={`flex h-full min-w-[8px] items-center rounded-md px-2 text-[10px] text-white transition-all ${item.color}`} style={{ width: `${Math.max(item.value / funnelBase * 100, item.value ? 8 : 0)}%` }}>{index > 0 && funnel[index - 1].value > 0 ? `${Math.round(item.value / funnel[index - 1].value * 100)}%` : ''}</div></div><span className="text-right text-sm font-bold text-slate-800">{item.value}</span></div>)}
            </CardContent>
          </Card>

          <Card className="border-slate-200">
            <CardHeader className="pb-3"><CardTitle className="flex items-center gap-2 text-base"><ShieldAlert className="h-4 w-4 text-rose-500" />老板待处理事项</CardTitle></CardHeader>
            <CardContent>
              <div className="space-y-2">
                {ownerTodos.map(item => <button key={item.label} type="button" onClick={() => navigate('/sales-leads')} className={`flex w-full items-center justify-between rounded-lg border px-3 py-2.5 text-left text-sm transition hover:shadow-sm ${item.tone}`}><span>{item.label}</span><span className="rounded-full bg-white px-2 py-0.5 font-bold">{item.count}</span></button>)}
                {ownerTodos.length === 0 && <div className="rounded-lg bg-emerald-50 p-5 text-center text-sm text-emerald-700"><CheckCircle2 className="mx-auto mb-2 h-6 w-6" />当前没有销售异常待办</div>}
              </div>
            </CardContent>
          </Card>
        </div>

        <Card className="border-slate-200">
          <CardHeader className="pb-3"><div className="flex items-center justify-between"><div><CardTitle className="text-base">团队表现与系统建议</CardTitle><p className="mt-1 text-xs text-slate-500">{salesPeriod === 1 ? '按今天员工已保存的通话与跟进记录评分。' : `按最近${salesPeriod}天员工已保存的通话与跟进记录评分。`}</p></div><Button size="sm" variant="outline" onClick={() => navigate('/sales-leads')}>查看完整评分</Button></div></CardHeader>
          <CardContent className="overflow-x-auto">
            <table className="w-full min-w-[860px] text-left text-sm"><thead className="border-b text-xs text-slate-500"><tr><th className="pb-2">排名 / 销售</th><th className="pb-2">综合分</th><th className="pb-2">任务完成</th><th className="pb-2">接通率</th><th className="pb-2">意向率</th><th className="pb-2">预约 / 转客户</th><th className="pb-2">逾期回访</th><th className="pb-2">下一步建议</th></tr></thead><tbody className="divide-y divide-slate-100">{people.slice(0, 8).map(item => <tr key={item.sales_employee_id}><td className="py-3 font-semibold text-slate-900">#{item.rank} {item.salesperson}<p className="text-[11px] font-normal text-slate-400">{item.confidence}</p></td><td className="py-3 text-lg font-bold text-blue-700">{item.score}</td><td className="py-3">{item.metrics.completion_rate}%</td><td className="py-3">{item.metrics.connection_rate}%</td><td className="py-3">{item.metrics.interest_rate}%</td><td className="py-3">{item.metrics.appointments} / {item.metrics.conversions}</td><td className={`py-3 font-semibold ${item.metrics.overdue_followups ? 'text-rose-600' : 'text-emerald-600'}`}>{item.metrics.overdue_followups}</td><td className="max-w-xs py-3 text-xs text-slate-600">{item.suggestions[0]}</td></tr>)}{people.length === 0 && <tr><td colSpan={8} className="py-8 text-center text-slate-500">暂无足够的销售执行数据</td></tr>}</tbody></table>
          </CardContent>
        </Card>
      </section>
    );
  };

  // ---------- Sales Dashboard ----------
  if (isSales) {
    const recentCustomers = (data.customers || []).slice(0, 5);
    return (
      <div className="space-y-6">
        <h2 className="text-xl font-semibold text-slate-800">销售工作台</h2>
        {renderReminders()}
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
          {renderStatCard('我的客户', data.totalCustomers || 0, <Users className="w-5 h-5 text-blue-600" />, '', 'bg-blue-50', '/customers')}
          {renderStatCard('跟进中', data.followingCustomers || 0, <UserPlus className="w-5 h-5 text-amber-600" />, '', 'bg-amber-50', '/customers?status=following')}
          {renderStatCard('本月成交', data.closedThisMonth || 0, <Handshake className="w-5 h-5 text-green-600" />, '', 'bg-green-50', '/deals')}
          {renderStatCard('本月新增', data.newThisMonth || 0, <TrendingUp className="w-5 h-5 text-purple-600" />, '', 'bg-purple-50', '/customers')}
          {renderStatCard('待办任务', data.pendingTasks || 0, <ListTodo className="w-5 h-5 text-orange-600" />, '', 'bg-orange-50', '/tasks')}
          {renderStatCard('流失客户', data.lostCustomers || 0, <AlertTriangle className="w-5 h-5 text-red-600" />, '', 'bg-red-50', '/customers?status=lost')}
        </div>
        <Card className="border-slate-200">
          <CardHeader className="pb-3"><CardTitle className="text-base">我的最近客户</CardTitle></CardHeader>
          <CardContent>
            <div className="space-y-3">
              {recentCustomers.map((c: any) => (
                <div key={c.id} className="flex items-center justify-between py-2 border-b border-slate-100 last:border-0 cursor-pointer hover:bg-slate-50 rounded px-1" onClick={() => navigate('/customers')}>
                  <div><p className="text-sm font-medium text-slate-800">{c.business_name}</p><p className="text-xs text-slate-500">{c.contact_name} · {c.phone}</p></div>
                  <Badge variant="secondary" className={`text-xs ${statusColors[c.status] || ''}`}>{statusLabels[c.status] || c.status}</Badge>
                </div>
              ))}
              {recentCustomers.length === 0 && <p className="text-sm text-slate-400 text-center py-4">暂无客户数据</p>}
            </div>
          </CardContent>
        </Card>
      </div>
    );
  }

  // ---------- Ops Dashboard ----------
  if (isOps) {
    const myTasks = (data.tasks || []).filter((t: any) => t.status !== 'completed');
    return (
      <div className="space-y-6">
        <h2 className="text-xl font-semibold text-slate-800">运营工作台</h2>
        {renderReminders()}
        <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
          {renderStatCard('服务客户', data.totalCustomers || 0, <Users className="w-5 h-5 text-blue-600" />, '', 'bg-blue-50', '/customers')}
          {renderStatCard('待处理任务', data.pendingTasks || 0, <ListTodo className="w-5 h-5 text-orange-600" />, '', 'bg-orange-50', '/tasks')}
          {renderStatCard('延期任务', data.delayedTasks || 0, <Timer className="w-5 h-5 text-red-600" />, '', 'bg-red-50', '/tasks')}
          {renderStatCard('已完成任务', data.completedTasks || 0, <CheckCircle2 className="w-5 h-5 text-green-600" />, '', 'bg-green-50', '/tasks')}
        </div>
        <Card className="border-slate-200">
          <CardHeader className="pb-3"><CardTitle className="text-base">我的待办任务</CardTitle></CardHeader>
          <CardContent>
            <div className="space-y-3">
              {myTasks.slice(0, 8).map((t: any) => (
                <div key={t.id} className="flex items-center justify-between py-2 border-b border-slate-100 last:border-0 cursor-pointer hover:bg-slate-50 rounded px-1" onClick={() => navigate('/tasks')}>
                  <div><p className="text-sm font-medium text-slate-800">{t.title}</p><p className="text-xs text-slate-500">{t.due_date?.slice(0, 10) || '-'}</p></div>
                  <Badge variant="secondary" className="text-xs">{taskStatusLabels[t.status] || t.status}</Badge>
                </div>
              ))}
              {myTasks.length === 0 && <p className="text-sm text-slate-400 text-center py-4">暂无待办任务</p>}
            </div>
          </CardContent>
        </Card>
      </div>
    );
  }

  // ---------- Design Dashboard ----------
  if (isDesign) {
    const myTasks = data.tasks || [];
    const pending = myTasks.filter((t: any) => t.status === 'pending' || t.status === 'in_progress');
    const completed = myTasks.filter((t: any) => t.status === 'completed');
    const delayed = myTasks.filter((t: any) => t.status === 'delayed');
    return (
      <div className="space-y-6">
        <h2 className="text-xl font-semibold text-slate-800">设计工作台</h2>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {renderStatCard('我的任务', myTasks.length, <Palette className="w-5 h-5 text-purple-600" />, '', 'bg-purple-50', '/tasks')}
          {renderStatCard('待处理', pending.length, <ListTodo className="w-5 h-5 text-orange-600" />, '', 'bg-orange-50', '/tasks')}
          {renderStatCard('已完成', completed.length, <CheckCircle2 className="w-5 h-5 text-green-600" />, '', 'bg-green-50', '/tasks')}
          {renderStatCard('延期', delayed.length, <Timer className="w-5 h-5 text-red-600" />, '', 'bg-red-50', '/tasks')}
        </div>
        <Card className="border-slate-200">
          <CardHeader className="pb-3"><CardTitle className="text-base">待处理任务</CardTitle></CardHeader>
          <CardContent>
            <div className="space-y-3">
              {pending.slice(0, 8).map((t: any) => (
                <div key={t.id} className="flex items-center justify-between py-2 border-b border-slate-100 last:border-0 cursor-pointer hover:bg-slate-50 rounded px-1" onClick={() => navigate('/tasks')}>
                  <div><p className="text-sm font-medium text-slate-800">{t.title}</p><p className="text-xs text-slate-500">{t.due_date?.slice(0, 10) || '-'}</p></div>
                  <Badge variant="secondary" className={`text-xs ${priorityColors[t.priority] || ''}`}>{priorityLabels[t.priority] || t.priority}</Badge>
                </div>
              ))}
              {pending.length === 0 && <p className="text-sm text-slate-400 text-center py-4">暂无待处理任务</p>}
            </div>
          </CardContent>
        </Card>
      </div>
    );
  }

  // ---------- Finance Dashboard ----------
  if (isFinance) {
    return (
      <div className="space-y-6">
        <h2 className="text-xl font-semibold text-slate-800">财务工作台</h2>
        {renderReminders()}
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
          {renderStatCard('本月收款', `$${(data.monthlyRevenue || 0).toLocaleString()}`, <DollarSign className="w-5 h-5 text-emerald-600" />, '', 'bg-emerald-50', '/finance')}
          {renderStatCard('本月公司支出 (CNY)', `¥${(data.monthlyCompanyExpenseCNY || 0).toLocaleString()}`, <CreditCard className="w-5 h-5 text-red-600" />, '', 'bg-red-50', '/finance')}
          {renderStatCard('本月客户成本 (USD)', `$${(data.monthlyCustomerExpenseUSD || 0).toLocaleString()}`, <DollarSign className="w-5 h-5 text-amber-600" />, '', 'bg-amber-50', '/finance')}
          {renderStatCard('应收金额', `$${(data.totalOutstanding || 0).toLocaleString()}`, <CreditCard className="w-5 h-5 text-amber-600" />, '', 'bg-amber-50', '/finance')}
          {renderStatCard('欠费客户', data.overduePayments || 0, <AlertTriangle className="w-5 h-5 text-red-600" />, '', 'bg-red-50', '/finance')}
          {renderStatCard('即将到期', data.expiringSoon || 0, <Clock className="w-5 h-5 text-orange-600" />, '', 'bg-orange-50', '/finance')}
          {renderStatCard('已到期未续', data.expiredNotRenewed || 0, <Timer className="w-5 h-5 text-red-600" />, '', 'bg-red-50', '/finance')}
          {renderStatCard('本月工资表', payrollSummary?.items.find(item => item.month === new Date().toISOString().slice(0, 7))?.status === 'paid' ? '已发放' : payrollSummary?.items.find(item => item.month === new Date().toISOString().slice(0, 7))?.status === 'confirmed' ? '待发放' : '待确认', <ListTodo className="w-5 h-5 text-blue-600" />, '', 'bg-blue-50', '/payroll')}
        </div>
      </div>
    );
  }

  // ---------- Admin / Super Admin Dashboard ----------
  const recentCustomers = (data.customers || []).slice(0, 5);
  const upcomingTasks = (data.tasks || []).filter((t: any) => t.status !== 'completed').slice(0, 5);

  return (
    <div className="stitch-page space-y-6">
      <div className="stitch-page-header flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
        <div className="relative z-10">
          <p className="stitch-kicker">Executive CRM</p>
          <h1 className="stitch-title">老板今日工作台</h1>
          <p className="stitch-subtitle">集中查看经营结果、客户风险与团队执行，只把需要你判断和推动的事项放在前面。</p>
        </div>
        <div className="relative z-10 flex items-center gap-2 text-xs text-slate-500">
          <span className="h-2 w-2 rounded-full bg-emerald-500" />经营数据与业务任务分别按各自最近更新时间展示
        </div>
      </div>
      {renderOwnerCommandCenter()}
      {renderReminders()}
      <Collapsible open={showMoreOwnerDetails} onOpenChange={setShowMoreOwnerDetails} className="space-y-6">
        <Card className="border-dashed border-slate-300 bg-slate-50/70">
          <CardContent className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <p className="text-sm font-semibold text-slate-800">更多经营明细</p>
              <p className="mt-1 text-xs text-slate-500">销售漏斗、基础统计、排行榜和最近记录默认收起，需要复盘时再展开。</p>
            </div>
            <CollapsibleTrigger asChild>
              <Button variant="outline" className="shrink-0 bg-white">
                {showMoreOwnerDetails ? '收起明细' : '展开明细'}
                <ChevronDown className={`ml-2 h-4 w-4 transition-transform ${showMoreOwnerDetails ? 'rotate-180' : ''}`} />
              </Button>
            </CollapsibleTrigger>
          </CardContent>
        </Card>

        <CollapsibleContent className="space-y-6">
          {renderSalesOwnerCockpit()}

          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {renderStatCard('客户总数', data.totalCustomers || 0, <Users className="w-5 h-5 text-blue-600" />, '', 'bg-blue-50', '/customers')}
        {renderStatCard('本月新增', data.newThisMonth || 0, <UserPlus className="w-5 h-5 text-purple-600" />, '', 'bg-purple-50', '/customers')}
        {renderStatCard('本月成交额', `$${(data.monthlyDealAmount || 0).toLocaleString()}`, <Handshake className="w-5 h-5 text-green-600" />, '', 'bg-green-50', '/deals')}
        {renderStatCard('本月收款', `$${(data.monthlyRevenue || 0).toLocaleString()}`, <DollarSign className="w-5 h-5 text-emerald-600" />, '', 'bg-emerald-50', '/finance')}
        {renderStatCard('本月公司支出 (CNY)', `¥${(data.monthlyCompanyExpenseCNY || 0).toLocaleString()}`, <CreditCard className="w-5 h-5 text-red-600" />, '', 'bg-red-50', '/finance')}
        {renderStatCard('本月客户成本 (USD)', `$${(data.monthlyCustomerExpenseUSD || 0).toLocaleString()}`, <DollarSign className="w-5 h-5 text-amber-600" />, '', 'bg-amber-50', '/finance')}
        {renderStatCard('即将到期', data.expiringSoon || 0, <Clock className="w-5 h-5 text-orange-600" />, '', 'bg-orange-50', '/finance')}
        {renderStatCard('欠费客户', data.overduePayments || 0, <AlertTriangle className="w-5 h-5 text-red-600" />, '', 'bg-red-50', '/finance')}
        {renderStatCard('待办任务', data.pendingTasks || 0, <ListTodo className="w-5 h-5 text-purple-600" />, '', 'bg-purple-50', '/tasks')}
        {renderStatCard('本月工资表', payrollSummary?.items.find(item => item.month === new Date().toISOString().slice(0, 7))?.status === 'paid' ? '已发放' : payrollSummary?.items.find(item => item.month === new Date().toISOString().slice(0, 7))?.status === 'confirmed' ? '待发放' : '待确认', <ListTodo className="w-5 h-5 text-blue-600" />, '', 'bg-blue-50', '/payroll')}
        {renderStatCard('流失客户', data.lostCustomers || 0, <TrendingUp className="w-5 h-5 text-slate-600" />, '', 'bg-slate-100', '/customers?status=lost')}
          </div>

          <div className="grid md:grid-cols-3 gap-6">
        {/* Sales Leaderboard */}
        <Card className="border-slate-200">
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between gap-2 flex-wrap">
              <CardTitle className="text-base font-semibold">销售排行榜</CardTitle>
              <div className="flex items-center gap-1.5">
                <NativeSelect value={lbYear} onChange={setLbYear} className="w-[80px] h-7 text-xs" options={[{ value: 'all', label: '全部年' }, ...lbYearOptions.map(y => ({ value: String(y), label: `${y}年` }))]} />
                <NativeSelect value={lbMonth} onChange={setLbMonth} className="w-[72px] h-7 text-xs" options={[{ value: 'all', label: '全部月' }, ...Array.from({ length: 12 }, (_, i) => ({ value: String(i + 1), label: `${i + 1}月` }))]} />
              </div>
            </div>
          </CardHeader>
          <CardContent>
            <div className="space-y-3">
              {salesLeaderboard.map((s, i) => (
                <div key={s.name} className="flex items-center gap-3">
                  <span className={`w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold ${i === 0 ? 'bg-yellow-100 text-yellow-700' : i === 1 ? 'bg-slate-200 text-slate-600' : i === 2 ? 'bg-orange-100 text-orange-700' : 'bg-slate-100 text-slate-500'}`}>{i + 1}</span>
                  <div className="flex-1"><p className="text-sm font-medium">{s.name}</p><p className="text-xs text-slate-500">{s.count}单</p></div>
                  <span className="text-sm font-bold text-green-600">${s.amount.toLocaleString()}</span>
                </div>
              ))}
              {salesLeaderboard.length === 0 && <p className="text-sm text-slate-400 text-center py-4">{lbYear === 'all' ? '暂无成交数据' : `${lbYear}年${lbMonth === 'all' ? '' : lbMonth + '月'}暂无成交数据`}</p>}
            </div>
          </CardContent>
        </Card>

        {/* Recent customers */}
        <Card className="border-slate-200">
          <CardHeader className="pb-3"><CardTitle className="text-base font-semibold">最近客户</CardTitle></CardHeader>
          <CardContent>
            <div className="space-y-3">
              {recentCustomers.map((c: any) => (
                <div key={c.id} className="flex items-center justify-between py-2 border-b border-slate-100 last:border-0 cursor-pointer hover:bg-slate-50 rounded px-1" onClick={() => navigate('/customers')}>
                  <div><p className="text-sm font-medium text-slate-800">{c.business_name}</p><p className="text-xs text-slate-500">{c.contact_name}</p></div>
                  <Badge variant="secondary" className={`text-xs ${statusColors[c.status] || ''}`}>{statusLabels[c.status] || c.status}</Badge>
                </div>
              ))}
              {recentCustomers.length === 0 && <p className="text-sm text-slate-400 text-center py-4">暂无客户数据</p>}
            </div>
          </CardContent>
        </Card>

        {/* Upcoming tasks */}
        <Card className="border-slate-200">
          <CardHeader className="pb-3"><CardTitle className="text-base font-semibold">待办任务</CardTitle></CardHeader>
          <CardContent>
            <div className="space-y-3">
              {upcomingTasks.map((t: any) => (
                <div key={t.id} className="flex items-center justify-between py-2 border-b border-slate-100 last:border-0 cursor-pointer hover:bg-slate-50 rounded px-1" onClick={() => navigate('/tasks')}>
                  <div><p className="text-sm font-medium text-slate-800">{t.title}</p><p className="text-xs text-slate-500">{t.assignee_name} · {taskStatusLabels[t.status] || t.status}</p></div>
                  <Badge variant="secondary" className={`text-xs ${priorityColors[t.priority] || ''}`}>{priorityLabels[t.priority] || t.priority}</Badge>
                </div>
              ))}
              {upcomingTasks.length === 0 && <p className="text-sm text-slate-400 text-center py-4">暂无待办任务</p>}
            </div>
          </CardContent>
        </Card>
          </div>
        </CollapsibleContent>
      </Collapsible>
    </div>
  );
}
