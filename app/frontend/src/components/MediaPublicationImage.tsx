import { useEffect, useRef, useState } from 'react';
import { CheckCircle2, ImagePlus, Loader2, RefreshCw, ShieldCheck } from 'lucide-react';
import { invokeWithAuth } from '@/lib/tokenStore';
import { mediaError, mediaErrorStatus, mediaRequestId } from '@/lib/media-operations-api';
import { imagePreviewPath, imageRequestScope, prepareBrowserImage, publicationImages, publicationRights, verifiedPreviewBlob, verifiedPublicationImage, type PublicationImage, type PublicationImageList } from '@/lib/media-publication-images';
import { useHardNavigationBlock, useUnsavedChanges } from '@/lib/use-unsaved-changes';
import { Button } from './ui/button';
import { NativeSelect } from './ui/native-select';
import './media-publication-image.css';

type PreviewState = 'loading' | 'ready' | 'failed';
const pendingResult = (error: unknown) => !mediaErrorStatus(error) || [408,429].includes(mediaErrorStatus(error) || 0) || (mediaErrorStatus(error) || 0) >= 500;
const imageStatus = { ready: '固定图片版本', revoked: '已撤销使用', source_changed: '原素材已变化' };
const rightsLabel = (value: string) => publicationRights.find(row => row.value === value)?.label || '使用权待核对';
const formatBytes = (value: number) => value >= 1024 * 1024 ? `${(value / 1024 / 1024).toFixed(1)} MB` : `${Math.round(value / 1024)} KB`;

type ImageDeliveryPolicy = { enabled: boolean; can_manage: boolean; notice: string };
export function MediaImageDeliveryPolicy({customerId, scope = '', onChanged}: {customerId: number; scope?: string; onChanged?: () => void}) {
  const identity = `${scope}:${customerId}`, fence = useRef(imageRequestScope(identity)); fence.current.update(identity);
  const [resolvedIdentity,setResolvedIdentity] = useState(identity);
  const [policy,setPolicy] = useState<ImageDeliveryPolicy|null>(null),[loading,setLoading] = useState(true),[busy,setBusy] = useState(false),[uncertain,setUncertain] = useState(false),[confirmed,setConfirmed] = useState(false),[error,setError] = useState('');
  const seq = useRef(0),busyRef = useRef(false);
  const hold = useHardNavigationBlock(busy||uncertain);
  async function read(recover = false) {
    const current=fence.current.capture(),request = ++seq.current;setLoading(true);setError('');
    try { const response=await invokeWithAuth({url:'/api/v1/media-publication-images/delivery-policy',method:'GET',data:{customer_id:customerId}});if(!current()||request!==seq.current)return;const data=response.data as ImageDeliveryPolicy;if(!data||typeof data.enabled!=='boolean'||typeof data.can_manage!=='boolean'||typeof data.notice!=='string')throw new Error('图片投递设置返回不完整。');setPolicy(data);if(recover){setUncertain(false);setConfirmed(false);hold.release();onChanged?.();} }
    catch(cause){if(current()&&request===seq.current)setError(mediaError(cause,cause instanceof Error?cause.message:'图片投递设置暂时无法读取。'));}
    finally{if(current()&&request===seq.current)setLoading(false);}
  }
  useEffect(()=>{fence.current.activate();setResolvedIdentity(identity);setPolicy(null);setConfirmed(false);setBusy(false);setUncertain(false);setError('');busyRef.current=false;hold.release();void read();return()=>{fence.current.invalidate();seq.current++;};},[identity]);
  async function save() {
    if(!policy?.can_manage||!confirmed||busyRef.current||uncertain||resolvedIdentity!==identity)return;
    const current=fence.current.capture(),target=!policy.enabled;busyRef.current=true;setBusy(true);setError('');hold.lock();
    try { const response=await invokeWithAuth({url:'/api/v1/media-publication-images/delivery-policy',method:'POST',data:{enabled:target,public_delivery_confirmed:true}});if(!current())return;const value=response.data as ImageDeliveryPolicy;if(!value||value.enabled!==target||typeof value.can_manage!=='boolean'||typeof value.notice!=='string')throw new Error('投递设置保存结果待确认');setPolicy(value);setConfirmed(false);hold.release();onChanged?.(); }
    catch(cause){if(current()){if(pendingResult(cause)){setUncertain(true);setError('设置保存结果待确认。请读取当前设置后再操作。');}else{hold.release();setError(mediaError(cause,'设置尚未保存，请核对后重试。'));}}}
    finally{if(current()){busyRef.current=false;setBusy(false);}}
  }
  if(resolvedIdentity!==identity||loading&&!policy)return <p className="mpi-help" role="status">正在核对发布图片投递状态…</p>;
  return <section className="mpi-policy" aria-label="发布图片投递设置"><strong><ShieldCheck size={15}/> {policy?.enabled?'发布图片投递已启用':'发布图片投递尚未启用'}</strong><p>{policy?.notice||'设置暂未读取，固定图片仍按私有素材处理。'}</p><p>此设置作用于当前 Google 连接所属老板账号。启用不会公开现有素材；仅本账号下经过审核、并明确提交发布的固定副本可在投递有效期内读取。</p>{error&&<p className="mpi-notice warning" role="alert">{error}</p>}{uncertain?<Button variant="outline" disabled={busy||loading} onClick={()=>void read(true)}>读取当前设置并核对</Button>:policy?.can_manage?<><label className="mpi-check"><input type="checkbox" checked={confirmed} disabled={busy||loading} onChange={event=>setConfirmed(event.target.checked)}/>{policy.enabled?'我确认暂停本老板账号的图片投递；可能影响 Google 尚未完成抓取的图片。已公开帖子须在平台单独处理。':'我确认允许 Google 在本账号经审核并明确提交发布时，获取对应固定图片副本；持有投递地址者在有效期内也可能读取。原文件仍保持私有。'}</label><div className="mpi-actions"><Button variant="outline" disabled={busy||loading} onClick={()=>void read()}>刷新设置</Button><Button disabled={busy||loading||!confirmed} onClick={()=>void save()}>{busy?'正在保存…':policy.enabled?'确认暂停图片投递':'确认启用图片投递'}</Button></div></>:<p>只有此 Google 连接所属老板可以调整投递设置。</p>}</section>;
}

/** Authenticated, hash-verified preview. No credential or delivery URL enters img.src. */
export function PublicationImagePreview({ image, scope = '', title = '审核使用的最终配图', onStateChange }: { image: PublicationImage; scope?: string; title?: string; onStateChange?: (state: PreviewState) => void }) {
  const identity = `${scope}:${image?.id}:${image?.image_sha256}:${image?.byte_size}:${image?.preview_path}`, fence=useRef(imageRequestScope(identity));fence.current.update(identity);
  const [resolvedPreview,setResolvedPreview]=useState(identity);
  const [view,setView]=useState<{url:string;identity:string;current:()=>boolean}|null>(null), [state, setState] = useState<PreviewState>('loading'), [error, setError] = useState(''), [retry, setRetry] = useState(0);
  const listener = useRef(onStateChange); listener.current = onStateChange;
  useEffect(() => {
    fence.current.activate();setResolvedPreview(identity);const current=fence.current.capture();let currentUrl = '';
    const publish = (next: PreviewState) => { if (current()) { setState(next); listener.current?.(next); } };
    setView(null); setError(''); publish('loading');
    void (async () => {
      try {
        verifiedPublicationImage(image);
        if (!imagePreviewPath(image.preview_path, image.id)) throw new Error('图片预览路径无法核实。');
        const response = await invokeWithAuth({url: image.preview_path, method: 'GET', options: {responseType: 'blob'}});
        if (!current()) return;
        const blob = await verifiedPreviewBlob(image, response.data);
        if (!current()) return;
        currentUrl = URL.createObjectURL(blob); setView({url:currentUrl,identity,current});
      } catch (cause) { if (current()) { setError(mediaError(cause, cause instanceof Error ? cause.message : '图片暂时无法核对，请重试。')); publish('failed'); } }
    })();
    return () => { fence.current.invalidate(); if (currentUrl) URL.revokeObjectURL(currentUrl); };
  }, [identity, retry]);
  const display=view&&view.identity===identity&&view.current()?view:null;
  const displayState=resolvedPreview!==identity?'loading':state;
  try { verifiedPublicationImage(image); } catch { return <p className="mpi-notice warning" role="alert">图片版本资料不完整，请重新读取任务后核对。</p>; }
  return <figure className="mpi-preview" aria-label={title}>{displayState === 'loading' && <div className="mpi-preview-loading" role="status"><Loader2 className="animate-spin" size={18}/>正在读取并核对最终配图…</div>}{display && <img key={display.url} src={display.url} alt={title} referrerPolicy="no-referrer" onLoad={() => { if(display.current()){setState('ready'); listener.current?.('ready');} }} onError={() => { if(display.current()){setView(null); setError('图片无法显示，请重新读取最终版本。'); setState('failed'); listener.current?.('failed');} }}/>} {displayState === 'failed' && <div className="mpi-notice" role="alert">{error}<Button variant="outline" size="sm" onClick={() => setRetry(value => value + 1)}>重新读取配图</Button></div>}<figcaption><strong>{title}</strong><span>{image.width} × {image.height} · {formatBytes(image.byte_size)} · {rightsLabel(image.rights_basis)}</span><small>版本 {image.id.slice(0,8)} · 指纹 {image.image_sha256.slice(0,12)} · 此处为授权后读取的私有预览</small></figcaption></figure>;
}

type Candidate = { file: Blob; sourceSha256: string; width: number; height: number; preview: string };
type PendingPrepare = { id: string; candidate: Candidate; rights: string };
type Props = { customerId: number; materialId: number; value: string; onChange: (value: string) => void; canPrepare: boolean; scope: string; onHoldChange?: (active: boolean) => void; onChanged?: () => void; onDraftChange?: (active: boolean) => void; disabled?: boolean };
export default function MediaPublicationImage({ customerId, materialId, value, onChange, canPrepare, scope, onHoldChange, onChanged, onDraftChange, disabled = false }: Props) {
  const identity=`${scope}:${customerId}:${materialId}`,fence=useRef(imageRequestScope(identity));fence.current.update(identity);
  const [resolvedIdentity,setResolvedIdentity]=useState(identity);
  const [list, setList] = useState<PublicationImageList | null>(null), [loading, setLoading] = useState(true), [error, setError] = useState(''), [notice, setNotice] = useState('');
  const [candidate, setCandidate] = useState<Candidate | null>(null), [rights, setRights] = useState(''), [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false), [unknown, setUnknown] = useState(false), [notFound, setNotFound] = useState(false), [revokeConfirmed, setRevokeConfirmed] = useState(false);
  const busyRef = useRef(false), sequence = useRef(0), candidateRef = useRef<Candidate | null>(null), pending = useRef<PendingPrepare | null>(null);
  const holdListener = useRef(onHoldChange); holdListener.current = onHoldChange;
  const draftListener = useRef(onDraftChange); draftListener.current = onDraftChange;
  const guard = useUnsavedChanges(Boolean(candidate)), hold = useHardNavigationBlock(busy || unknown);
  const selected = list?.items.find(row => row.id === value);
  const canMake = canPrepare && !disabled && list?.can_prepare === true;
  const blocked = busy || unknown || disabled;
  function clearCandidate() { if (candidateRef.current) URL.revokeObjectURL(candidateRef.current.preview); candidateRef.current = null; setCandidate(null); setRights(''); setConfirmed(false); guard.markSaved(); }
  async function load() {
    const current=fence.current.capture(),seq = ++sequence.current; setLoading(true); setError('');
    try { const data = await publicationImages(customerId, materialId); if (current() && seq === sequence.current) setList(data); }
    catch (cause) { if (current() && seq === sequence.current) { setList(null); setError(mediaError(cause, cause instanceof Error ? cause.message : undefined)); } }
    finally { if (current() && seq === sequence.current) setLoading(false); }
  }
  useEffect(() => {
    fence.current.activate();setResolvedIdentity(identity);setList(null);setCandidate(null);setRights('');setConfirmed(false);setBusy(false);setUnknown(false);setNotFound(false);setRevokeConfirmed(false);setError('');setNotice('');pending.current=null;busyRef.current=false;candidateRef.current=null;guard.markSaved();hold.release();void load();
    return () => { fence.current.invalidate();sequence.current++;if(candidateRef.current)URL.revokeObjectURL(candidateRef.current.preview);candidateRef.current=null;holdListener.current?.(false);draftListener.current?.(false); };
  }, [identity]);
  useEffect(() => { holdListener.current?.(blocked); return () => holdListener.current?.(false); }, [blocked]);
  useEffect(() => { draftListener.current?.(Boolean(candidate)); return () => draftListener.current?.(false); }, [candidate]);
  async function readSource() {
    if (!canMake || busyRef.current || unknown) return;
    const current=fence.current.capture();busyRef.current = true; setBusy(true); setError(''); setNotice(''); hold.lock();
    try {
      const response = await invokeWithAuth({url: `/api/v1/entities/customer_materials/${materialId}/download`, method: 'GET', options: {responseType: 'blob'}});
      if(!current())return;
      if (!(response.data instanceof Blob)) throw new Error('原图片返回不完整，请重新读取素材。');
      const result = await prepareBrowserImage(response.data);
      if (!current()) return;
      clearCandidate(); const next = { ...result, preview: URL.createObjectURL(result.file) }; candidateRef.current = next; setCandidate(next);
    } catch (cause) { if (current()) setError(mediaError(cause, cause instanceof Error ? cause.message : '图片准备失败，请核对原文件。')); }
    finally { if (current()) { busyRef.current = false; setBusy(false); hold.release(); } }
  }
  function accept(image: PublicationImage) {
    verifiedPublicationImage(image, customerId, materialId);
    setList(current => ({items: [image, ...(current?.items || []).filter(row => row.id !== image.id)], can_prepare: current?.can_prepare === true, delivery_available: current?.delivery_available === true}));
    onChange(image.id); clearCandidate(); pending.current = null; setUnknown(false); setNotFound(false); hold.release(); setNotice('固定图片版本已保存。请核对下方服务器返回的最终配图，再提交任务审核。'); onChanged?.();
  }
  async function save(request?: PendingPrepare) {
    if (!canMake || busyRef.current || unknown && !request) return;
    if (!request && (!candidate || !rights || !confirmed)) { setError('请选择图片使用权依据，并确认本次公开使用。'); return; }
    const selectedRequest = request || {id: mediaRequestId(), candidate: candidate!, rights};
    const current=fence.current.capture();pending.current = selectedRequest; busyRef.current = true; setBusy(true); setError(''); setNotice(''); hold.lock();
    try {
      const body = new FormData(); body.append('customer_id', String(customerId)); body.append('material_id', String(materialId)); body.append('source_sha256', selectedRequest.candidate.sourceSha256); body.append('rights_basis', selectedRequest.rights); body.append('rights_confirmed','true'); body.append('request_id',selectedRequest.id); body.append('file',selectedRequest.candidate.file,'publication.png');
      const response = await invokeWithAuth({url:'/api/v1/media-publication-images/prepare',method:'POST',data:body,options:{headers:{'Content-Type':'multipart/form-data'}}});
      if (current()) accept(response.data);
    } catch (cause) {
      if (!current()) return;
      if (pendingResult(cause)) { setUnknown(true); setNotFound(false); setError('图片保存结果待确认。请查询原保存结果，系统会保留原请求编号，避免重复生成。'); }
      else { pending.current = null; setUnknown(false); hold.release(); setError(mediaError(cause, cause instanceof Error ? cause.message : '图片尚未保存。')); }
    } finally { if (current()) { busyRef.current = false; setBusy(false); } }
  }
  async function recover() {
    if (!pending.current || busyRef.current) return;
    const current=fence.current.capture(),request=pending.current;busyRef.current = true; setBusy(true); setError(''); setNotFound(false);
    try {
      const response = await invokeWithAuth({url:`/api/v1/media-publication-images/requests/${request.id}`,method:'GET'});
      if (current()) accept(response.data);
    } catch (cause) { if (current()) { if (mediaErrorStatus(cause) === 404) { setNotFound(true); setError('未找到原请求的固定图片版本。可沿用原编号重新确认保存，不会创建第二份同编号记录。'); } else setError(mediaError(cause,'暂时无法确认原保存结果，请稍后再查询。')); } }
    finally { if (current()) { busyRef.current = false; setBusy(false); } }
  }
  async function revoke() {
    if (!selected?.can_revoke || !revokeConfirmed || busyRef.current || unknown || disabled) return;
    const current=fence.current.capture();busyRef.current = true; setBusy(true); setError(''); hold.lock();
    try {
      const response = await invokeWithAuth({url:`/api/v1/media-publication-images/${selected.id}/revoke`,method:'POST',data:{}});
      const image = verifiedPublicationImage(response.data, customerId, materialId);
      if (current()) { setList(current => current ? {...current,items:current.items.map(row=>row.id===image.id?image:row)} : current); setRevokeConfirmed(false); setNotice('已撤销此图片版本的后续使用。历史操作记录保留，平台已经公开的帖子请单独处理。'); onChanged?.(); }
    } catch (cause) { if (current()) { setError(mediaError(cause,'撤销结果尚未确认，请刷新图片列表核对状态后再操作。')); await load(); } }
    finally { if (current()) { busyRef.current = false; setBusy(false); hold.release(); } }
  }
  if(resolvedIdentity!==identity)return <p className="mpi-help" role="status">正在确认当前客户与素材范围…</p>;
  return <section className="mpi-panel" aria-label="Google 固定发布图片"><header><div><ImagePlus size={18}/><h3>Google 发布配图</h3></div><Button variant="ghost" size="sm" onClick={()=>void load()} disabled={loading || blocked} aria-label="刷新发布图片版本"><RefreshCw size={15} className={loading?'animate-spin':''}/></Button></header><p className="mpi-help">原文件保持私有。先准备单张固定图片，经老板审核及明确发布后才可供 Google 获取。</p>{error && <div className="mpi-notice warning" role="alert">{error}</div>}{notice && <div className="mpi-notice" role="status">{notice}</div>}{loading ? <p className="mpi-help" role="status"><Loader2 size={15} className="animate-spin"/>正在核对素材与图片版本…</p> : list && <><label>本任务使用的图片版本<NativeSelect aria-label="Google 固定图片版本" value={value} onChange={next=>{onChange(next);setRevokeConfirmed(false);}} disabled={blocked} options={[{value:'',label:'不使用固定版本（保留原素材方式）'},...list.items.map(row=>({value:row.id,label:`${imageStatus[row.status]} · ${row.width}×${row.height} · ${row.id.slice(0,8)}`}))]}/></label>{value && !selected && <p className="mpi-notice warning">当前图片版本已不可用，请重新选择并保存草稿。</p>}{selected && <><PublicationImagePreview image={selected} scope={scope}/>{selected.status !== 'ready' && <p className="mpi-notice warning">此图片版本{imageStatus[selected.status]}，不能继续发布。请准备新版本并重新审核。</p>}{selected.can_revoke && selected.status==='ready' && <details className="mpi-revoke"><summary>撤销此版本</summary><label className="mpi-check"><input type="checkbox" checked={revokeConfirmed} disabled={blocked} onChange={event=>setRevokeConfirmed(event.target.checked)}/>确认阻止此固定图片版本的后续发布和图片投递</label><Button variant="outline" disabled={blocked||!revokeConfirmed} onClick={()=>void revoke()}>确认撤销版本</Button></details>}</>}{!list.delivery_available && <p className="mpi-notice"><ShieldCheck size={16}/>固定图片可准备和审核；图片公开投递尚未由老板启用，自动配图发布会暂停在检查阶段。</p>}{canMake && !candidate && !unknown && <Button variant="outline" onClick={()=>void readSource()} disabled={busy}><ImagePlus size={16}/>{busy?'正在准备…':'读取原图并准备新版本'}</Button>}{candidate && <div className="mpi-candidate"><strong>待保存的配图预览</strong><img src={candidate.preview} alt="本次待保存的配图预览"/><p>{candidate.width} × {candidate.height} · 保留原比例，不自动裁切；图片元数据将在固定版本中移除。</p><label>公开使用依据<NativeSelect aria-label="发布图片使用权依据" value={rights} onChange={next=>{setRights(next);setConfirmed(false);}} disabled={blocked} options={[{value:'',label:'请选择并核实使用权'},...publicationRights]}/></label><label className="mpi-check"><input type="checkbox" checked={confirmed} disabled={blocked} onChange={event=>setConfirmed(event.target.checked)}/><span>我确认这张图片可用于该客户的公开宣传。老板审核及发布确认后，Google 可读取固定副本；持有投递地址的人在有效期内也可能读取。原文件不会公开。</span></label><div className="mpi-actions"><Button variant="outline" disabled={blocked} onClick={clearCandidate}>放弃准备</Button><Button disabled={blocked||!rights||!confirmed} onClick={()=>void save()}><CheckCircle2 size={16}/>保存固定图片版本</Button></div></div>}{unknown && <div className="mpi-actions"><Button variant="outline" disabled={busy} onClick={()=>void recover()}>{busy?'正在查询…':'查询原保存结果'}</Button>{notFound && pending.current && <Button disabled={busy} onClick={()=>void save(pending.current!)}>以原编号重新确认保存</Button>}</div>}{!canMake && <p className="mpi-help">准备新图片需要该客户的素材编辑、交付协作及任务编辑权限。当前可查看已授权版本。</p>}</>}</section>;
}
