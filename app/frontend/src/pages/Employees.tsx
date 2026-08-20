import { useState, useEffect, useMemo } from 'react';
import { client } from '../lib/api';
import { invokeWithAuth } from '../lib/tokenStore';
import { useRole, roleLabels, empStatusLabels, empStatusColors, departmentLabels, positionLabels } from '../lib/role-context';
import { systemRoleLabels } from '../lib/permissions';
import { actionTypeLabels, logOperation } from '../lib/operation-log-helper';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Textarea } from '@/components/ui/textarea';
import { toast } from 'sonner';
import { Plus, Edit, Search, ArrowLeft, ShieldCheck, ShieldOff, UserX, ArrowRightLeft, Phone, Mail, KeyRound, Calendar, Trash2, MoreHorizontal, AlertTriangle, RefreshCw, ChevronRight, MonitorSmartphone } from 'lucide-react';
import { NativeSelect } from '@/components/ui/native-select';
import ConfirmDialog from '@/components/ConfirmDialog';
import { useBusinessDicts } from '../lib/dict-config';
import { useAutoRefresh } from '../lib/use-auto-refresh';
import { getLoadErrorMessage } from '../lib/load-utils';
import { useIsMobile } from '@/hooks/use-mobile';

const allRoleOptions = Object.entries(systemRoleLabels).map(([k, v]) => ({ value: k, label: v }));
const PAGE_SIZE_OPTIONS = [20, 50, 100];

function paginateList<T>(items: T[], page: number, pageSize: number) {
  const totalPages = Math.max(1, Math.ceil(items.length / pageSize));
  const safePage = Math.min(Math.max(page, 1), totalPages);
  const start = (safePage - 1) * pageSize;
  return {
    items: items.slice(start, start + pageSize),
    page: safePage,
    totalPages,
    total: items.length,
    start: items.length === 0 ? 0 : start + 1,
    end: Math.min(start + pageSize, items.length),
  };
}

const emptyForm = {
  name: '', role: 'sales', phone: '', email: '', status: 'active',
  department: 'sales', position: 'specialist', employee_code: '', notes: '',
  login_username: '', hire_date: '', supervisor: '',
  initial_password: '',
};

export default function Employees() {
  const { isAdmin, employee: currentEmp, hasPermission } = useRole();
  const isMobile = useIsMobile();
  const { statuses: statusLabels, taskStatuses: taskStatusLabels } = useBusinessDicts();
  const [employees, setEmployees] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [filterStatus, setFilterStatus] = useState('all');
  const [filterRole, setFilterRole] = useState('all');
  const [filterDept, setFilterDept] = useState('all');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [form, setForm] = useState(emptyForm);
  const [saving, setSaving] = useState(false);
  const [selectedEmp, setSelectedEmp] = useState<any>(null);
  const [empCustomers, setEmpCustomers] = useState<any[]>([]);
  const [empTasks, setEmpTasks] = useState<any[]>([]);
  const [empLogs, setEmpLogs] = useState<any[]>([]);
  const [empDeals, setEmpDeals] = useState<any[]>([]);

  const [showTransfer, setShowTransfer] = useState(false);
  const [transferFrom, setTransferFrom] = useState<any>(null);
  const [transferTo, setTransferTo] = useState('');
  const [transferring, setTransferring] = useState(false);

  const [resignTarget, setResignTarget] = useState<any>(null);
  const [resigning, setResigning] = useState(false);

  const [resetPwdTarget, setResetPwdTarget] = useState<any>(null);
  const [newPassword, setNewPassword] = useState('');
  const [resettingPassword, setResettingPassword] = useState(false);

  const [deleteTarget, setDeleteTarget] = useState<any>(null);
  const [deleting, setDeleting] = useState(false);
  const [disableTarget, setDisableTarget] = useState<any>(null);
  const [statusUpdating, setStatusUpdating] = useState(false);

  useEffect(() => { loadEmployees(); }, []);

  const loadEmployees = async () => {
    try {
      const res = await client.entities.employees.queryAll({ limit: 1000, sort: '-created_at' });
      setEmployees(res?.data?.items || []);
      setLoadError(null);
    } catch (err) {
      console.error(err);
      setLoadError(getLoadErrorMessage(err));
    }
    finally { setLoading(false); }
  };

  useAutoRefresh(loadEmployees, {
    intervalMs: 30000,
    enabled: !showForm && !showTransfer && !resetPwdTarget,
  });

  const filtered = useMemo(() => {
    return employees.filter(e => {
      const ms = !search || [e.name, e.phone, e.email, e.employee_code, e.department, e.position, e.login_username].some(f => (f || '').toLowerCase().includes(search.toLowerCase()));
      const mst = filterStatus === 'all' || e.status === filterStatus;
      const mr = filterRole === 'all' || e.role === filterRole;
      const md = filterDept === 'all' || e.department === filterDept;
      return ms && mst && mr && md;
    });
  }, [employees, search, filterStatus, filterRole, filterDept]);

  const paginated = useMemo(() => paginateList(filtered, page, pageSize), [filtered, page, pageSize]);

  useEffect(() => {
    setPage(1);
  }, [search, filterStatus, filterRole, filterDept, pageSize]);

  const activeEmployees = employees.filter(e => e.status === 'active' || e.status === 'probation');

  const openCreate = () => { setForm(emptyForm); setEditingId(null); setShowForm(true); };
  const openEdit = (e: any) => {
    setForm({
      name: e.name || '', role: e.role || 'sales', phone: e.phone || '', email: e.email || '',
      status: e.status || 'active', department: e.department || 'sales', position: e.position || 'specialist',
      employee_code: e.employee_code || '', notes: e.notes || '',
      login_username: e.login_username || '', hire_date: e.hire_date || '', supervisor: e.supervisor || '',
      initial_password: '',
    });
    setEditingId(e.id); setShowForm(true);
  };

  const handleSave = async () => {
    if (!form.name || !form.role) { toast.error('请填写姓名和角色'); return; }
    if (form.initial_password && form.initial_password.length < 8) {
      toast.error('初始密码至少需要8个字符');
      return;
    }
    if (form.email && employees.some(emp => emp.id !== editingId && (emp.email || '').trim().toLowerCase() === form.email.trim().toLowerCase())) {
      toast.error('该邮箱已被其他员工使用');
      return;
    }
    if (form.login_username && employees.some(emp => emp.id !== editingId && (emp.login_username || '').trim().toLowerCase() === form.login_username.trim().toLowerCase())) {
      toast.error('该登录用户名已存在');
      return;
    }
    setSaving(true);
    try {
      const now = new Date().toISOString();
      const op = currentEmp?.name || '管理员';
      const normalizedUserId = (form.login_username || form.email || form.employee_code || `emp_${Date.now()}`)
        .trim()
        .replace(/\s+/g, '_');
      const payload = {
        user_id: normalizedUserId || `emp_${Date.now()}`,
        name: form.name,
        role: form.role,
        phone: form.phone || null,
        email: form.email || null,
        status: form.status,
        department: form.department || null,
        position: form.position || null,
        employee_code: form.employee_code || null,
        notes: form.notes || null,
        login_username: form.login_username || null,
        hire_date: form.hire_date || null,
        supervisor: form.supervisor || null,
        updated_at: now,
      };
      if (editingId) {
        await client.entities.employees.update({ id: String(editingId), data: payload });
        toast.success('员工信息已更新');
        logOperation({ actionType: 'other', actionDetail: `编辑员工: ${form.name}`, operatorName: op });
      } else {
        const created = await client.entities.employees.create({
          data: {
            ...payload,
            created_at: now,
          },
        });
        if (form.initial_password && created?.data?.id) {
          await invokeWithAuth({
            url: '/api/v1/emp-auth/set-password',
            method: 'POST',
            data: {
              employee_id: created.data.id,
              new_password: form.initial_password,
            },
          });
          toast.success('员工已添加并设置初始密码');
        } else {
          toast.success('员工已添加，请为该员工设置登录密码');
        }
        if (form.role === 'sales_partner') toast.success('销售合伙人账号及分润档案已同时建立');
        logOperation({ actionType: 'other', actionDetail: `新增员工: ${form.name}`, operatorName: op });
      }
      setShowForm(false); loadEmployees();
    } catch (err: any) {
      const detail = err?.data?.detail || err?.response?.data?.detail || err?.message || '保存失败';
      toast.error(detail);
    } finally { setSaving(false); }
  };

  const toggleStatus = async (emp: any, newStatus: string) => {
    try {
      await client.entities.employees.update({ id: String(emp.id), data: { status: newStatus, updated_at: new Date().toISOString() } });
      toast.success(`员工状态已更新为${empStatusLabels[newStatus]}`);
      const op = currentEmp?.name || '管理员';
      logOperation({ actionType: 'other', actionDetail: `更改员工状态: ${emp.name} -> ${empStatusLabels[newStatus]}`, operatorName: op });
      loadEmployees();
      if (selectedEmp?.id === emp.id) setSelectedEmp({ ...selectedEmp, status: newStatus });
      return true;
    } catch {
      toast.error('操作失败');
      return false;
    }
  };

  const handleDisable = async () => {
    if (!disableTarget) return;
    setStatusUpdating(true);
    const updated = await toggleStatus(disableTarget, 'disabled');
    if (updated) setDisableTarget(null);
    setStatusUpdating(false);
  };

  const handleResign = async () => {
    if (!resignTarget) return;
    setResigning(true);
    try {
      const custRes = await client.entities.customers.query({ query: { sales_person: resignTarget.name }, limit: 1 });
      if ((custRes?.data?.items?.length || 0) > 0) {
        toast.error('该员工名下仍有客户，请先完成客户交接后再办理离职');
        setResigning(false);
        return;
      }
      await client.entities.employees.update({ id: String(resignTarget.id), data: { status: 'resigned', updated_at: new Date().toISOString() } });
      toast.success('员工已标记为离职');
      logOperation({ actionType: 'other', actionDetail: `员工离职: ${resignTarget.name}`, operatorName: currentEmp?.name || '管理员' });
      setResignTarget(null); loadEmployees();
    } catch { toast.error('操作失败'); } finally { setResigning(false); }
  };

  const handleTransfer = async () => {
    if (!transferFrom || !transferTo) { toast.error('请选择接收员工'); return; }
    setTransferring(true);
    try {
      const toEmp = employees.find(e => String(e.id) === transferTo);
      if (!toEmp) { toast.error('目标员工不存在'); setTransferring(false); return; }
      const custRes = await client.entities.customers.query({ query: { sales_person: transferFrom.name }, limit: 200 });
      const custs = custRes?.data?.items || [];
      let count = 0;
      for (const c of custs) {
        await client.entities.customers.update({ id: String(c.id), data: { sales_person: toEmp.name, sales_employee_id: toEmp.id, updated_at: new Date().toISOString() } });
        count++;
      }
      toast.success(`已将 ${count} 个客户从 ${transferFrom.name} 转交给 ${toEmp.name}`);
      logOperation({ actionType: 'other', actionDetail: `客户交接: ${transferFrom.name} -> ${toEmp.name} (${count}个客户)`, operatorName: currentEmp?.name || '管理员' });
      setShowTransfer(false); setTransferFrom(null); setTransferTo('');
    } catch { toast.error('交接失败'); } finally { setTransferring(false); }
  };

  const handleResetPassword = async () => {
    if (!resetPwdTarget) return;
    setResettingPassword(true);
    try {
      await invokeWithAuth({
        url: '/api/v1/emp-auth/set-password',
        method: 'POST',
        data: {
          employee_id: resetPwdTarget.id,
          new_password: newPassword,
        },
      });
      toast.success(`已重置 ${resetPwdTarget.name} 的登录密码`);
      logOperation({ actionType: 'other', actionDetail: `重置员工密码: ${resetPwdTarget.name}`, operatorName: currentEmp?.name || '管理员' });
      setResetPwdTarget(null);
      setNewPassword('');
    } catch (err: any) {
      const detail = err?.data?.detail || err?.response?.data?.detail || err?.message || '重置密码失败';
      toast.error(detail);
    } finally {
      setResettingPassword(false);
    }
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      // Check if employee has customers
      const custRes = await client.entities.customers.query({ query: { sales_person: deleteTarget.name }, limit: 1 });
      if ((custRes?.data?.items?.length || 0) > 0) {
        toast.error('该员工名下仍有客户，请先完成客户交接后再删除');
        setDeleting(false);
        return;
      }
      await client.entities.employees.delete({ id: String(deleteTarget.id) });
      toast.success(`员工「${deleteTarget.name}」已删除`);
      logOperation({ actionType: 'other', actionDetail: `删除员工: ${deleteTarget.name}`, operatorName: currentEmp?.name || '管理员' });
      setDeleteTarget(null);
      loadEmployees();
    } catch { toast.error('删除失败'); } finally { setDeleting(false); }
  };

  const openDetail = async (emp: any) => {
    setSelectedEmp(emp);
    try {
      const [custRes, taskRes, dealRes, logRes] = await Promise.all([
        client.entities.customers.query({ query: { sales_person: emp.name }, limit: 100, sort: '-created_at' }),
        client.entities.tasks.query({ query: { assignee_name: emp.name }, limit: 100, sort: '-created_at' }),
        client.entities.deals.query({ query: { sales_name: emp.name }, limit: 100, sort: '-deal_date' }),
        invokeWithAuth({
          url: '/api/v1/entities/operation_logs/all',
          method: 'GET',
          data: {
            query: JSON.stringify({ operator_name: emp.name }),
            limit: 50,
            sort: '-created_at',
          },
        }),
      ]);
      setEmpCustomers(custRes?.data?.items || []);
      setEmpTasks(taskRes?.data?.items || []);
      setEmpDeals(dealRes?.data?.items || []);
      setEmpLogs(logRes?.data?.items || []);
    } catch (err) { console.error(err); }
  };

  const empStats = useMemo(() => {
    if (!selectedEmp) return null;
    return {
      totalCust: empCustomers.length,
      followingCust: empCustomers.filter(c => c.status === 'following').length,
      closedCust: empCustomers.filter(c => c.status === 'closed').length,
      totalDeals: empDeals.length,
      totalRevenue: empDeals.reduce((s, d) => s + (d.deal_amount || 0), 0),
      pendingTasks: empTasks.filter(t => t.status === 'pending' || t.status === 'in_progress').length,
      completedTasks: empTasks.filter(t => t.status === 'completed').length,
    };
  }, [selectedEmp, empCustomers, empDeals, empTasks]);

  if (!isAdmin) {
    return <div className="flex items-center justify-center h-64"><p className="text-slate-400">仅管理员可管理员工</p></div>;
  }

  const canCreate = hasPermission('employee_create');
  const canEdit = hasPermission('employee_edit');
  const canDisable = hasPermission('employee_disable');
  const canResetPwd = hasPermission('employee_reset_password');

  const getRoleDisplay = (r: string) => systemRoleLabels[r as keyof typeof systemRoleLabels] || roleLabels[r] || r;

  const PaginationFooter = () => {
    if (paginated.total === 0) return null;
    return (
      <div className="flex flex-col gap-3 border-t border-slate-100 px-4 py-3 text-sm text-slate-600 sm:flex-row sm:items-center sm:justify-between">
        <div>
          显示 {paginated.start}-{paginated.end} 条 / 共 {paginated.total} 条
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-slate-500">每页</span>
          <NativeSelect
            value={String(pageSize)}
            onChange={value => setPageSize(Number(value))}
            className="w-24"
            options={PAGE_SIZE_OPTIONS.map(size => ({ value: String(size), label: `${size} 条` }))}
          />
          <Button size="sm" variant="outline" className="md:h-8" onClick={() => setPage(1)} disabled={paginated.page <= 1}>首页</Button>
          <Button size="sm" variant="outline" className="md:h-8" onClick={() => setPage(paginated.page - 1)} disabled={paginated.page <= 1}>上一页</Button>
          <span className="min-w-20 text-center text-xs text-slate-500">{paginated.page} / {paginated.totalPages} 页</span>
          <Button size="sm" variant="outline" className="md:h-8" onClick={() => setPage(paginated.page + 1)} disabled={paginated.page >= paginated.totalPages}>下一页</Button>
          <Button size="sm" variant="outline" className="md:h-8" onClick={() => setPage(paginated.totalPages)} disabled={paginated.page >= paginated.totalPages}>末页</Button>
        </div>
      </div>
    );
  };

  // ========== DETAIL VIEW ==========
  if (selectedEmp) {
    const e = selectedEmp;
    return (
      <div className="t24-detail-page app-page space-y-4">
        <div className="flex items-center gap-3 flex-wrap">
          <Button variant="ghost" size="sm" onClick={() => setSelectedEmp(null)}><ArrowLeft className="w-4 h-4 mr-1" /> 返回列表</Button>
          <h2 className="text-lg font-semibold">{e.name}</h2>
          <Badge variant="secondary">{getRoleDisplay(e.role)}</Badge>
          <Badge className={empStatusColors[e.status]}>{empStatusLabels[e.status] || e.status}</Badge>
        </div>

        <Tabs defaultValue="info" className="w-full">
          <TabsList className="bg-slate-100 flex-wrap h-auto gap-1 p-1">
            <TabsTrigger value="info" className="text-xs">基本信息</TabsTrigger>
            <TabsTrigger value="stats" className="text-xs">工作统计</TabsTrigger>
            <TabsTrigger value="customers" className="hidden text-xs md:inline-flex">负责客户 ({empCustomers.length})</TabsTrigger>
            <TabsTrigger value="tasks" className="text-xs">任务 ({empTasks.length})</TabsTrigger>
            <TabsTrigger value="deals" className="hidden text-xs md:inline-flex">成交 ({empDeals.length})</TabsTrigger>
            <TabsTrigger value="logs" className="hidden text-xs md:inline-flex">操作日志</TabsTrigger>
          </TabsList>

          <TabsContent value="info">
            <Card className="border-slate-200"><CardContent className="p-5">
              {!isMobile && <div className="mb-4 flex justify-end gap-2">
                {canEdit && <Button size="sm" variant="outline" onClick={() => openEdit(e)}><Edit className="w-3 h-3 mr-1" /> 编辑</Button>}
                <Button size="sm" variant="outline" onClick={() => { setTransferFrom(e); setShowTransfer(true); }}><ArrowRightLeft className="w-3 h-3 mr-1" /> 客户交接</Button>
                {canResetPwd && <Button size="sm" variant="outline" onClick={() => setResetPwdTarget(e)}><KeyRound className="w-3 h-3 mr-1" /> 重置密码</Button>}
                {e.status !== 'resigned' && canDisable && <Button size="sm" variant="outline" className="text-red-600 hover:text-red-700 hover:bg-red-50" onClick={() => setResignTarget(e)}><UserX className="w-3 h-3 mr-1" /> 办理离职</Button>}
              </div>}
              <div className="grid md:grid-cols-2 gap-x-8 gap-y-3 text-sm">
                <div className="flex gap-2"><span className="text-slate-500 w-24 shrink-0">工号:</span><span>{e.employee_code || '-'}</span></div>
                <div className="flex gap-2"><span className="text-slate-500 w-24 shrink-0">角色:</span><span>{getRoleDisplay(e.role)}</span></div>
                {!isMobile && <div className="flex gap-2"><span className="text-slate-500 w-24 shrink-0">登录用户名:</span><span>{e.login_username || '-'}</span></div>}
                <div className="flex gap-2 items-center"><Phone className="w-3 h-3 text-slate-400" /><span>{e.phone || '-'}</span></div>
                <div className="flex gap-2 items-center"><Mail className="w-3 h-3 text-slate-400" /><span>{e.email || '-'}</span></div>
                <div className="flex gap-2"><span className="text-slate-500 w-24 shrink-0">部门:</span><span>{departmentLabels[e.department] || e.department || '-'}</span></div>
                <div className="flex gap-2"><span className="text-slate-500 w-24 shrink-0">岗位:</span><span>{positionLabels[e.position] || e.position || '-'}</span></div>
                <div className="flex gap-2"><span className="text-slate-500 w-24 shrink-0">状态:</span><Badge className={empStatusColors[e.status]}>{empStatusLabels[e.status] || e.status}</Badge></div>
                <div className="flex gap-2 items-center"><Calendar className="w-3 h-3 text-slate-400" /><span className="text-slate-500 w-20 shrink-0">入职日期:</span><span>{e.hire_date || '-'}</span></div>
                <div className="flex gap-2"><span className="text-slate-500 w-24 shrink-0">直属上级:</span><span>{e.supervisor || '-'}</span></div>
                <div className="flex gap-2"><span className="text-slate-500 w-24 shrink-0">创建时间:</span><span>{e.created_at?.slice(0, 10) || '-'}</span></div>
                {e.notes && <div className="col-span-2 mt-2 p-3 bg-slate-50 rounded text-slate-600">{e.notes}</div>}
              </div>
              {!isMobile && e.status !== 'resigned' && canDisable && (
                <div className="mt-4 flex gap-2 border-t border-slate-100 pt-4">
                  <span className="text-sm text-slate-500">快速操作:</span>
                  {e.status === 'active' && <Button size="sm" variant="outline" className="h-7 text-xs" onClick={() => toggleStatus(e, 'disabled')}>停用</Button>}
                  {e.status === 'disabled' && <Button size="sm" variant="outline" className="h-7 text-xs text-green-600" onClick={() => toggleStatus(e, 'active')}>启用</Button>}
                  {e.status === 'probation' && <Button size="sm" variant="outline" className="h-7 text-xs text-green-600" onClick={() => toggleStatus(e, 'active')}>转正</Button>}
                </div>
              )}
            </CardContent></Card>
          </TabsContent>

          <TabsContent value="stats">
            <Card className="border-slate-200"><CardContent className="p-5">
              {empStats && (
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                  {[
                    { label: '负责客户', value: empStats.totalCust, color: 'text-blue-600' },
                    { label: '跟进中', value: empStats.followingCust, color: 'text-amber-600' },
                    { label: '已成交', value: empStats.closedCust, color: 'text-green-600' },
                    { label: '成交单数', value: empStats.totalDeals, color: 'text-purple-600' },
                    { label: '成交总额', value: `$${empStats.totalRevenue.toLocaleString()}`, color: 'text-emerald-600' },
                    { label: '待办任务', value: empStats.pendingTasks, color: 'text-orange-600' },
                    { label: '已完成任务', value: empStats.completedTasks, color: 'text-slate-600' },
                  ].map(s => (
                    <div key={s.label} className="p-3 bg-slate-50 rounded-lg text-center">
                      <p className="text-xs text-slate-500 mb-1">{s.label}</p>
                      <p className={`text-xl font-bold ${s.color}`}>{s.value}</p>
                    </div>
                  ))}
                </div>
              )}
            </CardContent></Card>
          </TabsContent>

          <TabsContent value="customers">
            <Card className="border-slate-200"><CardContent className="p-5">
              {empCustomers.length === 0 ? <p className="text-sm text-slate-400 text-center py-8">暂无负责客户</p> : (
                <div className="overflow-x-auto"><table className="w-full text-sm"><thead><tr className="border-b bg-slate-50 text-left text-slate-500"><th className="px-3 py-2 font-medium">商家名称</th><th className="px-3 py-2 font-medium">联系人</th><th className="px-3 py-2 font-medium">电话</th><th className="px-3 py-2 font-medium">状态</th></tr></thead>
                <tbody>{empCustomers.map((c: any) => (
                  <tr key={c.id} className="border-b border-slate-100"><td className="px-3 py-2 font-medium text-blue-600">{c.business_name}</td><td className="px-3 py-2">{c.contact_name}</td><td className="px-3 py-2 text-slate-500">{c.phone}</td><td className="px-3 py-2"><Badge className={`text-xs ${c.status === 'closed' ? 'bg-green-100 text-green-700' : c.status === 'following' ? 'bg-amber-100 text-amber-700' : 'bg-slate-100 text-slate-600'}`}>{statusLabels[c.status] || c.status}</Badge></td></tr>
                ))}</tbody></table></div>
              )}
            </CardContent></Card>
          </TabsContent>

          <TabsContent value="tasks">
            <Card className="border-slate-200"><CardContent className="p-5">
              {empTasks.length === 0 ? <p className="text-sm text-slate-400 text-center py-8">暂无任务</p> : (
                <div className="space-y-2">{empTasks.map((t: any) => (
                  <div key={t.id} className="p-3 bg-slate-50 rounded-lg flex items-center justify-between">
                    <div><p className="text-sm font-medium">{t.title}</p><p className="text-xs text-slate-500">{t.due_date?.slice(0, 10) || '-'}</p></div>
                    <Badge variant="secondary" className="text-xs">{taskStatusLabels[t.status] || t.status}</Badge>
                  </div>
                ))}</div>
              )}
            </CardContent></Card>
          </TabsContent>

          <TabsContent value="deals">
            <Card className="border-slate-200"><CardContent className="p-5">
              {empDeals.length === 0 ? <p className="text-sm text-slate-400 text-center py-8">暂无成交记录</p> : (
                <div className="space-y-2">{empDeals.map((d: any) => (
                  <div key={d.id} className="p-3 bg-slate-50 rounded-lg flex items-center justify-between">
                    <div><p className="text-sm font-medium">{d.package_name}</p><p className="text-xs text-slate-500">{d.deal_date?.slice(0, 10)}</p></div>
                    <span className="text-green-600 font-bold">${d.deal_amount}</span>
                  </div>
                ))}</div>
              )}
            </CardContent></Card>
          </TabsContent>

          <TabsContent value="logs">
            <Card className="border-slate-200"><CardContent className="p-5">
              {empLogs.length === 0 ? <p className="text-sm text-slate-400 text-center py-8">暂无操作日志</p> : (
                <div className="space-y-2 max-h-96 overflow-y-auto">{empLogs.map((log: any) => (
                  <div key={log.id} className="flex items-start gap-3 p-2.5 bg-slate-50 rounded-lg text-sm">
                    <Badge variant="secondary" className="text-xs shrink-0">{actionTypeLabels[log.action_type] || log.action_type}</Badge>
                    <div className="flex-1"><p className="text-slate-700">{log.action_detail}</p><p className="text-xs text-slate-400">{log.created_at?.slice(0, 16).replace('T', ' ')}</p></div>
                  </div>
                ))}</div>
              )}
            </CardContent></Card>
          </TabsContent>
        </Tabs>
      </div>
    );
  }

  // ========== LIST VIEW ==========
  return (
    <div className="t24-directory-page t24-employee-directory app-page space-y-5">
      <div className="app-page-title flex items-start justify-between">
        <div>
          <p className="app-page-kicker">T24 Marketing · Team</p>
          <h2 className="app-page-heading">员工管理</h2>
          <p className="app-page-description">统一查看员工身份、岗位、部门与工作状态，敏感账号操作集中在桌面端完成。</p>
        </div>
        {!isMobile && canCreate && <Button onClick={openCreate} className="bg-blue-600 hover:bg-blue-700"><Plus className="w-4 h-4 mr-1" /> 添加员工</Button>}
      </div>

      <div className="flex items-start gap-3 rounded-2xl border border-blue-100 bg-blue-50/80 p-4 text-sm text-blue-900 md:hidden">
        <MonitorSmartphone className="mt-0.5 h-5 w-5 shrink-0 text-blue-600" />
        <div>
          <p className="font-semibold">手机版提供员工目录与工作概览</p>
          <p className="mt-1 text-xs leading-5 text-blue-700">新增账号、密码重置、批量交接、停启用、离职与删除请在电脑端处理。</p>
        </div>
      </div>

      <div className="t24-directory-metrics grid grid-cols-2 gap-3 md:grid-cols-4">
        {[
          { label: '总员工', value: loading || (loadError && employees.length === 0) ? '—' : employees.length, color: 'text-blue-600' },
          { label: '在职', value: loading || (loadError && employees.length === 0) ? '—' : employees.filter(e => e.status === 'active').length, color: 'text-green-600' },
          { label: '试用期', value: loading || (loadError && employees.length === 0) ? '—' : employees.filter(e => e.status === 'probation').length, color: 'text-blue-600' },
          { label: '已离职', value: loading || (loadError && employees.length === 0) ? '—' : employees.filter(e => e.status === 'resigned').length, color: 'text-slate-500' },
        ].map(s => (
          <Card key={s.label} className="border-slate-200"><CardContent className="p-3 text-center">
            <p className="text-xs text-slate-500">{s.label}</p><p className={`text-xl font-bold ${s.color}`}>{s.value}</p>
          </CardContent></Card>
        ))}
      </div>

      <Card className="t24-directory-toolbar border-slate-200"><CardContent className="p-3">
        <div className="flex flex-col gap-3 sm:flex-row">
          <div className="relative flex-1"><Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" /><Input placeholder="搜索姓名、电话、邮箱、用户名..." value={search} onChange={e => setSearch(e.target.value)} className="pl-9" /></div>
          <NativeSelect value={filterStatus} onChange={setFilterStatus} className="w-full sm:w-[120px]" options={[{ value: 'all', label: '全部状态' }, ...Object.entries(empStatusLabels).map(([k, v]) => ({ value: k, label: v }))]} />
          <NativeSelect value={filterRole} onChange={setFilterRole} className="w-full sm:w-[120px]" options={[{ value: 'all', label: '全部角色' }, ...allRoleOptions]} />
          <NativeSelect value={filterDept} onChange={setFilterDept} className="w-full sm:w-[120px]" options={[{ value: 'all', label: '全部部门' }, ...Object.entries(departmentLabels).map(([k, v]) => ({ value: k, label: v }))]} />
        </div>
      </CardContent></Card>

      {loadError && (
        <div className="flex flex-col gap-3 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900 sm:flex-row sm:items-center sm:justify-between" role="alert">
          <div className="flex min-w-0 items-start gap-2">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            <div>
              <p className="font-medium">员工资料暂时无法更新</p>
              <p className="mt-0.5 text-xs text-amber-700">{employees.length > 0 ? '当前继续显示上一次成功读取的数据。' : loadError}</p>
            </div>
          </div>
          <Button
            size="sm"
            variant="outline"
            className="shrink-0 border-amber-200 bg-white text-amber-800 hover:bg-amber-100"
            onClick={() => { setLoading(employees.length === 0); void loadEmployees(); }}
          >
            <RefreshCw className="mr-1.5 h-3.5 w-3.5" />重试
          </Button>
        </div>
      )}

      <Card className="t24-directory-results border-slate-200"><CardContent className="p-0">
        {loading ? <div className="flex items-center justify-center py-12"><div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600" /></div>
        : loadError && employees.length === 0 ? <div className="py-12 text-center"><p className="text-sm font-medium text-slate-600">员工资料尚未加载</p><p className="mt-1 text-xs text-slate-400">请使用上方“重试”，当前不显示为零员工。</p></div>
        : filtered.length === 0 ? <p className="text-center text-slate-400 py-12">暂无员工</p>
        : (
          <>
          {isMobile ? <div className="space-y-3 p-3" data-testid="employee-mobile-cards">
            {paginated.items.map(e => (
              <article key={e.id} className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="truncate font-semibold text-slate-950">{e.name}</h3>
                      <Badge className={`text-xs ${empStatusColors[e.status]}`}>{empStatusLabels[e.status] || e.status}</Badge>
                    </div>
                    <p className="mt-1 text-xs text-slate-500">{e.employee_code || '未设工号'} · {getRoleDisplay(e.role)}</p>
                  </div>
                  <Badge variant="secondary" className="shrink-0 text-xs">{departmentLabels[e.department] || e.department || '未分部门'}</Badge>
                </div>
                <div className="mt-3 grid grid-cols-2 gap-2 rounded-xl bg-slate-50 p-3 text-xs text-slate-600">
                  <div><span className="block text-slate-400">岗位</span><span className="mt-0.5 block font-medium text-slate-700">{positionLabels[e.position] || e.position || '-'}</span></div>
                  <div><span className="block text-slate-400">直属上级</span><span className="mt-0.5 block font-medium text-slate-700">{e.supervisor || '-'}</span></div>
                </div>
                <div className="mt-3 flex gap-2">
                  {e.phone ? (
                    <a href={`tel:${e.phone}`} className="flex min-h-11 min-w-0 flex-1 items-center justify-center gap-2 rounded-xl border border-slate-200 px-3 text-sm font-semibold text-slate-700">
                      <Phone className="h-4 w-4" /><span className="truncate">拨打电话</span>
                    </a>
                  ) : null}
                  <Button type="button" variant="outline" className="min-h-11 flex-1 rounded-xl" onClick={() => openDetail(e)}>
                    查看概览<ChevronRight className="h-4 w-4" />
                  </Button>
                </div>
              </article>
            ))}
          </div> : <div className="overflow-x-auto"><table className="w-full text-sm"><thead><tr className="border-b bg-slate-50 text-left text-slate-500">
            <th className="px-4 py-3 font-medium">工号</th><th className="px-4 py-3 font-medium">姓名</th>
            <th className="px-4 py-3 font-medium">角色</th><th className="px-4 py-3 font-medium">部门</th>
            <th className="px-4 py-3 font-medium hidden md:table-cell">用户名</th>
            <th className="px-4 py-3 font-medium hidden md:table-cell">电话</th>
            <th className="px-4 py-3 font-medium">状态</th><th className="px-4 py-3 text-right font-medium w-20">操作</th>
          </tr></thead>
          <tbody>{paginated.items.map(e => (
            <tr key={e.id} className="border-b border-slate-100 hover:bg-slate-50 cursor-pointer transition-colors">
              <td className="px-4 py-3 text-xs font-mono text-slate-500" onClick={() => openDetail(e)}>{e.employee_code || '-'}</td>
              <td className="px-4 py-3 font-medium text-blue-600" onClick={() => openDetail(e)}>{e.name}</td>
              <td className="px-4 py-3" onClick={() => openDetail(e)}><Badge variant="secondary" className="text-xs">{getRoleDisplay(e.role)}</Badge></td>
              <td className="px-4 py-3 text-slate-500" onClick={() => openDetail(e)}>{departmentLabels[e.department] || e.department || '-'}</td>
              <td className="px-4 py-3 text-slate-500 hidden md:table-cell" onClick={() => openDetail(e)}>{e.login_username || '-'}</td>
              <td className="px-4 py-3 text-slate-500 hidden md:table-cell" onClick={() => openDetail(e)}>{e.phone || '-'}</td>
              <td className="px-4 py-3" onClick={() => openDetail(e)}><Badge className={`text-xs ${empStatusColors[e.status]}`}>{empStatusLabels[e.status] || e.status}</Badge></td>
              <td className="px-4 py-3 text-right">
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button
                      size="sm"
                      variant="ghost"
                      className="h-8 w-8 p-0 text-slate-500 hover:text-blue-600"
                      aria-label={`更多员工操作：${e.name}`}
                    >
                      <MoreHorizontal className="h-4 w-4" />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end" className="w-44">
                    {canEdit && <DropdownMenuItem onSelect={() => openEdit(e)}><Edit className="mr-2 h-4 w-4" />编辑资料</DropdownMenuItem>}
                    <DropdownMenuItem onSelect={() => { setTransferFrom(e); setShowTransfer(true); }}><ArrowRightLeft className="mr-2 h-4 w-4" />客户交接</DropdownMenuItem>
                    {canResetPwd && <DropdownMenuItem onSelect={() => setResetPwdTarget(e)}><KeyRound className="mr-2 h-4 w-4" />重置密码</DropdownMenuItem>}
                    {canDisable && (e.status === 'active' || e.status === 'disabled') && <DropdownMenuSeparator />}
                    {e.status === 'active' && canDisable && <DropdownMenuItem className="text-amber-700 focus:text-amber-800" onSelect={() => setDisableTarget(e)}><ShieldOff className="mr-2 h-4 w-4" />停用账号</DropdownMenuItem>}
                    {e.status === 'disabled' && canDisable && <DropdownMenuItem className="text-emerald-700 focus:text-emerald-800" onSelect={() => { void toggleStatus(e, 'active'); }}><ShieldCheck className="mr-2 h-4 w-4" />启用账号</DropdownMenuItem>}
                    {canDisable && <DropdownMenuSeparator />}
                    {canDisable && <DropdownMenuItem className="text-red-600 focus:bg-red-50 focus:text-red-700" onSelect={() => setDeleteTarget(e)}><Trash2 className="mr-2 h-4 w-4" />删除员工</DropdownMenuItem>}
                  </DropdownMenuContent>
                </DropdownMenu>
              </td>
            </tr>
          ))}</tbody></table></div>}
          </>
        )}
        {!loading && filtered.length > 0 && <PaginationFooter />}
      </CardContent></Card>

      {!isMobile && <>
      {/* Transfer Dialog */}
      <Dialog open={showTransfer} onOpenChange={v => { if (!v) { setShowTransfer(false); setTransferFrom(null); setTransferTo(''); } }}>
        <DialogContent className="max-w-md">
          <DialogHeader><DialogTitle>客户交接</DialogTitle></DialogHeader>
          <div className="space-y-4">
            <div><Label>转出员工</Label><Input value={transferFrom?.name || ''} disabled className="bg-slate-50" /></div>
            <div><Label>转入员工 *</Label>
              <NativeSelect value={transferTo} onChange={setTransferTo} options={[{ value: '', label: '请选择接收员工' }, ...activeEmployees.filter(e => e.id !== transferFrom?.id).map(e => ({ value: String(e.id), label: `${e.name} (${getRoleDisplay(e.role)})` }))]} />
            </div>
            <p className="text-xs text-slate-500">将 {transferFrom?.name} 名下所有客户转交给选定员工</p>
          </div>
          <div className="flex justify-end gap-2 mt-4">
            <Button variant="outline" onClick={() => { setShowTransfer(false); setTransferFrom(null); }}>取消</Button>
            <Button onClick={handleTransfer} disabled={transferring || !transferTo} className="bg-blue-600 hover:bg-blue-700">{transferring ? '交接中...' : '确认交接'}</Button>
          </div>
        </DialogContent>
      </Dialog>

      {/* Resign Confirm */}
      <ConfirmDialog open={!!resignTarget} onOpenChange={v => { if (!v) setResignTarget(null); }} title="确认办理离职"
        description={`确定要将「${resignTarget?.name}」标记为离职吗？离职后账号将被停用，但记录不会被删除。如果该员工名下仍有客户，需先完成客户交接。`}
        onConfirm={handleResign} loading={resigning} confirmLabel="确认办理离职" loadingLabel="办理中..." />

      <ConfirmDialog open={!!disableTarget} onOpenChange={v => { if (!v) setDisableTarget(null); }} title="确认停用账号"
        description={`确定要停用「${disableTarget?.name}」的账号吗？停用后该员工将无法登录，但员工资料和历史记录会继续保留。`}
        onConfirm={handleDisable} loading={statusUpdating} confirmLabel="确认停用" loadingLabel="停用中..." />

      {/* Reset Password Dialog */}
      <Dialog open={!!resetPwdTarget} onOpenChange={v => { if (!v) { setResetPwdTarget(null); setNewPassword(''); setResettingPassword(false); } }}>
        <DialogContent className="max-w-sm">
          <DialogHeader><DialogTitle>重置密码</DialogTitle></DialogHeader>
          <div className="space-y-4">
            <p className="text-sm text-slate-600">即将重置 <strong>{resetPwdTarget?.name}</strong> 的登录密码</p>
            <div>
              <Label>新密码</Label>
              <Input type="password" value={newPassword} onChange={e => setNewPassword(e.target.value)} placeholder="输入新密码（至少8位）" />
            </div>
            <p className="text-xs text-amber-600">请让员工本人安全接收并尽快在“我的账户”修改；不要通过微信群发送密码。</p>
          </div>
          <div className="flex justify-end gap-2 mt-4">
            <Button variant="outline" onClick={() => { setResetPwdTarget(null); setNewPassword(''); setResettingPassword(false); }}>取消</Button>
            <Button onClick={handleResetPassword} disabled={resettingPassword || !newPassword || newPassword.length < 8} className="bg-blue-600 hover:bg-blue-700">
              {resettingPassword ? '重置中...' : '确认重置'}
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      {/* Delete Confirm */}
      <ConfirmDialog open={!!deleteTarget} onOpenChange={v => { if (!v) setDeleteTarget(null); }} title="确认删除员工"
        description={`确定要删除员工「${deleteTarget?.name}」吗？此操作不可恢复。如果该员工名下仍有客户，需先完成客户交接。`}
        onConfirm={handleDelete} loading={deleting} confirmLabel="确认删除员工" loadingLabel="删除中..." />

      {/* Add/Edit Dialog */}
      <Dialog open={showForm} onOpenChange={setShowForm}>
        <DialogContent className="max-w-lg max-h-[85vh] overflow-y-auto">
          <DialogHeader><DialogTitle>{editingId ? '编辑员工' : '添加员工'}</DialogTitle></DialogHeader>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <div><Label>工号</Label><Input value={form.employee_code} onChange={e => setForm({ ...form, employee_code: e.target.value })} placeholder="如 EMP001" className="font-mono" /></div>
            <div><Label>姓名 *</Label><Input value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} /></div>
            <div><Label>角色 *</Label><NativeSelect value={form.role} onChange={v => setForm({ ...form, role: v })} options={allRoleOptions} /></div>
            <div><Label>部门</Label><NativeSelect value={form.department} onChange={v => setForm({ ...form, department: v })} options={Object.entries(departmentLabels).map(([k, v]) => ({ value: k, label: v }))} /></div>
            <div><Label>岗位</Label><NativeSelect value={form.position} onChange={v => setForm({ ...form, position: v })} options={Object.entries(positionLabels).map(([k, v]) => ({ value: k, label: v }))} /></div>
            <div><Label>状态</Label><NativeSelect value={form.status} onChange={v => setForm({ ...form, status: v })} options={Object.entries(empStatusLabels).map(([k, v]) => ({ value: k, label: v }))} /></div>
            <div><Label>登录用户名</Label><Input value={form.login_username} onChange={e => setForm({ ...form, login_username: e.target.value })} placeholder="用于系统登录" /></div>
            <div><Label>入职日期</Label><Input type="date" value={form.hire_date} onChange={e => setForm({ ...form, hire_date: e.target.value })} /></div>
            <div><Label>直属上级</Label><NativeSelect value={form.supervisor} onChange={v => setForm({ ...form, supervisor: v })} options={[{ value: '', label: '无' }, ...employees.filter(emp => emp.id !== editingId).map(emp => ({ value: emp.name, label: `${emp.name} (${getRoleDisplay(emp.role)})` }))]} /></div>
            <div><Label>电话</Label><Input value={form.phone} onChange={e => setForm({ ...form, phone: e.target.value })} /></div>
            <div><Label>邮箱</Label><Input value={form.email} onChange={e => setForm({ ...form, email: e.target.value })} /></div>
            {!editingId && (
              <div><Label>初始密码</Label><Input type="password" value={form.initial_password} onChange={e => setForm({ ...form, initial_password: e.target.value })} placeholder="可选，至少8位" /></div>
            )}
            <div className="md:col-span-2"><Label>备注</Label><Textarea value={form.notes} onChange={e => setForm({ ...form, notes: e.target.value })} rows={2} /></div>
          </div>
          {!editingId && <p className="text-xs text-slate-500 mt-3">建议不在此填写，由员工本人在安全环境下设置；第一阶段尚未开放邮件邀请流程。</p>}
          <div className="flex justify-end gap-2 mt-4">
            <Button variant="outline" onClick={() => setShowForm(false)}>取消</Button>
            <Button onClick={handleSave} disabled={saving} className="bg-blue-600 hover:bg-blue-700">{saving ? '保存中...' : '保存'}</Button>
          </div>
        </DialogContent>
      </Dialog>
      </>}
    </div>
  );
}
