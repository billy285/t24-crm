import { useEffect, useMemo, useRef, useState } from 'react';
import { AlertCircle, CheckCircle2, Clock3, RefreshCw, ShieldCheck } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { NativeSelect } from '@/components/ui/native-select';
import { Textarea } from '@/components/ui/textarea';
import { MediaImageDeliveryPolicy, PublicationImagePreview } from '@/components/MediaPublicationImage';
import { mediaError, mediaErrorStatus, mediaRequestId, mediaUtcToLocal } from '@/lib/media-operations-api';
import { confirmDiscardAllChanges, useHardNavigationBlock, useUnsavedChanges } from '@/lib/use-unsaved-changes';
import MediaMetaMonthlyPipeline from './MediaMetaMonthlyPipeline';
import { monthlyPlatform, type MonthlyRun } from '@/lib/media-monthly-api';
import { monthlyWorkflowApi, monthlyWorkflowImages, monthlyWorkflowMutationMatches, verifiedMonthlyWorkflow, type MonthlyWorkflow, type MonthlyWorkflowMutation } from '@/lib/media-monthly-workflow-api';
import './media-monthly-pipeline.css';

type Props = {
  scope: string; run: MonthlyRun; isOwner: boolean; parentBlocked: boolean;
  onPacketActive: (active: boolean) => void; onReloadRun: () => void; onOpenTask?: (id: number) => void; onHoldChange?: (active: boolean) => void; onChanged?: () => void;
};
type Pending = { mutation: MonthlyWorkflowMutation; before: MonthlyWorkflow };
const stageLabels = { prepared: '待整月审核', reviewed: '内容已审核 · 尚未排期', scheduled: '正式排期已开启', schedule_prepared: '计划已保存 · 尚未启用', cancelled: '已撤回 · 文案保留' };
const scheduleLabels: Record<string, string> = { scheduled: '等待到期', dispatching: '正在提交', pending: '提交结果待确认', accepted: 'Google 处理中', succeeded: 'Google 已确认', unknown: '结果待确认', rejected: 'Google 未通过', failed: '未提交成功', blocked: '条件变化，已暂停', missed: '错过时间，未补发', cancelled: '已取消' };
const uncertain = (cause: unknown) => !mediaErrorStatus(cause) || [408, 429].includes(mediaErrorStatus(cause) || 0) || (mediaErrorStatus(cause) || 0) >= 500;
const imageKey = (id: string, sha: string) => `${id}:${sha}`;
const shownTime = (value: string | null, zone = 'Asia/Shanghai') => value ? mediaUtcToLocal(value, zone).replace('T', ' ') : '尚未记录';

export default function MediaMonthlyPipeline(props: Props) {
  if (!props.isOwner || !Number.isSafeInteger(props.run.customer_id) || props.run.customer_id < 1 || props.run.status !== 'generated') return null;
  if (monthlyPlatform(props.run) !== 'google_business') return <MediaMetaMonthlyPipeline {...props}/>;
  return <OwnerMonthlyPipeline key={`${props.scope}:${props.run.customer_id}:${props.run.month}:${props.run.id}:${props.run.revision}`} {...props}/>;
}

function OwnerMonthlyPipeline({ scope, run, isOwner, parentBlocked, onPacketActive, onReloadRun, onOpenTask, onHoldChange, onChanged }: Props) {
  const identity = `${scope}:${run.customer_id}:${run.month}:${run.id}:${run.revision}:${isOwner}`;
  const current = useRef(identity); current.current = identity;
  const alive = useRef(true), sequence = useRef(0), busyRef = useRef(false), pending = useRef<Pending | null>(null);
  const packetListener = useRef(onPacketActive); packetListener.current = onPacketActive;
  const changedListener = useRef(onChanged); changedListener.current = onChanged;
  const holdListener = useRef(onHoldChange); holdListener.current = onHoldChange;
  const [data, setData] = useState<MonthlyWorkflow | null>(null), [loading, setLoading] = useState(true), [busy, setBusy] = useState(false);
  const [unknown, setUnknown] = useState(false), [notFound, setNotFound] = useState(false), [retryConfirmed, setRetryConfirmed] = useState(false), [needsRefresh, setNeedsRefresh] = useState(false);
  const [selected, setSelected] = useState<Record<number, string>>({}), [rightsConfirmed, setRightsConfirmed] = useState(false), [factsConfirmed, setFactsConfirmed] = useState(false);
  const [bulkImage, setBulkImage] = useState('');
  const [reviewConfirmed, setReviewConfirmed] = useState(false), [publicationConfirmed, setPublicationConfirmed] = useState(false), [cancelConfirmed, setCancelConfirmed] = useState(false), [cancelReason, setCancelReason] = useState('');
  const [showDeliveryPolicy, setShowDeliveryPolicy] = useState(false);
  const [error, setError] = useState(''), [notice, setNotice] = useState(''), [photoReady, setPhotoReady] = useState<Record<string, boolean>>({}), [photoEpoch, setPhotoEpoch] = useState(0);
  const photoEpochRef = useRef(0), initialSelection = useRef('{}');
  const selectionDirty = JSON.stringify(selected) !== initialSelection.current;
  const draftGuard = useUnsavedChanges(selectionDirty), hold = useHardNavigationBlock(busy || unknown);
  const authorized = () => alive.current && current.current === identity && isOwner && Number.isSafeInteger(run.customer_id) && run.customer_id > 0;
  const packet = data?.workflow;
  const stoppedHistory = packet?.status === 'cancelled' && (data?.history_frozen === true || !!data?.items.some(item => item.schedule && item.schedule.status !== 'cancelled'));
  const activePacket = !!packet && (packet.status !== 'cancelled' || stoppedHistory);
  const editingMaterial = !activePacket;
  const blocked = busy || unknown || loading || parentBlocked || needsRefresh || showDeliveryPolicy;
  const options = useMemo(() => {
    const images = data?.materials.flatMap(material => material.image_versions.filter(image => image.status === 'ready' && image.width >= 250 && image.height >= 250 && image.byte_size >= 10 * 1024 && image.byte_size <= 5 * 1024 * 1024).map(image => ({ image, title: material.title }))) || [];
    return [...new Map(images.map(value => [value.image.id, value])).values()];
  }, [data?.materials]);
  const displayedPhotos = useMemo(() => {
    if (!data) return [];
    if (activePacket) return monthlyWorkflowImages(data).map(image => ({ image, title: data.materials.find(material => material.id === image.material_id)?.title || '已冻结的实际配图' }));
    return options.filter(value => Object.values(selected).includes(value.image.id));
  }, [data, activePacket, options, selected]);
  const verifiedPhotos = displayedPhotos.length > 0 && displayedPhotos.every(value => photoReady[imageKey(value.image.id, value.image.image_sha256)] === true);
  const selectionComplete = !!data && data.items.length > 0 && data.items.length === run.items.length && data.items.every(item => options.some(option => option.image.id === selected[item.item_id]));
  const packetPhotosComplete = !!data && data.items.every(item => item.publication_image?.status === 'ready' && !item.quality_warnings.length);
  const expired = !!packet && ['prepared', 'reviewed'].includes(packet.status) && Date.parse(packet.expires_at) <= Date.now();
  const freshPacket = !!data && !data.source_stale && !expired && data.run_revision === run.revision;

  function resetConfirmations() { setRightsConfirmed(false); setFactsConfirmed(false); setReviewConfirmed(false); setPublicationConfirmed(false); setCancelConfirmed(false); setRetryConfirmed(false); }
  function renewPhotos() { photoEpochRef.current += 1; setPhotoEpoch(photoEpochRef.current); setPhotoReady({}); }
  function accept(value: MonthlyWorkflow) {
    setData(value); setSelected(Object.fromEntries(value.items.map(item => [item.item_id, item.image_version_id || ''])));
    initialSelection.current = JSON.stringify(Object.fromEntries(value.items.map(item => [item.item_id, item.image_version_id || ''])));
    setBulkImage(''); resetConfirmations(); renewPhotos(); draftGuard.markSaved();
    packetListener.current(!!value.workflow && (value.workflow.status !== 'cancelled' || value.history_frozen === true || value.items.some(item => item.schedule && item.schedule.status !== 'cancelled')));
  }
  async function readLatest(signal?: AbortSignal, preserveError = false) {
    const request = ++sequence.current; setLoading(true); if (!preserveError) setError('');
    try {
      const value = verifiedMonthlyWorkflow(await monthlyWorkflowApi<MonthlyWorkflow>(`/runs/${run.id}/workflow`, 'GET', undefined, signal), run.id, run);
      if (!authorized() || signal?.aborted || request !== sequence.current) return null;
      accept(value); setNeedsRefresh(false); return value;
    } catch (cause) {
      if (authorized() && !signal?.aborted && request === sequence.current) { setNeedsRefresh(true); setError(mediaError(cause, cause instanceof Error ? cause.message : '本月发布流程暂时无法核对。')); }
      return null;
    } finally { if (authorized() && !signal?.aborted && request === sequence.current) setLoading(false); }
  }
  useEffect(() => {
    alive.current = true; const controller = new AbortController(); void readLatest(controller.signal);
    return () => { alive.current = false; sequence.current += 1; controller.abort(); };
    // The instance key fences the actor, merchant, batch and legacy copy revision.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [identity]);
  useEffect(() => { holdListener.current?.(busy || unknown || selectionDirty); return () => holdListener.current?.(false); }, [busy, unknown, selectionDirty]);

  function lock() { busyRef.current = true; setBusy(true); hold.lock(); holdListener.current?.(true); }
  function release() { busyRef.current = false; setBusy(false); if (!pending.current) hold.release(); }
  function clearPending() { pending.current = null; setUnknown(false); setNotFound(false); setRetryConfirmed(false); }
  async function finish(value: MonthlyWorkflow, original: Pending) {
    if (!monthlyWorkflowMutationMatches(value, original.before, original.mutation)) throw new Error('返回结果与本次冻结的内容、图片或操作不一致，请读取原请求结果。');
    if (value.workflow?.status !== 'cancelled') packetListener.current(true);
    clearPending(); setNeedsRefresh(true);
    const message = original.mutation.kind === 'prepare' ? `本月审核清单已准备好，原有${run.items.length}篇文案保留；尚未审核、排期或公开发布。` : original.mutation.kind === 'review' ? '本月内容审核已通过，尚未创建正式排期，也未公开发布。' : original.mutation.kind === 'schedule' ? '正式排期已保存，服务器仅按已确认日期执行；请在下方查看每篇状态和异常。' : '本批次未执行的安排已撤回，文案保留；已公开内容不会删除。';
    const latest = await readLatest(undefined, true);
    if (authorized()) {
      const unchanged = latest && !latest.source_stale && latest.workflow?.id === value.workflow?.id && latest.workflow?.revision === value.workflow?.revision && latest.workflow?.status === value.workflow?.status;
      setNotice(!latest ? '原请求已返回记录，但当前清单尚未重新读取成功；继续操作已暂停。' : unchanged ? message : '原请求结果已核对，清单后来已有更新；下方显示当前状态，不会沿用旧确认继续操作。');
      changedListener.current?.();
    }
  }
  async function dispatch(original: Pending) {
    if (!authorized() || busyRef.current || parentBlocked) return;
    lock(); pending.current = original; setError(''); setNotice('');
    try {
      const value = verifiedMonthlyWorkflow(await monthlyWorkflowApi<MonthlyWorkflow>(`/runs/${run.id}/${original.mutation.kind}`, 'POST', original.mutation.body), run.id, run);
      if (authorized()) await finish(value, original);
    } catch (cause) {
      if (!authorized()) return;
      resetConfirmations();
      if (uncertain(cause)) { setUnknown(true); setError('这次操作结果待确认。请先读取原请求，不会自动重发、再次排期或另建一批。'); }
      else { clearPending(); setNeedsRefresh(true); setError(mediaError(cause, cause instanceof Error ? cause.message : '操作尚未完成，请重新核对当前状态。')); }
    } finally { if (authorized()) release(); }
  }
  async function recover() {
    const original = pending.current;
    if (!original || busyRef.current || !authorized()) return;
    lock(); setError(''); setNotFound(false);
    try {
      const value = verifiedMonthlyWorkflow(await monthlyWorkflowApi<MonthlyWorkflow>(`/workflow-requests/${original.mutation.body.request_id}`), run.id, run);
      if (authorized()) await finish(value, original);
    } catch (cause) {
      if (authorized()) {
        if (mediaErrorStatus(cause) === 409) {
          const latest = await readLatest(undefined, true);
          if (authorized() && latest) { clearPending(); setError(''); setNotice('原操作已登记，但批次版本已有变化。已读取当前清单，请按当前状态核对，不会重新执行原操作。'); changedListener.current?.(); }
        } else { setNotFound(mediaErrorStatus(cause) === 404); setError(mediaError(cause, '原请求结果仍无法确认，请保留编号，不要另建操作。')); }
      }
    } finally { if (authorized()) release(); }
  }
  function prepare() {
    if (!data || blocked || !data.capabilities.can_prepare || !selectionComplete || !verifiedPhotos || !rightsConfirmed || !factsConfirmed || data.run_revision !== run.revision) return;
    void dispatch({ before: data, mutation: { kind: 'prepare', body: { request_id: mediaRequestId(), expected_run_revision: data.run_revision, expected_workflow_revision: packet?.revision || 0, items: data.items.map(item => ({ item_id: item.item_id, image_version_id: selected[item.item_id], rights_confirmed: true })), facts_confirmed: true } } });
  }
  function review() {
    if (!data || !packet || blocked || !freshPacket || !packetPhotosComplete || !verifiedPhotos || !reviewConfirmed || packet.status !== 'prepared' || !data.capabilities.can_review) return;
    void dispatch({ before: data, mutation: { kind: 'review', body: { request_id: mediaRequestId(), expected_revision: packet.revision, preview_hash: packet.preview_hash, confirmed: true } } });
  }
  function schedule() {
    if (!data || !packet || blocked || !freshPacket || !packetPhotosComplete || !verifiedPhotos || !publicationConfirmed || packet.status !== 'reviewed' || !data.capabilities.can_schedule || !data.delivery.enabled || !data.scheduler.enabled) return;
    void dispatch({ before: data, mutation: { kind: 'schedule', body: { request_id: mediaRequestId(), expected_revision: packet.revision, preview_hash: packet.preview_hash, publication_confirmed: true, confirmation_version: 'monthly-publication-v1' } } });
  }
  function cancel() {
    if (!data || !packet || blocked || !data.capabilities.can_cancel || !cancelConfirmed || cancelReason.trim().length < 3 || cancelReason.trim().length > 200) return;
    void dispatch({ before: data, mutation: { kind: 'cancel', body: { request_id: mediaRequestId(), expected_revision: packet.revision, reason: cancelReason.trim() } } });
  }
  function toggleDeliveryPolicy() {
    if (busy || unknown || loading || parentBlocked || !confirmDiscardAllChanges()) return;
    setShowDeliveryPolicy(previous => !previous); setPublicationConfirmed(false);
    if (showDeliveryPolicy) void readLatest();
  }
  function selectImage(itemId: number, value: string) { holdListener.current?.(true); setSelected(previous => ({ ...previous, [itemId]: value })); resetConfirmations(); renewPhotos(); }
  function applyBulkImage() {
    if (!data || blocked || !options.some(option => option.image.id === bulkImage)) return;
    holdListener.current?.(true); setSelected(Object.fromEntries(data.items.map(item => [item.item_id, bulkImage]))); resetConfirmations(); renewPhotos();
  }
  function discardImageChanges() {
    if (!data || blocked) return;
    setSelected(Object.fromEntries(data.items.map(item => [item.item_id, item.image_version_id || '']))); setBulkImage(''); resetConfirmations(); renewPhotos(); draftGuard.markSaved(); holdListener.current?.(false);
  }
  function photoState(key: string, epoch: number, state: string) {
    if (!authorized() || epoch !== photoEpochRef.current) return;
    setPhotoReady(previous => ({ ...previous, [key]: state === 'ready' }));
    if (state !== 'ready') { setRightsConfirmed(false); setReviewConfirmed(false); setPublicationConfirmed(false); }
  }

  if (!data && loading) return <section className="mm-flow mm-flow-loading" role="status"><RefreshCw className="animate-spin"/>正在核对本月素材、审核清单和实际排期…</section>;
  if (!data) return <section className="mm-flow"><p className="mm-flow-error" role="alert">{error || '本月发布流程尚未就绪。'}</p><Button variant="outline" onClick={() => void readLatest()}>重新核对本月流程</Button></section>;
  const orderedItems = [...data.items].sort((a, b) => Date.parse(a.proposed_publish_at) - Date.parse(b.proposed_publish_at));
  return <section className="mm-flow" aria-label={`${run.profile_snapshot.public_facts.public_name}整月审核与发布流程`}>
    <header className="mm-flow-heading"><div><span className="mm-flow-eyebrow">{run.profile_snapshot.public_facts.public_name} · Google 商家 · {run.month}</span><h3>{activePacket ? stageLabels[packet!.status] : `把本月${run.items.length}篇准备为可核对的发布清单`}</h3><p>素材准备、内容审核、正式排期分别确认。准备和审核都不会公开发布。</p></div><Button variant="outline" disabled={busy || unknown || parentBlocked || showDeliveryPolicy} onClick={() => { if (confirmDiscardAllChanges()) void readLatest(); }}><RefreshCw/>刷新流程状态</Button></header>
    <ol className="mm-flow-steps" aria-label="本月发布进度"><li className={activePacket ? 'done' : 'current'}><span>1</span>素材与清单</li><li className={packet?.status === 'reviewed' || packet?.status === 'scheduled' ? 'done' : packet?.status === 'prepared' ? 'current' : ''}><span>2</span>整月内容审核</li><li className={packet?.status === 'scheduled' ? 'current' : ''}><span>3</span>确认正式排期</li><li><span>4</span>到期结果与异常</li></ol>
    {notice && <p className="mm-flow-notice" role="status">{notice}</p>}{error && <p className="mm-flow-error" role="alert"><AlertCircle/>{error}</p>}
    {unknown && <section className="mm-flow-recovery"><strong>先确认原操作结果</strong><p>网络中断时，审核或排期可能已经保存。只查询下方原编号，不会重新发布或创建另一批。</p><code>{pending.current?.mutation.body.request_id}</code><Button variant="outline" disabled={busy} onClick={() => void recover()}>读取原流程操作结果</Button>{notFound && <><label className="mm-check"><input type="checkbox" checked={retryConfirmed} disabled={busy} onChange={event => setRetryConfirmed(event.target.checked)}/>我已核对暂未登记，只沿用原编号和原内容重新确认。</label><Button disabled={busy || !retryConfirmed} onClick={() => { if (pending.current && retryConfirmed) void dispatch(pending.current); }}>沿用原流程请求确认</Button></>}</section>}
    {data.source_stale && <p className="mm-flow-warning">门店、菜单、素材或文案已变化，旧确认不能用于新的提交。已提交项目请核对原记录；未执行内容按当前状态处理。</p>}
    {needsRefresh && !unknown && <p className="mm-flow-warning">请先刷新并成功读取当前状态，再继续审核或排期。</p>}
    {data.run_revision !== run.revision && <p className="mm-flow-warning">本批次文案版本已更新，请先读取最新草稿。<Button variant="outline" disabled={busy || unknown || parentBlocked} onClick={onReloadRun}>读取最新草稿版本</Button></p>}
    {data.checks.some(check => check.state !== 'ready') && <details className="mm-flow-checks" open={!activePacket}><summary>还有 {data.checks.filter(check => check.state !== 'ready').length} 项需要核对</summary><ul>{data.checks.filter(check => check.state !== 'ready').map(check => <li key={check.key}>{check.message}</li>)}</ul></details>}
    {editingMaterial && <section className="mm-flow-materials"><h4>1 · 选择本月真实配图</h4><p>只准备固定图片和本月使用依据，不修改原素材记录、员工权限或公开投递设置。低清图片保留参考，不进入本批次。</p>{options.length === 0 && <p className="mm-flow-warning">暂无符合尺寸、大小及状态要求的固定图片。请先在“菜单与素材”准备真实图片版本，再刷新本页。</p>}<div className="mm-flow-bulk-image"><NativeSelect aria-label="本月统一配图" value={bulkImage} disabled={blocked} onChange={setBulkImage} options={[{ value: '', label: `可选：给${run.items.length}篇统一选择一张图` }, ...options.map(option => ({ value: option.image.id, label: `${option.title} · ${option.image.width}×${option.image.height}` }))]}/><Button variant="outline" disabled={blocked || !options.some(option => option.image.id === bulkImage)} onClick={applyBulkImage}>统一用于这{run.items.length}篇</Button></div>{selectionDirty && <Button variant="ghost" disabled={blocked} onClick={discardImageChanges}>放弃本次配图调整</Button>}<details><summary>逐篇调整配图 · {data.items.length}篇</summary><div className="mm-flow-image-choices">{orderedItems.map((item, index) => <label key={item.item_id}><span><b>第{index + 1}篇</b>{item.title}</span><NativeSelect aria-label={`本月清单配图 ${item.item_id}`} value={selected[item.item_id] || ''} disabled={blocked} onChange={value => selectImage(item.item_id, value)} options={[{ value: '', label: '请选择本篇实际配图' }, ...options.map(option => ({ value: option.image.id, label: `${option.title} · ${option.image.width}×${option.image.height}` }))]}/></label>)}</div></details></section>}
    {displayedPhotos.length > 0 && <section className="mm-flow-photos"><header><h4>{activePacket ? '本清单实际配图' : '本次选择的实际配图'} · {displayedPhotos.length}张</h4><p>{displayedPhotos.length === 1 ? `${run.items.length}篇目前共用同一张图；每篇下方都标明对应配图。可以先逐篇更换，再准备清单。` : '同一图片只读取并核对一次；每篇文案明确对应下方图片编号。'}</p></header><div>{displayedPhotos.map((value, index) => { const key = imageKey(value.image.id, value.image.image_sha256); return <article key={`${key}:${photoEpoch}`}><PublicationImagePreview image={value.image} scope={`${identity}:packet:${packet?.id || 'selection'}:${packet?.revision || 0}:read:${photoEpoch}`} title={`配图 ${index + 1} · ${value.title}`} onStateChange={state => photoState(key, photoEpoch, state)}/></article>; })}</div>{!verifiedPhotos && <p className="mm-flow-warning">请等待实际图片读取并核对成功。图片变化或无法显示时，不能继续确认。</p>}</section>}
    {editingMaterial && <footer className="mm-flow-prepare"><label className="mm-check"><input type="checkbox" checked={rightsConfirmed} disabled={blocked || !selectionComplete || !verifiedPhotos} onChange={event => setRightsConfirmed(event.target.checked)}/>我已核对所选真实图片及已有使用依据，确认这些固定图片可用于“{run.profile_snapshot.public_facts.public_name}”本月的公开宣传。本次仅保存私有审核清单。</label><label className="mm-check"><input type="checkbox" checked={factsConfirmed} disabled={blocked || !selectionComplete} onChange={event => setFactsConfirmed(event.target.checked)}/>保留现有{run.items.length}篇文案；我已确认当前菜单、门店资料和配图对应关系，未新增未经确认的价格、优惠或承诺。</label><Button disabled={blocked || !data.capabilities.can_prepare || !selectionComplete || !verifiedPhotos || !rightsConfirmed || !factsConfirmed || data.run_revision !== run.revision} onClick={prepare}><ShieldCheck/>准备本月审核清单，保留文案</Button></footer>}
    {activePacket && <>
      <section className="mm-flow-packet"><header><div><h4>本月完整审核清单 · {run.items.length}篇</h4><p>Google 门店：{data.binding?.title || '尚未绑定'} · {run.profile_snapshot.rules.timezone} · 每周{run.profile_snapshot.rules.posts_per_week}篇 · {run.profile_snapshot.rules.local_time}</p><p>{packet?.status === 'scheduled' || stoppedHistory ? '下方保留正式排期及平台结果。' : '下方日期仍是建议时间，尚未建立正式发布排期。'}<br/>{stoppedHistory ? '本批次待执行安排已停止，历史提交结果保留；待确认项目不会自动重发。' : packet?.status === 'scheduled' ? '确认后按所列日期执行；每次到期仍核对门店、权限和内容。' : <>本次审核有效至 {shownTime(packet!.expires_at, run.profile_snapshot.rules.timezone)}（{run.profile_snapshot.rules.timezone}）{expired ? ' · 已过期，请撤回后重新准备' : ''}</>}</p></div><span className="mm-flow-status">{stageLabels[packet!.status]}</span></header><div className="mm-flow-posts">{orderedItems.map((item, index) => { const photoIndex = displayedPhotos.findIndex(value => value.image.id === item.image_version_id && value.image.image_sha256 === item.image_sha256); return <article key={item.item_id}><header><span>第{index + 1}篇</span><strong>{shownTime(item.proposed_publish_at, item.timezone)}</strong><small>{item.timezone} · {item.schedule ? '正式排期' : '建议时间'}<br/>北京时间 {shownTime(item.proposed_publish_at, 'Asia/Shanghai')}</small></header><p className="mm-flow-photo-label">使用配图：{photoIndex >= 0 ? `图${photoIndex + 1} · ${displayedPhotos[photoIndex].title}` : '图片需重新核对'}</p><h5>{item.title}</h5><p className="mm-flow-copy">{item.content}</p><aside><strong>中文核对摘要 · 不公开</strong><p>{item.owner_summary}</p></aside>{item.quality_warnings.map(warning => <p className="mm-flow-warning" key={warning}>{warning}</p>)}{item.schedule && <p className={`mm-flow-result ${['unknown', 'blocked', 'missed', 'failed', 'rejected'].includes(item.schedule.status) ? 'attention' : ''}`}>{scheduleLabels[item.schedule.status] || item.schedule.status}<span>{item.schedule.message}</span></p>}</article>; })}</div></section>
      {packet!.status === 'prepared' && <section className="mm-flow-decision"><h4>2 · 整月内容审核</h4><p>一次核对全部正文、实际配图及门店日期。此步骤只审核内容，不建立正式排期。</p><label className="mm-check"><input type="checkbox" checked={reviewConfirmed} disabled={blocked || !freshPacket || !verifiedPhotos || !packetPhotosComplete || !data.capabilities.can_review} onChange={event => setReviewConfirmed(event.target.checked)}/>我已核对“{run.profile_snapshot.public_facts.public_name}”Google 商家的这{run.items.length}篇正文、实际配图和建议日期，确认内容审核通过；暂不排期、不公开发布。</label><Button disabled={blocked || !freshPacket || !verifiedPhotos || !packetPhotosComplete || !reviewConfirmed || !data.capabilities.can_review} onClick={review}><CheckCircle2/>整月审核通过，暂不排期</Button></section>}
      {packet!.status === 'reviewed' && <section className="mm-flow-decision mm-flow-publication"><h4>3 · 单独确认正式排期与到期发布</h4><p>确认后会为这{run.items.length}篇建立正式排期，服务器将在对应门店当地时间到期后公开提交给 Google。此操作不是保存草稿。</p>{!data.delivery.enabled && <p className="mm-flow-warning">图片投递尚未启用。请先展开下方设置，由老板单独核对公开投递依据；本页不会自动启用。</p>}<div className="mm-flow-delivery-policy"><Button variant="outline" disabled={busy || unknown || loading || parentBlocked} onClick={toggleDeliveryPolicy}>{showDeliveryPolicy ? '关闭图片投递设置，返回排期确认' : '真实排期前核对图片投递'}</Button>{showDeliveryPolicy && <MediaImageDeliveryPolicy customerId={run.customer_id} scope={`${identity}:delivery`} onChanged={() => { setShowDeliveryPolicy(false); void readLatest(); }}/>}</div>{!data.scheduler.enabled && <p className="mm-flow-warning">到期发布服务尚未启用，当前不能开启本批次。</p>}<label className="mm-check"><input type="checkbox" checked={publicationConfirmed} disabled={blocked || !freshPacket || !verifiedPhotos || !packetPhotosComplete || !data.capabilities.can_schedule || !data.delivery.enabled || !data.scheduler.enabled} onChange={event => setPublicationConfirmed(event.target.checked)}/>我确认将上方{run.items.length}篇已审核的文字和图片，按所列 {run.profile_snapshot.rules.timezone} 日期与{run.profile_snapshot.rules.local_time}时间，发布到“{data.binding?.title || '尚未绑定'}”的 Google 商家；允许服务器到期执行；异常篇目停止自动重发并提醒我，不补发历史时间。</label><Button disabled={blocked || !freshPacket || !verifiedPhotos || !packetPhotosComplete || !publicationConfirmed || !data.capabilities.can_schedule || !data.delivery.enabled || !data.scheduler.enabled} onClick={schedule}><Clock3/>确认整月排期并启用到期发布</Button></section>}
      {(packet!.status === 'scheduled' || stoppedHistory) && <section className="mm-flow-delivery"><h4>{stoppedHistory ? '本批次已停止 · 历史结果保留' : '4 · 到期执行与异常'}</h4><div className="mm-flow-metrics"><span>{stoppedHistory ? '已取消待发' : '等待到期'}<b>{stoppedHistory ? data.counts.cancelled : data.counts.scheduled}</b></span><span>Google已确认<b>{data.counts.succeeded}</b></span><span>需处理<b>{data.alerts.length}</b></span><span>结果待确认<b>{data.counts.unknown}</b></span></div><p>以每篇平台结果为准。待确认的请求不会自动重发，错过时间的内容不会自动补发。</p></section>}
      {data.capabilities.can_cancel && <details className="mm-flow-cancel"><summary>{packet!.status === 'scheduled' ? '停止本批次尚未执行的排期' : '撤回本清单并返回修改'}</summary><p>文案和历史记录保留。已公开内容不会删除；已提交或结果待确认的项目不能借此重发。</p><Textarea aria-label="撤回本月清单原因" value={cancelReason} onChange={event => { setCancelReason(event.target.value); setCancelConfirmed(false); }} rows={2} maxLength={200} disabled={blocked} placeholder="填写至少3字原因，便于后续核对"/><label className="mm-check"><input type="checkbox" checked={cancelConfirmed} disabled={blocked || cancelReason.trim().length < 3} onChange={event => setCancelConfirmed(event.target.checked)}/>确认撤回本批次尚未执行的安排，保留文案与记录。</label><Button variant="outline" disabled={blocked || !cancelConfirmed || cancelReason.trim().length < 3 || cancelReason.trim().length > 200} onClick={cancel}>确认撤回，保留文案</Button></details>}
      <details className="mm-flow-receipt"><summary>查看核对记录</summary><dl><dt>清单</dt><dd>#{packet!.id} · 版本{packet!.revision}</dd><dt>内容摘要</dt><dd>{packet!.preview_hash}</dd><dt>最近更新</dt><dd>{shownTime(packet!.updated_at, 'Asia/Shanghai')}（北京时间）</dd></dl></details>
    </>}
    {data.alerts.length > 0 && <section className="mm-flow-alerts" aria-label="本月发布异常提醒"><h4><AlertCircle/>需要老板处理 · {data.alerts.length}项</h4>{data.alerts.map(alert => <article key={`${alert.key}:${alert.version}`}><strong>{alert.title}</strong><p>{alert.message}</p><small>{alert.item_id ? `本月篇目 #${alert.item_id}` : '本月批次'} · {scheduleLabels[alert.status] || alert.status}</small>{alert.task_id && onOpenTask && <Button variant="outline" disabled={blocked} onClick={() => { if (!blocked && confirmDiscardAllChanges()) onOpenTask(alert.task_id!); }}>查看原任务</Button>}</article>)}<p>提醒会保留到实际问题解决。此处没有自动重发或清除异常按钮。</p></section>}
  </section>;
}
