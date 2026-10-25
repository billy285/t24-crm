import { useLocation, useNavigate } from 'react-router-dom';
import { useCallback, useEffect, useRef, useState } from 'react';
import { ArrowRight, CheckCircle2, Pause, RefreshCw, ShieldCheck } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { CrmFormDialogBody, CrmFormDialogContent, CrmFormDialogFooter, CrmFormDialogHeader, Dialog, DialogTitle } from '@/components/ui/dialog';
import { useRole } from '@/lib/role-context';
import { useAutoRefresh } from '@/lib/use-auto-refresh';
import { reconciliationCycles, reconciliationMoney as money, stripeReconciliationApi as api, stripeReconciliationDenied, stripeReconciliationError } from '@/lib/stripe-history-reconciliation';
import { autoPostingCount, autoPostingTime, autoPostingTotalsCount, canEnableAutoPosting, safeAutoPostingTotals, stripeAutoPostingLabels, validAutoPostingSelection, type StripeAutoPostingJob, type StripeAutoPostingOverview, type StripeAutoPostingPolicy, type StripeAutoPostingStatus } from '@/lib/stripe-auto-posting';
import './stripe-auto-posting.css';

type Action = { kind: 'trial'; ids: number[] } | { kind: 'policy'; policy: StripeAutoPostingPolicy; enabled: boolean };
const jobFilters: [StripeAutoPostingStatus | 'all', string][] = [['all', '全部记录'], ['auto_posted', '已自动入账'], ['manual_required', '待你处理'], ['manual_completed', '已人工处理'], ['retry', '待重试'], ['queued', '核验中']];

export default function StripeAutoPosting({ configured, onOpenReview, onChanged, onDenied }: { configured: boolean; onOpenReview: (id: number) => void; onChanged: () => void; onDenied: () => void }) {
  const { role } = useRole(); const isOwner = role === 'super_admin';
  const [data, setData] = useState<StripeAutoPostingOverview | null>(null);
  const [jobs, setJobs] = useState<StripeAutoPostingJob[]>([]); const [jobTotal, setJobTotal] = useState(0);
  const location = useLocation(); const navigate = useNavigate();
  const requestedFilter = new URLSearchParams(location.search).get('stripe_auto_status');
  const filter: StripeAutoPostingStatus | 'all' = jobFilters.some(([key]) => key === requestedFilter) ? requestedFilter as StripeAutoPostingStatus | 'all' : 'all';
  const setFilter = (next: StripeAutoPostingStatus | 'all') => { const params = new URLSearchParams(location.search); params.set('stripe_auto_status', next); navigate(`${location.pathname}?${params}`); };
  const [selected, setSelected] = useState<number[]>([]); const [action, setAction] = useState<Action | null>(null);
  const [loading, setLoading] = useState(false); const [busy, setBusy] = useState(false); const [error, setError] = useState(''); const [message, setMessage] = useState('');
  const [verified, setVerified] = useState(false); const [note, setNote] = useState(''); const [actionError, setActionError] = useState('');
  const [uncertain, setUncertain] = useState(false); const requestId = useRef(0); const inFlight = useRef(false);
  const load = useCallback(async () => {
    if (!isOwner) return;
    const request = ++requestId.current; setLoading(true); setError('');
    try {
      const [overview, result] = await Promise.all([api<StripeAutoPostingOverview>('/auto-posting'), api<{ items: StripeAutoPostingJob[]; total: number }>(`/auto-posting/jobs?status=${filter}`)]);
      if (!overview || !Array.isArray(overview.items) || !overview.counts || !Array.isArray(result.items)) throw new Error('invalid_auto_posting_response');
      if (request === requestId.current) { setData(overview); setJobs(result.items); setJobTotal(autoPostingCount(result.total) ?? result.items.length); setSelected(ids => ids.filter(id => overview.items.some(item => item.binding_id === id && item.eligible && !item.enabled))); setUncertain(false); }
    } catch (failure) {
      if (request === requestId.current) {
        if (stripeReconciliationDenied(failure)) { setData(null); setJobs([]); setSelected([]); setAction(null); onDenied(); }
        setError(stripeReconciliationError(failure, '自动入账设置暂时无法读取，请重新读取后操作。'));
      }
    } finally { if (request === requestId.current) setLoading(false); }
  }, [filter, isOwner, onDenied]);
  useEffect(() => { if (isOwner) void load(); else { setData(null); setJobs([]); setSelected([]); setAction(null); } return () => { requestId.current += 1; }; }, [isOwner, load]);
  useAutoRefresh(load, { enabled: isOwner && !action && !busy, intervalMs: 30000 });
  const openAction = (next: Action) => { if (uncertain || error || busy) return; setVerified(false); setNote(''); setActionError(''); setAction(next); };
  const commit = async () => {
    if (!action || !data || !verified || note.trim().length < 3 || inFlight.current || uncertain) return;
    if (action.kind === 'trial' && !validAutoPostingSelection(action.ids, data.items, data.limit)) return;
    if (action.kind === 'policy' && action.enabled && !canEnableAutoPosting(action.policy, data.enabled_count, data.limit)) return;
    inFlight.current = true; setBusy(true); setActionError(''); setMessage('');
    try {
      if (action.kind === 'trial') {
        const result = await api<{ passed: boolean }>('/auto-posting/trials', 'POST', { binding_ids: action.ids, owner_verified: true, owner_note: note.trim() });
        setMessage(result.passed ? '模拟核验已通过。尚未启用自动入账，请逐项确认启用。' : '模拟已完成，存在待处理项。请查看各服务原因，尚未启用自动入账。');
      } else {
        await api(`/auto-posting/bindings/${action.policy.binding_id}`, 'PATCH', { enabled: action.enabled, revision: action.policy.revision, owner_verified: true, owner_note: note.trim() });
        setMessage(action.enabled ? '本服务自动入账已启用，生效时间以下方服务器记录为准。历史待核对账单继续由你处理。' : '本服务已暂停自动入账，后续收款回到人工核对；已入账记录保留。');
      }
      setAction(null); setSelected([]); setVerified(false); await load(); onChanged();
    } catch (failure) {
      setVerified(false); setUncertain(true);
      if (stripeReconciliationDenied(failure)) { setData(null); setJobs([]); setAction(null); onDenied(); }
      setActionError(stripeReconciliationError(failure, '处理结果尚未确认。请关闭弹窗并重新读取设置，确认结果后再操作。'));
    } finally { inFlight.current = false; setBusy(false); }
  };
  if (!isOwner) return null;
  const totals = safeAutoPostingTotals(data?.totals); const today = safeAutoPostingTotals(data?.today_totals);
  const locked = loading || busy || Boolean(error) || uncertain;
  return <section className="sap-page" aria-label="Stripe 自动入账管理">
    <div className="shr-section-title"><div><h3>正常扣款自动记账，异常交给你</h3><p>按客户服务单独开启。支票仍由你确认；原财务计算、关账与分润规则继续使用。</p></div><Button size="sm" variant="outline" disabled={loading || busy} onClick={() => void load()}><RefreshCw size={13} className={loading ? 'animate-spin' : ''} />重新读取</Button></div>
    {error && <p className="shr-error" role="alert">{error}{data && ' 当前显示上次读取结果，操作已停用。'}</p>}
    {message && <p className="shr-success" role="status"><CheckCircle2 size={15} />{message}</p>}
    {!data ? <div className="shr-panel shr-empty" role="status">{loading ? '正在读取自动入账设置…' : '请重新读取自动入账设置。'}</div> : <>
      <div className="sap-summary"><div><span>自动入账服务</span><strong>{autoPostingCount(data.enabled_count) ?? '—'}<small> / {data.limit} 项试点</small></strong></div><div><span>今日自动入账 · 服务收入</span><strong>{autoPostingTotalsCount(data.today_totals) ?? '—'}<small> 笔</small></strong><p>{today === null ? '服务收入待确认' : today.length ? today.map(item => money(item.amount, item.currency)).join(' · ') : '今日暂无自动入账'}</p></div><div><span>累计自动入账 · 服务收入</span><strong>{autoPostingCount(data.counts.auto_posted) ?? '—'}<small> 笔</small></strong><p>{totals === null ? '服务收入待确认' : totals.length ? totals.map(item => money(item.amount, item.currency)).join(' · ') : '尚无自动入账'}</p></div><button type="button" onClick={() => setFilter('manual_required')}><span>需你处理</span><strong>{autoPostingCount(data.counts.manual_required) ?? '—'}<small> 笔</small></strong><p>归属、金额、重复或原规则未通过</p></button></div>
      <div className="sap-guide"><ShieldCheck size={16} /><div><strong>先选 3–5 项进行模拟核验，再逐项开启</strong><p>模拟只检查证据，不新增收入。开启后仅处理生效后新创建的账单；已有待核账单和历史账单不自动补记。</p></div></div>
      <div className="sap-policy-toolbar"><span>已选 {selected.length} 项用于模拟</span><Button size="sm" disabled={locked || !configured || !validAutoPostingSelection(selected, data.items, data.limit)} onClick={() => openAction({ kind: 'trial', ids: [...selected] })}>模拟核验所选服务</Button></div>
      <div className="sap-policies">{data.items.length ? data.items.map(policy => <article key={policy.binding_id} className="shr-panel sap-policy"><div className="sap-policy-main"><label className="sap-select"><input type="checkbox" aria-label={`选择模拟 ${policy.customer_name} ${policy.package_name}`} checked={selected.includes(policy.binding_id)} disabled={locked || !configured || !policy.eligible || policy.enabled || (!selected.includes(policy.binding_id) && selected.length >= Math.min(data.limit, 5))} onChange={event => setSelected(ids => event.target.checked ? [...ids, policy.binding_id] : ids.filter(id => id !== policy.binding_id))} /><span><strong>{policy.customer_name}</strong><small>{policy.package_name} · {money(policy.amount, policy.currency)} · {reconciliationCycles[policy.billing_cycle] || policy.billing_cycle}</small></span></label><span className={`shr-status ${policy.enabled ? 'shr-status-done' : 'shr-status-muted'}`}>{policy.enabled ? '自动入账已开启' : policy.effective_from ? '已暂停 · 人工核对' : '人工核对'}</span></div>
        <div className="sap-policy-meta"><span>{policy.trial ? `模拟${policy.trial.passed ? '通过' : '待处理'} · ${policy.trial.invoice_count} 笔凭据 · ${autoPostingTime(policy.trial.checked_at)}` : '尚未模拟核验'}</span><span>{policy.effective_from ? `${policy.enabled ? '自动记账生效' : '上次生效'} ${autoPostingTime(policy.effective_from)}（北京时间）` : '未设置自动记账生效时间'}</span></div>
        {(policy.eligibility_reasons?.length > 0 || policy.trial?.reasons?.length > 0) && <p className="sap-policy-reasons">{[...new Set([...(policy.eligibility_reasons || []), ...(policy.trial?.reasons || [])])].join('；')}</p>}
        <details className="sap-evidence"><summary>查看订阅与处理依据</summary><p>{policy.stripe_subscription_id}</p>{policy.latest_job && <p>{stripeAutoPostingLabels[policy.latest_job.status] || '状态待确认'}{policy.latest_job.reason && ` · ${policy.latest_job.reason}`}{policy.latest_job.payment_id && ` · 收款 #${policy.latest_job.payment_id}`}</p>}</details>
        <div className="shr-actions">{policy.latest_job?.review_id && <Button size="sm" variant="ghost" onClick={() => onOpenReview(policy.latest_job!.review_id!)}>查看最近账单 <ArrowRight size={13} /></Button>}{policy.enabled ? <Button size="sm" variant="outline" disabled={locked} onClick={() => openAction({ kind: 'policy', policy, enabled: false })}><Pause size={13} />暂停自动入账</Button> : <Button size="sm" variant="outline" disabled={locked || !configured || !canEnableAutoPosting(policy, data.enabled_count, data.limit)} onClick={() => openAction({ kind: 'policy', policy, enabled: true })}>确认启用自动入账</Button>}</div>
      </article>) : <div className="shr-panel shr-empty">先关联客户服务，再选择试点。</div>}</div>
      <div className="shr-section-title"><div><h3>系统处理记录</h3><p>已入账显示原记账服务收入（税前），未入账显示待核服务基价。待重试和核验中的记录暂不计入收入。</p></div></div><nav className="shr-filters" aria-label="自动入账处理状态">{jobFilters.map(([key, label]) => <button type="button" key={key} aria-pressed={filter === key} onClick={() => setFilter(key)}>{label}{key !== 'all' && <span>{autoPostingCount(data.counts[key]) ?? '—'}</span>}</button>)}</nav>
      <div className="sap-jobs">{jobs.length ? jobs.map(job => <button type="button" key={job.id} className="shr-panel sap-job" disabled={!job.review_id} onClick={() => onOpenReview(job.review_id)}><span><strong>{job.customer_name}</strong><small>{job.package_name} · {job.reason || stripeAutoPostingLabels[job.status]}</small><small>{job.payment_id ? `收款 #${job.payment_id} · ` : ''}{autoPostingTime(job.last_attempt_at || job.created_at)}</small></span><span><strong>{money(job.amount, job.currency)}</strong><small className={`shr-status ${job.status === 'auto_posted' ? 'shr-status-done' : job.status === 'manual_required' ? 'shr-status-exception' : ''}`}>{stripeAutoPostingLabels[job.status] || '状态待确认'}</small><small className="shr-link">查看依据 <ArrowRight size={12} /></small></span></button>) : <div className="shr-panel shr-empty">当前分类暂无处理记录。</div>}</div>{jobTotal > jobs.length && <p className="shr-note">当前展示最近 {jobs.length} 条，共 {jobTotal} 条；完整已入账明细可在收款核对页查看。</p>}
    </>}
    <Dialog open={Boolean(action)} onOpenChange={open => { if (!open && !busy) setAction(null); }}><CrmFormDialogContent className="financial-workspace-form shr-form-dialog shr-dialog sap-confirm" aria-describedby={undefined}><CrmFormDialogHeader><DialogTitle>{action?.kind === 'trial' ? '模拟核验所选服务' : action?.enabled ? '启用本服务自动入账' : '暂停本服务自动入账'}</DialogTitle></CrmFormDialogHeader><CrmFormDialogBody>
      {action?.kind === 'trial' ? <p className="shr-note">本次核验 {action.ids.length} 项服务的当前订阅与历史收款证据，不新增正式收款，不自动开启设置。</p> : action && <><div className="shr-selected"><strong>{action.policy.customer_name} · {action.policy.package_name}</strong><p>{money(action.policy.amount, action.policy.currency)} · {reconciliationCycles[action.policy.billing_cycle] || action.policy.billing_cycle}</p></div><p className="shr-note">{action.enabled ? '仅生效后新创建且正常实扣的账单可按原规则自动记账。历史待核对账单不补记；原关账与分润限制继续生效，异常交给你处理。' : '暂停后，尚未入账及后续账单由你人工核对。已入账记录不会删除或冲销。'}</p></>}
      <label>操作说明<Textarea aria-label="自动入账操作说明" value={note} maxLength={1000} disabled={busy || uncertain} onChange={event => { setNote(event.target.value); setVerified(false); }} placeholder="记录本次核验、启用或暂停的依据" /></label><label className="shr-check shr-owner-confirm"><input type="checkbox" checked={verified} disabled={busy || uncertain} onChange={event => setVerified(event.target.checked)} /><span>{action?.kind === 'trial' ? '我确认所选客户服务归属正确，同意只做模拟核验，不新增收入。' : action?.enabled ? '我已核对模拟结果、服务和原账，确认仅对生效后的新账单开启自动入账。' : '我确认暂停本服务自动入账，后续由我人工核对。'}</span></label>
      {actionError && <p className="shr-error" role="alert">{actionError}</p>}</CrmFormDialogBody><CrmFormDialogFooter className="shr-actions"><Button variant="outline" disabled={busy} onClick={() => setAction(null)}>暂不操作</Button><Button disabled={busy || uncertain || !verified || note.trim().length < 3} onClick={() => void commit()}>{busy ? '正在核验保存…' : action?.kind === 'trial' ? '确认开始模拟' : action?.enabled ? '确认启用' : '确认暂停'}</Button></CrmFormDialogFooter></CrmFormDialogContent></Dialog>
  </section>;
}
