import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { NativeSelect } from '@/components/ui/native-select';
import { formatPhoneNumber } from '@/lib/phone-format';
import { invokeWithAuth } from '@/lib/tokenStore';
import { localQueueSchedule, type RequestedSalesLead } from '@/pages/sales-workbench-flow';

export type SalesQueueView = 'today' | 'assigned' | 'callable';
type OwnedRow = {
  lead: { id: number; business_name: string; phone: string; country?: string; industry?: string; city?: string; state?: string };
  task_id: number | null;
  task_status: string | null;
  can_start: boolean;
  unavailable_reason: string | null;
  contact_queue: { local_time: string | null; next_window_at: string | null; in_contact_window: boolean | null };
};
type OwnedPage = { counts: { assigned: number; pending: number; callable: number }; items: OwnedRow[]; total: number; has_more: boolean };

type Props = {
  actor: number; salesId: number; date: string; isSelf: boolean; history: boolean; pendingSelected: boolean; pending?: number; view: SalesQueueView;
  target: RequestedSalesLead; busy: boolean;
  onView: (view: SalesQueueView) => void;
  onClearTarget: () => void;
  onDossier: (id: number) => void;
  onOpenTask: (id: number) => void;
  onStart: (id: number) => Promise<void>;
};

export default function SalesOwnedQueue({ actor, salesId, date, isSelf, pending, history, pendingSelected, view, target, busy,
  onView, onClearTarget, onDossier, onOpenTask, onStart }: Props) {
  const [page, setPage] = useState(0);
  const [industry, setIndustry] = useState('all');
  const [input, setInput] = useState('');
  const [query, setQuery] = useState('');
  const [starting, setStarting] = useState<number | null>(null);
  const [error, setError] = useState('');
  const pageSize = 20;
  const focused = view === 'assigned' ? target : null;
  useEffect(() => {
    const timer = window.setTimeout(() => { setQuery(input.trim()); setPage(0); }, 220);
    return () => window.clearTimeout(timer);
  }, [input]);
  const dataQuery = useQuery<OwnedPage>({
    queryKey: ['sales-workbench-owned', actor, salesId, date, view, industry, query, focused, page],
    queryFn: async () => {
      const params = new URLSearchParams({ target_date: date, sales_employee_id: String(salesId),
        view: view === 'today' ? 'summary' : view, skip: String(focused ? 0 : page * pageSize), limit: String(pageSize) });
      if (focused && typeof focused === 'number') params.set('lead_id', String(focused));
      if (!focused && view !== 'today') {
        if (industry !== 'all') params.set('industry', industry);
        if (query) params.set('q', query);
      }
      const { data } = await invokeWithAuth({ url: '/api/v1/sales-leads/workbench/owned?' + params, method: 'GET' });
      if (data?.sales_employee_id !== salesId || data?.target_date !== date || !data?.counts || !Array.isArray(data.items) || !Number.isInteger(data.total)) throw new Error('商家名单暂不可用');
      return data;
    },
    enabled: focused !== 'invalid',
    retry: false,
    staleTime: 15_000,
    refetchInterval: 60_000,
    refetchOnWindowFocus: true,
  });
  const result = dataQuery.data;
  const waiting = busy || starting !== null;
  const tabs = [
    { id: 'assigned' as const, label: isSelf ? '已分配给我' : '名下商家', count: result?.counts.assigned },
    { id: 'today' as const, label: history ? '当日待拨' : '今日待拨', count: pending ?? (history ? undefined : result?.counts.pending) },
    { id: 'callable' as const, label: '现在可拨', count: result?.counts.callable },
  ];
  async function start(id: number) {
    if (waiting) return;
    setStarting(id); setError('');
    try { await onStart(id); }
    catch (e: any) { setError(e?.data?.detail || e?.message || '开始联系失败，请重新核对当前归属'); void dataQuery.refetch(); }
    finally { setStarting(null); }
  }
  return <section className="sw-owned" aria-label="销售名单">
    <nav className="sw-owned-tabs" aria-label="名单范围">{tabs.map(tab =>
      <button type="button" key={tab.id} aria-pressed={view === tab.id && (tab.id !== 'today' || pendingSelected)} disabled={waiting}
        onClick={() => { if (tab.id !== view || tab.id === 'today') { onView(tab.id); setPage(0); setError(''); } }}>
        <span>{tab.label}</span><strong>{tab.count?.toLocaleString() ?? '—'}</strong>
      </button>)}</nav>
    {view === 'today' && dataQuery.isError && <div className="sw-owned-count-error" role="status">名下商家数量暂时无法更新
      <Button variant="ghost" size="sm" onClick={() => void dataQuery.refetch()}>重试</Button></div>}
    {view !== 'today' && <div className="sw-owned-list">
      {focused !== null ? <div className="sw-owned-filter"><strong>分配回执中的商家</strong>
        <Button size="sm" variant="outline" onClick={() => { setPage(0); setInput(''); setQuery(''); setIndustry('all'); onClearTarget(); }}>查看全部名下商家</Button></div> :
        <div className="sw-owned-filter"><Input value={input} maxLength={120} aria-label="搜索名下商家" placeholder="搜索商家或电话"
          onChange={e => setInput(e.target.value)} />
          <NativeSelect aria-label="名下商家行业" value={industry} onChange={v => { setIndustry(v); setPage(0); }}
            options={[{value:'all',label:'全部行业'},{value:'restaurant',label:'餐厅'},{value:'beauty',label:'美业'},{value:'other',label:'其他行业'}]} />
        </div>}
      {error && <p role="alert">{error}</p>}
      {focused === 'invalid' ? <p role="status">商家编号无效，请重新打开分配回执。</p> :
        dataQuery.isError ? <div role="alert">商家名单读取失败 <Button variant="ghost" size="sm" onClick={() => void dataQuery.refetch()}>重试</Button></div> :
        !result ? <p role="status">正在读取商家名单…</p> :
        !result.items.length ? <div className="sw-owned-empty" role="status">
          {focused ? '这家商家已不在该销售名下，或超出当前查看权限。' : query || industry !== 'all' ? '没有符合筛选的商家' :
           view === 'callable' ? '目前没有符合当地时段及联系条件的商家' : '暂无已分配的商家'}
          {view === 'callable' && <Button size="sm" variant="ghost" onClick={() => { setPage(0); setInput(''); setIndustry('all'); setQuery(''); onView('assigned'); }}>查看名下商家</Button>}
        </div> : <ul>{result.items.map(row => <li key={row.lead.id} data-lead-id={row.lead.id}>
          <div className="sw-owned-merchant"><button type="button" onClick={() => onDossier(row.lead.id)}>{row.lead.business_name}</button>
            <small>{[row.lead.industry, row.lead.city || row.lead.state, formatPhoneNumber(row.lead.phone, row.lead.country)].filter(Boolean).join(' · ')}</small>
          </div>
          <div className="sw-owned-timing"><span>{localQueueSchedule(row.contact_queue)}</span>
            <small>{row.unavailable_reason || (row.task_status === 'pending' ? '已在今日队列' : row.task_status === 'completed' ? '今日已记录' : '尚未排入今日待拨')}</small></div>
          {row.task_id && (row.task_status === 'pending' || row.task_status === 'completed') ?
            <Button size="sm" variant="outline" disabled={waiting} onClick={() => onOpenTask(row.lead.id)}>查看任务</Button> :
            isSelf && row.can_start ? <Button size="sm" variant="outline" disabled={waiting} onClick={() => void start(row.lead.id)}>{starting === row.lead.id ? '正在准备…' : '开始联系'}</Button> :
            <Button size="sm" variant="ghost" onClick={() => onDossier(row.lead.id)}>查看档案</Button>}
        </li>)}</ul>}
      {result && !dataQuery.isError && !focused && (result.total > pageSize || page > 0) && <div className="sw-owned-pager"><span>共 {result.total.toLocaleString()} 家 · 第 {page + 1} 页</span>
        <Button variant="outline" size="sm" disabled={page === 0 || waiting} onClick={() => setPage(v => v - 1)}>上一页</Button>
        <Button variant="outline" size="sm" disabled={!result.has_more || waiting} onClick={() => setPage(v => v + 1)}>下一页</Button></div>}
    </div>}
  </section>;
}
