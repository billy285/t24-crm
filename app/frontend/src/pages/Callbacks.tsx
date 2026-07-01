import { useState, useEffect, useMemo } from 'react';
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
import ExportButton from '@/components/ExportButton';
import { useBusinessDicts } from '../lib/dict-config';
import { useAutoRefresh } from '../lib/use-auto-refresh';

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
  const { role, employee, dataScope } = useRole();
  const {
    callbackTypes: callbackTypeLabels,
    callbackStatuses: callbackStatusLabels,
    callbackResults: resultLabels,
  } = useBusinessDicts();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [callbacks, setCallbacks] = useState<any[]>([]);
  const [customers, setCustomers] = useState<any[]>([]);
  const [employees, setEmployees] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [filterStatus, setFilterStatus] = useState('all');
  const [filterType, setFilterType] = useState('all');
  const [filterCustomerId, setFilterCustomerId] = useState('all');
  const [filterSchedule, setFilterSchedule] = useState('all');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [showForm, setShowForm] = useState(false);
  const [saving, setSaving] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<any>(null);
  const [deleting, setDeleting] = useState(false);

  const emptyForm = {
    customer_id: '',
    callback_date: new Date().toISOString().slice(0, 10),
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
    try {
      const [cbRes, cRes, eRes] = await Promise.all([
        client.apiCall.invoke({
          url: '/api/v1/entities/customer_callbacks',
          method: 'GET',
          data: { limit: 1000, sort: '-callback_date' },
        }),
        client.entities.customers.query({ limit: 1000 }),
        client.entities.employees.queryAll({ limit: 200 }),
      ]);
      let cbs = cbRes?.data?.items || [];
      const custs = cRes?.data?.items || [];
      const emps = eRes?.data?.items || [];

      // Filter by data scope
      if (dataScope === 'self' && employee) {
        cbs = cbs.filter((cb: any) => cb.employee_name === employee.name);
      }

      setCallbacks(cbs);
      setCustomers(custs);
      setEmployees(emps);
    } catch (err) {
      console.error('Failed to load callbacks:', err);
    } finally {
      setLoading(false);
    }
  };

  useAutoRefresh(loadData, {
    intervalMs: 30000,
    enabled: !showForm,
  });

  // Only show closed customers for callback
  const closedCustomers = useMemo(() =>
    customers.filter(c => c.status === 'closed'),
    [customers]
  );

  const customerMap = useMemo(() =>
    Object.fromEntries(customers.map(c => [c.id, c])),
    [customers]
  );

  // Filtered list
  const filtered = useMemo(() => {
    const today = new Date().toISOString().slice(0, 10);
    return callbacks.filter(cb => {
      const cust = customerMap[cb.customer_id];
      const matchSearch = !search ||
        cust?.business_name?.includes(search) ||
        cust?.contact_name?.includes(search) ||
        cb.content?.includes(search) ||
        cb.employee_name?.includes(search);
      const matchStatus = filterStatus === 'all' || cb.status === filterStatus;
      const matchType = filterType === 'all' || cb.callback_type === filterType;
      const matchCustomer = filterCustomerId === 'all' || String(cb.customer_id) === filterCustomerId;
      const callbackDate = cb.callback_date?.slice(0, 10) || '';
      const matchSchedule = filterSchedule === 'all'
        || (filterSchedule === 'today' && cb.status === 'pending' && callbackDate === today)
        || (filterSchedule === 'overdue' && cb.status === 'pending' && callbackDate < today);
      return matchSearch && matchStatus && matchType && matchCustomer && matchSchedule;
    });
  }, [callbacks, customerMap, search, filterStatus, filterType, filterCustomerId, filterSchedule]);
  const paginated = useMemo(() => paginateList(filtered, page, pageSize), [filtered, page, pageSize]);

  useEffect(() => {
    setPage(1);
  }, [search, filterStatus, filterType, filterCustomerId, filterSchedule, pageSize]);

  // Statistics
  const stats = useMemo(() => {
    const now = new Date();
    const today = now.toISOString().slice(0, 10);
    const todayCallbacks = callbacks.filter(cb => cb.callback_date?.slice(0, 10) === today);
    const pendingCount = callbacks.filter(cb => cb.status === 'pending').length;
    const completedCount = callbacks.filter(cb => cb.status === 'completed').length;
    const overdueCount = callbacks.filter(cb =>
      cb.status === 'pending' && cb.callback_date && cb.callback_date.slice(0, 10) < today
    ).length;
    const todayPending = todayCallbacks.filter(cb => cb.status === 'pending').length;
    return { pendingCount, completedCount, overdueCount, todayPending, total: callbacks.length };
  }, [callbacks]);

  const openEdit = (cb: any) => {
    setForm({
      customer_id: String(cb.customer_id || ''),
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

  const handleSave = async () => {
    if (!form.customer_id || !form.callback_date) {
      toast.error('请选择客户并填写回访日期');
      return;
    }
    setSaving(true);
    try {
      const payload: any = {
        customer_id: Number(form.customer_id),
        callback_date: form.callback_date ? new Date(form.callback_date).toISOString() : null,
        callback_type: form.callback_type,
        status: form.status,
        content: form.content,
        result: form.result || null,
        next_callback_date: form.next_callback_date ? new Date(form.next_callback_date).toISOString() : null,
        notes: form.notes || null,
      };

      if (editingId) {
        payload.updated_at = new Date().toISOString();
        await client.apiCall.invoke({
          url: `/api/v1/entities/customer_callbacks/${editingId}`,
          method: 'PUT',
          data: payload,
        });
        toast.success('回访记录已更新');
      } else {
        payload.employee_id = employee?.id || null;
        payload.employee_name = employee?.name || '';
        payload.created_at = new Date().toISOString();
        payload.updated_at = new Date().toISOString();
        await client.apiCall.invoke({
          url: '/api/v1/entities/customer_callbacks',
          method: 'POST',
          data: payload,
        });
        toast.success('回访记录已添加');
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
    if (!deleteTarget) return;
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
  const handleQuickComplete = async (cb: any) => {
    try {
      await client.apiCall.invoke({
        url: `/api/v1/entities/customer_callbacks/${cb.id}`,
        method: 'PUT',
        data: { status: 'completed', updated_at: new Date().toISOString() },
      });
      toast.success('已标记为完成');
      loadData();
    } catch (err) {
      toast.error('操作失败');
    }
  };

  // Quick no-answer action
  const handleQuickNoAnswer = async (cb: any) => {
    try {
      await client.apiCall.invoke({
        url: `/api/v1/entities/customer_callbacks/${cb.id}`,
        method: 'PUT',
        data: { status: 'no_answer', updated_at: new Date().toISOString() },
      });
      toast.success('已标记为未接通');
      loadData();
    } catch (err) {
      toast.error('操作失败');
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
      next_callback_date: cb.next_callback_date?.slice(0, 10) || '',
      notes: cb.notes || '',
      created_at: cb.created_at?.slice(0, 16) || '',
    };
  });

  const activeReminder = searchParams.get('reminder') || '';
  const activeReminderMessage = callbackReminderMessages[activeReminder];
  const customerFilterOptions = useMemo(() => [
    { value: 'all', label: '全部客户' },
    ...closedCustomers.map(c => ({ value: String(c.id), label: c.business_name })),
  ], [closedCustomers]);

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
          <Button size="sm" variant="outline" className="h-8" onClick={() => setPage(1)} disabled={paginated.page <= 1}>首页</Button>
          <Button size="sm" variant="outline" className="h-8" onClick={() => setPage(paginated.page - 1)} disabled={paginated.page <= 1}>上一页</Button>
          <span className="min-w-20 text-center text-xs text-slate-500">{paginated.page} / {paginated.totalPages} 页</span>
          <Button size="sm" variant="outline" className="h-8" onClick={() => setPage(paginated.page + 1)} disabled={paginated.page >= paginated.totalPages}>下一页</Button>
          <Button size="sm" variant="outline" className="h-8" onClick={() => setPage(paginated.totalPages)} disabled={paginated.page >= paginated.totalPages}>末页</Button>
        </div>
      </div>
    );
  };

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
        <h2 className="text-xl font-semibold text-slate-800 flex items-center gap-2">
          <PhoneCall className="w-5 h-5 text-blue-600" />
          电话回访
        </h2>
        <div className="flex gap-2">
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
              { key: 'employee_name', label: '回访人' },
              { key: 'next_callback_date', label: '下次回访日期' },
              { key: 'notes', label: '备注' },
              { key: 'created_at', label: '创建时间' },
            ]}
            filename={`电话回访_${new Date().toISOString().slice(0, 10)}`}
            sheetName="电话回访"
          />
          <Button
            onClick={() => { setForm(emptyForm); setEditingId(null); setShowForm(true); }}
            className="bg-blue-600 hover:bg-blue-700"
          >
            <Plus className="w-4 h-4 mr-1" /> 新增回访
          </Button>
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
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <Card className="border-slate-200">
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
            <p className="text-2xl font-bold text-red-700">{stats.overdueCount}</p>
          </CardContent>
        </Card>
        <Card className="border-blue-200 bg-blue-50">
          <CardContent className="p-3 text-center">
            <p className="text-xs text-blue-600">今日待办</p>
            <p className="text-2xl font-bold text-blue-700">{stats.todayPending}</p>
          </CardContent>
        </Card>
        <Card className="border-green-200 bg-green-50">
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
                .filter(cb => cb.status === 'pending' && cb.callback_date && cb.callback_date.slice(0, 10) < new Date().toISOString().slice(0, 10))
                .slice(0, 5)
                .map(cb => {
                  const cust = customerMap[cb.customer_id];
                  return (
                    <div key={cb.id} className="flex items-center justify-between text-xs text-red-600">
                      <span>
                        <button
                          className="text-red-700 font-medium hover:underline cursor-pointer"
                          onClick={() => goToCustomerDetail(cb.customer_id)}
                        >
                          {cust?.business_name || '未知客户'}
                        </button>
                        {' '}- 计划回访: {cb.callback_date?.slice(0, 10)}
                        {' '}({callbackTypeLabels[cb.callback_type] || cb.callback_type})
                      </span>
                      <div className="flex gap-1">
                        <Button size="sm" variant="ghost" className="h-5 px-1.5 text-xs text-green-700 hover:bg-green-100" onClick={() => handleQuickComplete(cb)}>
                          完成
                        </Button>
                        <Button size="sm" variant="ghost" className="h-5 px-1.5 text-xs text-red-700 hover:bg-red-100" onClick={() => handleQuickNoAnswer(cb)}>
                          未接
                        </Button>
                      </div>
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
          <div className="flex flex-col sm:flex-row gap-3">
            <div className="relative flex-1">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
              <Input
                placeholder="搜索客户名称、联系人、回访内容..."
                value={search}
                onChange={e => setSearch(e.target.value)}
                className="pl-9"
              />
            </div>
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
            <NativeSelect
              value={filterCustomerId}
              onChange={setFilterCustomerId}
              className="w-[180px]"
              options={customerFilterOptions}
            />
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
            <div className="divide-y divide-slate-100">
              {paginated.items.map(cb => {
                const cust = customerMap[cb.customer_id];
                const isOverdue = cb.status === 'pending' && cb.callback_date &&
                  cb.callback_date.slice(0, 10) < new Date().toISOString().slice(0, 10);
                const isToday = cb.callback_date?.slice(0, 10) === new Date().toISOString().slice(0, 10);

                return (
                  <div
                    key={cb.id}
                    className={`p-4 hover:bg-slate-50 transition-colors ${isOverdue ? 'bg-red-50/50' : isToday && cb.status === 'pending' ? 'bg-amber-50/30' : ''}`}
                  >
                    <div className="flex items-start justify-between mb-2">
                      <div className="flex items-center gap-2 flex-wrap">
                        <button
                          className="font-medium text-sm text-blue-600 hover:text-blue-800 hover:underline cursor-pointer flex items-center gap-1"
                          onClick={() => goToCustomerDetail(cb.customer_id)}
                          title="点击查看客户详情"
                        >
                          {cust?.business_name || `客户#${cb.customer_id}`}
                          <ExternalLink className="w-3 h-3 opacity-50" />
                        </button>
                        {cust?.phone && (
                          <a
                            href={`tel:${cust.phone}`}
                            className="text-xs text-slate-500 hover:text-blue-600 flex items-center gap-0.5"
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
                      <div className="flex items-center gap-2">
                        <Badge className={`text-xs flex items-center gap-1 ${callbackStatusColors[cb.status]}`}>
                          {callbackStatusIcons[cb.status]}
                          {callbackStatusLabels[cb.status] || cb.status}
                        </Badge>
                        <Badge variant="outline" className="text-xs">
                          {callbackTypeLabels[cb.callback_type] || cb.callback_type}
                        </Badge>
                        {cb.status === 'pending' && (
                          <>
                            <Button
                              size="sm"
                              variant="ghost"
                              className="h-6 px-1.5 text-xs text-green-600 hover:text-green-800 hover:bg-green-50"
                              onClick={() => handleQuickComplete(cb)}
                              title="标记完成"
                            >
                              <CheckCircle2 className="w-3.5 h-3.5" />
                            </Button>
                            <Button
                              size="sm"
                              variant="ghost"
                              className="h-6 px-1.5 text-xs text-orange-600 hover:text-orange-800 hover:bg-orange-50"
                              onClick={() => handleQuickNoAnswer(cb)}
                              title="未接通"
                            >
                              <PhoneOff className="w-3.5 h-3.5" />
                            </Button>
                          </>
                        )}
                        <Button
                          size="sm"
                          variant="ghost"
                          className="h-6 w-6 p-0 text-slate-400 hover:text-blue-600"
                          onClick={() => openEdit(cb)}
                        >
                          <Edit className="w-3 h-3" />
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          className="h-6 w-6 p-0 text-slate-400 hover:text-red-600"
                          onClick={() => setDeleteTarget(cb)}
                        >
                          <Trash2 className="w-3 h-3" />
                        </Button>
                      </div>
                    </div>
                    {cb.content && (
                      <p className="text-sm text-slate-700 mb-1">{cb.content}</p>
                    )}
                    <div className="flex flex-wrap gap-3 text-xs text-slate-500">
                      {cb.employee_name && <span>回访人: {cb.employee_name}</span>}
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
      <ConfirmDialog
        open={!!deleteTarget}
        onOpenChange={(v) => { if (!v) setDeleteTarget(null); }}
        title="确认删除回访记录"
        description="确定要删除此回访记录吗？此操作不可撤销。"
        onConfirm={handleDelete}
        loading={deleting}
      />

      {/* Add/Edit Dialog */}
      <Dialog open={showForm} onOpenChange={(v) => { setShowForm(v); if (!v) { setEditingId(null); setForm(emptyForm); } }}>
        <DialogContent className="max-w-lg max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{editingId ? '编辑回访记录' : '新增回访记录'}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div>
              <Label>选择客户（已成交） *</Label>
              <NativeSelect
                value={form.customer_id}
                onChange={v => setForm({ ...form, customer_id: v })}
                placeholder="请选择客户"
                options={[
                  { value: '', label: '请选择客户' },
                  ...(dataScope === 'self' && employee
                    ? closedCustomers.filter(c => c.sales_person === employee.name || c.sales_employee_id === employee.id)
                    : closedCustomers
                  ).map(c => ({
                    value: String(c.id),
                    label: `${c.business_name} - ${c.contact_name} (${c.phone || '-'})`,
                  })),
                ]}
              />
              {closedCustomers.length === 0 && (
                <p className="text-xs text-slate-400 mt-1">暂无已成交客户，请先在客户管理中将客户状态设为"已成交"</p>
              )}
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <Label>回访日期 *</Label>
                <Input
                  type="date"
                  value={form.callback_date}
                  onChange={e => setForm({ ...form, callback_date: e.target.value })}
                />
              </div>
              <div>
                <Label>回访类型</Label>
                <NativeSelect
                  value={form.callback_type}
                  onChange={v => setForm({ ...form, callback_type: v })}
                  options={Object.entries(callbackTypeLabels).map(([k, v]) => ({ value: k, label: v }))}
                />
              </div>
            </div>

            <div className="grid grid-cols-2 gap-4">
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
              <Label>回访内容</Label>
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
          <div className="flex justify-end gap-2 mt-4">
            <Button variant="outline" onClick={() => setShowForm(false)}>取消</Button>
            <Button
              onClick={handleSave}
              disabled={saving}
              className="bg-blue-600 hover:bg-blue-700"
            >
              {saving ? '保存中...' : '保存'}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
