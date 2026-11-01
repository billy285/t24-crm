import { useEffect, useRef, useState, type CSSProperties } from 'react';
import { CheckCircle2, ChevronRight, Download, ImagePlus, Layers3, Loader2, Palette, RefreshCw, ShieldCheck, Sparkles, Video } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { NativeSelect } from '@/components/ui/native-select';
import { Textarea } from '@/components/ui/textarea';
import { mediaError, mediaErrorStatus, mediaRequestId } from '@/lib/media-operations-api';
import { confirmDiscardAllChanges, useHardNavigationBlock, useUnsavedChanges } from '@/lib/use-unsaved-changes';
import { assetKindLabels, assetPresets, assetProfileReadable, assetStatusLabels, assetStudioApi, assetStudioPreview, verifiedAssetJob, verifiedAssetMutation, verifiedAssetStudio, type AssetFormat, type AssetJob, type AssetKind, type AssetMutation, type AssetOutput, type AssetProfile, type AssetRecipe, type AssetSource, type AssetStudio } from '@/lib/media-asset-studio';
import './media-asset-studio.css';

type Props = { scope: string; customerId: number; isOwner: boolean; onChanged?: () => void };
type Pending = { path: string; method: 'POST' | 'PUT'; body: Record<string, unknown>; expected: { kind: AssetMutation['kind']; request_id: string; customer_id: number; job_id?: string; recipe?: AssetRecipe; sources?: AssetSource[]; profile?: Omit<AssetProfile, 'revision'>; profile_revision?: number } };
type RecipeForm = { kind: AssetKind; image_ids: string[]; title: string; subtitle: string; format: AssetFormat; exposure: number; color: number; sharpness: number };
const emptyRecipe = (): RecipeForm => ({ kind: 'poster', image_ids: [], title: '', subtitle: '', format: 'square', exposure: 0, color: 1, sharpness: 1 });
const countBounds: Record<AssetKind, [number, number]> = { poster: [1, 1], collage: [2, 4], enhance: [1, 1], video: [2, 6] };
const uncertain = (cause: unknown) => !mediaErrorStatus(cause) || [408, 429].includes(mediaErrorStatus(cause) || 0) || (mediaErrorStatus(cause) || 0) >= 500;
const sameProfile = (a: AssetProfile, b: AssetProfile) => ['preset', 'brand_name', 'primary_color', 'accent_color', 'footer'].every(key => a[key as keyof AssetProfile] === b[key as keyof AssetProfile]);
const shortTime = (value: string) => new Intl.DateTimeFormat('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }).format(new Date(value));

export default function MediaAssetStudio(props: Props) {
  if (!props.isOwner || !Number.isSafeInteger(props.customerId) || props.customerId < 1) return null;
  return <OwnerAssetStudio key={`${props.scope}:${props.customerId}`} {...props}/>;
}

function OwnerAssetStudio({ scope, customerId, isOwner, onChanged }: Props) {
  const identity = `${scope}:${customerId}:${isOwner}`;
  const identityRef = useRef(identity); identityRef.current = identity;
  const alive = useRef(true), sequence = useRef(0), busyRef = useRef(false), pending = useRef<Pending | null>(null), changed = useRef(onChanged); changed.current = onChanged;
  const [studio, setStudio] = useState<AssetStudio | null>(null), [profile, setProfile] = useState<AssetProfile | null>(null), [form, setForm] = useState<RecipeForm>(emptyRecipe);
  const [loading, setLoading] = useState(true), [busy, setBusy] = useState(false), [unknown, setUnknown] = useState(false), [notFound, setNotFound] = useState(false), [retryConfirmed, setRetryConfirmed] = useState(false);
  const [error, setError] = useState(''), [notice, setNotice] = useState(''), [search, setSearch] = useState(''), [selectedJob, setSelectedJob] = useState<string | null>(null);
  const [rightsConfirmed, setRightsConfirmed] = useState(false), [adoptConfirmed, setAdoptConfirmed] = useState(false), [adoptTitle, setAdoptTitle] = useState('');
  const [previewReady, setPreviewReady] = useState<Record<string, boolean>>({}), [previewEpoch, setPreviewEpoch] = useState(0), [pollStopped, setPollStopped] = useState(false);
  const previewEpochRef = useRef(0);
  const current = () => alive.current && identityRef.current === identity && isOwner;
  const profileDirty = !!studio && !!profile && !sameProfile(profile, studio.profile);
  const recipeDirty = !!(form.image_ids.length || form.title || form.subtitle);
  const guard = useUnsavedChanges(profileDirty || recipeDirty), hold = useHardNavigationBlock(busy || unknown);
  const blocked = loading || busy || unknown;
  const job = studio?.jobs.find(row => row.id === selectedJob) || null;
  const selectedSources = form.image_ids.map(imageId => studio?.sources.find(source => source.image_id === imageId)).filter((source): source is AssetSource => !!source);
  const sourceProofReady = selectedSources.length > 0 && selectedSources.every(source => previewReady[`source:${source.image_id}:${source.image_sha256}`]);
  const publicSourceTitle = (source: AssetSource) => (source.suggested_title?.trim() || profile?.brand_name || studio?.customer_name || '').slice(0, 80);
  const [minimum, maximum] = countBounds[form.kind];
  const selectionValid = selectedSources.length === form.image_ids.length && form.image_ids.length >= minimum && form.image_ids.length <= maximum;
  const kindAvailable = !!studio?.capabilities[form.kind];
  const lowSources = selectedSources.filter(source => source.width < 720 || source.height < 720);
  const outputKey = job?.output ? `output:${job.id}:${job.output.sha256}` : '';
  const canCreate = !!studio?.capabilities.can_create && kindAvailable && !profileDirty && !!profile && assetProfileReadable(profile) && studio.profile.revision > 0 && selectionValid && sourceProofReady && rightsConfirmed && !blocked;

  function resetProof() { previewEpochRef.current += 1; setPreviewEpoch(previewEpochRef.current); setPreviewReady({}); setRightsConfirmed(false); setAdoptConfirmed(false); }
  function resetForm() { setForm(emptyRecipe()); resetProof(); guard.markSaved(); }
  function acceptStudio(value: AssetStudio) { setStudio(value); setProfile({ ...value.profile }); resetProof(); guard.markSaved(); }
  async function load(signal?: AbortSignal) {
    const seq = ++sequence.current; setLoading(true); setError('');
    try {
      const value = verifiedAssetStudio(await assetStudioApi<AssetStudio>(`/customers/${customerId}/studio`, 'GET', undefined, signal), customerId);
      if (!current() || signal?.aborted || seq !== sequence.current) return;
      acceptStudio(value);
      setSelectedJob(previous => value.jobs.some(row => row.id === previous) ? previous : value.jobs[0]?.id || null);
      const first = value.jobs.find(row => row.id === selectedJob) || value.jobs[0];
      setAdoptTitle(first ? `${assetKindLabels[first.kind]} · ${first.recipe.title || value.customer_name}`.slice(0, 120) : '');
    } catch (cause) { if (current() && !signal?.aborted && seq === sequence.current) { setStudio(null); setProfile(null); setError(mediaError(cause, cause instanceof Error ? cause.message : '商家素材制作暂时无法读取。')); } }
    finally { if (current() && !signal?.aborted && seq === sequence.current) setLoading(false); }
  }
  useEffect(() => {
    alive.current = true; const controller = new AbortController(); void load(controller.signal);
    return () => { alive.current = false; sequence.current += 1; controller.abort(); };
    // Scope and merchant are fenced by the keyed owner instance.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [identity]);
  function acceptJob(value: AssetJob) {
    setStudio(previous => previous ? { ...previous, jobs: [value, ...previous.jobs.filter(row => row.id !== value.id)].slice(0, 30) } : previous);
    setSelectedJob(value.id); setAdoptTitle(`${assetKindLabels[value.kind]} · ${value.recipe.title || studio?.customer_name || '商家素材'}`.slice(0, 120));
    setAdoptConfirmed(false);
  }
  async function readJob(jobId: string, signal?: AbortSignal, silent = false) {
    try {
      const value = verifiedAssetJob(await assetStudioApi<AssetJob>(`/jobs/${jobId}`, 'GET', undefined, signal), customerId, jobId);
      if (current() && !signal?.aborted) {
        setStudio(previous => previous ? { ...previous, jobs: previous.jobs.map(row => row.id === value.id && value.revision >= row.revision ? value : row) } : previous);
        return value;
      }
    } catch (cause) { if (current() && !signal?.aborted) { if ([401, 403, 404].includes(mediaErrorStatus(cause) || 0)) { setStudio(null); setProfile(null); } if (!silent) setError(mediaError(cause, '制作状态暂时无法读取，请刷新原任务，不要重复制作。')); } }
    return null;
  }
  useEffect(() => {
    if (!job || !['queued', 'processing'].includes(job.status) || blocked) return;
    const controller = new AbortController(), started = Date.now(); let timer: ReturnType<typeof setTimeout> | undefined, stopped = false;
    setPollStopped(false);
    const poll = async () => {
      if (stopped || controller.signal.aborted) return;
      if (Date.now() - started >= 120000) { setPollStopped(true); return; }
      if (typeof document === 'undefined' || document.visibilityState !== 'hidden') await readJob(job.id, controller.signal, true);
      if (!stopped && !controller.signal.aborted) timer = setTimeout(() => void poll(), 4000);
    };
    timer = setTimeout(() => void poll(), 4000);
    return () => { stopped = true; controller.abort(); if (timer) clearTimeout(timer); };
    // One bounded GET poll per selected active job; no production request is replayed.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [identity, job?.id, job?.status, blocked]);

  async function finish(value: AssetMutation, original: Pending) {
    verifiedAssetMutation(value, original.expected);
    if (original.expected.kind === 'profile') {
      if (!value.profile || value.profile.revision <= Number(original.body.expected_revision)) throw new Error('品牌设置版本尚未确认，请查询原请求。');
      setStudio(previous => previous ? { ...previous, profile: value.profile! } : previous); setProfile(value.profile); resetProof(); guard.markSaved(); setNotice(value.profile.revision > Number(original.body.expected_revision) + 1 ? '原品牌设置已登记，随后已有更新；下方显示当前模板，制作前请按当前版本核对。' : '品牌模板已保存。之后制作的成品使用此版本，历史素材保持原样。');
    } else {
      if (original.expected.kind === 'create' && value.job!.request_id !== original.expected.request_id) throw new Error('制作任务与原请求不一致。');
      if (original.expected.kind === 'adopt' && (!value.job!.adoption || value.job!.output?.sha256 !== original.body.output_sha256)) throw new Error('新素材保存结果需要继续核对。');
      acceptJob(value.job!);
      if (original.expected.kind === 'create') resetForm();
      setNotice(original.expected.kind === 'adopt' ? '已保存为新的团队素材，仍待内容审核；没有替换原图、任务或月度清单，也没有发布。' : original.expected.kind === 'retry' ? '原制作任务状态已核对。只按当前任务显示的状态继续处理。' : '私有制作任务已登记。可先处理其他工作，完成后再核对成品。');
      if (original.expected.kind === 'adopt') changed.current?.();
    }
    pending.current = null; setUnknown(false); setNotFound(false); setRetryConfirmed(false); hold.release();
  }
  async function dispatch(original: Pending) {
    if (!current() || busyRef.current) return;
    pending.current = original; busyRef.current = true; setBusy(true); setError(''); setNotice(''); hold.lock();
    try { const value = await assetStudioApi<AssetMutation>(original.path, original.method, original.body); if (current()) await finish(value, original); }
    catch (cause) {
      if (!current()) return;
      setRightsConfirmed(false); setAdoptConfirmed(false);
      if (uncertain(cause)) { setUnknown(true); setNotFound(false); setError('原操作结果待确认。请查询原编号，系统不会自动重复制作或重复保存素材。'); }
      else { pending.current = null; setUnknown(false); hold.release(); setError(mediaError(cause, cause instanceof Error ? cause.message : '操作尚未完成，请重新核对。')); }
    } finally { if (current()) { busyRef.current = false; setBusy(false); } }
  }
  async function recover() {
    const original = pending.current; if (!original || busyRef.current || !current()) return;
    busyRef.current = true; setBusy(true); setError(''); setNotFound(false); hold.lock();
    try { const value = await assetStudioApi<AssetMutation>(`/requests/${original.expected.request_id}`); if (current()) await finish(value, original); }
    catch (cause) { if (current()) { setNotFound(mediaErrorStatus(cause) === 404); setError(mediaError(cause, '原操作仍无法确认，请保留编号，不要另建制作或素材。')); } }
    finally { if (current()) { busyRef.current = false; setBusy(false); } }
  }
  function saveProfile() {
    if (!studio || !profile || blocked || !studio.capabilities.can_edit || !profile.brand_name.trim() || !assetProfileReadable(profile) || !profileDirty && studio.profile.revision > 0) return;
    const values = { preset: profile.preset, brand_name: profile.brand_name.trim(), primary_color: profile.primary_color.toUpperCase(), accent_color: profile.accent_color.toUpperCase(), footer: profile.footer.trim() };
    const request_id = mediaRequestId(); void dispatch({ path: `/customers/${customerId}/profile`, method: 'PUT', body: { request_id, expected_revision: studio.profile.revision, ...values }, expected: { kind: 'profile', request_id, customer_id: customerId, profile: values, profile_revision: studio.profile.revision } });
  }
  function create() {
    if (!canCreate || !studio || !profile) return;
    const request_id = mediaRequestId(), recipe: AssetRecipe = { profile_revision: studio.profile.revision, ...form, title: form.title.trim(), subtitle: form.subtitle.trim(), image_ids: [...form.image_ids], rights_confirmed: true };
    void dispatch({ path: `/customers/${customerId}/jobs`, method: 'POST', body: { request_id, ...recipe }, expected: { kind: 'create', request_id, customer_id: customerId, recipe, sources: selectedSources.map(source => ({ ...source })) } });
  }
  function retryJob() {
    if (!studio || !job || blocked || !studio.capabilities.can_create || !job.can_retry || job.status !== 'failed' || job.source_stale) return;
    const request_id = mediaRequestId(); void dispatch({ path: `/jobs/${job.id}/retry`, method: 'POST', body: { request_id, expected_revision: job.revision }, expected: { kind: 'retry', request_id, customer_id: customerId, job_id: job.id, recipe: job.recipe, sources: job.sources } });
  }
  function adopt() {
    if (!studio || !job || blocked || !studio.capabilities.can_adopt || !job.can_adopt || job.source_stale || !job.output || !previewReady[outputKey] || !adoptConfirmed || !adoptTitle.trim()) return;
    const request_id = mediaRequestId(); void dispatch({ path: `/jobs/${job.id}/adopt`, method: 'POST', body: { request_id, expected_revision: job.revision, output_sha256: job.output.sha256, title: adoptTitle.trim(), derivative_confirmed: true }, expected: { kind: 'adopt', request_id, customer_id: customerId, job_id: job.id, recipe: job.recipe, sources: job.sources } });
  }
  function updateForm(patch: Partial<RecipeForm>) { setForm(previous => ({ ...previous, ...patch })); if ('image_ids' in patch || 'kind' in patch) resetProof(); else setRightsConfirmed(false); }
  function toggleSource(source: AssetSource) {
    if (blocked || !studio?.capabilities.can_create) return;
    if (form.image_ids.includes(source.image_id)) updateForm({ image_ids: form.image_ids.filter(value => value !== source.image_id) });
    else if (maximum === 1) updateForm({ image_ids: [source.image_id], ...(!form.title || selectedSources.some(value => form.title === publicSourceTitle(value)) ? { title: publicSourceTitle(source) } : {}) });
    else if (form.image_ids.length < maximum) updateForm({ image_ids: [...form.image_ids, source.image_id], ...(!form.title ? { title: publicSourceTitle(source) } : {}) });
  }
  function previewState(key: string, epoch: number, ready: boolean) { if (current() && epoch === previewEpochRef.current) { setPreviewReady(previous => ({ ...previous, [key]: ready })); if (!ready) { setRightsConfirmed(false); setAdoptConfirmed(false); } } }

  if (loading && !studio) return <section className="mas-empty" role="status"><Loader2 className="animate-spin"/><p>正在核对当前商家的品牌、真实素材和制作任务…</p></section>;
  if (!studio || !profile) return <section className="mas-empty"><Palette/><p role="alert">{error || '当前商家素材制作尚未开放。'}</p><Button variant="outline" onClick={() => void load()}>重新核对商家范围</Button></section>;
  const filteredSources = studio.sources.filter(source => !search.trim() || source.title.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase()));
  return <section className="mas-studio" aria-label={`${studio.customer_name}素材制作`}>
    <header className="mas-header"><div><span className="mas-eyebrow">仅老板 · 当前商家素材</span><h2><Palette/>{studio.customer_name}<small>素材制作</small></h2><p>真实照片配合品牌模板，先私有制作，再核对保存；不自动发布。</p></div><Button variant="outline" disabled={blocked} onClick={() => { if (confirmDiscardAllChanges()) { resetForm(); void load(); } }}><RefreshCw/>刷新制作记录</Button></header>
    {!studio.cooperation_active && <p className="mas-warning">{studio.read_only_reason || '当前商家已停止合作，仅保留历史制作记录。'}</p>}
    {error && <p className="mas-error" role="alert">{error}</p>}{notice && <p className="mas-notice" role="status">{notice}</p>}
    {unknown && <section className="mas-recovery"><strong>先核对原操作</strong><p>网络中断时任务可能已保存。只查询当前商家的原请求，不会自动重做。</p><code>{pending.current?.expected.request_id}</code><Button variant="outline" disabled={busy} onClick={() => void recover()}>查询原制作操作结果</Button>{notFound && <><label className="mas-check"><input type="checkbox" disabled={busy} checked={retryConfirmed} onChange={event => setRetryConfirmed(event.target.checked)}/>已核对暂未登记，只沿用原编号和相同内容重新确认。</label><Button disabled={busy || !retryConfirmed} onClick={() => { if (pending.current && retryConfirmed) void dispatch(pending.current); }}>沿用原编号确认操作</Button></>}</section>}
    <div className={`mas-layout ${studio.jobs.length ? 'has-job' : ''}`}><div className="mas-create">
      <details className="mas-brand" open={studio.profile.revision === 0 || undefined}><summary><span><b>01</b>商家品牌模板</span><small>{studio.profile.revision ? `${assetPresets.find(value => value.value === studio.profile.preset)?.label} · 已保存` : '首次制作前先确认'}</small></summary><div className="mas-brand-fields"><div className={`mas-brand-swatch ${profile.preset}`} style={{ '--mas-brand': profile.primary_color, '--mas-accent': profile.accent_color } as CSSProperties}><span>品牌版式示意</span><strong>{profile.brand_name || studio.customer_name}</strong><i/><small>{profile.footer || '统一配色 · 统一信息层级'}</small></div><label>版式风格<NativeSelect aria-label="商家版式风格" value={profile.preset} disabled={blocked || !studio.capabilities.can_edit} onChange={value => setProfile(previous => previous ? { ...previous, preset: value as AssetProfile['preset'] } : previous)} options={assetPresets}/></label><label>品牌名称<Input aria-label="商家品牌名称" maxLength={60} disabled={blocked || !studio.capabilities.can_edit} value={profile.brand_name} onChange={event => setProfile(previous => previous ? { ...previous, brand_name: event.target.value } : previous)}/></label><div className="mas-colors"><label>主色<input aria-label="商家品牌主色" type="color" value={profile.primary_color} disabled={blocked || !studio.capabilities.can_edit} onChange={event => setProfile(previous => previous ? { ...previous, primary_color: event.target.value } : previous)}/></label><label>点缀色<input aria-label="商家品牌点缀色" type="color" value={profile.accent_color} disabled={blocked || !studio.capabilities.can_edit} onChange={event => setProfile(previous => previous ? { ...previous, accent_color: event.target.value } : previous)}/></label></div><label>页脚信息<Input aria-label="商家海报页脚" maxLength={120} disabled={blocked || !studio.capabilities.can_edit} value={profile.footer} onChange={event => setProfile(previous => previous ? { ...previous, footer: event.target.value } : previous)} placeholder="填写已确认的门店名称、地址或电话"/></label><p className="mas-help">仅使用你确认的真实信息，不生成未经确认的优惠、价格或经营承诺。</p>{!assetProfileReadable(profile) && <p className="mas-warning">主色过浅，文字与版式背景不够清楚。请选择更深的主色再保存。</p>}<Button disabled={blocked || !studio.capabilities.can_edit || !profile.brand_name.trim() || !assetProfileReadable(profile) || !profileDirty && studio.profile.revision > 0} onClick={saveProfile}>保存本商家品牌模板</Button></div></details>
      <section className="mas-recipe"><header><span className="mas-step">02</span><div><h3>选择制作方式与真实照片</h3><p>使用当前商家的固定图片；原文件和现有月度清单保持原样。</p></div></header><div className="mas-kinds">{(['poster', 'collage', 'enhance', 'video'] as AssetKind[]).map(kind => { const Icon = kind === 'poster' ? ImagePlus : kind === 'collage' ? Layers3 : kind === 'enhance' ? Sparkles : Video; return <button type="button" aria-pressed={form.kind === kind} disabled={blocked || !studio.capabilities[kind] || !studio.capabilities.can_create} key={kind} onClick={() => updateForm({ ...emptyRecipe(), kind, format: kind === 'enhance' ? 'original' : 'square' })}><Icon/><strong>{assetKindLabels[kind]}</strong><small>{kind === 'poster' ? '单张照片＋品牌信息' : kind === 'collage' ? '2—4张真实照片' : kind === 'enhance' ? '亮度、色彩与清晰度' : studio.capabilities.video ? '照片轮播短片 · 无声' : '当前环境尚未开放'}</small></button>; })}</div>{studio.capabilities.video && <p className="mas-help">短视频使用2—6张真实照片，每张3秒依次展示，无配乐、无动态生成；保存后仍需单独审核平台发布。</p>}{!studio.capabilities.video && <p className="mas-help">短视频：{studio.capabilities.video_reason || '制作引擎尚未完成验证，当前不可创建。'}</p>}
        {profileDirty && <p className="mas-warning">品牌信息尚未保存，请先保存模板，再制作新成品。</p>}
        <div className="mas-source-heading"><label>筛选本商家照片<Input aria-label="搜索本商家制作照片" value={search} onChange={event => setSearch(event.target.value)} placeholder="搜索素材名称"/></label><span>已选 {form.image_ids.length} / {maximum} 张</span></div>
        {studio.sources.length === 0 ? <div className="mas-source-empty">暂无可用的固定图片。请先在本商家“团队素材”上传真实照片并准备固定版本。</div> : <div className="mas-source-list">{filteredSources.map(source => <label key={source.image_id} className={form.image_ids.includes(source.image_id) ? 'selected' : ''}><input type="checkbox" disabled={blocked || !studio.capabilities.can_create || !form.image_ids.includes(source.image_id) && maximum > 1 && form.image_ids.length >= maximum} checked={form.image_ids.includes(source.image_id)} onChange={() => toggleSource(source)}/><span><strong>{source.title}</strong><small>{source.width}×{source.height} · {source.width < 720 || source.height < 720 ? '原图较小，成品可能模糊' : '固定真实图片'}</small></span>{form.image_ids.includes(source.image_id) && <b>图{form.image_ids.indexOf(source.image_id) + 1}</b>}</label>)}{!filteredSources.length && <p className="mas-help">没有匹配的照片名称。</p>}</div>}
        {selectedSources.length > 0 && <details className="mas-originals" open><summary>核对本次原图 · {selectedSources.length}张</summary><div>{selectedSources.map((source, index) => <AssetPrivatePreview key={`${source.image_id}:${previewEpoch}`} scope={`${identity}:source:${previewEpoch}`} source={source} label={`原图${index + 1} · ${source.title}`} onReady={ready => previewState(`source:${source.image_id}:${source.image_sha256}`, previewEpoch, ready)}/>)}</div></details>}
        <div className="mas-fields">{form.kind === 'enhance' ? <p className="mas-help">保留原图尺寸与比例，仅调整亮度、色彩和锐度；不裁切、不放大、不清理背景。</p> : <label>输出尺寸<NativeSelect aria-label="制作输出尺寸" value={form.format} disabled={blocked || !studio.capabilities.can_create} onChange={value => updateForm({ format: value as AssetFormat })} options={[{ value: 'square', label: '方形 · 1080×1080' }, { value: 'portrait', label: '竖版 · 1080×1350' }, { value: 'landscape', label: '横版 · 1200×900' }]}/></label>}{form.kind !== 'enhance' && <>{!!studio.copy_suggestions?.length && <label>复用现有内容<NativeSelect aria-label="复用本商家已有文案" value="" disabled={blocked || !studio.capabilities.can_create} onChange={value => { const suggestion = studio.copy_suggestions?.[Number(value)]; if (value !== '' && suggestion) updateForm({ title: suggestion.title, subtitle: suggestion.subtitle }); }} options={[{ value: '', label: '可选：选择已有内容标题，不必从零填写' }, ...studio.copy_suggestions.map((suggestion, index) => ({ value: String(index), label: suggestion.title }))]}/><span className="mas-help">仅复用本商家的现有内容草稿，采用前请核对。</span></label>}<label>主标题<Input aria-label="素材制作主标题" maxLength={80} value={form.title} disabled={blocked || !studio.capabilities.can_create} onChange={event => updateForm({ title: event.target.value })} placeholder="使用已确认的产品名称或本次主题"/></label><label>补充说明<Textarea aria-label="素材制作补充说明" rows={2} maxLength={160} value={form.subtitle} disabled={blocked || !studio.capabilities.can_create} onChange={event => updateForm({ subtitle: event.target.value })} placeholder="仅填写确认过的卖点；留空不会自动编造"/></label></>}{form.kind === 'enhance' && <div className="mas-adjustments">{([{ key: 'exposure', label: '亮度', min: -.2, max: .2, step: .05 }, { key: 'color', label: '色彩', min: .8, max: 1.2, step: .05 }, { key: 'sharpness', label: '清晰度', min: .8, max: 1.2, step: .05 }] as const).map(control => <label key={control.key}>{control.label}<span>{form[control.key].toFixed(2)}</span><input aria-label={`照片优化${control.label}`} type="range" min={control.min} max={control.max} step={control.step} value={form[control.key]} disabled={blocked || !studio.capabilities.can_create} onChange={event => updateForm({ [control.key]: Number(event.target.value) })}/></label>)}</div>}</div>
        {lowSources.length > 0 && <p className="mas-warning">有{lowSources.length}张原图较小。模板排版和轻度优化无法还原不存在的细节；建议补充清晰原图。不会生成虚构菜品或门店细节。</p>}
        <footer className="mas-make"><label className="mas-check"><input type="checkbox" checked={rightsConfirmed} disabled={blocked || !selectionValid || !sourceProofReady || !studio.capabilities.can_create} onChange={event => setRightsConfirmed(event.target.checked)}/>我已核对本商家真实照片及使用依据、文字信息和原图清晰度；仅创建私有制作任务，成品仍需审核。</label><Button disabled={!canCreate} onClick={create}><Sparkles/>{busy ? '正在登记…' : '开始私有制作'}</Button><p>{minimum === maximum ? `本方式需要${minimum}张照片。` : `本方式需要${minimum}—${maximum}张照片。`}不会自动审核、排期或发布。</p></footer>
      </section>
    </div><aside className="mas-results"><section className="mas-jobs"><header><div><span className="mas-step">03</span><h3>制作记录与成品</h3></div><span>{studio.jobs.length}项</span></header>{!studio.jobs.length ? <div className="mas-result-empty"><Palette/><strong>从一份真实素材开始</strong><p>左侧确认制作后，这里显示进度和实际成品。没有任务时不会预生成或调用服务。</p></div> : <div className="mas-job-list">{studio.jobs.map(row => <button type="button" key={row.id} className={job?.id === row.id ? 'selected' : ''} disabled={busy || unknown} onClick={() => { setSelectedJob(row.id); setAdoptConfirmed(false); setAdoptTitle(`${assetKindLabels[row.kind]} · ${row.recipe.title || studio.customer_name}`.slice(0, 120)); resetProof(); }}><span><strong>{row.recipe.title || assetKindLabels[row.kind]}</strong><small>{assetKindLabels[row.kind]} · {shortTime(row.created_at)}</small></span><b className={`mas-state ${row.status}`}>{assetStatusLabels[row.status]}</b><ChevronRight/></button>)}</div>}</section>
      {job && <section className="mas-result"><header><div><span className="mas-eyebrow">本商家私有成品</span><h3>{job.recipe.title || assetKindLabels[job.kind]}</h3></div><Button variant="ghost" disabled={busy || unknown} onClick={() => { setPollStopped(false); void readJob(job.id); }} aria-label="刷新当前制作任务"><RefreshCw/></Button></header><p className={`mas-job-message ${job.status}`} role="status">{['queued', 'processing'].includes(job.status) && <Loader2 className="animate-spin"/>}{assetStatusLabels[job.status]}<span>{job.message}</span></p>{pollStopped && <p className="mas-help">自动查询已暂停，后台任务不会因此重复创建。稍后点击刷新查看原任务结果。</p>}{job.source_stale && <p className="mas-warning">原图、品牌或商家状态已变化。这份历史成品不能直接保存采用，请重新核对来源后制作。</p>}
        {job.output && <AssetPrivatePreview key={`${job.id}:${job.output.sha256}:${previewEpoch}`} scope={`${identity}:output:${job.id}:${job.revision}:${previewEpoch}`} output={job.output} label={job.kind === 'video' ? '核对实际私有视频' : '核对实际制作成品'} onReady={ready => previewState(outputKey, previewEpoch, ready)}/>}
        {job.sources.length > 0 && <details className="mas-originals"><summary>对照本任务原图 · {job.sources.length}张</summary><div>{job.sources.map((source, index) => <AssetPrivatePreview key={`${job.id}:${source.image_id}`} scope={`${identity}:job-original:${job.id}`} source={source} label={`任务原图${index + 1} · ${source.title}`}/>)}</div></details>}
        {job.status === 'failed' && job.can_retry && <Button variant="outline" disabled={blocked || job.source_stale || !studio.capabilities.can_create} onClick={retryJob}>重新制作此任务</Button>}
        {job.status === 'unknown' && <p className="mas-warning">制作进程结果尚未确认，请刷新原任务核对。此处不会自动重做或自动保存素材。</p>}
        {job.adoption ? <div className="mas-adopted"><CheckCircle2/><strong>已保存为新团队素材</strong><p>素材 #{job.adoption.material_id} · 待内容审核。{job.kind === 'video' ? '视频仅进入素材库，不作为Google固定图片。' : '固定图片可在后续任务或月度清单中另行选择。'}原图及已审核清单没有被替换。</p></div> : job.output && job.status === 'succeeded' && <div className="mas-adopt"><label>新素材名称<Input aria-label="制作成品新素材名称" value={adoptTitle} maxLength={120} disabled={blocked || !job.can_adopt} onChange={event => { setAdoptTitle(event.target.value); setAdoptConfirmed(false); }}/></label><label className="mas-check"><input type="checkbox" checked={adoptConfirmed} disabled={blocked || !job.can_adopt || !previewReady[outputKey] || !studio.capabilities.can_adopt} onChange={event => setAdoptConfirmed(event.target.checked)}/>我已核对实际成品和原图，确认另存为本商家的新团队素材；仍待内容审核，不替换任何已有任务、图片或排期。</label><Button disabled={blocked || !job.can_adopt || !previewReady[outputKey] || !studio.capabilities.can_adopt || !adoptConfirmed || !adoptTitle.trim()} onClick={adopt}><ShieldCheck/>保存为新团队素材</Button></div>}
        <details className="mas-receipt"><summary>查看制作记录</summary><dl><dt>任务</dt><dd>{job.id} · 版本{job.revision}</dd><dt>模板版本</dt><dd>{job.profile_revision}</dd><dt>最后更新</dt><dd>{shortTime(job.updated_at)}</dd>{job.error_code && <><dt>状态说明</dt><dd>{job.error_code}</dd></>}</dl></details>
      </section>}
    </aside></div>
  </section>;
}

/** Authenticated bytes are hash-checked before a local data/image or video URL is shown. */
export function AssetPrivatePreview({ scope, source, output, label, onReady }: { scope: string; source?: AssetSource; output?: AssetOutput; label: string; onReady?: (ready: boolean) => void }) {
  const descriptor = source || output, identity = `${scope}:${descriptor?.preview_path}:${source?.image_sha256 || output?.sha256}:${descriptor?.byte_size}`;
  const identityRef = useRef(identity);
  const listener = useRef(onReady); listener.current = onReady;
  const [view, setView] = useState<{ identity: string; url: string; blob: Blob; video: boolean } | null>(null), [error, setError] = useState(''), [ready, setReady] = useState(false), [retry, setRetry] = useState(0);
  const previewIdentity = `${identity}:retry:${retry}`; identityRef.current = previewIdentity;
  useEffect(() => {
    let active = true, videoUrl = ''; const controller = new AbortController();
    identityRef.current = previewIdentity;
    const current = () => active && !controller.signal.aborted && identityRef.current === previewIdentity;
    setView(null); setError(''); setReady(false); listener.current?.(false);
    void (async () => {
      try {
        if (!descriptor) throw new Error('缺少私有成品资料。');
        const result = await assetStudioPreview(descriptor, controller.signal); if (!current()) return;
        if (!result.pngUrl) videoUrl = URL.createObjectURL(result.blob);
        setView({ identity: previewIdentity, url: result.pngUrl || videoUrl, blob: result.blob, video: !result.pngUrl });
      } catch (cause) { if (current()) { setError(mediaError(cause, cause instanceof Error ? cause.message : '私有预览暂时无法读取。')); listener.current?.(false); } }
    })();
    return () => { active = false; controller.abort(); if (identityRef.current === previewIdentity) identityRef.current = ''; if (videoUrl) URL.revokeObjectURL(videoUrl); };
    // Hash, scope and path form the immutable private-preview identity.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [identity, retry]);
  const display = view?.identity === previewIdentity ? view : null;
  function loaded() { if (identityRef.current === previewIdentity && display) { setReady(true); listener.current?.(true); } }
  function failed() { if (identityRef.current === previewIdentity) { setReady(false); setError(display?.video ? '视频无法在当前浏览器播放，请重新读取；未核对完成前不能保存采用。' : '图片无法显示，请重新读取核对。'); listener.current?.(false); } }
  function download() {
    if (!display || !ready || identityRef.current !== previewIdentity) return;
    const url = URL.createObjectURL(display.blob), anchor = document.createElement('a'); anchor.href = url; anchor.download = `merchant-asset.${display.video ? 'mp4' : 'png'}`; document.body.appendChild(anchor); anchor.click(); anchor.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  return <figure className="mas-private-preview"><figcaption><strong>{label}</strong><span>{descriptor?.width}×{descriptor?.height}{output?.duration_seconds ? ` · ${output.duration_seconds}秒` : ''} · 私有核对</span></figcaption>{!display && !error && <p role="status"><Loader2 className="animate-spin"/>正在读取并核对固定内容…</p>}{display && (display.video ? <video controls playsInline preload="metadata" src={display.url} onLoadedData={loaded} onError={failed} aria-label={label}/> : <img src={display.url} alt={label} referrerPolicy="no-referrer" onLoad={loaded} onError={failed}/>)}{error && <p className="mas-error" role="alert">{error}<Button variant="outline" onClick={() => setRetry(value => value + 1)}>重新读取私有预览</Button></p>}{display && ready && output && <Button variant="outline" onClick={download}><Download/>下载已核对成品</Button>}</figure>;
}
