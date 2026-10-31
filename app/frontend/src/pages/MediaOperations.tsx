import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AlertCircle, ArrowRight, CalendarDays, Check, CheckCircle2, ChevronLeft, ChevronRight, Clock3, Copy, ExternalLink, FileText, Globe2, Image, ListChecks, Loader2, LockKeyhole, Plus, RefreshCw, Search, ShieldCheck } from 'lucide-react';
import { useRole } from '@/lib/role-context';
import { confirmDiscardAllChanges, useHardNavigationBlock, useUnsavedChanges } from '@/lib/use-unsaved-changes';
import MediaPublicationFields from '@/components/MediaPublicationFields';
import MediaPublicationPreview from '@/components/MediaPublicationPreview';
import MediaTeamMaterials from '@/components/MediaTeamMaterials';
import MediaPublicationImage, { PublicationImagePreview } from '@/components/MediaPublicationImage';
import { imageVersionId } from '@/lib/media-publication-images';
import MediaPlatformCapabilities from '@/components/MediaPlatformCapabilities';
import MediaPlanningWorkspace from '@/components/MediaPlanningWorkspace';
import { blankPublicationForm, publicationEquivalent, publicationForm, publicationPayload, type PublicationForm } from '@/components/media-publication';
import GoogleBusinessManagement from '@/components/GoogleBusinessManagement';
import type { GbpPublicationEntry } from '@/lib/google-readiness';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { NativeSelect } from '@/components/ui/native-select';
import { Dialog, DialogTitle, DialogDescription, CrmFormDialogContent, CrmFormDialogHeader, CrmFormDialogBody, CrmFormDialogFooter } from '@/components/ui/dialog';
import { mediaActionLabels, mediaError, mediaErrorStatus, mediaLocalToUtc, mediaOperationsApi, mediaRequestId, mediaSafeProofUrl, mediaScheduleLabel, mediaStatusLabels, mediaTimezones, mediaUtcToLocal, verifiedMediaTask, type MediaAction, type MediaCustomer, type MediaList, type MediaOptions, type MediaPublication, type MediaStatus, type MediaTask } from '@/lib/media-operations-api';
import './media-operations.css';

type Form = { customer_id: string; service_progress_id: string; title: string; platform: string; local_time: string; timezone: string; assignee_id: string; content: string; material_id: string; image_version_id: string; publication: PublicationForm };
type PendingMutation = { path: string; method: 'POST' | 'PUT'; data: unknown; expectedId?: number };
const blankForm = (): Form => ({ customer_id: '', service_progress_id: '', title: '', platform: 'google_business', local_time: '', timezone: 'Asia/Shanghai', assignee_id: '', content: '', material_id: '', image_version_id: '', publication: blankPublicationForm() });
const stages: MediaStatus[] = ['draft', 'in_review', 'ready', 'completed', 'blocked'];
const emptyOptions: MediaOptions = { customers: [], assignees: [], platforms: [] };
const imageTypes = new Set(['image', 'photo', 'screenshot', 'picture', '图片', '截图']);
const isProofImage = (kind: string, contentType?: string | null) => imageTypes.has(kind.toLowerCase()) || kind.toLowerCase().startsWith('image/') || Boolean(contentType?.toLowerCase().startsWith('image/'));
const taskForm = (item: MediaTask): Form => ({ customer_id: String(item.customer_id), service_progress_id: item.service_progress_id ? String(item.service_progress_id) : '', title: item.title, platform: item.platform, local_time: mediaUtcToLocal(item.due_at, item.timezone), timezone: item.timezone, assignee_id: String(item.assignee_id), content: item.content || '', material_id: item.material_id ? String(item.material_id) : '', image_version_id: item.image_version_id || '', publication: publicationForm(item.publication, item.timezone) });
const timestamp = (value: string) => {
  const date = new Date(value);
  return Number.isFinite(date.getTime()) ? new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(date) : '时间待核对';
};
const safePreviewTime = (value: string, zone: string) => { try { return mediaLocalToUtc(value, zone); } catch { return ''; } };
const isOverdue = (item: MediaTask) => item.status !== 'completed' && new Date(item.due_at).getTime() < Date.now();

export default function MediaOperations() {
  const { employee, systemRole, loading: roleLoading } = useRole();
  const owner = systemRole === 'super_admin';
  const allowed = ['super_admin', 'admin', 'ops'].includes(systemRole || '');
  const [workspace, setWorkspace] = useState<'tasks' | 'planning' | 'google' | 'materials'>(() => typeof window !== 'undefined' && new URLSearchParams(window.location.search).has('google') ? 'google' : 'tasks');
  const scope = `${employee?.id || ''}:${systemRole || ''}`;
  const scopeRef = useRef(scope); scopeRef.current = scope;
  const [resolvedScope, setResolvedScope] = useState(scope);
  const [googlePublicationEntry, setGooglePublicationEntry] = useState<GbpPublicationEntry | undefined>();
  const googleEntrySequence = useRef(0);
  const [list, setList] = useState<MediaList | null>(null);
  const [options, setOptions] = useState<MediaOptions>(emptyOptions);
  const [listLoading, setListLoading] = useState(true);
  const [optionsLoading, setOptionsLoading] = useState(false);
  const [listError, setListError] = useState('');
  const [optionsError, setOptionsError] = useState('');
  const [status, setStatus] = useState<MediaStatus | 'all'>('all');
  const [customerFilter, setCustomerFilter] = useState('all');
  const [search, setSearch] = useState('');
  const [query, setQuery] = useState('');
  const [page, setPage] = useState(1);
  const [mode, setMode] = useState<'create' | 'edit' | 'view' | null>(null);
  const [item, setItem] = useState<MediaTask | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState('');
  const [form, setForm] = useState<Form>(blankForm);
  const [action, setAction] = useState<MediaAction | null>(null);
  const [note, setNote] = useState('');
  const [proofUrl, setProofUrl] = useState('');
  const [proofMaterial, setProofMaterial] = useState('');
  const [reviewConfirmed, setReviewConfirmed] = useState(false);
  const [mutationError, setMutationError] = useState('');
  const [busy, setBusy] = useState(false);
  const [imageHold, setImageHold] = useState(false), [imageDraft, setImageDraft] = useState(false), [imagePreviewReady, setImagePreviewReady] = useState(false);
  const imageHoldRef = useRef(false);
  const [unknownResult, setUnknownResult] = useState(false);
  const [leaveChoice, setLeaveChoice] = useState(false);
  const [announcement, setAnnouncement] = useState('');
  const [copiedTaskId, setCopiedTaskId] = useState<number | null>(null);
  const [copyError, setCopyError] = useState('');
  const listSeq = useRef(0), optionSeq = useRef(0), detailSeq = useRef(0);
  const busyRef = useRef(false);
  const createId = useRef('');
  const pending = useRef<PendingMutation | null>(null);
  const activeTaskId = useRef<number | null>(null);
  const initialForm = useRef(JSON.stringify(blankForm()));
  const limit = 20;
  const customer = options.customers.find(row => String(row.id) === form.customer_id);
  const detailCustomer = options.customers.find(row => row.id === item?.customer_id);
  const eligibleAssignees = options.assignees.filter(row => !row.eligible_customer_ids || row.eligible_customer_ids.includes(Number(form.customer_id)));
  const formDirty = (mode === 'create' || mode === 'edit') && JSON.stringify(form) !== initialForm.current;
  const actionDirty = mode !== null && Boolean(action && (note.trim() || proofUrl.trim() || proofMaterial || reviewConfirmed));
  const dirty = formDirty || actionDirty || imageDraft;
  const draftGuard = useUnsavedChanges(dirty);
  const navigationHold = useHardNavigationBlock(busy || unknownResult || imageHold);
  const canCreate = list?.capabilities?.can_create === true && !optionsLoading && !optionsError && options.customers.some(row => row.can_write);

  const loadList = useCallback(async (clear = false) => {
    if (!allowed) { setListLoading(false); return; }
    const sequence = ++listSeq.current, identity = scope;
    if (clear) setList(null);
    setListLoading(true); setListError('');
    const params = new URLSearchParams({ skip: String((page - 1) * limit), limit: String(limit) });
    if (status !== 'all') params.set('status', status);
    if (customerFilter !== 'all') params.set('customer_id', customerFilter);
    if (query.trim()) params.set('q', query.trim());
    try {
      const result = await mediaOperationsApi<MediaList>(`?${params}`);
      if (listSeq.current !== sequence || scopeRef.current !== identity) return;
      if (!result || !Array.isArray(result.items) || !Number.isSafeInteger(result.total) || result.total < 0 || !result.summary || !result.capabilities) throw new Error('运营列表返回不完整');
      result.items.forEach(row => verifiedMediaTask(row));
      setList(result);
    } catch (error) {
      if (listSeq.current !== sequence || scopeRef.current !== identity) return;
      setList(null); setListError(mediaError(error));
      if ([401, 403, 404].includes(mediaErrorStatus(error) || 0)) { setItem(null); setMode(null); setOptions(emptyOptions); }
    } finally { if (listSeq.current === sequence && scopeRef.current === identity) setListLoading(false); }
  }, [allowed, customerFilter, page, query, scope, status]);

  const loadOptions = useCallback(async () => {
    if (!allowed) return;
    const sequence = ++optionSeq.current, identity = scope;
    setOptionsLoading(true); setOptionsError('');
    try {
      const result = await mediaOperationsApi<MediaOptions>('/options');
      if (sequence !== optionSeq.current || scopeRef.current !== identity) return;
      if (!result || !Array.isArray(result.customers) || !Array.isArray(result.assignees) || !Array.isArray(result.platforms)) throw new Error('授权资料返回不完整');
      setOptions(result);
    } catch (error) { if (sequence === optionSeq.current && scopeRef.current === identity) { setOptions(emptyOptions); setOptionsError(mediaError(error, '授权客户和素材暂时无法读取。')); } }
    finally { if (sequence === optionSeq.current && scopeRef.current === identity) setOptionsLoading(false); }
  }, [allowed, scope]);

  useEffect(() => {
    listSeq.current++; optionSeq.current++; detailSeq.current++;
    setList(null); setOptions(emptyOptions); setItem(null); setMode(null); setForm(blankForm()); setGooglePublicationEntry(undefined);
    setAction(null); setNote(''); setProofUrl(''); setProofMaterial(''); setMutationError(''); setDetailError('');
    setUnknownResult(false); setImageHold(false); setImageDraft(false); imageHoldRef.current=false; setImagePreviewReady(false); pending.current = null; activeTaskId.current = null; createId.current = ''; busyRef.current = false; setBusy(false);
    draftGuard.markSaved(); navigationHold.release();
    setSearch(''); setQuery(''); setStatus('all'); setCustomerFilter('all'); setPage(1); setAnnouncement(''); setCopyError(''); setCopiedTaskId(null); setResolvedScope(scope);
    return () => { listSeq.current++; optionSeq.current++; detailSeq.current++; };
  }, [scope]);
  useEffect(() => { void loadList(true); return () => { listSeq.current++; }; }, [loadList]);
  useEffect(() => { void loadOptions(); return () => { optionSeq.current++; }; }, [loadOptions]);
  useEffect(() => { const timer = window.setTimeout(() => { setQuery(search); setPage(1); }, 250); return () => window.clearTimeout(timer); }, [search]);

  async function readDetail(id: number, preserveForm = false, nextAction?: 'return') {
    activeTaskId.current = id;
    setCopiedTaskId(null); setCopyError('');
    const sequence = ++detailSeq.current, identity = scope;
    setDetailLoading(true); setDetailError('');
    if (!preserveForm) { setItem(null); setMode('view'); setAction(null); setMutationError(''); }
    try {
      const result = verifiedMediaTask(await mediaOperationsApi<MediaTask>(`/${id}`), id);
      if (sequence !== detailSeq.current || scopeRef.current !== identity) return;
      setItem(result); setImagePreviewReady(false);
      if (nextAction === 'return' && (result.permissions.can_return || result.permissions.can_review)) { setAction('return'); setNote(''); setProofUrl(''); setProofMaterial(''); setReviewConfirmed(false); }
    } catch (error) {
      if (sequence !== detailSeq.current || scopeRef.current !== identity) return;
      setItem(null); setDetailError(mediaError(error));
      if ([401, 403, 404].includes(mediaErrorStatus(error) || 0)) { setOptions(emptyOptions); void loadList(true); }
    } finally { if (sequence === detailSeq.current && scopeRef.current === identity) setDetailLoading(false); }
  }

  function updateForm<K extends keyof Form>(key: K, value: Form[K]) { if(imageDraft && ['material_id','platform'].includes(key)){setMutationError('请先保存或放弃正在准备的配图，再更换素材或平台。');return;} setForm(current => ({ ...current, [key]: value, ...(key === 'material_id' || key === 'platform' && value !== 'google_business' ? {image_version_id: ''} : {}) })); setMutationError(''); }
  function chooseCustomer(value: string) {
    if(imageDraft){setMutationError('请先保存或放弃正在准备的配图，再更换客户。');return;}
    const eligible = options.assignees.filter(row => !row.eligible_customer_ids || row.eligible_customer_ids.includes(Number(value)));
    setForm(current => ({ ...current, customer_id: value, service_progress_id: '', material_id: '', image_version_id: '', assignee_id: eligible.some(row => row.id === Number(employee?.id)) ? String(employee?.id) : eligible.length === 1 ? String(eligible[0].id) : '' }));
  }
  function openCreate() {
    if (busyRef.current || unknownResult || !canCreate) return;
    const next = blankForm();
    if (customerFilter !== 'all' && options.customers.some(row => row.id === Number(customerFilter) && row.can_write)) next.customer_id = customerFilter;
    next.assignee_id = String(employee?.id || '');
    setForm(next); initialForm.current = JSON.stringify(next); createId.current = mediaRequestId();
    setItem(null); setMode('create'); setAction(null); setMutationError(''); setDetailError(''); setLeaveChoice(false);
  }
  function openEdit() {
    if (!item?.permissions.can_edit || busyRef.current || unknownResult) return;
    const next = taskForm(item); setForm(next); initialForm.current = JSON.stringify(next); setMode('edit'); setAction(null); setMutationError('');
  }
  function closeDialog() {
    if (busyRef.current || imageHoldRef.current) return;
    if (dirty && !unknownResult && !leaveChoice) { setLeaveChoice(true); return; }
    detailSeq.current++; setMode(null); setItem(null); setAction(null); setNote(''); setProofUrl(''); setProofMaterial(''); setReviewConfirmed(false); setLeaveChoice(false); setMutationError(''); setDetailError(''); draftGuard.markSaved();
  }
  function beginAction(next: MediaAction) {
    setAction(next); setNote(''); setProofUrl(''); setProofMaterial(''); setReviewConfirmed(false); setMutationError('');
  }

  async function copyContent() {
    if (!item?.content) return;
    const identity = scope, id = item.id;
    try {
      if (!navigator.clipboard?.writeText) throw new Error('Clipboard unavailable');
      await navigator.clipboard.writeText(item.content);
      if (scopeRef.current !== identity || activeTaskId.current !== id) return;
      setCopiedTaskId(id); setCopyError(''); setAnnouncement('正文已复制；活动、优惠条款与按钮请一并核对后再发布。');
    } catch {
      if (scopeRef.current === identity && activeTaskId.current === id) setCopyError('暂时无法自动复制，可以在下方选中文字后手动复制。');
    }
  }

  function acceptMutation(result: MediaTask) {
    detailSeq.current++; setDetailLoading(false); setDetailError(''); setItem(result); setMode('view'); setAction(null); activeTaskId.current = result.id;
    setForm(taskForm(result)); initialForm.current = JSON.stringify(taskForm(result));
    pending.current = null; createId.current = ''; setUnknownResult(false); setLeaveChoice(false); draftGuard.markSaved(); navigationHold.release();
    setAnnouncement(`已保存：${mediaStatusLabels[result.status]}`);
    void loadList();
  }

  async function runMutation(request: PendingMutation) {
    if (busyRef.current) return;
    const identity = scope;
    navigationHold.lock(); busyRef.current = true; setBusy(true); setMutationError(''); pending.current = request;
    try {
      const result = verifiedMediaTask(await mediaOperationsApi<MediaTask>(request.path, request.method, request.data), request.expectedId);
      if (scopeRef.current !== identity) return;
      acceptMutation(result);
    } catch (error) {
      if (scopeRef.current !== identity) return;
      const code = mediaErrorStatus(error);
      if (!code || code >= 500) { setUnknownResult(true); setMutationError('操作结果尚未确认。请重新确认结果，系统会沿用本次请求编号，避免重复保存。'); }
      else {
        pending.current = null; setUnknownResult(false); navigationHold.release(); setMutationError(mediaError(error, '填写内容尚不符合要求，请检查后重试。'));
        if ([401, 403, 404].includes(code)) { setItem(null); setOptions(emptyOptions); setMode(null); void loadList(true); }
        else if (code === 409 && request.expectedId) {
          // A colleague's newer revision must be read before a fresh edit.
          // Never attach its revision to this user's stale form values.
          setMode('view'); setItem(null); setAction(null); setNote(''); setProofUrl(''); setProofMaterial(''); setReviewConfirmed(false); draftGuard.markSaved();
          setMutationError('内容已更新，请核对最新版本后重新编辑。');
          void readDetail(request.expectedId, true); void loadList();
        }
      }
    } finally { if (scopeRef.current === identity) { busyRef.current = false; setBusy(false); } }
  }

  async function recoverUnknown() {
    const request = pending.current;
    if (!request || busyRef.current) return;
    // Creation and transitions have durable request IDs. Draft updates use CAS;
    // read the persisted task before deciding whether that same update is safe.
    if (request.method !== 'PUT' || !request.expectedId) { void runMutation(request); return; }
    const identity = scope;
    navigationHold.lock(); busyRef.current = true; setBusy(true); setMutationError('');
    let retry = false;
    try {
      const current = verifiedMediaTask(await mediaOperationsApi<MediaTask>(`/${request.expectedId}`), request.expectedId);
      if (scopeRef.current !== identity) return;
      const sent = request.data as Record<string, unknown>;
      const matches = Object.entries(sent).filter(([key]) => key !== 'expected_revision').every(([key, value]) => key === 'due_at'
        ? new Date(current.due_at).getTime() === new Date(String(value)).getTime()
        : key === 'publication' ? publicationEquivalent(current.publication, value) : (current as unknown as Record<string, unknown>)[key] === value);
      if (current.revision > Number(sent.expected_revision) && matches) acceptMutation(current);
      else if (current.revision === Number(sent.expected_revision)) retry = true;
      else {
        pending.current = null; setUnknownResult(false); navigationHold.release(); draftGuard.markSaved(); setItem(current); setMode('view'); setAction(null); activeTaskId.current = current.id;
        setForm(taskForm(current)); initialForm.current = JSON.stringify(taskForm(current));
        setMutationError('已读取最新任务，内容或状态已发生变化。请核对当前资料后再决定下一步。'); void loadList();
      }
    } catch (error) {
      if (scopeRef.current !== identity) return;
      if ([401, 403, 404].includes(mediaErrorStatus(error) || 0)) { pending.current = null; setUnknownResult(false); navigationHold.release(); draftGuard.markSaved(); setItem(null); setMode(null); setOptions(emptyOptions); void loadList(true); }
      else setMutationError('暂时仍无法确认保存结果，请稍后重新确认。');
    } finally { if (scopeRef.current === identity) { busyRef.current = false; setBusy(false); } }
    if (retry && scopeRef.current === identity) void runMutation(request);
  }

  function saveForm() {
    if (busyRef.current || unknownResult || imageHoldRef.current) return;
    try {
      if(imageDraft) throw new Error('请先保存或放弃当前配图准备，再保存任务草稿。');
      if (form.image_version_id && !imageVersionId(form.image_version_id)) throw new Error('请选择有效的固定图片版本。');
      if (!form.title.trim()) throw new Error('请填写任务标题。');
      if (!form.customer_id || !customer?.can_write) throw new Error('请选择有协作授权的客户。');
      const due_at = mediaLocalToUtc(form.local_time, form.timezone);
      const publication = publicationPayload(form.publication, form.timezone, form.platform);
      const payload = { ...(publication ? { publication } : {}), title: form.title.trim(), platform: form.platform, due_at, timezone: form.timezone, content: form.content, material_id: form.material_id ? Number(form.material_id) : null, image_version_id: form.platform === 'google_business' && form.image_version_id ? form.image_version_id : null };
      if (mode === 'edit' && item) void runMutation({ path: `/${item.id}`, method: 'PUT', expectedId: item.id, data: { ...payload, expected_revision: item.revision, ...(owner && form.assignee_id ? { assignee_id: Number(form.assignee_id) } : {}) } });
      else {
        if (!createId.current) createId.current = mediaRequestId();
        void runMutation({ path: '', method: 'POST', data: { ...payload, client_request_id: createId.current, customer_id: Number(form.customer_id), service_progress_id: form.service_progress_id ? Number(form.service_progress_id) : null, ...(form.assignee_id ? { assignee_id: Number(form.assignee_id) } : {}) } });
      }
    } catch (error) { setMutationError(error instanceof Error ? error.message : '请核对填写内容。'); }
  }

  function performAction() {
    if (!action || !item || busyRef.current || unknownResult) return;
    if (['return', 'block'].includes(action) && note.trim().length < 3) { setMutationError('请填写至少 3 个字的原因，方便下一位同事继续处理。'); return; }
    if (action === 'approve' && item.image_version_id && !imagePreviewReady) { setMutationError('请先成功读取并核对服务器保存的最终配图，再确认审核。'); return; }
    if (action === 'approve' && !reviewConfirmed) { setMutationError('请先确认内容事实、品牌语气和素材已核对。'); return; }
    if (action === 'complete' && !proofUrl.trim() && !proofMaterial) { setMutationError('请填写发布链接，或选择该客户已授权的发布截图。'); return; }
    if (action === 'complete' && proofUrl.trim() && !mediaSafeProofUrl(proofUrl.trim())) { setMutationError('发布链接需要是有效的 HTTPS 地址。'); return; }
    void runMutation({ path: `/${item.id}/transition`, method: 'POST', expectedId: item.id, data: { expected_revision: item.revision, request_id: mediaRequestId(), action, ...(note.trim() ? { note: note.trim() } : {}), ...(action === 'complete' ? { proof_url: proofUrl.trim() || null, proof_material_id: proofMaterial ? Number(proofMaterial) : null } : {}) } });
  }

  const filteredOptions = useMemo(() => [{ value: 'all', label: '全部授权客户' }, ...options.customers.map(row => ({ value: String(row.id), label: row.name }))], [options.customers]);
  const schedulePreview = useMemo(() => { if (!form.local_time) return ''; try { return `${mediaUtcToLocal(mediaLocalToUtc(form.local_time, form.timezone), 'Asia/Shanghai').replace('T', ' ')} 北京时间`; } catch (error) { return error instanceof Error ? error.message : ''; } }, [form.local_time, form.timezone]);
  const priority = list?.items.find(row => row.status === 'blocked') || list?.items.find(row => isOverdue(row)) || list?.items.find(row => owner ? row.status === 'in_review' : row.status === 'ready') || list?.items.find(row => row.status !== 'completed');
  const modalEditing = mode === 'create' || mode === 'edit';
  const readOnly = busy || unknownResult || imageHold;
  const optionLabel = (value: string) => options.platforms.find(row => row.value === value)?.label || value;
  function changeWorkspace(next: 'tasks' | 'planning' | 'google' | 'materials') {
    if (next === workspace || busyRef.current || unknownResult || imageHoldRef.current || !confirmDiscardAllChanges()) return;
    draftGuard.markSaved(); setMode(null); setItem(null); setAction(null); setLeaveChoice(false); setMutationError('');
    setGooglePublicationEntry(undefined); setWorkspace(next);
  }
  function openGooglePublication() {
    if (!item || item.platform !== 'google_business' || !['draft', 'in_review', 'ready'].includes(item.status) || busyRef.current || unknownResult || imageHoldRef.current || dirty) return;
    const target = { key: ++googleEntrySequence.current, customerId: item.customer_id, taskId: item.id, preview: item.status === 'ready' };
    closeDialog(); setGooglePublicationEntry(target); setWorkspace('google');
  }

  if (roleLoading || resolvedScope !== scope) return <div className="mo-loading"><Loader2 className="animate-spin" aria-hidden="true"/>正在确认访问范围…</div>;
  if (!allowed) return <section className="media-operations mo-denied"><LockKeyhole aria-hidden="true"/><h1>代运营中心尚未向此账号开放</h1><p>由老板邀请运营人员，并单独授权客户交付资料。</p></section>;

  return <main className={`media-operations app-page${workspace === 'google' ? ' mo-google-mode' : ''}`} aria-label="代运营中心">
    <header className="mo-page-header"><div><p className="mo-eyebrow">任务与交付 · 代运营</p><h1>代运营中心</h1><p className="mo-subtitle">{workspace === 'google' ? '在授权范围内处理 Google 评论和帖子。' : '准备内容、完成审核、发布后留下凭证。'}</p></div>{workspace === 'tasks' && <div className="mo-header-actions"><Button variant="outline" onClick={() => { void loadList(); void loadOptions(); }} disabled={listLoading || busy} aria-label="刷新运营资料"><RefreshCw className={listLoading ? 'animate-spin' : ''} aria-hidden="true"/><span>刷新</span></Button><Button onClick={openCreate} disabled={!canCreate || busy || unknownResult}><Plus aria-hidden="true"/>新增任务</Button></div>}</header>
    <div className="mo-workspace-switch" role="group" aria-label="代运营工作区"><button className={workspace === 'tasks' ? 'active' : ''} aria-pressed={workspace === 'tasks'} onClick={() => changeWorkspace('tasks')}><ListChecks aria-hidden="true"/>运营任务</button><button className={workspace === 'planning' ? 'active' : ''} aria-pressed={workspace === 'planning'} onClick={() => changeWorkspace('planning')}><CalendarDays aria-hidden="true"/>内容编排</button><button className={workspace === 'google' ? 'active' : ''} aria-pressed={workspace === 'google'} onClick={() => changeWorkspace('google')}><Globe2 aria-hidden="true"/>Google 商家</button><button className={workspace === 'materials' ? 'active' : ''} aria-pressed={workspace === 'materials'} onClick={() => changeWorkspace('materials')}><Image aria-hidden="true"/>客户素材</button></div>
    <MediaPlatformCapabilities key={scope} scope={scope}/>
    {workspace === 'google' ? <GoogleBusinessManagement scope={scope} isOwner={owner} publicationEntry={googlePublicationEntry} onCreateTask={() => { if (busyRef.current || unknownResult || !confirmDiscardAllChanges()) return; setWorkspace('tasks'); openCreate(); }} onOpenTask={(id, nextAction) => { if (busyRef.current || unknownResult || !confirmDiscardAllChanges()) return; setWorkspace('tasks'); void readDetail(id, false, nextAction); }}/> : workspace === 'materials' ? <MediaTeamMaterials key={scope} scope={scope} customers={options.customers} initialCustomerId={customerFilter !== 'all' ? Number(customerFilter) : undefined} onChanged={() => void loadOptions()} loading={optionsLoading} error={optionsError} onRetry={() => void loadOptions()}/> : workspace === 'planning' ? <MediaPlanningWorkspace key={scope} scope={scope} customers={options.customers} assignees={options.assignees} onOpenTask={id=>{if(busyRef.current||unknownResult||!confirmDiscardAllChanges())return;setWorkspace('tasks');void readDetail(id);}} onCreateTask={()=>{if(busyRef.current||unknownResult||!confirmDiscardAllChanges())return;setWorkspace('tasks');openCreate();}} onChanged={()=>{void loadList();void loadOptions();}}/> : <>
    <div className="mo-scope"><ShieldCheck aria-hidden="true"/><span>{owner ? '老板视角 · 查看全部运营交付，审核后进入发布' : '我的工作 · 仅显示本人负责且老板已授权的客户任务'}</span><span className="mo-manual-tag">按平台能力执行 · 凭证留痕</span></div>
    <p className="sr-only" role="status" aria-live="polite">{announcement}</p>
    {unknownResult && <div className="mo-alert mo-alert-warn" role="alert"><AlertCircle aria-hidden="true"/><div><strong>上次操作结果待确认</strong><p>请先确认结果，再继续修改或新增任务。</p></div><Button variant="outline" disabled={busy} onClick={() => void recoverUnknown()}>{busy ? '正在确认…' : '重新确认结果'}</Button></div>}
    {optionsError && <div className="mo-alert" role="alert"><AlertCircle aria-hidden="true"/><span>{optionsError}</span><Button variant="ghost" size="sm" onClick={() => void loadOptions()} disabled={optionsLoading}>重新读取授权资料</Button></div>}
    <section className="mo-overview" aria-label="运营任务概况">
      <button className={status === 'blocked' ? 'mo-metric mo-metric-warning active' : 'mo-metric mo-metric-warning'} onClick={() => { setStatus('blocked'); setPage(1); }}><span><AlertCircle aria-hidden="true"/>需处理</span><strong>{list?.summary.blocked ?? '—'}</strong><small>缺资料、执行遇阻</small></button>
      <div className="mo-metric"><span><Clock3 aria-hidden="true"/>已逾期</span><strong>{list?.summary.overdue ?? '—'}</strong><small>尚未完成的计划任务</small></div>
      <button className={status === 'in_review' ? 'mo-metric active' : 'mo-metric'} onClick={() => { setStatus('in_review'); setPage(1); }}><span><ListChecks aria-hidden="true"/>待审核</span><strong>{list?.summary.in_review ?? '—'}</strong><small>确认后交给发布执行</small></button>
      <button className={status === 'ready' ? 'mo-metric active' : 'mo-metric'} onClick={() => { setStatus('ready'); setPage(1); }}><span><CalendarDays aria-hidden="true"/>待发布</span><strong>{list?.summary.ready ?? '—'}</strong><small>发布后提交链接或截图</small></button>
    </section>
    {priority && !listLoading && <section className="mo-next" aria-label="建议优先处理"><div className="mo-next-icon"><ArrowRight aria-hidden="true"/></div><div><small>{owner ? '先看这一项' : '接下来处理'}</small><strong>{priority.customer_name} · {priority.title}</strong><span>{priority.status === 'blocked' ? priority.block_reason || '需要补充资料或处理异常' : `${mediaStatusLabels[priority.status]} · ${mediaScheduleLabel(priority.due_at, priority.timezone)}`}</span></div><Button variant="outline" onClick={() => void readDetail(priority.id)}>打开任务<ArrowRight aria-hidden="true"/></Button></section>}
    <section className="mo-workspace" aria-label="运营任务列表">
      <div className="mo-stages" role="group" aria-label="按任务阶段筛选"><button className={status === 'all' ? 'active' : ''} aria-pressed={status === 'all'} onClick={() => { setStatus('all'); setPage(1); }}>全部</button>{stages.map(stage => <button key={stage} className={status === stage ? 'active' : ''} aria-pressed={status === stage} onClick={() => { setStatus(stage); setPage(1); }}>{mediaStatusLabels[stage]}<span>{list?.summary[stage] ?? '—'}</span></button>)}</div>
      <div className="mo-filters"><label className="mo-search"><Search aria-hidden="true"/><Input value={search} onChange={event => setSearch(event.target.value)} placeholder="搜索客户或任务" aria-label="搜索客户或任务"/></label><NativeSelect aria-label="筛选授权客户" value={customerFilter} onChange={value => { setCustomerFilter(value); setPage(1); }} options={filteredOptions}/></div>
      {listError ? <div className="mo-empty" role="alert"><AlertCircle aria-hidden="true"/><h2>运营资料暂时无法读取</h2><p>{listError}</p><Button variant="outline" onClick={() => void loadList(true)}>重新读取</Button></div> : listLoading ? <div className="mo-empty" aria-live="polite"><Loader2 className="animate-spin" aria-hidden="true"/><h2>正在读取运营任务</h2><p>按当前账号和客户授权确认范围。</p></div> : !list?.items.length ? <div className="mo-empty"><FileText aria-hidden="true"/><h2>{query || customerFilter !== 'all' || status !== 'all' ? '这个范围还没有任务' : '从第一项运营任务开始'}</h2><p>{owner ? '选择客户、负责人和计划时间，内容准备后再提交审核。' : '任务分配给你，并获得客户交付授权后，会显示在这里。'}</p>{canCreate && <Button onClick={openCreate} disabled={unknownResult}><Plus aria-hidden="true"/>新增运营任务</Button>}</div> : <><div className="mo-table-head" aria-hidden="true"><span>客户 / 任务</span><span>任务截止</span><span>负责人</span><span>阶段</span><span/></div><div className="mo-task-list">{list.items.map(row => <button key={row.id} className="mo-task-row" onClick={() => void readDetail(row.id)} aria-label={`查看任务：${row.customer_name}，${row.title}`}><span className="mo-task-name"><strong>{row.title}</strong><small>{row.customer_name}<i>·</i>{optionLabel(row.platform)}</small></span><span className={`mo-task-time ${isOverdue(row) ? 'overdue' : ''}`}><CalendarDays aria-hidden="true"/>{mediaUtcToLocal(row.due_at, row.timezone).replace('T', ' ')}<small>{row.timezone}{isOverdue(row) ? ' · 已逾期' : ''}</small></span><span className="mo-task-assignee">{row.assignee_name}</span><span className={`mo-status mo-status-${row.status}`}>{mediaStatusLabels[row.status]}</span><ChevronRight className="mo-row-arrow" aria-hidden="true"/></button>)}</div><footer className="mo-pagination"><span>共 {list.total} 项 · 第 {page} / {Math.max(1, Math.ceil(list.total / limit))} 页</span><div><Button variant="outline" size="sm" onClick={() => setPage(current => Math.max(1, current - 1))} disabled={page <= 1 || listLoading} aria-label="上一页"><ChevronLeft aria-hidden="true"/></Button><Button variant="outline" size="sm" onClick={() => setPage(current => current + 1)} disabled={page * limit >= list.total || listLoading} aria-label="下一页"><ChevronRight aria-hidden="true"/></Button></div></footer></>}
    </section>
    <p className="mo-boundary"><LockKeyhole aria-hidden="true"/>仅管理运营交付。人工发布后再确认完成，内容审核不会立即发布或记账；Google 排期仍须有相应授权并明确确认。</p>

    <Dialog open={mode !== null} onOpenChange={open => { if (!open) closeDialog(); }}>
      <CrmFormDialogContent className="mo-dialog" onEscapeKeyDown={event => { if (busy || dirty) { event.preventDefault(); if (!busy) setLeaveChoice(true); } }} onPointerDownOutside={event => { if (busy || dirty) { event.preventDefault(); if (!busy) setLeaveChoice(true); } }}>
        <CrmFormDialogHeader><DialogTitle>{mode === 'create' ? '新增运营任务' : mode === 'edit' ? '编辑运营草稿' : item?.title || '运营任务'}</DialogTitle><DialogDescription>{modalEditing ? '明确客户、负责人和计划时间，准备完成后再提交审核。' : item ? `${item.customer_name} · ${optionLabel(item.platform)} · ${mediaStatusLabels[item.status]}` : '正在读取已授权的任务资料。'}</DialogDescription></CrmFormDialogHeader>
        <CrmFormDialogBody>
          {leaveChoice && <div className="mo-alert mo-alert-warn"><div><strong>还有未保存的内容</strong><p>可以继续填写，也可以放弃本次修改。</p></div><Button variant="outline" size="sm" onClick={() => setLeaveChoice(false)}>继续填写</Button><Button variant="ghost" size="sm" onClick={() => { initialForm.current = JSON.stringify(form); draftGuard.markSaved(); setLeaveChoice(false); setMode(null); setItem(null); setAction(null); setNote(''); setProofUrl(''); setProofMaterial(''); setReviewConfirmed(false); }}>放弃修改</Button></div>}
          {detailLoading ? <div className="mo-dialog-loading"><Loader2 className="animate-spin" aria-hidden="true"/>正在读取任务…</div> : detailError ? <div className="mo-alert" role="alert"><AlertCircle aria-hidden="true"/><span>{detailError}</span>{activeTaskId.current && <Button variant="outline" size="sm" onClick={() => void readDetail(activeTaskId.current!)}>重新读取</Button>}</div> : modalEditing ? <div className="mo-form">
            <div className="mo-form-grid"><label>客户（必填）<NativeSelect aria-label="任务客户" value={form.customer_id} onChange={chooseCustomer} disabled={mode === 'edit' || readOnly || optionsLoading} options={[{ value: '', label: '选择已授权客户' }, ...options.customers.filter(row => row.can_write).map(row => ({ value: String(row.id), label: row.name }))]}/></label><label>关联服务<NativeSelect aria-label="关联服务" value={form.service_progress_id} onChange={value => updateForm('service_progress_id', value)} disabled={mode === 'edit' || readOnly || !customer} options={[{ value: '', label: '客户运营任务（不关联具体服务）' }, ...(customer?.services || []).map(row => ({ value: String(row.id), label: row.name }))]}/></label></div>
            <label>任务标题（必填）<Input aria-label="任务标题" value={form.title} onChange={event => updateForm('title', event.target.value)} placeholder="例如：本周 Instagram 门店介绍" maxLength={200} disabled={readOnly}/></label>
            <div className="mo-form-grid"><label>发布平台<NativeSelect aria-label="发布平台" value={form.platform} onChange={value => updateForm('platform', value)} disabled={readOnly} options={options.platforms}/></label><label>主要负责人{owner ? <NativeSelect aria-label="主要负责人" value={form.assignee_id} onChange={value => updateForm('assignee_id', value)} disabled={readOnly || !form.customer_id} options={[{ value: '', label: '选择具有客户协作授权的同事' }, ...eligibleAssignees.map(row => ({ value: String(row.id), label: row.name }))]}/> : <Input value={employee?.name || '本人'} disabled aria-label="主要负责人"/>}</label></div>
            {owner && customer && eligibleAssignees.length === 0 && <p className="mo-help">此客户暂无具备运营协作权限的员工，可由老板负责，或先在客户中心邀请同事。</p>}
            <div className="mo-schedule"><div className="mo-form-grid"><label>商家时区<NativeSelect aria-label="商家时区" value={form.timezone} onChange={value => updateForm('timezone', value)} disabled={readOnly} options={mediaTimezones.some(row => row.value === form.timezone) ? mediaTimezones : [...mediaTimezones, { value: form.timezone, label: form.timezone }]}/></label><label>计划发布时间（必填）<Input aria-label="计划发布时间" type="datetime-local" value={form.local_time} onInput={event => updateForm('local_time', event.currentTarget.value)} onChange={event => updateForm('local_time', event.target.value)} disabled={readOnly}/></label></div><p>{schedulePreview || '按选定的商家时区填写；系统会自动换算北京时间。'} 这是准备完成目标，不会自动创建 Google 发布排期。</p></div>
            <label>内容草稿<Textarea aria-label="内容草稿" value={form.content} onChange={event => updateForm('content', event.target.value)} placeholder="可以先保存空草稿；提交审核前请补齐完整发布内容。" rows={7} maxLength={20000} disabled={readOnly}/></label>
            {form.platform === 'google_business' ? <MediaPublicationFields value={form.publication} onChange={value => updateForm('publication', value)} disabled={readOnly}/> : <p className="mo-platform-note">{optionLabel(form.platform)} 当前只创建人工发布任务，不发送 Google 帖型、优惠或行动按钮字段。</p>}
            <label>关联素材<NativeSelect aria-label="关联素材" value={form.material_id} onChange={value => updateForm('material_id', value)} disabled={readOnly || !customer} options={[{ value: '', label: '暂不关联素材' }, ...(customer?.materials || []).map(row => ({ value: String(row.id), label: row.title }))]}/><span className="mo-help">仅列出该客户已授权的团队素材。私有 JPEG／PNG 图片可在下方准备固定发布版本；外部图片链接保留原方式。视频仅准备。</span></label>
            {form.platform === 'google_business' && customer && form.material_id && (customer.materials.find(row => row.id === Number(form.material_id))?.has_private_file || form.image_version_id) && <MediaPublicationImage key={`${scope}:${customer.id}:${form.material_id}`} scope={scope} customerId={customer.id} materialId={Number(form.material_id)} value={form.image_version_id} canPrepare={customer.can_prepare_images === true} disabled={busy || unknownResult} onChange={value => updateForm('image_version_id', value)} onHoldChange={active => {imageHoldRef.current=active;setImageHold(active);}} onDraftChange={setImageDraft} onChanged={() => void loadOptions()}/>}
            <details className="mo-draft-preview"><summary>核对完整内容预览</summary><div className="mo-copy">{form.content || '正文尚未填写'}</div>{form.platform === 'google_business' && <MediaPublicationPreview publication={{topic_type:form.publication.topic_type,...(form.publication.topic_type!=='STANDARD'?{event:{title:form.publication.event_title,start_at:safePreviewTime(form.publication.event_start,form.timezone),end_at:safePreviewTime(form.publication.event_end,form.timezone)}}:{}),...(form.publication.topic_type==='OFFER'?{offer:{coupon_code:form.publication.coupon_code,redeem_online_url:form.publication.redeem_online_url,terms_conditions:form.publication.terms_conditions}}:{}),...(form.publication.topic_type!=='OFFER'&&form.publication.action_type?{call_to_action:{action_type:form.publication.action_type as NonNullable<MediaPublication['call_to_action']>['action_type'],url:form.publication.action_url}}:{})}} timezone={form.timezone} heading="草稿结构预览"/>}</details>
          </div> : item && <div className="mo-detail">
            <div className="mo-detail-meta"><span className={`mo-status mo-status-${item.status}`}>{mediaStatusLabels[item.status]}</span><span>{item.assignee_name} 负责</span><span>任务 #{item.id}</span></div>
            <section className="mo-detail-schedule"><CalendarDays aria-hidden="true"/><div><span className="mo-task-deadline-label">任务截止 · 准备完成目标</span><strong>{mediaUtcToLocal(item.due_at, item.timezone).replace('T', ' ')}</strong><small>{item.timezone} · 北京时间 {mediaUtcToLocal(item.due_at, 'Asia/Shanghai').replace('T', ' ')}</small></div>{isOverdue(item) && <span className="mo-overdue-tag">已逾期</span>}</section>
            {item.platform === 'google_business' && ['draft', 'in_review', 'ready'].includes(item.status) && !action && (owner || Object.values(item.permissions).some(Boolean)) && <section className="mo-google-handoff" aria-label="Google 开工与发布下一步"><p>{item.status === 'ready' ? '内部审核已通过。请前往对应 Google 门店核对最终图文和实际排期；提交发布凭证不会代替 Google 发帖。' : '先核对对应 Google 门店、素材和审核准备情况。查看开工清单不会审核通过、发帖或创建排期。'}</p><Button variant="outline" onClick={openGooglePublication} disabled={busy || unknownResult || imageHold}>{item.status === 'ready' ? '前往 Google 核对发布' : '查看 Google 开工清单'}<ArrowRight aria-hidden="true"/></Button></section>}
            {item.block_reason && <div className="mo-alert mo-alert-warn"><AlertCircle aria-hidden="true"/><div><strong>当前需要处理</strong><p>{item.block_reason}</p></div></div>}
            {item.review_note && <div className="mo-review-note"><ListChecks aria-hidden="true"/><div><strong>审核说明</strong><p>{item.review_note}</p></div></div>}
            <section><div className="mo-copy-heading"><h3><FileText aria-hidden="true"/>发布内容</h3><Button variant="ghost" size="sm" onClick={() => void copyContent()} disabled={!item.content}><Copy aria-hidden="true"/>{copiedTaskId === item.id ? '已复制' : '复制文案'}</Button></div>{copyError && <p className="mo-help" role="status">{copyError}</p>}<div className={item.content ? 'mo-copy' : 'mo-copy mo-copy-empty'}>{item.content || '还没有填写内容草稿。编辑并补齐内容后，提交审核。'}</div></section>
            {item.platform === 'google_business' && <MediaPublicationPreview publication={item.publication} timezone={item.timezone} heading="审核与发布结构"/>}
            <section className="mo-detail-material"><Image aria-hidden="true"/><div><strong>关联素材</strong><span>{item.material_title || '暂未关联素材'}</span>{item.platform === 'google_business' && item.material_id && !item.publication_image && <p className="mo-help">私有图片需先准备固定发布版本。若使用外部公开图片链接，请在审核时核对实际图片；关联素材不代表已经满足发布条件。</p>}</div></section>
            {item.publication_image && <PublicationImagePreview key={`${scope}:${item.publication_image.id}`} scope={scope} image={item.publication_image} title="本次审核和发布使用的固定配图" onStateChange={state => setImagePreviewReady(state === 'ready' && item.publication_image?.status === 'ready')}/>}
            {item.publication_image && item.publication_image.status !== 'ready' && <p className="mo-alert mo-alert-warn">固定配图的原素材或使用状态已变化，请退回草稿并重新准备、审核。</p>}
            {item.image_version_id && !item.publication_image && <p className="mo-alert mo-alert-warn">当前固定图片版本或独立素材授权不可用，请重新核对；暂不能确认图片审核。</p>}
            {(item.proof_url || item.proof_material_id || item.completed_at) && <section className="mo-proof"><h3><CheckCircle2 aria-hidden="true"/>发布凭证</h3>{mediaSafeProofUrl(item.proof_url) && <a href={mediaSafeProofUrl(item.proof_url)!} target="_blank" rel="noopener noreferrer">查看发布链接<ExternalLink aria-hidden="true"/></a>}{item.proof_material_id && <p>发布截图：{detailCustomer?.materials.find(row => row.id === item.proof_material_id)?.title || `已关联素材 #${item.proof_material_id}`}</p>}{item.completed_at && <small>确认完成于 {timestamp(item.completed_at)}（北京时间）</small>}</section>}
            {action && <section className="mo-action-form" aria-label={mediaActionLabels[action]}><h3>{mediaActionLabels[action]}</h3>{action === 'complete' && <><p>请先在对应平台完成发布，再提交真实的链接或截图。</p><label>发布链接<Input aria-label="发布链接" value={proofUrl} onChange={event => setProofUrl(event.target.value)} placeholder="https://…" type="url" disabled={readOnly}/></label><label>或选择发布截图<NativeSelect aria-label="发布截图" value={proofMaterial} onChange={setProofMaterial} disabled={readOnly} options={[{ value: '', label: '不选择截图' }, ...(detailCustomer?.materials || []).filter(row => isProofImage(row.material_type, row.content_type)).map(row => ({ value: String(row.id), label: row.title }))]}/></label></>}{action === 'approve' && <label className="mo-confirm"><input type="checkbox" checked={reviewConfirmed} onChange={event => setReviewConfirmed(event.target.checked)} disabled={readOnly}/><span>我已核对正文、活动或优惠起止、条款、按钮去向及素材，确认可以交给发布人员。固定配图将按此版本公开使用，原文件保持私有。</span></label>}{action === 'submit' && <p>提交后草稿将锁定，等待老板审核。审核通过后进入对应平台待发布队列；Google 发布仍须另外授权与确认。</p>}{action === 'resume' && <p>恢复后回到可继续处理的阶段，需要审核的内容仍会重新审核。</p>}<label>{['block', 'return'].includes(action) ? '原因 / 下一步 *' : '补充说明（选填）'}<Textarea aria-label="操作说明" value={note} onChange={event => setNote(event.target.value)} rows={3} maxLength={2000} disabled={readOnly} placeholder={['block', 'return'].includes(action) ? '说明缺少什么、需要谁协助。' : '为后续交接留下必要说明。'}/></label></section>}
            {!action && Array.isArray(item.events) && item.events.length > 0 && <section className="mo-history"><h3>处理记录</h3><ol>{[...item.events].reverse().map(event => <li key={event.id}><span className="mo-history-dot"/><div><strong>{mediaActionLabels[event.action as keyof typeof mediaActionLabels] || '更新任务'}<small>{event.actor_name} · {timestamp(event.created_at)}</small></strong>{event.note && <p>{event.note}</p>}</div></li>)}</ol></section>}
          </div>}
          {mutationError && <div className="mo-alert mo-alert-warn" role="alert"><AlertCircle aria-hidden="true"/><span>{mutationError}</span></div>}
        </CrmFormDialogBody>
        <CrmFormDialogFooter>
          {unknownResult ? <><Button variant="outline" onClick={closeDialog} disabled={busy}>收起</Button><Button onClick={() => void recoverUnknown()} disabled={busy}>{busy && <Loader2 className="animate-spin" aria-hidden="true"/>}重新确认结果</Button></> : modalEditing ? <><Button variant="outline" onClick={closeDialog} disabled={busy}>取消</Button><Button onClick={saveForm} disabled={busy || imageHold || imageDraft || detailLoading || optionsLoading || Boolean(optionsError)}>{busy ? <Loader2 className="animate-spin" aria-hidden="true"/> : <Check aria-hidden="true"/>}{busy ? '正在保存…' : '保存草稿'}</Button></> : action ? <><Button variant="outline" onClick={() => { setAction(null); setMutationError(''); }} disabled={busy}>取消</Button><Button onClick={performAction} disabled={busy || imageHold || action === 'approve' && (!reviewConfirmed || Boolean(item?.image_version_id && !imagePreviewReady))}>{busy && <Loader2 className="animate-spin" aria-hidden="true"/>}{busy ? '正在保存…' : mediaActionLabels[action]}</Button></> : item ? <div className="mo-detail-actions">{item.permissions.can_block && <Button variant="ghost" onClick={() => beginAction('block')} disabled={busy}>记录异常</Button>}{item.permissions.can_edit && <Button variant="outline" onClick={openEdit} disabled={busy || Boolean(optionsError)}>编辑草稿</Button>}{(item.permissions.can_review || item.permissions.can_return) && <Button variant="outline" onClick={() => beginAction('return')} disabled={busy}>退回修改</Button>}{item.permissions.can_review && <Button onClick={() => beginAction('approve')} disabled={busy}><Check aria-hidden="true"/>审核通过</Button>}{item.permissions.can_submit && <Button onClick={() => beginAction('submit')} disabled={busy}>提交审核<ArrowRight aria-hidden="true"/></Button>}{item.permissions.can_complete && <Button onClick={() => beginAction('complete')} disabled={busy}>提交发布凭证<ArrowRight aria-hidden="true"/></Button>}{item.permissions.can_resume && <Button onClick={() => beginAction('resume')} disabled={busy}>恢复处理</Button>}{!Object.values(item.permissions).some(Boolean) && <span className="mo-readonly"><LockKeyhole aria-hidden="true"/>当前为只读资料</span>}</div> : <Button variant="outline" onClick={closeDialog}>关闭</Button>}
        </CrmFormDialogFooter>
      </CrmFormDialogContent>
    </Dialog>
    </>}
  </main>;
}
