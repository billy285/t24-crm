import { useState, useEffect, useMemo, useRef } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { client } from '../lib/api';
import { useRole } from '../lib/role-context';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Textarea } from '@/components/ui/textarea';
import { toast } from 'sonner';
import {
  Plus, Search, Edit, Trash2, ExternalLink, Phone, Clock,
  CheckCircle2, AlertCircle, CalendarClock, PhoneCall, PhoneOff,
  Filter
} from 'lucide-react';
import { NativeSelect } from '@/components/ui/native-select';
import ConfirmDialog from '@/components/ConfirmDialog';
import CustomerCombobox from '@/components/CustomerCombobox';
import ExportButton from '@/components/ExportButton';
import PageLoadState from '@/components/PageLoadState';
import { Combobox } from '@/components/ui/combobox';
import { useBusinessDicts } from '../lib/dict-config';
import { addBusinessDateDays, businessDateKey } from '../lib/business-date';
import { getLoadErrorMessage, loadWithRetry } from '../lib/load-utils';
import { useAutoRefresh } from '../lib/use-auto-refresh';
import { invokeWithAuth } from '../lib/tokenStore';

const callbackStatusColors: Record<string, string> = {
  pending: 'bg-amber-100 text-amber-700',
  completed: 'bg-green-100 text-green-700',
  no_answer: 'bg-red-100 text-red-700',
  rescheduled: 'bg-blue-100 text-blue-700',
  cancelled: 'bg-slate-100 text-slate-600',
};
const callbackStatusIcons: Record<string, React.ReactNode> = {
  pending: <Clock className="w-3.5 h-3.5" />,
  completed: <CheckCircle2 className="w-3.5 h-3.5" />,
  no_answer: <PhoneOff className="w-3.5 h-3.5" />,
  rescheduled: <CalendarClock className="w-3.5 h-3.5" />,
  cancelled: <AlertCircle className="w-3.5 h-3.5" />,
};
const callbackReminderMessages: Record<string, { title: string; description: string }> = {
  callback_today: {
    title: '今日回访提醒',
    description: '页面已自动切到今日待办，并定位到对应客户的待回访记录。',
  },
  callback_overdue: {
    title: '逾期回访提醒',
    description: '页面已自动切到逾期待处理记录，方便你直接补回访。',
  },
};
const PAGE_SIZE_OPTIONS = [20, 50, 100];

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

export default function Callbacks() {
  const { employee, dataScope, hasPermission, isAdmin } = useRole();
  const canCreateCallback = isAdmin || hasPermission('follow_up_create');
  const canEditCallback = isAdmin || hasPermission('follow_up_edit');
  const canDeleteCallback = isAdmin || hasPermission('follow_up_delete');
  const businessToday = businessDateKey();
  const {
    callbackTypes: callbackTypeLabels,
    callbackStatuses: callbackStatusLabels,
    callbackResults: resultLabels,
  } = useBusinessDicts();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [callbacks, setCallbacks] = useState<any[]>([]);
  const [tasks, setTasks] = useState<any[]>([]);
  const [customers, setCustomers] = useState<any[]>([]);
  const [employees, setEmployees] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [filterStatus, setFilterStatus] = useState('all');
  const [filterType, setFilterType] = useState('all');
  const [filterCustomerId, setFilterCustomerId] = useState('');
  const [filterEmployeeId, setFilterEmployeeId] = useState('all');
  const [filterSchedule, setFilterSchedule] = useState('all');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [showForm, setShowForm] = useState(false);
  const [saving, setSaving] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<any>(null);
  const [deleting, setDeleting] = useState(false);
  const loadRequestSeqRef = useRef(0);
  const quickNoAnswerInFlightRef = useRef<Set<number>>(new Set());
  const [quickNoAnswerBusyIds, setQuickNoAnswerBusyIds] = useState<Set<number>>(new Set());

  const emptyForm = {
    customer_id: '',
    employee_id: employee?.id ? String(employee.id) : '',
    callback_date: businessToday,
    callback_type: 'satisfaction',
    status: 'pending',
    content: '',
    result: '',
    next_callback_date: '',
    notes: '',
  };
  const [form, setForm] = useState(emptyForm);

  useEffect(() => { loadData(); }, []);

  useEffect(() => {
    const nextStatus = searchParams.get('status');
    if (nextStatus === 'all' || (nextStatus && callbackStatusLabels[nextStatus])) {
      setFilterStatus(nextStatus);
    }

    const nextType = searchParams.get('type');
    if (nextType === 'all' || (nextType && callbackTypeLabels[nextType])) {
      setFilterType(nextType);
    }

    const nextCustomerId = searchParams.get('customer_id');
    if (nextCustomerId) {
      setFilterCustomerId(nextCustomerId);
    }

    const nextSchedule = searchParams.get('schedule');
    if (nextSchedule === 'all' || nextSchedule === 'today' || nextSchedule === 'overdue') {
      setFilterSchedule(nextSchedule);
    }

    const nextSearch = searchParams.get('search');
    if (nextSearch !== null) {
      setSearch(nextSearch);
    }
  }, [callbackStatusLabels, callbackTypeLabels, searchParams]);

  const loadData = async () => {
    const requestSeq = ++loadRequestSeqRef.current;
    try {
      const [cbRes, cRes, eRes, tRes] = await loadWithRetry(() => Promise.all([
        client.apiCall.invoke({
          url: '/api/v1/entities/customer_callbacks',
          method: 'GET',
          data: { limit: 1000, sort: '-callback_date' },
        }),
        client.entities.customers.query({ limit: 1000 }),
        invokeWithAuth({
          url: '/api/v1/entities/employees/directory',
          method: 'GET',
          data: { limit: 200 },
        }),
        client.entities.tasks.query({ limit: 1000, sort: '-created_at' }),
      ]));
      let cbs = cbRes?.data?.items || [];
      const custs = cRes?.data?.items || [];
      const emps = eRes?.data?.items || [];

      // Filter by data scope
      if (dataScope === 'self' && employee) {
        cbs = cbs.filter((cb: any) => Number(cb.employee_id) === Number(employee.id) || cb.employee_name === employee.name);
      }

      if (requestSeq !== loadRequestSeqRef.current) return;
      setCallbacks(cbs);
      setCustomers(custs);
      setEmployees(emps);
      setTasks(tRes?.data?.items || []);
      setLoadError(null);
    } catch (err) {
      if (requestSeq !== loadRequestSeqRef.current) return;
      console.error('Failed to load callbacks:', err);
      setLoadError(getLoadErrorMessage(err));
    } finally {
      if (requestSeq === loadRequestSeqRef.current) setLoading(false);
    }
  };

  useEffect(() => () => {
    loadRequestSeqRef.current += 1;
  }, []);

  useAutoRefresh(loadData, {
    intervalMs: 30000,
    enabled: !showForm,
  });

  // Only show closed customers for callback
  const closedCustomers = useMemo(() =>
    customers.filter(c => c.status === 'closed'),
    [customers]
  );

  const selectableCustomers = useMemo(() => (
    dataScope === 'self' && employee
      ? closedCustomers.filter(c => c.sales_person === employee.name || Number(c.sales_employee_id) === Number(employee.id))
      : closedCustomers
  ), [closedCustomers, dataScope, employee]);

  const customerMap = useMemo(() =>
    Object.fromEntries(customers.map(c => [c.id, c])),
    [customers]
  );

  const activeEmployees = useMemo(() => employees.filter((item: any) => (
    (!item.status || ['active', 'probation'].includes(item.status))
    && (dataScope !== 'self' || !employee || Number(item.id) === Number(employee.id))
  )), [dataScope, employee, employees]);

  const employeeOptions = useMemo(() => activeEmployees.map((item: any) => ({
    value: String(item.id),
    label: [item.name, item.employee_code, item.department].filter(Boolean).join(' · '),
  })), [activeEmployees]);

  // Filtered list
  const filtered = useMemo(() => {
    return callbacks.filter(cb => {
      const cust = customerMap[cb.customer_id];
      const keyword = search.trim().toLowerCase();
      const matchSearch = !keyword || [
        cust?.customer_code,
        cust?.business_name,
        cust?.contact_name,
        cust?.phone,
        cb.content,
        cb.employee_name,
        cb.completed_by_employee_name,
      ].some(value => String(value || '').toLowerCase().includes(keyword));
      const matchStatus = filterStatus === 'all' || cb.status === filterStatus;
      const matchType = filterType === 'all' || cb.callback_type === filterType;
      const matchCustomer = !filterCustomerId || String(cb.customer_id) === filterCustomerId;
      const matchEmployee = filterEmployeeId === 'all' || String(cb.employee_id) === filterEmployeeId;
      const callbackDate = cb.callback_date?.slice(0, 10) || '';
      const matchSchedule = filterSchedule === 'all'
        || (filterSchedule === 'today' && cb.status === 'pending' && callbackDate === businessToday)
        || (filterSchedule === 'overdue' && cb.status === 'pending' && callbackDate < businessToday);
      return matchSearch && matchStatus && matchType && matchCustomer && matchEmployee && matchSchedule;
    });
  }, [businessToday, callbacks, customerMap, search, filterStatus, filterType, filterCustomerId, filterEmployeeId, filterSchedule]);
  const paginated = useMemo(() => paginateList(filtered, page, pageSize), [filtered, page, pageSize]);

  useEffect(() => {
    setPage(1);
  }, [search, filterStatus, filterType, filterCustomerId, filterEmployeeId, filterSchedule, pageSize]);

  // Statistics
  const stats = useMemo(() => {
    const todayCallbacks = callbacks.filter(cb => cb.callback_date?.slice(0, 10) === businessToday);
    const pendingCount = callbacks.filter(cb => cb.status === 'pending').length;
    const completedCount = callbacks.filter(cb => cb.status === 'completed').length;
    const overdueCount = callbacks.filter(cb =>
      cb.status === 'pending' && cb.callback_date && cb.callback_date.slice(0, 10) < businessToday
    ).length;
    const todayPending = todayCallbacks.filter(cb => cb.status === 'pending').length;
    return { pendingCount, completedCount, overdueCount, todayPending, total: callbacks.length };
  }, [businessToday, callbacks]);

  const openEdit = (cb: any) => {
    if (!canEditCallback) return;
    setForm({
      customer_id: String(cb.customer_id || ''),
      employee_id: String(cb.employee_id || employee?.id || ''),
      callback_date: cb.callback_date?.slice(0, 10) || '',
      callback_type: cb.callback_type || 'satisfaction',
      status: cb.status || 'pending',
      content: cb.content || '',
      result: cb.result || '',
      next_callback_date: cb.next_callback_date?.slice(0, 10) || '',
      notes: cb.notes || '',
    });
    setEditingId(cb.id);
    setShowForm(true);
  };

  const ensureFollowUpTask = async (callbackRecord: any, nextDate: string) => {
    if (!callbackRecord?.id || !['unsatisfied', 'need_followup'].includes(callbackRecord.result)) return;
    const marker = `来源：电话回访 #${callbackRecord.id}`;
    if (tasks.some((task: any) => String(task.notes || '').includes(marker) && task.status !== 'cancelled')) return;
    const customer = customerMap[callbackRecord.customer_id];
    await client.entities.tasks.create({
      data: {
        title: `回访跟进：${customer?.business_name || `客户 #${callbackRecord.customer_id}`}`,
        customer_id: callbackRecord.customer_id,
        customer_name: customer?.business_name || '',
        assignee_id: callbackRecord.employee_id || null,
        assignee_name: callbackRecord.employee_name || '',
        collaborator_names: '',
        task_type: 'follow_up',
        priority: callbackRecord.result === 'unsatisfied' ? 'high' : 'medium',
        status: 'pending',
        due_date: nextDate || addBusinessDateDays(businessToday, 1),
        notes: `${marker}\n回访结果：${resultLabels[callbackRecord.result] || callbackRecord.result}\n${callbackRecord.content || '需要继续跟进客户'}`,
        attachment_link: '',
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      },
    });
  };

  const ensureNextCallback = async (callbackRecord: any, nextDate: string) => {
    if (!callbackRecord?.id || !nextDate) return;
    const marker = `自动安排：来自回访 #${callbackRecord.id}`;
    if (callbacks.some((item: any) => String(item.notes || '').includes(marker))) return;
    await client.apiCall.invoke({
      url: '/api/v1/entities/customer_callbacks',
      method: 'POST',
      data: {
        customer_id: callbackRecord.customer_id,
        employee_id: callbackRecord.employee_id || null,
        employee_name: callbackRecord.employee_name || '',
        created_by_employee_id: employee?.id || null,
        created_by_employee_name: employee?.name || '',
        callback_date: new Date(nextDate).toISOString(),
        callback_type: callbackRecord.callback_type || 'satisfaction',
        status: 'pending',
        content: '',
        result: null,
        next_callback_date: null,
        notes: marker,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      },
    });
  };

  const handleSave = async () => {
    if (editingId ? !canEditCallback : !canCreateCallback) {
      toast.error('当前账号没有保存回访记录的权限');
      return;
    }
    if (!form.customer_id || !form.employee_id || !form.callback_date) {
      toast.error('请选择客户、回访负责人并填写回访日期');
      return;
    }
    if (form.status === 'completed' && (!form.result || !form.content.trim())) {
      toast.error('完成回访前，请填写回访结果和沟通内容');
      return;
    }
    if (['unsatisfied', 'need_followup'].includes(form.result) && !form.next_callback_date) {
      toast.error('客户不满意或需要跟进时，请安排下次回访日期');
      return;
    }
    if (form.status === 'rescheduled' && !form.next_callback_date) {
      toast.error('改期回访时，请填写下次回访日期');
      return;
    }
    setSaving(true);
    try {
      const now = new Date().toISOString();
      const responsibleEmployee = employees.find((item: any) => Number(item.id) === Number(form.employee_id));
      const nextCallbackDate = form.next_callback_date || (form.status === 'no_answer' ? addBusinessDateDays(businessToday, 1) : '');
      const payload: any = {
        customer_id: Number(form.customer_id),
        employee_id: Number(form.employee_id),
        employee_name: responsibleEmployee?.name || '',
        callback_date: form.callback_date ? new Date(form.callback_date).toISOString() : null,
        callback_type: form.callback_type,
        status: form.status,
        content: form.content,
        result: form.result || null,
        next_callback_date: nextCallbackDate ? new Date(nextCallbackDate).toISOString() : null,
        notes: form.notes || null,
        completed_by_employee_id: form.status === 'completed' ? employee?.id || null : null,
        completed_by_employee_name: form.status === 'completed' ? employee?.name || '' : null,
        completed_at: form.status === 'completed' ? now : null,
        updated_at: now,
      };

      let savedCallback: any = null;
      if (editingId) {
        const response = await client.apiCall.invoke({
          url: `/api/v1/entities/customer_callbacks/${editingId}`,
          method: 'PUT',
          data: payload,
        });
        savedCallback = response?.data;
        toast.success('回访记录已更新');
      } else {
        payload.created_by_employee_id = employee?.id || null;
        payload.created_by_employee_name = employee?.name || '';
        payload.created_at = now;
        const response = await client.apiCall.invoke({
          url: '/api/v1/entities/customer_callbacks',
          method: 'POST',
          data: payload,
        });
        savedCallback = response?.data;
        toast.success('回访记录已添加');
      }
      if (savedCallback) {
        await ensureFollowUpTask(savedCallback, nextCallbackDate);
        if (['no_answer', 'rescheduled'].includes(savedCallback.status)
          || ['unsatisfied', 'need_followup'].includes(savedCallback.result)) {
        if (canCreateCallback) await ensureNextCallback(savedCallback, nextCallbackDate);
        }
      }
      setShowForm(false);
      setEditingId(null);
      setForm(emptyForm);
      loadData();
    } catch (err) {
      toast.error('保存失败');
      console.error(err);
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!deleteTarget || !canDeleteCallback) return;
    setDeleting(true);
    try {
      await client.apiCall.invoke({
        url: `/api/v1/entities/customer_callbacks/${deleteTarget.id}`,
        method: 'DELETE',
      });
      toast.success('回访记录已删除');
      setDeleteTarget(null);
      loadData();
    } catch (err) {
      toast.error('删除失败');
      console.error(err);
    } finally {
      setDeleting(false);
    }
  };

  const goToCustomerDetail = (customerId: number) => {
    navigate(`/customers?detail=${customerId}`);
  };

  // Quick complete action
  const handleQuickComplete = (cb: any) => {
    openEdit({ ...cb, status: 'completed' });
  };

  // Quick no-answer action
  const handleQuickNoAnswer = async (cb: any) => {
    if (!canEditCallback) return;
    const callbackId = Number(cb.id);
    if (!callbackId || quickNoAnswerInFlightRef.current.has(callbackId)) return;
    quickNoAnswerInFlightRef.current.add(callbackId);
    setQuickNoAnswerBusyIds(current => new Set(current).add(callbackId));
    try {
      const nextDate = addBusinessDateDays(businessToday, 1);
      const response = await client.apiCall.invoke({
        url: `/api/v1/entities/customer_callbacks/${callbackId}`,
        method: 'PUT',
        data: {
          status: 'no_answer',
          next_callback_date: new Date(nextDate).toISOString(),
          updated_at: new Date().toISOString(),
        },
      });
      if (canCreateCallback) {
        await ensureNextCallback(response?.data || { ...cb, status: 'no_answer' }, nextDate);
      }
      toast.success('已标记为未接通，并自动安排明日回访');
      await loadData();
      setCallbacks(current => current.map(item => Number(item.id) === callbackId
        ? { ...item, status: 'no_answer', next_callback_date: new Date(nextDate).toISOString() }
        : item));
    } catch (err) {
      toast.error('操作失败');
    } finally {
      quickNoAnswerInFlightRef.current.delete(callbackId);
      setQuickNoAnswerBusyIds(current => {
        const next = new Set(current);
        next.delete(callbackId);
        return next;
      });
    }
  };

  // Export data
  const exportData = filtered.map(cb => {
    const cust = customerMap[cb.customer_id];
    return {
      customer_name: cust?.business_name || `客户#${cb.customer_id}`,
      contact_name: cust?.contact_name || '',
      phone: cust?.phone || '',
      callback_date: cb.callback_date?.slice(0, 10) || '',
      callback_type_label: callbackTypeLabels[cb.callback_type] || cb.callback_type,
      status_label: callbackStatusLabels[cb.status] || cb.status,
      content: cb.content || '',
      result_label: resultLabels[cb.result] || cb.result || '',
      employee_name: cb.employee_name || '',
      completed_by_employee_name: cb.completed_by_employee_name || '',
      next_callback_date: cb.next_callback_date?.slice(0, 10) || '',
      notes: cb.notes || '',
      created_at: cb.created_at?.slice(0, 16) || '',
    };
  });

  const activeReminder = searchParams.get('reminder') || '';
  const activeReminderMessage = callbackReminderMessages[activeReminder];
  const PaginationFooter = () => {
    if (paginated.total === 0) return null;
    return (
      <div className="flex flex-col gap-3 border-t border-slate-100 px-4 py-3 text-sm text-slate-500 sm:flex-row sm:items-center sm:justify-between">
        <div>
          显示 {paginated.start}-{paginated.end} 条 / 共 {paginated.total} 条
          {filtered.length !== callbacks.length ? `（筛选自 ${callbacks.length} 条）` : ''}
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

  if (loading && callbacks.length === 0) {
    return <PageLoadState loading message="正在加载电话回访记录…" />;
  }
  if (loadError && callbacks.length === 0) {
    return <PageLoadState error={loadError} onRetry={() => { setLoading(true); void loadData(); }} />;
  }

  return (
    <div className="t24-work-page app-page space-y-5">
      {/* Header */}
      <div className="app-page-title flex flex-col items-start justify-between gap-3 sm:flex-row sm:items-center">
        <div><p className="app-page-kicker">T24 Marketing · Customer Care</p><h2 className="app-page-heading flex items-center gap-2">
          <PhoneCall className="w-5 h-5 text-blue-600" />
          电话回访
        </h2><p className="app-page-description">集中处理今日、逾期和后续回访，完成后记录真实结果。</p></div>
        <div className="flex w-full gap-2 sm:w-auto">
          <div className="hidden sm:block">
            <ExportButton
              data={exportData}
              columns={[
              { key: 'customer_name', label: '客户名称' },
              { key: 'contact_name', label: '联系人' },
              { key: 'phone', label: '电话' },
              { key: 'callback_date', label: '回访日期' },
              { key: 'callback_type_label', label: '回访类型' },
              { key: 'status_label', label: '状态' },
              { key: 'content', label: '回访内容' },
              { key: 'result_label', label: '回访结果' },
              { key: 'employee_name', label: '回访负责人' },
              { key: 'completed_by_employee_name', label: '实际完成人' },
              { key: 'next_callback_date', label: '下次回访日期' },
              { key: 'notes', label: '备注' },
              { key: 'created_at', label: '创建时间' },
            ]}
              filename={`电话回访_${businessToday}`}
              sheetName="电话回访"
            />
          </div>
          {canCreateCallback && <Button
            onClick={() => {
              setForm({ ...emptyForm, employee_id: employee?.id ? String(employee.id) : '' });
              setEditingId(null);
              setShowForm(true);
            }}
            className="min-h-11 flex-1 bg-blue-600 hover:bg-blue-700 sm:flex-none md:min-h-0"
          >
            <Plus className="w-4 h-4 mr-1" /> 新增回访
          </Button>}
        </div>
      </div>

      {activeReminderMessage && (
        <Card className="border-blue-200 bg-blue-50">
          <CardContent className="p-3">
            <p className="text-sm font-medium text-blue-700">{activeReminderMessage.title}</p>
            <p className="text-xs text-blue-600 mt-1">{activeReminderMessage.description}</p>
          </CardContent>
        </Card>
      )}

      {/* Stats Cards */}
      <div className="grid grid-cols-3 gap-2 md:grid-cols-5 md:gap-3">
        <Card className="hidden border-slate-200 md:block">
          <CardContent className="p-3 text-center">
            <p className="text-xs text-slate-500">总回访</p>
            <p className="text-2xl font-bold text-slate-800">{stats.total}</p>
          </CardContent>
        </Card>
        <Card className="border-amber-200 bg-amber-50">
          <CardContent className="p-3 text-center">
            <p className="text-xs text-amber-600">待回访</p>
            <p className="text-2xl font-bold text-amber-700">{stats.pendingCount}</p>
          </CardContent>
        </Card>
        <Card className="border-red-200 bg-red-50">
          <CardContent className="p-3 text-center">
            <p className="text-xs text-red-600">已逾期</p>
            <p className="text-2xl font-bold text-red-700" data-testid="callback-overdue-count">{stats.overdueCount}</p>
          </CardContent>
        </Card>
        <Card className="border-blue-200 bg-blue-50">
          <CardContent className="p-3 text-center">
            <p className="text-xs text-blue-600">今日待办</p>
            <p className="text-2xl font-bold text-blue-700" data-testid="callback-today-count">{stats.todayPending}</p>
          </CardContent>
        </Card>
        <Card className="hidden border-green-200 bg-green-50 md:block">
          <CardContent className="p-3 text-center">
            <p className="text-xs text-green-600">已完成</p>
            <p className="text-2xl font-bold text-green-700">{stats.completedCount}</p>
          </CardContent>
        </Card>
      </div>

      {/* Overdue reminders */}
      {stats.overdueCount > 0 && (
        <Card className="border-red-200 bg-red-50">
          <CardContent className="p-3">
            <div className="flex items-center gap-2 text-red-700 mb-2">
              <AlertCircle className="w-4 h-4" />
              <span className="text-sm font-medium">逾期回访提醒 ({stats.overdueCount})</span>
            </div>
            <div className="space-y-1">
              {callbacks
                .filter(cb => cb.status === 'pending' && cb.callback_date && cb.callback_date.slice(0, 10) < businessToday)
                .slice(0, 5)
                .map(cb => {
                  const cust = customerMap[cb.customer_id];
                  return (
                    <div key={cb.id} className="flex flex-col gap-2 rounded-lg border border-red-100 bg-white/60 p-2 text-xs text-red-600 sm:flex-row sm:items-center sm:justify-between sm:border-0 sm:bg-transparent sm:p-0">
                      <span className="min-w-0">
                        <button
                          className="text-red-700 font-medium hover:underline cursor-pointer"
                          onClick={() => goToCustomerDetail(cb.customer_id)}
                        >
                          {cust?.business_name || '未知客户'}
                        </button>
                        {' '}- 计划回访: {cb.callback_date?.slice(0, 10)}
                        {' '}({callbackTypeLabels[cb.callback_type] || cb.callback_type})
                      </span>
                      {canEditCallback && <div className="grid grid-cols-2 gap-2 sm:flex sm:gap-1">
                        <Button size="sm" variant="ghost" className="min-h-11 px-3 text-xs text-green-700 hover:bg-green-100 md:h-7 md:min-h-0 md:px-2" onClick={() => handleQuickComplete(cb)}>
                          完成
                        </Button>
                        <Button size="sm" variant="ghost" className="min-h-11 px-3 text-xs text-red-700 hover:bg-red-100 md:h-7 md:min-h-0 md:px-2" disabled={quickNoAnswerBusyIds.has(Number(cb.id))} onClick={() => handleQuickNoAnswer(cb)}>
                          {quickNoAnswerBusyIds.has(Number(cb.id)) ? '处理中' : '未接'}
                        </Button>
                      </div>}
                    </div>
                  );
                })}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Filters */}
      <Card className="border-slate-200">
        <CardContent className="p-3">
          <div className="space-y-3">
            <div className="relative flex-1">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
              <Input
                placeholder="搜索客户名称、联系人、回访内容..."
                value={search}
                onChange={e => setSearch(e.target.value)}
                className="pl-9"
              />
            </div>
            <div className="hidden flex-wrap gap-3 md:flex">
            <NativeSelect
              value={filterStatus}
              onChange={setFilterStatus}
              className="w-[140px]"
              options={[
                { value: 'all', label: '全部状态' },
                ...Object.entries(callbackStatusLabels).map(([k, v]) => ({ value: k, label: v })),
              ]}
            />
            <NativeSelect
              value={filterType}
              onChange={setFilterType}
              className="w-[160px]"
              options={[
                { value: 'all', label: '全部类型' },
                ...Object.entries(callbackTypeLabels).map(([k, v]) => ({ value: k, label: v })),
              ]}
            />
            <NativeSelect
              value={filterSchedule}
              onChange={setFilterSchedule}
              className="w-[150px]"
              options={[
                { value: 'all', label: '全部时间' },
                { value: 'today', label: '今日待办' },
                { value: 'overdue', label: '已逾期' },
              ]}
            />
            <div className="w-full sm:w-[260px]">
              <CustomerCombobox
                customers={selectableCustomers}
                value={filterCustomerId}
                onValueChange={setFilterCustomerId}
                placeholder="搜索客户"
                allowClear
                clearLabel="全部客户"
              />
            </div>
            <NativeSelect
              value={filterEmployeeId}
              onChange={setFilterEmployeeId}
              className="w-[170px]"
              options={[{ value: 'all', label: '全部负责人' }, ...employeeOptions]}
            />
            </div>
            <details className="rounded-xl border border-slate-200 bg-white md:hidden">
              <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between px-3 text-sm font-semibold text-slate-700">筛选回访<span className="text-xs font-normal text-slate-400">状态 · 时间 · 客户</span></summary>
              <div className="grid gap-3 border-t border-slate-100 p-3">
                <NativeSelect value={filterStatus} onChange={setFilterStatus} options={[{ value: 'all', label: '全部状态' }, ...Object.entries(callbackStatusLabels).map(([k, v]) => ({ value: k, label: v }))]} />
                <NativeSelect value={filterType} onChange={setFilterType} options={[{ value: 'all', label: '全部类型' }, ...Object.entries(callbackTypeLabels).map(([k, v]) => ({ value: k, label: v }))]} />
                <NativeSelect value={filterSchedule} onChange={setFilterSchedule} options={[{ value: 'all', label: '全部时间' }, { value: 'today', label: '今日待办' }, { value: 'overdue', label: '已逾期' }]} />
                <CustomerCombobox customers={selectableCustomers} value={filterCustomerId} onValueChange={setFilterCustomerId} placeholder="搜索客户" allowClear clearLabel="全部客户" />
                <NativeSelect value={filterEmployeeId} onChange={setFilterEmployeeId} options={[{ value: 'all', label: '全部负责人' }, ...employeeOptions]} />
              </div>
            </details>
          </div>
        </CardContent>
      </Card>

      {/* Callback list */}
      <Card className="border-slate-200">
        <CardContent className="p-0">
          {loading ? (
            <div className="flex items-center justify-center py-12">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600" />
            </div>
          ) : filtered.length === 0 ? (
            <p className="text-center text-slate-400 py-12">暂无回访记录</p>
          ) : (
            <div className="grid gap-3 p-3 md:block md:divide-y md:divide-slate-100 md:p-0">
              {paginated.items.map(cb => {
                const cust = customerMap[cb.customer_id];
                const isOverdue = cb.status === 'pending' && cb.callback_date &&
                  cb.callback_date.slice(0, 10) < businessToday;
                const isToday = cb.callback_date?.slice(0, 10) === businessToday;

                return (
                  <div
                    key={cb.id}
                    className={`rounded-xl border p-4 transition-colors md:rounded-none md:border-0 ${isOverdue ? 'border-red-200 bg-red-50/50' : isToday && cb.status === 'pending' ? 'border-amber-200 bg-amber-50/30' : 'border-slate-200 bg-white hover:bg-slate-50'}`}
                  >
                    <div className="mb-2 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                      <div className="flex items-center gap-2 flex-wrap">
                        <button
                          className="flex min-h-11 items-center gap-1 text-sm font-medium text-blue-600 hover:text-blue-800 hover:underline md:min-h-0"
                          onClick={() => goToCustomerDetail(cb.customer_id)}
                          title="点击查看客户详情"
                        >
                          {cust?.business_name || `客户#${cb.customer_id}`}
                          <ExternalLink className="w-3 h-3 opacity-50" />
                        </button>
                        {cust?.phone && (
                          <a
                            href={`tel:${cust.phone}`}
                            className="flex min-h-11 items-center gap-1 text-xs text-slate-500 hover:text-blue-600 md:min-h-0"
                            title="点击拨打电话"
                          >
                            <Phone className="w-3 h-3" />
                            {cust.phone}
                          </a>
                        )}
                        <span className="text-xs text-slate-400">
                          {cb.callback_date?.slice(0, 10)}
                        </span>
                        {isOverdue && (
                          <Badge className="text-xs bg-red-100 text-red-700">逾期</Badge>
                        )}
                        {isToday && cb.status === 'pending' && (
                          <Badge className="text-xs bg-amber-100 text-amber-700">今日</Badge>
                        )}
                      </div>
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge className={`text-xs flex items-center gap-1 ${callbackStatusColors[cb.status]}`}>
                          {callbackStatusIcons[cb.status]}
                          {callbackStatusLabels[cb.status] || cb.status}
                        </Badge>
                        <Badge variant="outline" className="text-xs">
                          {callbackTypeLabels[cb.callback_type] || cb.callback_type}
                        </Badge>
                        {canEditCallback && cb.status === 'pending' && (
                          <>
                            <Button
                              size="sm"
                              variant="ghost"
                              className="h-11 min-w-11 px-2 text-xs text-green-600 hover:bg-green-50 hover:text-green-800 md:h-7 md:min-w-0 md:px-1.5"
                              onClick={() => handleQuickComplete(cb)}
                              title="标记完成"
                              aria-label={`完成回访：${cust?.business_name || `客户${cb.customer_id}`}`}
                            >
                              <CheckCircle2 className="w-3.5 h-3.5" />
                            </Button>
                            <Button
                              size="sm"
                              variant="ghost"
                              className="h-11 min-w-11 px-2 text-xs text-orange-600 hover:bg-orange-50 hover:text-orange-800 md:h-7 md:min-w-0 md:px-1.5"
                              disabled={quickNoAnswerBusyIds.has(Number(cb.id))}
                              onClick={() => handleQuickNoAnswer(cb)}
                              title="未接通"
                              aria-label={`标记未接：${cust?.business_name || `客户${cb.customer_id}`}`}
                            >
                              <PhoneOff className="w-3.5 h-3.5" />
                            </Button>
                          </>
                        )}
                        {canEditCallback && <Button
                          size="sm"
                          variant="ghost"
                          className="h-11 w-11 p-0 text-slate-500 hover:text-blue-600 md:h-7 md:w-7"
                          onClick={() => openEdit(cb)}
                          aria-label={`编辑回访：${cust?.business_name || `客户${cb.customer_id}`}`}
                        >
                          <Edit className="w-3 h-3" />
                        </Button>}
                        {canDeleteCallback && <Button
                          size="sm"
                          variant="ghost"
                          className="h-11 w-11 p-0 text-slate-500 hover:text-red-600 md:h-7 md:w-7"
                          onClick={() => setDeleteTarget(cb)}
                          aria-label={`删除回访：${cust?.business_name || `客户${cb.customer_id}`}`}
                        >
                          <Trash2 className="w-3 h-3" />
                        </Button>}
                      </div>
                    </div>
                    {cb.content && (
                      <p className="text-sm text-slate-700 mb-1">{cb.content}</p>
                    )}
                    <div className="flex flex-wrap gap-3 text-xs text-slate-500">
                      {cb.employee_name && <span>负责人: {cb.employee_name}</span>}
                      {cb.completed_by_employee_name && <span className="text-green-700">实际完成: {cb.completed_by_employee_name}</span>}
                      {cb.created_by_employee_name && <span>创建人: {cb.created_by_employee_name}</span>}
                      {cb.result && (
                        <span className="text-purple-600">
                          结果: {resultLabels[cb.result] || cb.result}
                        </span>
                      )}
                      {cb.next_callback_date && (
                        <span className="text-amber-600">
                          下次回访: {cb.next_callback_date.slice(0, 10)}
                        </span>
                      )}
                      {cb.notes && <span className="text-slate-400">备注: {cb.notes}</span>}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
          {filtered.length > 0 && <PaginationFooter />}
        </CardContent>
      </Card>

      {/* Delete Confirm */}
      {canDeleteCallback && <ConfirmDialog
        open={!!deleteTarget}
        onOpenChange={(v) => { if (!v) setDeleteTarget(null); }}
        title="确认删除回访记录"
        description="确定要删除此回访记录吗？此操作不可撤销。"
        onConfirm={handleDelete}
        loading={deleting}
      />}

      {/* Add/Edit Dialog */}
      {(canCreateCallback || canEditCallback) && <Dialog open={showForm} onOpenChange={(v) => { setShowForm(v); if (!v) { setEditingId(null); setForm(emptyForm); } }}>
        <DialogContent className="max-h-[calc(100dvh-1rem)] w-[calc(100vw-1rem)] max-w-lg overflow-y-auto sm:max-h-[85vh]">
          <DialogHeader>
            <DialogTitle>{editingId ? '编辑回访记录' : '新增回访记录'}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div>
              <Label>选择客户（已成交） *</Label>
              <CustomerCombobox
                customers={selectableCustomers}
                value={form.customer_id}
                onValueChange={v => setForm({ ...form, customer_id: v })}
                placeholder="请选择客户"
              />
              {closedCustomers.length === 0 && (
                <p className="text-xs text-slate-400 mt-1">暂无已成交客户，请先在客户管理中将客户状态设为"已成交"</p>
              )}
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <Label>回访负责人 *</Label>
                <Combobox
                  options={employeeOptions}
                  value={form.employee_id}
                  onValueChange={v => setForm({ ...form, employee_id: v })}
                  placeholder="选择负责员工"
                  searchPlaceholder="按姓名、编号或部门搜索"
                  emptyText="没有找到在职员工"
                  disabled={dataScope === 'self'}
                />
                <p className="mt-1 text-xs text-slate-400">负责人可分配；实际完成人按当前登录员工自动记录。</p>
              </div>
              <div>
                <Label>回访日期 *</Label>
                <Input
                  type="date"
                  data-testid="callback-date-input"
                  value={form.callback_date}
                  onChange={e => setForm({ ...form, callback_date: e.target.value })}
                />
              </div>
            </div>

            <div>
              <Label>回访类型</Label>
              <NativeSelect
                value={form.callback_type}
                onChange={v => setForm({ ...form, callback_type: v })}
                options={Object.entries(callbackTypeLabels).map(([k, v]) => ({ value: k, label: v }))}
              />
            </div>

            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div>
                <Label>状态</Label>
                <NativeSelect
                  value={form.status}
                  onChange={v => setForm({ ...form, status: v })}
                  options={Object.entries(callbackStatusLabels).map(([k, v]) => ({ value: k, label: v }))}
                />
              </div>
              <div>
                <Label>回访结果</Label>
                <NativeSelect
                  value={form.result}
                  onChange={v => setForm({ ...form, result: v })}
                  options={[
                    { value: '', label: '请选择结果' },
                    ...Object.entries(resultLabels).map(([k, v]) => ({ value: k, label: v })),
                  ]}
                />
              </div>
            </div>

            <div>
              <Label>回访内容{form.status === 'completed' ? ' *' : ''}</Label>
              <Textarea
                value={form.content}
                onChange={e => setForm({ ...form, content: e.target.value })}
                rows={3}
                placeholder="记录回访沟通的主要内容..."
              />
            </div>

            <div>
              <Label>下次回访日期</Label>
              <Input
                type="date"
                value={form.next_callback_date}
                onChange={e => setForm({ ...form, next_callback_date: e.target.value })}
              />
              <p className="mt-1 text-xs text-slate-400">
                未接通会自动安排明日回访；不满意或需跟进会同步生成任务，避免遗漏。
              </p>
            </div>

            <div>
              <Label>备注</Label>
              <Input
                value={form.notes}
                onChange={e => setForm({ ...form, notes: e.target.value })}
                placeholder="其他备注信息..."
              />
            </div>
          </div>
          <div className="sticky bottom-0 z-20 -mx-6 -mb-6 mt-4 flex gap-2 border-t border-slate-200 bg-white/95 px-6 py-4 backdrop-blur sm:static sm:m-0 sm:justify-end sm:border-0 sm:bg-transparent sm:p-0">
            <Button variant="outline" className="flex-1 sm:flex-none" onClick={() => setShowForm(false)}>取消</Button>
            <Button
              onClick={handleSave}
              disabled={saving}
              className="flex-1 bg-blue-600 hover:bg-blue-700 sm:flex-none"
            >
              {saving ? '保存中...' : '保存'}
            </Button>
          </div>
        </DialogContent>
      </Dialog>}
    </div>
  );
}
