import { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { Bell } from 'lucide-react';
import { invokeWithAuth } from '@/lib/tokenStore';
import { useAutoRefresh } from '@/lib/use-auto-refresh';

type DueMonth = { month: string; ready_count: number; review_count: number };

export default function CommissionStatementReminder() {
  const [months, setMonths] = useState<DueMonth[]>([]);
  const [failed, setFailed] = useState(false);
  const sequence = useRef(0);
  const load = useCallback(async () => {
    const request = ++sequence.current;
    try {
      const { data } = await invokeWithAuth({ url: '/api/v1/commissions/statements/reminders', method: 'GET' });
      if (!Array.isArray(data?.items)) throw new Error("月结提醒未完整返回");
      if (sequence.current === request) {
        setMonths(data.items);
        setFailed(false);
      }
    } catch {
      if (sequence.current === request) setFailed(true);
    }
  }, []);
  useEffect(() => {
    void load();
    return () => { sequence.current++; };
  }, [load]);
  useAutoRefresh(load, { intervalMs: 60000 });

  if (!months.length && !failed) return null;
  return <section aria-label="渠道月结提醒" className="t24-card space-y-2 rounded-xl border p-4">
    <h2 className="flex items-center gap-2 text-base font-semibold"><Bell size={17} />渠道月结提醒</h2>
    {failed && <p role="status" className="text-sm">月结提醒暂时无法更新。<button type="button" className="ml-2 underline" onClick={() => void load()}>重试</button></p>}
    {months.map(item => <Link key={item.month} to={'/commissions?view=statements&month=' + item.month}
      className="flex min-h-11 flex-wrap items-center justify-between gap-2 rounded-md px-2 py-1 text-sm">
      <strong>{item.month} 渠道结算</strong>
      <span>{[item.ready_count > 0 && `${item.ready_count} 张待结算`, item.review_count > 0 && `${item.review_count} 张待核对`].filter(Boolean).join(' · ')} ›</span>
    </Link>)}
  </section>;
}
