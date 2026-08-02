import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  Activity, AlertTriangle, CalendarDays, Clock3, History, PauseCircle,
  RefreshCw, Search, UserCheck, Users, UserX,
} from 'lucide-react';
import { toast } from 'sonner';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { client } from '@/lib/api';
import { useRole } from '@/lib/role-context';

type Summary = {
  new_customers: number;
  existing_customers: number;
  current_active: number;
  current_paused: number;
  pending_stop: number;
  stopped: number;
  retention_3m: number | null;
  retention_6m: number | null;
  retention_12m: number | null;
  median_tenure_months: number | null;
  average_stopped_months: number | null;
  review_count: number;
};

type LifecycleCustomer = {
  id: number;
  customer_id: number;
  business_name: string;
  customer_code?: string;
  cycle_number: number;
  first_payment_id?: number;
  started_at: string;
  ended_at?: string;
  status: string;
  start_source: string;
  start_locked: boolean;
  stop_reason?: string;
  stop_reason_label?: string;
  cooperation_months: number;
  source?: string;
  sales_person?: string;
  needs_review: boolean;
};

type LifecycleData = {
  summary: Summary;
  cohorts: Array<{ month: string; customers: number; m1: number | null; m3: number | null; m6: number | null; m12: number | null }>;
  monthly: Array<{ month: string; active_at_start: number; started: number; stopped: number; churn_rate: number }>;
  stop_reasons: Array<{ reason: string; label: string; count: number }>;
  customers: LifecycleCustomer[];
};

type DetailData = {
  customer: { id: number; business_name: string; customer_code?: string };
  cycles: LifecycleCustomer[];
  events: Array<{
    id: number;
    event_type: string;
    effective_at: string;
    reason_label?: string;
    note?: string;
    actor_name?: string;
    source_type?: string;
    source_id?: number;
  }>;
};

const statusLabels: Record<string, string> = {
  active: '合作中', paused: '暂停', pending_stop: '待确认停止', stopped: '已停止',
};

const statusClasses: Record<string, string> = {
  active: 'bg-emerald-100 text-emerald-700',
  paused: 'bg-amber-100 text-amber-700',
  pending_stop: 'bg-orange-100 text-orange-700',
  stopped: 'bg-red-100 text-red-700',
};

const eventLabels: Record<string, string> = {
  started: '第一笔有效记账', pause: '暂停合作', pending_stop: '进入待确认停止',
  resume: '恢复合作', stop: '停止合作', reactivate: '重新合作', adjust_start: '修正合作开始日期',
};

const stopReasonOptions = [
  ['performance', '效果不满意'], ['price', '价格问题'], ['service', '服务问题'],
  ['closed_business', '客户关店'], ['business_difficulty', '客户经营困难'],
  ['changed_provider', '更换服务商'], ['seasonal_pause', '季节性暂停'],
  ['payment', '付款问题'], ['owner_change', '老板变更'], ['data_correction', '历史数据修正'], ['other', '其他'],
];

const actionLabels: Record<string, string> = {
  pause: '暂停合作', pending_stop: '标记待确认停止', resume: '恢复合作', stop: '确认停止合作',
  reactivate: '确认重新合作', adjust_start: '修正开始日期',
};

function authOptions() {
  const token = localStorage.getItem('emp_auth_token') || localStorage.getItem('token');
  return token ? { headers: { Authorization: `Bearer ${token}` } } : undefined;
}

function getErrorMessage(error: any, fallback = '操作失败') {
  return error?.data?.detail || error?.response?.data?.detail || error?.message || fallback;
}

function formatDate(value?: string) {
  return value ? value.slice(0, 10) : '-';
}

function formatRate(value: number | null) {
  return value == null ? '样本未成熟' : `${value.toFixed(1)}%`;
}

function retentionClass(value: number | null) {
  if (value == null) return 'text-slate-400';
  if (value >= 75) return 'bg-emerald-50 text-emerald-700';
  if (value >= 50) return 'bg-amber-50 text-amber-700';
  return 'bg-red-50 text-red-700';
}

export default function CustomerLifecycle() {
  const { isAdmin } = useRole();
  const [searchParams] = useSearchParams();
  const today = new Date().toISOString().slice(0, 10);
  const [startDate, setStartDate] = useState('2026-01-01');
  const [asOf, setAsOf] = useState(today);
  const [data, setData] = useState<LifecycleData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [search, setSearch] = useState(searchParams.get('customer') || '');
  const [statusFilter, setStatusFilter] = useState('all');
  const [page, setPage] = useState(1);
  const [actionTarget, setActionTarget] = useState<LifecycleCustomer | null>(null);
  const [actionType, setActionType] = useState('');
  const [actionDate, setActionDate] = useState(today);
  const [actionReason, setActionReason] = useState('');
  const [actionNote, setActionNote] = useState('');
  const [actionSaving, setActionSaving] = useState(false);
  const [detail, setDetail] = useState<DetailData | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const loadData = async () => {
    setLoading(true);
    setError('');
    try {
      const response = await client.apiCall.invoke({
        url: `/api/v1/customer-lifecycle/overview?start_date=${startDate}&as_of=${asOf}`,
        method: 'GET',
        options: authOptions(),
      });
      setData(response.data);
    } catch (err: any) {
      setError(getErrorMessage(err, '生命周期数据加载失败'));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { void loadData(); }, []);
  useEffect(() => { setPage(1); }, [search, statusFilter]);

  const filteredCustomers = useMemo(() => {
    const keyword = search.trim().toLowerCase();
    return (data?.customers || []).filter(customer => {
      if (statusFilter !== 'all' && customer.status !== statusFilter) return false;
      if (!keyword) return true;
      return [customer.customer_id, customer.business_name, customer.customer_code, customer.sales_person]
        .filter(Boolean).some(value => String(value).toLowerCase().includes(keyword));
    });
  }, [data, search, statusFilter]);

  const pageSize = 20;
  const totalPages = Math.max(1, Math.ceil(filteredCustomers.length / pageSize));
  const visibleCustomers = filteredCustomers.slice((page - 1) * pageSize, page * pageSize);

  const openAction = (customer: LifecycleCustomer, action: string) => {
    setActionTarget(customer);
    setActionType(action);
    setActionDate(action === 'adjust_start' ? formatDate(customer.started_at) : today);
    setActionReason('');
    setActionNote('');
  };

  const submitAction = async () => {
    if (!actionTarget || !actionType) return;
    if (actionType === 'stop' && !actionReason) {
      toast.error('请选择停止合作原因');
      return;
    }
    if (actionType === 'adjust_start' && !actionNote.trim()) {
      toast.error('请填写修正原因');
      return;
    }
    setActionSaving(true);
    try {
      await client.apiCall.invoke({
        url: `/api/v1/customer-lifecycle/customers/${actionTarget.customer_id}/actions`,
        method: 'POST',
        data: {
          action: actionType,
          effective_date: actionDate,
          reason_code: actionReason || null,
          note: actionNote || null,
        },
        options: authOptions(),
      });
      toast.success(`${actionTarget.business_name}：${actionLabels[actionType]}完成`);
      setActionTarget(null);
      await loadData();
    } catch (err: any) {
      toast.error(getErrorMessage(err));
    } finally {
      setActionSaving(false);
    }
  };

  const runBackfill = async () => {
    setLoading(true);
    try {
      const response = await client.apiCall.invoke({
        url: '/api/v1/customer-lifecycle/backfill', method: 'POST', options: authOptions(),
      });
      const result = response.data || {};
      toast.success(`回溯完成：新增 ${result.created || 0}，更新 ${result.updated || 0}，待核对 ${result.review || 0}`);
      await loadData();
    } catch (err: any) {
      toast.error(getErrorMessage(err, '历史数据回溯失败'));
      setLoading(false);
    }
  };

  const openDetail = async (customer: LifecycleCustomer) => {
    setDetailLoading(true);
    setDetail({ customer: { id: customer.customer_id, business_name: customer.business_name, customer_code: customer.customer_code }, cycles: [], events: [] });
    try {
      const response = await client.apiCall.invoke({
        url: `/api/v1/customer-lifecycle/customers/${customer.customer_id}`,
        method: 'GET', options: authOptions(),
      });
      setDetail(response.data);
    } catch (err: any) {
      toast.error(getErrorMessage(err, '客户生命周期加载失败'));
      setDetail(null);
    } finally {
      setDetailLoading(false);
    }
  };

  const summary = data?.summary;
  const cards = [
    ['2026新客户', summary?.new_customers ?? 0, '第一笔有效记账在统计期内', Users, 'text-blue-600', 'bg-blue-50'],
    ['当前合作', summary?.current_active ?? 0, `历史存量 ${summary?.existing_customers ?? 0}`, UserCheck, 'text-emerald-600', 'bg-emerald-50'],
    ['暂停合作', summary?.current_paused ?? 0, '暂不计入正式流失', PauseCircle, 'text-amber-600', 'bg-amber-50'],
    ['待确认停止', summary?.pending_stop ?? 0, '需要管理员核对', AlertTriangle, 'text-orange-600', 'bg-orange-50'],
    ['已停止', summary?.stopped ?? 0, '统计期内正式停止', UserX, 'text-red-600', 'bg-red-50'],
    ['预计中位时长', summary?.median_tenure_months == null ? '尚未达到' : `${summary.median_tenure_months}月`, summary?.average_stopped_months == null ? '暂无已停止样本' : `已流失平均 ${summary.average_stopped_months}月`, Clock3, 'text-violet-600', 'bg-violet-50'],
  ] as const;

  return (
    <div className="app-page space-y-5">
      <div className="app-page-title gap-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-blue-600">T24 Marketing · Customer Lifecycle</p>
          <h1 className="mt-1 text-2xl font-bold text-slate-900">客户生命周期</h1>
          <p className="mt-1 text-sm text-slate-500">从第一笔有效记账开始，观察留存、暂停、停止与重新合作。</p>
        </div>
        <div className="flex flex-wrap gap-2">
          {isAdmin && <Button variant="outline" onClick={() => void runBackfill()} disabled={loading}><History className="mr-2 h-4 w-4" />回溯历史</Button>}
          <Button onClick={() => void loadData()} disabled={loading}><RefreshCw className={`mr-2 h-4 w-4 ${loading ? 'animate-spin' : ''}`} />刷新数据</Button>
        </div>
      </div>

      <Card className="border-slate-200">
        <CardContent className="flex flex-wrap items-end gap-3 p-4">
          <div><Label>统计开始</Label><Input type="date" value={startDate} min="2026-01-01" onChange={event => setStartDate(event.target.value)} className="mt-1 w-44" /></div>
          <div><Label>统计截止</Label><Input type="date" value={asOf} max={today} onChange={event => setAsOf(event.target.value)} className="mt-1 w-44" /></div>
          <Button variant="outline" onClick={() => void loadData()} disabled={loading}><CalendarDays className="mr-2 h-4 w-4" />应用时间</Button>
          <p className="text-xs text-slate-500">合作起点来自第一笔金额大于0且有实际收款日期的记账；套餐到期不会自动判定客户流失。</p>
        </CardContent>
      </Card>

      {error && <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">{error}</div>}

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-6">
        {cards.map(([label, value, hint, Icon, color, bg]) => (
          <Card key={label} className="border-slate-200">
            <CardContent className="p-4">
              <div className={`flex h-9 w-9 items-center justify-center rounded-xl ${bg}`}><Icon className={`h-4 w-4 ${color}`} /></div>
              <p className="mt-3 text-xs text-slate-500">{label}</p>
              <p className="mt-1 text-xl font-bold text-slate-900">{value}</p>
              <p className="mt-1 text-[11px] text-slate-400">{hint}</p>
            </CardContent>
          </Card>
        ))}
      </div>

      <div className="grid gap-4 xl:grid-cols-[1.4fr_1fr]">
        <Card className="border-slate-200">
          <CardHeader><CardTitle className="text-base">首笔记账月份留存</CardTitle><p className="text-xs text-slate-500">只统计第一笔有效记账发生在2026年后的新客户；样本未满对应月份时不强行计算。</p></CardHeader>
          <CardContent className="overflow-x-auto">
            <table className="w-full min-w-[620px] text-sm">
              <thead><tr className="border-b bg-slate-50 text-left text-xs text-slate-500"><th className="px-3 py-3">首笔记账月份</th><th className="px-3 py-3">新客户</th><th className="px-3 py-3">1个月</th><th className="px-3 py-3">3个月</th><th className="px-3 py-3">6个月</th><th className="px-3 py-3">12个月</th></tr></thead>
              <tbody>{(data?.cohorts || []).map(row => <tr key={row.month} className="border-b border-slate-100"><td className="px-3 py-3 font-medium">{row.month}</td><td className="px-3 py-3">{row.customers}</td>{[row.m1, row.m3, row.m6, row.m12].map((value, index) => <td key={index} className={`px-3 py-3 font-semibold ${retentionClass(value)}`}>{formatRate(value)}</td>)}</tr>)}</tbody>
            </table>
            {!loading && (data?.cohorts || []).length === 0 && <div className="py-10 text-center text-sm text-slate-400">统计期内暂无新客户生命周期数据</div>}
          </CardContent>
        </Card>

        <Card className="border-slate-200">
          <CardHeader><CardTitle className="text-base">停止合作原因</CardTitle><p className="text-xs text-slate-500">只统计管理员已经正式确认的停止记录。</p></CardHeader>
          <CardContent className="space-y-3">
            {(data?.stop_reasons || []).map(row => {
              const total = Math.max(summary?.stopped || 0, 1);
              return <div key={row.reason}><div className="flex justify-between text-sm"><span>{row.label}</span><span className="font-semibold">{row.count}</span></div><div className="mt-1 h-2 overflow-hidden rounded-full bg-slate-100"><div className="h-full rounded-full bg-red-400" style={{ width: `${Math.max(row.count * 100 / total, 6)}%` }} /></div></div>;
            })}
            {!loading && (data?.stop_reasons || []).length === 0 && <div className="py-10 text-center text-sm text-slate-400">暂无已确认停止记录</div>}
          </CardContent>
        </Card>
      </div>

      <Card className="border-slate-200">
        <CardHeader><CardTitle className="text-base">月度新增与流失</CardTitle></CardHeader>
        <CardContent className="overflow-x-auto">
          <table className="w-full min-w-[640px] text-sm"><thead><tr className="border-b bg-slate-50 text-left text-xs text-slate-500"><th className="px-3 py-3">月份</th><th className="px-3 py-3">月初合作</th><th className="px-3 py-3">新增周期</th><th className="px-3 py-3">正式停止</th><th className="px-3 py-3">月度流失率</th></tr></thead><tbody>{(data?.monthly || []).map(row => <tr key={row.month} className="border-b border-slate-100"><td className="px-3 py-3 font-medium">{row.month}</td><td className="px-3 py-3">{row.active_at_start}</td><td className="px-3 py-3 text-blue-600">+{row.started}</td><td className="px-3 py-3 text-red-600">{row.stopped}</td><td className="px-3 py-3 font-semibold">{row.churn_rate.toFixed(1)}%</td></tr>)}</tbody></table>
        </CardContent>
      </Card>

      <Card className="border-slate-200">
        <CardHeader className="gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div><CardTitle className="text-base">客户合作明细</CardTitle><p className="mt-1 text-xs text-slate-500">共 {filteredCustomers.length} 位客户 · 待核对 {summary?.review_count || 0}</p></div>
          <div className="flex flex-wrap gap-2"><div className="relative"><Search className="absolute left-3 top-2.5 h-4 w-4 text-slate-400" /><Input value={search} onChange={event => setSearch(event.target.value)} placeholder="搜索客户名称、编号、负责人" className="w-72 pl-9" /></div><select value={statusFilter} onChange={event => setStatusFilter(event.target.value)} className="h-10 rounded-md border border-slate-200 bg-white px-3 text-sm"><option value="all">全部状态</option>{Object.entries(statusLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></div>
        </CardHeader>
        <CardContent className="overflow-x-auto">
          <table className="w-full min-w-[1120px] text-sm"><thead><tr className="border-b bg-slate-50 text-left text-xs text-slate-500"><th className="px-3 py-3">客户</th><th className="px-3 py-3">合作开始</th><th className="px-3 py-3">时长</th><th className="px-3 py-3">状态</th><th className="px-3 py-3">停止日期/原因</th><th className="px-3 py-3">负责人</th><th className="px-3 py-3 text-right">操作</th></tr></thead><tbody>{visibleCustomers.map(customer => <tr key={customer.customer_id} className="border-b border-slate-100 align-top hover:bg-slate-50/60"><td className="px-3 py-3"><button type="button" onClick={() => void openDetail(customer)} className="text-left font-semibold text-blue-700 hover:underline">{customer.business_name}</button><p className="mt-1 text-xs text-slate-400">{customer.customer_code || '-'} · 第{customer.cycle_number}段合作</p></td><td className="px-3 py-3"><p>{formatDate(customer.started_at)}</p><p className="mt-1 text-xs text-slate-400">记账 #{customer.first_payment_id || '人工修正'}{customer.start_locked ? ' · 已锁定' : ''}</p></td><td className="px-3 py-3 font-semibold">{customer.cooperation_months}月</td><td className="px-3 py-3"><Badge className={statusClasses[customer.status]}>{statusLabels[customer.status] || customer.status}</Badge>{customer.needs_review && <p className="mt-1 text-xs text-orange-600">需要核对</p>}</td><td className="px-3 py-3"><p>{formatDate(customer.ended_at)}</p><p className="mt-1 text-xs text-slate-500">{customer.stop_reason_label || '-'}</p></td><td className="px-3 py-3">{customer.sales_person || '-'}</td><td className="px-3 py-3"><div className="flex justify-end gap-1"><Button size="sm" variant="ghost" onClick={() => void openDetail(customer)}>轨迹</Button>{isAdmin && <>{customer.status === 'active' && <Button size="sm" variant="outline" onClick={() => openAction(customer, 'pause')}>暂停</Button>}{['active', 'paused'].includes(customer.status) && <Button size="sm" variant="outline" className="text-orange-600" onClick={() => openAction(customer, 'pending_stop')}>待停止</Button>}{['paused', 'pending_stop'].includes(customer.status) && <Button size="sm" variant="outline" onClick={() => openAction(customer, 'resume')}>恢复</Button>}{['active', 'paused', 'pending_stop'].includes(customer.status) && <Button size="sm" variant="outline" className="text-red-600" onClick={() => openAction(customer, 'stop')}>停止</Button>}{customer.status === 'stopped' && <Button size="sm" variant="outline" onClick={() => openAction(customer, 'reactivate')}>重新合作</Button>}<Button size="sm" variant="ghost" onClick={() => openAction(customer, 'adjust_start')}>修正日期</Button></>}</div></td></tr>)}</tbody></table>
          {!loading && visibleCustomers.length === 0 && <div className="py-12 text-center text-sm text-slate-400">暂无符合条件的客户</div>}
          <div className="mt-4 flex items-center justify-between text-xs text-slate-500"><span>第 {page}/{totalPages} 页</span><div className="flex gap-2"><Button size="sm" variant="outline" disabled={page <= 1} onClick={() => setPage(value => value - 1)}>上一页</Button><Button size="sm" variant="outline" disabled={page >= totalPages} onClick={() => setPage(value => value + 1)}>下一页</Button></div></div>
        </CardContent>
      </Card>

      <Dialog open={!!actionTarget} onOpenChange={open => !open && setActionTarget(null)}>
        <DialogContent className="sm:max-w-lg"><DialogHeader><DialogTitle>{actionLabels[actionType] || '生命周期操作'}</DialogTitle></DialogHeader><div className="space-y-4"><div className="rounded-lg bg-slate-50 p-3 text-sm"><p className="font-semibold">{actionTarget?.business_name}</p><p className="mt-1 text-xs text-slate-500">当前状态：{statusLabels[actionTarget?.status || ''] || '-'}</p></div><div><Label>{actionType === 'adjust_start' ? '新的合作开始日期' : '生效日期'}</Label><Input type="date" value={actionDate} max={today} onChange={event => setActionDate(event.target.value)} className="mt-1" /></div>{actionType === 'stop' && <div><Label>停止合作原因 *</Label><select value={actionReason} onChange={event => setActionReason(event.target.value)} className="mt-1 h-10 w-full rounded-md border border-slate-200 bg-white px-3 text-sm"><option value="">请选择原因</option>{stopReasonOptions.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></div>}<div><Label>{actionType === 'adjust_start' ? '修正原因 *' : '备注'}</Label><Textarea value={actionNote} onChange={event => setActionNote(event.target.value)} rows={3} className="mt-1" placeholder={actionType === 'reactivate' ? '系统将使用停止合作后的第一笔有效收款作为新周期起点' : '填写业务背景，方便以后复盘'} /></div>{actionType === 'reactivate' && <p className="rounded-lg bg-blue-50 p-3 text-xs text-blue-700">重新合作必须已经存在停止日期之后的新收款；新周期开始日期自动取该笔收款日期。</p>}</div><DialogFooter><Button variant="outline" onClick={() => setActionTarget(null)}>取消</Button><Button onClick={() => void submitAction()} disabled={actionSaving}>{actionSaving ? '处理中…' : '确认'}</Button></DialogFooter></DialogContent>
      </Dialog>

      <Dialog open={!!detail} onOpenChange={open => !open && setDetail(null)}>
        <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-3xl"><DialogHeader><DialogTitle>{detail?.customer.business_name || '客户'} · 生命周期轨迹</DialogTitle></DialogHeader>{detailLoading ? <div className="py-12 text-center text-sm text-slate-400">正在加载…</div> : <div className="space-y-5"><div className="grid gap-3 sm:grid-cols-2">{(detail?.cycles || []).map(cycle => <div key={cycle.id} className="rounded-xl border border-slate-200 p-4"><div className="flex items-center justify-between"><p className="font-semibold">第{cycle.cycle_number}段合作</p><Badge className={statusClasses[cycle.status]}>{statusLabels[cycle.status]}</Badge></div><p className="mt-3 text-sm text-slate-600">{formatDate(cycle.started_at)} 至 {formatDate(cycle.ended_at)}</p><p className="mt-1 text-xs text-slate-400">起点：{cycle.first_payment_id ? `记账 #${cycle.first_payment_id}` : '管理员修正'} · {cycle.stop_reason_label || '暂无停止原因'}</p></div>)}</div><div><h3 className="mb-3 text-sm font-semibold text-slate-800">事件记录</h3><div className="relative space-y-3 before:absolute before:bottom-2 before:left-[7px] before:top-2 before:w-px before:bg-slate-200">{(detail?.events || []).map(event => <div key={event.id} className="relative flex gap-3"><span className="z-10 mt-2 h-3.5 w-3.5 rounded-full border-2 border-white bg-blue-500 ring-1 ring-blue-200" /><div className="flex-1 rounded-xl border border-slate-200 bg-slate-50 p-3"><div className="flex flex-wrap justify-between gap-2"><p className="text-sm font-semibold">{eventLabels[event.event_type] || event.event_type}</p><span className="text-xs text-slate-400">{formatDate(event.effective_at)}</span></div><p className="mt-1 text-xs text-slate-500">{event.reason_label || event.note || (event.source_id ? `${event.source_type} #${event.source_id}` : '无备注')} {event.actor_name ? `· ${event.actor_name}` : ''}</p></div></div>)}</div></div></div>}</DialogContent>
      </Dialog>
    </div>
  );
}
