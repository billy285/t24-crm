import { mediaProviderScope, mediaScopedBindings } from '@/lib/media-provider-scope';
import { useCallback, useEffect, useRef, useState } from 'react';
import { AlertCircle, CalendarClock, CheckCircle2, Clock3, ExternalLink, FileText, ImagePlus, Loader2, Plus, RefreshCw, Send, ShieldCheck } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { NativeSelect } from '@/components/ui/native-select';
import { Dialog, DialogTitle, DialogDescription, CrmFormDialogBody, CrmFormDialogContent, CrmFormDialogFooter, CrmFormDialogHeader } from '@/components/ui/dialog';
import { invokeWithAuth } from '@/lib/tokenStore';
import { useHardNavigationBlock, useUnsavedChanges } from '@/lib/use-unsaved-changes';
import { mediaError, mediaErrorStatus, mediaLocalToUtc, mediaRequestId, mediaTimezones, mediaUtcToLocal } from '@/lib/media-operations-api';
import { metaPlatformLabel, metaRequestScope, type MetaAuthorization } from '@/lib/meta-business-api';
import { sourceImageDimensions } from '@/lib/media-publication-images';
import { metaOperationsApi, metaOpsActionLabels, metaOpsAuthorizationUrl, metaOpsImageDataUrl, metaOpsPublicUrl, metaOpsScheduleLabels, verifiedMetaOpsAction, verifiedMetaOpsBinding, verifiedMetaOpsComments, verifiedMetaOpsDraft, verifiedMetaOpsMedia, verifiedMetaOpsPosts, verifiedMetaOpsPreview, verifiedMetaOpsSchedule, verifiedMetaOpsStatus, verifiedMetaOpsWorkspace, type MetaOpsAction, type MetaOpsBinding, type MetaOpsComment, type MetaOpsComments, type MetaOpsDraft, type MetaOpsMedia, type MetaOpsPosts, type MetaOpsPreview, type MetaOpsRequest, type MetaOpsSchedule, type MetaOpsStatus, type MetaOpsWorkspace } from '@/lib/meta-operations-api';
import './meta-operations.css';

type Props = { scope: string; isOwner: boolean; refreshKey?: string; customerId?: number; platformFilter?: string };
type Section = 'posts' | 'comments' | 'schedules' | 'history';
type Editor = { title: string; content: string; media_id: string };
type Modal = { kind: 'editor'; draft: MetaOpsDraft | null; replyTo: MetaOpsComment | null } | { kind: 'preview'; preview: MetaOpsPreview } | { kind: 'schedule'; preview: MetaOpsPreview } | { kind: 'action'; action: MetaOpsAction } | { kind: 'cancel'; schedule: MetaOpsSchedule } | { kind: 'activate'; schedule: MetaOpsSchedule } | { kind: 'authorize'; authorization: MetaAuthorization } | { kind: 'pause'; binding: MetaOpsBinding };
type MutationKind = 'draft' | 'media' | 'action' | 'schedule' | 'oauth' | 'binding';
type Pending = { path: string; method: 'POST' | 'PATCH'; data: unknown; requestId: string | null; bindingId: number; kind: MutationKind; accept: (value: unknown) => void; controlActionId?: number };
const sectionLabels: Record<Section, string> = { posts: '内容发布', comments: '评论回复', schedules: '发布排期', history: '操作记录' };
const blankEditor = (): Editor => ({ title: '', content: '', media_id: '' });
const emptyPosts: MetaOpsPosts = { items: [], next_cursor: null };
const emptyComments: MetaOpsComments = { items: [], next_cursor: null };
const uncertain = (cause: unknown) => !mediaErrorStatus(cause) || [408, 429].includes(mediaErrorStatus(cause) || 0) || (mediaErrorStatus(cause) || 0) >= 500;
const formatTime = (value: string | null, zone = 'Asia/Shanghai') => value && Number.isFinite(Date.parse(value)) ? new Intl.DateTimeFormat('zh-CN', { timeZone: zone, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(new Date(value)) : '时间待核对';
const editorFrom = (draft: MetaOpsDraft): Editor => ({ title: draft.title, content: draft.content, media_id: draft.media_id || '' });
const currentAction = (value: unknown, bindingId: number) => verifiedMetaOpsAction(value as MetaOpsAction, bindingId);
function previewConsentLabel(preview: MetaOpsPreview, approved: boolean): string {
  if (preview.draft.kind === 'reply') return approved ? '我已核对客户、平台账号、当前原评论和拟回复，确认以商家身份公开回复。' : '我已核对客户、平台账号、当前原评论和拟回复，确认审核通过此固定版本；本次不公开回复。';
  const content = preview.media ? '正文和固定配图' : '本次纯文字正文';
  return approved ? `我已核对客户、平台账号、${content}，确认将此版本公开发布。` : `我已核对客户、平台账号、${content}，确认审核通过此固定版本；本次不公开发布。`;
}


export function MetaPrivateImage({ image, scope, onReady }: { image: MetaOpsMedia; scope: string; onReady?: (ready: boolean) => void }) {
  const identity = `${scope}:${image.id}:${image.sha256}:${image.byte_size}:${image.width}x${image.height}:${image.preview_path}`, fence = useRef(metaRequestScope(identity)); fence.current.update(identity);
  const [view, setView] = useState<{ identity: string; url: string; current: () => boolean } | null>(null), [error, setError] = useState(''), [retry, setRetry] = useState(0);
  const listener = useRef(onReady); listener.current = onReady;
  useEffect(() => {
    fence.current.activate(); const current = fence.current.capture(); setView(null); setError(''); listener.current?.(false);
    void (async () => {
      try {
        verifiedMetaOpsMedia(image);
        const response = await invokeWithAuth({ url: image.preview_path, method: 'GET', options: { responseType: 'blob' } });
        if (!current()) return;
        const url = await metaOpsImageDataUrl(image, response.data);
        if (current()) setView({ identity, url, current });
      } catch (cause) { if (current()) { setError(mediaError(cause, cause instanceof Error ? cause.message : '图片暂时无法核对。')); listener.current?.(false); } }
    })();
    return () => fence.current.invalidate();
  }, [identity, retry]);
  const display = view && view.identity === identity && view.current() ? view : null;
  return <figure className="mops-image" aria-label="Meta 固定发布图片预览">{display ? <img src={display.url} alt="本次核对的固定发布图片" referrerPolicy="no-referrer" onLoad={() => { if (display.current()) listener.current?.(true); }} onError={() => { if (display.current()) { setView(null); setError('图片无法显示，请重新读取固定版本。'); listener.current?.(false); } }}/> : error ? <p role="alert">{error}<Button variant="outline" size="sm" onClick={() => setRetry(value => value + 1)}>重新读取图片</Button></p> : <p role="status"><Loader2 className="animate-spin"/>正在读取并核对固定图片…</p>}<figcaption>{image.width} × {image.height} · {Math.ceil(image.byte_size / 1024)} KB · 固定版本 {image.id.slice(0, 8)}<small>私有预览 · 内容指纹 {image.sha256.slice(0, 12)}</small></figcaption></figure>;
}

export default function MetaOperationsWorkspace({ scope: identityScope, isOwner, refreshKey = '', customerId, platformFilter }: Props) {
  const scope = mediaProviderScope(identityScope, customerId, platformFilter);
  const identity = `${scope}:${isOwner ? 'owner' : 'staff'}:${refreshKey}`, fence = useRef(metaRequestScope(identity)); fence.current.update(identity);
  const identityRef = useRef(identity), ownerRef = useRef(isOwner); identityRef.current = identity; ownerRef.current = isOwner;
  const [resolvedIdentity, setResolvedIdentity] = useState(identity), [state, setState] = useState<MetaOpsStatus | null>(null), [loading, setLoading] = useState(true), [error, setError] = useState(''), [notice, setNotice] = useState('');
  const [bindingId, setBindingId] = useState(''), [section, setSection] = useState<Section>('posts'), [workspace, setWorkspace] = useState<MetaOpsWorkspace | null>(null), [workspaceLoading, setWorkspaceLoading] = useState(false), [workspaceError, setWorkspaceError] = useState('');
  const [posts, setPosts] = useState<MetaOpsPosts>(emptyPosts), [postsLoading, setPostsLoading] = useState(false), [postRef, setPostRef] = useState(''), [comments, setComments] = useState<MetaOpsComments>(emptyComments), [commentsLoading, setCommentsLoading] = useState(false), [commentsError, setCommentsError] = useState('');
  const [modal, setModal] = useState<Modal | null>(null), [form, setForm] = useState<Editor>(blankEditor), [file, setFile] = useState<File | null>(null), [rights, setRights] = useState(false), [confirmed, setConfirmed] = useState(false), [previewImageReady, setPreviewImageReady] = useState(false), [previewImageEpoch, setPreviewImageEpoch] = useState(0), [localTime, setLocalTime] = useState(''), [timezone, setTimezone] = useState('America/Denver');
  const [busy, setBusy] = useState(false), [unknown, setUnknown] = useState(false), [notFound, setNotFound] = useState(false), [expiredOAuth, setExpiredOAuth] = useState(false), [modalError, setModalError] = useState('');
  const fileInputRef = useRef<HTMLInputElement | null>(null), previewImageEpochRef = useRef(0);
  const stateSeq = useRef(0), workspaceSeq = useRef(0), postsSeq = useRef(0), commentsSeq = useRef(0), modalSeq = useRef(0), busyRef = useRef(false), selectedRef = useRef(bindingId), postRefRef = useRef(postRef), pending = useRef<Pending | null>(null), initialForm = useRef(JSON.stringify(blankEditor()));
  selectedRef.current = bindingId; postRefRef.current = postRef;
  const owner = isOwner && state?.is_owner === true;
  const authorized = () => owner && ownerRef.current && identityRef.current === identity;
  const selected = state?.bindings.find(row => String(row.id) === bindingId);
  const liveWorkspace = workspace && workspace.binding.id === selected?.id ? workspace : null;
  const dirty = modal?.kind === 'editor' && (JSON.stringify(form) !== initialForm.current || !!file);
  const guard = useUnsavedChanges(Boolean(dirty)), hold = useHardNavigationBlock(busy || unknown);
  const blocked = busy || unknown;
  const preparationBlocked = blocked || selected?.paused === true;
  const draftKind = modal?.kind === 'editor' ? modal.draft?.kind || (modal.replyTo ? 'reply' : 'post') : 'post';
  const contentLimit = draftKind === 'reply' ? 1000 : selected?.platform === 'instagram' ? 2200 : 5000;
  // A new confirmation or a rejected mutation must revalidate even an unchanged mounted image.
  const resetPreviewImage = useCallback(() => { setPreviewImageReady(false); setPreviewImageEpoch(++previewImageEpochRef.current); }, []);
  function imageReadinessChanged(ready: boolean) { if (previewImageEpochRef.current === previewImageEpoch) setPreviewImageReady(ready); }

  const loadStatus = useCallback(async () => {
    if (!isOwner || !ownerRef.current || identityRef.current !== identity) return null;
    const current = fence.current.capture(), seq = ++stateSeq.current; setLoading(true); setError('');
    try {
      const raw = verifiedMetaOpsStatus(await metaOperationsApi<MetaOpsStatus>('/status'));
      const value = { ...raw, bindings: mediaScopedBindings(raw.bindings, customerId, platformFilter) };
      if (!current() || seq !== stateSeq.current) return null;
      setState(value);
      if (!value.bindings.some(row => String(row.id) === selectedRef.current)) { const next = value.bindings[0] ? String(value.bindings[0].id) : ''; selectedRef.current = next; setBindingId(next); setWorkspace(null); setModal(null); }
      return value;
    } catch (cause) { if (current() && seq === stateSeq.current) { setState(null); setWorkspace(null); setError(mediaError(cause, cause instanceof Error ? cause.message : 'Meta 试点能力暂时无法读取。')); } return null; }
    finally { if (current() && seq === stateSeq.current) setLoading(false); }
  }, [identity, isOwner]);
  async function loadWorkspace(id: number) {
    if (!isOwner || !ownerRef.current || identityRef.current !== identity) return null;
    const current = fence.current.capture(), seq = ++workspaceSeq.current; setWorkspaceLoading(true); setWorkspaceError('');
    try {
      const value = verifiedMetaOpsWorkspace(await metaOperationsApi<MetaOpsWorkspace>(`/bindings/${id}/workspace`), id);
      if (!current() || seq !== workspaceSeq.current || selectedRef.current !== String(id)) return null;
      setWorkspace(value); return value;
    } catch (cause) { if (current() && seq === workspaceSeq.current && selectedRef.current === String(id)) { setWorkspace(null); setWorkspaceError(mediaError(cause, cause instanceof Error ? cause.message : 'Meta 工作区暂时无法读取。')); } return null; }
    finally { if (current() && seq === workspaceSeq.current) setWorkspaceLoading(false); }
  }
  useEffect(() => {
    fence.current.activate(); setResolvedIdentity(identity); stateSeq.current++; workspaceSeq.current++; postsSeq.current++; commentsSeq.current++; modalSeq.current++;
    setState(null); setWorkspace(null); setBindingId(''); selectedRef.current = ''; setSection('posts'); setPosts(emptyPosts); setComments(emptyComments); setPostRef(''); postRefRef.current = ''; setModal(null); setForm(blankEditor()); setFile(null); setRights(false); setConfirmed(false); resetPreviewImage(); setError(''); setWorkspaceError(''); setCommentsError(''); setNotice(''); setModalError(''); setUnknown(false); setNotFound(false); setExpiredOAuth(false); setBusy(false); busyRef.current = false; pending.current = null; guard.markSaved(); hold.release();
    if (isOwner) { const current = fence.current.capture(); void loadStatus().then(value => { if (!current() || !value) return; const result = new URLSearchParams(window.location.search).get('meta_ops'); if (result === 'connected') setNotice(value.bindings.some(row => row.operations_active && !row.paused) ? '独立运营授权已建立。公开提交仍取决于下方执行状态，真实发布与回复需逐项核对确认。' : '已返回 CRM，但尚未确认有效的独立运营授权，请核对下方账号状态。'); if (result === 'failed') setNotice('本次 Meta 运营授权未完成。下方显示当前实际保存的能力，系统未自动发布或回复。'); }); } else setLoading(false);
    return () => { fence.current.invalidate(); stateSeq.current++; workspaceSeq.current++; postsSeq.current++; commentsSeq.current++; modalSeq.current++; };
  }, [identity, isOwner, loadStatus, resetPreviewImage]);
  useEffect(() => { if (isOwner && bindingId) void loadWorkspace(Number(bindingId)); }, [identity, isOwner, bindingId]);

  function chooseBinding(value: string) {
    if (blocked || !guard.confirmDiscard()) return;
    workspaceSeq.current++; postsSeq.current++; commentsSeq.current++; modalSeq.current++; selectedRef.current = value; setBindingId(value); setWorkspace(null); setPosts(emptyPosts); setComments(emptyComments); setPostRef(''); postRefRef.current = ''; setCommentsError(''); setModal(null); setConfirmed(false); resetPreviewImage(); setFile(null); setRights(false); guard.markSaved();
  }
  function discardSelectedFile() { if (blocked) return; if (fileInputRef.current) fileInputRef.current.value = ''; setFile(null); setRights(false); }
  function close() { if (busyRef.current || unknown || !guard.confirmDiscard()) return; modalSeq.current++; setModal(null); setModalError(''); setConfirmed(false); resetPreviewImage(); setFile(null); setRights(false); guard.markSaved(); }
  function openEditor(draft: MetaOpsDraft | null = null, replyTo: MetaOpsComment | null = null) {
    if (!owner || !selected || preparationBlocked || !liveWorkspace) return;
    const next = draft ? editorFrom(draft) : { ...blankEditor(), title: replyTo ? '评论回复' : `${selected.customer_name} ${selected.platform === 'instagram' ? 'Instagram' : 'Facebook'} 帖文` };
    modalSeq.current++; setModal({ kind: 'editor', draft, replyTo }); setForm(next); initialForm.current = JSON.stringify(next); setFile(null); setRights(false); setConfirmed(false); resetPreviewImage(); setModalError(''); guard.markSaved();
  }
  function editField(key: keyof Editor, value: string) { if (blocked) return; setForm(previous => ({ ...previous, [key]: value })); setConfirmed(false); setModalError(''); }
  function lock() { busyRef.current = true; setBusy(true); hold.lock(); }
  function unlock() { busyRef.current = false; setBusy(false); if (!pending.current) hold.release(); }
  function finish() { pending.current = null; setUnknown(false); setNotFound(false); setExpiredOAuth(false); hold.release(); }
  async function runMutation(request: Pending) {
    if (!authorized() || busyRef.current || unknown && pending.current !== request || selectedRef.current !== String(request.bindingId)) return;
    const current = fence.current.capture(); pending.current = request; lock(); setModalError(''); setNotFound(false); setExpiredOAuth(false);
    try {
      const value = request.kind === 'media' ? (await invokeWithAuth({ url: `/api/v1/meta-operations${request.path}`, method: request.method, data: request.data, options: { headers: { 'Content-Type': 'multipart/form-data' } } })).data : await metaOperationsApi(request.path, request.method, request.data);
      if (!current() || selectedRef.current !== String(request.bindingId)) return;
      request.accept(value); finish();
    } catch (cause) {
      if (!current()) return;
      if (uncertain(cause)) { setUnknown(true); setModalError('本次保存或提交结果待确认。请查询原结果，避免重复操作。'); }
      else { finish(); setModalError(mediaError(cause, cause instanceof Error ? cause.message : '操作尚未完成。')); if (mediaErrorStatus(cause) === 409) { setConfirmed(false); resetPreviewImage(); void loadWorkspace(request.bindingId); } }
    } finally { if (current()) unlock(); }
  }
  async function recover() {
    const request = pending.current; if (!request || busyRef.current || !authorized()) return;
    const current = fence.current.capture(); lock(); setModalError(''); setNotFound(false); setExpiredOAuth(false);
    try {
      if (request.requestId) {
        const path = request.kind === 'oauth' ? `/oauth/requests/${request.requestId}` : `/requests/${request.requestId}`;
        const value = await metaOperationsApi<MetaOpsRequest>(path);
        if (!current() || selectedRef.current !== String(request.bindingId)) return;
        if (request.kind === 'oauth') request.accept(value);
        else { if (value.kind !== request.kind) throw new Error('原请求结果类型不一致，请保留当前编号后核对。'); request.accept(value.result); }
        finish();
      } else if (request.kind === 'binding') {
        const value = await loadStatus(); if (!current() || !value) return; finish(); setModal(null); setConfirmed(false); setWorkspace(null); setNotice('已读取当前实际账号操作状态。请按试点账号的授权与暂停状态继续。'); if (selectedRef.current) void loadWorkspace(Number(selectedRef.current));
      } else if (request.controlActionId) {
        const value = currentAction(await metaOperationsApi(`/actions/${request.controlActionId}`), request.bindingId);
        if (!current()) return; request.accept(value); finish();
      } else {
        const value = await loadWorkspace(request.bindingId); if (!current() || !value) return;
        finish(); modalSeq.current++; setModal(null); setConfirmed(false); resetPreviewImage(); setFile(null); guard.markSaved(); setNotice('已读取当前实际草稿与排期状态。请核对列表中的版本和状态，再决定下一步。');
      }
    } catch (cause) { if (current()) { if (mediaErrorStatus(cause) === 409 && request.kind === 'oauth') { setExpiredOAuth(true); setModalError('本次运营授权已使用、过期或配置已变化。请读取当前实际状态后结束原请求，再重新核对授权。'); } else if (mediaErrorStatus(cause) === 404 && request.requestId) { setNotFound(true); setModalError('原编号暂未找到保存结果。可以继续查询，或沿用同一编号确认；系统会核对原请求内容。'); } else setModalError(mediaError(cause, cause instanceof Error ? cause.message : '原请求结果暂时无法确认。')); } }
    finally { if (current()) unlock(); }
  }
  async function endExpiredAuthorization() {
    if (busyRef.current || !authorized() || pending.current?.kind !== 'oauth' || !expiredOAuth) return;
    const current = fence.current.capture(); lock(); setModalError('');
    try { const value = await loadStatus(); if (!current() || !value) return; finish(); setModal(null); setConfirmed(false); guard.markSaved(); setNotice('已读取当前实际运营授权状态。原授权请求已结束，未自动发起新的授权或公开提交。'); if (selectedRef.current) void loadWorkspace(Number(selectedRef.current)); }
    finally { if (current()) unlock(); }
  }
  function acceptDraft(raw: unknown) {
    const value = verifiedMetaOpsDraft(raw as MetaOpsDraft, selected!.id); setWorkspace(previous => previous ? { ...previous, drafts: [value, ...previous.drafts.filter(row => row.id !== value.id)] } : previous); setModal(null); setFile(null); setRights(false); setConfirmed(false); guard.markSaved(); setNotice(value.status === 'approved' ? '当前版本已审核通过。真实发布仍需重新核对预览，并单独确认。' : '草稿已保存，尚未公开发布。');
  }
  function saveDraft() {
    if (modal?.kind !== 'editor' || !selected || selected.paused || !form.title.trim() || !form.content.trim() || Array.from(form.content).length > contentLimit || blocked) return;
    if (file) { setModalError('请先保存所选图片的固定版本，再保存本草稿。'); return; }
    if (draftKind === 'post' && selected.platform === 'instagram' && !form.media_id) { setModalError('Instagram 图文帖子需要一张固定 JPEG 图片。'); return; }
    const data = { title: form.title, content: form.content, media_id: form.media_id || null };
    if (modal.draft) void runMutation({ path: `/drafts/${modal.draft.id}`, method: 'PATCH', data: { expected_revision: modal.draft.revision, ...data }, requestId: null, bindingId: selected.id, kind: 'draft', accept: acceptDraft });
    else {
      const requestId = mediaRequestId(); void runMutation({ path: `/bindings/${selected.id}/drafts`, method: 'POST', data: { request_id: requestId, kind: draftKind, ...data, ...(modal.replyTo ? { target_ref: modal.replyTo.target_ref, expected_target_version: modal.replyTo.version } : {}) }, requestId, bindingId: selected.id, kind: 'draft', accept: acceptDraft });
    }
  }
  async function uploadImage() {
    if (!authorized() || !selected || selected.paused || !file || !rights || blocked || modal?.kind !== 'editor') return;
    const current = fence.current.capture(), generation = modalSeq.current;
    try {
      if (!file.size || file.size > 8 * 1024 * 1024) throw new Error('请选择不超过 8MB 的 JPEG 图片。');
      const dimensions = sourceImageDimensions(new Uint8Array(await file.arrayBuffer())); if (dimensions.kind !== 'jpeg') throw new Error('当前试点只接受单张 JPEG 图片。');
      if (!current() || generation !== modalSeq.current) return;
      const requestId = mediaRequestId(), data = new FormData(); data.append('request_id', requestId); data.append('rights_confirmed', 'true'); data.append('file', file, file.name);
      void runMutation({ path: `/bindings/${selected.id}/media`, method: 'POST', data, requestId, bindingId: selected.id, kind: 'media', accept: raw => { const value = verifiedMetaOpsMedia(raw as MetaOpsMedia); setWorkspace(previous => previous ? { ...previous, media: [value, ...previous.media.filter(row => row.id !== value.id)] } : previous); setForm(previous => ({ ...previous, media_id: value.id })); if (fileInputRef.current) fileInputRef.current.value = ''; setFile(null); setRights(false); setConfirmed(false); setModalError(''); setNotice('固定图片已私有保存。请核对图片后再保存草稿。'); } });
    } catch (cause) { if (current()) setModalError(mediaError(cause, cause instanceof Error ? cause.message : '图片尚未上传。')); }
  }
  async function previewDraft(draft: MetaOpsDraft) {
    if (!selected || selected.paused || blocked || !authorized()) return;
    const current = fence.current.capture(), generation = ++modalSeq.current; lock(); setModalError(''); setConfirmed(false); resetPreviewImage();
    try {
      const value = verifiedMetaOpsPreview(await metaOperationsApi<MetaOpsPreview>(`/drafts/${draft.id}/preview`, 'POST', { expected_revision: draft.revision }), draft, selected);
      if (current() && generation === modalSeq.current && selectedRef.current === String(draft.binding_id)) setModal({ kind: 'preview', preview: value });
    } catch (cause) { if (current()) setError(mediaError(cause, cause instanceof Error ? cause.message : '当前版本预览尚未完成。')); }
    finally { if (current()) unlock(); }
  }
  function approve(preview: MetaOpsPreview) {
    if (!selected || selected.paused || !confirmed || preview.media && !previewImageReady || blocked) return;
    void runMutation({ path: `/drafts/${preview.draft.id}/approve`, method: 'POST', data: { expected_revision: preview.draft.revision, preview_hash: preview.preview_hash, confirmed: true }, requestId: null, bindingId: selected.id, kind: 'draft', accept: acceptDraft });
  }
  function acceptAction(raw: unknown, requestId?: string) {
    const value = verifiedMetaOpsAction(raw as MetaOpsAction, selected!.id, requestId); setWorkspace(previous => previous ? { ...previous, actions: [value, ...previous.actions.filter(row => row.id !== value.id)] } : previous); setModal({ kind: 'action', action: value }); setConfirmed(false); resetPreviewImage(); setNotice(value.message);
  }
  function publish(preview: MetaOpsPreview) {
    if (!selected || selected.paused || blocked || !confirmed || preview.draft.status !== 'approved' || preview.draft.preview_hash !== preview.preview_hash || !preview.ready_for_publish || preview.media && !previewImageReady || !(preview.draft.kind === 'reply' ? selected.capabilities.can_reply : selected.capabilities.can_publish)) return;
    const requestId = mediaRequestId(); void runMutation({ path: `/drafts/${preview.draft.id}/publish`, method: 'POST', data: { request_id: requestId, expected_revision: preview.draft.revision, preview_hash: preview.preview_hash, confirmed: true }, requestId, bindingId: selected.id, kind: 'action', accept: raw => { const result = verifiedMetaOpsAction(raw as MetaOpsAction, selected.id, requestId); const sent = result.submitted_draft; if (result.draft_id !== preview.draft.id || sent.draft_revision !== preview.draft.revision || sent.preview_hash !== preview.preview_hash || sent.content !== preview.draft.content || sent.media_id !== preview.draft.media_id || sent.kind !== preview.draft.kind || sent.target_ref !== preview.draft.target_ref || result.target.customer_name !== preview.target.customer_name || result.target.platform !== preview.target.platform || result.target.asset_name !== preview.target.asset_name) throw new Error('Meta 原请求结果与本次确认内容不一致，请保留原编号查询。'); acceptAction(result, requestId); } });
  }
  function prepareSchedule(preview: MetaOpsPreview) { if (blocked || selected?.paused || preview.draft.kind !== 'post' || preview.draft.status !== 'approved' || preview.draft.preview_hash !== preview.preview_hash) return; setModal({ kind: 'schedule', preview }); setLocalTime(''); setTimezone('America/Denver'); setConfirmed(false); resetPreviewImage(); setModalError(''); }
  function saveSchedule(preview: MetaOpsPreview) {
    if (!selected || selected.paused || blocked || !confirmed || preview.media && !previewImageReady || state?.scheduler.enabled && !selected.capabilities.can_schedule) return;
    let plannedAt: string; try { plannedAt = mediaLocalToUtc(localTime, timezone); if (Date.parse(plannedAt) <= Date.now() + 60_000) throw new Error('请选择至少一分钟后的时间。'); } catch (cause) { setModalError(cause instanceof Error ? cause.message : '请选择有效的未来时间和时区。'); return; }
    const requestId = mediaRequestId(); void runMutation({ path: `/drafts/${preview.draft.id}/schedules`, method: 'POST', data: { request_id: requestId, expected_revision: preview.draft.revision, preview_hash: preview.preview_hash, planned_at: plannedAt, timezone, confirmed: true, execute_confirmed: state?.scheduler.enabled === true }, requestId, bindingId: selected.id, kind: 'schedule', accept: raw => { const value = verifiedMetaOpsSchedule(raw as MetaOpsSchedule, selected.id); setWorkspace(previous => previous ? { ...previous, schedules: [value, ...previous.schedules.filter(row => row.id !== value.id)] } : previous); setModal(null); setConfirmed(false); setSection('schedules'); setNotice(value.message || metaOpsScheduleLabels[value.status]); } });
  }
  function cancelSchedule(schedule: MetaOpsSchedule) {
    if (!selected || blocked || !confirmed) return;
    void runMutation({ path: `/schedules/${schedule.id}/cancel`, method: 'POST', data: { expected_revision: schedule.revision, confirmed: true }, requestId: null, bindingId: selected.id, kind: 'schedule', accept: raw => { const value = verifiedMetaOpsSchedule(raw as MetaOpsSchedule, selected.id); setWorkspace(previous => previous ? { ...previous, schedules: previous.schedules.map(row => row.id === value.id ? value : row) } : previous); setModal(null); setConfirmed(false); setNotice(value.message); } });
  }
  function activateSchedule(schedule: MetaOpsSchedule) {
    if (!selected || selected.paused || blocked || !confirmed || !state?.scheduler.enabled || !selected.capabilities.can_schedule || schedule.status !== 'prepared' || schedule.media && !previewImageReady) return;
    void runMutation({ path: `/schedules/${schedule.id}/activate`, method: 'POST', data: { expected_revision: schedule.revision, confirmed: true }, requestId: null, bindingId: selected.id, kind: 'schedule', accept: raw => { const value = verifiedMetaOpsSchedule(raw as MetaOpsSchedule, selected.id); setWorkspace(previous => previous ? { ...previous, schedules: previous.schedules.map(row => row.id === value.id ? value : row) } : previous); setModal(null); setConfirmed(false); setNotice(value.message); } });
  }
  function pauseBinding(binding: MetaOpsBinding) {
    if (!authorized() || blocked || !confirmed || !binding.can_pause || binding.paused) return;
    void runMutation({ path: `/bindings/${binding.id}/disconnect`, method: 'POST', data: { expected_revision: binding.revision, confirmed: true }, requestId: null, bindingId: binding.id, kind: 'binding', accept: raw => { const value = verifiedMetaOpsBinding(raw as MetaOpsBinding); if (value.id !== binding.id || !value.paused || value.operations_active) throw new Error('账号暂停结果待核对，请读取当前实际状态。'); setState(previous => previous ? { ...previous, bindings: previous.bindings.map(row => row.id === value.id ? value : row) } : previous); setWorkspace(previous => previous ? { ...previous, binding: value } : previous); setModal(null); setConfirmed(false); setNotice('此账号的独立运营操作已暂停。未来计划已阻止继续执行，只读连接和已公开内容保留。'); void loadWorkspace(binding.id); } });
  }
  async function readAction(action: MetaOpsAction) {
    if (blocked || !selected || !authorized()) return;
    const current = fence.current.capture(); lock(); setError('');
    try { const value = currentAction(await metaOperationsApi(`/actions/${action.id}`), selected.id); if (current()) acceptAction(value); }
    catch (cause) { if (current()) { const message = mediaError(cause, 'Meta 原操作结果暂时无法读取。'); setError(message); setModalError(message); } }
    finally { if (current()) unlock(); }
  }
  function continueAction(action: MetaOpsAction) {
    if (!selected || selected.paused || blocked || !confirmed || !action.can_continue || !(action.kind === 'reply' ? selected.capabilities.can_reply : selected.capabilities.can_publish) || !['processing', 'pending'].includes(action.status) || action.media && !previewImageReady) return;
    void runMutation({ path: `/actions/${action.id}/continue`, method: 'POST', data: { expected_revision: action.revision, confirmed: true }, requestId: null, bindingId: selected.id, kind: 'action', controlActionId: action.id, accept: acceptAction });
  }
  async function loadPosts(cursor?: string) {
    if (!authorized() || !selected || !selected.capabilities.can_read_posts || blocked) return;
    const current = fence.current.capture(), id = selected.id, seq = ++postsSeq.current; setPostsLoading(true); setCommentsError('');
    try { const value = verifiedMetaOpsPosts(await metaOperationsApi<MetaOpsPosts>(`/bindings/${id}/posts${cursor ? `?cursor=${encodeURIComponent(cursor)}` : ''}`)); if (current() && seq === postsSeq.current && selectedRef.current === String(id)) setPosts(previous => ({ ...value, items: cursor ? [...previous.items, ...value.items.filter(row => !previous.items.some(old => old.target_ref === row.target_ref))] : value.items })); }
    catch (cause) { if (current() && seq === postsSeq.current) setCommentsError(mediaError(cause, 'Meta 帖文暂时无法读取。')); }
    finally { if (current() && seq === postsSeq.current) setPostsLoading(false); }
  }
  async function loadComments(ref: string, cursor?: string) {
    if (!authorized() || !selected || !ref || !selected.capabilities.can_read_comments || blocked) return;
    const current = fence.current.capture(), id = selected.id, seq = ++commentsSeq.current; setCommentsLoading(true); setCommentsError('');
    try { const query = new URLSearchParams({ post_ref: ref, ...(cursor ? { cursor } : {}) }); const value = verifiedMetaOpsComments(await metaOperationsApi<MetaOpsComments>(`/bindings/${id}/comments?${query}`), ref); if (current() && seq === commentsSeq.current && selectedRef.current === String(id) && postRefRef.current === ref) setComments(previous => ({ ...value, items: cursor ? [...previous.items, ...value.items.filter(row => !previous.items.some(old => old.target_ref === row.target_ref))] : value.items })); }
    catch (cause) { if (current() && seq === commentsSeq.current) setCommentsError(mediaError(cause, 'Meta 评论暂时无法读取。')); }
    finally { if (current() && seq === commentsSeq.current) setCommentsLoading(false); }
  }
  function choosePost(value: string) { if (blocked) return; commentsSeq.current++; postRefRef.current = value; setPostRef(value); setComments(emptyComments); setCommentsError(''); if (value) void loadComments(value); }
  function chooseSection(value: Section) { if (blocked) return; setSection(value); if (value === 'comments' && selected?.capabilities.can_read_posts && !posts.items.length) void loadPosts(); }
  function navigateOAuth(raw: unknown, authorization: MetaAuthorization) {
    const value = raw as { authorization_url: string; expires_in: number }, url = metaOpsAuthorizationUrl(value?.authorization_url, authorization);
    if (!url || !Number.isSafeInteger(value.expires_in) || value.expires_in < 1 || value.expires_in > 600) throw new Error('Meta 运营授权链接无法核实，请查询原请求。');
    guard.markSaved(); finish(); window.location.assign(url);
  }
  function startAuthorization() {
    if (!selected || modal?.kind !== 'authorize' || !confirmed || blocked || !state?.write_configured) return;
    const requestId = mediaRequestId(), authorization = modal.authorization;
    void runMutation({ path: '/oauth/start', method: 'POST', data: { request_id: requestId, connection_id: selected.connection_id, confirmed: true }, requestId, bindingId: selected.id, kind: 'oauth', accept: raw => navigateOAuth(raw, authorization) });
  }

  if (!isOwner) return <section className="mops-empty"><ShieldCheck/><p>Meta 试点运营仅由老板操作，不新增员工访问权限。</p></section>;
  if (resolvedIdentity !== identity || loading && !state) return <section className="mops-empty" role="status"><Loader2 className="animate-spin"/><p>正在读取 Meta 试点操作范围…</p></section>;
  const preview = modal?.kind === 'preview' || modal?.kind === 'schedule' ? modal.preview : null;
  const modalImage = preview?.media || (modal?.kind === 'action' ? modal.action.media : modal?.kind === 'activate' ? modal.schedule.media : null);
  const modalTitle = modal?.kind === 'editor' ? draftKind === 'reply' ? '准备评论回复' : modal.draft ? '修改帖文草稿' : '新建帖文草稿' : modal?.kind === 'preview' ? '核对当前版本' : modal?.kind === 'schedule' ? '设置发布计划' : modal?.kind === 'action' ? 'Meta 原操作结果' : modal?.kind === 'cancel' ? '取消发布计划' : modal?.kind === 'activate' ? '确认启用原发布计划' : modal?.kind === 'pause' ? '暂停此账号的独立运营操作' : '补充 Meta 运营授权';
  const approved = preview?.draft.status === 'approved' && preview.draft.preview_hash === preview.preview_hash;
  const canConfirmPreview = !!preview && (!preview.media || previewImageReady);
  const scheduleLabel = state?.scheduler.enabled ? '确认排期' : '保存发布计划（暂不执行）';
  let schedulePreview = ''; try { if (localTime) schedulePreview = `${formatTime(mediaLocalToUtc(localTime, timezone), timezone)}（${timezone}） · 北京时间 ${formatTime(mediaLocalToUtc(localTime, timezone))}`; } catch { /* show field validation on submit */ }
  return <section className="mops-workspace" aria-label="Meta 试点运营工作区">
    <header className="mops-heading"><div><p className="mops-eyebrow">Facebook / Instagram · 运营试点</p><h2>准备内容，核对后再公开</h2><p>当前先由老板试用。授权、内部审核和真实发布分别确认。</p></div><Button variant="outline" disabled={blocked || !!modal || loading} onClick={() => { void loadStatus(); if (selected) void loadWorkspace(selected.id); }} aria-label="刷新 Meta 运营工作区"><RefreshCw className={loading ? 'animate-spin' : ''}/><span>刷新工作区</span></Button></header>
    {notice && <div className="mops-notice" role="status"><CheckCircle2/>{notice}</div>}{error && <div className="mops-alert" role="alert"><AlertCircle/><div>{error}</div><Button variant="outline" disabled={blocked} onClick={() => void loadStatus()}>重新读取</Button></div>}
    {state && !owner && <p className="mops-empty">当前账号未开放 Meta 试点操作。</p>}
    {state && owner && <>
      {!state.bindings.length ? <div className="mops-empty"><ShieldCheck/><h3>先绑定试点商家的平台账号</h3><p>在连接管理中核对 {state.pilot_label} 的客户与 Facebook／Instagram 对应关系后，再准备公开内容。</p></div> : <>
        <div className="mops-account"><label>试点客户与平台<NativeSelect aria-label="Meta 试点运营账号" value={bindingId} disabled={blocked || !!modal} onChange={chooseBinding} options={state.bindings.map(row => ({ value: String(row.id), label: `${row.customer_name} · ${metaPlatformLabel(row.platform)} · ${row.asset_name}` }))}/></label>{state.authorization && <Button variant="outline" disabled={blocked || !selected || !state.write_configured} onClick={() => { if (state.authorization) { setModal({ kind: 'authorize', authorization: state.authorization }); setConfirmed(false); setModalError(''); } }}>补充运营授权</Button>}{selected?.can_pause && <Button variant="outline" disabled={blocked || !!modal} onClick={() => { setModal({ kind: 'pause', binding: selected }); setConfirmed(false); setModalError(''); }}>暂停此账号操作</Button>}</div>
        {selected && <div className="mops-capabilities" aria-label="当前 Meta 操作能力"><span className={selected.operations_active && !selected.paused ? 'ready' : ''}><CheckCircle2/>{selected.paused ? '运营已暂停' : selected.operations_active ? '独立运营授权已建立' : '已绑定 · 待运营授权'}</span><span className={selected.capabilities.can_publish ? 'ready' : ''}>帖文：{selected.paused ? '操作已暂停' : selected.capabilities.can_publish ? '可核对后发布' : selected.operations_active ? '暂不可执行，原因见下方' : '待运营授权'}</span><span className={selected.capabilities.can_reply ? 'ready' : ''}>评论：{selected.paused ? '操作已暂停' : selected.capabilities.can_reply ? '可核对后回复' : selected.operations_active ? '暂不可执行，原因见下方' : '待运营授权'}</span><span className={state.scheduler.enabled ? 'ready' : ''}>排期：{state.scheduler.enabled ? '服务器执行已启用' : '仅保存计划，执行未启用'}</span></div>}
        {selected?.capabilities.blocked_reasons.length ? <div className="mops-gates"><ShieldCheck/><div><strong>先准备，执行条件就绪后再提交</strong>{selected.capabilities.blocked_reasons.map(reason => <p key={reason}>{reason}</p>)}</div></div> : null}
        <nav className="mops-tabs" aria-label="Meta 运营流程">{(Object.keys(sectionLabels) as Section[]).map(key => <button type="button" key={key} aria-pressed={section === key} className={section === key ? 'active' : ''} disabled={blocked} onClick={() => chooseSection(key)}>{sectionLabels[key]}</button>)}</nav>
        {workspaceLoading ? <div className="mops-empty" role="status"><Loader2 className="animate-spin"/>正在读取当前账号的草稿与记录…</div> : workspaceError ? <div className="mops-alert" role="alert">{workspaceError}<Button variant="outline" disabled={blocked} onClick={() => selected && void loadWorkspace(selected.id)}>重新读取工作区</Button></div> : liveWorkspace && selected && <>
          {section === 'posts' && <section className="mops-panel"><header><div><h3>帖文草稿</h3><p>{selected.platform === 'instagram' ? 'Instagram 本轮支持单张 JPEG 图文。' : 'Facebook 本轮支持纯文字或单张 JPEG 图文。'}保存草稿和审核不会公开内容。</p></div><Button disabled={preparationBlocked} onClick={() => openEditor()}><Plus/>新建帖文</Button></header><DraftRows drafts={liveWorkspace.drafts.filter(row => row.kind === 'post')} blocked={preparationBlocked} onEdit={openEditor} onPreview={draft => void previewDraft(draft)}/></section>}
          {section === 'comments' && <><section className="mops-panel"><header><div><h3>评论收件箱</h3><p>先选择真实帖文，再读取其评论。回复只在核对当前版本后提交。</p></div><Button variant="outline" disabled={blocked || postsLoading || !selected.capabilities.can_read_posts} onClick={() => void loadPosts()}><RefreshCw/>读取帖文</Button></header>{!selected.capabilities.can_read_posts || !selected.capabilities.can_read_comments ? <div className="mops-empty"><ShieldCheck/><p>当前账号的帖文／评论读取权限尚未就绪，完成运营授权后可在这里处理真实评论。</p></div> : <div className="mops-comments"><label>选择已发布帖文<NativeSelect aria-label="Meta 评论所属帖文" value={postRef} disabled={blocked || postsLoading} onChange={choosePost} options={[{ value: '', label: postsLoading ? '正在读取真实帖文…' : '请选择帖文' }, ...posts.items.map(row => ({ value: row.target_ref, label: `${formatTime(row.created_at)} · ${row.content.slice(0, 65) || '图片帖文'}` }))]}/></label>{posts.next_cursor && <Button variant="outline" disabled={blocked || postsLoading} onClick={() => void loadPosts(posts.next_cursor!)}>读取更多帖文</Button>}{commentsError && <p className="mops-alert" role="alert">{commentsError}</p>}{commentsLoading ? <p role="status">正在读取当前帖文评论…</p> : postRef && !comments.items.length ? <p className="mops-empty">本次未返回评论。</p> : comments.items.map(row => <article className="mops-comment" key={row.target_ref}><div><strong>{row.author_name || '平台用户'}</strong><small>{formatTime(row.created_at)}（北京时间）</small><p>{row.content || '此评论没有文字内容。'}</p></div><Button variant="outline" disabled={preparationBlocked} onClick={() => openEditor(null, row)}>准备回复</Button></article>)}{comments.next_cursor && <Button variant="outline" disabled={blocked || commentsLoading} onClick={() => void loadComments(postRef, comments.next_cursor!)}>读取更多评论</Button>}</div>}</section><section className="mops-panel"><header><div><h3>拟回复草稿</h3><p>保存草稿后，逐条核对原评论与回复内容。</p></div></header><DraftRows drafts={liveWorkspace.drafts.filter(row => row.kind === 'reply')} blocked={preparationBlocked} onEdit={openEditor} onPreview={draft => void previewDraft(draft)}/></section></>}
          {section === 'schedules' && <section className="mops-panel"><header><div><h3>发布计划</h3><p>{state.scheduler.enabled ? '仅执行明确确认的未来排期。' : '服务器执行尚未启用。当前保存的计划不会自动发布。'}从已审核帖文的预览中设置时间。</p></div></header>{!liveWorkspace.schedules.length ? <div className="mops-empty"><CalendarClock/><p>暂无发布计划。先保存帖文并通过审核，再核对排期。</p></div> : liveWorkspace.schedules.map(row => <article className="mops-row" key={row.id}><div><strong>{row.submitted_draft.title || `帖文 #${row.draft_id}`}</strong><span>{formatTime(row.planned_at, row.timezone)} · {row.timezone}</span><small>北京时间 {formatTime(row.planned_at)} · {row.message}</small></div><span className={`mops-pill ${row.status === 'succeeded' ? 'success' : ''}`}>{metaOpsScheduleLabels[row.status]}</span>{row.status === 'prepared' && <Button variant="outline" size="sm" disabled={preparationBlocked || !state.scheduler.enabled || !selected.capabilities.can_schedule} onClick={() => { setModal({ kind: 'activate', schedule: row }); setConfirmed(false); resetPreviewImage(); setModalError(''); }}>启用此排期</Button>}{['prepared', 'scheduled', 'blocked'].includes(row.status) && <Button variant="outline" size="sm" disabled={blocked} onClick={() => { setModal({ kind: 'cancel', schedule: row }); setConfirmed(false); setModalError(''); }}>取消计划</Button>}</article>)}</section>}
          {section === 'history' && <section className="mops-panel"><header><div><h3>真实提交记录</h3><p>只按平台确认记录结果；处理中和结果待确认均不算已公开。</p></div></header>{!liveWorkspace.actions.length ? <div className="mops-empty"><Clock3/><p>暂无公开提交记录。保存草稿和内部审核不会产生发帖或回复记录。</p></div> : liveWorkspace.actions.map(row => <article className="mops-row" key={row.id}><div><strong>{row.kind === 'reply' ? '评论回复' : '帖文发布'}</strong><span>{row.message}</span><small>{formatTime(row.created_at)}（北京时间）</small></div><span className={`mops-pill ${row.status === 'succeeded' ? 'success' : row.status === 'unknown' ? 'warning' : ''}`}>{metaOpsActionLabels[row.status]}</span><Button variant="outline" size="sm" disabled={blocked} onClick={() => void readAction(row)}>查看原结果</Button></article>)}</section>}
        </>}
      </>}
    </>}
    <Dialog open={!!modal} onOpenChange={value => { if (!value) close(); }}><CrmFormDialogContent className="mops-dialog" aria-busy={busy} onEscapeKeyDown={event => { if (busyRef.current || unknown) event.preventDefault(); }} onPointerDownOutside={event => { if (busyRef.current || unknown || dirty) event.preventDefault(); }}><CrmFormDialogHeader><DialogTitle>{modalTitle}</DialogTitle><DialogDescription>{selected ? `${selected.customer_name} · ${metaPlatformLabel(selected.platform)} · ${selected.asset_name}` : '仅对当前明确选择的试点账号操作。'}</DialogDescription></CrmFormDialogHeader><CrmFormDialogBody>
      {modal?.kind === 'editor' && <div className="mops-form">{modal.replyTo && <blockquote className="mops-source"><strong>{modal.replyTo.author_name || '平台用户'}</strong><p>{modal.replyTo.content}</p><small>回复前会重新核对原评论版本。</small></blockquote>}<label>内部标题 *<Input aria-label="Meta 草稿标题" value={form.title} disabled={blocked} maxLength={200} onChange={event => editField('title', event.target.value)}/></label><label>{draftKind === 'reply' ? '拟公开回复' : '帖文正文'}<Textarea aria-label="Meta 草稿正文" rows={7} value={form.content} disabled={blocked} onChange={event => editField('content', event.target.value)}/><small className={Array.from(form.content).length > contentLimit ? 'mops-danger' : ''}>{Array.from(form.content).length} / {contentLimit} 字符 · 保存后仍需审核及公开确认</small></label>{draftKind === 'post' && <><label>固定发布图片<NativeSelect aria-label="Meta 草稿固定图片" value={form.media_id} disabled={blocked} onChange={value => editField('media_id', value)} options={[{ value: '', label: selected?.platform === 'instagram' ? '请选择一张固定 JPEG 图片' : '纯文字帖文（不配图）' }, ...(liveWorkspace?.media.map(row => ({ value: row.id, label: `${row.width}×${row.height} · ${row.id.slice(0, 8)}` })) || [])]}/></label>{liveWorkspace?.media.find(row => row.id === form.media_id) && <MetaPrivateImage image={liveWorkspace.media.find(row => row.id === form.media_id)!} scope={`${identity}:editor:${previewImageEpoch}`}/>}<div className="mops-upload"><strong><ImagePlus/>上传新的固定图片</strong><p>只接受单张 JPEG，最大 8MB。保存后的图片先保持私有；真实发布确认后才向平台提供对应副本。</p>{selected?.platform === 'instagram' && <p>Instagram 建议 1080×1080 或 1080×1350；图片宽度需 320—1440 像素，宽高比介于 4:5 与 1.91:1，不自动裁切。</p>}<input ref={fileInputRef} type="file" aria-label="Meta 试点 JPEG 图片" accept="image/jpeg,.jpg,.jpeg" disabled={blocked} onChange={event => { setFile(event.target.files?.[0] || null); setRights(false); setConfirmed(false); setModalError(''); }}/>{file && <><p>已选：{file.name}</p><label className="mops-check"><input type="checkbox" checked={rights} disabled={blocked} onChange={event => setRights(event.target.checked)}/><span>我确认有权将这张图片用于该商家的公开宣传；本次仅保存私有固定版本。</span></label><Button variant="outline" disabled={blocked} onClick={discardSelectedFile}>放弃所选图片</Button><Button variant="outline" disabled={blocked || !rights} onClick={() => void uploadImage()}>保存私有图片版本</Button></>}</div></>}</div>}
      {preview && <div className="mops-preview"><div className="mops-target"><ShieldCheck/><div><strong>{preview.target.customer_name}</strong><p>{metaPlatformLabel(preview.target.platform)} · {preview.target.asset_name}</p><small>草稿 #{preview.draft.id} · 版本 {preview.draft.revision}</small></div></div>{preview.reply_to && <blockquote className="mops-source"><strong>原评论 · {preview.reply_to.author_name || '平台用户'}</strong><p>{preview.reply_to.content}</p><small>{formatTime(preview.reply_to.created_at)}（北京时间）</small></blockquote>}<div className="mops-public-copy"><small>{preview.draft.kind === 'reply' ? '本次拟公开回复' : '本次拟公开帖文'}</small><p>{preview.draft.content}</p></div>{modalImage && <MetaPrivateImage image={modalImage} scope={`${identity}:${modal?.kind}:${preview.preview_hash}:${previewImageEpoch}`} onReady={imageReadinessChanged}/>}<p className="mops-help">{modalImage ? preview.media_delivery_notice || '这张固定图片只在明确提交发布时开放供 Meta 抓取的临时副本；原素材保持私有。' : '本次为纯文字内容。'}审核通过、设置计划和公开提交为不同操作。</p>{preview.draft.status === 'approved' && preview.draft.preview_hash !== preview.preview_hash && <p className="mops-alert">账号、授权或内容版本已变化，请重新审核当前预览；原审核不能直接用于这次公开提交。</p>}{preview.warnings.map(warning => <p className="mops-alert" key={warning}>{warning}</p>)}{modal?.kind === 'schedule' && <div className="mops-form"><label>计划发布时间<Input aria-label="Meta 计划发布时间" type="datetime-local" value={localTime} disabled={blocked} onChange={event => { setLocalTime(event.target.value); setConfirmed(false); }}/></label><label>时间所属时区（门店默认丹佛）<NativeSelect aria-label="Meta 计划时区" value={timezone} disabled={blocked} onChange={value => { setTimezone(value); setConfirmed(false); }} options={mediaTimezones}/></label>{schedulePreview && <p className="mops-time-preview">{schedulePreview}</p>}<p className="mops-alert">{state?.scheduler.enabled ? '将按这里明确确认的账号、时间与冻结内容执行。' : '当前只保存发布计划，服务器不会自动执行；启用定时执行还需老板另行确认。'}</p></div>}</div>}
      {modal?.kind === 'action' && <div className="mops-preview"><span className={`mops-pill ${modal.action.status === 'succeeded' ? 'success' : ''}`}>{metaOpsActionLabels[modal.action.status]}</span><div className="mops-target"><strong>{modal.action.target.customer_name} · {metaPlatformLabel(modal.action.target.platform)}</strong><p>{modal.action.target.asset_name}</p></div><p>{modal.action.message}</p><div className="mops-public-copy"><small>原请求实际提交内容</small><p>{modal.action.submitted_draft.content}</p></div>{modal.action.media && <MetaPrivateImage image={modal.action.media} scope={`${identity}:action:${modal.action.id}:${modal.action.revision}:${previewImageEpoch}`} onReady={imageReadinessChanged}/>}<p className="mops-help">原请求编号：{modal.action.request_id}<br/>{formatTime(modal.action.created_at)}（北京时间）</p>{metaOpsPublicUrl(modal.action.provider_url) && <a className="mops-external" href={metaOpsPublicUrl(modal.action.provider_url)!} target="_blank" rel="noopener noreferrer">查看平台内容<ExternalLink/></a>}{modal.action.can_continue && !(modal.action.kind === 'reply' ? selected?.capabilities.can_reply : selected?.capabilities.can_publish) && <p className="mops-alert">当前账号的公开提交权限或执行状态尚未就绪。可查询原结果，恢复条件后再单独确认继续。</p>}{modal.action.status === 'pending' && modal.action.can_continue && <p className="mops-alert">原请求已保留，平台提交尚未开始。核对原内容并确认后，只继续同一请求。</p>}{modal.action.status === 'processing' && <p className="mops-alert">Instagram 正在处理这次原请求的素材。继续时只检查并推进同一请求，不能新建第二次发布。</p>}</div>}
      {modal?.kind === 'activate' && <div className="mops-preview"><div className="mops-target"><strong>{modal.schedule.target.customer_name} · {metaPlatformLabel(modal.schedule.target.platform)}</strong><p>{modal.schedule.target.asset_name}</p><small>原计划 #{modal.schedule.id} · 固定草稿版本 {modal.schedule.draft_revision}</small></div><p className="mops-time-preview">{formatTime(modal.schedule.planned_at, modal.schedule.timezone)}（{modal.schedule.timezone}） · 北京时间 {formatTime(modal.schedule.planned_at)}</p><div className="mops-public-copy"><small>原计划冻结内容</small><p>{modal.schedule.submitted_draft.content}</p></div>{modal.schedule.media && <MetaPrivateImage image={modal.schedule.media} scope={`${identity}:schedule:${modal.schedule.id}:${modal.schedule.preview_hash}:${previewImageEpoch}`} onReady={imageReadinessChanged}/>}<p className="mops-alert">仅启用这一条明确核对的未来排期。内容、账号或图片版本变化后需要重新准备计划。</p></div>}
      {modal?.kind === 'cancel' && <div className="mops-preview"><strong>{metaOpsScheduleLabels[modal.schedule.status]}</strong><p>{formatTime(modal.schedule.planned_at, modal.schedule.timezone)} · {modal.schedule.timezone}</p><p>取消此发布计划，草稿与操作历史保留。已提交给平台的操作须查询原结果。</p></div>}
      {modal?.kind === 'pause' && <div className="mops-preview"><div className="mops-target"><strong>{modal.binding.customer_name}</strong><p>{metaPlatformLabel(modal.binding.platform)} · {modal.binding.asset_name}</p></div><p>只暂停此账号在 CRM 的独立发帖、评论回复和排期操作，未来计划会阻止继续执行。只读连接、已公开内容与历史记录保留，不撤销 Meta 平台授权。</p><p className="mops-help">恢复操作需要重新核对独立运营授权。不会改变其他账号、员工权限或公司财务。</p></div>}
      {modal?.kind === 'authorize' && <div className="mops-form"><p>{modal.authorization.purpose}</p><div className="mops-target"><strong>{modal.authorization.flow}</strong><p>授权返回：{modal.authorization.redirect_uri}</p><p>{modal.authorization.token_storage}</p></div><div className="mops-scopes"><strong>本应用配置的运营权限</strong><ul>{modal.authorization.requested_scopes.map(value => <li key={value}>{value}</li>)}</ul><p>平台页面的实际资产和权限仍需本人核对。本次不自动发布或回复。</p></div></div>}
      {modal && modal.kind !== 'editor' && !(modal.kind === 'action' && !modal.action.can_continue) && !unknown && <label className="mops-check"><input type="checkbox" checked={confirmed} disabled={blocked || !!preview?.media && !previewImageReady || modal.kind === 'action' && !!modal.action.media && !previewImageReady || modal.kind === 'activate' && !!modal.schedule.media && !previewImageReady} onChange={event => setConfirmed(event.target.checked)}/><span>{modal.kind === 'preview' ? previewConsentLabel(modal.preview, approved) : modal.kind === 'schedule' ? state?.scheduler.enabled ? '我已核对账号、固定内容、图片、时区和时间，允许服务器在指定时间公开发布。' : '我已核对账号、固定内容、图片、时区和时间，本次仅保存计划，不启用自动执行。' : modal.kind === 'action' ? '我已核对原请求提交的账号、正文和配图，确认检查并继续同一发布请求。' : modal.kind === 'cancel' ? '我确认取消上述发布计划。' : modal.kind === 'pause' ? '我已核对上述客户与平台账号，确认只暂停此账号的独立运营操作及未来排期。' : modal.kind === 'activate' ? '我已核对原计划的账号、冻结正文、图片、时区和时间，确认允许服务器按这一条计划公开发布。' : '我已核对运营权限、当前账号和 CRM 接收地址，确认前往 Meta 补充授权。'}</span></label>}
      {modalError && <div className="mops-alert" role="alert"><AlertCircle/>{modalError}</div>}{unknown && <p className="mops-help">{pending.current?.requestId ? `原请求编号：${pending.current.requestId}` : '请读取当前实际版本后核对，系统不会自动重复本次操作。'}</p>}
    </CrmFormDialogBody><CrmFormDialogFooter>{unknown ? <><Button variant="outline" disabled={busy} onClick={() => void recover()}>{busy ? '正在查询…' : pending.current?.requestId ? '查询原请求结果' : '读取实际操作状态'}</Button>{notFound && pending.current?.requestId && <Button disabled={busy} onClick={() => pending.current && void runMutation(pending.current)}>沿用原编号确认</Button>}{expiredOAuth && <Button variant="outline" disabled={busy} onClick={() => void endExpiredAuthorization()}>读取实际状态并结束本次授权</Button>}</> : modal?.kind === 'editor' ? <><Button variant="outline" disabled={busy} onClick={close}>取消</Button><Button disabled={busy || !form.title.trim() || !form.content.trim() || Array.from(form.content).length > contentLimit || !!file} onClick={saveDraft}><FileText/>仅保存草稿</Button></> : modal?.kind === 'preview' ? <><Button variant="outline" disabled={busy} onClick={close}>关闭预览</Button>{approved && modal.preview.draft.kind === 'post' && <Button variant="outline" disabled={busy} onClick={() => prepareSchedule(modal.preview)}><CalendarClock/>设置发布计划</Button>}<Button disabled={busy || !confirmed || !canConfirmPreview || approved && (!modal.preview.ready_for_publish || !(modal.preview.draft.kind === 'reply' ? selected?.capabilities.can_reply : selected?.capabilities.can_publish))} onClick={() => approved ? publish(modal.preview) : approve(modal.preview)}>{approved ? <Send/> : <CheckCircle2/>}{approved ? modal.preview.draft.kind === 'reply' ? '确认公开回复' : '确认公开发布' : '确认审核当前版本'}</Button></> : modal?.kind === 'schedule' ? <><Button variant="outline" disabled={busy} onClick={close}>取消</Button><Button disabled={busy || !confirmed || !localTime || !canConfirmPreview || state?.scheduler.enabled && !selected?.capabilities.can_schedule} onClick={() => saveSchedule(modal.preview)}><CalendarClock/>{scheduleLabel}</Button></> : modal?.kind === 'action' ? <><Button variant="outline" disabled={busy} onClick={close}>关闭</Button><Button variant="outline" disabled={busy} onClick={() => void readAction(modal.action)}>查询原结果</Button>{modal.action.can_continue && <Button disabled={busy || !confirmed || !['processing', 'pending'].includes(modal.action.status) || !(modal.action.kind === 'reply' ? selected?.capabilities.can_reply : selected?.capabilities.can_publish) || !!modal.action.media && !previewImageReady} onClick={() => continueAction(modal.action)}>检查并继续原请求</Button>}</> : modal?.kind === 'cancel' ? <><Button variant="outline" disabled={busy} onClick={close}>返回</Button><Button disabled={busy || !confirmed} onClick={() => cancelSchedule(modal.schedule)}>确认取消计划</Button></> : modal?.kind === 'activate' ? <><Button variant="outline" disabled={busy} onClick={close}>返回</Button><Button disabled={busy || !confirmed || !state?.scheduler.enabled || !selected?.capabilities.can_schedule || !!modal.schedule.media && !previewImageReady} onClick={() => activateSchedule(modal.schedule)}>确认启用此排期</Button></> : modal?.kind === 'pause' ? <><Button variant="outline" disabled={busy} onClick={close}>返回</Button><Button disabled={busy || !confirmed || !modal.binding.can_pause} onClick={() => pauseBinding(modal.binding)}>确认暂停此账号操作</Button></> : modal?.kind === 'authorize' ? <><Button variant="outline" disabled={busy} onClick={close}>取消</Button><Button disabled={busy || !confirmed || !state?.write_configured} onClick={startAuthorization}>前往 Meta 运营授权</Button></> : null}</CrmFormDialogFooter></CrmFormDialogContent></Dialog>
  </section>;
}

function DraftRows({ drafts, blocked, onEdit, onPreview }: { drafts: MetaOpsDraft[]; blocked: boolean; onEdit: (draft: MetaOpsDraft) => void; onPreview: (draft: MetaOpsDraft) => void }) {
  return !drafts.length ? <div className="mops-empty"><FileText/><p>暂无草稿。先准备内容，再逐项审核。</p></div> : <div>{drafts.map(row => <article className="mops-row" key={row.id}><div><strong>{row.title || (row.kind === 'reply' ? '评论回复草稿' : '未命名帖文')}</strong><p>{row.content}</p><small>版本 {row.revision} · {formatTime(row.updated_at)}（北京时间）</small></div><span className={`mops-pill ${row.status === 'approved' ? 'success' : ''}`}>{row.status === 'approved' ? '已审核 · 待确认操作' : '草稿'}</span><div className="mops-row-actions"><Button variant="outline" size="sm" disabled={blocked} onClick={() => onEdit(row)}>修改</Button><Button variant="outline" size="sm" disabled={blocked} onClick={() => onPreview(row)}>预览与操作</Button></div></article>)}</div>;
}
