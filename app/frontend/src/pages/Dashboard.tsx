import { useState, useEffect, useMemo } from 'react';
import { client } from '../lib/api';
import { useRole } from '../lib/role-context';
import { invokeWithAuth } from '../lib/tokenStore';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { NativeSelect } from '@/components/ui/native-select';
import { useNavigate } from 'react-router-dom';
import {
  Users, UserPlus, Handshake, AlertTriangle, DollarSign,
  Clock, TrendingUp, ListTodo, Bell, CalendarClock, CreditCard, PackageCheck,
  Palette, CheckCircle2, Timer, PhoneCall, Target, PhoneForwarded,
  CalendarCheck2, ShieldAlert, FileCheck2, Banknote, ArrowRight
} from 'lucide-react';
import { useBusinessDicts } from '../lib/dict-config';
import { decorateEffectiveSubscriptions } from '../lib/subscription-utils';
import { useAutoRefresh } from '../lib/use-auto-refresh';

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
  const { role, employee, isAdmin } = useRole();
  const { statuses: statusLabels } = useBusinessDicts();
  const navigate = useNavigate();
  const [data, setData] = useState<any>({});
  const [reminders, setReminders] = useState<Reminder[]>([]);
  const [loading, setLoading] = useState(true);
  const [salesPeriod, setSalesPeriod] = useState<1 | 7 | 30>(7);
  const [salesManagement, setSalesManagement] = useState<SalesManagementDashboard | null>(null);
  const [salesPerformance, setSalesPerformance] = useState<SalesPerformanceDashboard | null>(null);
  const [salesRecovery, setSalesRecovery] = useState<SalesRecoveryOverview | null>(null);
  const [salesCockpitLoading, setSalesCockpitLoading] = useState(false);
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
      // Always load tasks
      queries.push(client.entities.tasks.query({ limit: 200 }));

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

      // Build reminders
      buildReminders(customers, followUps, subs, payments, tasks, now, sevenDaysAgo, callbacksList);
    } catch (err) {
      console.error('Failed to load dashboard:', err);
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

  useEffect(() => {
    if (isAdm) void loadSalesCockpit(salesPeriod);
  }, [isAdm, salesPeriod]);

  useAutoRefresh(loadDashboard, { intervalMs: 30000 });

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

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600" />
      </div>
    );
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
      { label: '已拨打', value: metrics.calls, color: 'bg-blue-600' },
      { label: '已接通', value: metrics.connected, color: 'bg-cyan-500' },
      { label: '有意向', value: metrics.interested, color: 'bg-amber-500' },
      { label: '已预约', value: metrics.appointments, color: 'bg-violet-500' },
      { label: '转正式客户', value: metrics.converted, color: 'bg-emerald-600' },
    ];
    const funnelBase = Math.max(...funnel.map(item => item.value), 1);
    const salesMetricCards = [
      { label: '已分配任务', value: metrics.assigned, helper: `${metrics.completed} 条已完成`, icon: Target, tone: 'text-slate-700 bg-slate-100', link: '/sales-workbench' },
      { label: '拨打完成率', value: `${metrics.completion_rate}%`, helper: `${metrics.calls} 次拨打记录`, icon: PhoneCall, tone: 'text-blue-700 bg-blue-50', link: '/sales-workbench' },
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
                <h3 className="mt-2 text-xl font-semibold">从拨打执行到正式成交，一眼看清销售推进效率</h3>
                <p className="mt-1 text-xs text-slate-300">销售预测与正式财务数据分开统计；售前收款仅显示销售交接中已确认的金额。</p>
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
          <CardHeader className="pb-3"><div className="flex items-center justify-between"><div><CardTitle className="text-base">团队表现与系统建议</CardTitle><p className="mt-1 text-xs text-slate-500">{salesPeriod === 1 ? '按今天真实拨打与跟进记录评分。' : `按最近${salesPeriod}天真实拨打与跟进记录评分。`}</p></div><Button size="sm" variant="outline" onClick={() => navigate('/sales-leads')}>查看完整评分</Button></div></CardHeader>
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
        </div>
      </div>
    );
  }

  // ---------- Admin / Super Admin Dashboard ----------
  const recentCustomers = (data.customers || []).slice(0, 5);
  const upcomingTasks = (data.tasks || []).filter((t: any) => t.status !== 'completed').slice(0, 5);
  const adminAttention = salesManagement?.owner_attention;
  const adminTodayActions = [
    {
      step: '01',
      eyebrow: '先处理异常',
      title: '跟进高意向与逾期回访',
      description: '优先处理最可能影响成交的销售异常。',
      count: (adminAttention?.high_intent_stale || 0) + (adminAttention?.overdue_followups || 0),
      unit: '项待处理',
      link: '/sales-leads',
      tone: 'border-rose-200 bg-rose-50/70 text-rose-700',
    },
    {
      step: '02',
      eyebrow: '再看执行',
      title: '检查今天的拨打进度',
      description: '确认每位销售已经领取任务并持续完成记录。',
      count: salesManagement?.metrics?.completed || 0,
      unit: `/${salesManagement?.metrics?.assigned || 0} 已完成`,
      link: '/sales-workbench',
      tone: 'border-blue-200 bg-blue-50/70 text-blue-700',
    },
    {
      step: '03',
      eyebrow: '最后闭环',
      title: '确认交付、收款与续费',
      description: '把成交后的任务和财务异常在当天闭环。',
      count: (data.pendingTasks || 0) + (data.overduePayments || 0) + (data.expiringSoon || 0),
      unit: '项需关注',
      link: '/tasks',
      tone: 'border-amber-200 bg-amber-50/70 text-amber-700',
    },
  ];

  return (
    <div className="space-y-6">
      <div>
        <p className="text-xs font-semibold uppercase tracking-[0.18em] text-blue-600">今日经营节奏</p>
        <h2 className="mt-1 text-2xl font-bold tracking-tight text-slate-900">管理员工作台</h2>
        <p className="mt-1 text-sm text-slate-500">先处理异常，再检查执行，最后确认成交后的交付闭环。</p>
      </div>

      <section aria-labelledby="admin-today-actions">
        <div className="mb-3 flex items-end justify-between gap-3">
          <div>
            <h3 id="admin-today-actions" className="text-base font-semibold text-slate-900">今天先做这三件事</h3>
            <p className="mt-1 text-xs text-slate-500">按照优先级完成，避免只看数据却不知道下一步。</p>
          </div>
          <span className="hidden text-xs text-slate-400 sm:block">点击卡片直接进入处理页面</span>
        </div>
        <div className="grid gap-3 lg:grid-cols-3">
          {adminTodayActions.map(action => (
            <button
              key={action.step}
              type="button"
              onClick={() => navigate(action.link)}
              className={`group flex min-h-36 flex-col rounded-2xl border p-4 text-left transition hover:-translate-y-0.5 hover:shadow-md ${action.tone}`}
            >
              <div className="flex items-center justify-between gap-3">
                <span className="text-[11px] font-bold tracking-[0.16em]">{action.step} · {action.eyebrow}</span>
                <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-1" />
              </div>
              <p className="mt-3 font-semibold text-slate-900">{action.title}</p>
              <p className="mt-1 flex-1 text-xs leading-5 text-slate-600">{action.description}</p>
              <p className="mt-3 text-2xl font-bold">{action.count}<span className="ml-1 text-xs font-medium">{action.unit}</span></p>
            </button>
          ))}
        </div>
      </section>

      {renderSalesOwnerCockpit()}
      {renderReminders()}

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
    </div>
  );
}
