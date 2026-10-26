import '@/pages/crm-sales-visual-polish.css';
import { CrmFormDialogContent, CrmFormDialogHeader, CrmFormDialogBody, CrmFormDialogFooter } from '@/components/ui/dialog';
import { useEffect, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { ChevronRight, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { HandoffRecord } from '@/components/CustomerSalesHandoff';
import { confirmDiscardAllChanges } from '@/lib/use-unsaved-changes';
import { dealHandoffApi, salesHandoffError, salesHandoffMoney, type SalesDealHandoff } from '@/lib/sales-deal-handoff';
import './sales-deal-handoff.css';
import { getSafeInternalPath } from '@/lib/navigation-state';
import { salesHandoffCustomerHref, salesHandoffReturnPath } from './sales-handoff-navigation';
import './owner-handoff-entry.css';

type QueueStatus = 'all' | 'pending_payment' | 'pending_operations' | 'pending_access' | 'completed';
type QueueItem = SalesDealHandoff & { pending_payment?: boolean; pending_operations?: boolean; pending_access?: boolean };
type Queue = { items: QueueItem[]; counts: Record<QueueStatus, number>; total: number; is_owner: boolean; status: QueueStatus };
const filters: { value: QueueStatus; label: string }[] = [{ value: 'pending_payment', label: '待核款' }, { value: 'pending_operations', label: '待接收' }, { value: 'pending_access', label: '待授权' }, { value: 'all', label: '全部登记' }, { value: 'completed', label: '已完成' }];

export default function SalesDealHandoffQueue({ onOpenLead }: { onOpenLead: (leadId: number) => void }) {
  const location = useLocation();
  const navigate = useNavigate();
  const search = new URLSearchParams(location.search);
  const requestedStatus = filters.some(item => item.value === search.get('status')) ? search.get('status') as QueueStatus : null;
  const requestedAction = search.get('action') === 'finance' ? 'finance' : search.get('action') === 'ack' ? 'ack' : null;
  const requestedHandoff = /^[1-9]\d*$/.test(search.get('handoff') || '') ? Number(search.get('handoff')) : null;
  const returnTo = getSafeInternalPath(search.get('returnTo'));
  const [status, setStatus] = useState<QueueStatus>(requestedStatus || 'all');
  const [queue, setQueue] = useState<Queue | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [selected, setSelected] = useState<number | null>(null);
  const [detail, setDetail] = useState<SalesDealHandoff | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState('');
  const [detailBusy, setDetailBusy] = useState(false);
  const [detailIntent, setDetailIntent] = useState<'ack' | 'finance' | null>(null);
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
      if (!initialized.current) { initialized.current = true; if (data.is_owner && !requestedStatus) setStatus('pending_payment'); }
    } catch (problem) { if (sequence.current === request) { setQueue(null); setError(salesHandoffError(problem, '成交与交接待办读取失败。')); } }
    finally { if (sequence.current === request) setLoading(false); }
  };
  const readDetail = async (id: number, intent: 'ack' | 'finance' | null = null) => {
    const request = ++detailSequence.current;
    setSelected(id); setDetailIntent(intent); setDetail(null); setDetailLoading(true); setDetailError('');
    try {
      const data = await dealHandoffApi<{ registered: boolean; handoff: SalesDealHandoff }>(`/${id}`);
      if (detailSequence.current !== request) return;
      if (data.handoff?.id !== id) throw new Error('交接资料不匹配，请重试。');
      setDetail(data.handoff);
    } catch (problem) { if (detailSequence.current === request) setDetailError(salesHandoffError(problem, '交接资料读取失败。')); }
    finally { if (detailSequence.current === request) setDetailLoading(false); }
  };
  useEffect(() => { void load(); return () => { sequence.current += 1; }; }, [status]);
  useEffect(() => { if (requestedStatus) setStatus(requestedStatus); }, [requestedStatus]);
  useEffect(() => { if (requestedHandoff) void readDetail(requestedHandoff, requestedAction); }, [requestedHandoff, requestedAction]);
  useEffect(() => () => { detailSequence.current += 1; }, []);
  return <section className="sdh-customer-card" aria-label="成交与交接待办">
    {returnTo && <Button type="button" variant="ghost" size="sm" onClick={() => navigate(returnTo)}>返回来源页面</Button>}
    <div className="sdh-card-heading"><div><h3>成交与交接</h3><p>{queue?.is_owner ? '核款、客户授权与运营本人接收分别推进；各项由对应负责人完成。' : '只显示有权查看的登记；收款由老板核对，客户权限由老板邀请。'}</p></div><Button type="button" size="sm" variant="outline" disabled={loading} onClick={() => void load()}><RefreshCw size={14}/>刷新待办</Button></div>
    <div className="sdh-work-lanes">
      {queue?.is_owner === true && <section className="sdh-work-lane sdh-work-lane-owner" aria-label="待我处理"><h4>待我处理</h4><nav className="sdh-queue-filters" aria-label="老板核对与授权">{filters.filter(filter => ['pending_payment', 'pending_access'].includes(filter.value)).map(filter => <Button key={filter.value} type="button" size="sm" variant={status === filter.value ? 'secondary' : 'outline'} aria-pressed={status === filter.value} onClick={() => setStatus(filter.value)}>{filter.label}<span>{queue?.counts[filter.value] ?? '—'}</span></Button>)}</nav></section>}
      <section className="sdh-work-lane" aria-label={queue?.is_owner === true ? '待团队接收' : '交接进度'}><h4>{queue?.is_owner === true ? '待团队接收' : '交接进度'}</h4><nav className="sdh-queue-filters" aria-label="运营接收分类">{filters.filter(filter => filter.value === 'pending_operations').map(filter => <Button key={filter.value} type="button" size="sm" variant={status === filter.value ? 'secondary' : 'outline'} aria-pressed={status === filter.value} onClick={() => setStatus(filter.value)}>{filter.label}<span>{queue?.counts[filter.value] ?? '—'}</span></Button>)}</nav></section>
    </div>
    <div className="sdh-queue-history"><nav className="sdh-queue-filters" aria-label="成交登记记录">{filters.filter(filter => ['all', 'completed'].includes(filter.value)).map(filter => <Button key={filter.value} type="button" size="sm" variant={status === filter.value ? 'secondary' : 'outline'} aria-pressed={status === filter.value} onClick={() => setStatus(filter.value)}>{filter.label}<span>{queue?.counts[filter.value] ?? '—'}</span></Button>)}</nav><p>同一成交可有多个待办，核款、授权与本人接收分别完成。</p></div>
    {error ? <p className="sdh-note sdh-error" role="alert">{error}</p> : loading ? <p className="py-8 text-center text-sm text-slate-500" role="status">正在读取成交待办…</p> : !queue?.items.length ? <p className="py-8 text-center text-sm text-slate-500">当前分类没有待处理的成交登记。</p> : <div className="sdh-queue-list">{queue.items.map(item => <article key={item.id}>
      <div className="sdh-queue-main"><div className="sdh-queue-title"><strong>{item.business_name || `成交登记 #${item.id}`}</strong>{typeof item.waiting_days === 'number' && (item.pending_payment || item.pending_operations || item.pending_access) && <span className="sdh-waiting">{item.waiting_days > 0 ? `已等待 ${item.waiting_days} 天` : '今日登记'}</span>}</div>
        <p>{item.package_name}{typeof item.amount === 'number' ? ` · ${salesHandoffMoney(item.amount, item.currency)}` : ''}</p>
        <ul className="sdh-next-tasks" aria-label="本单下一步">
          {item.pending_payment && (queue.is_owner || item.receipt_review_status === 'pending_owner_review') && <li><strong>核对收款</strong><span>老板 · 依据真实付款及结算凭据</span></li>}
          {item.pending_access && queue.is_owner && <li><strong>邀请运营授权</strong><span>老板 · 指定负责人不会自动获权</span></li>}
          {item.pending_operations && <li><strong>运营本人接收</strong><span>{item.operations_owner_name || '指定运营'} · {item.operations_access_status === 'authorized' ? '待本人核对交接资料' : '待老板邀请后本人接收'}</span></li>}
          {!queue.is_owner && item.can_request_payment === true && <li><strong>发送本单付款信息</strong><span>主要销售负责人 · 收款仍由老板核对</span></li>}
          {!item.pending_payment && !item.pending_operations && !item.pending_access && <li><strong>{queue.is_owner ? '交接已完成' : '登记已完成'}</strong><span>{queue.is_owner ? '按客户服务安排继续交付' : '财务状态按独立授权查看'}</span></li>}
        </ul>
      </div>
      <div className="sdh-queue-actions">{item.can_finance_confirm === true && <Button type="button" size="sm" variant="outline" onClick={() => void readDetail(item.id, 'finance')}>核对收款</Button>}{item.pending_access && queue.is_owner && item.can_view_customer === true && <Button type="button" size="sm" variant="outline" onClick={() => { if (!confirmDiscardAllChanges()) return; navigate(salesHandoffCustomerHref(item.customer_id, salesHandoffReturnPath(`${location.pathname}${location.search}`, status, item.id), true)); }}>邀请运营</Button>}{item.can_operations_ack === true && <Button type="button" size="sm" variant="outline" onClick={() => void readDetail(item.id, 'ack')}>本人接收</Button>}<Button type="button" size="sm" variant="outline" onClick={() => void readDetail(item.id)}>查看交接<ChevronRight size={14}/></Button></div>
    </article>)}</div>}
    <Dialog open={selected !== null} onOpenChange={open => { if (!open && confirmDiscardAllChanges()) { setSelected(null); setDetail(null); detailSequence.current += 1; } }}><CrmFormDialogContent className="max-w-2xl [&>button]:z-30 crm-sales-dialog-polish">
<CrmFormDialogHeader><DialogTitle>成交与交接详情</DialogTitle></CrmFormDialogHeader>
<CrmFormDialogBody className="crm-sales-dialog-body">{detailLoading ? <p role="status">正在读取交接…</p> : detailError ? <p className="sdh-note sdh-error" role="alert">{detailError}</p> : detail && <><HandoffRecord key={`${detail.id}-${detailIntent || 'view'}`} item={detail} initialAction={detailIntent} onBusyChange={setDetailBusy} onChanged={async () => { await Promise.all([readDetail(detail.id), load()]); }}/><div className="sdh-receipt-actions">{detail.can_view_customer === true && <Button type="button" variant="outline" disabled={detailBusy} onClick={() => { if (!confirmDiscardAllChanges()) return; navigate(salesHandoffCustomerHref(detail.customer_id, salesHandoffReturnPath(`${location.pathname}${location.search}`, status, detail.id), queue?.is_owner === true && detail.operations_access_status !== 'authorized')); }}>{queue?.is_owner === true && detail.operations_access_status !== 'authorized' ? '邀请运营授权' : '查看客户'}</Button>}{detail.can_view_customer !== true && <p className="sdh-note">客户资料待老板邀请，请勿重复登记成交。</p>}<Button type="button" variant="ghost" disabled={detailBusy} onClick={() => { if (!confirmDiscardAllChanges()) return; setSelected(null); setDetail(null); onOpenLead(detail.lead_id); }}>查看登记回执</Button></div></>}</CrmFormDialogBody>

</CrmFormDialogContent></Dialog>
  </section>;
}
