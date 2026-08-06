import { useEffect, useMemo, useState } from 'react';
import { ArrowRight, CalendarClock, CheckCircle2, Plus, RefreshCw, Target } from 'lucide-react';
import { toast } from 'sonner';

import { invokeWithAuth } from '@/lib/tokenStore';
import { useRole } from '@/lib/role-context';
import { customerPlatformLabels } from '@/lib/dict-config';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { NativeSelect } from '@/components/ui/native-select';
import { Textarea } from '@/components/ui/textarea';

const stageLabels: Record<string, string> = { initial: '初步意向', needs_confirmed: '需求确认', quoted: '已报价', negotiating: '商务沟通', payment_pending: '待收款' };
const statusLabels: Record<string, string> = { open: '跟进中', on_hold: '暂缓', won: '已成交', lost: '未成交' };
const statusTone: Record<string, string> = { open: 'bg-blue-100 text-blue-700', on_hold: 'bg-amber-100 text-amber-700', won: 'bg-emerald-100 text-emerald-700', lost: 'bg-slate-200 text-slate-600' };
const blankForm = {
  id: null as number | null, business_line_id: '', product_id: '', product_plan_id: '', title: '',
  stage: 'initial', status: 'open', estimated_amount: '', currency: 'USD', probability: 10,
  selected_platforms: [] as string[], expected_close_date: '', next_follow_up_at: '', pause_until: '', lost_reason: '', notes: '',
};

function toApiDate(value: string) { return value ? new Date(value).toISOString() : null; }
function toLocalDate(value?: string | null) { return value ? String(value).slice(0, 16) : ''; }

export default function CustomerOpportunitiesTab({ customer }: { customer: any }) {
  const { employee } = useRole();
  const [opportunities, setOpportunities] = useState<any[]>([]);
  const [catalog, setCatalog] = useState<any>({ business_lines: [], products: [], plans: [] });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [editorOpen, setEditorOpen] = useState(false);
  const [followTarget, setFollowTarget] = useState<any>(null);
  const [form, setForm] = useState(blankForm);
  const [followForm, setFollowForm] = useState({ content: '', contact_method: 'phone', stage: 'initial', probability: 10, next_follow_up_at: '' });

  const load = async () => {
    setLoading(true);
    try {
      const [oppRes, catalogRes] = await Promise.all([
        invokeWithAuth({ url: '/api/v1/opportunities', method: 'GET', data: { customer_id: customer.id, page_size: 200 } }),
        invokeWithAuth({ url: '/api/v1/product-plans', method: 'GET', data: { active_only: false } }),
      ]);
      setOpportunities(oppRes.data?.items || []);
      setCatalog(catalogRes.data || { business_lines: [], products: [], plans: [] });
    } catch (error: any) { toast.error(error?.data?.detail || '加载商机失败'); }
    finally { setLoading(false); }
  };
  useEffect(() => { void load(); }, [customer.id]);

  const products = useMemo(() => catalog.products.filter((item: any) => String(item.business_line_id) === form.business_line_id), [catalog.products, form.business_line_id]);
  const plans = useMemo(() => catalog.plans.filter((item: any) => String(item.product_id) === form.product_id && item.is_active), [catalog.plans, form.product_id]);
  const selectedPlan = plans.find((item: any) => String(item.id) === form.product_plan_id) || catalog.plans.find((item: any) => String(item.id) === form.product_plan_id);
  const openCount = opportunities.filter(item => item.status === 'open').length;
  const weightedPipeline = opportunities.filter(item => item.status === 'open').reduce((sum, item) => sum + Number(item.weighted_amount || 0), 0);

  const openEditor = (opportunity?: any) => {
    if (opportunity) setForm({
      id: opportunity.id, business_line_id: String(opportunity.business_line?.id || ''), product_id: String(opportunity.product?.id || ''),
      product_plan_id: String(opportunity.plan?.id || ''), title: opportunity.title || '', stage: opportunity.stage || 'initial', status: opportunity.status || 'open',
      estimated_amount: opportunity.estimated_amount == null ? '' : String(opportunity.estimated_amount), currency: opportunity.currency || 'USD', probability: opportunity.probability ?? 10,
      selected_platforms: opportunity.selected_platforms || [], expected_close_date: toLocalDate(opportunity.expected_close_date),
      next_follow_up_at: toLocalDate(opportunity.next_follow_up_at), pause_until: toLocalDate(opportunity.pause_until), lost_reason: opportunity.lost_reason || '', notes: opportunity.notes || '',
    });
    else {
      const line = catalog.business_lines.find((item: any) => item.code === 'managed_service') || catalog.business_lines[0];
      const product = catalog.products.find((item: any) => item.business_line_id === line?.id);
      setForm({ ...blankForm, business_line_id: line ? String(line.id) : '', product_id: product ? String(product.id) : '', title: `${customer.business_name} 新商机`, next_follow_up_at: new Date(Date.now() + 86400000).toISOString().slice(0, 16) });
    }
    setEditorOpen(true);
  };

  const save = async () => {
    if (!form.business_line_id || !form.title.trim()) { toast.error('请选择业务线并填写商机名称'); return; }
    if (form.status === 'open' && !form.next_follow_up_at) { toast.error('跟进中商机必须填写下次跟进时间'); return; }
    if (selectedPlan?.scope_type === 'platforms' && form.status === 'won' && form.selected_platforms.length !== Number(selectedPlan.platform_limit || 0)) { toast.error(`成交前必须确认 ${selectedPlan.platform_limit} 个实际运营平台`); return; }
    setSaving(true);
    try {
      const data = {
        customer_id: customer.id, business_line_id: Number(form.business_line_id), product_id: form.product_id ? Number(form.product_id) : null,
        product_plan_id: form.product_plan_id ? Number(form.product_plan_id) : null, title: form.title.trim(), stage: form.stage, status: form.status,
        estimated_amount: form.estimated_amount === '' ? null : Number(form.estimated_amount), currency: form.currency, probability: Number(form.probability),
        owner_employee_id: employee?.id ? Number(employee.id) : null, owner_name: employee?.name || null, source: 'existing_customer', selected_platforms: form.selected_platforms,
        service_scope: {}, expected_close_date: toApiDate(form.expected_close_date), next_follow_up_at: toApiDate(form.next_follow_up_at),
        pause_until: toApiDate(form.pause_until), lost_reason: form.lost_reason.trim() || null, notes: form.notes.trim() || null,
      };
      await invokeWithAuth({ url: form.id ? `/api/v1/opportunities/${form.id}` : '/api/v1/opportunities', method: form.id ? 'PUT' : 'POST', data: form.id ? Object.fromEntries(Object.entries(data).filter(([key]) => key !== 'customer_id')) : data });
      toast.success(form.id ? '商机已更新' : '商机已建立，下次跟进任务已同步'); setEditorOpen(false); await load();
    } catch (error: any) { toast.error(error?.data?.detail || error?.message || '保存商机失败'); }
    finally { setSaving(false); }
  };

  const openFollow = (opportunity: any) => {
    setFollowTarget(opportunity);
    setFollowForm({ content: '', contact_method: 'phone', stage: opportunity.stage, probability: opportunity.probability, next_follow_up_at: new Date(Date.now() + 86400000).toISOString().slice(0, 16) });
  };
  const saveFollow = async () => {
    if (!followTarget || !followForm.content.trim() || !followForm.next_follow_up_at) { toast.error('请填写跟进内容和下次跟进时间'); return; }
    setSaving(true);
    try {
      await invokeWithAuth({ url: `/api/v1/opportunities/${followTarget.id}/follow-ups`, method: 'POST', data: { ...followForm, next_follow_up_at: toApiDate(followForm.next_follow_up_at) } });
      toast.success('跟进已记录，任务日期已更新'); setFollowTarget(null); await load();
    } catch (error: any) { toast.error(error?.data?.detail || '保存跟进失败'); }
    finally { setSaving(false); }
  };
  const convert = async (opportunity: any) => {
    try {
      const response = await invokeWithAuth({ url: `/api/v1/opportunities/${opportunity.id}/convert`, method: 'POST', data: {} });
      toast.success(response.data?.message || '已转为待首笔收款'); await load();
    } catch (error: any) { toast.error(error?.data?.detail || '转成交失败'); }
  };

  return <div className="space-y-4">
    <div className="grid gap-3 sm:grid-cols-3"><Card><CardContent className="p-4"><p className="text-xs text-slate-500">跟进中商机</p><p className="mt-1 text-2xl font-semibold text-blue-600">{openCount}</p></CardContent></Card><Card><CardContent className="p-4"><p className="text-xs text-slate-500">加权商机金额</p><p className="mt-1 text-2xl font-semibold text-slate-900">${weightedPipeline.toLocaleString()}</p></CardContent></Card><Card><CardContent className="flex h-full items-center justify-between p-4"><div><p className="text-sm font-medium">新增交叉销售机会</p><p className="mt-1 text-xs text-slate-500">不会覆盖客户当前合作项目</p></div><Button size="sm" onClick={() => openEditor()}><Plus className="mr-1 h-4 w-4" />新商机</Button></CardContent></Card></div>
    {loading ? <p className="py-8 text-center text-sm text-slate-400">正在读取商机…</p> : opportunities.length === 0 ? <div className="rounded-xl border border-dashed py-10 text-center"><Target className="mx-auto h-8 w-8 text-slate-300" /><p className="mt-2 text-sm text-slate-500">暂无商机。已有合作客户的新需求应在这里单独建立，不修改原订阅。</p></div> : <div className="space-y-3">{opportunities.map(opportunity => <div key={opportunity.id} className="rounded-xl border border-slate-200 p-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between"><div><div className="flex flex-wrap items-center gap-2"><p className="font-semibold text-slate-900">{opportunity.title}</p><Badge className={statusTone[opportunity.status]}>{statusLabels[opportunity.status]}</Badge><Badge variant="outline">{stageLabels[opportunity.stage]}</Badge></div><p className="mt-1 text-xs text-slate-500">{opportunity.business_line?.name || '业务待确认'} · {opportunity.product?.name || '产品待确认'} · {opportunity.plan?.name || '套餐待确认'}</p></div><div className="text-right"><p className="font-semibold text-slate-900">{opportunity.currency} {Number(opportunity.estimated_amount || 0).toLocaleString()}</p><p className="text-xs text-slate-500">概率 {opportunity.probability}% · 加权 {Number(opportunity.weighted_amount || 0).toLocaleString()}</p></div></div>
      {opportunity.selected_platforms?.length > 0 && <div className="mt-3 flex flex-wrap gap-1">{opportunity.selected_platforms.map((platform: string) => <Badge key={platform} variant="secondary">{customerPlatformLabels[platform] || platform}</Badge>)}</div>}
      <div className="mt-3 grid gap-2 text-xs sm:grid-cols-3"><div className="rounded-lg bg-slate-50 p-2"><p className="text-slate-400">负责人</p><p className="mt-1 text-slate-700">{opportunity.owner_name || '-'}</p></div><div className="rounded-lg bg-slate-50 p-2"><p className="text-slate-400">下次跟进</p><p className="mt-1 text-slate-700">{opportunity.next_follow_up_at?.slice(0, 16).replace('T', ' ') || '-'}</p></div><div className="rounded-lg bg-slate-50 p-2"><p className="text-slate-400">任务闭环</p><p className="mt-1 text-slate-700">{opportunity.task_id ? `任务 #${opportunity.task_id}` : '已结束'}</p></div></div>
      <div className="mt-3 flex flex-wrap justify-end gap-2"><Button size="sm" variant="outline" onClick={() => openEditor(opportunity)}>编辑</Button>{opportunity.status === 'open' && <Button size="sm" variant="outline" onClick={() => openFollow(opportunity)}><CalendarClock className="mr-1 h-3.5 w-3.5" />记录跟进</Button>}{opportunity.status === 'open' && <Button size="sm" onClick={() => convert(opportunity)}><CheckCircle2 className="mr-1 h-3.5 w-3.5" />转待收款</Button>}{opportunity.converted_deal_id && <Button size="sm" variant="ghost" disabled><ArrowRight className="mr-1 h-3.5 w-3.5" />成交 #{opportunity.converted_deal_id}</Button>}</div>
    </div>)}</div>}
    <Button variant="ghost" size="sm" onClick={load} disabled={loading}><RefreshCw className={`mr-1 h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />刷新商机</Button>

    <Dialog open={editorOpen} onOpenChange={setEditorOpen}><DialogContent className="max-h-[90vh] max-w-2xl overflow-y-auto"><DialogHeader><DialogTitle>{form.id ? '编辑商机' : '新增客户商机'}</DialogTitle></DialogHeader><div className="grid gap-4 py-2 md:grid-cols-2">
      <div className="md:col-span-2"><Label>商机名称 *</Label><Input value={form.title} onChange={event => setForm(prev => ({ ...prev, title: event.target.value }))} /></div>
      <div><Label>业务线 *</Label><NativeSelect value={form.business_line_id} onChange={value => { const product = catalog.products.find((item: any) => String(item.business_line_id) === value); setForm(prev => ({ ...prev, business_line_id: value, product_id: product ? String(product.id) : '', product_plan_id: '', selected_platforms: [] })); }} options={catalog.business_lines.map((line: any) => ({ value: String(line.id), label: line.name }))} /></div>
      <div><Label>产品</Label><NativeSelect value={form.product_id} onChange={value => setForm(prev => ({ ...prev, product_id: value, product_plan_id: '', selected_platforms: [] }))} placeholder="待确认" options={products.map((product: any) => ({ value: String(product.id), label: product.name }))} /></div>
      <div><Label>套餐</Label><NativeSelect value={form.product_plan_id} onChange={value => setForm(prev => ({ ...prev, product_plan_id: value, selected_platforms: [] }))} placeholder="待确认" options={plans.map((plan: any) => ({ value: String(plan.id), label: `${plan.name}${plan.pricing_status === 'draft' ? '（价格待定）' : ''}` }))} /></div>
      <div><Label>预计金额</Label><Input type="number" min="0" value={form.estimated_amount} onChange={event => setForm(prev => ({ ...prev, estimated_amount: event.target.value }))} /></div>
      {selectedPlan?.scope_type === 'platforms' && <div className="md:col-span-2"><Label>实际运营平台（该套餐任选 {selectedPlan.platform_limit} 个）</Label><div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-4">{Object.entries(customerPlatformLabels).map(([key, label]) => <label key={key} className="flex items-center gap-2 rounded-lg border p-2 text-sm"><input type="checkbox" checked={form.selected_platforms.includes(key)} onChange={event => setForm(prev => ({ ...prev, selected_platforms: event.target.checked ? [...prev.selected_platforms, key] : prev.selected_platforms.filter(item => item !== key) }))} />{label}</label>)}</div><p className="mt-1 text-xs text-slate-500">套餐只定义数量，运营人员在这里看到实际平台。</p></div>}
      <div><Label>阶段</Label><NativeSelect value={form.stage} onChange={value => setForm(prev => ({ ...prev, stage: value, probability: ({ initial: 10, needs_confirmed: 25, quoted: 45, negotiating: 70, payment_pending: 90 } as any)[value] }))} options={Object.entries(stageLabels).map(([value, label]) => ({ value, label }))} /></div>
      <div><Label>状态</Label><NativeSelect value={form.status} onChange={value => setForm(prev => ({ ...prev, status: value }))} options={Object.entries(statusLabels).map(([value, label]) => ({ value, label }))} /></div>
      {form.status === 'open' && <div><Label>下次跟进 *</Label><Input type="datetime-local" value={form.next_follow_up_at} onChange={event => setForm(prev => ({ ...prev, next_follow_up_at: event.target.value }))} /></div>}
      {form.status === 'on_hold' && <div><Label>恢复跟进日期 *</Label><Input type="datetime-local" value={form.pause_until} onChange={event => setForm(prev => ({ ...prev, pause_until: event.target.value }))} /></div>}
      {form.status === 'lost' && <div className="md:col-span-2"><Label>未成交原因 *</Label><Input value={form.lost_reason} onChange={event => setForm(prev => ({ ...prev, lost_reason: event.target.value }))} /></div>}
      <div className="md:col-span-2"><Label>备注</Label><Textarea value={form.notes} onChange={event => setForm(prev => ({ ...prev, notes: event.target.value }))} /></div>
    </div><div className="flex justify-end gap-2"><Button variant="outline" onClick={() => setEditorOpen(false)}>取消</Button><Button onClick={save} disabled={saving}>{saving ? '保存中…' : '保存并同步任务'}</Button></div></DialogContent></Dialog>

    <Dialog open={Boolean(followTarget)} onOpenChange={open => !open && setFollowTarget(null)}><DialogContent><DialogHeader><DialogTitle>记录商机跟进</DialogTitle></DialogHeader><div className="space-y-4 py-2"><div><Label>跟进内容 *</Label><Textarea rows={5} value={followForm.content} onChange={event => setFollowForm(prev => ({ ...prev, content: event.target.value }))} /></div><div className="grid grid-cols-2 gap-3"><div><Label>更新阶段</Label><NativeSelect value={followForm.stage} onChange={value => setFollowForm(prev => ({ ...prev, stage: value, probability: ({ initial: 10, needs_confirmed: 25, quoted: 45, negotiating: 70, payment_pending: 90 } as any)[value] }))} options={Object.entries(stageLabels).map(([value, label]) => ({ value, label }))} /></div><div><Label>下次跟进 *</Label><Input type="datetime-local" value={followForm.next_follow_up_at} onChange={event => setFollowForm(prev => ({ ...prev, next_follow_up_at: event.target.value }))} /></div></div></div><div className="flex justify-end gap-2"><Button variant="outline" onClick={() => setFollowTarget(null)}>取消</Button><Button onClick={saveFollow} disabled={saving}>保存跟进</Button></div></DialogContent></Dialog>
  </div>;
}
