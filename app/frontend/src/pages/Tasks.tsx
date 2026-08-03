import { useState, useEffect, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import { client } from '../lib/api';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Textarea } from '@/components/ui/textarea';
import { toast } from 'sonner';
import { Plus, Search, CheckCircle2, Edit, Trash2 } from 'lucide-react';
import { NativeSelect } from '@/components/ui/native-select';
import ConfirmDialog from '@/components/ConfirmDialog';
import CustomerCombobox from '@/components/CustomerCombobox';
import EmployeeMultiSelect from '@/components/EmployeeMultiSelect';
import PageLoadState from '@/components/PageLoadState';
import { Combobox } from '@/components/ui/combobox';
import { useBusinessDicts } from '../lib/dict-config';
import { getLoadErrorMessage, loadWithRetry } from '../lib/load-utils';
import { useAutoRefresh } from '../lib/use-auto-refresh';

const priorityColors: Record<string, string> = {
  high: 'bg-red-100 text-red-700', medium: 'bg-amber-100 text-amber-700', low: 'bg-slate-100 text-slate-600',
};
const statusColors: Record<string, string> = {
  pending: 'bg-blue-100 text-blue-700', in_progress: 'bg-amber-100 text-amber-700',
  waiting_client: 'bg-purple-100 text-purple-700', internal_waiting: 'bg-orange-100 text-orange-700',
  completed: 'bg-green-100 text-green-700', delayed: 'bg-red-100 text-red-700', cancelled: 'bg-slate-100 text-slate-500',
};
const taskSourceLabels: Record<string, string> = {
  manual: '手动任务',
  customer: '客户跟进',
  deal: '成交交付',
  service: '服务运营',
  renewal: '续费提醒',
  finance: '财务协作',
  system: '系统提醒',
};
const taskSourceColors: Record<string, string> = {
  manual: 'bg-slate-100 text-slate-600',
  customer: 'bg-sky-100 text-sky-700',
  deal: 'bg-indigo-100 text-indigo-700',
  service: 'bg-emerald-100 text-emerald-700',
  renewal: 'bg-amber-100 text-amber-700',
  finance: 'bg-rose-100 text-rose-700',
  system: 'bg-violet-100 text-violet-700',
};
const quickFilterLabels: Record<string, string> = {
  all: '全部任务',
  today_due: '今日到期',
  overdue: '已逾期',
  waiting_client: '等待客户',
  stale: '3天未更新',
  high_priority: '高优先级',
  unassigned: '未分配',
};
const taskReminderMessages: Record<string, { title: string; description: string }> = {
  delayed_task: {
    title: '延期任务提醒',
    description: '这里已经自动筛选出延期任务，并尽量聚焦到工作台提醒里那一条。',
  },
};
const PAGE_SIZE_OPTIONS = [20, 50, 100];

const getLocalDateKey = (date = new Date()) => {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
};

const parseSafeDate = (value?: string) => {
  if (!value) return null;
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
};

const getTaskDateKey = (value?: string) => {
  const parsed = parseSafeDate(value);
  return parsed ? getLocalDateKey(parsed) : value?.slice(0, 10) || '';
};

const isClosedTask = (task: any) => ['completed', 'cancelled'].includes(task?.status);

const isDueTodayTask = (task: any) => {
  if (isClosedTask(task)) return false;
  return getTaskDateKey(task?.due_date) === getLocalDateKey();
};

const isOverdueTask = (task: any) => {
  if (isClosedTask(task) || !task?.due_date) return false;
  return getTaskDateKey(task.due_date) < getLocalDateKey();
};

const isWaitingClientTask = (task: any) => {
  const text = [task?.title, task?.notes, task?.status].filter(Boolean).join(' ');
  return task?.status === 'waiting_client' || /等待客户|客户资料|客户提交|等客户|待客户/.test(text);
};

const isStaleTask = (task: any) => {
  if (isClosedTask(task)) return false;
  const date = parseSafeDate(task?.updated_at || task?.created_at);
  if (!date) return false;
  return Date.now() - date.getTime() > 3 * 24 * 60 * 60 * 1000;
};

const getTaskSource = (task: any) => {
  if (task?.source_type && taskSourceLabels[task.source_type]) return task.source_type;
  const text = [task?.task_type, task?.title, task?.notes].filter(Boolean).join(' ').toLowerCase();
  if (/续费|到期|renew|subscription/.test(text)) return 'renewal';
  if (/收款|付款|财务|发票|欠款|收入|成本|stripe|payment|finance/.test(text)) return 'finance';
  if (/成交后|交付|对接|权限|开通|onboard|handoff/.test(text)) return 'deal';
  if (/运营|素材|发布|平台|google|facebook|instagram|yelp|tiktok|小红书|service/.test(text)) return 'service';
  if (/跟进|回访|联系|call|follow/.test(text)) return 'customer';
  if (/系统|提醒|自动|智能/.test(text)) return 'system';
  return 'manual';
};

const getCompletionSummary = (notes?: string) => {
  if (!notes) return '';
  const index = notes.lastIndexOf('完成结果');
  if (index < 0) return '';
  return notes.slice(index).split('\n')[0];
};

const parseEmployeeNames = (value?: string) => Array.from(new Set(
  String(value || '').split(/[,，]/).map(name => name.trim()).filter(Boolean),
));

const paginateList = <T,>(items: T[], page: number, pageSize: number) => {
  const total = items.length;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const safePage = Math.min(Math.max(page || 1, 1), totalPages);
  const offset = (safePage - 1) * pageSize;
  return {
    items: items.slice(offset, offset + pageSize),
    page: safePage,
    total,
    totalPages,
    start: total === 0 ? 0 : offset + 1,
    end: Math.min(offset + pageSize, total),
  };
};

export default function Tasks() {
  const {
    taskTypes: taskTypeLabels,
    taskPriorities: priorityLabels,
    taskStatuses: statusLabels,
  } = useBusinessDicts();
  const extendedStatusLabels = useMemo(() => ({
    ...statusLabels,
    waiting_client: '等待客户资料',
    internal_waiting: '等待内部协作',
    cancelled: '已取消',
  }), [statusLabels]);
  const [searchParams] = useSearchParams();
  const [tasks, setTasks] = useState<any[]>([]);
  const [customers, setCustomers] = useState<any[]>([]);
  const [employees, setEmployees] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [filterStatus, setFilterStatus] = useState('all');
  const [filterPriority, setFilterPriority] = useState('all');
  const [filterSource, setFilterSource] = useState('all');
  const [quickFilter, setQuickFilter] = useState('all');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [showForm, setShowForm] = useState(false);
  const [saving, setSaving] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<any>(null);
  const [deleting, setDeleting] = useState(false);
  const [completeTarget, setCompleteTarget] = useState<any>(null);
  const [completionNote, setCompletionNote] = useState('');
  const [completing, setCompleting] = useState(false);
  const [focusTaskId, setFocusTaskId] = useState<number | null>(null);
  const emptyTaskForm = {
    title: '', customer_id: '', assignee_name: '', collaborator_names: '',
    task_type: 'other', priority: 'medium', status: 'pending',
    due_date: '', notes: '', attachment_link: '',
  };
  const [form, setForm] = useState(emptyTaskForm);

  const activeEmployeeOptions = useMemo(() => employees
    .filter((item: any) => !item.status || ['active', 'probation'].includes(item.status))
    .map((item: any) => ({
      value: String(item.name || item.full_name || item.username || item.email || '').trim(),
      label: [item.name || item.full_name || item.username || item.email, item.employee_code, item.department].filter(Boolean).join(' · '),
    }))
    .filter((item: any) => item.value), [employees]);

  const assigneeOptions = useMemo(() => {
    if (!form.assignee_name || activeEmployeeOptions.some(item => item.value === form.assignee_name)) return activeEmployeeOptions;
    return [{ value: form.assignee_name, label: `${form.assignee_name}（历史负责人）` }, ...activeEmployeeOptions];
  }, [activeEmployeeOptions, form.assignee_name]);

  useEffect(() => { loadData(); }, []);

  useEffect(() => {
    const nextStatus = searchParams.get('status');
    if (nextStatus === 'all' || (nextStatus && extendedStatusLabels[nextStatus])) {
      setFilterStatus(nextStatus);
    }

    const nextPriority = searchParams.get('priority');
    if (nextPriority === 'all' || (nextPriority && priorityLabels[nextPriority])) {
      setFilterPriority(nextPriority);
    }

    const nextSearch = searchParams.get('search');
    if (nextSearch !== null) {
      setSearch(nextSearch);
    }

    const rawTaskId = Number(searchParams.get('task_id') || 0);
    setFocusTaskId(Number.isFinite(rawTaskId) && rawTaskId > 0 ? rawTaskId : null);
  }, [extendedStatusLabels, priorityLabels, searchParams]);

  const loadData = async () => {
    try {
      const [tRes, cRes, eRes] = await loadWithRetry(() => Promise.all([
        client.entities.tasks.query({ limit: 1000, sort: '-created_at' }),
        client.entities.customers.query({ limit: 1000 }),
        client.entities.employees.query({ limit: 50 }),
      ]));
      setTasks(tRes?.data?.items || []);
      setCustomers(cRes?.data?.items || []);
      setEmployees(eRes?.data?.items || []);
      setLoadError(null);
    } catch (err) {
      console.error(err);
      setLoadError(getLoadErrorMessage(err));
    }
    finally { setLoading(false); }
  };

  useAutoRefresh(loadData, {
    intervalMs: 30000,
    enabled: !showForm && !completeTarget,
  });

  const filtered = useMemo(() => tasks.filter(t => {
    const keyword = search.trim().toLowerCase();
    const searchText = [
      t.title,
      t.customer_name,
      t.assignee_name,
      t.collaborator_names,
      t.notes,
      taskTypeLabels[t.task_type],
      taskSourceLabels[getTaskSource(t)],
    ].filter(Boolean).join(' ').toLowerCase();
    const matchSearch = !keyword || searchText.includes(keyword);
    const matchStatus = filterStatus === 'all' || t.status === filterStatus;
    const matchPriority = filterPriority === 'all' || t.priority === filterPriority;
    const matchSource = filterSource === 'all' || getTaskSource(t) === filterSource;
    const matchQuick = quickFilter === 'all'
      || (quickFilter === 'today_due' && isDueTodayTask(t))
      || (quickFilter === 'overdue' && isOverdueTask(t))
      || (quickFilter === 'waiting_client' && isWaitingClientTask(t))
      || (quickFilter === 'stale' && isStaleTask(t))
      || (quickFilter === 'high_priority' && t.priority === 'high' && !isClosedTask(t))
      || (quickFilter === 'unassigned' && !isClosedTask(t) && !String(t.assignee_name || '').trim());
    return matchSearch && matchStatus && matchPriority && matchSource && matchQuick;
  }), [filterPriority, filterSource, filterStatus, quickFilter, search, taskTypeLabels, tasks]);
  const paginated = useMemo(() => paginateList(filtered, page, pageSize), [filtered, page, pageSize]);

  useEffect(() => {
    setPage(1);
  }, [search, filterStatus, filterPriority, filterSource, quickFilter, pageSize]);

  useEffect(() => {
    if (!focusTaskId) return;
    const index = filtered.findIndex(task => Number(task.id) === Number(focusTaskId));
    if (index >= 0) setPage(Math.floor(index / pageSize) + 1);
  }, [filtered, focusTaskId, pageSize]);

  const pendingCount = tasks.filter(t => t.status === 'pending').length;
  const inProgressCount = tasks.filter(t => t.status === 'in_progress').length;
  const completedCount = tasks.filter(t => t.status === 'completed').length;
  const openCount = tasks.filter(t => !isClosedTask(t)).length;
  const quickCards = useMemo(() => [
    { key: 'today_due', title: '今日到期', value: tasks.filter(isDueTodayTask).length, hint: '今天必须推进', color: 'border-blue-200 bg-blue-50 text-blue-700' },
    { key: 'overdue', title: '已逾期', value: tasks.filter(isOverdueTask).length, hint: '需要马上处理', color: 'border-red-200 bg-red-50 text-red-700' },
    { key: 'waiting_client', title: '等待客户', value: tasks.filter(isWaitingClientTask).length, hint: '卡在客户资料', color: 'border-purple-200 bg-purple-50 text-purple-700' },
    { key: 'stale', title: '3天未更新', value: tasks.filter(isStaleTask).length, hint: '可能无人跟进', color: 'border-amber-200 bg-amber-50 text-amber-700' },
    { key: 'high_priority', title: '高优先级未完', value: tasks.filter(t => t.priority === 'high' && !isClosedTask(t)).length, hint: '老板重点看', color: 'border-rose-200 bg-rose-50 text-rose-700' },
    { key: 'unassigned', title: '未分配', value: tasks.filter(t => !isClosedTask(t) && !String(t.assignee_name || '').trim()).length, hint: '需要安排负责人', color: 'border-slate-200 bg-slate-50 text-slate-700' },
  ], [tasks]);
  const workload = useMemo(() => {
    const counter = tasks.reduce<Record<string, number>>((acc, task) => {
      if (isClosedTask(task)) return acc;
      const name = String(task.assignee_name || '').trim() || '未分配';
      acc[name] = (acc[name] || 0) + 1;
      return acc;
    }, {});
    return Object.entries(counter)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 6);
  }, [tasks]);
  const activeReminder = searchParams.get('reminder') || '';
  const activeReminderMessage = taskReminderMessages[activeReminder];

  useEffect(() => {
    if (!focusTaskId) return;
    const timer = window.setTimeout(() => {
      document.getElementById(`task-row-${focusTaskId}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }, 120);
    return () => window.clearTimeout(timer);
  }, [paginated.page, filtered.length, focusTaskId]);

  const PaginationFooter = () => {
    if (paginated.total === 0) return null;
    return (
      <div className="flex flex-col gap-3 border-t border-slate-100 px-4 py-3 text-sm text-slate-500 sm:flex-row sm:items-center sm:justify-between">
        <div>
          显示 {paginated.start}-{paginated.end} 条 / 共 {paginated.total} 条
          {filtered.length !== tasks.length ? `（筛选自 ${tasks.length} 条）` : ''}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-slate-400">每页</span>
          <NativeSelect
            value={String(pageSize)}
            onChange={value => setPageSize(Number(value))}
            options={PAGE_SIZE_OPTIONS.map(size => ({ value: String(size), label: `${size} 条` }))}
            className="h-8 w-24 text-xs"
          />
          <Button size="sm" variant="outline" className="h-8" onClick={() => setPage(1)} disabled={paginated.page <= 1}>首页</Button>
          <Button size="sm" variant="outline" className="h-8" onClick={() => setPage(paginated.page - 1)} disabled={paginated.page <= 1}>上一页</Button>
          <span className="min-w-20 text-center text-xs text-slate-500">{paginated.page} / {paginated.totalPages} 页</span>
          <Button size="sm" variant="outline" className="h-8" onClick={() => setPage(paginated.page + 1)} disabled={paginated.page >= paginated.totalPages}>下一页</Button>
          <Button size="sm" variant="outline" className="h-8" onClick={() => setPage(paginated.totalPages)} disabled={paginated.page >= paginated.totalPages}>末页</Button>
        </div>
      </div>
    );
  };

  const openEditTask = (t: any) => {
    setForm({
      title: t.title || '',
      customer_id: t.customer_id ? String(t.customer_id) : '',
      assignee_name: t.assignee_name || '',
      collaborator_names: t.collaborator_names || '',
      task_type: t.task_type || 'other',
      priority: t.priority || 'medium',
      status: t.status || 'pending',
      due_date: t.due_date?.slice(0, 10) || '',
      notes: t.notes || '',
      attachment_link: t.attachment_link || '',
    });
    setEditingId(t.id);
    setShowForm(true);
  };

  const handleSave = async () => {
    if (!form.title) { toast.error('请填写任务名称'); return; }
    setSaving(true);
    try {
      const cust = customers.find(c => c.id === Number(form.customer_id));
      const now = new Date().toISOString();
      const payload = {
        title: form.title,
        customer_id: form.customer_id ? Number(form.customer_id) : null,
        customer_name: cust?.business_name || '',
        assignee_id: employees.find((item: any) => String(item.name || '').trim() === form.assignee_name)?.id || null,
        assignee_name: form.assignee_name,
        collaborator_names: parseEmployeeNames(form.collaborator_names).filter(name => name !== form.assignee_name).join(', '),
        task_type: form.task_type,
        priority: form.priority,
        status: form.status,
        due_date: form.due_date || null,
        notes: form.notes,
        attachment_link: form.attachment_link,
        updated_at: now,
      };
      if (editingId) {
        await client.entities.tasks.update({ id: String(editingId), data: payload });
        toast.success('任务已更新');
      } else {
        await client.entities.tasks.create({ data: { ...payload, created_at: now } });
        toast.success('任务已创建');
      }
      setShowForm(false);
      setEditingId(null);
      setForm(emptyTaskForm);
      loadData();
    } catch (err) { toast.error('保存失败'); console.error(err); }
    finally { setSaving(false); }
  };

  const handleDeleteTask = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await client.entities.tasks.delete({ id: String(deleteTarget.id) });
      toast.success('任务已删除');
      setDeleteTarget(null);
      loadData();
    } catch (err) { toast.error('删除失败'); console.error(err); }
    finally { setDeleting(false); }
  };

  const handleStatusChange = async (taskId: number, newStatus: string) => {
    try {
      await client.entities.tasks.update({ id: String(taskId), data: { status: newStatus, updated_at: new Date().toISOString() } });
      toast.success('状态已更新');
      loadData();
    } catch (err) { toast.error('更新失败'); console.error(err); }
  };

  const handleCompleteTask = async () => {
    if (!completeTarget) return;
    if (!completionNote.trim()) {
      toast.error('请填写完成结果，方便后续追踪');
      return;
    }
    setCompleting(true);
    try {
      const now = new Date();
      const stamp = now.toLocaleString('zh-CN', { hour12: false });
      const existingNotes = String(completeTarget.notes || '').trim();
      const nextNotes = [
        existingNotes,
        `完成结果（${stamp}）：${completionNote.trim()}`,
      ].filter(Boolean).join('\n\n');
      await client.entities.tasks.update({
        id: String(completeTarget.id),
        data: {
          status: 'completed',
          completion_result: completionNote.trim(),
          notes: nextNotes,
          updated_at: now.toISOString(),
        },
      });
      toast.success('任务已完成并记录结果');
      setCompleteTarget(null);
      setCompletionNote('');
      loadData();
    } catch (err) {
      toast.error('完成任务失败');
      console.error(err);
    } finally {
      setCompleting(false);
    }
  };

  if (loading && tasks.length === 0) {
    return <PageLoadState loading message="正在加载任务与协作信息…" />;
  }
  if (loadError && tasks.length === 0) {
    return <PageLoadState error={loadError} onRetry={() => { setLoading(true); void loadData(); }} />;
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold text-slate-800">任务协作</h2>
          <p className="text-sm text-slate-500">未完成 {openCount} · 待处理 {pendingCount} · 进行中 {inProgressCount} · 已完成 {completedCount}</p>
        </div>
        <Button onClick={() => { setForm(emptyTaskForm); setEditingId(null); setShowForm(true); }} className="bg-blue-600 hover:bg-blue-700">
          <Plus className="w-4 h-4 mr-1" /> 新建任务
        </Button>
      </div>

      {activeReminderMessage && (
        <Card className="border-blue-200 bg-blue-50">
          <CardContent className="p-3">
            <p className="text-sm font-medium text-blue-700">{activeReminderMessage.title}</p>
            <p className="text-xs text-blue-600 mt-1">{activeReminderMessage.description}</p>
          </CardContent>
        </Card>
      )}

      <Card className="border-slate-200 bg-gradient-to-br from-white to-slate-50">
        <CardContent className="p-4">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
            <div>
              <p className="text-sm font-semibold text-slate-800">老板卡点看板</p>
              <p className="mt-1 text-xs text-slate-500">点一个卡片，就能直接筛出需要处理的任务。</p>
            </div>
            {quickFilter !== 'all' && (
              <Button size="sm" variant="outline" onClick={() => setQuickFilter('all')}>
                清除筛选：{quickFilterLabels[quickFilter]}
              </Button>
            )}
          </div>
          <div className="mt-3 grid grid-cols-2 gap-2 md:grid-cols-3 xl:grid-cols-6">
            {quickCards.map(card => (
              <button
                key={card.key}
                type="button"
                onClick={() => setQuickFilter(quickFilter === card.key ? 'all' : card.key)}
                className={`rounded-xl border p-3 text-left transition hover:-translate-y-0.5 hover:shadow-sm ${card.color} ${quickFilter === card.key ? 'ring-2 ring-blue-300' : ''}`}
              >
                <div className="text-2xl font-semibold">{card.value}</div>
                <div className="mt-1 text-sm font-medium">{card.title}</div>
                <div className="mt-1 text-xs opacity-80">{card.hint}</div>
              </button>
            ))}
          </div>
          {workload.length > 0 && (
            <div className="mt-4 rounded-xl border border-slate-100 bg-white p-3">
              <p className="text-xs font-semibold text-slate-500">当前未完成任务分布</p>
              <div className="mt-2 flex flex-wrap gap-2">
                {workload.map(([name, count]) => (
                  <Badge key={name} className="bg-slate-100 text-slate-700">
                    {name} · {count}
                  </Badge>
                ))}
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Filters */}
      <Card className="border-slate-200">
        <CardContent className="p-3">
          <div className="flex flex-col sm:flex-row gap-3">
            <div className="relative flex-1">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
              <Input placeholder="搜索任务名称、客户、负责人..." value={search} onChange={e => setSearch(e.target.value)} className="pl-9" />
            </div>
            <NativeSelect
              value={filterStatus}
              onChange={setFilterStatus}
              className="w-[140px]"
              options={[{ value: 'all', label: '全部状态' }, ...Object.entries(extendedStatusLabels).map(([k, v]) => ({ value: k, label: v }))]}
            />
            <NativeSelect
              value={filterPriority}
              onChange={setFilterPriority}
              className="w-[140px]"
              options={[{ value: 'all', label: '全部优先级' }, ...Object.entries(priorityLabels).map(([k, v]) => ({ value: k, label: v }))]}
            />
            <NativeSelect
              value={filterSource}
              onChange={setFilterSource}
              className="w-[140px]"
              options={[{ value: 'all', label: '全部来源' }, ...Object.entries(taskSourceLabels).map(([k, v]) => ({ value: k, label: v }))]}
            />
          </div>
        </CardContent>
      </Card>

      {/* Task list */}
      <Card className="border-slate-200">
        <CardContent className="p-0">
          {loading ? (
            <div className="flex items-center justify-center py-12"><div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600" /></div>
          ) : filtered.length === 0 ? (
            <p className="text-center text-slate-400 py-12">暂无任务</p>
          ) : (
            <div className="divide-y divide-slate-100">
              {paginated.items.map(t => {
                const source = getTaskSource(t);
                const completed = isClosedTask(t);
                const overdue = isOverdueTask(t);
                const dueToday = isDueTodayTask(t);
                const waitingClient = isWaitingClientTask(t);
                const stale = isStaleTask(t);
                const completionSummary = t.completion_result || getCompletionSummary(t.notes);
                return (
                  <div
                    key={t.id}
                    id={`task-row-${t.id}`}
                    className={`p-4 transition-colors ${t.id === focusTaskId ? 'bg-blue-50 ring-1 ring-blue-200' : 'hover:bg-slate-50'}`}
                  >
                    <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                      <div className="flex-1">
                        <div className="mb-2 flex flex-wrap items-center gap-2">
                          <span className={`font-medium text-sm ${completed ? 'line-through text-slate-400' : 'text-slate-800'}`}>{t.title}</span>
                          <Badge className={`text-xs ${statusColors[t.status] || 'bg-slate-100 text-slate-600'}`}>{extendedStatusLabels[t.status] || t.status || '未设置'}</Badge>
                          <Badge className={`text-xs ${priorityColors[t.priority] || 'bg-slate-100 text-slate-600'}`}>{priorityLabels[t.priority] || t.priority || '普通'}</Badge>
                          <Badge className={`text-xs ${taskSourceColors[source] || taskSourceColors.manual}`}>来源: {taskSourceLabels[source]}</Badge>
                          {t.automation_issue_id && <Badge className="bg-violet-100 text-violet-700 text-xs">自动闭环</Badge>}
                          {overdue && <Badge className="bg-red-100 text-red-700 text-xs">逾期</Badge>}
                          {dueToday && <Badge className="bg-blue-100 text-blue-700 text-xs">今日到期</Badge>}
                          {waitingClient && <Badge className="bg-purple-100 text-purple-700 text-xs">等待客户</Badge>}
                          {stale && <Badge className="bg-amber-100 text-amber-700 text-xs">3天未更新</Badge>}
                        </div>
                        <div className="flex flex-wrap gap-3 text-xs text-slate-500">
                          {t.customer_name && <span>客户: {t.customer_name}</span>}
                          <span>负责: {t.assignee_name || '未分配'}</span>
                          {t.collaborator_names && <span>协作: {t.collaborator_names}</span>}
                          <span>类型: {taskTypeLabels[t.task_type] || t.task_type || '其他'}</span>
                          {t.due_date && <span className={overdue ? 'text-red-500 font-medium' : ''}>截止: {getTaskDateKey(t.due_date)}</span>}
                        </div>
                        {t.notes && <p className="mt-2 whitespace-pre-wrap text-xs text-slate-500">{t.notes}</p>}
                        {completionSummary && (
                          <p className="mt-2 rounded-lg bg-green-50 px-3 py-2 text-xs font-medium text-green-700">{completionSummary}</p>
                        )}
                        {t.attachment_link && (
                          <a className="mt-2 inline-block text-xs text-blue-600 hover:underline" href={t.attachment_link} target="_blank" rel="noreferrer">查看附件</a>
                        )}
                      </div>
                      <div className="flex flex-wrap gap-1 shrink-0 lg:justify-end">
                        {!completed && (
                          <Button size="sm" variant="outline" className="border-green-200 text-green-700 hover:bg-green-50 h-8 px-2" onClick={() => { setCompleteTarget(t); setCompletionNote(''); }}>
                            <CheckCircle2 className="w-4 h-4 mr-1" /> 完成
                          </Button>
                        )}
                        {t.status === 'pending' && (
                          <Button size="sm" variant="ghost" className="text-amber-600 hover:text-amber-700 hover:bg-amber-50 h-8 px-2 text-xs" onClick={() => handleStatusChange(t.id, 'in_progress')}>
                            开始
                          </Button>
                        )}
                        {!completed && t.status !== 'waiting_client' && (
                          <Button size="sm" variant="ghost" className="text-purple-600 hover:text-purple-700 hover:bg-purple-50 h-8 px-2 text-xs" onClick={() => handleStatusChange(t.id, 'waiting_client')}>
                            等客户
                          </Button>
                        )}
                        {t.status === 'waiting_client' && (
                          <Button size="sm" variant="ghost" className="text-blue-600 hover:text-blue-700 hover:bg-blue-50 h-8 px-2 text-xs" onClick={() => handleStatusChange(t.id, 'in_progress')}>
                            继续
                          </Button>
                        )}
                        <Button size="sm" variant="ghost" className="h-8 w-8 p-0 text-slate-400 hover:text-blue-600" onClick={() => openEditTask(t)}><Edit className="w-3.5 h-3.5" /></Button>
                        {!t.automation_issue_id && <Button size="sm" variant="ghost" className="h-8 w-8 p-0 text-slate-400 hover:text-red-600" onClick={() => setDeleteTarget(t)}><Trash2 className="w-3.5 h-3.5" /></Button>}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
          {filtered.length > 0 && <PaginationFooter />}
        </CardContent>
      </Card>

      <ConfirmDialog
        open={!!deleteTarget}
        onOpenChange={(v) => { if (!v) setDeleteTarget(null); }}
        title="确认删除任务"
        description={`确定要删除任务「${deleteTarget?.title}」吗？此操作不可撤销。`}
        onConfirm={handleDeleteTask}
        loading={deleting}
      />

      <Dialog open={!!completeTarget} onOpenChange={(v) => { if (!v) { setCompleteTarget(null); setCompletionNote(''); } }}>
        <DialogContent className="max-w-md">
          <DialogHeader><DialogTitle>完成任务</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <div className="rounded-lg bg-slate-50 px-3 py-2">
              <p className="text-sm font-medium text-slate-800">{completeTarget?.title}</p>
              {completeTarget?.customer_name && <p className="mt-1 text-xs text-slate-500">客户: {completeTarget.customer_name}</p>}
            </div>
            <div>
              <Label>完成结果 *</Label>
              <Textarea
                value={completionNote}
                onChange={e => setCompletionNote(e.target.value)}
                rows={4}
                placeholder="例如：已联系客户并确认资料齐全，下一步进入正式运营。"
              />
              <p className="mt-1 text-xs text-slate-400">这段结果会自动写入任务备注，后续监管可以直接查看。</p>
            </div>
          </div>
          <div className="mt-4 flex justify-end gap-2">
            <Button variant="outline" onClick={() => { setCompleteTarget(null); setCompletionNote(''); }}>取消</Button>
            <Button onClick={handleCompleteTask} disabled={completing} className="bg-green-600 hover:bg-green-700">
              {completing ? '提交中...' : '确认完成'}
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      {/* Add/Edit task dialog */}
      <Dialog open={showForm} onOpenChange={(v) => { setShowForm(v); if (!v) { setEditingId(null); setForm(emptyTaskForm); } }}>
        <DialogContent className="max-w-lg max-h-[85vh] overflow-y-auto">
          <DialogHeader><DialogTitle>{editingId ? '编辑任务' : '新建任务'}</DialogTitle></DialogHeader>
          <div className="space-y-4">
            <div><Label>任务名称 *</Label><Input value={form.title} onChange={e => setForm({ ...form, title: e.target.value })} /></div>
            <div>
              <Label>所属客户</Label>
              <CustomerCombobox
                customers={customers}
                value={form.customer_id}
                onValueChange={v => setForm({ ...form, customer_id: v })}
                placeholder="搜索客户编号、名称、联系人或电话（可选）"
                allowClear
              />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <Label>负责人</Label>
                <Combobox
                  options={assigneeOptions}
                  value={form.assignee_name}
                  onValueChange={value => setForm({
                    ...form,
                    assignee_name: value,
                    collaborator_names: parseEmployeeNames(form.collaborator_names).filter(name => name !== value).join(', '),
                  })}
                  placeholder="选择负责人"
                  searchPlaceholder="搜索员工姓名、编号或部门…"
                  emptyText="没有找到在职员工"
                />
              </div>
              <div>
                <Label>协作人</Label>
                <EmployeeMultiSelect
                  employees={employees.filter((item: any) => String(item.name || '').trim() !== form.assignee_name)}
                  value={parseEmployeeNames(form.collaborator_names)}
                  onValueChange={names => setForm({ ...form, collaborator_names: names.join(', ') })}
                />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <Label>任务类型</Label>
                <NativeSelect
                  value={form.task_type}
                  onChange={v => setForm({ ...form, task_type: v })}
                  options={Object.entries(taskTypeLabels).map(([k, v]) => ({ value: k, label: v }))}
                />
              </div>
              <div>
                <Label>优先级</Label>
                <NativeSelect
                  value={form.priority}
                  onChange={v => setForm({ ...form, priority: v })}
                  options={Object.entries(priorityLabels).map(([k, v]) => ({ value: k, label: v }))}
                />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <Label>任务状态</Label>
                <NativeSelect
                  value={form.status}
                  onChange={v => setForm({ ...form, status: v })}
                  options={Object.entries(extendedStatusLabels).map(([k, v]) => ({ value: k, label: v }))}
                />
              </div>
              <div><Label>截止日期</Label><Input type="date" value={form.due_date} onChange={e => setForm({ ...form, due_date: e.target.value })} /></div>
            </div>
            <p className="rounded-lg bg-blue-50 px-3 py-2 text-xs text-blue-700">任务来源会根据任务标题、类型和备注自动归类，例如成交交付、服务运营、财务协作、续费提醒。</p>
            <div><Label>备注</Label><Textarea value={form.notes} onChange={e => setForm({ ...form, notes: e.target.value })} rows={2} /></div>
            <div><Label>附件链接</Label><Input value={form.attachment_link} onChange={e => setForm({ ...form, attachment_link: e.target.value })} placeholder="https://..." /></div>
          </div>
          <div className="flex justify-end gap-2 mt-4">
            <Button variant="outline" onClick={() => setShowForm(false)}>取消</Button>
            <Button onClick={handleSave} disabled={saving} className="bg-blue-600 hover:bg-blue-700">{saving ? '保存中...' : '保存'}</Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
