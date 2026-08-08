import { useEffect, useMemo, useState } from 'react';
import { BadgeDollarSign, BriefcaseBusiness, RefreshCw, Users } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import PageLoadState from '@/components/PageLoadState';
import { getLoadErrorMessage } from '@/lib/load-utils';
import { invokeWithAuth } from '@/lib/tokenStore';
import { useAutoRefresh } from '@/lib/use-auto-refresh';

type CurrencySummary = { pending: number; confirmed: number; payable: number; paid: number };
type PortalData = {
  partner: { name: string; partner_code: string; status: string; joined_at: string; stopped_at?: string | null };
  summary: { active_customer_count: number; ledger_count: number; currencies: Record<string, CurrencySummary> };
  agreements: Array<{ id: number; version: number; business_line_name: string; product_name: string; first_order_rate: number; renewal_rate: number; activity_decay: Record<string, number>; refund_guard_days: number; effective_from: string; effective_to?: string | null; status: string }>;
  customers: Array<{ attribution_id: number; customer_code?: string | null; customer_name: string; engagement_name?: string | null; effective_from: string; effective_to?: string | null; is_active: boolean }>;
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
const money = (value: number, currency: string) => `${currency} ${Number(value || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const percent = (value: number) => `${(Number(value || 0) * 100).toFixed(0)}%`;

export default function PartnerPortal() {
  const [data, setData] = useState<PortalData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadData = async () => {
    try {
      const response = await invokeWithAuth({ url: '/api/v1/commissions/my-dashboard', method: 'GET' });
      setData(response.data);
      setError(null);
    } catch (err) {
      setError(getLoadErrorMessage(err));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { void loadData(); }, []);
  useAutoRefresh(loadData, { intervalMs: 60000 });

  const activeAgreements = useMemo(() => (data?.agreements || []).filter(item => item.status === 'active'), [data?.agreements]);
  if (loading && !data) return <PageLoadState loading message="正在核对您的客户归属与分润…" />;
  if (error && !data) return <PageLoadState error={error} onRetry={() => { setLoading(true); void loadData(); }} />;
  if (!data) return null;

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-blue-600">T24 Marketing · Partner</p>
          <h2 className="mt-1 text-xl font-semibold text-slate-900">我的客户与分润</h2>
          <p className="mt-1 text-sm text-slate-500">只展示归属于您的客户、协议和佣金，不包含公司整体财务及其他渠道数据。</p>
        </div>
        <Button variant="outline" size="sm" disabled={loading} onClick={() => void loadData()}><RefreshCw className={`mr-1 h-4 w-4 ${loading ? 'animate-spin' : ''}`} />刷新</Button>
      </div>

      <Card className="border-blue-100 bg-blue-50/40"><CardContent className="flex flex-wrap items-center justify-between gap-3 p-4"><div><p className="font-semibold text-slate-900">{data.partner.name}</p><p className="mt-1 text-xs text-slate-500">渠道编号 {data.partner.partner_code} · 加入 {data.partner.joined_at}</p></div><Badge className={data.partner.status === 'active' ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-100 text-slate-700'}>{partnerStatusLabels[data.partner.status] || data.partner.status}</Badge></CardContent></Card>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Card><CardContent className="p-4"><p className="flex items-center gap-2 text-xs text-slate-500"><Users className="h-4 w-4 text-blue-600" />当前归属客户</p><p className="mt-2 text-2xl font-semibold">{data.summary.active_customer_count}</p></CardContent></Card>
        <Card><CardContent className="p-4"><p className="flex items-center gap-2 text-xs text-slate-500"><BriefcaseBusiness className="h-4 w-4 text-violet-600" />生效协议</p><p className="mt-2 text-2xl font-semibold">{activeAgreements.length}</p></CardContent></Card>
        <Card><CardContent className="p-4"><p className="flex items-center gap-2 text-xs text-slate-500"><BadgeDollarSign className="h-4 w-4 text-emerald-600" />分润记录</p><p className="mt-2 text-2xl font-semibold">{data.summary.ledger_count}</p></CardContent></Card>
        <Card><CardContent className="p-4"><p className="text-xs text-slate-500">当前币种</p><p className="mt-2 text-2xl font-semibold">{Object.keys(data.summary.currencies).length || 0}</p></CardContent></Card>
      </div>

      {Object.entries(data.summary.currencies).length > 0 && <div className="grid gap-3 md:grid-cols-2">{Object.entries(data.summary.currencies).map(([currency, row]) => <Card key={currency}><CardHeader className="pb-2"><CardTitle className="text-base">{currency} 分润概况</CardTitle></CardHeader><CardContent className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4"><div><p className="text-xs text-slate-400">待确认</p><p className="mt-1 font-semibold text-amber-700">{money(row.pending, currency)}</p></div><div><p className="text-xs text-slate-400">累计确认</p><p className="mt-1 font-semibold text-blue-700">{money(row.confirmed, currency)}</p></div><div><p className="text-xs text-slate-400">可结算</p><p className="mt-1 font-semibold text-violet-700">{money(row.payable, currency)}</p></div><div><p className="text-xs text-slate-400">已发放</p><p className="mt-1 font-semibold text-emerald-700">{money(row.paid, currency)}</p></div></CardContent></Card>)}</div>}

      <Card><CardHeader><CardTitle className="text-base">我的客户归属</CardTitle></CardHeader><CardContent className="overflow-x-auto p-0"><table className="w-full min-w-[720px] text-sm"><thead className="bg-slate-50 text-left text-xs text-slate-500"><tr><th className="px-4 py-3">客户</th><th>归属项目</th><th>生效日期</th><th>状态</th></tr></thead><tbody>{data.customers.map(row => <tr key={row.attribution_id} className="border-t"><td className="px-4 py-3"><p className="font-medium">{row.customer_name}</p><p className="text-xs text-slate-400">{row.customer_code || '-'}</p></td><td>{row.engagement_name || '客户全部项目'}</td><td>{row.effective_from}{row.effective_to ? ` 至 ${row.effective_to}` : ''}</td><td><Badge className={row.is_active ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-100 text-slate-600'}>{row.is_active ? '当前归属' : '历史归属'}</Badge></td></tr>)}{data.customers.length === 0 && <tr><td colSpan={4} className="py-10 text-center text-slate-400">目前没有归属到您的客户</td></tr>}</tbody></table></CardContent></Card>

      <Card><CardHeader><CardTitle className="text-base">我的分润明细</CardTitle></CardHeader><CardContent className="overflow-x-auto p-0"><table className="w-full min-w-[980px] text-sm"><thead className="bg-slate-50 text-left text-xs text-slate-500"><tr><th className="px-4 py-3">月份 / 客户</th><th>类型</th><th>计佣金额</th><th>合同 × 活跃</th><th>我的佣金</th><th>状态</th><th className="px-4">发放凭证</th></tr></thead><tbody>{data.entries.map(row => <tr key={row.id} className="border-t"><td className="px-4 py-3"><p className="font-medium">{row.service_month} · {row.customer_name}</p><p className="text-xs text-slate-400">{row.engagement_name || '全部项目'}</p></td><td>{entryTypeLabels[row.entry_type] || row.entry_type}</td><td>{money(row.eligible_service_amount, row.currency)}</td><td>{percent(row.contract_rate)} × {percent(row.activity_multiplier)}<p className="text-xs text-slate-400">{row.inactivity_months} 个月无新客</p></td><td className={row.commission_amount < 0 ? 'font-semibold text-rose-600' : 'font-semibold text-blue-700'}>{money(row.commission_amount, row.currency)}</td><td><Badge className={entryStatusClasses[row.status] || 'bg-slate-100 text-slate-700'}>{entryStatusLabels[row.status] || row.status}</Badge></td><td className="px-4 text-xs text-slate-500">{row.payout_reference || '-'}</td></tr>)}{data.entries.length === 0 && <tr><td colSpan={7} className="py-10 text-center text-slate-400">目前没有分润记录</td></tr>}</tbody></table></CardContent></Card>

      <Card><CardHeader><CardTitle className="text-base">我的协议版本</CardTitle></CardHeader><CardContent className="space-y-3">{data.agreements.map(row => <div key={row.id} className="rounded-xl border border-slate-200 p-4"><div className="flex flex-wrap items-center justify-between gap-2"><div><p className="font-medium">V{row.version} · {row.business_line_name} · {row.product_name}</p><p className="mt-1 text-xs text-slate-400">{row.effective_from}{row.effective_to ? ` 至 ${row.effective_to}` : ' 起生效'}</p></div><Badge variant="outline">{row.status === 'active' ? '生效中' : '历史版本'}</Badge></div><div className="mt-3 grid grid-cols-2 gap-3 text-sm sm:grid-cols-4"><div><p className="text-xs text-slate-400">首单比例</p><p className="mt-1 font-semibold">{percent(row.first_order_rate)}</p></div><div><p className="text-xs text-slate-400">续费比例</p><p className="mt-1 font-semibold">{percent(row.renewal_rate)}</p></div><div><p className="text-xs text-slate-400">退款观察期</p><p className="mt-1 font-semibold">{row.refund_guard_days} 天</p></div><div><p className="text-xs text-slate-400">6个月无新客</p><p className="mt-1 font-semibold">保留 {percent(Number(row.activity_decay?.['6'] || 0))}</p></div></div></div>)}{data.agreements.length === 0 && <p className="py-8 text-center text-sm text-slate-400">尚未配置分润协议，请联系管理员</p>}</CardContent></Card>
    </div>
  );
}
