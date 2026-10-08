import { useEffect, useState } from 'react';
import { History } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { invokeWithAuth } from '@/lib/tokenStore';

type Item = { id: number; outcome_label: string; notes?: string; called_at: string; sales_employee_name?: string };
type Props = { leadId: number; lastContactAt?: string; onOpenAll: () => void; formatDate: (value?: string) => string; compact?: boolean };

export default function SalesRecentHistory({ leadId, lastContactAt, onOpenAll, formatDate, compact = false }: Props) {
  const [items, setItems] = useState<Item[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    let cancelled = false;
    setItems([]); setLoading(true); setError(false);
    void invokeWithAuth({ url: `/api/v1/sales-leads/${leadId}/call-history`, method: 'GET' })
      .then(response => { if (!cancelled) setItems(Array.isArray(response.data) ? response.data : []); })
      .catch(() => { if (!cancelled) setError(true); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [leadId, lastContactAt, retry]);

  if (compact) return <div className="sw-last-contact" aria-label="最近联系">
    <History size={14} aria-hidden="true" />
    {loading ? <span>正在读取…</span> : error ? <Button variant="ghost" size="sm" onClick={() => setRetry(value => value + 1)}>记录读取失败，重试</Button> : <span title={items[0]?.notes || undefined}>{items[0] ? `上次：${items[0].notes || items[0].outcome_label}` : '尚无联系记录'}</span>}
    <Button variant="ghost" size="sm" onClick={onOpenAll}>历史</Button>
  </div>;

  return <section className="sc-panel sc-history" aria-label="最近联系">
    <div className="sc-panel-heading"><h3><History size={15} />最近联系</h3><Button variant="ghost" size="sm" onClick={onOpenAll}>全部</Button></div>
    {loading ? <p className="sc-muted-state">正在读取联系记录…</p> : error ? <div className="sc-muted-state" role="alert">联系记录暂时无法读取。<Button variant="ghost" size="sm" onClick={() => setRetry(value => value + 1)}>重试</Button></div> : !items.length ? <p className="sc-muted-state">尚无联系记录。首次沟通后会显示在这里。</p> : <ol className="sc-history-list">{items.slice(0, 3).map(item => <li key={item.id}><div className="sc-history-meta"><time>{formatDate(item.called_at)}</time><span>{item.sales_employee_name || '未记录'}</span></div><p>{item.notes || '本次未填写备注'}</p><span className="sc-history-outcome">{item.outcome_label}</span></li>)}</ol>}
  </section>;
}
