import { useState, useEffect, useMemo } from 'react';
import { client } from '../lib/api';
import { useRole } from '../lib/role-context';
import { isAdminRole } from '../lib/permissions';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { NativeSelect } from '@/components/ui/native-select';
import { useNavigate } from 'react-router-dom';
import {
  Users, UserPlus, Handshake, AlertTriangle, DollarSign,
  Clock, TrendingUp, ListTodo, Bell, CalendarClock, CreditCard, PackageCheck,
  Palette, Truck, CheckCircle2, Timer, PhoneCall
} from 'lucide-react';

interface Reminder {
  id: string;
  type: 'follow_up' | 'renewal' | 'overdue_payment' | 'pending_task' | 'no_follow_7d' | 'callback';
  title: string;
  description: string;
  urgency: 'high' | 'medium' | 'low';
  date?: string;
  link?: string;
}

export default function Dashboard() {
  const { role, employee, isAdmin } = useRole();
  const navigate = useNavigate();
  const [data, setData] = useState<any>({});
  const [reminders, setReminders] = useState<Reminder[]>([]);
  const [loading, setLoading] = useState(true);
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
      const subs = subsRes?.data?.items || [];
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
      const sevenDaysLater = new Date(now.getTime() + 7 * 86400000);
      const thirtyDaysLater = new Date(now.getTime() + 30 * 86400000);
      const sevenDaysAgo = new Date(now.getTime() - 7 * 86400000);
      const currentMonthKey = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;

      const totalCustomers = customers.length;
      const followingCustomers = customers.filter((c: any) => c.status === 'following').length;
      const closedThisMonth = deals.filter((d: any) => new Date(d.deal_date) >= monthStart).length;
      const lostCustomers = customers.filter((c: any) => c.status === 'lost').length;
      const newThisMonth = customers.filter((c: any) => new Date(c.created_at) >= monthStart).length;

      const expiringSoon = subs.filter((s: any) =>
        s.end_date && new Date(s.end_date) <= thirtyDaysLater && new Date(s.end_date) >= now && s.status !== 'expired'
      ).length;

      const monthlyPayments = payments.filter((p: any) => new Date(p.payment_date) >= monthStart);
      const monthlyRevenue = monthlyPayments.reduce((sum: number, p: any) => sum + (p.amount_paid || 0), 0);
      const overduePayments = payments.filter((p: any) => (p.outstanding_amount || 0) > 0).length;
      const totalOutstanding = payments.filter((p: any) => (p.outstanding_amount || 0) > 0).reduce((s: number, p: any) => s + (p.outstanding_amount || 0), 0);

      const pendingTasks = tasks.filter((t: any) => t.status === 'pending' || t.status === 'in_progress').length;
      const completedTasks = tasks.filter((t: any) => t.status === 'completed').length;
      const delayedTasks = tasks.filter((t: any) => t.status === 'delayed').length;

      const monthlyDealAmount = deals.filter((d: any) => new Date(d.deal_date) >= monthStart).reduce((s: number, d: any) => s + (d.deal_amount || 0), 0);

      // Expired not renewed
      const expiredNotRenewed = subs.filter((s: any) =>
        s.end_date && new Date(s.end_date) < now && (s.status === 'expired' || s.status === 'expiring_soon')
      ).length;

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
      buildReminders(customers, followUps, subs, payments, tasks, now, sevenDaysLater, sevenDaysAgo, callbacksList);
    } catch (err) {
      console.error('Failed to load dashboard:', err);
    } finally {
      setLoading(false);
    }
  };

  const buildReminders = (customers: any[], followUps: any[], subs: any[], payments: any[], tasks: any[], now: Date, sevenDaysLater: Date, sevenDaysAgo: Date, callbacksList?: any[]) => {
    const newReminders: Reminder[] = [];
    const customerMap = Object.fromEntries(customers.map((c: any) => [c.id, c]));
    const todayStr = now.toISOString().slice(0, 10);

    // Today's follow-ups
    if (isAdm || isSales) {
      const todayFollowUps = followUps.filter((f: any) =>
        f.next_follow_date?.slice(0, 10) === todayStr && f.stage !== 'closed' && f.stage !== 'lost'
      );
      todayFollowUps.slice(0, 5).forEach((f: any) => {
        const cust = customerMap[f.customer_id];
        newReminders.push({
          id: `fu-today-${f.id}`, type: 'follow_up', urgency: 'high',
          title: `今日待跟进: ${cust?.business_name || '未知客户'}`,
          description: f.content?.slice(0, 50) || '请及时跟进',
          date: todayStr, link: '/customers?status=following',
        });
      });

      // Overdue follow-ups
      const overdueFollowUps = followUps.filter((f: any) =>
        f.next_follow_date && new Date(f.next_follow_date) < now && f.next_follow_date?.slice(0, 10) !== todayStr && f.stage !== 'closed' && f.stage !== 'lost'
      );
      overdueFollowUps.slice(0, 5).forEach((f: any) => {
        const cust = customerMap[f.customer_id];
        newReminders.push({
          id: `fu-${f.id}`, type: 'follow_up', urgency: 'high',
          title: `逾期跟进: ${cust?.business_name || '未知客户'}`,
          description: `计划跟进日期 ${f.next_follow_date?.slice(0, 10)} 已过期`,
          date: f.next_follow_date?.slice(0, 10), link: '/customers?status=following',
        });
      });

      // 7-day no follow-up
      const customerLastFollowUp: Record<number, string> = {};
      followUps.forEach((f: any) => {
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
          description: `上次跟进: ${lastDate}`, link: '/customers?status=following',
        });
      });
    }

    // Expiring subscriptions
    if (isAdm || isFinance) {
      const expiringSubs = subs.filter((s: any) =>
        s.end_date && new Date(s.end_date) <= sevenDaysLater && new Date(s.end_date) >= now && s.status !== 'expired'
      );
      expiringSubs.slice(0, 5).forEach((s: any) => {
        const cust = customerMap[s.customer_id];
        newReminders.push({
          id: `sub-${s.id}`, type: 'renewal', urgency: 'high',
          title: `即将到期: ${cust?.business_name || '未知客户'}`,
          description: `${s.package_name} 将于 ${s.end_date?.slice(0, 10)} 到期`,
          date: s.end_date?.slice(0, 10), link: '/finance',
        });
      });

      // Overdue payments
      const overduePaymentsList = payments.filter((p: any) => (p.outstanding_amount || 0) > 0);
      overduePaymentsList.slice(0, 5).forEach((p: any) => {
        const cust = customerMap[p.customer_id];
        newReminders.push({
          id: `pay-${p.id}`, type: 'overdue_payment', urgency: 'high',
          title: `欠费: ${cust?.business_name || '未知客户'}`,
          description: `${p.product_name} 欠款 $${p.outstanding_amount}`, link: '/finance',
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
          date: todayStr2, link: '/callbacks',
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
          date: cb.callback_date?.slice(0, 10), link: '/callbacks',
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
        date: t.due_date?.slice(0, 10), link: '/tasks',
      });
    });

    const urgencyOrder = { high: 0, medium: 1, low: 2 };
    newReminders.sort((a, b) => urgencyOrder[a.urgency] - urgencyOrder[b.urgency]);
    setReminders(newReminders);
  };

  const statusLabels: Record<string, string> = { new: '新线索', following: '跟进中', closed: '已成交', paused: '暂停', lost: '流失' };
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
                  {r.date && <span className="text-xs text-slate-400 flex-shrink-0">{r.date}</span>}
                </div>
              );
            })}
          </div>
        </CardContent>
      </Card>
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

  return (
    <div className="space-y-6">
      <h2 className="text-xl font-semibold text-slate-800">管理员工作台</h2>
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