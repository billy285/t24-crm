import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import MobileAppHome, {
  type MobileHomeRecentItem,
  type MobileHomeTodayItem,
} from '@/components/MobileAppHome';
import { client } from '@/lib/api';
import type { MobileBusinessAppKey } from '@/lib/app-navigation';
import { BUSINESS_DATA_REFRESH_EVENT } from '@/lib/data-refresh';
import { useRole } from '@/lib/role-context';
import { decorateEffectiveSubscriptions } from '@/lib/subscription-utils';
import { invokeWithAuth } from '@/lib/tokenStore';

type LauncherSnapshot = {
  todayItems: MobileHomeTodayItem[];
  appBadges: Partial<Record<MobileBusinessAppKey, number>>;
  recentItems: MobileHomeRecentItem[];
  notificationCount: number;
};

type AnyRecord = Record<string, any>;

const emptySnapshot: LauncherSnapshot = {
  todayItems: [],
  appBadges: {},
  recentItems: [],
  notificationCount: 0,
};

const localDateKey = () => new Intl.DateTimeFormat('en-CA', {
  timeZone: 'Asia/Shanghai',
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
}).format(new Date());

const dateKey = (value?: string | null) => String(value || '').slice(0, 10);
const isClosedTask = (task: AnyRecord) => ['completed', 'cancelled'].includes(String(task.status || ''));
const splitNames = (value?: string) => String(value || '').split(/[,，]/).map(item => item.trim()).filter(Boolean);
const timestampLabel = (value?: string | null) => {
  const key = dateKey(value);
  if (!key) return '';
  const today = localDateKey();
  if (key === today) return '今天更新';
  return key;
};

const itemsOf = (result: PromiseSettledResult<any>) => result.status === 'fulfilled'
  ? (result.value?.data?.items || [])
  : [];

const dataOf = (result: PromiseSettledResult<any>) => result.status === 'fulfilled'
  ? (result.value?.data || null)
  : null;

const fulfilled = (result: PromiseSettledResult<any>) => result.status === 'fulfilled';

export default function MobileAppLauncher({ onOpenProfile }: { onOpenProfile: () => void }) {
  const { employee, role, canAccess, isAdmin } = useRole();
  const [snapshot, setSnapshot] = useState<LauncherSnapshot>(emptySnapshot);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const requestSequence = useRef(0);
  const identityKey = `${employee?.id || 'unknown'}:${role || 'unknown'}`;

  const loadSnapshot = useCallback(async ({ background = false }: { background?: boolean } = {}) => {
    const requestId = ++requestSequence.current;
    if (!background) setLoading(true);

    const canReadTasks = canAccess('/tasks');
    const canReadCustomers = canAccess('/customers');
    const canReadFinance = ['super_admin', 'admin', 'finance'].includes(role);
    const isPartner = role === 'sales_partner';
    const isSales = role === 'sales';
    const isSalesManager = role === 'sales_manager';
    const today = localDateKey();

    const [tasksResult, customersResult, subscriptionsResult, paymentsResult, salesResult, partnerResult] = await Promise.allSettled([
      canReadTasks
        ? client.entities.tasks.query({ limit: 200, sort: '-updated_at' })
        : Promise.resolve({ data: { items: [] } }),
      canReadCustomers
        ? client.entities.customers.query({ limit: 100, sort: '-updated_at' })
        : Promise.resolve({ data: { items: [] } }),
      canReadFinance
        ? client.entities.subscriptions.query({ limit: 200, sort: 'end_date' })
        : Promise.resolve({ data: { items: [] } }),
      canReadFinance
        ? client.entities.payments.queryAll({ limit: 200, sort: '-payment_date' })
        : Promise.resolve({ data: { items: [] } }),
      isSales
        ? invokeWithAuth({ url: `/api/v1/sales-leads/workbench/today?target_date=${today}`, method: 'GET' })
        : isSalesManager
          ? invokeWithAuth({ url: '/api/v1/sales-leads/dashboard/management', method: 'GET' })
          : Promise.resolve({ data: null }),
      isPartner
        ? invokeWithAuth({ url: '/api/v1/commissions/my-dashboard', method: 'GET' })
        : Promise.resolve({ data: null }),
    ]);

    if (requestId !== requestSequence.current) return;

    const requiredResults = [
      canReadTasks ? tasksResult : null,
      canReadCustomers ? customersResult : null,
      canReadFinance ? subscriptionsResult : null,
      canReadFinance ? paymentsResult : null,
      (isSales || isSalesManager) ? salesResult : null,
      isPartner ? partnerResult : null,
    ].filter(Boolean) as PromiseSettledResult<any>[];

    const allFailed = requiredResults.length > 0 && requiredResults.every(result => !fulfilled(result));
    const partiallyFailed = requiredResults.some(result => !fulfilled(result));

    if (allFailed) {
      setLoadError('首页数字暂时无法更新，应用入口仍可正常使用。');
      setLoading(false);
      return;
    }

    let tasks = itemsOf(tasksResult);
    let customers = itemsOf(customersResult);
    const subscriptions = decorateEffectiveSubscriptions(itemsOf(subscriptionsResult));
    const payments = itemsOf(paymentsResult);
    const salesData = dataOf(salesResult) || {};
    const partnerData = dataOf(partnerResult) || {};
    const employeeName = String(employee?.name || '').trim();

    if (['ops', 'design'].includes(role) && employeeName) {
      tasks = tasks.filter((task: AnyRecord) => (
        String(task.assignee_name || '').trim() === employeeName
        || splitNames(task.collaborator_names).includes(employeeName)
      ));
    }
    if (role === 'sales' && employeeName) {
      customers = customers.filter((customer: AnyRecord) => (
        String(customer.sales_person || '').trim() === employeeName
        || Number(customer.sales_employee_id) === Number(employee?.id)
      ));
    }
    if (role === 'ops' && employeeName && !isAdmin) {
      customers = customers.filter((customer: AnyRecord) => (
        String(customer.ops_person || '').trim() === employeeName
        || String(customer.sales_person || '').trim() === employeeName
      ));
    }

    const openTasks = tasks.filter((task: AnyRecord) => !isClosedTask(task));
    const overdueTasks = openTasks.filter((task: AnyRecord) => {
      const due = dateKey(task.due_date);
      return due && due < today;
    });
    const dueTodayTasks = openTasks.filter((task: AnyRecord) => dateKey(task.due_date) === today);
    const financeRiskSubscriptions = subscriptions.filter((subscription: AnyRecord) => (
      ['renewal_pending', 'expiring_soon', 'expired'].includes(String(subscription.status || ''))
    ));
    const overduePayments = payments.filter((payment: AnyRecord) => Number(payment.outstanding_amount || 0) > 0);
    const recentItems: MobileHomeRecentItem[] = [];
    const todayItems: MobileHomeTodayItem[] = [];
    const appBadges: Partial<Record<MobileBusinessAppKey, number>> = {};
    let notificationCount = 0;

    if (isSales) {
      const remaining = Number(salesData.remaining_count || 0);
      const callbacksDue = Number(salesData.performance?.callbacks_due || salesData.categories?.callback || 0);
      const firstTask = Array.isArray(salesData.items)
        ? salesData.items.find((item: AnyRecord) => item.task_status !== 'completed')
        : null;
      appBadges.sales = remaining;
      notificationCount = remaining + callbacksDue;
      todayItems.push({
        id: 'sales-today',
        title: remaining > 0 ? `今天还有 ${remaining} 条销售任务` : '今日销售任务已完成',
        description: callbacksDue > 0
          ? `${callbacksDue} 条客户需要回访，优先完成已约时间的联系。`
          : '继续维护意向客户并完整记录沟通结果。',
        meta: firstTask?.lead?.business_name ? `下一位：${firstTask.lead.business_name}` : undefined,
        path: '/sales-workbench',
        actionLabel: remaining > 0 ? '开始拨打' : '查看今日记录',
        tone: remaining > 0 ? 'info' : 'success',
      });
    } else if (isSalesManager) {
      const metrics = salesData.metrics || {};
      const assigned = Number(metrics.assigned || 0);
      const completed = Number(metrics.completed || 0);
      const remaining = Math.max(0, assigned - completed);
      appBadges.sales = remaining;
      notificationCount = remaining;
      todayItems.push({
        id: 'sales-team-today',
        title: assigned > 0 ? `团队今日已完成 ${completed}/${assigned}` : '查看销售团队今日执行',
        description: remaining > 0 ? `还有 ${remaining} 条分配任务未完成，及时查看成员进度。` : '今日暂无未完成的团队销售任务。',
        path: '/sales-workbench',
        actionLabel: '查看团队进度',
        tone: remaining > 0 ? 'warning' : 'success',
      });
    } else if (isPartner) {
      const renewalAttention = Number(partnerData.summary?.renewal_attention_count || 0);
      const currencies = Object.values(partnerData.summary?.currencies || {}) as AnyRecord[];
      const payableEntries = currencies.reduce((sum, item) => sum + Number(item.payable || 0), 0);
      appBadges.partner = renewalAttention;
      notificationCount = renewalAttention;
      todayItems.push({
        id: 'partner-today',
        title: renewalAttention > 0 ? `${renewalAttention} 位合作客户需要关注` : '合作客户状态正常',
        description: payableEntries > 0 ? `当前有 ${payableEntries} 笔分润进入可结算状态。` : '查看客户续费与分润确认状态。',
        path: '/partner-portal',
        actionLabel: '查看客户与分润',
        tone: renewalAttention > 0 ? 'warning' : 'success',
      });
    } else if (role === 'finance') {
      const riskCount = financeRiskSubscriptions.length + overduePayments.length;
      appBadges.finance = riskCount;
      notificationCount = riskCount;
      todayItems.push({
        id: 'finance-today',
        title: riskCount > 0 ? `${riskCount} 项财务事项需要核对` : '收款与续费状态正常',
        description: `${overduePayments.length} 笔待收款 · ${financeRiskSubscriptions.length} 个续费风险`,
        path: '/finance?tab=receivables',
        actionLabel: '查看财务待办',
        tone: overduePayments.length > 0 ? 'critical' : riskCount > 0 ? 'warning' : 'success',
      });
    } else if (role === 'ops' || role === 'design') {
      const priorityCount = overdueTasks.length + dueTodayTasks.length;
      appBadges.delivery = openTasks.length;
      notificationCount = priorityCount || openTasks.length;
      const roleName = role === 'design' ? '设计' : '运营';
      todayItems.push({
        id: `${role}-today`,
        title: overdueTasks.length > 0
          ? `${overdueTasks.length} 项${roleName}任务已逾期`
          : dueTodayTasks.length > 0
            ? `今天有 ${dueTodayTasks.length} 项${roleName}任务到期`
            : `当前有 ${openTasks.length} 项${roleName}任务`,
        description: overdueTasks.length > 0 ? '优先处理逾期事项，并补充最新进展。' : '从自己的任务开始，完成后及时记录结果。',
        meta: (overdueTasks[0] || dueTodayTasks[0] || openTasks[0])?.title,
        path: '/tasks?view=mine',
        actionLabel: '打开我的任务',
        tone: overdueTasks.length > 0 ? 'critical' : priorityCount > 0 ? 'warning' : openTasks.length > 0 ? 'info' : 'success',
      });
    } else {
      const totalRisk = overdueTasks.length + financeRiskSubscriptions.length + overduePayments.length;
      appBadges.delivery = openTasks.length;
      appBadges.customers = customers.length;
      appBadges.finance = financeRiskSubscriptions.length + overduePayments.length;
      notificationCount = totalRisk;
      todayItems.push({
        id: 'owner-today',
        title: totalRisk > 0 ? `今天有 ${totalRisk} 项经营风险待确认` : '今日经营状态暂无高风险提醒',
        description: `${overdueTasks.length} 项逾期任务 · ${overduePayments.length} 笔待收款 · ${financeRiskSubscriptions.length} 个续费风险`,
        path: '/',
        actionLabel: '打开老板今日工作台',
        tone: overduePayments.length > 0 || overdueTasks.length > 0 ? 'critical' : totalRisk > 0 ? 'warning' : 'success',
      });
    }

    if (canReadTasks) {
      openTasks.slice(0, 2).forEach((task: AnyRecord) => recentItems.push({
        id: `task-${task.id}`,
        title: task.title || '待处理任务',
        description: task.customer_name || task.assignee_name || '任务协作',
        timestamp: timestampLabel(task.updated_at || task.created_at || task.due_date),
        path: `/tasks?task_id=${task.id}&returnTo=${encodeURIComponent('/apps')}`,
        appKey: 'delivery',
      }));
    }
    if (canReadCustomers && recentItems.length < 3) {
      customers.slice(0, 3 - recentItems.length).forEach((customer: AnyRecord) => recentItems.push({
        id: `customer-${customer.id}`,
        title: customer.business_name || customer.name || `客户 #${customer.id}`,
        description: customer.status || customer.customer_code || '客户资料',
        timestamp: timestampLabel(customer.updated_at || customer.created_at),
        path: `/customers?detail=${customer.id}&tab=overview&returnTo=${encodeURIComponent('/apps')}`,
        appKey: 'customers',
      }));
    }

    setSnapshot({ todayItems, appBadges, recentItems, notificationCount });
    setLoadError(partiallyFailed ? '部分首页数字暂未更新，已显示当前可用数据。' : '');
    setLoading(false);
  }, [canAccess, employee?.id, employee?.name, isAdmin, role]);

  useEffect(() => {
    setSnapshot(emptySnapshot);
    setLoadError('');
    void loadSnapshot();
    return () => { requestSequence.current += 1; };
  }, [identityKey, loadSnapshot]);

  useEffect(() => {
    const refresh = () => void loadSnapshot({ background: true });
    window.addEventListener(BUSINESS_DATA_REFRESH_EVENT, refresh);
    return () => window.removeEventListener(BUSINESS_DATA_REFRESH_EVENT, refresh);
  }, [loadSnapshot]);

  const retry = useMemo(() => () => {
    void loadSnapshot();
  }, [loadSnapshot]);

  return (
    <MobileAppHome
      {...snapshot}
      loading={loading}
      loadError={loadError}
      onRetry={retry}
      onOpenProfile={onOpenProfile}
    />
  );
}
