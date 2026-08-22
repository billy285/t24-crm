import { useEffect, useMemo, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import {
  AlertTriangle,
  ArrowRight,
  CalendarClock,
  CheckCircle2,
  ClipboardCheck,
  Clock3,
  RefreshCw,
  UserRound,
} from 'lucide-react';
import { toast } from 'sonner';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Textarea } from '@/components/ui/textarea';
import PageLoadState from '@/components/PageLoadState';
import { client } from '@/lib/api';
import { useAutoRefresh } from '@/lib/use-auto-refresh';
import { useRole } from '@/lib/role-context';

type WorkbenchTask = {
  id: number;
  title?: string;
  customer_id?: number;
  customer_name?: string;
  assignee_name?: string;
  collaborator_names?: string;
  status?: string;
  priority?: string;
  due_date?: string;
  notes?: string;
  updated_at?: string;
};

type CallbackRecord = {
  id: number;
  customer_id: number;
  employee_id?: number;
  employee_name?: string;
  callback_date?: string;
  callback_type?: string;
  status?: string;
};

type ServiceProgress = {
  id: number;
  customer_id: number;
  customer_name?: string;
  ops_person?: string;
  issue_owner?: string;
  issue_status?: string;
  issue_description?: string;
  issue_resolved?: boolean;
  notes?: string;
};

type CustomerRecord = { id: number; business_name?: string; customer_code?: string };
type ActionFilter = 'all' | 'overdue' | 'today' | 'waiting' | 'issue';
type ActionItem = {
  id: string;
  kind: 'task' | 'callback' | 'issue';
  sourceId: number;
  customerId?: number;
  customerName: string;
  title: string;
  description: string;
  urgency: 'overdue' | 'today' | 'waiting' | 'normal';
  date?: string;
  raw: WorkbenchTask | CallbackRecord | ServiceProgress;
};

const localDateKey = () => {
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit',
  }).format(new Date());
};

const daysBetweenDateKeys = (from?: string, to?: string) => {
  if (!from || !to) return 0;
  const start = Date.parse(`${from}T00:00:00Z`);
  const end = Date.parse(`${to}T00:00:00Z`);
  return Math.max(0, Math.round((end - start) / 86400000));
};

const isClosedTask = (task: WorkbenchTask) => ['completed', 'cancelled'].includes(task.status || '');
const isWaitingClient = (task: WorkbenchTask) => task.status === 'waiting_client'
  || /等待客户|客户资料|待客户/.test(`${task.title || ''} ${task.notes || ''}`);
const splitNames = (value?: string) => (value || '').split(/[,，]/).map(item => item.trim()).filter(Boolean);

export default function OperationsWorkbench() {
  const navigate = useNavigate();
  const location = useLocation();
  const { role, employee, isAdmin } = useRole();
  const [tasks, setTasks] = useState<WorkbenchTask[]>([]);
  const [callbacks, setCallbacks] = useState<CallbackRecord[]>([]);
  const [progresses, setProgresses] = useState<ServiceProgress[]>([]);
  const [customers, setCustomers] = useState<CustomerRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [filter, setFilter] = useState<ActionFilter>('all');
  const [visibleCount, setVisibleCount] = useState(30);
  const [completeTarget, setCompleteTarget] = useState<ActionItem | null>(null);
  const [completionNote, setCompletionNote] = useState('');
  const [saving, setSaving] = useState(false);

  const loadData = async () => {
    const results = await Promise.allSettled([
      client.entities.tasks.query({ limit: 1000, sort: '-created_at' }),
      client.apiCall.invoke({ url: '/api/v1/entities/customer_callbacks', method: 'GET', data: { limit: 1000, sort: '-callback_date' } }),
      client.entities.service_progresses.queryAll({ limit: 1000, sort: '-last_update_time' }),
      client.entities.customers.query({ limit: 1000 }),
    ]);
    const succeeded = results.filter(result => result.status === 'fulfilled').length;
    if (succeeded === 0) {
      setLoadError('运营数据暂时无法读取，请稍后重试。');
      setLoading(false);
      return;
    }
    const valueAt = (index: number) => results[index].status === 'fulfilled' ? (results[index] as PromiseFulfilledResult<any>).value : null;
    setTasks(valueAt(0)?.data?.items || []);
    setCallbacks(valueAt(1)?.data?.items || []);
    setProgresses(valueAt(2)?.data?.items || []);
    setCustomers(valueAt(3)?.data?.items || []);
    setLoadError(succeeded < results.length ? '部分关联数据暂未加载，已保留可用的今日事项。' : '');
    setLoading(false);
  };

  useEffect(() => { void loadData(); }, []);
  useAutoRefresh(loadData, { intervalMs: 30000, enabled: !completeTarget });

  const customerMap = useMemo(
    () => Object.fromEntries(customers.map(customer => [customer.id, customer])),
    [customers],
  );
  const employeeName = String(employee?.name || '').trim();
  const today = localDateKey();
  const usePersonalScope = role === 'ops' && !isAdmin && Boolean(employeeName);

  const scopedTasks = useMemo(() => tasks.filter(task => {
    if (isClosedTask(task)) return false;
    if (!usePersonalScope) return true;
    return task.assignee_name === employeeName || splitNames(task.collaborator_names).includes(employeeName);
  }), [employeeName, tasks, usePersonalScope]);

  const scopedCallbacks = useMemo(() => callbacks.filter(callback => {
    if (callback.status !== 'pending') return false;
    if (!usePersonalScope) return true;
    return Number(callback.employee_id) === Number(employee?.id) || callback.employee_name === employeeName;
  }), [callbacks, employee?.id, employeeName, usePersonalScope]);

  const scopedIssues = useMemo(() => progresses.filter(progress => {
    if (progress.issue_resolved || !progress.issue_status || progress.issue_status === 'none') return false;
    if (!usePersonalScope) return true;
    return progress.ops_person === employeeName || progress.issue_owner === employeeName;
  }), [employeeName, progresses, usePersonalScope]);

  const actions = useMemo<ActionItem[]>(() => {
    const taskActions = scopedTasks.map<ActionItem>(task => {
      const date = task.due_date?.slice(0, 10);
      const urgency = isWaitingClient(task) ? 'waiting' : date && date < today ? 'overdue' : date === today ? 'today' : 'normal';
      return {
        id: `task-${task.id}`,
        kind: 'task',
        sourceId: task.id,
        customerId: task.customer_id,
        customerName: task.customer_name || customerMap[task.customer_id || 0]?.business_name || '未关联客户',
        title: task.title || '运营任务',
        description: task.assignee_name ? `负责人：${task.assignee_name}` : '尚未分配负责人',
        urgency,
        date,
        raw: task,
      };
    });
    const callbackActions = scopedCallbacks.map<ActionItem>(callback => {
      const date = callback.callback_date?.slice(0, 10);
      return {
        id: `callback-${callback.id}`,
        kind: 'callback',
        sourceId: callback.id,
        customerId: callback.customer_id,
        customerName: customerMap[callback.customer_id]?.business_name || `客户 #${callback.customer_id}`,
        title: '记录客户回访结果',
        description: callback.employee_name ? `回访负责人：${callback.employee_name}` : '待安排回访负责人',
        urgency: date && date < today ? 'overdue' : date === today ? 'today' : 'normal',
        date,
        raw: callback,
      };
    });
    const issueActions = scopedIssues.map<ActionItem>(progress => ({
      id: `issue-${progress.id}`,
      kind: 'issue',
      sourceId: progress.id,
      customerId: progress.customer_id,
      customerName: progress.customer_name || customerMap[progress.customer_id]?.business_name || `客户 #${progress.customer_id}`,
      title: progress.issue_description || '服务问题待处理',
      description: progress.issue_owner ? `问题负责人：${progress.issue_owner}` : '需要确认处理人和结果',
      urgency: ['waiting_client', 'waiting_material'].includes(progress.issue_status || '') ? 'waiting' : 'today',
      raw: progress,
    }));
    const urgencyRank = { overdue: 0, today: 1, waiting: 2, normal: 3 };
    return [...taskActions, ...callbackActions, ...issueActions].sort((a, b) => {
      const urgencyDifference = urgencyRank[a.urgency] - urgencyRank[b.urgency];
      if (urgencyDifference !== 0) return urgencyDifference;
      return String(a.date || '9999').localeCompare(String(b.date || '9999'));
    });
  }, [customerMap, scopedCallbacks, scopedIssues, scopedTasks, today]);

  const stats = useMemo(() => ({
    overdue: actions.filter(action => action.urgency === 'overdue').length,
    today: actions.filter(action => action.urgency === 'today').length,
    waiting: actions.filter(action => action.urgency === 'waiting').length,
    issues: actions.filter(action => action.kind === 'issue').length,
  }), [actions]);
  const filteredActions = filter === 'all'
    ? actions
    : filter === 'issue'
      ? actions.filter(action => action.kind === 'issue')
      : actions.filter(action => action.urgency === filter);
  const visibleActions = filteredActions.slice(0, visibleCount);

  useEffect(() => { setVisibleCount(30); }, [filter]);

  const currentReturnPath = `${location.pathname}${location.search}`;
  const openCustomer = (action: ActionItem) => {
    if (!action.customerId) return;
    navigate(`/customers?detail=${action.customerId}&tab=overview&from=tasks&returnTo=${encodeURIComponent(currentReturnPath)}`);
  };

  const openAction = (action: ActionItem) => {
    if (action.kind === 'callback') {
      const schedule = action.urgency === 'overdue' ? 'overdue' : action.urgency === 'today' ? 'today' : 'all';
      navigate(`/callbacks?customer_id=${action.customerId || ''}&schedule=${schedule}`);
      return;
    }
    setCompletionNote('');
    setCompleteTarget(action);
  };

  const completeAction = async () => {
    if (!completeTarget || !completionNote.trim()) {
      toast.error('请填写处理结果，方便后续追踪。');
      return;
    }
    setSaving(true);
    try {
      const now = new Date();
      if (completeTarget.kind === 'task') {
        const task = completeTarget.raw as WorkbenchTask;
        const existingNotes = String(task.notes || '').trim();
        await client.entities.tasks.update({
          id: String(task.id),
          data: {
            status: 'completed',
            completion_result: completionNote.trim(),
            notes: [existingNotes, `完成结果：${completionNote.trim()}`].filter(Boolean).join('\n\n'),
            updated_at: now.toISOString(),
          },
        });
        toast.success('任务已完成并记录结果');
      } else if (completeTarget.kind === 'issue') {
        const progress = completeTarget.raw as ServiceProgress;
        await client.entities.service_progresses.update({
          id: String(progress.id),
          data: {
            issue_resolved: true,
            issue_resolved_date: today,
            last_update_time: now.toISOString(),
            last_update_person: employeeName || '管理员',
            notes: [String(progress.notes || '').trim(), `问题处理结果：${completionNote.trim()}`].filter(Boolean).join('\n\n'),
          },
        });
        toast.success('服务问题已解决并记录结果');
      }
      setCompleteTarget(null);
      setCompletionNote('');
      await loadData();
    } catch (error) {
      console.error(error);
      toast.error('保存处理结果失败');
    } finally {
      setSaving(false);
    }
  };

  if (loading && actions.length === 0) return <PageLoadState loading message="正在汇总今天的运营事项…" />;
  if (loadError && actions.length === 0 && tasks.length === 0 && callbacks.length === 0 && progresses.length === 0) {
    return <PageLoadState error={loadError} onRetry={() => { setLoading(true); void loadData(); }} />;
  }

  const urgencyStyles = {
    overdue: { label: '已逾期', badge: 'bg-rose-100 text-rose-700', card: 'border-rose-200 bg-rose-50/40', bar: 'bg-rose-500', icon: 'bg-rose-100 text-rose-700' },
    today: { label: '今天处理', badge: 'bg-blue-100 text-blue-700', card: 'border-blue-200', bar: 'bg-blue-500', icon: 'bg-blue-100 text-blue-700' },
    waiting: { label: '等待客户', badge: 'bg-amber-100 text-amber-800', card: 'border-amber-200 bg-amber-50/40', bar: 'bg-amber-500', icon: 'bg-amber-100 text-amber-700' },
    normal: { label: '后续待办', badge: 'bg-slate-100 text-slate-600', card: 'border-slate-200', bar: 'bg-slate-400', icon: 'bg-slate-100 text-slate-600' },
  } as const;

  return (
    <div className="t24-work-page app-page space-y-5">
      <div className="app-page-title">
        <div>
          <p className="app-page-kicker">T24 Marketing · Operations Today</p>
          <h2 className="app-page-heading">运营今日工作台</h2>
          <p className="app-page-description">先处理逾期和今天必须完成的事项；任务与服务问题可在本页直接闭环。</p>
        </div>
        <Button variant="outline" size="sm" onClick={() => void loadData()} disabled={loading}>
          <RefreshCw className={`mr-1.5 h-4 w-4 ${loading ? 'animate-spin' : ''}`} />刷新
        </Button>
      </div>

      {loadError && <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">{loadError}</div>}

      <div className="grid grid-cols-2 gap-2 md:gap-3 xl:grid-cols-4">
        {[
          { key: 'overdue' as const, label: '逾期未处理', value: stats.overdue, icon: AlertTriangle, tone: 'text-rose-700' },
          { key: 'today' as const, label: '今天必须做', value: stats.today, icon: CalendarClock, tone: 'text-blue-700' },
          { key: 'waiting' as const, label: '等待客户', value: stats.waiting, icon: Clock3, tone: 'text-amber-700' },
          { key: 'issue' as const, label: '服务问题', value: stats.issues, icon: ClipboardCheck, tone: 'text-violet-700' },
        ].map(item => (
          <button key={item.label} type="button" onClick={() => setFilter(item.key)} className="text-left">
            <Card className={`h-full rounded-[20px] border-slate-200 transition hover:border-blue-300 hover:shadow-sm md:rounded-xl ${filter === item.key ? 'ring-2 ring-blue-500 ring-offset-1' : ''}`}>
              <CardContent className="flex min-h-[88px] items-center gap-2.5 p-3 md:gap-3 md:p-4">
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-slate-50"><item.icon className={`h-[18px] w-[18px] ${item.tone}`} /></span>
                <div className="min-w-0"><p className="text-xl font-bold text-slate-900 md:text-2xl md:font-semibold">{item.value}</p><p className="truncate text-[11px] font-medium text-slate-500 md:text-xs">{item.label}</p></div>
              </CardContent>
            </Card>
          </button>
        ))}
      </div>

      <div className="flex items-start justify-between gap-3 px-0.5">
        <div className="min-w-0"><div className="flex items-center gap-2"><h3 className="text-lg font-bold text-slate-950 md:text-base md:font-semibold md:text-slate-900">下一步动作</h3><span className="rounded-full bg-slate-900 px-2 py-0.5 text-[10px] font-bold text-white">{filteredActions.length} 项</span></div><p className="mt-1 text-xs leading-5 text-slate-500">按逾期、今日、等待客户排序，先处理最重要的事项。</p></div>
        {filter !== 'all' && <Button size="sm" variant="ghost" onClick={() => setFilter('all')}>查看全部 {actions.length} 项</Button>}
      </div>

      {filteredActions.length === 0 ? (
        <Card className="border-dashed border-emerald-200 bg-emerald-50/40"><CardContent className="flex flex-col items-center py-12 text-center"><CheckCircle2 className="h-8 w-8 text-emerald-600" /><p className="mt-3 font-medium text-emerald-900">当前分类没有待处理事项</p><p className="mt-1 text-sm text-emerald-700">系统每 30 秒刷新一次；新任务和提醒会自动进入这里。</p></CardContent></Card>
      ) : (
        <div className="grid gap-3">
          {visibleActions.map(action => {
            const style = urgencyStyles[action.urgency];
            const overdueDays = action.urgency === 'overdue' ? daysBetweenDateKeys(action.date, today) : 0;
            const missingOwner = /尚未分配|待安排|需要确认处理人/.test(action.description);
            const actionTypeLabel = action.kind === 'task' ? '任务' : action.kind === 'callback' ? '回访' : '服务问题';
            const primaryActionLabel = action.kind === 'callback' ? '记录回访' : action.kind === 'issue' ? '解决问题' : '完成任务';
            const ActionIcon = action.kind === 'callback' ? Clock3 : action.kind === 'issue' ? AlertTriangle : ClipboardCheck;
            const ownerLabel = action.description.replace(/^(负责人|回访负责人|问题负责人)：\s*/, '');
            return (
              <Card key={action.id} className={`overflow-hidden rounded-[22px] shadow-[0_10px_28px_-22px_rgba(15,23,42,0.55)] md:rounded-xl md:shadow-none ${style.card}`}>
                <CardContent className="p-0 md:p-4">
                  <div className="md:hidden">
                    <div className={`h-1 w-full ${style.bar}`} />
                    <div className="p-4">
                      <div className="flex items-start justify-between gap-3">
                        <div className="flex min-w-0 items-center gap-2.5">
                          <span className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl ${style.icon}`}><ActionIcon className="h-[18px] w-[18px]" /></span>
                          <div className="min-w-0">
                            <div className="flex flex-wrap items-center gap-1.5">
                              <span className={`rounded-full px-2 py-1 text-[10px] font-bold ${style.badge}`}>{action.urgency === 'overdue' && overdueDays > 0 ? `逾期 ${overdueDays} 天` : style.label}</span>
                              <span className="rounded-full border border-slate-200 bg-white px-2 py-1 text-[10px] font-bold text-slate-600">{actionTypeLabel}</span>
                            </div>
                          </div>
                        </div>
                        {action.date && <span className="shrink-0 rounded-full bg-white/80 px-2 py-1 text-[10px] font-medium tabular-nums text-slate-500">{action.date}</span>}
                      </div>

                      <button type="button" onClick={() => openCustomer(action)} disabled={!action.customerId} className="mt-3 flex max-w-full items-center gap-1.5 text-left disabled:cursor-default">
                        <span className="truncate text-[16px] font-bold text-slate-950">{action.customerName}</span>
                        {action.customerId && <ArrowRight className="h-4 w-4 shrink-0 text-blue-600" />}
                      </button>
                      <p className="mt-1.5 line-clamp-2 text-[13px] font-medium leading-5 text-slate-700">{action.title}</p>

                      <div className="mt-3 flex items-center gap-2 rounded-2xl border border-white/80 bg-white/70 px-3 py-2.5">
                        <UserRound className={`h-4 w-4 shrink-0 ${missingOwner ? 'text-orange-600' : 'text-slate-500'}`} />
                        <div className="min-w-0 flex-1"><span className="block text-[9px] font-medium text-slate-400">负责人</span><span className={`block truncate text-xs font-semibold ${missingOwner ? 'text-orange-700' : 'text-slate-700'}`}>{ownerLabel}</span></div>
                        {missingOwner && <span className="shrink-0 rounded-full bg-orange-100 px-2 py-1 text-[9px] font-bold text-orange-700">待分配</span>}
                      </div>

                      <div className={`mt-3 grid gap-2 ${action.customerId ? 'grid-cols-[0.9fr_1.1fr]' : 'grid-cols-1'}`}>
                        {action.customerId && <Button className="min-h-12 rounded-2xl bg-white text-slate-700 shadow-sm hover:bg-slate-50" variant="outline" onClick={() => openCustomer(action)}><UserRound className="mr-1.5 h-4 w-4" />客户 360</Button>}
                        <Button className="min-h-12 rounded-2xl bg-blue-600 font-bold shadow-sm hover:bg-blue-700" onClick={() => openAction(action)}>{primaryActionLabel}</Button>
                      </div>
                    </div>
                  </div>

                  <div className="hidden gap-4 md:flex md:flex-col lg:flex-row lg:items-center">
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge className={style.badge}>{action.urgency === 'overdue' && overdueDays > 0 ? `逾期 ${overdueDays} 天` : style.label}</Badge>
                        <Badge variant="outline">{actionTypeLabel}</Badge>
                        {missingOwner && <Badge className="bg-orange-100 text-orange-800">缺少负责人</Badge>}
                        {action.date && <span className="text-xs text-slate-500">计划 {action.date}</span>}
                      </div>
                      <button type="button" onClick={() => openCustomer(action)} disabled={!action.customerId} className="mt-2 flex items-center gap-1 text-left font-semibold text-slate-900 hover:text-blue-700 disabled:cursor-default disabled:hover:text-slate-900">
                        {action.customerName}{action.customerId && <ArrowRight className="h-3.5 w-3.5" />}
                      </button>
                      <p className="mt-1 text-sm text-slate-700">{action.title}</p>
                      <p className="mt-1 text-xs text-slate-500">{action.description}</p>
                    </div>
                    <div className="flex shrink-0 flex-wrap gap-2">
                      {action.customerId && <Button size="sm" variant="outline" onClick={() => openCustomer(action)}><UserRound className="mr-1 h-3.5 w-3.5" />客户 360</Button>}
                      <Button size="sm" onClick={() => openAction(action)}>{primaryActionLabel}</Button>
                    </div>
                  </div>
                </CardContent>
              </Card>
            );
          })}
        </div>
      )}

      {visibleActions.length < filteredActions.length && (
        <div className="flex justify-center">
          <Button variant="outline" onClick={() => setVisibleCount(count => count + 30)}>
            继续显示（剩余 {filteredActions.length - visibleActions.length} 项）
          </Button>
        </div>
      )}

      <Dialog open={!!completeTarget} onOpenChange={open => { if (!open) setCompleteTarget(null); }}>
        <DialogContent>
          <DialogHeader><DialogTitle>{completeTarget?.kind === 'issue' ? '解决服务问题' : '完成任务'}</DialogTitle></DialogHeader>
          <div className="space-y-4">
            <div className="rounded-lg bg-slate-50 p-3"><p className="font-medium text-slate-900">{completeTarget?.customerName}</p><p className="mt-1 text-sm text-slate-600">{completeTarget?.title}</p></div>
            <div><p className="mb-2 text-sm font-medium text-slate-700">处理结果 *</p><Textarea rows={4} value={completionNote} onChange={event => setCompletionNote(event.target.value)} placeholder="写清楚做了什么、结果是什么、是否还需要下一步" /></div>
            <div className="flex justify-end gap-2"><Button variant="outline" onClick={() => setCompleteTarget(null)}>取消</Button><Button disabled={saving} onClick={() => void completeAction()}>{saving ? '保存中…' : '完成并记录'}</Button></div>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
