import { useState, useEffect } from 'react';
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

const taskTypeLabels: Record<string, string> = {
  follow_up: '跟进客户', design: '设计页面', menu_entry: '菜单录入',
  stripe_setup: 'Stripe配置', google_auth: 'Google权限', test_order: '测试订单',
  report: '周报提交', renewal_reminder: '续费催款', other: '其他',
};
const priorityLabels: Record<string, string> = { high: '高', medium: '中', low: '低' };
const priorityColors: Record<string, string> = {
  high: 'bg-red-100 text-red-700', medium: 'bg-amber-100 text-amber-700', low: 'bg-slate-100 text-slate-600',
};
const statusLabels: Record<string, string> = {
  pending: '待处理', in_progress: '进行中', completed: '已完成', delayed: '延期',
};
const statusColors: Record<string, string> = {
  pending: 'bg-blue-100 text-blue-700', in_progress: 'bg-amber-100 text-amber-700',
  completed: 'bg-green-100 text-green-700', delayed: 'bg-red-100 text-red-700',
};

export default function Tasks() {
  const [tasks, setTasks] = useState<any[]>([]);
  const [customers, setCustomers] = useState<any[]>([]);
  const [employees, setEmployees] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [filterStatus, setFilterStatus] = useState('all');
  const [filterPriority, setFilterPriority] = useState('all');
  const [showForm, setShowForm] = useState(false);
  const [saving, setSaving] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<any>(null);
  const [deleting, setDeleting] = useState(false);
  const emptyTaskForm = {
    title: '', customer_id: '', assignee_name: '', collaborator_names: '',
    task_type: 'other', priority: 'medium', status: 'pending',
    due_date: '', notes: '', attachment_link: '',
  };
  const [form, setForm] = useState(emptyTaskForm);

  useEffect(() => { loadData(); }, []);

  const loadData = async () => {
    try {
      const [tRes, cRes, eRes] = await Promise.all([
        client.entities.tasks.query({ limit: 200, sort: '-created_at' }),
        client.entities.customers.query({ limit: 200 }),
        client.entities.employees.query({ limit: 50 }),
      ]);
      setTasks(tRes?.data?.items || []);
      setCustomers(cRes?.data?.items || []);
      setEmployees(eRes?.data?.items || []);
    } catch (err) { console.error(err); }
    finally { setLoading(false); }
  };

  const filtered = tasks.filter(t => {
    const matchSearch = !search || t.title?.includes(search) || t.customer_name?.includes(search) || t.assignee_name?.includes(search);
    const matchStatus = filterStatus === 'all' || t.status === filterStatus;
    const matchPriority = filterPriority === 'all' || t.priority === filterPriority;
    return matchSearch && matchStatus && matchPriority;
  });

  const pendingCount = tasks.filter(t => t.status === 'pending').length;
  const inProgressCount = tasks.filter(t => t.status === 'in_progress').length;
  const completedCount = tasks.filter(t => t.status === 'completed').length;

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
        assignee_name: form.assignee_name,
        collaborator_names: form.collaborator_names,
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
    } catch (err) { toast.error('更新失败'); }
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold text-slate-800">任务协作</h2>
          <p className="text-sm text-slate-500">待处理 {pendingCount} · 进行中 {inProgressCount} · 已完成 {completedCount}</p>
        </div>
        <Button onClick={() => { setForm(emptyTaskForm); setEditingId(null); setShowForm(true); }} className="bg-blue-600 hover:bg-blue-700">
          <Plus className="w-4 h-4 mr-1" /> 新建任务
        </Button>
      </div>

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
              options={[{ value: 'all', label: '全部状态' }, ...Object.entries(statusLabels).map(([k, v]) => ({ value: k, label: v }))]}
            />
            <NativeSelect
              value={filterPriority}
              onChange={setFilterPriority}
              className="w-[140px]"
              options={[{ value: 'all', label: '全部优先级' }, ...Object.entries(priorityLabels).map(([k, v]) => ({ value: k, label: v }))]}
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
              {filtered.map(t => (
                <div key={t.id} className="p-4 hover:bg-slate-50 transition-colors">
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex-1">
                      <div className="flex items-center gap-2 mb-1">
                        <span className={`font-medium text-sm ${t.status === 'completed' ? 'line-through text-slate-400' : 'text-slate-800'}`}>{t.title}</span>
                        <Badge className={`text-xs ${statusColors[t.status]}`}>{statusLabels[t.status]}</Badge>
                        <Badge className={`text-xs ${priorityColors[t.priority]}`}>{priorityLabels[t.priority]}</Badge>
                      </div>
                      <div className="flex flex-wrap gap-3 text-xs text-slate-500">
                        {t.customer_name && <span>客户: {t.customer_name}</span>}
                        {t.assignee_name && <span>负责: {t.assignee_name}</span>}
                        {t.collaborator_names && <span>协作: {t.collaborator_names}</span>}
                        <span>类型: {taskTypeLabels[t.task_type] || t.task_type}</span>
                        {t.due_date && <span className={new Date(t.due_date) < new Date() && t.status !== 'completed' ? 'text-red-500 font-medium' : ''}>截止: {t.due_date?.slice(0, 10)}</span>}
                      </div>
                      {t.notes && <p className="text-xs text-slate-400 mt-1">{t.notes}</p>}
                    </div>
                    <div className="flex gap-1 shrink-0">
                      {t.status !== 'completed' && (
                        <Button size="sm" variant="ghost" className="text-green-600 hover:text-green-700 hover:bg-green-50 h-8 px-2" onClick={() => handleStatusChange(t.id, 'completed')}>
                          <CheckCircle2 className="w-4 h-4" />
                        </Button>
                      )}
                      {t.status === 'pending' && (
                        <Button size="sm" variant="ghost" className="text-amber-600 hover:text-amber-700 hover:bg-amber-50 h-8 px-2 text-xs" onClick={() => handleStatusChange(t.id, 'in_progress')}>
                          开始
                        </Button>
                      )}
                      <Button size="sm" variant="ghost" className="h-8 w-8 p-0 text-slate-400 hover:text-blue-600" onClick={() => openEditTask(t)}><Edit className="w-3.5 h-3.5" /></Button>
                      <Button size="sm" variant="ghost" className="h-8 w-8 p-0 text-slate-400 hover:text-red-600" onClick={() => setDeleteTarget(t)}><Trash2 className="w-3.5 h-3.5" /></Button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
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

      {/* Add/Edit task dialog */}
      <Dialog open={showForm} onOpenChange={(v) => { setShowForm(v); if (!v) { setEditingId(null); setForm(emptyTaskForm); } }}>
        <DialogContent className="max-w-lg max-h-[85vh] overflow-y-auto">
          <DialogHeader><DialogTitle>{editingId ? '编辑任务' : '新建任务'}</DialogTitle></DialogHeader>
          <div className="space-y-4">
            <div><Label>任务名称 *</Label><Input value={form.title} onChange={e => setForm({ ...form, title: e.target.value })} /></div>
            <div>
              <Label>所属客户</Label>
              <NativeSelect
                value={form.customer_id}
                onChange={v => setForm({ ...form, customer_id: v })}
                placeholder="选择客户（可选）"
                options={[{ value: '', label: '选择客户（可选）' }, ...customers.map(c => ({ value: String(c.id), label: c.business_name }))]}
              />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div><Label>负责人</Label><Input value={form.assignee_name} onChange={e => setForm({ ...form, assignee_name: e.target.value })} /></div>
              <div><Label>协作人</Label><Input value={form.collaborator_names} onChange={e => setForm({ ...form, collaborator_names: e.target.value })} placeholder="逗号分隔" /></div>
            </div>
            <div className="grid grid-cols-3 gap-4">
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
              <div><Label>截止日期</Label><Input type="date" value={form.due_date} onChange={e => setForm({ ...form, due_date: e.target.value })} /></div>
            </div>
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