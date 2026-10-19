import { useCallback, useEffect, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { ArrowLeft, ArrowRight, CheckCircle2, ChevronRight, ClipboardCheck, RefreshCw, ShieldCheck } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { buildReturnLink, getSafeInternalPath } from '@/lib/navigation-state';
import { useRole } from '@/lib/role-context';
import { useAutoRefresh } from '@/lib/use-auto-refresh';
import StripeHistoryReminders from '@/components/StripeHistoryReminders';
import { followThroughApi, followThroughAccessDenied, followThroughDate, kickoffLastServiceDate, followThroughError, followThroughHref, type FollowThroughCoverage, type KickoffDetail, type KickoffDraft, type KickoffItem, type KickoffList, type OwnerExceptionOverview, type RenewalObservations } from '@/lib/service-follow-through';
import './service-follow-through.css';

const kickoffLabels: Record<string, string> = { missing: '待建清单', in_progress: '进行中', overdue: '已逾期', completed: '已完成' };
const itemLabels: Record<string, string> = { pending: '待完成', blocked: '有卡点', completed: '已完成' };
const cycleLabels: Record<string, string> = { monthly: '月付', quarterly: '季付', annual: '年付', semi_annual: '半年付', one_time: '一次性' };
const ownerFilters = [ ['pending_receipt', '待核款'], ['pending_access', '待授权'], ['pending_operations', '待接收'], ['kickoff_missing', '待建清单'], ['kickoff_blocked', '开工受阻'], ['kickoff_overdue', '开工逾期'], ['renewal_attention', '续费待核对'], ['renewal_unconnected', '续费待连接'] ];
const todayKey = () => new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date());

function Coverage({ value }: { value: FollowThroughCoverage }) {
  return <div className="sf-coverage"><ShieldCheck size={15} aria-hidden="true" /><div><strong>{value.webhook_configured === true ? '仅展示已关联的通知与登记日期提醒' : 'Stripe 通知尚未配置，续费状态待确认'}</strong><p>{value.note || value.scope || '尚未覆盖全部 Stripe 历史订阅；未收到异常通知不等于扣款正常。'}</p><span>已关联 {value.linked_subscriptions ?? 0} · 待连接 {value.unconnected_subscriptions ?? 0} · 最近通知 {followThroughDate(value.latest_event_at)}</span></div></div>;
}

export function OwnerExceptions() {
  const { role } = useRole();
  const navigate = useNavigate();
  const location = useLocation();
  const [data, setData] = useState<OwnerExceptionOverview | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [expanded, setExpanded] = useState(false);
  const sequence = useRef(0);
  const load = useCallback(async () => {
    const request = ++sequence.current;
    setLoading(true); setError('');
    try { const result = await followThroughApi<OwnerExceptionOverview>('/owner-overview'); if (sequence.current === request) setData(result); }
    catch (failure) { if (sequence.current === request) { if (followThroughAccessDenied(failure)) setData(null); setError(followThroughError(failure, '异常总览暂时无法读取，请重试。')); } }
    finally { if (sequence.current === request) setLoading(false); }
  }, []);
  useEffect(() => { if (role === 'super_admin') void load(); return () => { sequence.current += 1; }; }, [role, load]);
  useAutoRefresh(load, { enabled: role === 'super_admin', intervalMs: 30000 });
  if (role !== 'super_admin') return null;
  const navigateTo = (href?: string) => { const safe = followThroughHref(href); if (safe) navigate(buildReturnLink(safe, `${location.pathname}${location.search}`)); };
  const items = data?.items || [];
  return <section className="sf-owner sf-panel" aria-label="老板异常总览">
    <div className="sf-heading"><div><p className="sf-kicker">销售 → 收款 → 运营 → 续费</p><h2>老板异常总览 <span>{data ? data.counts.total_actions ?? items.length : '—'}</span></h2><p>先处理需要你推动的事情</p></div><Button size="sm" variant="outline" onClick={() => void load()} disabled={loading} aria-label="刷新老板异常总览"><RefreshCw className={loading ? 'animate-spin' : ''} size={14} />刷新</Button></div>
    <StripeHistoryReminders compact />
    {error && <div className="sf-error" role="alert">{error}{data && ' 以下为上次读取结果，请刷新后再判断。'}</div>}
    {!data && loading && <p role="status" className="sf-empty">正在读取异常事项…</p>}
    {data && <>
      <div className="sf-owner-counts">{ownerFilters.map(([key, label]) => <button key={key} type="button" onClick={() => navigateTo(key.startsWith('renewal') ? `/operations-workbench?view=renewals&status=${key === 'renewal_unconnected' ? 'unconnected' : 'attention'}` : key.startsWith('kickoff') ? `/operations-workbench?view=kickoffs&status=${key === 'kickoff_missing' ? 'missing' : key === 'kickoff_blocked' ? 'blocked' : 'overdue'}` : `/sales-leads?view=handoffs&status=${key === 'pending_receipt' ? 'pending_payment' : key}`)}><span>{label}</span><strong>{data.counts[key] ?? 0}</strong></button>)}</div>
      {items.length > 0 ? <div className="sf-exception-list">{(expanded ? items : items.slice(0, 3)).map((item, index) => <button className={`sf-exception sf-tone-${item.severity || 'medium'}`} type="button" key={item.id} onClick={() => navigateTo(item.href)} disabled={!followThroughHref(item.href)}><span className="sf-rank">{index === 0 ? '先处理' : String(index + 1).padStart(2, '0')}</span><span className="sf-exception-copy"><strong>{item.title}</strong><small>{item.business_name || '待核对事项'}{Number(item.waiting_days) > 0 && ` · 已等待 ${item.waiting_days} 天`}</small></span><ChevronRight size={16} /></button>)}</div> : <p className="sf-empty"><CheckCircle2 size={17} />当前已覆盖记录暂无待处理事项，通知覆盖仍需单独核对。</p>}
      <div className="sf-footer"><span>更新 {followThroughDate(data.generated_at)}（北京时间）</span>{items.length > 3 && <button type="button" onClick={() => setExpanded(!expanded)}>{expanded ? '收起事项' : `查看全部 ${items.length} 项`}</button>}<button type="button" onClick={() => navigateTo('/operations-workbench?view=renewals')}>查看续费覆盖 <ArrowRight size={13} /></button></div>
    </>}
  </section>;
}

export function ServiceFollowThroughNav({ view, onChange }: { view: string; onChange: (view: string) => void }) {
  const { role } = useRole();
  return <nav className="sf-nav" aria-label="运营工作台视图"><button type="button" aria-current={view === 'today' ? 'page' : undefined} onClick={() => onChange('today')}>今日事项</button><button type="button" aria-current={view === 'kickoffs' ? 'page' : undefined} onClick={() => onChange('kickoffs')}>开工清单</button>{role === 'super_admin' && <button type="button" aria-current={view === 'renewals' ? 'page' : undefined} onClick={() => onChange('renewals')}>续费提醒<span>仅老板</span></button>}</nav>;
}

export function ServiceFollowThroughWorkspace({ view }: { view: 'kickoffs' | 'renewals' }) {
  const { role } = useRole();
  const location = useLocation(); const navigate = useNavigate();
  const query = new URLSearchParams(location.search);
  const allowed = view === 'kickoffs' ? ['all', 'missing', 'in_progress', 'blocked', 'overdue', 'completed'] : ['all', 'attention', 'unconnected', 'upcoming'];
  const status = allowed.includes(query.get('status') || '') ? query.get('status')! : 'all';
  const handoffId = /^[1-9]\d*$/.test(query.get('handoff') || '') ? Number(query.get('handoff')) : null;
  const [kickoffs, setKickoffs] = useState<KickoffList | null>(null);
  const [renewals, setRenewals] = useState<RenewalObservations | null>(null);
  const [loading, setLoading] = useState(false); const [error, setError] = useState('');
  const sequence = useRef(0);
  const forbidden = view === 'renewals' && role !== 'super_admin';
  const load = useCallback(async () => {
    if (forbidden) return;
    const request = ++sequence.current; setLoading(true); setError('');
    try {
      if (view === 'kickoffs') { const result = await followThroughApi<KickoffList>(`/kickoffs?status=${status}`); if (request === sequence.current) setKickoffs(result); }
      else { const result = await followThroughApi<RenewalObservations>(`/renewals?status=${status}`); if (request === sequence.current) setRenewals(result); }
    } catch (failure) { if (request === sequence.current) { if (followThroughAccessDenied(failure)) { setKickoffs(null); setRenewals(null); } setError(followThroughError(failure, '记录暂时无法读取，请重试。')); } }
    finally { if (request === sequence.current) setLoading(false); }
  }, [forbidden, status, view]);
  useEffect(() => { setKickoffs(null); setRenewals(null); void load(); return () => { sequence.current += 1; }; }, [load]);
  useAutoRefresh(load, { enabled: view === 'renewals' && !forbidden, intervalMs: 30000 });
  const updateQuery = (key: string, value?: string) => { const next = new URLSearchParams(location.search); if (value) next.set(key, value); else next.delete(key); navigate(`${location.pathname}?${next}`); };
  const detailHref = (id: number) => { const next = new URLSearchParams(location.search); next.set('handoff', String(id)); return `${location.pathname}?${next}`; };
  const returnTo = getSafeInternalPath(query.get('returnTo'));
  const data = view === 'kickoffs' ? kickoffs : renewals;
  const filters = view === 'kickoffs' ? [['all', '全部'], ['missing', '待建清单'], ['in_progress', '进行中'], ['blocked', '有卡点'], ['overdue', '已逾期'], ['completed', '已完成']] : [['all', '全部'], ['attention', '待核对'], ['unconnected', '待连接'], ['upcoming', '近期到期']];
  if (forbidden) return <section className="sf-panel sf-empty" role="alert">续费付款信息仅老板可见。<Button variant="outline" onClick={() => updateQuery('view', 'kickoffs')}>查看开工清单</Button></section>;
  return <section className="sf-workspace" aria-label={view === 'kickoffs' ? '运营开工清单' : '续费异常提醒'}>
    {returnTo && returnTo !== location.pathname + location.search && <button type="button" className="sf-return" onClick={() => navigate(returnTo)}><ArrowLeft size={15} />返回来源页面</button>}
    <div className="sf-heading"><div><p className="sf-kicker">{view === 'kickoffs' ? '接收以后，每一步有记录' : '仅老板 · 只读观察'}</p><h2>{view === 'kickoffs' ? '运营开工清单' : '续费异常提醒'}</h2><p>{view === 'kickoffs' ? '按已登记套餐推进资料、授权与首次交付。' : '通知供你核对；不会自动记账、修改订阅或改变服务。'}</p></div><Button variant="outline" size="sm" onClick={() => void load()} disabled={loading}><RefreshCw size={14} className={loading ? 'animate-spin' : ''} />刷新记录</Button></div>
    {view === 'renewals' && renewals && <Coverage value={renewals.coverage} />}
    <nav className="sf-filters" aria-label={view === 'kickoffs' ? '开工清单筛选' : '续费提醒筛选'}>{filters.map(([key, label]) => <button key={key} type="button" aria-pressed={status === key} onClick={() => { const next = new URLSearchParams(location.search); next.set('status', key); next.delete('handoff'); navigate(`${location.pathname}?${next}`); }}>{label}<span>{data?.counts[key] ?? '—'}</span></button>)}</nav>
    {error && <div className="sf-error" role="alert">{error}{data && ' 当前显示上次读取结果，请重新读取后再判断。'}</div>}
    {loading && !data && <p className="sf-empty" role="status">正在读取记录…</p>}
    {view === 'kickoffs' && kickoffs && <>
      {handoffId ? <KickoffRecord handoffId={handoffId} onBack={() => updateQuery('handoff')} onSaved={() => void load()} /> : kickoffs.items.length === 0 ? <div className="sf-panel sf-empty"><ClipboardCheck size={24} /><strong>当前分类暂无开工清单</strong><p>先登记成交，由老板授权客户资料，再由指定运营确认接收。具备交付编辑权限后可建立清单。</p></div> : <div className="sf-records">{kickoffs.items.map(item => <button key={item.handoff_id} type="button" className="sf-record sf-panel" onClick={() => navigate(detailHref(item.handoff_id))}><span className="sf-record-copy"><strong>{item.business_name || `客户 #${item.customer_id}`}</strong><small>{item.package_name || '已登记套餐'} · {item.operations_owner_name || '待指定运营'}</small><small>服务 {item.service_start_date || '待确认'} 至 {item.service_end_date || '待确认'}</small></span><span className="sf-record-end"><span className={`sf-status sf-status-${item.status}`}>{kickoffLabels[item.status] || '待确认'}</span><small>{item.initialized ? `${item.completed_count}/${item.total_count} 项完成${item.blocked_count ? ` · ${item.blocked_count} 项受阻` : ''}` : '尚未建立'}{item.first_delivery_due_date && ` · 首交 ${item.first_delivery_due_date}`}</small><span className="sf-link">查看清单 <ChevronRight size={14} /></span></span></button>)}</div>}
    </>}
    {view === 'renewals' && renewals && <div className="sf-records">{renewals.items.length === 0 ? <div className="sf-panel sf-empty"><strong>当前分类暂无续费记录</strong><p>这不代表全部订阅正常。未关联的历史订阅和通知未覆盖期间仍需人工核对。</p></div> : renewals.items.map(item => <article className="sf-panel sf-renewal" key={item.id}><div className="sf-heading"><div><h3>{item.business_name || `客户 #${item.customer_id}`}</h3><p>{item.package_name || '已登记套餐'} · {cycleLabels[item.billing_cycle || ''] || '周期待确认'}</p></div><span className={`sf-status sf-status-${item.status}`}>{item.status_label || '状态待确认'}</span></div><div className="sf-renewal-meta"><span>续费参考日期 <strong>{item.due_date || '待确认'}</strong></span><span>{item.connection_status === 'linked' ? '已关联通知' : '尚未关联通知，仅依据登记日期提醒'} · 最近通知 {followThroughDate(item.latest_event_at)}</span></div>{item.signals?.length > 0 && <details className="sf-disclosure"><summary>查看通知依据 · {item.signals.length} 条</summary><ol>{item.signals.map((signal, index) => <li key={`${signal.invoice_id || signal.subscription_id || signal.kind}-${index}`}><div><strong>{signal.label || signal.status || signal.kind}</strong><time>{followThroughDate(signal.event_at)}</time></div>{typeof signal.amount === 'number' && <p>{signal.currency || 'USD'} {signal.amount.toFixed(2)} · 通知金额，待老板核对</p>}{signal.invoice_id && <p>账单 {signal.invoice_id}</p>}{signal.subscription_id && <p>订阅 {signal.subscription_id}</p>}</li>)}</ol></details>}{followThroughHref(item.href) && <Button variant="outline" size="sm" onClick={() => navigate(buildReturnLink(followThroughHref(item.href), `${location.pathname}${location.search}`))}>{item.handoff_id ? '查看成交与核款' : '查看客户续费'} <ArrowRight size={14} /></Button>}</article>)}</div>}
  </section>;
}

function KickoffRecord({ handoffId, onBack, onSaved }: { handoffId: number; onBack: () => void; onSaved: () => void }) {
  const [data, setData] = useState<KickoffDetail | null>(null); const [loading, setLoading] = useState(false); const [error, setError] = useState(''); const [saving, setSaving] = useState(false);
  const [firstDate, setFirstDate] = useState(''); const [editing, setEditing] = useState<KickoffItem | null>(null); const [drafts, setDrafts] = useState<Record<string, KickoffDraft>>({}); const [editError, setEditError] = useState('');
  const sequence = useRef(0); const inFlight = useRef(false);
  const load = useCallback(async () => { const request = ++sequence.current; setLoading(true); setError(''); try { const result = await followThroughApi<{ kickoff: KickoffDetail }>(`/kickoffs/${handoffId}`); if (sequence.current === request) setData(result.kickoff); } catch (failure) { if (sequence.current === request) { if (followThroughAccessDenied(failure)) { setData(null); setEditing(null); setDrafts({}); } setError(followThroughError(failure, '开工记录暂时无法读取。')); } } finally { if (sequence.current === request) setLoading(false); } }, [handoffId]);
  useEffect(() => { setData(null); setEditing(null); setDrafts({}); setFirstDate(''); void load(); return () => { sequence.current += 1; }; }, [load]);
  const initialize = async () => { if (!data?.can_edit || inFlight.current || !firstDate) return; inFlight.current = true; setSaving(true); setError(''); try { const result = await followThroughApi<{ kickoff: KickoffDetail }>(`/kickoffs/${handoffId}/initialize`, 'POST', { first_delivery_due_date: firstDate }); setData(result.kickoff); onSaved(); } catch (failure) { setError(followThroughError(failure, '清单未建立，请重试；不会改变交接与收款状态。')); } finally { inFlight.current = false; setSaving(false); } };
  const openEdit = (item: KickoffItem) => { setDrafts(previous => previous[item.key] ? previous : { ...previous, [item.key]: { status: item.status, due_date: item.due_date || '', note: item.note || '', evidence: item.evidence || '', completed_on: item.completed_on || '' } }); setEditError(''); setEditing(item); };
  const draft = editing ? drafts[editing.key] : null;
  const setDraft = (values: Partial<KickoffDraft>) => { if (editing) setDrafts(previous => ({ ...previous, [editing.key]: { ...previous[editing.key], ...values } })); };
  const saveItem = async () => { if (!editing || !draft || !data?.can_edit || inFlight.current) return; if (!draft.due_date || ((draft.status === 'completed' || draft.status === 'blocked') && draft.note.trim().length < 3) || (draft.status === 'completed' && !draft.completed_on)) { setEditError('请填写截止日期；完成或有卡点时，请补充至少 3 个字的记录，完成还需填写完成日期。'); return; } inFlight.current = true; setSaving(true); setEditError(''); try { const result = await followThroughApi<{ kickoff: KickoffDetail }>(`/kickoffs/${handoffId}/items/${encodeURIComponent(editing.key)}`, 'PATCH', { ...draft, revision: data.revision, completed_on: draft.status === 'completed' ? draft.completed_on : null }); setData(result.kickoff); setDrafts(previous => { const next = { ...previous }; delete next[editing.key]; return next; }); setEditing(null); onSaved(); } catch (failure) { if (followThroughAccessDenied(failure)) { setEditing(null); setDrafts({}); setData(null); setError('当前访问权限已变化，请重新读取记录。'); } else setEditError(followThroughError(failure, '保存失败，输入已保留。请重新读取记录后核对。')); } finally { inFlight.current = false; setSaving(false); } };
  return <div className="sf-kickoff-detail">
    <div className="sf-detail-toolbar"><button type="button" className="sf-return" onClick={onBack}><ArrowLeft size={15} />返回开工列表</button><Button size="sm" variant="outline" onClick={() => void load()} disabled={loading || saving}>重新读取记录</Button></div>
    {error && <div className="sf-error" role="alert">{error}{data && ' 已保留上次读取记录。'}</div>}
    {!data && loading && <p className="sf-empty" role="status">正在读取开工清单…</p>}
    {data && <>
      <article className="sf-panel sf-detail-header"><div className="sf-heading"><div><h3>{data.business_name || `客户 #${data.customer_id}`}</h3><p>{data.package_name || '已登记套餐'} · 运营 {data.operations_owner_name || '待指定'}</p></div><span className={`sf-status sf-status-${data.status}`}>{kickoffLabels[data.status] || '待确认'}</span></div><p>服务 {data.service_start_date || '待确认'} 至 {data.service_end_date || '待确认'}</p><p>服务平台：{data.selected_platforms?.join('、') || '尚未登记，请核对交接内容'}</p>{!data.can_edit && <p className="sf-readonly">{data.read_only_reason || '当前为只读。指定运营取得交付编辑权限并确认接收后，可维护开工清单。'}</p>}
        {!data.initialized && <div className="sf-initialize"><p>建立后按套餐生成固定步骤，不会自动开通服务或确认收款。</p>{data.can_edit ? <><label>首次交付计划日期<Input aria-label="首次交付计划日期" type="date" min={data.service_start_date} max={kickoffLastServiceDate(data.service_end_date)} value={firstDate} onChange={event => setFirstDate(event.target.value)} /></label><Button disabled={!firstDate || saving || firstDate < (data.service_start_date || '') || Boolean(data.service_end_date && firstDate >= data.service_end_date)} onClick={() => void initialize()}>{saving ? '正在建立…' : '建立开工清单'}</Button></> : <p>请由老板完成客户授权，并由指定运营确认接收。</p>}</div>}
      </article>
      {data.initialized && <><div className="sf-progress"><strong>已完成 {data.completed_count}/{data.total_count} 项</strong><span>{data.blocked_count ? `${data.blocked_count} 项受阻 · ` : ''}首次交付计划 {data.first_delivery_due_date || '待确认'}</span></div><div className="sf-records">{data.items.map(item => <article className="sf-panel sf-check-item" key={item.key}><div className="sf-heading"><div><h4>{item.title}</h4><p>截止 {item.due_date || '未安排'}{item.completed_on && ` · 完成 ${item.completed_on}`}</p></div><span className={`sf-status sf-status-${item.status}`}>{itemLabels[item.status]}</span></div>{item.note && <p className="sf-note">{item.note}</p>}{item.evidence && <p className="sf-evidence">依据：{item.evidence}</p>}<div className="sf-footer"><span>{item.updated_by_name ? `${item.updated_by_name} · ` : ''}{item.updated_at ? followThroughDate(item.updated_at) : '尚未更新'}</span>{data.can_edit && <Button size="sm" variant="outline" onClick={() => openEdit(item)} aria-label={`更新进度：${item.title}`}>更新进度<span className="sr-only">：{item.title}</span></Button>}</div></article>)}</div></>}
      {data.audit?.length > 0 && <details className="sf-panel sf-disclosure"><summary>变更记录 · {data.audit.length} 条</summary><ol>{data.audit.map(item => <li key={item.id}><div><strong>{item.actor_name || '操作人待确认'} · {['initialize', 'initialized'].includes(item.action || '') ? '建立清单' : '更新清单'}</strong><time>{followThroughDate(item.created_at)}</time></div><p>{data.items?.find(step => step.key === item.item_key)?.title || item.item_key || '开工安排'}</p></li>)}</ol></details>}
    </>}
    <Dialog open={Boolean(editing)} onOpenChange={open => { if (!open && !saving) setEditing(null); }}><DialogContent className="sf-edit-dialog" aria-describedby={undefined}><DialogHeader><DialogTitle>更新进度 · {editing?.title}</DialogTitle></DialogHeader>{draft && <form onSubmit={event => { event.preventDefault(); void saveItem(); }}><p className="sf-readonly">只更新开工记录；请填写授权状态和资料位置，不要填写密码或验证码。</p><label>进度状态<select aria-label="进度状态" value={draft.status} onChange={event => setDraft({ status: event.target.value as KickoffDraft['status'] })}><option value="pending">待完成</option><option value="blocked">有卡点</option><option value="completed">已完成</option></select></label><label>截止日期<Input aria-label="截止日期" type="date" min={data?.service_start_date} max={kickoffLastServiceDate(data?.service_end_date)} value={draft.due_date} onChange={event => setDraft({ due_date: event.target.value })} required /></label>{draft.status === 'completed' && <label>完成日期<Input aria-label="完成日期" type="date" min="1900-01-01" max={todayKey()} value={draft.completed_on} onChange={event => setDraft({ completed_on: event.target.value })} required /></label>}<label>进度说明<Textarea aria-label="进度说明" value={draft.note} maxLength={2000} placeholder="已完成什么，或卡在哪里、下一步如何处理" onChange={event => setDraft({ note: event.target.value })} /></label><label>依据 / 资料位置<Input aria-label="依据 / 资料位置" value={draft.evidence} maxLength={1000} placeholder="如：客户已授权、共享文件夹名称、交付记录编号" onChange={event => setDraft({ evidence: event.target.value })} /></label>{editError && <div className="sf-error" role="alert">{editError}<button type="button" onClick={() => void load()} disabled={loading}>刷新记录（保留输入）</button></div>}<div className="sf-form-actions"><Button type="button" variant="outline" onClick={() => setEditing(null)} disabled={saving}>暂不保存</Button><Button type="submit" disabled={saving || !data?.can_edit}>{saving ? '正在保存…' : '保存进度'}</Button></div></form>}</DialogContent></Dialog>
  </div>;
}
