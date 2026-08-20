import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AlertTriangle, BadgeDollarSign, BriefcaseBusiness, Handshake, RefreshCw, Users } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { NativeSelect } from '@/components/ui/native-select';
import PageLoadState from '@/components/PageLoadState';
import { getLoadErrorMessage } from '@/lib/load-utils';
import { invokeWithAuth } from '@/lib/tokenStore';
import { useAutoRefresh } from '@/lib/use-auto-refresh';
import { useIsMobile } from '@/hooks/use-mobile';

type CurrencySummary = { pending: number; confirmed: number; payable: number; paid: number };
type PortalData = {
  portal_mode?: 'partner' | 'owner_readonly';
  available_partners?: Array<{ id: number; name: string; partner_code: string; status: string }>;
  partner: { id: number; name: string; partner_code: string; status: string; joined_at: string; stopped_at?: string | null };
  summary: { active_customer_count: number; cooperation_customer_count: number; renewal_attention_count: number; stopped_customer_count: number; ledger_count: number; currencies: Record<string, CurrencySummary>; status_updated_at: string };
  agreements: Array<{ id: number; version: number; business_line_name: string; product_name: string; first_order_rate: number; renewal_rate: number; activity_decay: Record<string, number>; refund_guard_days: number; effective_from: string; effective_to?: string | null; status: string }>;
  customers: Array<{ row_key: string; attribution_id: number; customer_code?: string | null; customer_name: string; engagement_name?: string | null; business_line_name?: string | null; product_name?: string | null; cooperation_status: string; renewal_status: string; next_due_at?: string | null; last_receipt_at?: string | null; commission_impact: string; effective_from: string; effective_to?: string | null; is_active: boolean }>;
  entries: Array<{ id: number; customer_name: string; engagement_name?: string | null; entry_type: string; status: string; service_month: string; currency: string; eligible_service_amount: number; contract_rate: number; inactivity_months: number; activity_multiplier: number; commission_amount: number; paid_at?: string | null; payout_reference?: string | null }>;
};

const partnerStatusLabels: Record<string, string> = { active: '合作中', suspended: '暂停结算', terminated: '已终止', settled: '已结清' };
const entryTypeLabels: Record<string, string> = { first_order: '首单', renewal: '续费', refund_reversal: '退款冲减' };
const entryStatusLabels: Record<string, string> = { pending_confirmation: '待确认', confirmed: '已确认', payable: '可结算', paid: '已发放', reversed: '已作废' };
const entryStatusClasses: Record<string, string> = {
  pending_confirmation: 'bg-amber-100 text-amber-700',
  confirmed: 'bg-blue-100 text-blue-700',
  payable: 'bg-violet-100 text-violet-700',
  paid: 'bg-emerald-100 text-emerald-700',
  reversed: 'bg-slate-100 text-slate-600',
};
const cooperationStatusLabels: Record<string, string> = {
  pending_setup: '待启动', trial: '试用中', active_paid: '合作中', at_risk: '合作风险', paused: '暂停服务',
  pending_stop: '待停止', stopped: '已停止', reactivated: '已恢复', completed: '已完成', unknown: '待补资料', historical: '历史归属',
};
const cooperationStatusClasses: Record<string, string> = {
  pending_setup: 'bg-blue-100 text-blue-700', trial: 'bg-violet-100 text-violet-700', active_paid: 'bg-emerald-100 text-emerald-700',
  at_risk: 'bg-amber-100 text-amber-700', paused: 'bg-slate-100 text-slate-700', pending_stop: 'bg-orange-100 text-orange-700',
  stopped: 'bg-rose-100 text-rose-700', reactivated: 'bg-cyan-100 text-cyan-700', completed: 'bg-slate-100 text-slate-600',
  unknown: 'bg-amber-50 text-amber-700', historical: 'bg-slate-100 text-slate-500',
};
const renewalStatusLabels: Record<string, string> = {
  active: '续费正常', expiring_soon: '即将到期', renewal_pending: '待扣款确认', expired: '已到期', renewed: '已续费',
  upgraded: '已升级结束', stopped: '停止续费', paused: '暂停续费', lost: '已流失', not_configured: '未建订阅资料', not_applicable: '无需续费', historical: '不再展示',
};
const renewalStatusClasses: Record<string, string> = {
  active: 'bg-emerald-100 text-emerald-700', expiring_soon: 'bg-amber-100 text-amber-700', renewal_pending: 'bg-cyan-100 text-cyan-700',
  expired: 'bg-rose-100 text-rose-700', renewed: 'bg-green-100 text-green-700', upgraded: 'bg-violet-100 text-violet-700',
  stopped: 'bg-slate-100 text-slate-600', paused: 'bg-slate-100 text-slate-600', lost: 'bg-rose-100 text-rose-700',
  not_configured: 'bg-amber-50 text-amber-700', not_applicable: 'bg-slate-100 text-slate-600', historical: 'bg-slate-100 text-slate-500',
};
const money = (value: number, currency: string) => `${currency} ${Number(value || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const percent = (value: number) => `${(Number(value || 0) * 100).toFixed(0)}%`;
const formatDate = (value?: string | null) => value ? new Date(value).toLocaleDateString('zh-CN', { timeZone: 'UTC' }) : '-';

export default function PartnerPortal() {
  const isMobile = useIsMobile();
  const [data, setData] = useState<PortalData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedPartnerId, setSelectedPartnerId] = useState<number | null>(null);
  const requestSequence = useRef(0);
  const requestInFlight = useRef(false);

  const loadData = useCallback(async (partnerId?: number | null, source: 'manual' | 'auto' = 'manual') => {
    if (source === 'auto' && requestInFlight.current) return;
    const requestId = requestSequence.current + 1;
    requestSequence.current = requestId;
    requestInFlight.current = true;
    if (source === 'manual') setLoading(true);
    try {
      const response = await invokeWithAuth({
        url: '/api/v1/commissions/my-dashboard',
        method: 'GET',
        data: partnerId ? { partner_id: partnerId } : undefined,
      });
      if (requestId !== requestSequence.current) return;
      const nextData = response.data as PortalData;
      setData(nextData);
      setSelectedPartnerId(nextData.partner.id);
      setError(null);
    } catch (err) {
      if (requestId !== requestSequence.current) return;
      setError(getLoadErrorMessage(err));
    } finally {
      if (requestId === requestSequence.current) {
        requestInFlight.current = false;
        setLoading(false);
      }
    }
  }, []);

  useEffect(() => { void loadData(); }, [loadData]);
  useAutoRefresh(() => loadData(selectedPartnerId, 'auto'), { intervalMs: 60000 });

  const activeAgreements = useMemo(() => (data?.agreements || []).filter(item => item.status === 'active'), [data?.agreements]);
  if (loading && !data) return <PageLoadState loading message="正在核对您的客户归属与分润…" />;
  if (error && !data) return <PageLoadState error={error} onRetry={() => { setLoading(true); void loadData(selectedPartnerId); }} />;
  if (!data) return null;

  return (
    <div className="partner-portal-page t24-command-page app-page space-y-5">
      <div className="app-page-title flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-blue-600">T24 Marketing · Partner</p>
          <h2 className="mt-1 text-xl font-semibold text-slate-900">我的客户与分润</h2>
          <p className="mt-1 text-sm text-slate-500">
            {data.portal_mode === 'owner_readonly'
              ? '老板只读查看单个合伙人的客户、协议和佣金；此页面不提供新增、修改或结算操作。'
              : '只展示归属于您的客户、协议和佣金，不包含公司整体财务及其他渠道数据。'}
          </p>
        </div>
        <Button variant="outline" size="sm" disabled={loading} onClick={() => void loadData(selectedPartnerId)}><RefreshCw className={`mr-1 h-4 w-4 ${loading ? 'animate-spin' : ''}`} />刷新</Button>
      </div>

      {error ? (
        <div className="flex flex-col gap-3 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900 sm:flex-row sm:items-center sm:justify-between" role="alert">
          <div><p className="font-semibold">合伙人数据刷新失败</p><p className="mt-1 text-xs text-amber-700">当前继续显示 {data.partner.name} 的上一次成功数据，未切换到其他对象。{error}</p></div>
          <Button type="button" size="sm" variant="outline" className="shrink-0 border-amber-200 bg-white text-amber-800" onClick={() => void loadData(selectedPartnerId)}>重试</Button>
        </div>
      ) : null}

      {data.portal_mode === 'owner_readonly' && (data.available_partners?.length || 0) > 0 ? (
        <Card className="border-indigo-100 bg-indigo-50/40">
          <CardContent className="grid gap-3 p-4 sm:grid-cols-[minmax(0,1fr)_minmax(16rem,24rem)] sm:items-center">
            <div>
              <p className="font-semibold text-slate-900">老板只读视图</p>
              <p className="mt-1 text-xs text-slate-500">一次只核对一个合伙人，切换不会改变归属、协议或结算状态。</p>
            </div>
            <NativeSelect
              value={String(selectedPartnerId || data.partner.id)}
              disabled={loading}
              onChange={(value) => {
                const nextPartnerId = Number(value);
                void loadData(nextPartnerId);
              }}
              options={(data.available_partners || []).map(row => ({
                value: String(row.id),
                label: `${row.name} · ${row.partner_code}${row.status === 'active' ? '' : '（非活跃）'}`,
              }))}
            />
          </CardContent>
        </Card>
      ) : null}

      <Card className="border-blue-100 bg-blue-50/40"><CardContent className="flex flex-wrap items-center justify-between gap-3 p-4"><div><p className="font-semibold text-slate-900">{data.partner.name}</p><p className="mt-1 text-xs text-slate-500">渠道编号 {data.partner.partner_code} · 加入 {data.partner.joined_at}</p></div><Badge className={data.partner.status === 'active' ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-100 text-slate-700'}>{partnerStatusLabels[data.partner.status] || data.partner.status}</Badge></CardContent></Card>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Card><CardContent className="p-4"><p className="flex items-center gap-2 text-xs text-slate-500"><Users className="h-4 w-4 text-blue-600" />当前归属客户</p><p className="mt-2 text-2xl font-semibold">{data.summary.active_customer_count}</p></CardContent></Card>
        <Card><CardContent className="p-4"><p className="flex items-center gap-2 text-xs text-slate-500"><BriefcaseBusiness className="h-4 w-4 text-violet-600" />生效协议</p><p className="mt-2 text-2xl font-semibold">{activeAgreements.length}</p></CardContent></Card>
        <Card><CardContent className="p-4"><p className="flex items-center gap-2 text-xs text-slate-500"><BadgeDollarSign className="h-4 w-4 text-emerald-600" />分润记录</p><p className="mt-2 text-2xl font-semibold">{data.summary.ledger_count}</p></CardContent></Card>
        <Card><CardContent className="p-4"><p className="text-xs text-slate-500">当前币种</p><p className="mt-2 text-2xl font-semibold">{Object.keys(data.summary.currencies).length || 0}</p></CardContent></Card>
      </div>

      {Object.entries(data.summary.currencies).length > 0 && <div className="grid gap-3 md:grid-cols-2">{Object.entries(data.summary.currencies).map(([currency, row]) => <Card key={currency}><CardHeader className="pb-2"><CardTitle className="text-base">{currency} 分润概况</CardTitle></CardHeader><CardContent className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4"><div><p className="text-xs text-slate-400">待确认</p><p className="mt-1 font-semibold text-amber-700">{money(row.pending, currency)}</p></div><div><p className="text-xs text-slate-400">累计确认</p><p className="mt-1 font-semibold text-blue-700">{money(row.confirmed, currency)}</p></div><div><p className="text-xs text-slate-400">可结算</p><p className="mt-1 font-semibold text-violet-700">{money(row.payable, currency)}</p></div><div><p className="text-xs text-slate-400">已发放</p><p className="mt-1 font-semibold text-emerald-700">{money(row.paid, currency)}</p></div></CardContent></Card>)}</div>}

      <Card>
        <CardHeader className="pb-3">
          <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
            <div><CardTitle className="text-base">客户合作与续费状态</CardTitle><p className="mt-1 text-xs text-slate-500">由客户生命周期、订阅到期和服务实收自动更新；此处仅供查看。</p></div>
            <p className="text-xs text-slate-400">最近核对 {formatDate(data.summary.status_updated_at)}</p>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-3">
            <div className="rounded-xl border border-emerald-100 bg-emerald-50/60 p-3"><p className="flex items-center gap-2 text-xs text-emerald-700"><Handshake className="h-4 w-4" />仍在合作</p><p className="mt-2 text-2xl font-semibold text-emerald-800">{data.summary.cooperation_customer_count}</p></div>
            <div className="rounded-xl border border-amber-100 bg-amber-50/60 p-3"><p className="flex items-center gap-2 text-xs text-amber-700"><AlertTriangle className="h-4 w-4" />续费需关注</p><p className="mt-2 text-2xl font-semibold text-amber-800">{data.summary.renewal_attention_count}</p></div>
            <div className="rounded-xl border border-slate-200 bg-slate-50 p-3"><p className="text-xs text-slate-600">已停止合作</p><p className="mt-2 text-2xl font-semibold text-slate-800">{data.summary.stopped_customer_count}</p></div>
          </div>
        </CardContent>
        {!isMobile && <CardContent className="overflow-x-auto p-0">
          <table className="w-full min-w-[1180px] text-sm">
            <thead className="bg-slate-50 text-left text-xs text-slate-500"><tr><th className="px-4 py-3">客户</th><th>合作项目</th><th>合作状态</th><th>续费状态</th><th>续费关键日期</th><th>分润影响</th><th className="px-4">归属</th></tr></thead>
            <tbody>{data.customers.map(row => <tr key={row.row_key} className="border-t align-top"><td className="px-4 py-3"><p className="font-medium">{row.customer_name}</p><p className="text-xs text-slate-400">{row.customer_code || '-'}</p></td><td className="py-3"><p>{row.engagement_name || row.product_name || '客户全部项目'}</p><p className="mt-1 text-xs text-slate-400">{[row.business_line_name, row.product_name].filter(Boolean).join(' · ') || '项目资料待补充'}</p></td><td className="py-3"><Badge className={cooperationStatusClasses[row.cooperation_status] || cooperationStatusClasses.unknown}>{cooperationStatusLabels[row.cooperation_status] || row.cooperation_status}</Badge></td><td className="py-3"><Badge className={renewalStatusClasses[row.renewal_status] || renewalStatusClasses.not_configured}>{renewalStatusLabels[row.renewal_status] || row.renewal_status}</Badge></td><td className="py-3 text-xs"><p>下次到期：{formatDate(row.next_due_at)}</p><p className="mt-1 text-slate-400">最近实收：{formatDate(row.last_receipt_at)}</p></td><td className="max-w-[220px] py-3 text-xs text-slate-600">{row.commission_impact}</td><td className="px-4 py-3"><Badge className={row.is_active ? 'bg-blue-100 text-blue-700' : 'bg-slate-100 text-slate-600'}>{row.is_active ? '当前归属' : '历史归属'}</Badge><p className="mt-1 text-xs text-slate-400">{row.effective_from}{row.effective_to ? ` 至 ${row.effective_to}` : ' 起'}</p></td></tr>)}{data.customers.length === 0 && <tr><td colSpan={7} className="py-10 text-center text-slate-400">目前没有归属到您的客户</td></tr>}</tbody>
          </table>
        </CardContent>}
      </Card>

      {isMobile && <section className="space-y-4" aria-label="手机端客户与分润明细">
        <Card>
          <CardHeader><CardTitle className="text-base">客户合作状态</CardTitle></CardHeader>
          <CardContent className="space-y-3">
            {data.customers.map(row => <article key={row.row_key} className="rounded-2xl border border-slate-200 p-4"><div className="flex items-start justify-between gap-3"><div className="min-w-0"><h3 className="truncate font-semibold text-slate-950">{row.customer_name}</h3><p className="mt-1 truncate text-xs text-slate-500">{row.engagement_name || row.product_name || '客户全部项目'}</p></div><Badge className={cooperationStatusClasses[row.cooperation_status] || cooperationStatusClasses.unknown}>{cooperationStatusLabels[row.cooperation_status] || row.cooperation_status}</Badge></div><div className="mt-3 flex flex-wrap gap-2"><Badge className={renewalStatusClasses[row.renewal_status] || renewalStatusClasses.not_configured}>{renewalStatusLabels[row.renewal_status] || row.renewal_status}</Badge><Badge variant="outline">{row.is_active ? '当前归属' : '历史归属'}</Badge></div><div className="mt-3 rounded-xl bg-slate-50 p-3 text-xs text-slate-600"><p>下次到期：{formatDate(row.next_due_at)}</p><p className="mt-1">最近实收：{formatDate(row.last_receipt_at)}</p><p className="mt-2 leading-5 text-slate-500">{row.commission_impact}</p></div></article>)}
            {data.customers.length === 0 && <div className="app-empty">目前没有归属到您的客户</div>}
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle className="text-base">我的分润明细</CardTitle></CardHeader>
          <CardContent className="space-y-3">
            {data.entries.map(row => <article key={row.id} className="rounded-2xl border border-slate-200 p-4"><div className="flex items-start justify-between gap-3"><div><h3 className="font-semibold text-slate-950">{row.customer_name}</h3><p className="mt-1 text-xs text-slate-500">{row.service_month} · {entryTypeLabels[row.entry_type] || row.entry_type}</p></div><Badge className={entryStatusClasses[row.status] || 'bg-slate-100 text-slate-700'}>{entryStatusLabels[row.status] || row.status}</Badge></div><p className={`mt-3 text-xl font-bold ${row.commission_amount < 0 ? 'text-rose-600' : 'text-blue-700'}`}>{money(row.commission_amount, row.currency)}</p><div className="mt-3 grid grid-cols-2 gap-2 rounded-xl bg-slate-50 p-3 text-xs"><div><p className="text-slate-400">计佣金额</p><p className="mt-1 font-medium">{money(row.eligible_service_amount, row.currency)}</p></div><div><p className="text-slate-400">合同 × 活跃</p><p className="mt-1 font-medium">{percent(row.contract_rate)} × {percent(row.activity_multiplier)}</p></div></div>{row.payout_reference ? <p className="mt-3 text-xs text-slate-500">发放凭证：{row.payout_reference}</p> : null}</article>)}
            {data.entries.length === 0 && <div className="app-empty">目前没有分润记录</div>}
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle className="text-base">我的协议版本</CardTitle></CardHeader>
          <CardContent className="space-y-3">{data.agreements.map(row => <div key={row.id} className="rounded-2xl border border-slate-200 p-4"><div className="flex items-start justify-between gap-2"><div><p className="font-medium">V{row.version} · {row.business_line_name}</p><p className="mt-1 text-xs text-slate-400">{row.product_name} · {row.effective_from}{row.effective_to ? ` 至 ${row.effective_to}` : ' 起'}</p></div><Badge variant="outline">{row.status === 'active' ? '生效中' : '历史'}</Badge></div><div className="mt-3 grid grid-cols-2 gap-2 text-sm"><div><p className="text-xs text-slate-400">首单比例</p><p className="mt-1 font-semibold">{percent(row.first_order_rate)}</p></div><div><p className="text-xs text-slate-400">续费比例</p><p className="mt-1 font-semibold">{percent(row.renewal_rate)}</p></div></div></div>)}{data.agreements.length === 0 && <div className="app-empty">尚未配置分润协议</div>}</CardContent>
        </Card>
      </section>}

      {!isMobile && <div>

      <Card><CardHeader><CardTitle className="text-base">我的分润明细</CardTitle></CardHeader><CardContent className="overflow-x-auto p-0"><table className="w-full min-w-[980px] text-sm"><thead className="bg-slate-50 text-left text-xs text-slate-500"><tr><th className="px-4 py-3">月份 / 客户</th><th>类型</th><th>计佣金额</th><th>合同 × 活跃</th><th>我的佣金</th><th>状态</th><th className="px-4">发放凭证</th></tr></thead><tbody>{data.entries.map(row => <tr key={row.id} className="border-t"><td className="px-4 py-3"><p className="font-medium">{row.service_month} · {row.customer_name}</p><p className="text-xs text-slate-400">{row.engagement_name || '全部项目'}</p></td><td>{entryTypeLabels[row.entry_type] || row.entry_type}</td><td>{money(row.eligible_service_amount, row.currency)}</td><td>{percent(row.contract_rate)} × {percent(row.activity_multiplier)}<p className="text-xs text-slate-400">{row.inactivity_months} 个月无新客</p></td><td className={row.commission_amount < 0 ? 'font-semibold text-rose-600' : 'font-semibold text-blue-700'}>{money(row.commission_amount, row.currency)}</td><td><Badge className={entryStatusClasses[row.status] || 'bg-slate-100 text-slate-700'}>{entryStatusLabels[row.status] || row.status}</Badge></td><td className="px-4 text-xs text-slate-500">{row.payout_reference || '-'}</td></tr>)}{data.entries.length === 0 && <tr><td colSpan={7} className="py-10 text-center text-slate-400">目前没有分润记录</td></tr>}</tbody></table></CardContent></Card>

      <Card><CardHeader><CardTitle className="text-base">我的协议版本</CardTitle></CardHeader><CardContent className="space-y-3">{data.agreements.map(row => <div key={row.id} className="rounded-xl border border-slate-200 p-4"><div className="flex flex-wrap items-center justify-between gap-2"><div><p className="font-medium">V{row.version} · {row.business_line_name} · {row.product_name}</p><p className="mt-1 text-xs text-slate-400">{row.effective_from}{row.effective_to ? ` 至 ${row.effective_to}` : ' 起生效'}</p></div><Badge variant="outline">{row.status === 'active' ? '生效中' : '历史版本'}</Badge></div><div className="mt-3 grid grid-cols-2 gap-3 text-sm sm:grid-cols-4"><div><p className="text-xs text-slate-400">首单比例</p><p className="mt-1 font-semibold">{percent(row.first_order_rate)}</p></div><div><p className="text-xs text-slate-400">续费比例</p><p className="mt-1 font-semibold">{percent(row.renewal_rate)}</p></div><div><p className="text-xs text-slate-400">退款观察期</p><p className="mt-1 font-semibold">{row.refund_guard_days} 天</p></div><div><p className="text-xs text-slate-400">6个月无新客</p><p className="mt-1 font-semibold">保留 {percent(Number(row.activity_decay?.['6'] || 0))}</p></div></div></div>)}{data.agreements.length === 0 && <p className="py-8 text-center text-sm text-slate-400">尚未配置分润协议，请联系管理员</p>}</CardContent></Card>
      </div>}
    </div>
  );
}
