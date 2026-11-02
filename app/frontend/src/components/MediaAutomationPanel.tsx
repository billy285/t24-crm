import { useEffect, useRef, useState } from 'react';
import { AlertCircle, ArrowRight, CalendarClock, CheckCircle2, Loader2, PauseCircle, RefreshCw, ShieldCheck } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { NativeSelect } from '@/components/ui/native-select';
import { confirmDiscardAllChanges, useHardNavigationBlock, useUnsavedChanges } from '@/lib/use-unsaved-changes';
import { mediaError, mediaErrorStatus, mediaRequestId, mediaUtcToLocal } from '@/lib/media-operations-api';
import { monthlyPlatformLabels, validMonthlyPlatform, type MonthlyPlatform } from '@/lib/media-monthly-api';
import { automationCurrentMonth, automationJobLabels, automationState, automationTimezone, readAutomation, recoverAutomation, saveAutomation, type AutomationSave, type AutomationSetup } from '@/lib/media-automation-api';
import './media-automation-panel.css';

type Props = { scope: string; isOwner: boolean; customerId: number; customerName?: string; platform?: MonthlyPlatform; onOpenMonthly: (platform: MonthlyPlatform, month: string, runId?: number) => void; onChanged?: () => void };
type Form = { enabled: boolean; leadDays: number };
const platformOptions = Object.entries(monthlyPlatformLabels).map(([value, label]) => ({ value, label }));
const formFor = (value: AutomationSetup): Form => ({ enabled: value.policy?.enabled ?? false, leadDays: value.policy?.lead_days ?? 7 });
const pendingError = (cause: unknown) => { const status = mediaErrorStatus(cause); return !status || status === 408 || status === 429 || status >= 500; };
const jobDate = (value: string, timezone: string) => mediaUtcToLocal(value, timezone).replace('T', ' ');

export default function MediaAutomationPanel(props: Props) {
  if (!props.isOwner || !Number.isSafeInteger(props.customerId) || props.customerId < 1 || props.platform !== undefined && !validMonthlyPlatform(props.platform)) return null;
  return <AutomationScope key={`${props.scope}:${props.customerId}:${props.platform || 'choose'}`} {...props}/>;
}

function AutomationScope(props: Props) {
  const [platform, setPlatform] = useState<MonthlyPlatform>(props.platform || 'google_business');
  return <section className="ma-scope" aria-label="商家草稿自动准备"><header className="ma-scope-heading"><div><span>减少每月重复准备</span><h3>草稿自动准备</h3><p>按这家商家的已确认资料准备下月内容，生成后集中交给你审核。</p></div><label>发布平台<NativeSelect aria-label="草稿自动准备平台" value={platform} disabled={props.platform !== undefined} options={platformOptions} onChange={value => { if (validMonthlyPlatform(value) && confirmDiscardAllChanges()) setPlatform(value); }}/></label></header><AutomationSettings key={`${props.scope}:${props.customerId}:${platform}`} {...props} platform={platform}/></section>;
}

function AutomationSettings({ scope, customerId, customerName, platform, onOpenMonthly, onChanged }: Props & { platform: MonthlyPlatform }) {
  const identity = `${scope}:${customerId}:${platform}`, current = useRef(identity); current.current = identity;
  const alive = useRef(true), sequence = useRef(0), busyRef = useRef(false), pending = useRef<AutomationSave | null>(null);
  const [data, setData] = useState<AutomationSetup | null>(null), [loading, setLoading] = useState(true), [refresh, setRefresh] = useState(0), [busy, setBusy] = useState(false), [unknown, setUnknown] = useState(false);
  const [form, setForm] = useState<Form>({ enabled: false, leadDays: 7 }), [confirmed, setConfirmed] = useState(false), [error, setError] = useState(''), [notice, setNotice] = useState('');
  const original = data ? formFor(data) : null, dirty = Boolean(data && original && (form.enabled !== original.enabled || form.leadDays !== original.leadDays || confirmed));
  const guard = useUnsavedChanges(dirty), hold = useHardNavigationBlock(busy || unknown);
  const blocked = loading || busy || unknown;
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  useEffect(() => {
    const controller = new AbortController(), request = ++sequence.current, captured = identity;
    setLoading(true); setData(null); setError(''); setNotice(''); setConfirmed(false);
    void readAutomation(customerId, platform, controller.signal).then(value => { if (alive.current && !controller.signal.aborted && request === sequence.current && current.current === captured) { setData(value); setForm(formFor(value)); } }).catch(cause => { if (alive.current && !controller.signal.aborted && request === sequence.current && current.current === captured) setError(mediaError(cause, cause instanceof Error ? cause.message : '自动准备规则暂时无法读取。')); }).finally(() => { if (alive.current && !controller.signal.aborted && request === sequence.current && current.current === captured) setLoading(false); });
    return () => controller.abort();
  }, [identity, customerId, platform, refresh]);

  function change(patch: Partial<Form>) { if (!alive.current || current.current !== identity || busyRef.current || unknown) return; setForm(value => ({ ...value, ...patch })); setConfirmed(false); setNotice(''); }
  function accept(value: AutomationSetup, message: string) { setData(value); setForm(formFor(value)); setConfirmed(false); setUnknown(false); setError(''); setNotice(message); pending.current = null; guard.markSaved(); hold.release(); onChanged?.(); }
  async function save() {
    if (!alive.current || current.current !== identity || !data || busyRef.current || unknown || !dirty || form.enabled && (!data.eligibility.can_enable || !confirmed)) return;
    const signature = data.source_signature || data.policy?.source_signature, runtime = data.runtime.fingerprint || data.policy?.runtime_fingerprint;
    if (!signature || !runtime) { setError('请先保存已核实的门店、菜单、图片和发布规则，再设置自动准备。'); return; }
    const body: AutomationSave = { request_id: mediaRequestId(), expected_revision: data.policy?.revision || 0, enabled: form.enabled, lead_days: form.leadDays, local_time: '09:00', source_signature: signature, runtime_fingerprint: runtime, confirmed: form.enabled && confirmed, notice_version: 'monthly-autoprep-v1' };
    const captured = identity; pending.current = body; busyRef.current = true; setBusy(true); setError(''); setNotice(''); hold.lock();
    try { const value = await saveAutomation(customerId, platform, body); if (alive.current && current.current === captured) accept(value, body.enabled ? '草稿自动准备规则已保存。生成结果仍等待你审核，公开发布和排期权限没有变化。' : '已暂停后续草稿自动准备。现有草案和已保存的发布安排保持原样。'); }
    catch (cause) { if (alive.current && current.current === captured) { if (pendingError(cause)) { setUnknown(true); setError('规则保存结果待确认。请查询原保存回执，先不要重复保存。'); } else { pending.current = null; hold.release(); setError(mediaError(cause, '规则尚未保存，请核对当前资料和版本。')); } } }
    finally { if (alive.current && current.current === captured) { busyRef.current = false; setBusy(false); } }
  }
  async function recover() {
    const body = pending.current; if (!alive.current || current.current !== identity || !body || busyRef.current) return;
    const captured = identity; busyRef.current = true; setBusy(true); setError('');
    try { const receipt = await recoverAutomation(customerId, platform, body); let result = receipt.result; if (receipt.current_revision !== receipt.result.policy!.revision) result = await readAutomation(customerId, platform); if (alive.current && current.current === captured) accept(result, receipt.current_revision === receipt.result.policy!.revision ? '原保存回执已核对，无需重复提交。' : '原保存回执已核对，并已读取后来更新的最新规则。'); }
    catch (cause) { if (alive.current && current.current === captured) setError(mediaError(cause, '原保存结果暂时无法核对，请稍后查询同一次请求。')); }
    finally { if (alive.current && current.current === captured) { busyRef.current = false; setBusy(false); } }
  }
  function openMonth(month: string, runId?: number) { if (alive.current && current.current === identity && !blocked && !busyRef.current && confirmDiscardAllChanges()) onOpenMonthly(platform, month, runId); }
  function reload() { if (alive.current && current.current === identity && !blocked && confirmDiscardAllChanges()) { guard.markSaved(); setRefresh(value => value + 1); } }
  if (loading) return <div className="ma-loading" role="status"><Loader2 className="animate-spin"/>正在核对本商家的自动准备规则…</div>;
  if (!data) return <div className="ma-message warning" role="alert"><AlertCircle/><div><strong>规则暂时无法读取</strong><p>{error || '当前无法确认是否已启用，请重新读取。'}</p><Button variant="outline" onClick={() => setRefresh(value => value + 1)}>重新读取</Button></div></div>;
  const state = automationState(data), timezone = automationTimezone(data), latest = data.latest_job;
  return <div className="ma-panel" aria-busy={busy}>
    <div className="ma-status"><span className={`ma-badge ${state.tone}`}>{state.label}</span><Button variant="ghost" disabled={blocked} aria-label="刷新草稿自动准备规则" onClick={reload}><RefreshCw size={15}/><span>刷新</span></Button></div>
    <div className="ma-summary"><div><span>下个准备月份</span><strong>{data.next_target_month}</strong><small>{data.next_run_at ? `${jobDate(data.next_run_at, timezone)} · ${timezone}` : '先确认商家资料与门店时区'}</small></div><div><span>准备完成之后</span><strong>等你集中审核</strong><small>不会直接发布，也不会自动通过审核</small></div></div>
    {!data.worker.enabled && <p className="ma-message"><CalendarClock/><span>自动准备服务尚未启用。可以先保存规则；当前不会在后台生成新草案。</span></p>}
    {error && <p className="ma-message warning" role="alert"><AlertCircle/>{error}</p>}{notice && <p className="ma-message success" role="status"><CheckCircle2/>{notice}</p>}
    {data.eligibility.gaps.length > 0 && <details className="ma-gaps" open={!data.eligibility.can_enable}><summary>{data.eligibility.can_enable ? '生成前仍需留意' : '先补齐这些资料'} · {data.eligibility.gaps.length}项</summary><ul>{data.eligibility.gaps.map((gap, i) => <li key={i}>{gap}</li>)}</ul><Button variant="outline" disabled={blocked} onClick={() => openMonth(automationCurrentMonth(data))}>核对门店、素材与规则<ArrowRight size={15}/></Button></details>}
    <div className="ma-config"><label className="ma-toggle"><input type="checkbox" aria-label="启用本商家草稿自动准备" checked={form.enabled} disabled={blocked || !form.enabled && !data.eligibility.can_enable} onChange={event => change({ enabled: event.target.checked })}/><span><strong>按规则自动准备下月草稿</strong><small>仅限{customerName || data.customer.name}的{monthlyPlatformLabels[platform]}，不扩大任何账号或员工权限。</small></span></label><label className="ma-lead">准备时间<NativeSelect aria-label="下月草稿提前准备天数" value={String(form.leadDays)} disabled={blocked} options={Array.from({ length: 12 }, (_, i) => ({ value: String(i + 3), label: `提前${i + 3}天 · 当地09:00` }))} onChange={value => change({ leadDays: Number(value) })}/></label></div>
    {form.enabled && <div className="ma-consent"><strong>本次文字生成范围</strong><p>{data.notice.text}</p><p className="ma-caption">文字服务：{data.runtime.model || '暂未就绪'} · {data.runtime.destination_host || '目的地待核对'}</p><label><input type="checkbox" checked={confirmed} disabled={blocked || !data.eligibility.can_enable} onChange={event => setConfirmed(event.target.checked)}/><span>我确认按这份已核实的公开文字和规则准备下月草稿，资料或服务变化后重新核对。图片字节、财务和私人内容不发送；生成后仍由我审核。</span></label></div>}
    <footer className="ma-actions">{unknown ? <Button variant="outline" disabled={busy} onClick={() => void recover()}><RefreshCw size={15}/>{busy ? '正在核对原回执…' : '查询原保存结果'}</Button> : <><Button disabled={blocked || !dirty || form.enabled && (!data.eligibility.can_enable || !confirmed)} onClick={() => void save()}>{busy ? <Loader2 className="animate-spin" size={15}/> : form.enabled ? <ShieldCheck size={15}/> : <PauseCircle size={15}/>}保存自动准备规则</Button><Button variant="outline" disabled={blocked} onClick={() => openMonth(automationCurrentMonth(data))}>准备／查看本月<ArrowRight size={15}/></Button></>}</footer>
    <section className="ma-jobs" aria-label="自动准备记录"><header><h4>最近准备结果</h4><span>{data.recent_jobs.length}条记录</span></header>{latest ? <div className={`ma-latest${['blocked', 'unknown', 'failed', 'missed'].includes(latest.status) ? ' warning' : ''}`}><div><strong>{latest.month} · {automationJobLabels[latest.status]}</strong><p>{latest.message}</p><small>{jobDate(latest.updated_at, timezone)} · {timezone}</small></div>{latest.run_id && <Button variant="outline" disabled={blocked} onClick={() => openMonth(latest.month, latest.run_id!)}>打开原草案<ArrowRight size={15}/></Button>}{latest.status === 'unknown' && <small>请先核对原生成结果，系统不会自动重发这次请求。</small>}</div> : <p className="ma-caption">尚无自动准备记录。已有手动草案仍从本月工作区查看。</p>}{data.recent_jobs.length > 1 && <details><summary>查看之前的准备记录</summary>{data.recent_jobs.filter(job => job.id !== latest?.id).map(job => <div className="ma-job" key={job.id}><div><strong>{job.month} · {automationJobLabels[job.status]}</strong><p>{job.message}</p></div>{job.run_id && <Button variant="outline" disabled={blocked} onClick={() => openMonth(job.month, job.run_id!)}>查看原草案</Button>}</div>)}</details>}</section>
  </div>;
}
