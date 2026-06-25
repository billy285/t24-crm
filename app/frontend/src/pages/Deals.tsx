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
import { saveRemoteAppConfig } from '../lib/app-config';
import { buildOptionKey, serializeDictEntries, useBusinessDicts, useDictConfig } from '../lib/dict-config';

function parseMultiValue(value?: string | null) {
  return (value || '').split(',').map(item => item.trim()).filter(Boolean);
}

function parseDealPackageLabels(value?: string | null) {
  return (value || '').split(/[、,，]/).map(item => item.trim()).filter(Boolean);
}

function getTodayDateInput() {
  return new Date().toISOString().slice(0, 10);
}

function buildEmptyDealForm() {
  return {
    customer_id: '',
    product_type: 'ordering_system',
    package_name: '',
    package_keys: [] as string[],
    billing_cycle: 'monthly',
    deal_amount: '',
    deal_date: getTodayDateInput(),
    is_paid: false,
    service_start_date: '',
    service_end_date: '',
    needs_group: false,
    is_handed_over: false,
    is_transferred_ops: false,
    notes: '',
  };
}

export default function Deals() {
  const { employee, dataScope, hasPermission } = useRole();
  const dictConfig = useDictConfig();
  const { products: productLabels, billingCycles: cycleLabels, customerPackages: customerPackageLabels } = useBusinessDicts();
  const [deals, setDeals] = useState<any[]>([]);
  const [customers, setCustomers] = useState<any[]>([]);
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
  const [showPackageManager, setShowPackageManager] = useState(false);
  const [newPackageName, setNewPackageName] = useState('');
  const [packageDrafts, setPackageDrafts] = useState<Array<{ key: string; label: string }>>([]);
  const [savingPackages, setSavingPackages] = useState(false);
  const [packageOverrideLabels, setPackageOverrideLabels] = useState<Record<string, string>>({});
  const emptyDealForm = buildEmptyDealForm();
  const [form, setForm] = useState(emptyDealForm);
  const dealPackageLabels = { ...customerPackageLabels, ...packageOverrideLabels };
  const dealPackageOptions = Object.entries(dealPackageLabels).map(([value, label]) => ({ value, label }));

  const loadData = async () => {
    try {
      const [dRes, cRes] = await Promise.all([
        client.entities.deals.query({ limit: 200, sort: '-deal_date' }),
        client.entities.customers.query({ limit: 200 }),
      ]);
      let dealItems = dRes?.data?.items || [];
      const custItems = cRes?.data?.items || [];

      // Filter deals by data scope: sales role only sees their own deals
      if (dataScope === 'self' && employee) {
        // Build a set of customer IDs that belong to this sales person
        const myCustomerIds = new Set(
          custItems
            .filter((c: any) => c.sales_person === employee.name || c.sales_employee_id === employee.id)
            .map((c: any) => c.id)
        );
        dealItems = dealItems.filter((d: any) =>
          d.sales_name === employee.name || myCustomerIds.has(d.customer_id)
        );
      }

      setDeals(dealItems);
      setCustomers(custItems);
    } catch (err) { console.error(err); }
    finally { setLoading(false); }
  };

  useEffect(() => {
    setLoading(true);
    void loadData();
  }, [dataScope, employee?.id, employee?.name]);

  // Build a customer lookup map for quick access to phone, email, zip etc.
  const customerMap = new Map<number, any>();
  customers.forEach(c => customerMap.set(c.id, c));

  const filtered = deals.filter(d => {
    // Text search
    if (search) {
      const q = search.toLowerCase();
      const cust = customerMap.get(d.customer_id);
      const matchSearch =
        d.customer_name?.toLowerCase().includes(q) ||
        d.package_name?.toLowerCase().includes(q) ||
        d.sales_name?.toLowerCase().includes(q) ||
        cust?.phone?.toLowerCase().includes(q) ||
        cust?.email?.toLowerCase().includes(q) ||
        cust?.address?.toLowerCase().includes(q) ||
        cust?.city?.toLowerCase().includes(q) ||
        cust?.customer_code?.toLowerCase().includes(q);
      if (!matchSearch) return false;
    }
    // Product type filter
    if (filterProduct !== 'all' && d.product_type !== filterProduct) return false;
    // Payment status filter
    if (filterPaid !== 'all') {
      if (filterPaid === 'paid' && !d.is_paid) return false;
      if (filterPaid === 'unpaid' && d.is_paid) return false;
    }
    // Billing cycle filter
    if (filterCycle !== 'all' && d.billing_cycle !== filterCycle) return false;
    // Date range filter
    const dealDate = d.deal_date?.slice(0, 10) || '';
    if (filterDateFrom && dealDate < filterDateFrom) return false;
    if (filterDateTo && dealDate > filterDateTo) return false;
    return true;
  });

  const hasActiveFilters = filterProduct !== 'all' || filterPaid !== 'all' || filterCycle !== 'all' || filterDateFrom || filterDateTo;

  const clearFilters = () => {
    setFilterProduct('all');
    setFilterPaid('all');
    setFilterCycle('all');
    setFilterDateFrom('');
    setFilterDateTo('');
    setSearch('');
  };

  const totalAmount = deals.reduce((s, d) => s + (d.deal_amount || 0), 0);

  useEffect(() => {
    if (!showForm && !editingId) {
      setPackageOverrideLabels({});
    }
  }, [showForm, editingId]);

  const openPackageManager = () => {
    setPackageDrafts(Object.entries(customerPackageLabels).map(([key, label]) => ({ key, label })));
    setNewPackageName('');
    setShowPackageManager(true);
  };

  const handleAddPackageDraft = () => {
    const label = newPackageName.trim();
    if (!label) {
      toast.error('请输入套餐名称');
      return;
    }
    if (packageDrafts.some(item => item.label.trim() === label)) {
      toast.error('该套餐已存在');
      return;
    }
    let key = buildOptionKey(label);
    while (packageDrafts.some(item => item.key === key)) {
      key = `${key}_${Date.now()}`;
    }
    setPackageDrafts(prev => [...prev, { key, label }]);
    setNewPackageName('');
  };

  const handleRemovePackageDraft = (key: string) => {
    if (packageDrafts.length <= 1) {
      toast.error('至少保留一个套餐');
      return;
    }
    const label = packageDrafts.find(item => item.key === key)?.label || customerPackageLabels[key];
    const usedInDeals = !!label && deals.some(item => parseDealPackageLabels(item.package_name).includes(label));
    const usedInCustomers = customers.some(item => parseMultiValue(item.interested_packages).includes(key));
    if (usedInDeals || usedInCustomers) {
      toast.error('该套餐已有客户或成交记录在使用，请先调整历史数据后再删除');
      return;
    }
    const remaining = packageDrafts.filter(item => item.key !== key);
    setPackageDrafts(remaining);
    if (form.package_keys.includes(key)) {
      setForm(prev => ({ ...prev, package_keys: prev.package_keys.filter(item => item !== key) }));
    }
  };

  const handleSavePackages = async () => {
    const pendingLabel = newPackageName.trim();
    let draftsToSave = packageDrafts;
    if (pendingLabel) {
      if (packageDrafts.some(item => item.label.trim() === pendingLabel)) {
        toast.error('该套餐已存在');
        return;
      }
      let key = buildOptionKey(pendingLabel);
      while (packageDrafts.some(item => item.key === key)) {
        key = `${key}_${Date.now()}`;
      }
      draftsToSave = [...packageDrafts, { key, label: pendingLabel }];
    }

    const normalizedEntries = draftsToSave.reduce<Record<string, string>>((acc, item) => {
      const label = item.label.trim();
      if (label) {
        acc[item.key] = label;
      }
      return acc;
    }, {});
    const labels = Object.values(normalizedEntries);
    if (labels.length === 0) {
      toast.error('请至少保留一个套餐');
      return;
    }
    if (new Set(labels).size !== labels.length) {
      toast.error('套餐名称不能重复');
      return;
    }

    setSavingPackages(true);
    try {
      await saveRemoteAppConfig('dict_config', {
        ...dictConfig,
        customerPackages: serializeDictEntries(normalizedEntries),
      });
      const availableKeys = new Set(Object.keys(normalizedEntries));
      setPackageDrafts(Object.entries(normalizedEntries).map(([key, label]) => ({ key, label })));
      setForm(prev => ({
        ...prev,
        package_keys: prev.package_keys.filter(key => availableKeys.has(key) || packageOverrideLabels[key]),
      }));
      setShowPackageManager(false);
      setNewPackageName('');
      toast.success('套餐配置已更新');
    } catch (err: any) {
      const detail = err?.data?.detail || err?.message || '保存套餐配置失败';
      toast.error(detail);
    } finally {
      setSavingPackages(false);
    }
  };

  const togglePackageKey = (key: string) => {
    setForm(prev => ({
      ...prev,
      package_keys: prev.package_keys.includes(key)
        ? prev.package_keys.filter(item => item !== key)
        : [...prev.package_keys, key],
    }));
  };

  const openEditDeal = (d: any) => {
    const selectedLabels = parseDealPackageLabels(d.package_name);
    const labelToKey = new Map<string, string>();
    Object.entries(customerPackageLabels).forEach(([key, label]) => labelToKey.set(label, key));
    const customLabels: Record<string, string> = {};
    const packageKeys = selectedLabels.map((label, index) => {
      const matchedKey = labelToKey.get(label);
      if (matchedKey) return matchedKey;
      let tempKey = buildOptionKey(label || `package_${index + 1}`);
      while (customerPackageLabels[tempKey] || customLabels[tempKey]) {
        tempKey = `${tempKey}_${index + 1}`;
      }
      customLabels[tempKey] = label;
      return tempKey;
    });
    setPackageOverrideLabels(customLabels);
    setForm({
      customer_id: String(d.customer_id || ''),
      product_type: d.product_type || 'ordering_system',
      package_name: d.package_name || '',
      package_keys: packageKeys,
      billing_cycle: d.billing_cycle || 'monthly',
      deal_amount: String(d.deal_amount || ''),
      deal_date: d.deal_date?.slice(0, 10) || getTodayDateInput(),
      is_paid: d.is_paid || false,
      service_start_date: d.service_start_date?.slice(0, 10) || '',
      service_end_date: d.service_end_date?.slice(0, 10) || '',
      needs_group: d.needs_group || false,
      is_handed_over: d.is_handed_over || false,
      is_transferred_ops: d.is_transferred_ops || false,
      notes: d.notes || '',
    });
    setEditingId(d.id);
    setShowForm(true);
  };

  const handleSave = async () => {
    if (!form.customer_id || form.package_keys.length === 0 || !form.deal_amount) {
      toast.error('请填写必填字段');
      return;
    }
    setSaving(true);
    try {
      const cust = customers.find(c => c.id === Number(form.customer_id));
      const now = new Date().toISOString();
      const payload = {
        customer_id: Number(form.customer_id),
        customer_name: cust?.business_name || '',
        sales_name: cust?.sales_person || '',
        product_type: form.product_type,
        package_name: form.package_keys.map(key => dealPackageLabels[key] || key).filter(Boolean).join('、'),
        billing_cycle: form.billing_cycle,
        deal_amount: Number(form.deal_amount),
        deal_date: form.deal_date || null,
        is_paid: form.is_paid,
        service_start_date: form.service_start_date || null,
        service_end_date: form.service_end_date || null,
        needs_group: form.needs_group,
        is_handed_over: form.is_handed_over,
        is_transferred_ops: form.is_transferred_ops,
        notes: form.notes,
      };

      delete (payload as any).package_keys;

      if (editingId) {
        const updatedDealRes = await client.entities.deals.update({ id: String(editingId), data: payload });
        const updatedDeal = updatedDealRes?.data || { ...payload, id: editingId, updated_at: now };
        setDeals(prev => prev.map(item => (item.id === editingId ? { ...item, ...updatedDeal } : item)));
        toast.success('成交记录已更新');
      } else {
        const createdDealRes = await client.entities.deals.create({ data: { ...payload, created_at: now } });
        const createdDeal = createdDealRes?.data;
        if (createdDeal) {
          setDeals(prev => [createdDeal, ...prev]);
        }
        if (form.service_start_date && form.service_end_date) {
          await client.entities.subscriptions.create({
            data: {
              deal_id: createdDeal?.id || null,
              customer_id: Number(form.customer_id), customer_name: cust?.business_name || '',
              package_name: form.package_keys.map(key => dealPackageLabels[key] || key).filter(Boolean).join('、'), package_price: Number(form.deal_amount),
              billing_cycle: form.billing_cycle, start_date: form.service_start_date,
              end_date: form.service_end_date, auto_renew: false,
              renewal_person: cust?.sales_person || '', status: 'active',
              created_at: now, updated_at: now,
            },
          });
        }
        if (cust) {
          await client.entities.customers.update({ id: String(cust.id), data: { status: 'closed', updated_at: now } });
          setCustomers(prev => prev.map(item => (item.id === cust.id ? { ...item, status: 'closed', updated_at: now } : item)));
        }
        toast.success('成交记录已创建');
      }
      setPackageOverrideLabels({});
      setShowForm(false);
      setEditingId(null);
      setForm(buildEmptyDealForm());
      await loadData();
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
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold text-slate-800">成交管理</h2>
          <p className="text-sm text-slate-500">共 {deals.length} 笔成交，总金额 ${totalAmount.toLocaleString()}</p>
        </div>
        <div className="flex gap-2">
          <ExportButton
            data={filtered.map(d => ({
              ...d,
              product_type_label: productLabels[d.product_type] || d.product_type,
              billing_cycle_label: cycleLabels[d.billing_cycle] || d.billing_cycle,
              is_paid_label: d.is_paid ? '已付' : '未付',
              is_handed_over_label: d.is_handed_over ? '已交接' : '待交接',
              is_transferred_ops_label: d.is_transferred_ops ? '已转运营' : '未转运营',
              deal_date_short: d.deal_date?.slice(0, 10) || '',
              service_start_short: d.service_start_date?.slice(0, 10) || '',
              service_end_short: d.service_end_date?.slice(0, 10) || '',
            }))}
            columns={[
              { key: 'customer_name', label: '客户名称' },
              { key: 'sales_name', label: '销售' },
              { key: 'product_type_label', label: '产品类型' },
              { key: 'package_name', label: '套餐名称' },
              { key: 'deal_amount', label: '成交金额' },
              { key: 'billing_cycle_label', label: '服务周期' },
              { key: 'deal_date_short', label: '成交日期' },
              { key: 'is_paid_label', label: '付款状态' },
              { key: 'is_handed_over_label', label: '交接状态' },
              { key: 'is_transferred_ops_label', label: '转运营' },
              { key: 'service_start_short', label: '服务开始' },
              { key: 'service_end_short', label: '服务到期' },
              { key: 'notes', label: '备注' },
            ]}
            filename={`成交记录_${new Date().toISOString().slice(0, 10)}`}
            sheetName="成交记录"
          />
          <Button onClick={() => { setPackageOverrideLabels({}); setForm(buildEmptyDealForm()); setEditingId(null); setShowForm(true); }} className="bg-blue-600 hover:bg-blue-700">
            <Plus className="w-4 h-4 mr-1" /> 录入成交
          </Button>
        </div>
      </div>

      {/* Search & Filters */}
      <Card className="border-slate-200">
        <CardContent className="p-3 space-y-3">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
            <Input placeholder="搜索客户名称、电话、邮箱、地址、套餐、销售..." value={search} onChange={e => setSearch(e.target.value)} className="pl-9" />
          </div>
          <div className="flex flex-col sm:flex-row gap-3 flex-wrap">
            <NativeSelect
              value={filterProduct}
              onChange={setFilterProduct}
              className="w-[150px]"
              options={[{ value: 'all', label: '全部产品' }, ...Object.entries(productLabels).map(([k, v]) => ({ value: k, label: v }))]}
            />
            <NativeSelect
              value={filterPaid}
              onChange={setFilterPaid}
              className="w-[130px]"
              options={[{ value: 'all', label: '全部状态' }, { value: 'paid', label: '已付款' }, { value: 'unpaid', label: '未付款' }]}
            />
            <NativeSelect
              value={filterCycle}
              onChange={setFilterCycle}
              className="w-[130px]"
              options={[{ value: 'all', label: '全部周期' }, ...Object.entries(cycleLabels).map(([k, v]) => ({ value: k, label: v }))]}
            />
            <div className="flex items-center gap-2">
              <Input type="date" value={filterDateFrom} onChange={e => setFilterDateFrom(e.target.value)} className="w-[145px] text-sm" placeholder="开始日期" />
              <span className="text-slate-400 text-sm">至</span>
              <Input type="date" value={filterDateTo} onChange={e => setFilterDateTo(e.target.value)} className="w-[145px] text-sm" placeholder="结束日期" />
            </div>
            {hasActiveFilters && (
              <Button variant="ghost" size="sm" onClick={clearFilters} className="text-slate-500 hover:text-slate-700 shrink-0">
                清除筛选
              </Button>
            )}
          </div>
          {hasActiveFilters && (
            <p className="text-xs text-slate-500">
              筛选结果：{filtered.length} 条记录，合计 (USD) ${filtered.reduce((s, d) => s + (d.deal_amount || 0), 0).toLocaleString()}
            </p>
          )}
        </CardContent>
      </Card>

      {/* Deals list */}
      <Card className="border-slate-200">
        <CardContent className="p-0">
          {loading ? (
            <div className="flex items-center justify-center py-12">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600" />
            </div>
          ) : filtered.length === 0 ? (
            <p className="text-center text-slate-400 py-12">暂无成交记录</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b bg-slate-50 text-left text-slate-500">
                    <th className="px-4 py-3 font-medium">客户</th>
                    <th className="px-4 py-3 font-medium">套餐</th>
                    <th className="px-4 py-3 font-medium">产品类型</th>
                    <th className="px-4 py-3 font-medium">金额</th>
                    <th className="px-4 py-3 font-medium">周期</th>
                    <th className="px-4 py-3 font-medium hidden md:table-cell">成交日</th>
                    <th className="px-4 py-3 font-medium hidden md:table-cell">付款</th>
                    <th className="px-4 py-3 font-medium hidden lg:table-cell">交接</th>
                    <th className="px-4 py-3 font-medium w-24">操作</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map(d => (
                    <tr key={d.id} className="border-b border-slate-100 hover:bg-slate-50">
                      <td className="px-4 py-3 font-medium">{d.customer_name}</td>
                      <td className="px-4 py-3">{d.package_name}</td>
                      <td className="px-4 py-3"><Badge variant="secondary" className="text-xs">{productLabels[d.product_type] || d.product_type}</Badge></td>
                      <td className="px-4 py-3 font-bold text-green-600">${d.deal_amount}</td>
                      <td className="px-4 py-3 text-slate-500">{cycleLabels[d.billing_cycle] || d.billing_cycle}</td>
                      <td className="px-4 py-3 text-slate-500 hidden md:table-cell">{d.deal_date?.slice(0, 10)}</td>
                      <td className="px-4 py-3 hidden md:table-cell">{d.is_paid ? <Badge className="bg-green-100 text-green-700 text-xs">已付</Badge> : <Badge className="bg-red-100 text-red-700 text-xs">未付</Badge>}</td>
                      <td className="px-4 py-3 hidden lg:table-cell">{d.is_handed_over ? '✅' : '⏳'} {d.is_transferred_ops ? '→运营' : ''}</td>
                      <td className="px-4 py-3">
                        <div className="flex gap-1">
                          <Button size="sm" variant="ghost" className="h-7 w-7 p-0 text-slate-500 hover:text-blue-600" onClick={() => openEditDeal(d)}><Edit className="w-3.5 h-3.5" /></Button>
                          <Button size="sm" variant="ghost" className="h-7 w-7 p-0 text-slate-500 hover:text-red-600" onClick={() => setDeleteTarget(d)}><Trash2 className="w-3.5 h-3.5" /></Button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      <Dialog open={showPackageManager} onOpenChange={(open) => { setShowPackageManager(open); if (!open) setNewPackageName(''); }}>
        <DialogContent className="max-w-lg">
          <DialogHeader><DialogTitle>管理套餐</DialogTitle></DialogHeader>
          <div className="space-y-4 py-2">
            <div className="flex items-center gap-2">
              <Input
                value={newPackageName}
                onChange={e => setNewPackageName(e.target.value)}
                placeholder="新增套餐，例如：Google商家管理"
                onKeyDown={e => {
                  if (e.key === 'Enter') {
                    e.preventDefault();
                    handleAddPackageDraft();
                  }
                }}
              />
              <Button type="button" onClick={handleAddPackageDraft}>
                添加
              </Button>
            </div>
            <div className="max-h-72 space-y-2 overflow-y-auto">
              {packageDrafts.map(item => (
                <div key={item.key} className="flex items-center justify-between gap-3 rounded-md border border-slate-200 bg-slate-50 px-3 py-2">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium text-slate-700">{item.label}</p>
                    <p className="truncate text-xs text-slate-400">{item.key}</p>
                  </div>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="h-8 w-8 p-0 text-slate-500 hover:text-red-600"
                    onClick={() => handleRemovePackageDraft(item.key)}
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
              ))}
            </div>
            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={() => setShowPackageManager(false)}>取消</Button>
              <Button onClick={handleSavePackages} disabled={savingPackages}>
                {savingPackages ? '保存中...' : '保存'}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      <ConfirmDialog
        open={!!deleteTarget}
        onOpenChange={(v) => { if (!v) setDeleteTarget(null); }}
        title="确认删除成交记录"
        description={`确定要删除「${deleteTarget?.customer_name} - ${deleteTarget?.package_name}」的成交记录吗？`}
        onConfirm={handleDeleteDeal}
        loading={deleting}
      />

      {/* Add/Edit deal dialog */}
      <Dialog open={showForm} onOpenChange={(v) => { setShowForm(v); if (!v) { setPackageOverrideLabels({}); setEditingId(null); setForm(buildEmptyDealForm()); } }}>
        <DialogContent className="max-w-lg max-h-[85vh] overflow-y-auto">
          <DialogHeader><DialogTitle>{editingId ? '编辑成交记录' : '录入成交'}</DialogTitle></DialogHeader>
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
                ).map(c => ({ value: String(c.id), label: c.business_name }))]}
              />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <Label>产品类型</Label>
                <NativeSelect
                  value={form.product_type}
                  onChange={v => setForm({ ...form, product_type: v })}
                  options={Object.entries(productLabels).map(([k, v]) => ({ value: k, label: v }))}
                />
              </div>
              <div>
                <Label>服务周期</Label>
                <NativeSelect
                  value={form.billing_cycle}
                  onChange={v => setForm({ ...form, billing_cycle: v })}
                  options={Object.entries(cycleLabels).map(([k, v]) => ({ value: k, label: v }))}
                />
              </div>
            </div>
            <div className="space-y-2">
              <div className="flex items-center justify-between gap-2">
                <Label>套餐名称 *</Label>
                <Button type="button" variant="outline" size="sm" onClick={openPackageManager}>
                  管理套餐
                </Button>
              </div>
              <div className="max-h-56 overflow-y-auto rounded-md border border-slate-200 bg-slate-50 p-3">
                {dealPackageOptions.length === 0 ? (
                  <p className="text-sm text-slate-500">暂无可选套餐，请先添加套餐。</p>
                ) : (
                  <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                    {dealPackageOptions.map(option => (
                      <label key={option.value} className="flex items-center gap-2 rounded-md border border-slate-200 bg-white px-3 py-2 text-sm text-slate-700">
                        <input
                          type="checkbox"
                          checked={form.package_keys.includes(option.value)}
                          onChange={() => togglePackageKey(option.value)}
                        />
                        <span>{option.label}</span>
                      </label>
                    ))}
                  </div>
                )}
              </div>
              <p className="text-xs text-slate-500">
                已选套餐：
                {form.package_keys.length > 0
                  ? ` ${form.package_keys.map(key => dealPackageLabels[key] || key).join('、')}`
                  : ' 暂未选择'}
              </p>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div><Label>成交金额 *</Label><Input type="number" value={form.deal_amount} onChange={e => setForm({ ...form, deal_amount: e.target.value })} placeholder="0.00" /></div>
              <div><Label>成交日期</Label><Input type="date" value={form.deal_date} onChange={e => setForm({ ...form, deal_date: e.target.value })} /></div>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div><Label>服务开始日期</Label><Input type="date" value={form.service_start_date} onChange={e => setForm({ ...form, service_start_date: e.target.value })} /></div>
              <div><Label>服务到期日期</Label><Input type="date" value={form.service_end_date} onChange={e => setForm({ ...form, service_end_date: e.target.value })} /></div>
            </div>
            <div className="flex flex-wrap gap-6">
              <div className="flex items-center gap-2"><Switch checked={form.is_paid} onCheckedChange={v => setForm({ ...form, is_paid: v })} /><Label>已付款</Label></div>
              <div className="flex items-center gap-2"><Switch checked={form.needs_group} onCheckedChange={v => setForm({ ...form, needs_group: v })} /><Label>需要建群</Label></div>
              <div className="flex items-center gap-2"><Switch checked={form.is_handed_over} onCheckedChange={v => setForm({ ...form, is_handed_over: v })} /><Label>已交接</Label></div>
              <div className="flex items-center gap-2"><Switch checked={form.is_transferred_ops} onCheckedChange={v => setForm({ ...form, is_transferred_ops: v })} /><Label>已转运营</Label></div>
            </div>
            <div><Label>备注</Label><Textarea value={form.notes} onChange={e => setForm({ ...form, notes: e.target.value })} rows={2} /></div>
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
