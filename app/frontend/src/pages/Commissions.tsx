import { useEffect, useMemo, useState } from 'react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { NativeSelect } from '@/components/ui/native-select';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import './commissions.css';
import { Textarea } from '@/components/ui/textarea';
import { invokeWithAuth } from '@/lib/tokenStore';
import { ArrowLeft, ArrowRight, ChevronDown, SlidersHorizontal, AlertTriangle, BadgeDollarSign, Building2, HandCoins, RefreshCw, ShieldCheck, Sparkles } from 'lucide-react';
import { toast } from 'sonner';
import { useIsMobile } from '@/hooks/use-mobile';

type Partner = { id: number; partner_code: string; name: string; partner_type: string; employee_id?: number; status: string; joined_at: string; stopped_at?: string; notes?: string };
type Agreement = { id: number; partner_id: number; version: number; business_line_id?: number; product_id?: number; first_order_rate: number; renewal_rate: number; activity_decay: Record<string, number>; refund_guard_days: number; effective_from: string; effective_to?: string; status: string };
type Attribution = { id: number; customer_id: number; customer_name?: string; engagement_id?: number; partner_id: number; partner_name?: string; effective_from: string; effective_to?: string; is_active: boolean; source_note?: string };
type Entry = { id: number; partner_name?: string; customer_id: number; customer_name?: string; payment_id: number; refund_id?: number; entry_type: string; status: string; service_month: string; occurred_at: string; currency: string; gross_receipt_amount: number; eligible_service_amount: number; contract_rate: number; inactivity_months: number; activity_multiplier: number; commission_amount: number; payout_reference?: string };
type QualityIssue = { key: string; type: string; severity: string; title: string; description: string; customer_id?: number; customer_name?: string; engagement_id?: number; payment_id?: number; partner_id?: number; partner_name?: string };
type QualitySummary = { issue_count: number; high_count: number; covered_count: number; examined_count: number; coverage_rate: number };
type DashboardData = { summary: { partner_count: number; active_partner_count: number; pending_count: number; currencies: Record<string, Record<string, number>>; accounting_rule: string; quality?: QualitySummary }; quality_issues: QualityIssue[]; partners: Partner[]; agreements: Agreement[]; attributions: Attribution[]; entries: Entry[] };
type OptionsData = { employees: Array<{ id: number; name: string; employee_code?: string; role: string }>; customers: Array<{ id: number; name: string; code?: string }>; business_lines: Array<{ id: number; name: string; code: string }>; products: Array<{ id: number; name: string; business_line_id: number }>; engagements: Array<{ id: number; customer_id: number; package_name?: string; status: string }> };
type BulkAttributionItem = { customer_id: number; customer_code?: string; customer_name: string; engagement_id?: number; engagement_name?: string; effective_from: string; partner_id?: number; partner_name?: string; partner_type?: string; status: 'ready' | 'manual_review'; basis: string; issue_keys: string[] };
type BulkAttributionPreview = { preview_token: string; source_issue_count: number; target_count: number; ready_count: number; employee_count: number; direct_count: number; manual_review_count: number; items: BulkAttributionItem[] };

const partnerTypeLabels: Record<string, string> = { agency: '代理商', partner: '销售合伙人', employee: '内部销售', direct: '公司直营' };
const partnerStatusLabels: Record<string, string> = { active: '合作中', suspended: '暂停结算', terminated: '已终止', settled: '已结清' };
const entryTypeLabels: Record<string, string> = { first_order: '首单佣金', renewal: '续费佣金', refund_reversal: '退款冲回' };
const entryStatusLabels: Record<string, string> = { pending_confirmation: '待确认', confirmed: '已确认入账', payable: '待发放', paid: '已发放', reversed: '已作废' };
const today = () => new Intl.DateTimeFormat('en-CA', {
  timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit',
}).format(new Date());
const percent = (value: number) => `${(Number(value || 0) * 100).toFixed(0)}%`;
const money = (value: number, currency: string) => `${currency === 'CNY' ? '¥' : '$'}${Number(value || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const errorMessage = (error: any) => error?.data?.detail || error?.response?.data?.detail || error?.message || '操作失败';

export default function Commissions() {
  const isMobile = useIsMobile();
  const [data, setData] = useState<DashboardData | null>(null);
  const [options, setOptions] = useState<OptionsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);
  const [month, setMonth] = useState('');
  const [search, setSearch] = useState('');
  const [activeTab, setActiveTab] = useState('ledger');
  const [showFilters, setShowFilters] = useState(false);
  const managementLabels: Record<string, string> = { partners: '渠道与协议', attributions: '客户归属', quality: '待办事项', rules: '计算规则' };
  const isManagementView = Boolean(managementLabels[activeTab]);
  const [customerSearch, setCustomerSearch] = useState('');
  const [dialog, setDialog] = useState<'partner' | 'agreement' | 'attribution' | 'bulkAttribution' | null>(null);
  const [bulkPreview, setBulkPreview] = useState<BulkAttributionPreview | null>(null);
  const [partnerForm, setPartnerForm] = useState({ partner_code: '', name: '', partner_type: 'partner', employee_id: '', joined_at: today(), contact_name: '', contact_phone: '', contact_email: '', notes: '' });
  const [agreementForm, setAgreementForm] = useState({ partner_id: '', business_line_id: 'all', product_id: 'all', first_order_rate: '50', renewal_rate: '20', refund_guard_days: '30', decay_rates: ['100', '80', '60', '40', '25', '10', '0'], effective_from: today(), notes: '' });
  const [attributionForm, setAttributionForm] = useState({ customer_id: '', partner_id: '', engagement_id: 'all', effective_from: today(), source_note: '' });

  const load = async () => {
    setLoading(true);
    try {
      const dashboardRequest = invokeWithAuth({ url: `/api/v1/commissions/dashboard${month ? `?month=${month}` : ''}`, method: 'GET' });
      const optionsRequest = isMobile
        ? Promise.resolve(null)
        : invokeWithAuth({ url: '/api/v1/commissions/options', method: 'GET' });
      const [dashboardResponse, optionsResponse] = await Promise.all([dashboardRequest, optionsRequest]);
      setData(dashboardResponse.data);
      setOptions(optionsResponse?.data || null);
    } catch (error) { toast.error(errorMessage(error)); }
    finally { setLoading(false); }
  };

  useEffect(() => { void load(); }, [isMobile, month]);

  const filteredEntries = useMemo(() => (data?.entries || []).filter(item => `${item.partner_name || ''} ${item.customer_name || ''} ${item.payment_id}`.toLowerCase().includes(search.toLowerCase())), [data?.entries, search]);
  const filteredAttributions = useMemo(() => (data?.attributions || []).filter(item => `${item.partner_name || ''} ${item.customer_name || ''}`.toLowerCase().includes(search.toLowerCase())), [data?.attributions, search]);
  const settlements = useMemo(() => {
    const grouped = new Map<string, { partner_name: string; currency: string; pending: number; confirmed: number; payable: number; paid: number; adjustments: number; entry_count: number }>();
    (filteredEntries || []).filter(item => item.status !== 'reversed').forEach(item => {
      const key = `${item.partner_name || '未命名渠道'}::${item.currency}`;
      const row = grouped.get(key) || { partner_name: item.partner_name || '未命名渠道', currency: item.currency, pending: 0, confirmed: 0, payable: 0, paid: 0, adjustments: 0, entry_count: 0 };
      row.entry_count += 1;
      if (item.entry_type === 'refund_reversal') row.adjustments += item.commission_amount;
      if (item.status === 'pending_confirmation') row.pending += item.commission_amount;
      if (['confirmed', 'payable', 'paid'].includes(item.status)) row.confirmed += item.commission_amount;
      if (item.status === 'payable') row.payable += item.commission_amount;
      if (item.status === 'paid') row.paid += item.commission_amount;
      grouped.set(key, row);
    });
    return [...grouped.values()].sort((a, b) => a.partner_name.localeCompare(b.partner_name));
  }, [filteredEntries]);
  const selectedLineId = agreementForm.business_line_id === 'all' ? undefined : Number(agreementForm.business_line_id);
  const agreementProducts = (options?.products || []).filter(product => !selectedLineId || product.business_line_id === selectedLineId);
  const selectedCustomerId = Number(attributionForm.customer_id || 0);
  const customerEngagements = (options?.engagements || []).filter(item => item.customer_id === selectedCustomerId);
  const customerOptions = (options?.customers || []).filter(item => `${item.code || ''} ${item.name}`.toLowerCase().includes(customerSearch.toLowerCase())).slice(0, 80);

  const submit = async () => {
    setWorking(true);
    try {
      if (dialog === 'partner') {
        await invokeWithAuth({ url: '/api/v1/commissions/partners', method: 'POST', data: { ...partnerForm, employee_id: partnerForm.employee_id ? Number(partnerForm.employee_id) : null } });
      } else if (dialog === 'agreement') {
        await invokeWithAuth({ url: '/api/v1/commissions/agreements', method: 'POST', data: {
          ...agreementForm,
          partner_id: Number(agreementForm.partner_id), business_line_id: agreementForm.business_line_id === 'all' ? null : Number(agreementForm.business_line_id),
          product_id: agreementForm.product_id === 'all' ? null : Number(agreementForm.product_id),
          first_order_rate: Number(agreementForm.first_order_rate) / 100, renewal_rate: Number(agreementForm.renewal_rate) / 100,
          refund_guard_days: Number(agreementForm.refund_guard_days),
          activity_decay: Object.fromEntries(agreementForm.decay_rates.map((rate, index) => [index, Number(rate) / 100])),
        } });
      } else if (dialog === 'attribution') {
        await invokeWithAuth({ url: '/api/v1/commissions/attributions', method: 'POST', data: {
          ...attributionForm, customer_id: Number(attributionForm.customer_id), partner_id: Number(attributionForm.partner_id),
          engagement_id: attributionForm.engagement_id === 'all' ? null : Number(attributionForm.engagement_id),
        } });
      }
      toast.success('已保存；历史协议和已确认佣金快照未被改写');
      setDialog(null);
      await load();
    } catch (error) { toast.error(errorMessage(error)); }
    finally { setWorking(false); }
  };

  const scan = async () => {
    setWorking(true);
    try {
      const response = await invokeWithAuth({ url: '/api/v1/commissions/scan', method: 'POST' });
      toast.success(`扫描完成，新生成 ${response.data.entries_created} 条佣金记录`);
      await load();
    } catch (error) { toast.error(errorMessage(error)); }
    finally { setWorking(false); }
  };

  const previewBulkAttribution = async () => {
    setWorking(true);
    try {
      const response = await invokeWithAuth({ url: '/api/v1/commissions/attributions/bulk-preview', method: 'GET' });
      setBulkPreview(response.data);
      setDialog('bulkAttribution');
    } catch (error) { toast.error(errorMessage(error)); }
    finally { setWorking(false); }
  };

  const applyBulkAttribution = async () => {
    if (!bulkPreview?.ready_count) return;
    setWorking(true);
    try {
      const response = await invokeWithAuth({
        url: '/api/v1/commissions/attributions/bulk-apply',
        method: 'POST',
        data: { preview_token: bulkPreview.preview_token },
      });
      toast.success(`已补齐 ${response.data.assigned_count} 项归属；新生成 ${response.data.entries_created} 条待确认佣金`);
      setDialog(null);
      setBulkPreview(null);
      await load();
    } catch (error) { toast.error(errorMessage(error)); }
    finally { setWorking(false); }
  };

  const transition = async (entry: Entry, to_status: string) => {
    let reason = '';
    let payout_reference = '';
    if (to_status === 'reversed') { reason = window.prompt('请输入作废原因：') || ''; if (!reason) return; }
    if (to_status === 'paid') { payout_reference = window.prompt('请输入付款流水号或凭证编号：') || ''; if (!payout_reference) return; }
    try {
      await invokeWithAuth({ url: `/api/v1/commissions/entries/${entry.id}/transition`, method: 'POST', data: { to_status, reason: reason || null, payout_reference: payout_reference || null } });
      toast.success('佣金状态已更新'); await load();
    } catch (error) { toast.error(errorMessage(error)); }
  };

  const changePartnerStatus = async (partner: Partner, next: string) => {
    const reason = window.prompt(next === 'terminated' ? '请输入停止合作原因。停止日后的续费自动归公司：' : '请输入状态变更原因：') || '';
    if (!reason) return;
    const effective_date = window.prompt('请输入生效日期（YYYY-MM-DD）：', today()) || '';
    if (!effective_date) return;
    try {
      await invokeWithAuth({ url: `/api/v1/commissions/partners/${partner.id}/status`, method: 'POST', data: { status: next, effective_date, reason } });
      toast.success('渠道状态已更新，历史已确认佣金保持不变'); await load();
    } catch (error) { toast.error(errorMessage(error)); }
  };

  const resolveIssue = (issue: QualityIssue) => {
    if (issue.partner_id && ['partner_without_agreement', 'payment_without_agreement'].includes(issue.type)) {
      setAgreementForm(value => ({ ...value, partner_id: String(issue.partner_id) }));
      setDialog('agreement');
      return;
    }
    if (issue.customer_id) {
      setCustomerSearch(issue.customer_name || String(issue.customer_id));
      setAttributionForm(value => ({
        ...value,
        customer_id: String(issue.customer_id),
        engagement_id: issue.engagement_id ? String(issue.engagement_id) : 'all',
      }));
      setDialog('attribution');
    }
  };

  const exportSettlements = () => {
    const rows = [
      ['月份', '渠道', '币种', '记录数', '待确认', '已确认费用', '待发放', '已发放', '退款冲回'],
      ...settlements.map(row => [month || '全部', row.partner_name, row.currency, row.entry_count, row.pending, row.confirmed, row.payable, row.paid, row.adjustments]),
    ];
    const csv = `\uFEFF${rows.map(row => row.map(value => `"${String(value).replace(/"/g, '""')}"`).join(',')).join('\n')}`;
    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
    const link = document.createElement('a');
    link.href = url;
    link.download = `渠道结算单_${month || '全部月份'}.csv`;
    link.click();
    URL.revokeObjectURL(url);
  };

  if (loading && !data) return <div className="app-page"><div className="app-loading">正在读取渠道与分润台账...</div></div>;

  return <div className="app-page commission-page">
    <div className="commission-heading">
      <div><p className="text-xs text-slate-500">渠道合作</p><h1 className="mt-2 text-2xl font-semibold tracking-tight text-slate-900">渠道与分润</h1></div>
      {!isMobile && <DropdownMenu><DropdownMenuTrigger asChild><Button variant="ghost" className="gap-2 text-slate-600">渠道管理<ChevronDown className="h-4 w-4" /></Button></DropdownMenuTrigger><DropdownMenuContent align="end">
        <DropdownMenuItem onSelect={() => setActiveTab('partners')}>渠道与协议 · {data?.summary.partner_count ?? 0}</DropdownMenuItem>
        <DropdownMenuItem onSelect={() => setActiveTab('attributions')}>客户归属 · {data?.attributions.length ?? 0}</DropdownMenuItem>
        <DropdownMenuItem onSelect={() => setActiveTab('quality')}>待办事项 · {data?.summary.quality?.issue_count ?? 0}</DropdownMenuItem>
        <DropdownMenuItem onSelect={() => setActiveTab('rules')}>计算规则</DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={() => setDialog('partner')}>新增渠道</DropdownMenuItem>
        <DropdownMenuItem onSelect={() => setDialog('agreement')}>新增协议版本</DropdownMenuItem>
        <DropdownMenuItem onSelect={() => setDialog('attribution')}>设置客户归属</DropdownMenuItem>
      </DropdownMenuContent></DropdownMenu>}
    </div>

    {!!data?.summary.quality?.issue_count && !isManagementView && <section className="commission-priority" aria-label="分润待办">
      <p className="text-xs text-amber-700">需要处理</p>
      <h2 className="mt-3 text-xl font-medium text-slate-900">还有 {data.summary.quality.issue_count} 项分润数据待补齐</h2>
      <p className="mt-2 text-sm text-slate-500">先核对客户归属，再处理协议或冲突。</p>
      {!isMobile ? <Button className="mt-6 gap-2" onClick={() => setActiveTab('quality')}>查看待办<ArrowRight className="h-4 w-4" /></Button> : <p className="mt-5 text-xs text-slate-500">请在电脑端处理待办事项。</p>}
    </section>}

    <div className="commission-record-heading">
      <div>{isManagementView ? <div className="flex flex-wrap items-center gap-3"><Button variant="ghost" size="sm" className="gap-1 text-slate-500" onClick={() => setActiveTab('ledger')}><ArrowLeft className="h-4 w-4" />返回台账</Button><h2 className="text-lg font-medium">{managementLabels[activeTab]}</h2></div> : <h2 className="text-lg font-medium text-slate-900">{isMobile ? '结算摘要' : '佣金台账'}</h2>}</div>
      {!isManagementView && !isMobile && <div className="flex gap-5" aria-label="分润记录视图"><Button variant="ghost" aria-pressed={activeTab === 'ledger'} className="commission-view-button" onClick={() => setActiveTab('ledger')}>佣金记录</Button><Button variant="ghost" aria-pressed={activeTab === 'settlements'} className="commission-view-button" onClick={() => setActiveTab('settlements')}>月度结算</Button></div>}
    </div>
    <div className="commission-toolbar">
      <p className="text-sm text-slate-500">{activeTab === 'partners' ? <>合作中 <span className="ml-2 font-medium text-slate-900">{data?.summary.active_partner_count ?? 0} 个</span></> : activeTab === 'quality' || activeTab === 'attributions' ? <>归属覆盖率 <span className="ml-2 font-medium text-slate-900">{data?.summary.quality?.coverage_rate ?? '—'}%</span></> : <>待确认佣金 <span className="ml-2 font-medium text-slate-900">{data?.summary.pending_count ?? 0} 笔</span></>}</p>
      <div className="flex flex-wrap gap-2">
        {['ledger', 'settlements', 'attributions'].includes(activeTab) && <Button variant="ghost" size="sm" aria-expanded={showFilters} aria-controls="commission-filters" onClick={() => setShowFilters(v => !v)} className="gap-2 text-slate-500"><SlidersHorizontal className="h-4 w-4" />{search || month ? '筛选已启用' : '筛选'}</Button>}
        {!isMobile && ['ledger', 'settlements'].includes(activeTab) && <Button variant="ghost" size="sm" onClick={scan} disabled={working} className="gap-2 text-slate-600"><RefreshCw className={`h-4 w-4 ${working ? 'animate-spin' : ''}`} />扫描实收与退款</Button>}
        {!isMobile && activeTab === 'partners' && <><Button variant="outline" size="sm" onClick={() => setDialog('agreement')}>新增协议版本</Button><Button size="sm" onClick={() => setDialog('partner')}>新增渠道</Button></>}
        {!isMobile && activeTab === 'attributions' && <Button size="sm" onClick={() => setDialog('attribution')}>设置归属</Button>}
        {!isMobile && activeTab === 'quality' && <Button size="sm" onClick={previewBulkAttribution} disabled={working}><Sparkles className="mr-2 h-4 w-4" />批量补齐预览</Button>}
      </div>
    </div>
    {(['ledger', 'settlements', 'attributions'].includes(activeTab) && (showFilters || activeTab === 'settlements')) && <div id="commission-filters" className="commission-filters">
      <Input aria-label="搜索渠道、客户或收款编号" className="w-full md:max-w-sm" placeholder="搜索渠道、客户或收款编号" value={search} onChange={event => setSearch(event.target.value)} />
      <Input aria-label="结算月份" type="month" className="w-full md:w-44" value={month} onChange={event => setMonth(event.target.value)} />
      {(month || search) && <Button variant="ghost" onClick={() => { setMonth(''); setSearch(''); }}>清除筛选</Button>}
    </div>}

    <section className="space-y-3 md:hidden" aria-labelledby="mobile-commission-summary">
      <div className="rounded-2xl border border-blue-100 bg-blue-50 p-4">
        <h2 id="mobile-commission-summary" className="font-semibold text-blue-950">手机版为只读结算摘要</h2>
        <p className="mt-1 text-xs leading-5 text-blue-700">确认、转应付、发放、作废、协议版本、归属调整和渠道停结请在电脑端完成。</p>
      </div>
      {settlements.slice(0, 6).map(row => (
        <Card key={`${row.partner_name}-${row.currency}`}>
          <CardContent className="p-4">
            <div className="flex items-start justify-between gap-3"><div><p className="font-semibold text-slate-900">{row.partner_name}</p><p className="mt-1 text-xs text-slate-500">{row.currency} · {row.entry_count} 条记录</p></div><Badge variant="outline">{month || '全部月份'}</Badge></div>
            <div className="mt-3 grid grid-cols-2 gap-2 rounded-xl bg-slate-50 p-3 text-xs"><div><p className="text-slate-400">待确认</p><p className="mt-1 font-semibold text-amber-700">{money(row.pending, row.currency)}</p></div><div><p className="text-slate-400">待发放</p><p className="mt-1 font-semibold text-blue-700">{money(row.payable, row.currency)}</p></div><div><p className="text-slate-400">已确认费用</p><p className="mt-1 font-semibold text-slate-800">{money(row.confirmed, row.currency)}</p></div><div><p className="text-slate-400">已发放</p><p className="mt-1 font-semibold text-emerald-700">{money(row.paid, row.currency)}</p></div></div>
          </CardContent>
        </Card>
      ))}
      {!settlements.length && <div className="app-empty">当前筛选范围暂无结算摘要</div>}
    </section>

    {!isMobile && <>
    <div>

      <section hidden={activeTab !== 'ledger'} aria-label="佣金记录"><Card><CardHeader><CardTitle className="flex items-center gap-2 text-base"><BadgeDollarSign className="h-5 w-5 text-blue-600" />佣金记录</CardTitle><details className="mt-2 text-sm text-slate-500"><summary className="cursor-pointer">查看计佣条件</summary><p className="mt-3">客户归属只是确定“以后由谁分润”，不等于已经产生佣金；仅生效日后的已确认服务实收、匹配有效协议后才会生成台账，归属日前已完成的首单不会重新计算。</p></details></CardHeader><CardContent className="overflow-x-auto p-0">{filteredEntries.length > 0 ? <table className="w-full min-w-[1080px] text-sm"><thead className="bg-slate-50 text-left text-xs text-slate-500"><tr><th className="px-4 py-3">月份 / 对象</th><th>类型</th><th>计佣基数</th><th>合同 × 活跃</th><th>佣金</th><th>状态</th><th className="px-4">操作</th></tr></thead><tbody>{filteredEntries.map(entry => <tr key={entry.id} className="border-t"><td className="px-4 py-3"><p className="font-medium">{entry.service_month} · {entry.customer_name || `客户 #${entry.customer_id}`}</p><p className="text-xs text-slate-400">{entry.partner_name} · 收款 #{entry.payment_id}{entry.refund_id ? ` · 退款 #${entry.refund_id}` : ''}</p></td><td><Badge variant="outline">{entryTypeLabels[entry.entry_type] || entry.entry_type}</Badge></td><td>{money(entry.eligible_service_amount, entry.currency)}<p className="text-xs text-slate-400">实收 {money(entry.gross_receipt_amount, entry.currency)}</p></td><td>{percent(entry.contract_rate)} × {percent(entry.activity_multiplier)}<p className="text-xs text-slate-400">{entry.inactivity_months} 月无新客</p></td><td className={entry.commission_amount < 0 ? 'font-semibold text-red-600' : 'font-semibold text-blue-700'}>{money(entry.commission_amount, entry.currency)}</td><td><Badge className={entry.status === 'paid' ? 'bg-emerald-100 text-emerald-700' : entry.status === 'pending_confirmation' ? 'bg-amber-100 text-amber-700' : 'bg-blue-100 text-blue-700'}>{entryStatusLabels[entry.status] || entry.status}</Badge></td><td className="px-4"><div className="flex gap-1">{entry.status === 'pending_confirmation' && <Button size="sm" variant="outline" onClick={() => transition(entry, 'confirmed')}>确认</Button>}{entry.status === 'confirmed' && <Button size="sm" variant="outline" onClick={() => transition(entry, 'payable')}>转应付</Button>}{entry.status === 'payable' && <Button size="sm" onClick={() => transition(entry, 'paid')}>已发放</Button>}{['pending_confirmation', 'confirmed'].includes(entry.status) && <Button size="sm" variant="ghost" className="text-red-600" onClick={() => transition(entry, 'reversed')}>作废</Button>}</div></td></tr>)}{filteredEntries.length === 0 && <tr><td colSpan={7} className="py-12 text-center text-slate-400"><p>当前没有符合计佣条件的记录。</p><p className="mt-1 text-xs">请确认归属生效日期、有效协议和生效日后的已确认服务实收，再执行“扫描实收与退款”。</p></td></tr>}</tbody></table> : <div className="commission-empty"><BadgeDollarSign className="mx-auto h-6 w-6 text-slate-400" /><p className="mt-5 font-medium text-slate-700">{search || month ? '没有匹配的佣金记录' : '暂无佣金记录'}</p><p className="mt-2 text-sm text-slate-500">{search || month ? '可以调整筛选条件后再查看。' : '扫描实收后，符合计佣条件的记录会显示在这里。'}</p></div>}</CardContent></Card></section>
      <section hidden={activeTab !== 'settlements'} aria-label="月度结算"><Card><CardHeader><div className="flex flex-wrap items-center justify-between gap-2"><div><CardTitle className="text-base">渠道月度结算单</CardTitle><p className="mt-1 text-xs text-slate-500">使用上方月份筛选生成结算口径；待确认不进入费用，已确认、待发放和已发放不会重复计费。</p></div><Button variant="outline" onClick={exportSettlements} disabled={!settlements.length}>导出结算 CSV</Button></div></CardHeader><CardContent className="overflow-x-auto p-0"><table className="w-full min-w-[900px] text-sm"><thead className="bg-slate-50 text-left text-xs text-slate-500"><tr><th className="px-4 py-3">渠道</th><th>币种</th><th>记录</th><th>待确认</th><th>已确认费用</th><th>待发放</th><th>已发放</th><th>退款冲回</th></tr></thead><tbody>{settlements.map(row => <tr key={`${row.partner_name}-${row.currency}`} className="border-t"><td className="px-4 py-3 font-medium">{row.partner_name}</td><td>{row.currency}</td><td>{row.entry_count}</td><td className="text-amber-700">{money(row.pending, row.currency)}</td><td className="font-semibold text-blue-700">{money(row.confirmed, row.currency)}</td><td>{money(row.payable, row.currency)}</td><td className="text-emerald-700">{money(row.paid, row.currency)}</td><td className={row.adjustments < 0 ? 'text-red-600' : ''}>{money(row.adjustments, row.currency)}</td></tr>)}{!settlements.length && <tr><td colSpan={8} className="py-12 text-center text-slate-400">当前月份暂无可结算佣金</td></tr>}</tbody></table></CardContent></Card></section>
      <section hidden={activeTab !== 'partners'} aria-label="渠道与协议"><div className="grid gap-4 lg:grid-cols-2">{(data?.partners || []).map(partner => { const rules = (data?.agreements || []).filter(item => item.partner_id === partner.id); return <Card key={partner.id}><CardHeader className="pb-3"><div className="flex items-start justify-between"><div><CardTitle className="text-base">{partner.name}</CardTitle><p className="text-xs text-slate-400">{partner.partner_code} · {partnerTypeLabels[partner.partner_type]}</p></div><Badge>{partnerStatusLabels[partner.status]}</Badge></div></CardHeader><CardContent><div className="space-y-2">{rules.map(rule => <div key={rule.id} className="rounded-lg border bg-slate-50 p-3 text-sm"><div className="flex justify-between"><span>协议 V{rule.version}</span><Badge variant="outline">{rule.status === 'active' ? '当前生效' : '历史版本'}</Badge></div><p className="mt-1 text-slate-600">首单 {percent(rule.first_order_rate)} · 续费 {percent(rule.renewal_rate)} · 观察期 {rule.refund_guard_days} 天</p><p className="text-xs text-slate-400">{rule.effective_from} 至 {rule.effective_to || '长期'}</p></div>)}{rules.length === 0 && <p className={`text-sm ${partner.partner_type === 'direct' ? 'text-emerald-700' : 'text-amber-600'}`}>{partner.partner_type === 'direct' ? '直营归属不产生外部佣金，无需协议' : '尚未配置分润协议'}</p>}</div>{partner.partner_type !== 'direct' && partner.status === 'active' && <div className="mt-4 flex gap-2"><Button size="sm" variant="outline" onClick={() => changePartnerStatus(partner, 'suspended')}>暂停结算</Button><Button size="sm" variant="outline" className="text-red-600" onClick={() => changePartnerStatus(partner, 'terminated')}>停止合作</Button></div>}{partner.partner_type !== 'direct' && partner.status === 'suspended' && <Button className="mt-4" size="sm" onClick={() => changePartnerStatus(partner, 'active')}>恢复合作</Button>}</CardContent></Card>})}{!data?.partners.length && <Card><CardContent className="py-12 text-center text-slate-400">先新增销售合伙人、代理商或内部销售。</CardContent></Card>}</div></section>
      <section hidden={activeTab !== 'attributions'} aria-label="客户归属"><Card><CardContent className="overflow-x-auto p-0"><table className="w-full text-sm"><thead className="bg-slate-50 text-left text-xs text-slate-500"><tr><th className="px-4 py-3">客户</th><th>归属渠道</th><th>项目</th><th>生效期间</th><th>当前状态</th></tr></thead><tbody>{filteredAttributions.map(item => <tr className="border-t" key={item.id}><td className="px-4 py-3 font-medium">{item.customer_name || `客户 #${item.customer_id}`}</td><td>{item.partner_name}</td><td>{item.engagement_id ? `项目 #${item.engagement_id}` : '客户全部项目'}</td><td>{item.effective_from} 至 {item.effective_to || '当前'}</td><td><Badge className={item.is_active ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-100 text-slate-600'}>{item.is_active ? '当前归属' : '历史归属'}</Badge></td></tr>)}</tbody></table></CardContent></Card></section>
      <section hidden={activeTab !== 'quality'} aria-label="待办事项"><div className="space-y-3">{(data?.quality_issues || []).map(issue => <Card key={issue.key} className={issue.severity === 'high' ? 'border-amber-200' : ''}><CardContent className="flex flex-wrap items-center justify-between gap-3 p-4"><div><div className="flex items-center gap-2"><Badge className={issue.severity === 'high' ? 'bg-amber-100 text-amber-800' : 'bg-slate-100 text-slate-700'}>{issue.severity === 'high' ? '高优先级' : '待补齐'}</Badge><p className="font-semibold text-slate-900">{issue.title}</p></div><p className="mt-2 text-sm text-slate-600">{issue.customer_name ? `${issue.customer_name} · ` : ''}{issue.description}</p></div><Button size="sm" variant="outline" onClick={() => resolveIssue(issue)}>{issue.partner_id ? '补充协议' : '设置归属'}</Button></CardContent></Card>)}{!data?.quality_issues?.length && <Card><CardContent className="py-12 text-center"><ShieldCheck className="mx-auto h-8 w-8 text-emerald-500" /><p className="mt-3 font-semibold text-emerald-800">分润数据检查通过</p><p className="mt-1 text-sm text-slate-500">当前付费项目和服务实收均有归属或适用协议。</p></CardContent></Card>}</div></section>
      <section hidden={activeTab !== 'rules'} aria-label="计算规则"><div className="grid gap-4 lg:grid-cols-3"><Card><CardContent className="p-5"><HandCoins className="h-6 w-6 text-blue-600" /><h3 className="mt-3 font-semibold">首单与续费分开</h3><p className="mt-1 text-sm text-slate-500">首笔有效服务费使用首单比例；同一客户后续实收使用续费比例。广告代充值始终排除。</p></CardContent></Card><Card><CardContent className="p-5"><AlertTriangle className="h-6 w-6 text-amber-600" /><h3 className="mt-3 font-semibold">续费活跃衰减</h3><p className="mt-1 text-sm text-slate-500">当月有新客 100%，连续 1–6 月无新客依次为 80%、60%、40%、25%、10%、0%。</p></CardContent></Card><Card><CardContent className="p-5"><Building2 className="h-6 w-6 text-emerald-600" /><h3 className="mt-3 font-semibold">停止合作自动归公司</h3><p className="mt-1 text-sm text-slate-500">停止日前已产生的分润继续结算；停止日后的续费不再计佣，原始客户来源和历史记录永久保留。</p></CardContent></Card></div></section>
    </div>
    {!isManagementView && <details className="commission-accounting"><summary className="cursor-pointer text-sm text-slate-500">财务汇总与记账规则</summary><div className="mt-5 space-y-4">
      {Object.entries(data?.summary.currencies || {}).map(([currency, values]) => <div key={currency} className="flex flex-wrap gap-x-6 gap-y-2 text-sm"><span className="font-medium">{currency}</span><span>已确认 {money(values.confirmed_expense, currency)}</span><span>待发放 {money(values.payable, currency)}</span><span>已发放 {money(values.paid, currency)}</span></div>)}
      <p className="text-sm leading-6 text-slate-500">{data?.summary.accounting_rule}。广告代充值不会参与佣金计算；退款生成独立负数冲回记录。</p>
    </div></details>}


    <Dialog open={dialog === 'partner'} onOpenChange={open => !open && setDialog(null)}><DialogContent><DialogHeader><DialogTitle>新增渠道或销售身份</DialogTitle></DialogHeader><div className="grid gap-3 sm:grid-cols-2"><div><Label>渠道编号 *</Label><Input value={partnerForm.partner_code} onChange={e => setPartnerForm(v => ({ ...v, partner_code: e.target.value }))} placeholder="例如 PARTNER-001" /></div><div><Label>名称 *</Label><Input value={partnerForm.name} onChange={e => setPartnerForm(v => ({ ...v, name: e.target.value }))} /></div><div><Label>身份类型</Label><NativeSelect value={partnerForm.partner_type} onChange={value => setPartnerForm(v => ({ ...v, partner_type: value, employee_id: value === 'employee' ? v.employee_id : '' }))} options={Object.entries(partnerTypeLabels).filter(([value]) => value !== 'direct').map(([value, label]) => ({ value, label }))} /></div><div><Label>加入日期</Label><Input type="date" value={partnerForm.joined_at} onChange={e => setPartnerForm(v => ({ ...v, joined_at: e.target.value }))} /></div>{partnerForm.partner_type === 'employee' && <div className="sm:col-span-2"><Label>关联员工 *</Label><NativeSelect value={partnerForm.employee_id} onChange={value => setPartnerForm(v => ({ ...v, employee_id: value }))} placeholder="选择员工" options={(options?.employees || []).map(item => ({ value: String(item.id), label: `${item.name}${item.employee_code ? ` · ${item.employee_code}` : ''}` }))} /></div>}<div><Label>联系人</Label><Input value={partnerForm.contact_name} onChange={e => setPartnerForm(v => ({ ...v, contact_name: e.target.value }))} /></div><div><Label>联系电话</Label><Input value={partnerForm.contact_phone} onChange={e => setPartnerForm(v => ({ ...v, contact_phone: e.target.value }))} /></div><div className="sm:col-span-2"><Label>邮箱</Label><Input value={partnerForm.contact_email} onChange={e => setPartnerForm(v => ({ ...v, contact_email: e.target.value }))} /></div><div className="sm:col-span-2"><Label>备注</Label><Textarea value={partnerForm.notes} onChange={e => setPartnerForm(v => ({ ...v, notes: e.target.value }))} /></div></div><DialogFooter><Button variant="outline" onClick={() => setDialog(null)}>取消</Button><Button disabled={working || !partnerForm.partner_code || !partnerForm.name || (partnerForm.partner_type === 'employee' && !partnerForm.employee_id)} onClick={submit}>保存渠道</Button></DialogFooter></DialogContent></Dialog>
    <Dialog open={dialog === 'agreement'} onOpenChange={open => !open && setDialog(null)}><DialogContent className="max-h-[90vh] overflow-y-auto"><DialogHeader><DialogTitle>新增协议版本</DialogTitle></DialogHeader><div className="space-y-3"><div><Label>渠道 *</Label><NativeSelect value={agreementForm.partner_id} onChange={value => setAgreementForm(v => ({ ...v, partner_id: value }))} placeholder="选择渠道" options={(data?.partners || []).filter(item => item.partner_type !== 'direct' && !['terminated', 'settled'].includes(item.status)).map(item => ({ value: String(item.id), label: `${item.name} · ${item.partner_code}` }))} /><p className="mt-1 text-xs text-slate-400">这里只显示合作中或暂停结算的非直营渠道。</p></div><div className="grid grid-cols-1 gap-3 sm:grid-cols-2"><div><Label>业务线</Label><NativeSelect value={agreementForm.business_line_id} onChange={value => setAgreementForm(v => ({ ...v, business_line_id: value, product_id: 'all' }))} options={[{ value: 'all', label: '全部业务线' }, ...(options?.business_lines || []).map(item => ({ value: String(item.id), label: item.name }))]} /></div><div><Label>具体产品</Label><NativeSelect value={agreementForm.product_id} onChange={value => setAgreementForm(v => ({ ...v, product_id: value }))} options={[{ value: 'all', label: '该范围全部产品' }, ...agreementProducts.map(item => ({ value: String(item.id), label: item.name }))]} /></div></div><p className="text-xs text-slate-500">比例相同时选择“全部业务线 / 该范围全部产品”；只有某条业务或某个产品比例不同时才缩小范围。</p><div className="grid grid-cols-1 gap-3 sm:grid-cols-3"><div><Label>首单比例 %</Label><Input type="number" min="0" max="100" value={agreementForm.first_order_rate} onChange={e => setAgreementForm(v => ({ ...v, first_order_rate: e.target.value }))} /></div><div><Label>续费比例 %</Label><Input type="number" min="0" max="100" value={agreementForm.renewal_rate} onChange={e => setAgreementForm(v => ({ ...v, renewal_rate: e.target.value }))} /></div><div><Label>退款观察天数</Label><Input type="number" min="0" value={agreementForm.refund_guard_days} onChange={e => setAgreementForm(v => ({ ...v, refund_guard_days: e.target.value }))} /></div></div><div><Label>连续无新客户时，续费比例保留倍率</Label><div className="mt-2 grid grid-cols-4 gap-2 sm:grid-cols-7">{agreementForm.decay_rates.map((rate, index) => <div key={index}><p className="mb-1 text-[11px] text-slate-500">{index} 月</p><Input type="number" min="0" max="100" value={rate} onChange={event => setAgreementForm(value => ({ ...value, decay_rates: value.decay_rates.map((item, itemIndex) => itemIndex === index ? event.target.value : item) }))} /></div>)}</div><p className="mt-1 text-xs text-slate-400">这里的 100% 是“保留全部合同续费比例”，不是把客户收入全部分给渠道。</p></div><div><Label>生效日期</Label><Input type="date" value={agreementForm.effective_from} onChange={e => setAgreementForm(v => ({ ...v, effective_from: e.target.value }))} /></div><div className="rounded-lg bg-amber-50 p-3 text-xs text-amber-800">保存后创建新版本，旧版本只会结束生效，不会重算过去已确认的佣金。</div><div><Label>备注</Label><Textarea value={agreementForm.notes} onChange={e => setAgreementForm(v => ({ ...v, notes: e.target.value }))} /></div></div><DialogFooter><Button variant="outline" onClick={() => setDialog(null)}>取消</Button><Button disabled={working || !agreementForm.partner_id} onClick={submit}>保存协议版本</Button></DialogFooter></DialogContent></Dialog>
    <Dialog open={dialog === 'attribution'} onOpenChange={open => !open && setDialog(null)}><DialogContent><DialogHeader><DialogTitle>设置客户/项目销售归属</DialogTitle></DialogHeader><div className="space-y-3"><div><Label>搜索客户编号或名称</Label><Input value={customerSearch} onChange={event => setCustomerSearch(event.target.value)} placeholder="输入客户编号或商家名称筛选" /></div><div><Label>客户 *</Label><NativeSelect value={attributionForm.customer_id} onChange={value => setAttributionForm(v => ({ ...v, customer_id: value, engagement_id: 'all' }))} placeholder={customerOptions.length ? '从搜索结果选择客户' : '没有匹配客户'} disabled={!customerOptions.length} options={customerOptions.map(item => ({ value: String(item.id), label: `${item.code ? `${item.code} · ` : ''}${item.name}` }))} /><p className="mt-1 text-xs text-slate-400">客户较多时先输入客户编号或商家名称，再从结果中选择。</p></div><div><Label>具体项目</Label><NativeSelect value={attributionForm.engagement_id} onChange={value => setAttributionForm(v => ({ ...v, engagement_id: value }))} disabled={!attributionForm.customer_id} options={[{ value: 'all', label: '客户全部项目' }, ...customerEngagements.map(item => ({ value: String(item.id), label: `${item.package_name || `项目 #${item.id}`} · ${item.status}` }))]} /></div><div><Label>归属渠道 *</Label><NativeSelect value={attributionForm.partner_id} onChange={value => setAttributionForm(v => ({ ...v, partner_id: value }))} placeholder="选择合作中的渠道" options={(data?.partners || []).filter(item => item.status === 'active').map(item => ({ value: String(item.id), label: `${item.name} · ${partnerTypeLabels[item.partner_type]}` }))} /></div><div><Label>生效日期</Label><Input type="date" value={attributionForm.effective_from} onChange={e => setAttributionForm(v => ({ ...v, effective_from: e.target.value }))} /></div><div><Label>归属依据</Label><Textarea value={attributionForm.source_note} onChange={e => setAttributionForm(v => ({ ...v, source_note: e.target.value }))} placeholder="例如：由该合伙人开发并完成首笔服务费收款" /></div></div><DialogFooter><Button variant="outline" onClick={() => setDialog(null)}>取消</Button><Button disabled={working || !attributionForm.customer_id || !attributionForm.partner_id} onClick={submit}>保存归属</Button></DialogFooter></DialogContent></Dialog>
    <Dialog open={dialog === 'bulkAttribution'} onOpenChange={open => !open && setDialog(null)}><DialogContent className="max-h-[90vh] max-w-4xl overflow-y-auto"><DialogHeader><DialogTitle>一键补齐客户归属</DialogTitle></DialogHeader>{bulkPreview && <div className="space-y-4"><div className="rounded-lg border border-blue-100 bg-blue-50 p-3 text-sm text-blue-900"><p className="font-semibold">执行前预览，不覆盖任何已有归属</p><p className="mt-1 text-blue-700">系统只自动处理依据明确的记录：匹配到内部销售则归该员工，否则归公司直营；冲突数据继续保留人工确认。</p></div><div className="grid grid-cols-2 gap-3 sm:grid-cols-4"><div className="rounded-lg border p-3"><p className="text-xs text-slate-500">可自动补齐</p><p className="mt-1 text-2xl font-bold text-blue-700">{bulkPreview.ready_count}</p></div><div className="rounded-lg border p-3"><p className="text-xs text-slate-500">内部销售</p><p className="mt-1 text-2xl font-bold">{bulkPreview.employee_count}</p></div><div className="rounded-lg border p-3"><p className="text-xs text-slate-500">公司直营</p><p className="mt-1 text-2xl font-bold text-emerald-700">{bulkPreview.direct_count}</p></div><div className="rounded-lg border p-3"><p className="text-xs text-slate-500">人工确认</p><p className="mt-1 text-2xl font-bold text-amber-600">{bulkPreview.manual_review_count}</p></div></div><div className="max-h-[45vh] overflow-auto rounded-lg border"><table className="w-full min-w-[760px] text-sm"><thead className="sticky top-0 bg-slate-50 text-left text-xs text-slate-500"><tr><th className="px-3 py-2">客户 / 项目</th><th>建议归属</th><th>生效日期</th><th className="px-3">判断依据</th></tr></thead><tbody>{bulkPreview.items.map(item => <tr key={`${item.customer_id}-${item.engagement_id || 'all'}`} className="border-t"><td className="px-3 py-3"><p className="font-medium">{item.customer_code ? `${item.customer_code} · ` : ''}{item.customer_name}</p><p className="text-xs text-slate-400">{item.engagement_id ? item.engagement_name || `项目 #${item.engagement_id}` : '客户全部项目'}</p></td><td><Badge className={item.status === 'ready' ? item.partner_type === 'direct' ? 'bg-emerald-100 text-emerald-700' : 'bg-blue-100 text-blue-700' : 'bg-amber-100 text-amber-800'}>{item.status === 'ready' ? item.partner_name : '待人工确认'}</Badge></td><td>{item.effective_from}</td><td className="px-3 text-xs text-slate-600">{item.basis}</td></tr>)}</tbody></table>{!bulkPreview.items.length && <div className="py-10 text-center text-sm text-emerald-700">当前没有需要补齐的客户归属</div>}</div><p className="text-xs text-slate-500">原始 {bulkPreview.source_issue_count} 条归属问题已按客户和项目合并为 {bulkPreview.target_count} 个处理目标；协议缺失不会在本次批量操作中自动修改。</p></div>}<DialogFooter><Button variant="outline" onClick={() => setDialog(null)}>取消</Button><Button disabled={working || !bulkPreview?.ready_count} onClick={applyBulkAttribution}>{working ? '正在处理...' : `确认补齐 ${bulkPreview?.ready_count || 0} 项`}</Button></DialogFooter></DialogContent></Dialog>
    </>}
  </div>;
}
