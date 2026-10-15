import { useEffect, useRef, useState } from 'react';
import { ChevronRight, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { HandoffRecord } from '@/components/CustomerSalesHandoff';
import { confirmDiscardAllChanges } from '@/lib/use-unsaved-changes';
import { dealHandoffApi, salesHandoffError, salesHandoffMoney, type SalesDealHandoff } from '@/lib/sales-deal-handoff';
import './sales-deal-handoff.css';

type QueueStatus = 'all' | 'pending_payment' | 'pending_operations' | 'pending_access' | 'completed';
type QueueItem = SalesDealHandoff & { pending_payment?: boolean; pending_operations?: boolean; pending_access?: boolean };
type Queue = { items: QueueItem[]; counts: Record<QueueStatus, number>; total: number; is_owner: boolean; status: QueueStatus };
const filters: { value: QueueStatus; label: string }[] = [{ value: 'pending_payment', label: '待核款' }, { value: 'pending_operations', label: '待接收' }, { value: 'pending_access', label: '待授权' }, { value: 'all', label: '全部登记' }, { value: 'completed', label: '已完成' }];

export default function SalesDealHandoffQueue({ onOpenLead }: { onOpenLead: (leadId: number) => void }) {
  const [status, setStatus] = useState<QueueStatus>('all');
  const [queue, setQueue] = useState<Queue | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [selected, setSelected] = useState<number | null>(null);
  const [detail, setDetail] = useState<SalesDealHandoff | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState('');
  const [detailBusy, setDetailBusy] = useState(false);
  const sequence = useRef(0);
  const initialized = useRef(false);
  const detailSequence = useRef(0);
  const load = async () => {
    const request = ++sequence.current;
    setLoading(true); setError('');
    try {
      const data = await dealHandoffApi<Queue>(`/queue?status=${status}`);
      if (sequence.current !== request) return;
      if (!Array.isArray(data.items) || !data.counts) throw new Error('成交与交接待办暂不可用。');
      setQueue(data);
      if (!initialized.current) { initialized.current = true; if (data.is_owner) setStatus('pending_payment'); }
    } catch (problem) { if (sequence.current === request) { setQueue(null); setError(salesHandoffError(problem, '成交与交接待办读取失败。')); } }
    finally { if (sequence.current === request) setLoading(false); }
  };
  const readDetail = async (id: number) => {
    const request = ++detailSequence.current;
    setSelected(id); setDetail(null); setDetailLoading(true); setDetailError('');
    try {
      const data = await dealHandoffApi<{ registered: boolean; handoff: SalesDealHandoff }>(`/${id}`);
      if (detailSequence.current !== request) return;
      if (data.handoff?.id !== id) throw new Error('交接资料不匹配，请重试。');
      setDetail(data.handoff);
    } catch (problem) { if (detailSequence.current === request) setDetailError(salesHandoffError(problem, '交接资料读取失败。')); }
    finally { if (detailSequence.current === request) setDetailLoading(false); }
  };
  useEffect(() => { void load(); return () => { sequence.current += 1; }; }, [status]);
  useEffect(() => () => { detailSequence.current += 1; }, []);
  return <section className="sdh-customer-card" aria-label="成交与交接待办">
    <div className="sdh-card-heading"><div><h3>成交与交接</h3><p>{queue?.is_owner ? '先核款，再处理运营授权与本人接收。' : '这里只显示当前账号有权查看的成交登记。'}</p></div><Button type="button" size="sm" variant="outline" disabled={loading} onClick={() => void load()}><RefreshCw size={14}/>刷新待办</Button></div>
    <nav className="sdh-queue-filters" aria-label="成交待办分类">{filters.filter(filter => !['pending_access', 'pending_payment'].includes(filter.value) || queue?.is_owner === true).map(filter => <Button key={filter.value} type="button" size="sm" variant={status === filter.value ? 'secondary' : 'outline'} aria-pressed={status === filter.value} onClick={() => setStatus(filter.value)}>{filter.label}<span>{queue?.counts[filter.value] ?? '—'}</span></Button>)}</nav>
    {error ? <p className="sdh-note sdh-error" role="alert">{error}</p> : loading ? <p className="py-8 text-center text-sm text-slate-500" role="status">正在读取成交待办…</p> : !queue?.items.length ? <p className="py-8 text-center text-sm text-slate-500">当前分类没有待处理的成交登记。</p> : <div className="sdh-queue-list">{queue.items.map(item => <article key={item.id}><div><strong>{item.business_name || `成交登记 #${item.id}`}</strong><p>{item.package_name}{typeof item.amount === 'number' ? ` · ${salesHandoffMoney(item.amount, item.currency)}` : ''}</p><div className="sdh-statuses">{item.pending_payment && <span>收款待核对</span>}{item.pending_operations && <span>运营待接收</span>}{item.pending_access && <span>待老板邀请</span>}{!item.pending_payment && !item.pending_operations && !item.pending_access && <span>{queue.is_owner ? '已完成' : '已登记，财务独立核对'}</span>}</div></div><Button type="button" size="sm" variant="outline" onClick={() => void readDetail(item.id)}>查看交接<ChevronRight size={14}/></Button></article>)}</div>}
    <Dialog open={selected !== null} onOpenChange={open => { if (!open && confirmDiscardAllChanges()) { setSelected(null); setDetail(null); detailSequence.current += 1; } }}><DialogContent className="max-h-[90dvh] max-w-2xl overflow-y-auto [&>button]:z-30"><DialogHeader><DialogTitle>成交与交接详情</DialogTitle></DialogHeader>{detailLoading ? <p role="status">正在读取交接…</p> : detailError ? <p className="sdh-note sdh-error" role="alert">{detailError}</p> : detail && <><HandoffRecord item={detail} onBusyChange={setDetailBusy} onChanged={async () => { await Promise.all([readDetail(detail.id), load()]); }}/><div className="sdh-receipt-actions">{detail.can_view_customer === true && <Button asChild variant="outline" disabled={detailBusy}><a aria-disabled={detailBusy} onClick={event => { if (!confirmDiscardAllChanges()) event.preventDefault(); }} href={`/customers?detail=${detail.customer_id}&returnTo=${encodeURIComponent('/sales-leads?view=handoffs')}`}>{detail.operations_access_status === 'authorized' ? '查看客户' : '去客户中心邀请授权'}</a></Button>}{detail.can_view_customer !== true && <p className="sdh-note">客户资料待老板邀请，请勿重复登记成交。</p>}<Button type="button" variant="ghost" disabled={detailBusy} onClick={() => { if (!confirmDiscardAllChanges()) return; setSelected(null); setDetail(null); onOpenLead(detail.lead_id); }}>查看登记回执</Button></div></>}</DialogContent></Dialog>
  </section>;
}
