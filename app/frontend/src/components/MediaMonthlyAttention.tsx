import { useEffect, useRef, useState } from 'react';
import { AlertCircle, ArrowRight, ClipboardCheck, Loader2, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { monthlyApi } from '@/lib/media-monthly-api';
import { verifiedMonthlyAttention, type MonthlyAttention } from '@/lib/media-monthly-attention';
import './media-monthly-attention.css';

type Props = { scope: string; isOwner: boolean; customerId: number | null; visible: boolean; refreshToken: number; onOpen: (runId: number) => void };

export default function MediaMonthlyAttention(props: Props) {
  if (!props.isOwner || !props.visible || props.customerId !== null && props.customerId !== 20) return null;
  return <OwnerAttention key={`${props.scope}:${props.customerId ?? 'all'}`} {...props}/>;
}

function OwnerAttention({ scope, customerId, refreshToken, onOpen }: Props) {
  const identity = `${scope}:${customerId ?? 'all'}`, current = useRef(identity);
  current.current = identity;
  const [data, setData] = useState<MonthlyAttention | null>(null), [loading, setLoading] = useState(true), [failed, setFailed] = useState(false), [refresh, setRefresh] = useState(0);

  useEffect(() => {
    let active = true, controller: AbortController | null = null;
    async function read() {
      controller?.abort();
      const request = new AbortController(); controller = request;
      setLoading(true); setData(null); setFailed(false);
      try {
        const value = verifiedMonthlyAttention(await monthlyApi<MonthlyAttention>('/customers/20/workflow-alerts', 'GET', undefined, request.signal));
        if (active && !request.signal.aborted && current.current === identity) setData(value);
      } catch {
        if (active && !request.signal.aborted && current.current === identity) setFailed(true);
      } finally {
        if (active && !request.signal.aborted && current.current === identity) setLoading(false);
      }
    }
    const whenVisible = () => { if (document.visibilityState !== 'hidden') void read(); };
    void read();
    const timer = window.setInterval(whenVisible, 60000);
    document.addEventListener('visibilitychange', whenVisible);
    return () => { active = false; controller?.abort(); window.clearInterval(timer); document.removeEventListener('visibilitychange', whenVisible); };
  }, [identity, refresh, refreshToken]);

  if (loading) return <section className="mw-month-attention" role="status"><Loader2 className="animate-spin"/><span>正在核对北方面食月度发布提醒…</span></section>;
  if (failed || !data) return <section className="mw-month-attention warning"><AlertCircle/><div><strong>月度提醒暂时无法读取</strong><p>请重新读取后核对，当前无法确认是否有待办。</p></div><Button variant="outline" onClick={() => setRefresh(value => value + 1)}><RefreshCw/>重新读取</Button></section>;
  if (!data.run_id && !data.counts.total && !data.counts.pending_confirmation) return null;
  const runId = data.run_id, exceptions = data.counts.attention;
  return <section className={`mw-month-attention${exceptions ? ' warning' : ''}`} aria-label="北方面食月度发布提醒">
    {exceptions ? <AlertCircle/> : <ClipboardCheck/>}
    <div><strong>北方面食 · 月度发布</strong><p>{data.counts.pending_confirmation > 0 ? `${data.counts.pending_confirmation} 批等待你确认` : '查看本月执行进度'}<span> · </span>{exceptions ? `${exceptions} 项发布异常待处理` : '当前未发现发布异常'}</p>{exceptions > 0 && data.items[0] && <p>{data.items[0].title}</p>}</div>
    {runId && <Button variant="outline" onClick={() => { if (current.current === identity) onOpen(runId); }}>查看整月计划<ArrowRight/></Button>}
  </section>;
}
