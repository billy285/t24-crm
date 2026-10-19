import { useCallback, useEffect, useId, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { ArrowRight, RefreshCw } from 'lucide-react';
import { useRole } from '@/lib/role-context';
import { useAutoRefresh } from '@/lib/use-auto-refresh';
import { buildReturnLink } from '@/lib/navigation-state';
import { reconciliationTime, stripeReconciliationApi, stripeReconciliationDenied, stripeReconciliationError } from '@/lib/stripe-history-reconciliation';
import { pendingStripeReminders, reminderCount, stripeDailyScanState, stripeReminderHref, type StripeHistoryReminders as ReminderData } from '@/lib/stripe-history-reminders';
import './stripe-history-reminders.css';

export default function StripeHistoryReminders({ compact = false }: { compact?: boolean }) {
  const { role } = useRole();
  const isOwner = role === 'super_admin';
  const navigate = useNavigate(); const location = useLocation();
  const [data, setData] = useState<ReminderData | null>(null);
  const [loading, setLoading] = useState(false); const [error, setError] = useState('');
  const [showExceptions, setShowExceptions] = useState(false); const exceptionId = useId();
  const sequence = useRef(0);
  const load = useCallback(async () => {
    if (!isOwner) return;
    const request = ++sequence.current; setLoading(true); setError('');
    try {
      const result = await stripeReconciliationApi<ReminderData>('/reminders');
      if (!result?.daily_scan || !result?.counts || !Array.isArray(result.items)) throw new Error('invalid_reminder_response');
      if (request === sequence.current) setData(result);
    } catch (failure) {
      if (request === sequence.current) {
        if (stripeReconciliationDenied(failure)) { setData(null); setShowExceptions(false); }
        setError(stripeReconciliationError(failure, 'Stripe 待核提醒暂时无法读取，请重试。'));
      }
    } finally { if (request === sequence.current) setLoading(false); }
  }, [isOwner]);
  useEffect(() => {
    if (isOwner) void load(); else { setData(null); setError(''); setShowExceptions(false); }
    return () => { sequence.current += 1; };
  }, [isOwner, load]);
  useAutoRefresh(load, { enabled: isOwner, intervalMs: 30000 });
  if (!isOwner) return null;

  const open = (href: string) => navigate(buildReturnLink(href, `${location.pathname}${location.search}`));
  const pending = pendingStripeReminders(data?.counts);
  const exceptions = reminderCount(data?.counts.exception);
  const retries = reminderCount(data?.daily_scan.retry_bindings);
  const state = stripeDailyScanState(data?.daily_scan);
  const scan = data?.daily_scan;
  const discovered = reminderCount(scan?.last_discovered_reviews);
  const countText = (value: number | null) => value === null ? '—' : value;

  return <section className={`shr-reminders${compact ? ' shr-reminders-compact' : ''}`} aria-label={compact ? 'Stripe 待核提醒' : 'Stripe 每日补查'}>
    <div className="shr-reminders-top">
      <div className="shr-reminders-counts">
        <button type="button" onClick={() => open('/finance?tab=stripe_reconciliation&stripe_view=reviews&stripe_status=unverified')}><span>Stripe 待核收款</span><strong>{countText(pending)}</strong></button>
        <button type="button" className={exceptions ? 'shr-reminders-attention' : ''} disabled={exceptions === null} aria-expanded={showExceptions} aria-controls={exceptionId} onClick={() => setShowExceptions(value => !value)}><span>异常</span><strong>{countText(exceptions)}</strong></button>
        {retries !== null && retries > 0 && <span className="shr-reminders-retry">补查待重试 {retries}</span>}
      </div>
      <button type="button" className="shr-reminders-refresh" aria-label="刷新 Stripe 待核提醒" disabled={loading} onClick={() => void load()}><RefreshCw size={14} className={loading ? 'animate-spin' : ''} /><span>刷新</span></button>
    </div>
    {error ? <p className="shr-reminders-error" role="status">{error}{data && ' 当前为上次读取结果，请重新读取后再判断。'}</p> : loading && !data ? <p role="status" className="shr-reminders-meta">正在读取提醒与补查结果…</p> : <div className="shr-reminders-meta"><span className={`shr-reminders-state shr-reminders-${state.tone}`}>{state.label}</span><span>每日 09:00（北京时间）补查</span>{scan?.last_run_at && <span>最近运行 {reconciliationTime(scan.last_run_at)}</span>}{scan && <span>{discovered === null ? '新账单数待确认' : `发现新账单 ${discovered} 笔`}</span>}</div>}
    {showExceptions && data && <div id={exceptionId} className="shr-reminders-exceptions" role="region" aria-label="Stripe 异常清单"><p>异常账单直接逐笔核对；已入账凭据变化需检查原账的调整流程。</p>{Array.isArray(data.exception_items) ? data.exception_items.length ? data.exception_items.map(item => { const href = stripeReminderHref(item.href); return <button type="button" className="shr-reminders-item" key={item.id} disabled={!href} onClick={() => href && open(href)}><span><strong>{item.customer_name || '客户待确认'}</strong><small>{item.package_name || '服务待确认'} · {item.title || '待老板核对'}</small></span><ArrowRight size={14} /></button>; }) : <p>{exceptions === 0 ? '当前已读取记录暂无异常。' : '异常清单待确认，请刷新后再核对。'}</p> : <p>异常清单待确认，请刷新后再核对。</p>}{data.exception_has_more && <p>先处理最近 20 条异常，其余事项仍保留。</p>}</div>}
    {!compact && data && <details className="shr-reminders-details"><summary>查看补查进度与待核事项 <ArrowRight size={13} /></summary><div className="shr-reminders-details-body"><p>已补查 {countText(reminderCount(scan?.covered_bindings))}/{countText(reminderCount(scan?.active_bindings))} 个已关联服务{scan?.next_scheduled_at && ` · 下次 ${reconciliationTime(scan.next_scheduled_at)}`}</p>{scan?.covered_through ? <p>全部已关联服务共同覆盖至 {reconciliationTime(scan.covered_through)}（北京时间，按账单创建时间）</p> : <p>尚未确认全部已关联服务的完整补查范围。</p>}<p>补查只生成待核对账单；实际到账、税费和是否入账仍由你逐笔核对。</p>{data.items.slice(0, 3).map(item => { const href = stripeReminderHref(item.href); return <button type="button" className="shr-reminders-item" key={item.id} disabled={!href} onClick={() => href && open(href)}><span><strong>{item.customer_name || '客户待确认'}</strong><small>{item.package_name || '服务待确认'} · {item.title || '待老板核对'}</small></span><ArrowRight size={14} /></button>; })}</div></details>}
  </section>;
}
