import { useEffect, useMemo, useState } from 'react';
import {
  ArrowRight,
  CalendarRange,
  CircleDollarSign,
  RefreshCw,
  TrendingDown,
  TrendingUp,
  WalletCards,
} from 'lucide-react';
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { toast } from 'sonner';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { invokeWithAuth } from '@/lib/tokenStore';

type MonthlyProfitRow = {
  year_month: string;
  usd_revenue: number;
  usd_management_deduction: number;
  usd_cost: number;
  usd_operating_balance: number;
  exchange_rate: number;
  exchange_rate_status: string;
  exchange_rate_source: string;
  usd_converted_cny: number;
  cny_operating_income: number;
  cny_actual_expense: number;
  estimated_profit_cny: number;
  status: 'profit' | 'loss' | 'break_even';
};

type PeriodProfitRow = {
  period: string;
  month_count: number;
  usd_operating_balance: number;
  usd_converted_cny: number;
  cny_operating_income: number;
  cny_actual_expense: number;
  estimated_profit_cny: number;
  profitable_months: number;
  loss_months: number;
  break_even_months: number;
};

type ProfitPayload = {
  definition: string;
  usd_definition: string;
  payroll_note: string;
  start_date: string;
  end_date: string;
  fallback_exchange_rate: number;
  rows: MonthlyProfitRow[];
  quarterly: PeriodProfitRow[];
  yearly: PeriodProfitRow[];
  summary: PeriodProfitRow;
};

type ViewMode = 'month' | 'quarter' | 'year';

const localDate = (date: Date) => (
  `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
);

const monthEnd = (date: Date) => localDate(new Date(date.getFullYear(), date.getMonth() + 1, 0));
const cny = (value: number) => `¥${Number(value || 0).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const usd = (value: number) => `$${Number(value || 0).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

const compactCny = (value: number) => {
  const absolute = Math.abs(value);
  if (absolute >= 10000) return `${value < 0 ? '-' : ''}¥${(absolute / 10000).toFixed(1)}万`;
  return `${value < 0 ? '-' : ''}¥${Math.round(absolute).toLocaleString('zh-CN')}`;
};

export default function RmbProfitEstimate() {
  const today = useMemo(() => new Date(), []);
  const defaultStart = `${today.getFullYear()}-01-01`;
  const defaultEnd = localDate(today);
  const [startDate, setStartDate] = useState(defaultStart);
  const [endDate, setEndDate] = useState(defaultEnd);
  const [appliedRange, setAppliedRange] = useState({ start: defaultStart, end: defaultEnd });
  const [fallbackRate, setFallbackRate] = useState('6.7');
  const [appliedRate, setAppliedRate] = useState(6.7);
  const [viewMode, setViewMode] = useState<ViewMode>('month');
  const [payload, setPayload] = useState<ProfitPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadData = async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({
        start: appliedRange.start,
        end: appliedRange.end,
        fallback_rate: String(appliedRate),
      });
      const response = await invokeWithAuth({
        url: `/api/v1/reports/rmb-profit-estimate?${params.toString()}`,
        method: 'GET',
      });
      setPayload(response.data as ProfitPayload);
      setError(null);
    } catch (requestError: any) {
      setError(requestError?.data?.detail || requestError?.message || '人民币利润预估读取失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadData();
  }, [appliedRange.end, appliedRange.start, appliedRate]);

  const applyPreset = (preset: 'month' | 'quarter' | 'year' | 'all') => {
    let nextStart = defaultStart;
    let nextEnd = defaultEnd;
    if (preset === 'month') {
      nextStart = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-01`;
      nextEnd = monthEnd(today);
    } else if (preset === 'quarter') {
      const quarterStartMonth = Math.floor(today.getMonth() / 3) * 3;
      nextStart = localDate(new Date(today.getFullYear(), quarterStartMonth, 1));
      nextEnd = monthEnd(new Date(today.getFullYear(), quarterStartMonth + 2, 1));
    } else if (preset === 'all') {
      nextStart = '2026-01-01';
    }
    setStartDate(nextStart);
    setEndDate(nextEnd);
    setAppliedRange({ start: nextStart, end: nextEnd });
  };

  const applyCustomRange = () => {
    const parsedRate = Number(fallbackRate);
    if (!startDate || !endDate || endDate < startDate) {
      toast.error('请选择正确的开始和结束日期');
      return;
    }
    if (!Number.isFinite(parsedRate) || parsedRate <= 0.1 || parsedRate >= 20) {
      toast.error('预估汇率必须在 0.1 到 20 之间');
      return;
    }
    setAppliedRate(parsedRate);
    setAppliedRange({ start: startDate, end: endDate });
  };

  const tableRows = useMemo(() => {
    if (!payload) return [];
    if (viewMode === 'quarter') return payload.quarterly;
    if (viewMode === 'year') return payload.yearly;
    return payload.rows;
  }, [payload, viewMode]);

  const chartRows = useMemo(() => tableRows.map((row: any) => ({
    name: viewMode === 'month' ? row.year_month : row.period,
    profit: row.estimated_profit_cny,
  })), [tableRows, viewMode]);

  const summary = payload?.summary;
  const profitMargin = summary && summary.usd_converted_cny + summary.cny_operating_income > 0
    ? summary.estimated_profit_cny / (summary.usd_converted_cny + summary.cny_operating_income)
    : 0;

  return (
    <div className="app-page space-y-5">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-blue-600">T24 Marketing · RMB Profit Estimate</p>
          <h1 className="mt-1 text-2xl font-bold text-slate-900">人民币利润预估</h1>
          <p className="mt-1 text-sm text-slate-500">先核算美元经营结余，再按月均汇率折算，最后扣除财务中已录入的人民币实际支出。</p>
        </div>
        <Button variant="outline" onClick={() => void loadData()} disabled={loading}>
          <RefreshCw className={`mr-2 h-4 w-4 ${loading ? 'animate-spin' : ''}`} />刷新数据
        </Button>
      </div>

      <Card className="border-blue-100 bg-gradient-to-r from-blue-50 via-white to-emerald-50">
        <CardContent className="p-5">
          <div className="flex flex-wrap items-end gap-3">
            <div className="flex flex-wrap gap-2">
              <Button size="sm" variant="outline" onClick={() => applyPreset('month')}>本月</Button>
              <Button size="sm" variant="outline" onClick={() => applyPreset('quarter')}>本季度</Button>
              <Button size="sm" variant="outline" onClick={() => applyPreset('year')}>本年</Button>
              <Button size="sm" variant="outline" onClick={() => applyPreset('all')}>2026 至今</Button>
            </div>
            <div className="min-w-[150px] flex-1 lg:max-w-[190px]">
              <Label htmlFor="rmb-profit-start" className="text-xs">开始日期</Label>
              <Input id="rmb-profit-start" type="date" value={startDate} onChange={event => setStartDate(event.target.value)} className="mt-1 bg-white" />
            </div>
            <div className="min-w-[150px] flex-1 lg:max-w-[190px]">
              <Label htmlFor="rmb-profit-end" className="text-xs">结束日期</Label>
              <Input id="rmb-profit-end" type="date" value={endDate} onChange={event => setEndDate(event.target.value)} className="mt-1 bg-white" />
            </div>
            <div className="w-[170px]">
              <Label htmlFor="rmb-profit-rate" className="text-xs">缺失月份预估汇率</Label>
              <Input id="rmb-profit-rate" type="number" min="0.1" max="20" step="0.0001" value={fallbackRate} onChange={event => setFallbackRate(event.target.value)} className="mt-1 bg-white" />
            </div>
            <Button onClick={applyCustomRange}><CalendarRange className="mr-2 h-4 w-4" />查询</Button>
          </div>
          <p className="mt-3 text-xs text-slate-500">已保存的月均汇率优先使用；只有缺少汇率的月份才使用上面的预估值。页面仅供经营预估，不改变任何原始收支记录。</p>
        </CardContent>
      </Card>

      {error ? (
        <Card className="border-red-200 bg-red-50"><CardContent className="p-8 text-center"><p className="font-medium text-red-700">{error}</p><Button className="mt-4" variant="outline" onClick={() => void loadData()}>重新加载</Button></CardContent></Card>
      ) : loading && !payload ? (
        <div className="app-loading">正在计算人民币利润预估...</div>
      ) : payload && summary ? (
        <>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <Card><CardContent className="p-4"><div className="flex items-center justify-between"><p className="text-sm text-slate-500">美元经营结余</p><CircleDollarSign className="h-5 w-5 text-blue-600" /></div><p className="mt-2 text-2xl font-bold text-blue-700">{usd(summary.usd_operating_balance)}</p><p className="mt-1 text-xs text-slate-400">美元收入扣完美元端全部成本</p></CardContent></Card>
            <Card><CardContent className="p-4"><div className="flex items-center justify-between"><p className="text-sm text-slate-500">折合人民币</p><ArrowRight className="h-5 w-5 text-indigo-600" /></div><p className="mt-2 text-2xl font-bold text-indigo-700">{cny(summary.usd_converted_cny)}</p><p className="mt-1 text-xs text-slate-400">各月分别按对应月均汇率换算</p></CardContent></Card>
            <Card><CardContent className="p-4"><div className="flex items-center justify-between"><p className="text-sm text-slate-500">人民币实际支出</p><WalletCards className="h-5 w-5 text-amber-600" /></div><p className="mt-2 text-2xl font-bold text-amber-700">{cny(summary.cny_actual_expense)}</p><p className="mt-1 text-xs text-slate-400">工资如已录入运营支出，只在这里扣一次</p></CardContent></Card>
            <Card className={summary.estimated_profit_cny >= 0 ? 'border-emerald-200 bg-emerald-50/60' : 'border-red-200 bg-red-50/60'}><CardContent className="p-4"><div className="flex items-center justify-between"><p className="text-sm text-slate-500">预估人民币净利润</p>{summary.estimated_profit_cny >= 0 ? <TrendingUp className="h-5 w-5 text-emerald-600" /> : <TrendingDown className="h-5 w-5 text-red-600" />}</div><p className={`mt-2 text-2xl font-bold ${summary.estimated_profit_cny >= 0 ? 'text-emerald-700' : 'text-red-700'}`}>{cny(summary.estimated_profit_cny)}</p><p className="mt-1 text-xs text-slate-500">预估利润率 {(profitMargin * 100).toFixed(1)}%</p></CardContent></Card>
          </div>

          <Card>
            <CardHeader className="pb-3"><div className="flex flex-wrap items-center justify-between gap-3"><div><CardTitle className="text-base">利润趋势</CardTitle><p className="mt-1 text-xs text-slate-500">绿色为盈利，红色为亏损。</p></div><div className="flex rounded-lg border bg-slate-50 p-1">{([['month', '按月'], ['quarter', '按季度'], ['year', '按年']] as const).map(([key, label]) => <button key={key} type="button" onClick={() => setViewMode(key)} className={`rounded-md px-3 py-1.5 text-sm ${viewMode === key ? 'bg-white font-medium text-blue-700 shadow-sm' : 'text-slate-500'}`}>{label}</button>)}</div></div></CardHeader>
            <CardContent>
              <div className="h-[270px] w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={chartRows} margin={{ left: 8, right: 8, top: 8, bottom: 8 }}>
                    <CartesianGrid strokeDasharray="3 3" vertical={false} />
                    <XAxis dataKey="name" tick={{ fontSize: 12 }} />
                    <YAxis tickFormatter={compactCny} tick={{ fontSize: 11 }} width={72} />
                    <Tooltip formatter={(value: number) => [cny(value), '预估净利润']} />
                    <Bar dataKey="profit" radius={[5, 5, 0, 0]}>{chartRows.map(item => <Cell key={item.name} fill={item.profit >= 0 ? '#10b981' : '#ef4444'} />)}</Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-3"><CardTitle className="text-base">{viewMode === 'month' ? '每月计算明细' : viewMode === 'quarter' ? '季度汇总' : '年度汇总'}</CardTitle></CardHeader>
            <CardContent className="p-0">
              <div className="overflow-x-auto">
                <table className="w-full min-w-[980px] text-sm">
                  <thead><tr className="border-y bg-slate-50 text-left text-xs text-slate-500"><th className="px-4 py-3">期间</th><th className="px-4 py-3">美元经营结余</th><th className="px-4 py-3">月均汇率</th><th className="px-4 py-3">折合人民币</th><th className="px-4 py-3">人民币收入</th><th className="px-4 py-3">人民币实际支出</th><th className="px-4 py-3">预估人民币净利润</th><th className="px-4 py-3">结果</th></tr></thead>
                  <tbody>{tableRows.map((item: any) => {
                    const monthly = viewMode === 'month';
                    const period = monthly ? item.year_month : item.period;
                    const profit = Number(item.estimated_profit_cny || 0);
                    return <tr key={period} className="border-b align-top hover:bg-slate-50/70">
                      <td className="px-4 py-3 font-semibold text-slate-800">{period}{monthly && <details className="mt-1 max-w-[300px] text-xs font-normal text-slate-500"><summary className="cursor-pointer text-blue-600">查看美元结余公式</summary><p className="mt-1 leading-5">收入 {usd(item.usd_revenue)} − 管理扣点 {usd(item.usd_management_deduction)} − 美元成本 {usd(item.usd_cost)} = {usd(item.usd_operating_balance)}</p></details>}</td>
                      <td className="px-4 py-3 font-medium text-blue-700">{usd(item.usd_operating_balance)}</td>
                      <td className="px-4 py-3">{monthly ? <><p>{Number(item.exchange_rate).toFixed(4)}</p><p className="mt-1 text-xs text-slate-400">{item.exchange_rate_source}</p></> : <span className="text-xs text-slate-500">逐月换算</span>}</td>
                      <td className="px-4 py-3 text-indigo-700">{cny(item.usd_converted_cny)}</td>
                      <td className="px-4 py-3 text-emerald-700">{cny(item.cny_operating_income)}</td>
                      <td className="px-4 py-3 text-amber-700">{cny(item.cny_actual_expense)}</td>
                      <td className={`px-4 py-3 font-bold ${profit >= 0 ? 'text-emerald-700' : 'text-red-700'}`}>{cny(profit)}</td>
                      <td className="px-4 py-3"><Badge className={profit > 0 ? 'bg-emerald-100 text-emerald-700' : profit < 0 ? 'bg-red-100 text-red-700' : 'bg-slate-100 text-slate-600'}>{profit > 0 ? '盈利' : profit < 0 ? '亏损' : '持平'}</Badge>{!monthly && <p className="mt-1 text-xs text-slate-400">盈利 {item.profitable_months} 月 · 亏损 {item.loss_months} 月 · 持平 {item.break_even_months} 月</p>}</td>
                    </tr>;
                  })}</tbody>
                </table>
              </div>
            </CardContent>
          </Card>

          <Card className="border-slate-200 bg-slate-50"><CardContent className="p-4 text-xs leading-6 text-slate-600"><p className="font-semibold text-slate-800">计算口径</p><p>{payload.definition}</p><p>{payload.usd_definition}</p><p className="text-blue-700">{payload.payroll_note}</p></CardContent></Card>
        </>
      ) : null}
    </div>
  );
}
