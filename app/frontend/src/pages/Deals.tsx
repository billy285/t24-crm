import { useState, useEffect } from 'react';
import { client } from '../lib/api';
import { useRole } from '../lib/role-context';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Textarea } from '@/components/ui/textarea';
import { Switch } from '@/components/ui/switch';
import { toast } from 'sonner';
import { Plus, Search, Edit, Trash2 } from 'lucide-react';
import { NativeSelect } from '@/components/ui/native-select';
import ExportButton from '@/components/ExportButton';
import ConfirmDialog from '@/components/ConfirmDialog';

export default function Deals() {
  const { employee, dataScope } = useRole();
  const [deals, setDeals] = useState<any[]>([]);
  const [customers, setCustomers] = useState<any[]>([]);
  const [options, setOptions] = useState<Record<string, any[]>>({});
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [filterProduct, setFilterProduct] = useState('all');
  const [filterPaid, setFilterPaid] = useState('all');
  const [filterCycle, setFilterCycle] = useState('all');
  const [filterDateFrom, setFilterDateFrom] = useState('');
  const [filterDateTo, setFilterDateTo] = useState('');
  const [showForm, setShowForm] = useState(false);
  const [saving, setSaving] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<any>(null);
  const [deleting, setDeleting] = useState(false);
  const emptyDealForm = {
    customer_id: '', product_type: 'ordering_system', package_name: '',
    billing_cycle: 'monthly', deal_amount: '', is_paid: false,
    service_start_date: '', service_end_date: '', needs_group: false,
    is_handed_over: false, is_transferred_ops: false, notes: '',
  };
  const [form, setForm] = useState(emptyDealForm);

  useEffect(() => {
    loadData();
    loadOptions();
  }, []);

  const loadOptions = async () => {
    try {
      const res = await client.get('/api/v1/system-options');
      const groupedOptions: Record<string, any[]> = {};
      (res?.data || []).forEach((opt: any) => {
        if (!groupedOptions[opt.category]) {
          groupedOptions[opt.category] = [];
        }
        groupedOptions[opt.category].push(opt);
      });
      setOptions(groupedOptions);
    } catch (err) {
      console.error("Failed to load options", err);
    }
  };

  const loadData = async () => {
    setLoading(true);
    try {
      const [dRes, cRes] = await Promise.all([
        client.entities.deals.query({ limit: 200, sort: '-deal_date' }),
        client.entities.customers.query({ limit: 200 }),
      ]);
      let dealItems = dRes?.data?.items || [];
      const custItems = cRes?.data?.items || [];

      if (dataScope === 'self' && employee) {
        const myCustomerIds = new Set(custItems.filter((c: any) => c.sales_employee_id === employee.id).map((c: any) => c.id));
        dealItems = dealItems.filter((d: any) => myCustomerIds.has(d.customer_id));
      }

      setDeals(dealItems);
      setCustomers(custItems);
    } catch (err) { console.error(err); }
    finally { setLoading(false); }
  };

  const customerMap = new Map<number, any>();
  customers.forEach(c => customerMap.set(c.id, c));

  const optionMap = new Map<string, string>();
  Object.values(options).flat().forEach(o => optionMap.set(o.key, o.label));

  const filtered = deals.filter(d => {
    if (search) {
      const q = search.toLowerCase();
      const cust = customerMap.get(d.customer_id);
      if (!(d.customer_name?.toLowerCase().includes(q) || d.package_name?.toLowerCase().includes(q) || cust?.phone?.toLowerCase().includes(q))) return false;
    }
    if (filterProduct !== 'all' && d.product_type !== filterProduct) return false;
    if (filterPaid !== 'all') {
      if (filterPaid === 'paid' && !d.is_paid) return false;
      if (filterPaid === 'unpaid' && d.is_paid) return false;
    }
    if (filterCycle !== 'all' && d.billing_cycle !== filterCycle) return false;
    if (filterDateFrom && (d.deal_date?.slice(0, 10) || '') < filterDateFrom) return false;
    if (filterDateTo && (d.deal_date?.slice(0, 10) || '') > filterDateTo) return false;
    return true;
  });

  const totalAmount = filtered.reduce((s, d) => s + (d.deal_amount || 0), 0);

  const openEditDeal = (d: any) => {
    setForm({ ...emptyDealForm, ...d, customer_id: String(d.customer_id), deal_amount: String(d.deal_amount) });
    setEditingId(d.id);
    setShowForm(true);
  };

  const handleSave = async () => {
    if (!form.customer_id || !form.package_name || !form.deal_amount) {
      toast.error('请填写必填字段');
      return;
    }
    setSaving(true);
    try {
      const cust = customers.find(c => c.id === Number(form.customer_id));
      const payload = { ...form, customer_id: Number(form.customer_id), deal_amount: Number(form.deal_amount), customer_name: cust?.business_name || '' };

      if (editingId) {
        await client.entities.deals.update({ id: String(editingId), data: payload });
        toast.success('成交记录已更新');
      } else {
        await client.entities.deals.create({ data: { ...payload, deal_date: new Date().toISOString() } });
        toast.success('成交记录已创建');
      }
      setShowForm(false);
      loadData();
    } catch (err) { toast.error('保存失败'); console.error(err); }
    finally { setSaving(false); }
  };

  const handleDeleteDeal = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await client.entities.deals.delete({ id: String(deleteTarget.id) });
      toast.success('成交记录已删除');
      setDeleteTarget(null);
      loadData();
    } catch (err) { toast.error('删除失败'); console.error(err); }
    finally { setDeleting(false); }
  };

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <h2 className="text-xl font-semibold">成交管理 ({filtered.length} / {deals.length}) - 总额: ${totalAmount.toLocaleString()}</h2>
        <Button onClick={() => { setForm(emptyDealForm); setEditingId(null); setShowForm(true); }}><Plus className="w-4 h-4 mr-2" />录入成交</Button>
      </div>

      <Card><CardContent className="p-2 flex gap-2">
        <Search className="w-5 h-5 text-gray-400" />
        <Input placeholder="搜索客户、套餐、电话..." value={search} onChange={e => setSearch(e.target.value)} className="border-0" />
        <NativeSelect value={filterProduct} onChange={setFilterProduct} options={[{ value: 'all', label: '全部产品' }, ...(options.deal_product_type || []).map(o => ({ value: o.key, label: o.label }))]} />
        <NativeSelect value={filterPaid} onChange={setFilterPaid} options={[{ value: 'all', label: '全部状态' }, ...(options.deal_payment_status || []).map(o => ({ value: o.key, label: o.label }))]} />
        <NativeSelect value={filterCycle} onChange={setFilterCycle} options={[{ value: 'all', label: '全部周期' }, ...(options.deal_billing_cycle || []).map(o => ({ value: o.key, label: o.label }))]} />
        <Input type="date" value={filterDateFrom} onChange={e => setFilterDateFrom(e.target.value)} />
        <Input type="date" value={filterDateTo} onChange={e => setFilterDateTo(e.target.value)} />
      </CardContent></Card>

      {loading ? <p>加载中...</p> : (
        <Card><CardContent>
          <table className="w-full text-sm">
            <thead><tr className="border-b">{['客户', '套餐', '产品类型', '金额', '周期', '成交日', '付款', '操作'].map(h => <th key={h} className="p-2 text-left font-medium">{h}</th>)}</tr></thead>
            <tbody>{filtered.map(d => (
              <tr key={d.id} className="border-b hover:bg-gray-50">
                <td className="p-2">{d.customer_name}</td>
                <td className="p-2">{d.package_name}</td>
                <td className="p-2"><Badge variant="secondary">{optionMap.get(d.product_type) || d.product_type}</Badge></td>
                <td className="p-2 font-bold text-green-600">${d.deal_amount}</td>
                <td className="p-2">{optionMap.get(d.billing_cycle) || d.billing_cycle}</td>
                <td className="p-2">{d.deal_date?.slice(0, 10)}</td>
                <td className="p-2">{d.is_paid ? <Badge className="text-green-700 bg-green-100">已付</Badge> : <Badge className="text-red-700 bg-red-100">未付</Badge>}</td>
                <td className="p-2 flex gap-1">
                  <Button size="sm" variant="ghost" onClick={() => openEditDeal(d)}><Edit className="w-4 h-4" /></Button>
                  <Button size="sm" variant="ghost" className="text-red-500" onClick={() => setDeleteTarget(d)}><Trash2 className="w-4 h-4" /></Button>
                </td>
              </tr>
            ))}</tbody>
          </table>
        </CardContent></Card>
      )}

      <Dialog open={showForm} onOpenChange={setShowForm}>
        <DialogContent>
          <DialogHeader><DialogTitle>{editingId ? '编辑成交' : '录入成交'}</DialogTitle></DialogHeader>
          <div className="space-y-3 py-4">
            <Label>选择客户 *</Label>
            <NativeSelect value={form.customer_id} onChange={v => setForm({ ...form, customer_id: v })} options={customers.map(c => ({ value: c.id, label: c.business_name }))} />
            <div className="grid grid-cols-2 gap-4">
              <div><Label>产品类型</Label><NativeSelect value={form.product_type} onChange={v => setForm({ ...form, product_type: v })} options={(options.deal_product_type || []).map(o => ({ value: o.key, label: o.label }))} /></div>
              <div><Label>服务周期</Label><NativeSelect value={form.billing_cycle} onChange={v => setForm({ ...form, billing_cycle: v })} options={(options.deal_billing_cycle || []).map(o => ({ value: o.key, label: o.label }))} /></div>
            </div>
            <Label>套餐名称 *</Label><Input value={form.package_name} onChange={e => setForm({ ...form, package_name: e.target.value })} />
            <Label>成交金额 *</Label><Input type="number" value={form.deal_amount} onChange={e => setForm({ ...form, deal_amount: e.target.value })} />
            <div className="grid grid-cols-2 gap-4">
              <div><Label>服务开始</Label><Input type="date" value={form.service_start_date} onChange={e => setForm({ ...form, service_start_date: e.target.value })} /></div>
              <div><Label>服务结束</Label><Input type="date" value={form.service_end_date} onChange={e => setForm({ ...form, service_end_date: e.target.value })} /></div>
            </div>
            <div className="flex gap-4"><Switch checked={form.is_paid} onCheckedChange={v => setForm({ ...form, is_paid: v })} /><Label>已付款</Label></div>
            <Label>备注</Label><Textarea value={form.notes} onChange={e => setForm({ ...form, notes: e.target.value })} />
          </div>
          <div className="flex justify-end gap-2"><Button variant="outline" onClick={() => setShowForm(false)}>取消</Button><Button onClick={handleSave} disabled={saving}>{saving ? '保存中...' : '保存'}</Button></div>
        </DialogContent>
      </Dialog>

      <ConfirmDialog open={!!deleteTarget} onOpenChange={() => setDeleteTarget(null)} title="确认删除" description={`确定删除这笔成交记录吗？`} onConfirm={handleDeleteDeal} loading={deleting} />
    </div>
  );
}
