import { useState, useEffect, useMemo, useCallback, useRef } from 'react';
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import { client } from '../lib/api';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Textarea } from '@/components/ui/textarea';
import { toast } from 'sonner';
import {
  Plus, Search, CheckCircle2, Edit, Trash2, ArrowLeft, Bot,
  ClipboardList, UserCheck, Users, ExternalLink,
} from 'lucide-react';
import { NativeSelect } from '@/components/ui/native-select';
import ConfirmDialog from '@/components/ConfirmDialog';
import CustomerCombobox from '@/components/CustomerCombobox';
import EmployeeMultiSelect from '@/components/EmployeeMultiSelect';
import PageLoadState from '@/components/PageLoadState';
import { Combobox } from '@/components/ui/combobox';
import { useBusinessDicts } from '../lib/dict-config';
import { getLoadErrorMessage, loadWithRetry } from '../lib/load-utils';
import { useAutoRefresh } from '../lib/use-auto-refresh';
import { useRole } from '../lib/role-context';
import { buildReturnLink, getReturnLabel, getSafeInternalPath } from '../lib/navigation-state';

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
const primaryViewLabels: Record<string, string> = {
  all: '全部任务',
  mine: '我的任务',
  system: '系统提醒',
  team: '团队待办',
  completed: '已完成',
};

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
  const { employee, hasPermission, dataScope, canAccess } = useRole();
  const location = useLocation();
  const navigate = useNavigate();
  const taskScope = dataScope === 'all'
    ? 'all'
    : (dataScope === 'department' || String(dataScope) === 'team')
      ? 'team'
      : 'self';
  const canViewAllTasks = taskScope === 'all';
  const canViewTeamTasks = taskScope === 'all' || taskScope === 'team';
  const canCreateTask = hasPermission('task_create');
  const canEditTask = hasPermission('task_edit');
  const canDeleteTask = hasPermission('task_delete');
  const canOpenCustomers = canAccess('/customers');
  const defaultPrimaryView = canViewAllTasks && !window.matchMedia('(max-width: 767px)').matches ? 'all' : 'mine';
  const safePrimaryView = useCallback((value?: string | null) => {
    if (!value || !primaryViewLabels[value]) return defaultPrimaryView;
    if (value === 'all' && !canViewAllTasks) return 'mine';
    if (value === 'team' && !canViewTeamTasks) return 'mine';
    return value;
  }, [canViewAllTasks, canViewTeamTasks, defaultPrimaryView]);
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
  const [searchParams, setSearchParams] = useSearchParams();
  const [tasks, setTasks] = useState<any[]>([]);
  const [customers, setCustomers] = useState<any[]>([]);
  const [employees, setEmployees] = useState<any[]>([]);
  const [formOptionsLoading, setFormOptionsLoading] = useState(false);
  const [formOptionsLoaded, setFormOptionsLoaded] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [search, setSearch] = useState(() => searchParams.get('search') || '');
  const [filterStatus, setFilterStatus] = useState(() => {
    const value = searchParams.get('status');
    return value === 'all' || (value && extendedStatusLabels[value]) ? value : 'all';
  });
  const [filterPriority, setFilterPriority] = useState(() => {
    const value = searchParams.get('priority');
    return value === 'all' || (value && priorityLabels[value]) ? value : 'all';
  });
  const [filterSource, setFilterSource] = useState(() => {
    const value = searchParams.get('source');
    return value === 'all' || (value && taskSourceLabels[value]) ? value : 'all';
  });
  const [quickFilter, setQuickFilter] = useState(() => {
    const value = searchParams.get('quick');
    return value && quickFilterLabels[value] ? value : 'all';
  });
  const [primaryView, setPrimaryView] = useState(() => (
    searchParams.get('source') === 'system'
      ? 'system'
      : safePrimaryView(searchParams.get('view'))
  ));
  const [page, setPage] = useState(() => {
    const value = Number(searchParams.get('page') || 1);
    return Number.isFinite(value) && value > 0 ? value : 1;
  });
  const [pageSize, setPageSize] = useState(() => {
    const value = Number(searchParams.get('pageSize') || 20);
    return PAGE_SIZE_OPTIONS.includes(value) ? value : 20;
  });
  const [showForm, setShowForm] = useState(false);
  const [saving, setSaving] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<any>(null);
  const [deleting, setDeleting] = useState(false);
  const [completeTarget, setCompleteTarget] = useState<any>(null);
  const [completionNote, setCompletionNote] = useState('');
  const [completing, setCompleting] = useState(false);
  const loadRequestSeqRef = useRef(0);
  const [focusTaskId, setFocusTaskId] = useState<number | null>(() => {
    const value = Number(searchParams.get('task_id') || 0);
    return Number.isFinite(value) && value > 0 ? value : null;
  });
  const emptyTaskForm = {
    title: '', customer_id: '', customer_name: '', assignee_name: '', collaborator_names: '',
    task_type: 'other', priority: 'medium', status: 'pending',
    due_date: '', notes: '', attachment_link: '',
  };
  const [form, setForm] = useState(emptyTaskForm);

  const scopedEmployees = useMemo(() => employees
    .filter((item: any) => !item.status || ['active', 'probation'].includes(item.status)), [employees]);

  const activeEmployeeOptions = useMemo(() => scopedEmployees
    .map((item: any) => ({
      value: String(item.name || item.full_name || item.username || item.email || '').trim(),
      label: [item.name || item.full_name || item.username || item.email, item.employee_code, item.department].filter(Boolean).join(' · '),
    }))
    .filter((item: any) => item.value), [scopedEmployees]);

  const assigneeOptions = useMemo(() => {
    if (!form.assignee_name || activeEmployeeOptions.some(item => item.value === form.assignee_name)) return activeEmployeeOptions;
    return [{ value: form.assignee_name, label: `${form.assignee_name}（历史负责人）` }, ...activeEmployeeOptions];
  }, [activeEmployeeOptions, form.assignee_name]);

  useEffect(() => { loadData(); }, []);

  useEffect(() => {
    const nextView = searchParams.get('view');
    const nextSource = searchParams.get('source');
    if (nextView && primaryViewLabels[nextView]) setPrimaryView(safePrimaryView(nextView));
    else if (nextSource === 'system') setPrimaryView('system');

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

    if (nextSource === 'all' || (nextSource && taskSourceLabels[nextSource])) {
      setFilterSource(nextSource);
    }

    const nextQuick = searchParams.get('quick');
    if (nextQuick && quickFilterLabels[nextQuick]) setQuickFilter(nextQuick);

    const nextPage = Number(searchParams.get('page') || 1);
    if (Number.isFinite(nextPage) && nextPage > 0) setPage(nextPage);

    const nextPageSize = Number(searchParams.get('pageSize') || 20);
    if (PAGE_SIZE_OPTIONS.includes(nextPageSize)) setPageSize(nextPageSize);

    const rawTaskId = Number(searchParams.get('task_id') || 0);
    setFocusTaskId(Number.isFinite(rawTaskId) && rawTaskId > 0 ? rawTaskId : null);
  }, [extendedStatusLabels, priorityLabels, safePrimaryView, searchParams]);

  useEffect(() => {
    const next = new URLSearchParams(searchParams);
    const setOrDelete = (key: string, value: string, emptyValue: string) => {
      if (!value || value === emptyValue) next.delete(key);
      else next.set(key, value);
    };
    setOrDelete('view', primaryView, defaultPrimaryView);
    setOrDelete('status', filterStatus, 'all');
    setOrDelete('priority', filterPriority, 'all');
    setOrDelete('source', filterSource, 'all');
    setOrDelete('quick', quickFilter, 'all');
    if (search.trim()) next.set('search', search.trim());
    else next.delete('search');
    if (page > 1) next.set('page', String(page));
    else next.delete('page');
    if (pageSize !== 20) next.set('pageSize', String(pageSize));
    else next.delete('pageSize');
    if (next.toString() !== searchParams.toString()) setSearchParams(next, { replace: true });
  }, [defaultPrimaryView, filterPriority, filterSource, filterStatus, page, pageSize, primaryView, quickFilter, search, searchParams, setSearchParams]);

  const loadData = async () => {
    const requestSeq = ++loadRequestSeqRef.current;
    try {
      const tRes = await loadWithRetry(() => client.entities.tasks.query({ limit: 1000, sort: '-created_at' }));
      if (requestSeq !== loadRequestSeqRef.current) return;
      setTasks(tRes?.data?.items || []);
      setLoadError(null);
    } catch (err) {
      if (requestSeq !== loadRequestSeqRef.current) return;
      console.error(err);
      setLoadError(getLoadErrorMessage(err));
    }
    finally {
      if (requestSeq === loadRequestSeqRef.current) setLoading(false);
    }
  };

  useEffect(() => () => {
    loadRequestSeqRef.current += 1;
  }, []);

  const loadTaskFormOptions = useCallback(async () => {
    if (formOptionsLoaded || formOptionsLoading) return;
    setFormOptionsLoading(true);
    try {
      const [assigneeResult, customerResult] = await Promise.allSettled([
        taskScope === 'self'
          ? Promise.resolve(null)
          : client.apiCall.invoke({ url: '/api/v1/entities/tasks/assignee-options', method: 'GET' }),
        canOpenCustomers
          ? client.entities.customers.query({ limit: 1000 })
          : Promise.resolve(null),
      ]);
      if (assigneeResult.status === 'fulfilled' && assigneeResult.value) {
        setEmployees(assigneeResult.value?.data?.items || []);
      }
      if (customerResult.status === 'fulfilled' && customerResult.value) {
        setCustomers(customerResult.value?.data?.items || []);
      }
      setFormOptionsLoaded(true);
    } catch (err) {
      console.error(err);
      toast.error('任务表单选项加载失败，请稍后重试');
    } finally {
      setFormOptionsLoading(false);
    }
  }, [canOpenCustomers, formOptionsLoaded, formOptionsLoading, taskScope]);

  useAutoRefresh(loadData, {
    intervalMs: 30000,
    enabled: !showForm && !completeTarget,
  });

  const filtered = useMemo(() => tasks.filter(t => {
    if (focusTaskId && Number(t.id) === Number(focusTaskId)) return true;
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
    const employeeName = String(employee?.name || '').trim();
    const collaborators = parseEmployeeNames(t.collaborator_names);
    const isMine = Boolean(employeeName) && (String(t.assignee_name || '').trim() === employeeName || collaborators.includes(employeeName));
    const source = getTaskSource(t);
    const matchPrimaryView = primaryView === 'all'
      || (primaryView === 'mine' && isMine && !isClosedTask(t))
      || (primaryView === 'system' && (source === 'system' || Boolean(t.automation_issue_id)) && !isClosedTask(t))
      || (primaryView === 'team' && !isClosedTask(t))
      || (primaryView === 'completed' && t.status === 'completed');
    const matchQuick = quickFilter === 'all'
      || (quickFilter === 'today_due' && isDueTodayTask(t))
      || (quickFilter === 'overdue' && isOverdueTask(t))
      || (quickFilter === 'waiting_client' && isWaitingClientTask(t))
      || (quickFilter === 'stale' && isStaleTask(t))
      || (quickFilter === 'high_priority' && t.priority === 'high' && !isClosedTask(t))
      || (quickFilter === 'unassigned' && !isClosedTask(t) && !String(t.assignee_name || '').trim());
    return matchSearch && matchStatus && matchPriority && matchSource && matchQuick && matchPrimaryView;
  }), [employee?.name, filterPriority, filterSource, filterStatus, focusTaskId, primaryView, quickFilter, search, taskTypeLabels, tasks]);
  const paginated = useMemo(() => paginateList(filtered, page, pageSize), [filtered, page, pageSize]);

  useEffect(() => {
    setPage(1);
  }, [search, filterStatus, filterPriority, filterSource, quickFilter, pageSize]);

  useEffect(() => {
    if (!focusTaskId) return;
    const index = filtered.findIndex(task => Number(task.id) === Number(focusTaskId));
    if (index >= 0) setPage(Math.floor(index / pageSize) + 1);
  }, [filtered, focusTaskId, pageSize]);

  const completedCount = tasks.filter(t => t.status === 'completed').length;
  const quickCards = useMemo(() => [
    { key: 'today_due', title: '今日到期', value: tasks.filter(isDueTodayTask).length, hint: '今天必须推进', color: 'border-blue-200 bg-blue-50 text-blue-700' },
    { key: 'overdue', title: '已逾期', value: tasks.filter(isOverdueTask).length, hint: '需要马上处理', color: 'border-red-200 bg-red-50 text-red-700' },
    { key: 'waiting_client', title: '等待客户', value: tasks.filter(isWaitingClientTask).length, hint: '卡在客户资料', color: 'border-purple-200 bg-purple-50 text-purple-700' },
    { key: 'stale', title: '3天未更新', value: tasks.filter(isStaleTask).length, hint: '可能无人跟进', color: 'border-amber-200 bg-amber-50 text-amber-700' },
    { key: 'high_priority', title: '高优先级未完', value: tasks.filter(t => t.priority === 'high' && !isClosedTask(t)).length, hint: '老板重点看', color: 'border-rose-200 bg-rose-50 text-rose-700' },
    { key: 'unassigned', title: '未分配', value: tasks.filter(t => !isClosedTask(t) && !String(t.assignee_name || '').trim()).length, hint: '需要安排负责人', color: 'border-slate-200 bg-slate-50 text-slate-700' },
  ], [tasks]);
  const primaryViews = useMemo(() => {
    const employeeName = String(employee?.name || '').trim();
    const mineCount = tasks.filter(task => {
      const collaborators = parseEmployeeNames(task.collaborator_names);
      return !isClosedTask(task) && Boolean(employeeName) && (
        String(task.assignee_name || '').trim() === employeeName || collaborators.includes(employeeName)
      );
    }).length;
    return [
      { key: 'all', label: '全部任务', count: tasks.length, hint: '所有状态与来源', icon: ClipboardList },
      { key: 'mine', label: '我的任务', count: mineCount, hint: employeeName ? `${employeeName} 负责或协作` : '登录员工负责或协作', icon: UserCheck },
      { key: 'system', label: '系统提醒', count: tasks.filter(task => (getTaskSource(task) === 'system' || task.automation_issue_id) && !isClosedTask(task)).length, hint: '自动扫描产生', icon: Bot },
      { key: 'team', label: '团队待办', count: tasks.filter(task => !isClosedTask(task)).length, hint: '全部未完成任务', icon: Users },
      { key: 'completed', label: '已完成', count: completedCount, hint: '查看处理结果', icon: CheckCircle2 },
    ].filter(view => (
      (view.key !== 'all' || canViewAllTasks)
      && (view.key !== 'team' || canViewTeamTasks)
    ));
  }, [canViewAllTasks, canViewTeamTasks, completedCount, employee?.name, tasks]);
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
  const returnTo = getSafeInternalPath(searchParams.get('returnTo'));
  const getCurrentTaskPath = (taskId?: number) => {
    const params = new URLSearchParams(location.search);
    if (taskId) params.set('task_id', String(taskId));
    const query = params.toString();
    return `${location.pathname}${query ? `?${query}` : ''}`;
  };

  const changePrimaryView = (nextView: string) => {
    setPrimaryView(nextView);
    setQuickFilter('all');
    setFocusTaskId(null);
    if (nextView === 'system') setFilterSource('system');
    else if (filterSource === 'system') setFilterSource('all');
  };

  const activateMobileFocus = (focus: 'mine' | 'today_due' | 'overdue') => {
    setFocusTaskId(null);
    setFilterSource('all');
    if (focus === 'mine') {
      setPrimaryView('mine');
      setQuickFilter('all');
      return;
    }
    setPrimaryView(canViewTeamTasks ? 'team' : 'mine');
    setQuickFilter(focus);
  };

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
          <Button size="sm" variant="outline" className="min-h-11 md:h-8 md:min-h-0" onClick={() => setPage(1)} disabled={paginated.page <= 1}>首页</Button>
          <Button size="sm" variant="outline" className="min-h-11 md:h-8 md:min-h-0" onClick={() => setPage(paginated.page - 1)} disabled={paginated.page <= 1}>上一页</Button>
          <span className="min-w-20 text-center text-xs text-slate-500">{paginated.page} / {paginated.totalPages} 页</span>
          <Button size="sm" variant="outline" className="min-h-11 md:h-8 md:min-h-0" onClick={() => setPage(paginated.page + 1)} disabled={paginated.page >= paginated.totalPages}>下一页</Button>
          <Button size="sm" variant="outline" className="min-h-11 md:h-8 md:min-h-0" onClick={() => setPage(paginated.totalPages)} disabled={paginated.page >= paginated.totalPages}>末页</Button>
        </div>
      </div>
    );
  };

  const openEditTask = (t: any) => {
    if (!canEditTask) return;
    setForm({
      title: t.title || '',
      customer_id: t.customer_id ? String(t.customer_id) : '',
      customer_name: t.customer_name || '',
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
    void loadTaskFormOptions();
  };

  const handleSave = async () => {
    if (editingId ? !canEditTask : !canCreateTask) {
      toast.error('当前账号没有此任务操作权限');
      return;
    }
    if (!form.title) { toast.error('请填写任务名称'); return; }
    setSaving(true);
    try {
      const cust = customers.find(c => c.id === Number(form.customer_id));
      const now = new Date().toISOString();
      const payload = {
        title: form.title,
        customer_id: form.customer_id ? Number(form.customer_id) : null,
        customer_name: cust?.business_name || form.customer_name || '',
        ...(taskScope === 'self' && editingId ? {} : {
          assignee_id: employees.find((item: any) => String(item.name || '').trim() === form.assignee_name)?.id || employee?.id || null,
          assignee_name: form.assignee_name || employee?.name || '',
          collaborator_names: parseEmployeeNames(form.collaborator_names).filter(name => name !== form.assignee_name).join(', '),
        }),
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
    if (!deleteTarget || !canDeleteTask) return;
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
    if (!canEditTask) return;
    try {
      await client.entities.tasks.update({ id: String(taskId), data: { status: newStatus, updated_at: new Date().toISOString() } });
      toast.success('状态已更新');
      loadData();
    } catch (err) { toast.error('更新失败'); console.error(err); }
  };

  const handleCompleteTask = async () => {
    if (!completeTarget || !canEditTask) return;
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
          {returnTo && (
            <Button variant="ghost" size="sm" className="-ml-3 mb-1 min-h-11 text-slate-600 md:h-8 md:min-h-0" onClick={() => navigate(returnTo)}>
              <ArrowLeft className="mr-1 h-4 w-4" />{getReturnLabel(returnTo)}
            </Button>
          )}
          <p className="app-page-kicker">T24 Marketing · Work</p>
          <h2 className="app-page-heading">任务协作</h2>
          <p className="app-page-description">选择工作视角后直接处理；完成任务必须填写结果，系统会继续追踪闭环。</p>
        </div>
        {canCreateTask && (
          <Button onClick={() => { setForm(emptyTaskForm); setEditingId(null); setShowForm(true); void loadTaskFormOptions(); }} className="bg-blue-600 hover:bg-blue-700">
            <Plus className="w-4 h-4 mr-1" /> 新建任务
          </Button>
        )}
      </div>

      {activeReminderMessage && (
        <Card className="border-blue-200 bg-blue-50">
          <CardContent className="p-3">
            <p className="text-sm font-medium text-blue-700">{activeReminderMessage.title}</p>
            <p className="text-xs text-blue-600 mt-1">{activeReminderMessage.description}</p>
          </CardContent>
        </Card>
      )}

      <Card className="border-slate-200 md:hidden">
        <CardContent className="p-3">
          <p className="mb-3 text-xs font-semibold text-slate-500">手机优先视角</p>
          <div className="grid grid-cols-3 gap-2" role="group" aria-label="手机任务重点">
            <button
              type="button"
              onClick={() => activateMobileFocus('mine')}
              className={`min-h-16 rounded-xl border px-2 py-2 text-left ${primaryView === 'mine' && quickFilter === 'all' ? 'border-blue-600 bg-blue-600 text-white' : 'border-slate-200 bg-white text-slate-700'}`}
            >
              <span className="block text-lg font-bold">{primaryViews.find(view => view.key === 'mine')?.count || 0}</span>
              <span className="text-xs font-semibold">我的</span>
            </button>
            <button
              type="button"
              onClick={() => activateMobileFocus('today_due')}
              className={`min-h-16 rounded-xl border px-2 py-2 text-left ${quickFilter === 'today_due' ? 'border-blue-600 bg-blue-600 text-white' : 'border-blue-200 bg-blue-50 text-blue-700'}`}
            >
              <span className="block text-lg font-bold">{quickCards.find(card => card.key === 'today_due')?.value || 0}</span>
              <span className="text-xs font-semibold">今日</span>
            </button>
            <button
              type="button"
              onClick={() => activateMobileFocus('overdue')}
              className={`min-h-16 rounded-xl border px-2 py-2 text-left ${quickFilter === 'overdue' ? 'border-red-600 bg-red-600 text-white' : 'border-red-200 bg-red-50 text-red-700'}`}
            >
              <span className="block text-lg font-bold">{quickCards.find(card => card.key === 'overdue')?.value || 0}</span>
              <span className="text-xs font-semibold">逾期</span>
            </button>
          </div>
        </CardContent>
      </Card>

      <Card className="hidden border-slate-200 md:block">
        <CardContent className="p-2">
          <div className="grid grid-cols-2 gap-2 md:grid-cols-5">
            {primaryViews.map(view => {
              const Icon = view.icon;
              const active = primaryView === view.key;
              return (
                <button key={view.key} type="button" onClick={() => changePrimaryView(view.key)} className={`rounded-lg border px-3 py-3 text-left transition ${active ? 'border-slate-900 bg-slate-900 text-white shadow-sm' : 'border-transparent text-slate-600 hover:border-slate-200 hover:bg-slate-50'}`}>
                  <div className="flex items-center justify-between gap-2"><Icon className="h-4 w-4" /><span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${active ? 'bg-white/15 text-white' : 'bg-slate-100 text-slate-600'}`}>{view.count}</span></div>
                  <p className="mt-2 text-sm font-semibold">{view.label}</p>
                  <p className="mt-0.5 truncate text-[11px] opacity-70">{view.hint}</p>
                </button>
              );
            })}
          </div>
        </CardContent>
      </Card>

      <Card className="hidden border-slate-200/90 bg-white md:block">
        <CardContent className="p-4">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
            <div>
              <p className="app-section-title">需要处理</p>
              <p className="app-section-description">点击一个问题类型，直接筛出对应任务。</p>
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
                className={`rounded-lg border p-3 text-left transition hover:shadow-sm ${card.color} ${quickFilter === card.key ? 'ring-2 ring-blue-300' : ''}`}
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
      <div className="app-toolbar">
          <div className="flex flex-col gap-3 md:flex-row">
            <div className="relative flex-1">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
              <Input placeholder="搜索任务名称、客户、负责人..." value={search} onChange={e => setSearch(e.target.value)} className="pl-9" />
            </div>
            <div className="hidden gap-3 md:flex">
              <NativeSelect value={filterStatus} onChange={setFilterStatus} className="w-[140px]" options={[{ value: 'all', label: '全部状态' }, ...Object.entries(extendedStatusLabels).map(([k, v]) => ({ value: k, label: v }))]} />
              <NativeSelect value={filterPriority} onChange={setFilterPriority} className="w-[140px]" options={[{ value: 'all', label: '全部优先级' }, ...Object.entries(priorityLabels).map(([k, v]) => ({ value: k, label: v }))]} />
              <NativeSelect value={filterSource} onChange={setFilterSource} className="w-[140px]" options={[{ value: 'all', label: '全部来源' }, ...Object.entries(taskSourceLabels).map(([k, v]) => ({ value: k, label: v }))]} />
            </div>
          </div>
          <details className="mt-3 rounded-xl border border-slate-200 bg-white md:hidden">
            <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between px-3 text-sm font-semibold text-slate-700">更多筛选<span className="text-xs font-normal text-slate-400">状态 · 优先级 · 来源</span></summary>
            <div className="grid gap-3 border-t border-slate-100 p-3">
              <NativeSelect value={filterStatus} onChange={setFilterStatus} options={[{ value: 'all', label: '全部状态' }, ...Object.entries(extendedStatusLabels).map(([k, v]) => ({ value: k, label: v }))]} />
              <NativeSelect value={filterPriority} onChange={setFilterPriority} options={[{ value: 'all', label: '全部优先级' }, ...Object.entries(priorityLabels).map(([k, v]) => ({ value: k, label: v }))]} />
              <NativeSelect value={filterSource} onChange={setFilterSource} options={[{ value: 'all', label: '全部来源' }, ...Object.entries(taskSourceLabels).map(([k, v]) => ({ value: k, label: v }))]} />
            </div>
          </details>
      </div>

      {/* Task list */}
      <Card className="border-slate-200">
        <CardContent className="p-0">
          {loading ? (
            <div className="flex items-center justify-center py-12"><div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600" /></div>
          ) : filtered.length === 0 ? (
            <div className="py-12 text-center"><p className="text-sm font-medium text-slate-500">当前视角下暂无任务</p><p className="mt-1 text-xs text-slate-400">可以切换任务分层或清除筛选条件。</p></div>
          ) : (
            <div className="grid gap-3 p-3 md:block md:divide-y md:divide-slate-100 md:p-0">
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
                    className={`rounded-xl border p-4 transition-colors md:rounded-none md:border-0 ${t.id === focusTaskId ? 'border-blue-200 bg-blue-50 ring-1 ring-blue-200' : 'border-slate-200 bg-white hover:bg-slate-50'}`}
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
                      <div className="grid shrink-0 grid-cols-2 gap-2 md:flex md:flex-wrap md:justify-end md:gap-1">
                        {canEditTask && t.status === 'pending' && (
                          <Button size="sm" className="min-h-11 w-full bg-blue-600 px-3 text-xs hover:bg-blue-700 md:h-8 md:min-h-0 md:w-auto" onClick={() => handleStatusChange(t.id, 'in_progress')}>
                            开始处理
                          </Button>
                        )}
                        {canEditTask && !completed && t.status !== 'pending' && (
                          <Button size="sm" className="min-h-11 w-full bg-green-600 px-3 text-xs hover:bg-green-700 md:h-8 md:min-h-0 md:w-auto" onClick={() => { setCompleteTarget(t); setCompletionNote(''); }}>
                            <CheckCircle2 className="mr-1 h-4 w-4" />完成并记录
                          </Button>
                        )}
                        {canEditTask && !completed && t.status !== 'waiting_client' && (
                          <Button size="sm" variant="ghost" className="min-h-11 w-full px-2 text-xs text-purple-600 hover:bg-purple-50 hover:text-purple-700 md:h-8 md:min-h-0 md:w-auto" onClick={() => handleStatusChange(t.id, 'waiting_client')}>
                            等客户
                          </Button>
                        )}
                        {canEditTask && t.status === 'waiting_client' && (
                          <Button size="sm" variant="ghost" className="min-h-11 w-full px-2 text-xs text-blue-600 hover:bg-blue-50 hover:text-blue-700 md:h-8 md:min-h-0 md:w-auto" onClick={() => handleStatusChange(t.id, 'in_progress')}>
                            继续
                          </Button>
                        )}
                        {canOpenCustomers && t.customer_id && (
                          <Button size="sm" variant="outline" className="min-h-11 w-full px-2 text-xs md:h-8 md:min-h-0 md:w-auto" onClick={() => navigate(buildReturnLink(`/customers?detail=${t.customer_id}`, getCurrentTaskPath(t.id), 'tasks'))}>
                            <ExternalLink className="mr-1 h-3.5 w-3.5" />打开客户
                          </Button>
                        )}
                        {canEditTask && <Button aria-label="编辑任务" title="编辑任务" size="sm" variant="ghost" className="min-h-11 w-full p-0 text-slate-500 hover:text-blue-600 md:h-8 md:min-h-0 md:w-8" onClick={() => openEditTask(t)}><Edit className="w-3.5 h-3.5" /><span className="md:hidden">编辑</span></Button>}
                        {canDeleteTask && !t.automation_issue_id && <Button aria-label="删除任务" title="删除任务" size="sm" variant="ghost" className="min-h-11 w-full p-0 text-slate-500 hover:text-red-600 md:h-8 md:min-h-0 md:w-8" onClick={() => setDeleteTarget(t)}><Trash2 className="w-3.5 h-3.5" /><span className="md:hidden">删除</span></Button>}
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

      {canDeleteTask && (
        <ConfirmDialog
          open={!!deleteTarget}
          onOpenChange={(v) => { if (!v) setDeleteTarget(null); }}
          title="确认删除任务"
          description={`确定要删除任务「${deleteTarget?.title}」吗？此操作不可撤销。`}
          onConfirm={handleDeleteTask}
          loading={deleting}
        />
      )}

      {canEditTask && <Dialog open={!!completeTarget} onOpenChange={(v) => { if (!v) { setCompleteTarget(null); setCompletionNote(''); } }}>
        <DialogContent className="max-w-md">
          <DialogHeader><DialogTitle>填写处理结果并完成</DialogTitle></DialogHeader>
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
              <p className="mt-1 text-xs text-slate-400">结果会写入任务记录；系统问题会据此继续追踪是否真正解决。</p>
            </div>
          </div>
          <div className="mt-4 flex gap-2 sm:justify-end">
            <Button variant="outline" className="flex-1 sm:flex-none" onClick={() => { setCompleteTarget(null); setCompletionNote(''); }}>取消</Button>
            <Button onClick={handleCompleteTask} disabled={completing} className="flex-1 bg-green-600 hover:bg-green-700 sm:flex-none">
              {completing ? '提交中...' : '确认完成'}
            </Button>
          </div>
        </DialogContent>
      </Dialog>}

      {/* Add/Edit task dialog */}
      {(canCreateTask || (canEditTask && editingId !== null)) && <Dialog open={showForm} onOpenChange={(v) => { setShowForm(v); if (!v) { setEditingId(null); setForm(emptyTaskForm); } }}>
        <DialogContent className="max-h-[calc(100dvh-1rem)] w-[calc(100vw-1rem)] max-w-lg overflow-y-auto sm:max-h-[85vh]">
          <DialogHeader><DialogTitle>{editingId ? '编辑任务' : '新建任务'}</DialogTitle></DialogHeader>
          <div className="space-y-4">
            <div><Label>任务名称 *</Label><Input value={form.title} onChange={e => setForm({ ...form, title: e.target.value })} /></div>
            <div>
              <Label>所属客户</Label>
              {canOpenCustomers ? (
                <CustomerCombobox
                  customers={customers}
                  value={form.customer_id}
                  onValueChange={v => setForm({ ...form, customer_id: v })}
                  placeholder={formOptionsLoading ? '正在加载可选客户…' : '搜索客户编号、名称、联系人或电话（可选）'}
                  allowClear
                />
              ) : (
                <Input value={form.customer_name || '未关联客户'} disabled aria-label="当前关联客户" />
              )}
            </div>
            {taskScope === 'self' ? (
              <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600">
                负责人：{form.assignee_name || employee?.name || '当前账号'}
                {form.collaborator_names && <span className="ml-3">协作：{form.collaborator_names}</span>}
                <p className="mt-1 text-slate-400">仅自己范围的账号不能变更任务归属。</p>
              </div>
            ) : (
              <div className="grid gap-4 sm:grid-cols-2">
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
                    placeholder={formOptionsLoading ? '正在加载负责人…' : '选择负责人'}
                    searchPlaceholder="搜索员工姓名或部门…"
                    emptyText="没有找到范围内的在职员工"
                    disabled={formOptionsLoading}
                  />
                </div>
                <div>
                  <Label>协作人</Label>
                  {formOptionsLoading ? (
                    <div className="flex min-h-11 items-center rounded-md border border-slate-200 px-3 text-sm text-slate-400">正在加载协作人…</div>
                  ) : (
                    <EmployeeMultiSelect
                      employees={scopedEmployees.filter((item: any) => String(item.name || '').trim() !== form.assignee_name)}
                      value={parseEmployeeNames(form.collaborator_names)}
                      onValueChange={names => setForm({ ...form, collaborator_names: names.join(', ') })}
                    />
                  )}
                </div>
              </div>
            )}
            <div className="grid gap-4 sm:grid-cols-2">
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
            <div className="grid gap-4 sm:grid-cols-2">
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
          <div className="sticky bottom-0 z-20 -mx-6 -mb-6 mt-4 flex gap-2 border-t border-slate-200 bg-white/95 px-6 py-4 backdrop-blur sm:static sm:m-0 sm:justify-end sm:border-0 sm:bg-transparent sm:p-0">
            <Button variant="outline" className="flex-1 sm:flex-none" onClick={() => setShowForm(false)}>取消</Button>
            <Button onClick={handleSave} disabled={saving} className="flex-1 bg-blue-600 hover:bg-blue-700 sm:flex-none">{saving ? '保存中...' : '保存'}</Button>
          </div>
        </DialogContent>
      </Dialog>}
    </div>
  );
}
