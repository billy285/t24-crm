import { useEffect, useMemo, useState } from 'react';
import { Boxes, Edit3, Plus, RefreshCw } from 'lucide-react';
import { toast } from 'sonner';

import { invokeWithAuth } from '@/lib/tokenStore';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { NativeSelect } from '@/components/ui/native-select';
import { Switch } from '@/components/ui/switch';
import { Textarea } from '@/components/ui/textarea';

type Catalog = { business_lines: any[]; products: any[]; plans: any[] };
const emptyCatalog: Catalog = { business_lines: [], products: [], plans: [] };
const blankPlan = {
  id: null as number | null,
  product_id: '', code: '', name: '', version_label: '', pricing_status: 'draft', standard_price: '',
  default_currency: 'USD', default_billing_cycle: 'monthly', platform_limit: '', scope_type: 'generic',
  entitlements: '', is_active: true,
};
const lineTone: Record<string, string> = {
  managed_service: 'bg-blue-100 text-blue-700', restaurant_os: 'bg-orange-100 text-orange-700',
  beauty_os: 'bg-pink-100 text-pink-700', one_time_project: 'bg-slate-100 text-slate-600',
};

export default function ProductPlanSettings({ canEdit }: { canEdit: boolean }) {
  const [catalog, setCatalog] = useState<Catalog>(emptyCatalog);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [editorOpen, setEditorOpen] = useState(false);
  const [form, setForm] = useState(blankPlan);

  const loadCatalog = async () => {
    setLoading(true);
    try {
      const response = await invokeWithAuth({ url: '/api/v1/product-plans', method: 'GET' });
      setCatalog(response.data || emptyCatalog);
    } catch (error: any) {
      toast.error(error?.data?.detail || '加载产品套餐失败');
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { void loadCatalog(); }, []);

  const grouped = useMemo(() => catalog.business_lines.map(line => ({
    line,
    products: catalog.products.filter(product => product.business_line_id === line.id).map(product => ({
      ...product,
      plans: catalog.plans.filter(plan => plan.product_id === product.id),
    })),
  })), [catalog]);

  const openEditor = (plan?: any, preferredProductId?: number) => {
    if (plan) {
      setForm({
        id: plan.id, product_id: String(plan.product_id), code: plan.code || '', name: plan.name || '',
        version_label: plan.version_label || '', pricing_status: plan.pricing_status || 'draft',
        standard_price: plan.standard_price == null ? '' : String(plan.standard_price),
        default_currency: plan.default_currency || 'USD', default_billing_cycle: plan.default_billing_cycle || 'monthly',
        platform_limit: plan.platform_limit == null ? '' : String(plan.platform_limit), scope_type: plan.scope_type || 'generic',
        entitlements: (plan.entitlements || []).join('\n'), is_active: Boolean(plan.is_active),
      });
    } else {
      const product = catalog.products.find(item => item.id === preferredProductId) || catalog.products[0];
      const scopeType = product?.business_line_code === 'managed_service' ? 'platforms' : product?.business_line_code || 'generic';
      setForm({ ...blankPlan, product_id: product ? String(product.id) : '', scope_type: scopeType });
    }
    setEditorOpen(true);
  };

  const save = async () => {
    if (!form.product_id || !form.code.trim() || !form.name.trim()) {
      toast.error('请选择产品并填写套餐名称和代码'); return;
    }
    if (form.scope_type === 'platforms' && !form.platform_limit) {
      toast.error('代运营套餐必须填写可选平台数量'); return;
    }
    setSaving(true);
    try {
      const data = {
        product_id: Number(form.product_id), code: form.code.trim(), name: form.name.trim(),
        version_label: form.version_label.trim() || null, pricing_status: form.pricing_status,
        standard_price: form.standard_price === '' ? null : Number(form.standard_price),
        default_currency: form.default_currency, default_billing_cycle: form.default_billing_cycle || null,
        platform_limit: form.scope_type === 'platforms' ? Number(form.platform_limit) : null,
        scope_type: form.scope_type, entitlements: form.entitlements.split('\n').map(item => item.trim()).filter(Boolean),
        is_active: form.is_active, effective_from: null, effective_to: null,
      };
      await invokeWithAuth({
        url: form.id ? `/api/v1/product-plans/plans/${form.id}` : '/api/v1/product-plans/plans',
        method: form.id ? 'PUT' : 'POST', data,
      });
      toast.success(form.id ? '套餐已更新' : '套餐已创建');
      setEditorOpen(false);
      await loadCatalog();
    } catch (error: any) {
      toast.error(error?.data?.detail || error?.message || '保存套餐失败');
    } finally { setSaving(false); }
  };

  return <div className="space-y-4">
    <Card className="border-slate-200">
      <CardHeader className="pb-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div><CardTitle className="flex items-center gap-2 text-base"><Boxes className="h-4 w-4 text-blue-600" />产品、套餐与服务范围</CardTitle>
            <CardDescription className="mt-1">产品区分业务线；套餐定义价格、周期和可选数量；客户实际购买内容在商机和订阅中单独确认。</CardDescription></div>
          <Button variant="outline" size="sm" onClick={loadCatalog} disabled={loading}><RefreshCw className={`mr-1 h-4 w-4 ${loading ? 'animate-spin' : ''}`} />刷新</Button>
        </div>
      </CardHeader>
    </Card>
    {loading ? <div className="py-12 text-center text-sm text-slate-400">正在读取产品目录…</div> : grouped.map(({ line, products }) => <Card key={line.id} className="border-slate-200">
      <CardHeader className="pb-3"><div className="flex items-center justify-between gap-3"><div className="flex items-center gap-2"><CardTitle className="text-base">{line.name}</CardTitle><Badge className={lineTone[line.code] || lineTone.one_time_project}>{line.code}</Badge></div></div></CardHeader>
      <CardContent className="space-y-4">
        {products.length === 0 ? <p className="rounded-lg border border-dashed py-6 text-center text-sm text-slate-400">该业务线暂无产品，请先保留现有历史产品或由管理员建立正式产品。</p> : products.map(product => <div key={product.id} className="rounded-xl border border-slate-200 p-4">
          <div className="flex flex-wrap items-center justify-between gap-3"><div><p className="font-semibold text-slate-800">{product.name}</p><p className="mt-1 text-xs text-slate-400">{product.code} · {product.billing_kind === 'recurring' ? '周期产品' : '一次性产品'}</p></div>{canEdit && <Button size="sm" variant="outline" onClick={() => openEditor(undefined, product.id)}><Plus className="mr-1 h-3.5 w-3.5" />新增套餐</Button>}</div>
          <div className="mt-3 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {product.plans.map((plan: any) => <div key={plan.id} className="rounded-xl bg-slate-50 p-3">
              <div className="flex items-start justify-between gap-2"><div><p className="font-medium text-slate-800">{plan.name}</p><p className="mt-1 text-xs text-slate-400">{plan.version_label || '当前版本'}</p></div><Badge className={plan.pricing_status === 'published' ? 'bg-emerald-100 text-emerald-700' : plan.pricing_status === 'retired' ? 'bg-slate-200 text-slate-600' : 'bg-amber-100 text-amber-700'}>{plan.pricing_status === 'published' ? '已发布' : plan.pricing_status === 'retired' ? '已停用' : '价格待定'}</Badge></div>
              <p className="mt-3 text-lg font-semibold text-slate-900">{plan.standard_price == null ? '暂未定价' : `${plan.default_currency} ${Number(plan.standard_price).toLocaleString()}`}</p>
              <p className="mt-1 text-xs text-slate-500">{plan.scope_type === 'platforms' ? `任选 ${plan.platform_limit} 个平台，实际平台另行确认` : plan.scope_type === 'restaurant_os' ? '餐饮 OS 独立服务范围' : plan.scope_type === 'beauty_os' ? '美业 OS 独立服务范围' : '按项目确认服务范围'}</p>
              {canEdit && <Button size="sm" variant="ghost" className="mt-2 h-8 px-2 text-blue-600" onClick={() => openEditor(plan)}><Edit3 className="mr-1 h-3.5 w-3.5" />编辑</Button>}
            </div>)}
            {product.plans.length === 0 && <p className="text-sm text-slate-400">暂无正式套餐，现有历史记录不会受影响。</p>}
          </div>
        </div>)}
      </CardContent>
    </Card>)}

    <Dialog open={editorOpen} onOpenChange={setEditorOpen}><DialogContent className="max-h-[90vh] max-w-2xl overflow-y-auto"><DialogHeader><DialogTitle>{form.id ? '编辑套餐' : '新增套餐'}</DialogTitle></DialogHeader>
      <div className="grid gap-4 py-2 md:grid-cols-2">
        <div className="md:col-span-2"><Label>所属产品 *</Label><NativeSelect value={form.product_id} onChange={value => { const product = catalog.products.find(item => String(item.id) === value); setForm(prev => ({ ...prev, product_id: value, scope_type: product?.business_line_code === 'managed_service' ? 'platforms' : product?.business_line_code || 'generic', platform_limit: product?.business_line_code === 'managed_service' ? prev.platform_limit : '' })); }} disabled={Boolean(form.id)} placeholder="请选择" options={catalog.products.map(product => ({ value: String(product.id), label: `${product.business_line_name} · ${product.name}` }))} /></div>
        <div><Label>套餐名称 *</Label><Input value={form.name} onChange={event => setForm(prev => ({ ...prev, name: event.target.value }))} /></div>
        <div><Label>套餐代码 *</Label><Input value={form.code} onChange={event => setForm(prev => ({ ...prev, code: event.target.value }))} placeholder="managed_basic_v1" /></div>
        <div><Label>版本说明</Label><Input value={form.version_label} onChange={event => setForm(prev => ({ ...prev, version_label: event.target.value }))} placeholder="2026 版" /></div>
        <div><Label>价格状态</Label><NativeSelect value={form.pricing_status} onChange={value => setForm(prev => ({ ...prev, pricing_status: value }))} options={[{ value: 'draft', label: '价格待定' }, { value: 'published', label: '已发布' }, { value: 'retired', label: '已停用' }]} /></div>
        <div><Label>标准价格</Label><Input type="number" min="0" value={form.standard_price} onChange={event => setForm(prev => ({ ...prev, standard_price: event.target.value }))} placeholder="价格未定可留空" /></div>
        <div><Label>默认周期</Label><NativeSelect value={form.default_billing_cycle} onChange={value => setForm(prev => ({ ...prev, default_billing_cycle: value }))} options={[{ value: 'monthly', label: '月付' }, { value: 'quarterly', label: '季付' }, { value: 'annual', label: '年付' }, { value: 'one_time', label: '一次性' }]} /></div>
        {form.scope_type === 'platforms' && <div><Label>可选平台数量 *</Label><Input type="number" min="1" max="50" value={form.platform_limit} onChange={event => setForm(prev => ({ ...prev, platform_limit: event.target.value }))} /><p className="mt-1 text-xs text-slate-500">这是数量上限；客户实际运营哪些平台在商机中选择。</p></div>}
        <div className="md:col-span-2"><Label>包含权益（每行一项）</Label><Textarea rows={4} value={form.entitlements} onChange={event => setForm(prev => ({ ...prev, entitlements: event.target.value }))} /></div>
        <div className="md:col-span-2 flex items-center justify-between rounded-lg bg-slate-50 p-3"><div><p className="text-sm font-medium">允许新商机选择</p><p className="text-xs text-slate-500">停用后历史订阅仍保留。</p></div><Switch checked={form.is_active} onCheckedChange={checked => setForm(prev => ({ ...prev, is_active: checked }))} /></div>
      </div>
      <div className="flex justify-end gap-2"><Button variant="outline" onClick={() => setEditorOpen(false)}>取消</Button><Button onClick={save} disabled={saving}>{saving ? '保存中…' : '保存套餐'}</Button></div>
    </DialogContent></Dialog>
  </div>;
}
