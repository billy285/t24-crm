import { useCallback, useEffect, useRef, useState } from 'react';
import { ArrowRight, ClipboardCheck, RefreshCw } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useRole } from '@/lib/role-context';
import { BUSINESS_DATA_REFRESH_EVENT } from '@/lib/data-refresh';
import { mediaOperationsApi, type MediaList, type MediaSummary } from '@/lib/media-operations-api';

/** A separately scoped count: old delivery totals never imply no content work. */
export default function MediaOperationsEntry({ compact = false }: { compact?: boolean }) {
  const { employee, systemRole, canAccess } = useRole();
  const navigate = useNavigate();
  const identity = `${employee?.id || ''}:${systemRole || ''}`;
  const allowed = ['super_admin', 'admin', 'ops'].includes(systemRole) && canAccess('/media-ops');
  const identityRef = useRef(identity); identityRef.current = identity;
  const sequence = useRef(0);
  const [result, setResult] = useState<{ identity: string; summary: MediaSummary } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const refresh = useCallback(async () => {
    const request = ++sequence.current;
    if (!allowed) { setResult(null); setLoading(false); return; }
    setLoading(true); setError(false);
    try {
      const data = await mediaOperationsApi<MediaList>('?limit=1');
      const values = ['draft', 'in_review', 'ready', 'completed', 'blocked', 'overdue'] as const;
      if (!data?.summary || !values.every(key => Number.isSafeInteger(data.summary[key]) && data.summary[key] >= 0)) throw new Error('Incomplete summary');
      if (sequence.current === request && identityRef.current === identity) setResult({ identity, summary: data.summary });
    } catch {
      if (sequence.current === request && identityRef.current === identity) { setResult(null); setError(true); }
    } finally {
      if (sequence.current === request && identityRef.current === identity) setLoading(false);
    }
  }, [allowed, identity]);
  useEffect(() => {
    setResult(null); void refresh();
    const listener = () => void refresh();
    window.addEventListener(BUSINESS_DATA_REFRESH_EVENT, listener);
    return () => { sequence.current++; window.removeEventListener(BUSINESS_DATA_REFRESH_EVENT, listener); };
  }, [refresh]);
  if (!allowed) return null;
  const summary = result?.identity === identity ? result.summary : null;
  const pending = summary ? summary.draft + summary.in_review + summary.ready + summary.blocked : null;
  const waiting = loading || (!error && !summary);
  return <section aria-label="代运营待办" className={`mb-4 flex min-w-0 flex-wrap items-center gap-3 rounded-xl border border-blue-100 bg-blue-50/60 ${compact ? 'p-4' : 'px-4 py-3'}`}>
    <ClipboardCheck className="h-5 w-5 shrink-0 text-blue-600" aria-hidden="true" />
    <div className="min-w-0 flex-1"><h2 className="text-sm font-semibold text-slate-800">{waiting ? '正在读取代运营待办…' : error ? '代运营待办待更新' : pending ? `${pending} 项代运营任务待处理` : '代运营暂无待办'}</h2>
      <p className="mt-1 text-xs leading-relaxed text-slate-500">{summary ? `待准备 ${summary.draft} · 待审核 ${summary.in_review} · 待发布 ${summary.ready} · 异常 ${summary.blocked}` : '内容准备、审核与发布任务在这里继续。'}</p></div>
    {error && <button type="button" onClick={() => void refresh()} aria-label="重新读取代运营待办" className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg border border-blue-100 bg-white text-blue-600"><RefreshCw className="h-4 w-4" aria-hidden="true" /></button>}
    <button type="button" onClick={() => navigate('/media-ops')} className="flex min-h-11 shrink-0 items-center gap-1 rounded-lg bg-white px-3 text-xs font-semibold text-blue-700 shadow-sm">打开代运营<ArrowRight className="h-4 w-4" aria-hidden="true" /></button>
  </section>;
}
