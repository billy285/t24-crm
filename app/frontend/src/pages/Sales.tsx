import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { client } from '../lib/api';
import { useRole } from '../lib/role-context';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Textarea } from '@/components/ui/textarea';
import { toast } from 'sonner';
import { Plus, Search, AlertCircle, Edit, Trash2, ExternalLink } from 'lucide-react';
import { NativeSelect } from '@/components/ui/native-select';
import ConfirmDialog from '@/components/ConfirmDialog';
import ExportButton from '@/components/ExportButton';

const stageLabels: Record<string, string> = {
  new_lead: '新线索', contacted: '已联系', communicating: '沟通中', quoted: '已报价',
  considering: '考虑中', pending_close: '待成交', closed: '已成交', not_closed: '未成交',
  lost: '流失', follow_later: '后续再跟进',
};
const stageColors: Record<string, string> = {
  new_lead: 'bg-blue-100 text-blue-700', contacted: 'bg-sky-100 text-sky-700',
  communicating: 'bg-amber-100 text-amber-700', quoted: 'bg-purple-100 text-purple-700',
  considering: 'bg-orange-100 text-orange-700', pending_close: 'bg-lime-100 text-lime-700',
  closed: 'bg-green-100 text-green-700', not_closed: 'bg-slate-100 text-slate-600',
  lost: 'bg-red-100 text-red-700', follow_later: 'bg-gray-100 text-gray-600',
};
const methodLabels: Record<string, string> = { phone: '电话', wechat: '微信', sms: '短信', email: '邮件' };

export default function Sales() {
  const { role, employee, hasPermission, dataScope } = useRole();
  const navigate = useNavigate();
  const [followUps, setFollowUps] = useState<any[]>([]);
  const [customers, setCustomers] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [filterStage, setFilterStage] = useState('all');
  const [showForm, setShowForm] = useState(false);
  const [saving, setSaving] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<any>(null);
  const [deleting, setDeleting] = useState(false);
  const emptyFollowForm = {
    customer_id: '', contact_method: 'phone', content: '', customer_needs: '',
    customer_pain_points: '', has_quoted: false, quote_plan: '', close_probability: 30,
    stage: 'new_lead', next_follow_date: '',
  };
  const [form, setForm] = useState(emptyFollowForm);

  useEffect(() => { loadData(); }, []);

  const loadData = async () => {
    try {
      const [fuRes, cRes] = await Promise.all([
        client.entities.follow_ups.query({ limit: 200, sort: '-created_at' }),
        client.entities.customers.query({ limit: 200 }),
      ]);
      let fus = fuRes?.data?.items || [];
      const custs = cRes?.data?.items || [];

      // Filter by data scope: 'self' means only show own follow-ups
      if (dataScope === 'self' && employee) {
        fus = fus.filter((f: any) => f.employee_name === employee.name);
      }

      setFollowUps(fus);
      setCustomers(custs);
    } catch (err) { console.error(err); }
    finally { setLoading(false); }
  };

  const customerMap = Object.fromEntries(customers.map(c => [c.id, c]));

  const filtered = followUps.filter(f => {
    const cust = customerMap[f.customer_id];
    const matchSearch = !search || cust?.business_name?.includes(search) || f.content?.includes(search) || f.employee_name?.includes(search);
    const matchStage = filterStage === 'all' || f.stage === filterStage;
    return matchSearch && matchStage;
  });

  // Reminders: overdue follow-ups
  const now = new Date();
  const overdueFollowUps = followUps.filter(f => f.next_follow_date && new Date(f.next_follow_date) < now && f.stage !== 'closed' && f.stage !== 'lost');

  const openEditFollow = (f: any) => {
    setForm({
      customer_id: String(f.customer_id || ''),
      contact_method: f.contact_method || 'phone',
      content: f.content || '',
      customer_needs: f.customer_needs || '',
      customer_pain_points: f.customer_pain_points || '',
      has_quoted: f.has_quoted || false,
      quote_plan: f.quote_plan || '',
      close_probability: f.close_probability || 30,
      stage: f.stage || 'new_lead',
      next_follow_date: f.next_follow_date?.slice(0, 10) || '',
    });
    setEditingId(f.id);
    setShowForm(true);
  };

  const handleSave = async () => {
    if (!form.customer_id || !form.content) {
      toast.error('请选择客户并填写跟进内容');
      return;
    }
    setSaving(true);
    try {
      const payload = {
        customer_id: Number(form.customer_id),
        contact_method: form.contact_method,
        content: form.content,
        customer_needs: form.customer_needs,
        customer_pain_points: form.customer_pain_points,
        has_quoted: form.has_quoted,
        quote_plan: form.quote_plan,
        close_probability: form.close_probability,
        stage: form.stage,
        next_follow_date: form.next_follow_date || null,
      };
      if (editingId) {
        await client.entities.follow_ups.update({ id: String(editingId), data: payload });
        toast.success('跟进记录已更新');
      } else {
        await client.entities.follow_ups.create({
          data: {
            ...payload,
            employee_name: employee?.name || '',
            created_at: new Date().toISOString(),
          },
        });
        toast.success('跟进记录已添加');
      }
      setShowForm(false);
      setEditingId(null);
      setForm(emptyFollowForm);
      loadData();
    } catch (err) { toast.error('保存失败'); console.error(err); }
    finally { setSaving(false); }
  };

  const handleDeleteFollow = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await client.entities.follow_ups.delete({ id: String(deleteTarget.id) });
      toast.success('跟进记录已删除');
      setDeleteTarget(null);
      loadData();
    } catch (err) { toast.error('删除失败'); console.error(err); }
    finally { setDeleting(false); }
  };

  // Navigate to customer detail page
  const goToCustomerDetail = (customerId: number) => {
    navigate(`/customers?detail=${customerId}`);
  };

  // Export data
  const exportData = filtered.map(f => {
    const cust = customerMap[f.customer_id];
    return {
      customer_name: cust?.business_name || `客户#${f.customer_id}`,
      contact_method_label: methodLabels[f.contact_method] || f.contact_method,
      stage_label: stageLabels[f.stage] || f.stage,
      content: f.content,
      customer_needs: f.customer_needs || '',
      customer_pain_points: f.customer_pain_points || '',
      close_probability: `${f.close_probability}%`,
      has_quoted_label: f.has_quoted ? '是' : '否',
      quote_plan: f.quote_plan || '',
      employee_name: f.employee_name || '',
      next_follow_date: f.next_follow_date?.slice(0, 10) || '',
      created_at: f.created_at?.slice(0, 16) || '',
    };
  });

  return (
    <div className="space-y-4">
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
        <h2 className="text-xl font-semibold text-slate-800">销售跟进</h2>
        <div className="flex gap-2">
          <ExportButton
            data={exportData}
            columns={[
              { key: 'customer_name', label: '客户名称' },
              { key: 'stage_label', label: '跟进阶段' },
              { key: 'contact_method_label', label: '跟进方式' },
              { key: 'content', label: '跟进内容' },
              { key: 'customer_needs', label: '客户需求' },
              { key: 'customer_pain_points', label: '客户痛点' },
              { key: 'close_probability', label: '成交概率' },
              { key: 'has_quoted_label', label: '是否报价' },
              { key: 'quote_plan', label: '报价方案' },
              { key: 'employee_name', label: '跟进人' },
              { key: 'next_follow_date', label: '下次跟进日期' },
              { key: 'created_at', label: '创建时间' },
            ]}
            filename={`跟进记录_${new Date().toISOString().slice(0, 10)}`}
            sheetName="跟进记录"
          />
          <Button onClick={() => { setForm(emptyFollowForm); setEditingId(null); setShowForm(true); }} className="bg-blue-600 hover:bg-blue-700">
            <Plus className="w-4 h-4 mr-1" /> 新增跟进
          </Button>
        </div>
      </div>

      {/* Reminders */}
      {overdueFollowUps.length > 0 && (
        <Card className="border-amber-200 bg-amber-50">
          <CardContent className="p-3">
            <div className="flex items-center gap-2 text-amber-700 mb-2">
              <AlertCircle className="w-4 h-4" />
              <span className="text-sm font-medium">跟进提醒 ({overdueFollowUps.length})</span>
            </div>
            <div className="space-y-1">
              {overdueFollowUps.slice(0, 3).map(f => (
                <p key={f.id} className="text-xs text-amber-600">
                  <button
                    className="text-amber-700 font-medium hover:underline cursor-pointer"
                    onClick={() => goToCustomerDetail(f.customer_id)}
                  >
                    {customerMap[f.customer_id]?.business_name || '未知客户'}
                  </button>
                  {' '}- 计划跟进日期: {f.next_follow_date?.slice(0, 10)}
                </p>
              ))}
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
              <Input placeholder="搜索客户名称、跟进内容..." value={search} onChange={e => setSearch(e.target.value)} className="pl-9" />
            </div>
            <NativeSelect
              value={filterStage}
              onChange={setFilterStage}
              className="w-[160px]"
              options={[{ value: 'all', label: '全部阶段' }, ...Object.entries(stageLabels).map(([k, v]) => ({ value: k, label: v }))]}
            />
          </div>
        </CardContent>
      </Card>

      {/* Follow-up list */}
      <Card className="border-slate-200">
        <CardContent className="p-0">
          {loading ? (
            <div className="flex items-center justify-center py-12">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600" />
            </div>
          ) : filtered.length === 0 ? (
            <p className="text-center text-slate-400 py-12">暂无跟进记录</p>
          ) : (
            <div className="divide-y divide-slate-100">
              {filtered.map(f => {
                const cust = customerMap[f.customer_id];
                return (
                  <div key={f.id} className="p-4 hover:bg-slate-50 transition-colors">
                    <div className="flex items-start justify-between mb-2">
                      <div className="flex items-center gap-1">
                        <button
                          className="font-medium text-sm text-blue-600 hover:text-blue-800 hover:underline cursor-pointer flex items-center gap-1"
                          onClick={() => goToCustomerDetail(f.customer_id)}
                          title="点击查看客户详情"
                        >
                          {cust?.business_name || `客户#${f.customer_id}`}
                          <ExternalLink className="w-3 h-3 opacity-50" />
                        </button>
                        <span className="text-xs text-slate-400 ml-2">{f.created_at?.slice(0, 16)}</span>
                      </div>
                      <div className="flex items-center gap-2">
                        <Badge className={`text-xs ${stageColors[f.stage]}`}>{stageLabels[f.stage] || f.stage}</Badge>
                        <Badge variant="outline" className="text-xs">{methodLabels[f.contact_method] || f.contact_method}</Badge>
                        <Button size="sm" variant="ghost" className="h-6 w-6 p-0 text-slate-400 hover:text-blue-600" onClick={() => openEditFollow(f)}><Edit className="w-3 h-3" /></Button>
                        <Button size="sm" variant="ghost" className="h-6 w-6 p-0 text-slate-400 hover:text-red-600" onClick={() => setDeleteTarget(f)}><Trash2 className="w-3 h-3" /></Button>
                      </div>
                    </div>
                    <p className="text-sm text-slate-700 mb-1">{f.content}</p>
                    <div className="flex flex-wrap gap-3 text-xs text-slate-500">
                      {f.employee_name && <span>跟进人: {f.employee_name}</span>}
                      <span>成交概率: {f.close_probability}%</span>
                      {f.has_quoted && <span className="text-green-600">已报价: {f.quote_plan}</span>}
                      {f.next_follow_date && <span className="text-amber-600">下次跟进: {f.next_follow_date.slice(0, 10)}</span>}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </CardContent>
      </Card>

      <ConfirmDialog
        open={!!deleteTarget}
        onOpenChange={(v) => { if (!v) setDeleteTarget(null); }}
        title="确认删除跟进记录"
        description="确定要删除此跟进记录吗？此操作不可撤销。建议先导出数据备份。"
        onConfirm={handleDeleteFollow}
        loading={deleting}
      />

      {/* Add/Edit follow-up dialog */}
      <Dialog open={showForm} onOpenChange={(v) => { setShowForm(v); if (!v) { setEditingId(null); setForm(emptyFollowForm); } }}>
        <DialogContent className="max-w-lg max-h-[85vh] overflow-y-auto">
          <DialogHeader><DialogTitle>{editingId ? '编辑跟进记录' : '新增跟进记录'}</DialogTitle></DialogHeader>
          <div className="space-y-4">
            <div>
              <Label>选择客户 *</Label>
              <NativeSelect
                value={form.customer_id}
                onChange={v => setForm({ ...form, customer_id: v })}
                placeholder="请选择客户"
                options={[{ value: '', label: '请选择客户' }, ...(dataScope === 'self' && employee
                  ? customers.filter(c => c.sales_person === employee.name || c.sales_employee_id === employee.id)
                  : customers
                ).map(c => ({ value: String(c.id), label: `${c.business_name} - ${c.contact_name}` }))]}
              />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <Label>跟进方式</Label>
                <NativeSelect
                  value={form.contact_method}
                  onChange={v => setForm({ ...form, contact_method: v })}
                  options={Object.entries(methodLabels).map(([k, v]) => ({ value: k, label: v }))}
                />
              </div>
              <div>
                <Label>跟进阶段</Label>
                <NativeSelect
                  value={form.stage}
                  onChange={v => setForm({ ...form, stage: v })}
                  options={Object.entries(stageLabels).map(([k, v]) => ({ value: k, label: v }))}
                />
              </div>
            </div>
            <div><Label>跟进内容 *</Label><Textarea value={form.content} onChange={e => setForm({ ...form, content: e.target.value })} rows={3} /></div>
            <div><Label>客户需求</Label><Input value={form.customer_needs} onChange={e => setForm({ ...form, customer_needs: e.target.value })} /></div>
            <div><Label>客户痛点</Label><Input value={form.customer_pain_points} onChange={e => setForm({ ...form, customer_pain_points: e.target.value })} /></div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <Label>成交概率 ({form.close_probability}%)</Label>
                <Input type="range" min={0} max={100} step={10} value={form.close_probability} onChange={e => setForm({ ...form, close_probability: Number(e.target.value) })} />
              </div>
              <div>
                <Label>下次跟进日期</Label>
                <Input type="date" value={form.next_follow_date} onChange={e => setForm({ ...form, next_follow_date: e.target.value })} />
              </div>
            </div>
            <div className="flex items-center gap-2">
              <input type="checkbox" checked={form.has_quoted} onChange={e => setForm({ ...form, has_quoted: e.target.checked })} className="rounded" />
              <Label>已报价</Label>
              {form.has_quoted && <Input placeholder="报价方案" value={form.quote_plan} onChange={e => setForm({ ...form, quote_plan: e.target.value })} className="flex-1" />}
            </div>
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