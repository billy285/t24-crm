import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { ChevronDown, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { invokeWithAuth } from '@/lib/tokenStore';
import { AUTH_SESSION_EPOCH_KEY, AUTH_SESSION_INVALIDATED_EVENT, getAuthSessionEpoch } from '@/lib/auth-storage';
import { buildReturnLink } from '@/lib/navigation-state';
import { confirmDiscardAllChanges } from '@/lib/use-unsaved-changes';
import { buildCustomerWorkQueueItems, CustomerWorkQueueRequestGuard } from '@/lib/customer-work-queue';

type QueueProps = {
  actorKey: string;
  scopeKey: string;
  customers: readonly { id: number | string; business_name?: string }[];
  isOwner: boolean;
  canReadHandoffs: boolean;
  onOpenCustomer: (customerId: number, tab?: string) => void;
};
type Snapshot = { scope: string; session: string; source: 'owner' | 'handoffs'; items: unknown[]; coverageNote: string };
const categories = [{ key: 'all', label: '全部事项' }, { key: 'handoff', label: '待交接' }, { key: 'delivery', label: '开工事项' }, { key: 'renewal', label: '续费核对' }] as const;
const errorStatus = (error: any) => Number(error?.response?.status || error?.data?.status || error?.status);

/** Independent batch requests never block or refetch the customer directory. */
export default function CustomerWorkQueue({ actorKey, scopeKey, customers, isOwner, canReadHandoffs, onOpenCustomer }: QueueProps) {
  const navigate = useNavigate(), location = useLocation();
  const scope = JSON.stringify([actorKey, scopeKey, isOwner, canReadHandoffs]);
  const liveScope = useRef(scope); liveScope.current = scope;
  const guard = useRef(new CustomerWorkQueueRequestGuard());
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [category, setCategory] = useState<(typeof categories)[number]['key']>('all');
  const [expanded, setExpanded] = useState(false);
  const allowed = isOwner || canReadHandoffs;
  const load = useCallback(async () => {
    if (!allowed) return;
    const request = guard.current.begin(scope, getAuthSessionEpoch());
    const current = () => guard.current.current(request, liveScope.current, getAuthSessionEpoch());
    setLoading(true); setError('');
    try {
      const response = await invokeWithAuth({ url: isOwner ? '/api/v1/service-follow-through/owner-overview' : '/api/v1/sales-deal-handoffs/queue?status=all', method: 'GET', options: { signal: request.signal } });
      if (!current()) return;
      const data = response?.data;
      if (!data || !Array.isArray(data.items) || (!isOwner && data.is_owner !== false)) throw new Error('待办资料格式不完整');
      setSnapshot({ scope, session: request.session, source: isOwner ? 'owner' : 'handoffs', items: data.items,
        coverageNote: isOwner && typeof data.coverage?.note === 'string' ? data.coverage.note : '' });
    } catch (failure) {
      if (!current()) return;
      if ([401, 403, 404].includes(errorStatus(failure))) setSnapshot(null);
      setError([401, 403, 404].includes(errorStatus(failure)) ? '当前待办资料不可读取，请核对账号权限后重试。' : '待办资料暂不可用，请重试。');
    } finally { if (current()) setLoading(false); }
  }, [allowed, isOwner, scope]);
  useEffect(() => {
    setSnapshot(null); setError(''); setLoading(false); setCategory('all'); setExpanded(false);
    void load();
    return () => guard.current.invalidate();
  }, [load]);
  useEffect(() => {
    const invalidate = () => { guard.current.invalidate(); setSnapshot(null); setError(''); setLoading(false); };
    const storage = (event: StorageEvent) => { if (event.key === AUTH_SESSION_EPOCH_KEY) invalidate(); };
    window.addEventListener(AUTH_SESSION_INVALIDATED_EVENT, invalidate);
    window.addEventListener('storage', storage);
    return () => { window.removeEventListener(AUTH_SESSION_INVALIDATED_EVENT, invalidate); window.removeEventListener('storage', storage); };
  }, []);
  const visibleSnapshot = snapshot?.scope === scope && snapshot.session === getAuthSessionEpoch() ? snapshot : null;
  const items = useMemo(() => buildCustomerWorkQueueItems({ source: visibleSnapshot?.source || 'handoffs', items: visibleSnapshot?.items, visibleCustomers: customers }), [visibleSnapshot, customers]);
  const filtered = category === 'all' ? items : items.filter(item => item.category === category);
  const shown = expanded ? filtered : filtered.slice(0, 3);
  const navigateTo = (href: string) => { if (href && !error && confirmDiscardAllChanges()) navigate(buildReturnLink(href, `${location.pathname}${location.search}`)); };
  return <details className="customer-work-queue min-w-0 rounded-xl border border-slate-200 bg-white" aria-busy={loading}>
    <summary className="flex min-h-11 cursor-pointer flex-wrap items-center gap-2 px-4 py-3 text-sm"><strong>当前可见待办</strong><span className="text-slate-500">{visibleSnapshot ? `${items.length} 项` : allowed ? error ? '暂不可用' : '待读取' : '未开放'}{loading ? ' · 更新中' : ''}</span><ChevronDown size={15} className="ml-auto shrink-0" aria-hidden="true" /></summary>
    <div className="space-y-3 border-t border-slate-100 p-4">
      <div className="flex flex-wrap items-start justify-between gap-2"><p className="min-w-0 flex-1 text-xs leading-5 text-slate-500">当前已读取客户范围 · {isOwner ? '团队交接、开工与续费事项，按负责环节处理' : '已授权交接队列；开工与续费数据另按权限查看'}。按事项计数，同一客户可能有多项。</p>{allowed && <Button type="button" size="sm" variant="outline" className="min-h-11 shrink-0" disabled={loading} onClick={() => void load()}><RefreshCw size={14} className={loading ? 'animate-spin' : ''} />刷新待办</Button>}</div>
      {!allowed && <p className="text-sm text-slate-500">当前账号未开放交接待办来源，客户目录仍可正常使用。</p>}
      {error && <p role="alert" className="text-sm text-amber-800">{error}{visibleSnapshot ? ' 以下保留上次结果，处理入口暂停，刷新成功后再判断。' : ''}</p>}
      {!visibleSnapshot && loading && <p role="status" className="text-sm text-slate-500">正在读取待办资料…</p>}
      {visibleSnapshot && <>
        {isOwner && <nav className="flex flex-wrap gap-2" aria-label="客户待办分类">{categories.map(item => <Button type="button" key={item.key} size="sm" variant={category === item.key ? 'secondary' : 'outline'} className="min-h-11" aria-pressed={category === item.key} onClick={() => { setCategory(item.key); setExpanded(false); }}>{item.label} {item.key === 'all' ? items.length : items.filter(row => row.category === item.key).length}</Button>)}</nav>}
        {shown.length ? <ul className="divide-y divide-slate-100">{shown.map(item => <li key={item.key} className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1 py-2"><div className="min-w-0 flex-1 basis-40"><p className="break-words text-sm font-medium" title={item.title}>{item.title}</p><p className="break-words text-xs leading-5 text-slate-500" title={item.customerName}>{item.customerName}{item.waitingDays ? ` · 已等待 ${item.waitingDays} 天` : ''}</p></div><div className="flex flex-wrap gap-1"><Button type="button" size="sm" variant="ghost" className="min-h-11" onClick={() => onOpenCustomer(item.customerId, item.category === 'renewal' ? 'renewals' : undefined)}>查看客户</Button><Button type="button" size="sm" variant="outline" className="min-h-11" disabled={!item.href || Boolean(error)} onClick={() => navigateTo(item.href)}>去处理</Button></div></li>)}</ul> : <p className="text-sm text-slate-500">当前已读取客户范围内，此来源暂无待处理事项。</p>}
        {filtered.length > 3 && <Button type="button" size="sm" variant="ghost" className="min-h-11" onClick={() => setExpanded(value => !value)}>{expanded ? '收起事项' : `查看当前分类全部 ${filtered.length} 项`}</Button>}
        {isOwner && <p className="text-xs leading-5 text-slate-500">{visibleSnapshot.coverageNote || '续费仅依据已关联记录与已接收通知；没有异常通知不等于扣款正常。'}</p>}
      </>}
    </div>
  </details>;
}
