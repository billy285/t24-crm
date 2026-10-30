import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AlertCircle, ArrowRight, Check, CheckCircle2, ChevronDown, ExternalLink, FileText, Globe2, Link2, Loader2, MessageSquare, RefreshCw, Send, Settings2, ShieldCheck, Star, Unplug, Users } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { NativeSelect } from '@/components/ui/native-select';
import { Dialog, DialogTitle, DialogDescription, CrmFormDialogContent, CrmFormDialogHeader, CrmFormDialogBody, CrmFormDialogFooter } from '@/components/ui/dialog';
import { useHardNavigationBlock, useUnsavedChanges } from '@/lib/use-unsaved-changes';
import { mediaError, mediaErrorStatus, mediaRequestId } from '@/lib/media-operations-api';
import { gbpActionLabels, googleAuthorizationUrl, googleBusinessApi, googlePublicUrl, googlePreviewImageUrl, googleReplyBytes, verifiedGbpAction, verifiedGbpStatus, type GbpAction, type GbpBinding, type GbpConnection, type GbpGrants, type GbpLocations, type GbpOptions, type GbpReadyTask, type GbpReview, type GbpReviews, type GbpStatus } from '@/lib/google-business-api';
import GoogleReviewAssistant from './GoogleReviewAssistant';
import { googleReviewNeedsOwner, type GbpAiDraft } from '@/lib/google-business-ai-api';
import '@/pages/google-business.css';
import '@/pages/google-management.css';

type Props = { scope: string; isOwner: boolean; onOpenTask: (id: number, nextAction?: 'return') => void; entry?: { key: number; bindingId?: number; customerId?: number; kind?: 'bind' | 'grants' } };
type Modal = { kind: 'connect'; connection?: GbpConnection } | { kind: 'bind' } | { kind: 'grants'; binding: GbpBinding } | { kind: 'reply'; binding: GbpBinding; review: GbpReview } | { kind: 'publish'; binding: GbpBinding; task: GbpReadyTask } | { kind: 'action'; action: GbpAction } | { kind: 'disconnect_connection'; connection: GbpConnection } | { kind: 'disconnect_binding'; binding: GbpBinding };
type PendingWrite = { requestId: string; path: string; data: Record<string, unknown>; bindingId: number };
const emptyOptions: GbpOptions = { customers: [], assignees: [] };
const starValues: Record<string, number> = { ONE: 1, TWO: 2, THREE: 3, FOUR: 4, FIVE: 5 };
const ratingNumber = (value: string) => Math.min(5, Math.max(0, starValues[String(value).toUpperCase()] || Number(value) || 0));
const reviewReplyLabel = (review: GbpReview) => !review.reply ? '待回复' : review.reply_state === 'PENDING' ? '回复审核中' : review.reply_state === 'REJECTED' ? '回复未通过' : review.reply_state === 'APPROVED' ? '已回复' : '已有回复';
const reviewReplyTone = (review: GbpReview) => !review.reply || review.reply_state === 'PENDING' ? 'gbp-pill-warning' : review.reply_state === 'REJECTED' ? 'gbp-result-rejected' : review.reply_state === 'APPROVED' ? 'gbp-pill-success' : 'gbp-pill-muted';
const formatTime = (value?: string | null) => {
  if (!value || !Number.isFinite(new Date(value).getTime())) return '时间待确认';
  return new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(new Date(value));
};
const setupLabels: Record<string, string> = {
  T24_GBP_ENABLED: 'Google 连接功能尚未启用', T24_GBP_CLIENT_ID: 'Google 应用尚未配置', T24_GBP_CLIENT_SECRET: 'Google 应用凭据尚未配置',
  T24_GBP_TOKEN_KEY: '连接的安全存储尚未配置', T24_GBP_PUBLIC_URL: 'Google 授权回调地址尚未配置', T24_GBP_API_APPROVED: 'Google API 接入资格待确认',
};
const setupLabel = (name: string) => setupLabels[name] || '连接配置待管理员确认';
const providerStateLabels: Record<string, string> = { LIVE: '公开展示中', PROCESSING: 'Google 正在处理', REJECTED: 'Google 未通过', APPROVED: 'Google 已通过', PENDING: 'Google 审核中' };
const providerStateLabel = (value: string) => providerStateLabels[value] || 'Google 状态待进一步确认';
const isUncertain = (error: unknown) => !mediaErrorStatus(error) || [408, 429].includes(mediaErrorStatus(error) || 0) || (mediaErrorStatus(error) || 0) >= 500;

export default function GoogleBusinessWorkspace({ scope, isOwner, onOpenTask, entry }: Props) {
  const scopeRef = useRef(scope); scopeRef.current = scope;
  const entryApplied = useRef<number | null>(null);
  const [state, setState] = useState<GbpStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [section, setSection] = useState<'reviews' | 'posts' | 'actions'>('reviews');
  const [reviews, setReviews] = useState<GbpReviews | null>(null);
  const [reviewsLoading, setReviewsLoading] = useState(false);
  const [reviewsError, setReviewsError] = useState('');
  const [tasks, setTasks] = useState<GbpReadyTask[]>([]);
  const [tasksLoading, setTasksLoading] = useState(false);
  const [tasksError, setTasksError] = useState('');
  const [actions, setActions] = useState<GbpAction[]>([]);
  const [actionsLoading, setActionsLoading] = useState(false);
  const [actionsError, setActionsError] = useState('');
  const [modal, setModal] = useState<Modal | null>(null);
  const [modalError, setModalError] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  const [reply, setReply] = useState('');
  const [aiApproval, setAiApproval] = useState<GbpAiDraft | null>(null);
  const [aiBusy, setAiBusy] = useState(false);
  const aiBusyRef = useRef(false);
  const changeAiBusy = useCallback((value: boolean) => { aiBusyRef.current = value; setAiBusy(value); }, []);
  const [reviewFilter, setReviewFilter] = useState<'all' | 'unreplied' | 'negative' | 'replied'>('all');
  const [busy, setBusy] = useState(false);
  const [unknown, setUnknown] = useState(false);
  const [notReserved, setNotReserved] = useState(false);
  const [leaveChoice, setLeaveChoice] = useState(false);
  const [options, setOptions] = useState<GbpOptions>(emptyOptions);
  const [locations, setLocations] = useState<GbpLocations>({ items: [], truncated: false });
  const [locationsLoading, setLocationsLoading] = useState(false);
  const [connectionChoice, setConnectionChoice] = useState('');
  const [customerChoice, setCustomerChoice] = useState('');
  const [locationChoice, setLocationChoice] = useState('');
  const [grants, setGrants] = useState<GbpGrants | null>(null);
  const [grantsLoading, setGrantsLoading] = useState(false);
  const [employeeChoice, setEmployeeChoice] = useState('');
  const [grantReply, setGrantReply] = useState(false);
  const [grantPublish, setGrantPublish] = useState(false);
  const [controlNeedsRefresh, setControlNeedsRefresh] = useState(false);
  const statusSeq = useRef(0), reviewsSeq = useRef(0), tasksSeq = useRef(0), actionsSeq = useRef(0), modalSeq = useRef(0), locationSeq = useRef(0);
  const selectedRef = useRef(selectedId); selectedRef.current = selectedId;
  const modalRef = useRef(modal); modalRef.current = modal;
  const busyRef = useRef(false), durableHold = useRef(false), pending = useRef<PendingWrite | null>(null), bindRequestId = useRef('');
  const selected = state?.bindings.find(row => row.id === selectedId) || null;
  const owner = isOwner && state?.is_owner === true;
  const canUse = state?.configured === true && state.enabled;
  const currentGrant = grants?.employees.find(row => String(row.employee_id) === employeeChoice);
  const grantDirty = modal?.kind === 'grants' && !!currentGrant && (grantReply !== currentGrant.can_reply || grantPublish !== currentGrant.can_publish);
  const dirty = modal?.kind === 'reply' && reply !== (modal.review.reply || '') || modal?.kind === 'bind' && !!(customerChoice || locationChoice) || grantDirty;
  const draftGuard = useUnsavedChanges(dirty);
  const navigationHold = useHardNavigationBlock(busy || aiBusy || unknown || controlNeedsRefresh);
  const unusedLocations = useMemo(() => locations.items.filter(row => !state?.bindings.some(binding => binding.active && binding.location_name === row.location_name)), [locations.items, state?.bindings]);

  const loadStatus = useCallback(async () => {
    const seq = ++statusSeq.current, identity = scope;
    setLoading(true); setError('');
    try {
      const value = verifiedGbpStatus(await googleBusinessApi<GbpStatus>('/status'));
      if (seq !== statusSeq.current || scopeRef.current !== identity) return null;
      setState(value);
      setSelectedId(current => value.bindings.some(row => row.id === current && row.permissions.can_read) ? current : value.bindings.find(row => row.active && row.permissions.can_read)?.id || value.bindings.find(row => row.permissions.can_read)?.id || null);
      return value;
    } catch (cause) {
      if (seq !== statusSeq.current || scopeRef.current !== identity) return null;
      setState(null); setSelectedId(null); setReviews(null); setTasks([]); setActions([]); setError(mediaError(cause, 'Google 连接资料暂时无法读取。'));
      return null;
    } finally { if (seq === statusSeq.current && scopeRef.current === identity) setLoading(false); }
  }, [scope]);

  const loadReviews = useCallback(async (binding: GbpBinding, token?: string | null) => {
    const seq = ++reviewsSeq.current, identity = scope;
    setReviewsLoading(true); setReviewsError('');
    if (!token) setReviews(null);
    try {
      const value = await googleBusinessApi<GbpReviews>(`/bindings/${binding.id}/reviews${token ? `?page_token=${encodeURIComponent(token)}` : ''}`);
      if (!value || !Array.isArray(value.items) || typeof value.fetched_at !== 'string' || value.items.some(row => !row || typeof row.name !== 'string' || typeof row.version !== 'string' || typeof row.comment !== 'string')) throw new Error('评论资料返回不完整，请重新读取。');
      if (seq !== reviewsSeq.current || scopeRef.current !== identity || selectedRef.current !== binding.id) return;
      setReviews(previous => ({ ...value, items: token ? [...(previous?.items || []), ...value.items.filter(row => !previous?.items.some(old => old.name === row.name))] : value.items }));
    } catch (cause) {
      if (seq !== reviewsSeq.current || scopeRef.current !== identity || selectedRef.current !== binding.id) return;
      setReviews(null); setReviewsError(mediaError(cause, '评论暂时无法从 Google 读取。'));
      if ([401, 403, 404].includes(mediaErrorStatus(cause) || 0)) { setTasks([]); setActions([]); void loadStatus(); }
    } finally { if (seq === reviewsSeq.current && scopeRef.current === identity) setReviewsLoading(false); }
  }, [scope, loadStatus]);

  const loadTasks = useCallback(async (binding: GbpBinding) => {
    const seq = ++tasksSeq.current, identity = scope;
    setTasksLoading(true); setTasksError(''); setTasks([]);
    try {
      const value = await googleBusinessApi<{ items: GbpReadyTask[]; total: number }>(`/bindings/${binding.id}/ready-tasks`);
      if (!value || !Array.isArray(value.items) || value.items.some(row => !Number.isSafeInteger(row.id) || !Number.isSafeInteger(row.revision) || typeof row.content !== 'string')) throw new Error('待发布任务返回不完整，请重新读取。');
      if (seq === tasksSeq.current && scopeRef.current === identity && selectedRef.current === binding.id) setTasks(value.items);
    } catch (cause) { if (seq === tasksSeq.current && scopeRef.current === identity && selectedRef.current === binding.id) { setTasksError(mediaError(cause, '待发布内容暂时无法读取。')); if ([401, 403, 404].includes(mediaErrorStatus(cause) || 0)) void loadStatus(); } }
    finally { if (seq === tasksSeq.current && scopeRef.current === identity) setTasksLoading(false); }
  }, [scope, loadStatus]);

  const loadActions = useCallback(async (binding: GbpBinding) => {
    const seq = ++actionsSeq.current, identity = scope;
    setActionsLoading(true); setActionsError(''); setActions([]);
    try {
      const value = await googleBusinessApi<{ items: GbpAction[] }>(`/bindings/${binding.id}/actions`);
      if (!value || !Array.isArray(value.items)) throw new Error('操作记录返回不完整。');
      value.items.forEach(row => { verifiedGbpAction(row); if (row.binding_id !== binding.id) throw new Error('操作记录范围不一致。'); });
      if (seq === actionsSeq.current && scopeRef.current === identity && selectedRef.current === binding.id) setActions(value.items);
    } catch (cause) { if (seq === actionsSeq.current && scopeRef.current === identity && selectedRef.current === binding.id) { setActionsError(mediaError(cause, '操作记录暂时无法读取。')); if ([401, 403, 404].includes(mediaErrorStatus(cause) || 0)) void loadStatus(); } }
    finally { if (seq === actionsSeq.current && scopeRef.current === identity) setActionsLoading(false); }
  }, [scope, loadStatus]);

  useEffect(() => {
    statusSeq.current++; reviewsSeq.current++; tasksSeq.current++; actionsSeq.current++; modalSeq.current++; locationSeq.current++;
    setState(null); setSelectedId(null); setReviews(null); setTasks([]); setActions([]); setModal(null); setOptions(emptyOptions); setGrants(null); setLocations({ items: [], truncated: false });
    setUnknown(false); setControlNeedsRefresh(false); setBusy(false); busyRef.current = false; durableHold.current = false; pending.current = null; setNotice(''); draftGuard.markSaved(); navigationHold.release();
    void loadStatus();
    return () => { statusSeq.current++; reviewsSeq.current++; tasksSeq.current++; actionsSeq.current++; modalSeq.current++; locationSeq.current++; };
  }, [scope, loadStatus]);
  useEffect(() => {
    reviewsSeq.current++; tasksSeq.current++; actionsSeq.current++;
    setReviews(null); setTasks([]); setActions([]); setReviewsError(''); setTasksError(''); setActionsError('');
    if (!selected || !selected.active || !canUse) return;
    if (section === 'reviews' && selected.permissions.can_read) void loadReviews(selected);
    if (section === 'posts' && selected.permissions.can_publish) void loadTasks(selected);
    if (section === 'actions' && selected.permissions.can_read) void loadActions(selected);
  }, [selectedId, selected?.revision, selected?.active, canUse, section, loadReviews, loadTasks, loadActions]);

  useEffect(() => {
    if (!entry || entryApplied.current === entry.key || !state || loading || busyRef.current || durableHold.current || unknown || controlNeedsRefresh) return;
    const binding = state.bindings.find(row => row.id === entry.bindingId);
    entryApplied.current = entry.key;
    if (binding) setSelectedId(binding.id);
    if (entry.kind === 'bind' && owner && canUse) open({ kind: 'bind' });
    if (entry.kind === 'grants' && owner && binding) open({ kind: 'grants', binding });
  }, [entry, state, loading, owner, canUse, unknown, controlNeedsRefresh]);

  function lock() { busyRef.current = true; setBusy(true); navigationHold.lock(); }
  function unlock() { busyRef.current = false; setBusy(false); if (!durableHold.current) navigationHold.release(); }
  function open(next: Modal) {
    if (busyRef.current || aiBusyRef.current || durableHold.current || unknown || controlNeedsRefresh) return;
    modalSeq.current++; locationSeq.current++; setLocationsLoading(false); setModal(next); setModalError(''); setConfirmed(false); setLeaveChoice(false); setNotReserved(false);
    setReply(next.kind === 'reply' ? next.review.reply || '' : ''); setAiApproval(null); setAiBusy(false); aiBusyRef.current = false; setGrants(null); setEmployeeChoice(''); setGrantReply(false); setGrantPublish(false);
    if (next.kind === 'bind') {
      bindRequestId.current = mediaRequestId(); setCustomerChoice(''); setConnectionChoice(''); setLocationChoice(''); setLocations({ items: [], truncated: false });
      const identity = scope, seq = modalSeq.current;
      void googleBusinessApi<GbpOptions>('/options').then(value => {
        if (seq !== modalSeq.current || scopeRef.current !== identity) return;
        if (!value || !Array.isArray(value.customers) || !Array.isArray(value.assignees)) throw new Error('授权客户返回不完整。');
        setOptions(value);
        if (entry?.customerId && value.customers.some(row => row.id === entry.customerId)) setCustomerChoice(String(entry.customerId));
      }).catch(cause => { if (seq === modalSeq.current && scopeRef.current === identity) setModalError(mediaError(cause)); });
    }
    if (next.kind === 'grants') void loadGrants(next.binding);
  }
  function close() {
    if (busyRef.current || aiBusyRef.current || durableHold.current || unknown || controlNeedsRefresh) return;
    if (dirty) { setLeaveChoice(true); return; }
    modalSeq.current++; locationSeq.current++; setModal(null); setModalError(''); setConfirmed(false); draftGuard.markSaved();
  }
  function discard() { if (busyRef.current || aiBusyRef.current || durableHold.current || unknown || controlNeedsRefresh) return; draftGuard.markSaved(); modalSeq.current++; locationSeq.current++; setModal(null); setLeaveChoice(false); setModalError(''); }

  async function loadGrants(binding: GbpBinding) {
    const identity = scope, seq = modalSeq.current; setGrantsLoading(true);
    try {
      const value = await googleBusinessApi<GbpGrants>(`/bindings/${binding.id}/grants`);
      if (!value || !Array.isArray(value.employees) || value.binding.id !== binding.id || !Number.isSafeInteger(value.revision)) throw new Error('门店授权资料返回不完整。');
      if (seq !== modalSeq.current || scopeRef.current !== identity) return null;
      setGrants(value); return value;
    } catch (cause) { if (seq === modalSeq.current && scopeRef.current === identity) setModalError(mediaError(cause)); return null; }
    finally { if (seq === modalSeq.current && scopeRef.current === identity) setGrantsLoading(false); }
  }
  function chooseEmployee(value: string, data = grants) {
    if (grantDirty && !draftGuard.confirmDiscard()) return;
    const employee = data?.employees.find(row => String(row.employee_id) === value);
    setEmployeeChoice(value); setGrantReply(employee?.can_reply || false); setGrantPublish(employee?.can_publish || false); setModalError(''); setConfirmed(false);
  }
  async function chooseConnection(value: string) {
    setConnectionChoice(value); setLocationChoice(''); setLocations({ items: [], truncated: false }); setModalError(''); setConfirmed(false);
    const seq = ++locationSeq.current, identity = scope;
    if (!value) return;
    setLocationsLoading(true);
    try {
      const result = await googleBusinessApi<GbpLocations>(`/connections/${value}/locations`);
      if (!result || !Array.isArray(result.items) || result.items.some(row => typeof row.location_name !== 'string' || typeof row.title !== 'string')) throw new Error('Google 门店列表返回不完整。');
      if (seq === locationSeq.current && scopeRef.current === identity) setLocations(result);
    } catch (cause) { if (seq === locationSeq.current && scopeRef.current === identity) setModalError(mediaError(cause)); }
    finally { if (seq === locationSeq.current && scopeRef.current === identity) setLocationsLoading(false); }
  }
  async function connect() {
    if (busyRef.current || durableHold.current || !confirmed || !owner || !canUse) return;
    const identity = scope; lock(); setModalError('');
    try {
      const value = await googleBusinessApi<{ authorization_url: string }>('/oauth/start', 'POST', { confirmed: true, ...(modalRef.current?.kind === 'connect' && modalRef.current.connection ? { reconnect_connection_id: modalRef.current.connection.id } : {}) });
      const url = googleAuthorizationUrl(value.authorization_url);
      if (!url) throw new Error('Google 授权地址无效，请重新读取连接状态。');
      if (scopeRef.current !== identity) return;
      draftGuard.markSaved(); navigationHold.release(); window.location.assign(url);
    } catch (cause) { if (scopeRef.current === identity) setModalError(mediaError(cause, cause instanceof Error ? cause.message : '暂时无法打开 Google 授权。')); }
    finally { if (scopeRef.current === identity) unlock(); }
  }
  async function refreshControlResult() {
    if (busyRef.current) return;
    const identity = scope; lock(); setModalError('');
    try {
      const value = await loadStatus();
      if (scopeRef.current !== identity || !value) return;
      if (modalRef.current?.kind === 'grants') {
        const fresh = await loadGrants(modalRef.current.binding);
        if (!fresh) return;
        const row = fresh.employees.find(item => String(item.employee_id) === employeeChoice);
        setGrantReply(row?.can_reply || false); setGrantPublish(row?.can_publish || false);
      }
      draftGuard.markSaved(); durableHold.current = false; setControlNeedsRefresh(false); setModal(null); setNotice('已重新读取实际连接及授权状态，请核对后继续。');
    } finally { if (scopeRef.current === identity) unlock(); }
  }
  async function controlWrite(path: string, method: 'POST' | 'PUT', data: Record<string, unknown>) {
    if (busyRef.current || aiBusyRef.current || durableHold.current || unknown || controlNeedsRefresh) return;
    const identity = scope; lock(); setModalError('');
    try {
      await googleBusinessApi(path, method, data);
      if (scopeRef.current !== identity) return;
      draftGuard.markSaved(); setModal(null); setNotice('操作已保存。'); await loadStatus();
    } catch (cause) {
      if (scopeRef.current !== identity) return;
      if (isUncertain(cause)) { durableHold.current = true; setControlNeedsRefresh(true); setModalError('保存结果待确认，请重新读取实际状态后再操作。'); }
      else { setModalError(mediaError(cause)); if (mediaErrorStatus(cause) === 409 && modalRef.current?.kind === 'grants') { const fresh = await loadGrants(modalRef.current.binding); if (fresh) { const row = fresh.employees.find(item => String(item.employee_id) === employeeChoice); setGrantReply(row?.can_reply || false); setGrantPublish(row?.can_publish || false); draftGuard.markSaved(); } } }
    } finally { if (scopeRef.current === identity) unlock(); }
  }
  function completeAction(value: GbpAction, request: PendingWrite) {
    verifiedGbpAction(value, request.requestId);
    if (value.binding_id !== request.bindingId) throw new Error('Google 操作门店不一致，请按原编号重新确认。');
    pending.current = null; durableHold.current = false; setUnknown(false); setNotReserved(false); setModal({ kind: 'action', action: value }); setModalError(''); draftGuard.markSaved();
    setNotice(gbpActionLabels[value.status]);
    const binding = state?.bindings.find(row => row.id === value.binding_id);
    if (binding && selectedRef.current === binding.id) {
      if (section === 'reviews') void loadReviews(binding);
      if (section === 'posts') void loadTasks(binding);
      if (section === 'actions') void loadActions(binding);
    }
  }
  async function writePublic(request: PendingWrite) {
    if (busyRef.current || durableHold.current && pending.current?.requestId !== request.requestId) return;
    const identity = scope; pending.current = request; lock(); setModalError('');
    try {
      const result = await googleBusinessApi<GbpAction>(request.path, 'POST', request.data);
      if (scopeRef.current === identity) completeAction(result, request);
    } catch (cause) {
      if (scopeRef.current !== identity) return;
      if (isUncertain(cause) || cause instanceof Error && !mediaErrorStatus(cause)) { durableHold.current = true; setUnknown(true); setNotReserved(false); setModalError('提交结果尚未确认。请先查询原请求，避免重复回复或发布。'); }
      else {
        pending.current = null; setUnknown(false); setModalError(mediaError(cause));
        if ([401, 403, 404].includes(mediaErrorStatus(cause) || 0)) { setModal(null); await loadStatus(); setNotice('授权或门店状态已变化，请重新确认。'); }
        if (mediaErrorStatus(cause) === 409 && modalRef.current?.kind === 'reply') {
          const binding = modalRef.current.binding;
          setModal(null); draftGuard.markSaved(); await loadReviews(binding); setNotice('Google 评论或回复已有变化，已重新读取。请重新打开后核对。');
        }
      }
    } finally { if (scopeRef.current === identity) unlock(); }
  }
  async function recover() {
    const request = pending.current;
    if (!request || busyRef.current) return;
    const identity = scope; lock(); setModalError('');
    try {
      const result = await googleBusinessApi<GbpAction>(`/requests/${encodeURIComponent(request.requestId)}`);
      if (scopeRef.current === identity) completeAction(result, request);
    } catch (cause) {
      if (scopeRef.current !== identity) return;
      if ([401, 403].includes(mediaErrorStatus(cause) || 0)) { pending.current = null; durableHold.current = false; setUnknown(false); setModal(null); setReviews(null); setTasks([]); setActions([]); draftGuard.markSaved(); await loadStatus(); setNotice('当前账号或门店授权已变化，已停止提交并重新读取范围。'); return; }
      setNotReserved(mediaErrorStatus(cause) === 404);
      setModalError(mediaErrorStatus(cause) === 404 ? '尚未找到这个请求的操作记录。可以继续查询，或明确重新提交同一个请求编号。' : mediaError(cause, '仍无法确认，请稍后继续查询原请求。'));
    } finally { if (scopeRef.current === identity) unlock(); }
  }
  async function reconcile(action: GbpAction) {
    if (busyRef.current || durableHold.current || unknown) return;
    const identity = scope; lock(); setModalError('');
    try {
      const value = verifiedGbpAction(await googleBusinessApi<GbpAction>(`/actions/${action.id}/reconcile`, 'POST', { confirmed: true }));
      if (value.id !== action.id) throw new Error('操作结果编号不一致。');
      if (scopeRef.current === identity) { setModal({ kind: 'action', action: value }); setNotice(gbpActionLabels[value.status]); const binding = state?.bindings.find(row => row.id === value.binding_id); if (binding && section === 'actions') void loadActions(binding); }
    } catch (cause) { if (scopeRef.current === identity) { if ([401, 403, 404].includes(mediaErrorStatus(cause) || 0)) { setModal(null); setReviews(null); setTasks([]); setActions([]); await loadStatus(); setNotice('当前操作授权已变化，已重新读取范围。'); } else setModalError(mediaError(cause, '暂时无法查询 Google，尚未重新提交内容。')); } }
    finally { if (scopeRef.current === identity) unlock(); }
  }
  function submitModal() {
    if (!modal || busyRef.current || aiBusyRef.current || durableHold.current || !confirmed || unknown || controlNeedsRefresh) return;
    if (modal.kind === 'connect') { void connect(); return; }
    if (modal.kind === 'bind') {
      if (!connectionChoice || !customerChoice || !locationChoice) { setModalError('请完整选择客户、连接和 Google 门店。'); return; }
      void controlWrite('/bindings', 'POST', { request_id: bindRequestId.current, customer_id: Number(customerChoice), connection_id: Number(connectionChoice), location_name: locationChoice, confirmed: true }); return;
    }
    if (modal.kind === 'grants') {
      if (!grants || !employeeChoice || !currentGrant) return;
      void controlWrite(`/bindings/${modal.binding.id}/grants`, 'PUT', { expected_revision: grants.revision, employee_id: Number(employeeChoice), can_reply: grantReply, can_publish: grantPublish }); return;
    }
    if (modal.kind === 'disconnect_connection') { void controlWrite(`/connections/${modal.connection.id}/disconnect`, 'POST', { confirmed: true }); return; }
    if (modal.kind === 'disconnect_binding') { void controlWrite(`/bindings/${modal.binding.id}/disconnect`, 'POST', { confirmed: true, expected_revision: modal.binding.revision }); return; }
    if (modal.kind === 'reply') {
      if (!reply.trim() || googleReplyBytes(reply.trim()) > 4096) { setModalError('回复不能为空，且长度不能超过 Google 的 4096 字节限制。'); return; }
      if (!owner && (modal.review.requires_owner_review || aiApproval?.sensitive || googleReviewNeedsOwner(modal.review.comment, reply)) && !(aiApproval?.approved && aiApproval.reply === reply.trim() && aiApproval.review_version === modal.review.version)) { setModalError('这条回复需老板批准当前文本后才能公开。'); return; }
      const requestId = mediaRequestId();
      void writePublic({ requestId, bindingId: modal.binding.id, path: `/bindings/${modal.binding.id}/review-replies`, data: { request_id: requestId, review_name: modal.review.name, expected_version: modal.review.version, reply: reply.trim(), ...(aiApproval?.approved && aiApproval.reply === reply.trim() && aiApproval.review_version === modal.review.version ? { approval_id: aiApproval.id } : {}), confirmed: true } }); return;
    }
    if (modal.kind === 'publish') {
      const requestId = mediaRequestId();
      void writePublic({ requestId, bindingId: modal.binding.id, path: `/bindings/${modal.binding.id}/posts`, data: { request_id: requestId, task_id: modal.task.id, expected_revision: modal.task.revision, confirmed: true } });
    }
  }

  const title = modal?.kind === 'connect' ? modal.connection ? '重新授权 Google 商家' : '连接 Google 商家' : modal?.kind === 'bind' ? '绑定客户与 Google 门店' : modal?.kind === 'grants' ? 'Google 操作授权' : modal?.kind === 'reply' ? '回复 Google 评论' : modal?.kind === 'publish' ? '发布到 Google' : modal?.kind === 'action' ? 'Google 操作结果' : '断开 Google 连接';
  const confirmLabel = modal?.kind === 'connect' ? '我同意此连接读取我有权管理的门店和评论，并供已授权员工回复评论、发布帖子。' : modal?.kind === 'bind' ? '我已核对客户、门店名称和地址，确认对应同一家商家。' : modal?.kind === 'grants' ? '我已核对员工及门店，确认授予或撤销上面所列权限。' : modal?.kind === 'reply' ? '我已核对门店与回复内容，确认以商家身份公开回复。' : modal?.kind === 'publish' ? '我已核对门店、内容和素材，确认将这项已审核内容发布到 Google。' : '我确认停止此连接或门店的 CRM 操作授权。';
  const needsOwnerApproval = modal?.kind === 'reply' && !owner && (modal.review.requires_owner_review || aiApproval?.sensitive || googleReviewNeedsOwner(modal.review.comment, reply)) && !(aiApproval?.approved && aiApproval.reply === reply.trim() && aiApproval.review_version === modal.review.version);
  const visibleReviews = reviews?.items.filter(row => reviewFilter === 'all' || reviewFilter === 'unreplied' && !row.reply || reviewFilter === 'negative' && ratingNumber(row.rating) <= 2 || reviewFilter === 'replied' && !!row.reply) || [];
  const saveDisabled = busy || aiBusy || needsOwnerApproval || unknown || controlNeedsRefresh || !confirmed || modal?.kind === 'grants' && (!currentGrant || !grantDirty || (!currentGrant.eligible && (grantReply || grantPublish))) || modal?.kind === 'bind' && (!customerChoice || !locationChoice || locationsLoading) || modal?.kind === 'reply' && (!reply.trim() || googleReplyBytes(reply.trim()) > 4096);
  const pickedLocation = locations.items.find(row => row.location_name === locationChoice);

  return <section className="gbp-workspace" aria-label="Google 商家运营">
    <div className="gbp-intro"><div className="gbp-heading-icon"><Globe2 aria-hidden="true"/></div><div><h2>Google 商家运营</h2><p>查看评论、公开回复，将已审核的内容直接发布到对应门店。</p></div><Button variant="outline" onClick={() => void loadStatus()} disabled={loading || busy || unknown || controlNeedsRefresh} aria-label="刷新 Google 连接"><RefreshCw className={loading ? 'animate-spin' : ''} aria-hidden="true"/><span>刷新</span></Button></div>
    <p className="sr-only" role="status" aria-live="polite">{notice}</p>
    {notice && !unknown && <div className="gbp-notice"><CheckCircle2 aria-hidden="true"/><span>{notice}</span></div>}
    {unknown && <div className="gbp-alert gbp-alert-warn" role="alert"><AlertCircle aria-hidden="true"/><div><strong>上次提交结果待确认</strong><p>先查询原操作，确认前不会发起新的回复或帖子。</p></div><Button variant="outline" disabled={busy} onClick={() => void recover()}>查询原请求</Button></div>}
    {loading && !state ? <div className="gbp-empty"><Loader2 className="animate-spin" aria-hidden="true"/><h3>正在确认 Google 连接和门店范围</h3><p>仅显示当前账号被授权的门店。</p></div> : error ? <div className="gbp-alert" role="alert"><AlertCircle aria-hidden="true"/><div><strong>Google 连接暂时无法读取</strong><p>{error}</p></div><Button variant="outline" onClick={() => void loadStatus()}>重新读取</Button></div> : state && <>
      {!canUse && <div className="gbp-setup"><ShieldCheck aria-hidden="true"/><div><strong>{state.setup_missing.includes('T24_GBP_API_APPROVED') ? 'Google API 接入资格待确认' : 'Google 连接尚待配置'}</strong><p>{owner ? '完成 Google 应用与接入配置后，由你授权连接。当前不会向 Google 发送回复或帖子。' : '老板完成连接并授权门店后，你可以在这里处理评论和帖子。'}</p>{owner && state.setup_missing.length > 0 && <ul>{[...new Set(state.setup_missing.map(setupLabel))].map(label => <li key={label}>{label}</li>)}</ul>}</div></div>}
      {owner && <details className="gbp-connections" open={!state.connections.length}><summary><span><Link2 aria-hidden="true"/>Google 连接与门店授权</span><span>{state.connections.filter(row => row.active).length} 个有效连接<ChevronDown aria-hidden="true"/></span></summary><div className="gbp-connections-body"><div className="gbp-connection-tools"><p>由你管理连接，员工通过自己的 CRM 账号操作，无需获得 Google 密码。</p><Button onClick={() => open({ kind: 'connect' })} disabled={!canUse || busy || unknown || controlNeedsRefresh}><Link2 aria-hidden="true"/>连接 Google</Button></div>{state.connections.length ? <div className="gbp-connection-list">{state.connections.map(connection => <div className="gbp-connection" key={connection.id}><div><strong>{connection.label || 'Google 商家连接'}</strong><small>{connection.needs_reconnect ? '授权已失效，请重新连接' : connection.active ? `已连接 · ${formatTime(connection.connected_at)}（北京时间）` : '已断开'}</small>{connection.last_error && <p>{connection.last_error}</p>}</div><span className={`gbp-pill ${connection.active && !connection.needs_reconnect ? 'gbp-pill-success' : 'gbp-pill-muted'}`}>{connection.needs_reconnect ? '需重新授权' : connection.active ? '已连接' : '已断开'}</span>{(connection.active || connection.needs_reconnect) && <Button variant="outline" onClick={() => open({ kind: 'connect', connection })} disabled={busy || unknown || controlNeedsRefresh}>重新授权</Button>}{connection.active && <Button variant="ghost" onClick={() => open({ kind: 'disconnect_connection', connection })} disabled={busy || unknown || controlNeedsRefresh}>断开</Button>}</div>)}</div> : <p className="gbp-help">尚未建立 Google 连接。</p>}<div className="gbp-bind-tools"><span>连接后，逐一确认 Google 门店与 CRM 客户的对应关系。</span><Button variant="outline" onClick={() => open({ kind: 'bind' })} disabled={!canUse || !state.connections.some(row => row.active && !row.needs_reconnect) || busy || unknown || controlNeedsRefresh}><Link2 aria-hidden="true"/>绑定门店</Button></div></div></details>}
      {!state.bindings.length ? <div className="gbp-empty gbp-panel"><Globe2 aria-hidden="true"/><h3>{owner ? '先连接 Google，再绑定一家门店' : '暂无获授权的 Google 门店'}</h3><p>{owner ? '先核对一家门店的评论与发布结果，再逐步开放给运营。' : '需要老板邀请你协作客户，并单独开放评论回复或帖子发布权限。'}</p></div> : <div className="gbp-layout">
        <div className="gbp-mobile-store-select"><label>当前门店 · 已授权 {state.bindings.length} 家<NativeSelect aria-label="切换 Google 门店" value={selectedId ? String(selectedId) : ''} onChange={value => { if (!busyRef.current && !durableHold.current && !unknown && !controlNeedsRefresh) setSelectedId(Number(value)); }} disabled={busy || unknown || controlNeedsRefresh} options={state.bindings.map(binding => ({ value: String(binding.id), label: `${binding.customer_name} · ${binding.title}${binding.active ? '' : '（已断开）'}` }))}/></label></div><aside className="gbp-store-list" aria-label="获授权的 Google 门店"><div className="gbp-store-list-title"><h3>{owner ? '客户与门店' : '我的门店'}</h3><span>{state.bindings.length}</span></div>{state.bindings.map(binding => <button key={binding.id} className={`gbp-store ${selectedId === binding.id ? 'active' : ''}`} onClick={() => { if (!busyRef.current && !durableHold.current && !unknown && !controlNeedsRefresh) setSelectedId(binding.id); }} aria-pressed={selectedId === binding.id}><strong>{binding.customer_name}</strong><span>{binding.title}</span><small>{!binding.active ? '已断开' : [binding.permissions.can_reply && '可回复', binding.permissions.can_publish && '可发布'].filter(Boolean).join(' · ') || '只读查看'}</small></button>)}</aside>
        {selected && <div className="gbp-content"><header className="gbp-store-heading"><div><p>当前 Google 门店</p><h3>{selected.title}</h3><span>{selected.customer_name}{selected.address && ` · ${selected.address}`}</span></div>{selected.permissions.can_manage && <div className="gbp-store-tools"><Button variant="outline" onClick={() => open({ kind: 'grants', binding: selected })} disabled={busy || unknown || controlNeedsRefresh}><Users aria-hidden="true"/>操作授权</Button>{selected.active && <Button variant="ghost" onClick={() => open({ kind: 'disconnect_binding', binding: selected })} disabled={busy || unknown || controlNeedsRefresh} aria-label="断开当前门店"><Unplug aria-hidden="true"/></Button>}</div>}</header>
          {!selected.active ? <div className="gbp-empty"><Unplug aria-hidden="true"/><h3>此门店已断开</h3><p>当前不会向该门店提交回复或帖子。</p></div> : !canUse ? <div className="gbp-empty"><Settings2 aria-hidden="true"/><h3>连接配置完成后可处理此门店</h3><p>当前没有向 Google 提交内容。</p></div> : <><div className="gbp-section-tabs" role="group" aria-label="Google 运营功能"><button aria-pressed={section === 'reviews'} className={section === 'reviews' ? 'active' : ''} onClick={() => setSection('reviews')}><MessageSquare aria-hidden="true"/>评论回复</button><button aria-pressed={section === 'posts'} className={section === 'posts' ? 'active' : ''} onClick={() => setSection('posts')}><FileText aria-hidden="true"/>帖子发布</button><button aria-pressed={section === 'actions'} className={section === 'actions' ? 'active' : ''} onClick={() => setSection('actions')}>操作记录</button></div>
            {section === 'reviews' && <section aria-label="Google 评论"><div className="gbp-section-heading"><span>{reviews ? `已读取 ${reviews.items.length} 条 · 未回复 ${reviews.items.filter(row => !row.reply).length} 条` : '从 Google 读取最新评论'}{reviews && <small>最近读取 {formatTime(reviews.fetched_at)}（北京时间）</small>}</span><Button variant="ghost" disabled={reviewsLoading || busy || unknown} onClick={() => void loadReviews(selected)} aria-label="刷新当前门店评论"><RefreshCw className={reviewsLoading ? 'animate-spin' : ''} aria-hidden="true"/></Button></div>{reviewsError ? <div className="gbp-inline-error" role="alert">{reviewsError}<Button variant="outline" onClick={() => void loadReviews(selected)}>重新读取评论</Button></div> : !reviews && reviewsLoading ? <Loading label="正在读取 Google 评论…"/> : reviews?.items.length ? <><div className="gpm-reply-filters" role="group" aria-label="筛选当前已读取评论">{(['all', 'unreplied', 'negative', 'replied'] as const).map(value => <button key={value} className={reviewFilter === value ? 'active' : ''} aria-pressed={reviewFilter === value} onClick={() => setReviewFilter(value)}>{{ all: '全部', unreplied: '未回复', negative: '1–2 星', replied: '已有回复' }[value]}</button>)}</div><p className="gbp-help" style={{ padding: '0 18px 12px' }}>筛选仅针对当前已读取的 {reviews.items.length} 条评论；可继续读取更多。</p>{!visibleReviews.length && <div className="gbp-empty"><h3>当前已读取评论中没有符合项</h3><p>可调整筛选或继续读取下一页。</p></div>}<div className="gbp-review-list">{visibleReviews.map(review => <article className="gbp-review" key={review.name}><header><div><strong>{review.reviewer_name || 'Google 用户'}</strong><span className="gbp-rating" aria-label={`${ratingNumber(review.rating)} 星评价`}>{Array.from({ length: 5 }, (_, index) => <Star key={index} className={index < ratingNumber(review.rating) ? 'filled' : ''} aria-hidden="true"/>)}<small>{formatTime(review.created_at)}</small></span></div><span className={`gbp-pill ${reviewReplyTone(review)}`}>{reviewReplyLabel(review)}</span></header><p className="gbp-review-comment">{review.comment || '这条评价没有文字内容。'}</p>{review.reply && <div className="gbp-existing-reply"><strong>商家回复<small>{formatTime(review.reply_updated_at)}</small></strong><p>{review.reply}</p></div>}<footer>{selected.permissions.can_reply ? <Button variant={review.reply ? 'outline' : 'default'} onClick={() => open({ kind: 'reply', binding: selected, review })} disabled={busy || unknown || controlNeedsRefresh}><MessageSquare aria-hidden="true"/>{review.reply ? '修改回复' : '回复评论'}</Button> : <span className="gbp-help">当前仅可查看，回复权限由老板单独开放。</span>}</footer></article>)}</div>{reviews.next_page_token && <Button className="gbp-load-more" variant="outline" disabled={reviewsLoading || busy || unknown} onClick={() => void loadReviews(selected, reviews.next_page_token)}>{reviewsLoading ? '正在读取…' : '读取更多评论'}</Button>}</> : <Empty title="Google 暂未返回评论" text="此处显示实际读取结果，不会生成示例评论。"/>}</section>}
            {section === 'posts' && <section aria-label="Google 帖子发布"><div className="gbp-section-heading"><span>仅列出此客户已审核的 Google 待发布任务<small>内容保持审核版本；每次发布都需明确确认门店和内容。</small></span>{selected.permissions.can_publish && <Button variant="ghost" onClick={() => void loadTasks(selected)} disabled={tasksLoading || busy || unknown} aria-label="刷新待发布帖子"><RefreshCw className={tasksLoading ? 'animate-spin' : ''} aria-hidden="true"/></Button>}</div>{!selected.permissions.can_publish ? <Empty title="尚未开放帖子发布权限" text="内部任务编辑权限不会自动获得公开发布权限。"/> : tasksError ? <div className="gbp-inline-error" role="alert">{tasksError}<Button variant="outline" onClick={() => void loadTasks(selected)}>重新读取任务</Button></div> : tasksLoading ? <Loading label="正在读取已审核的帖子…"/> : !tasks.length ? <Empty title="暂无已审核的 Google 帖子" text="先在运营任务中准备内容，审核通过后会出现在这里。"/> : <div className="gbp-post-list">{tasks.map(task => <article className="gbp-post" key={task.id}><header><span className="gbp-pill gbp-pill-success">审核已通过</span><small>任务 #{task.id}</small></header><h4>{task.title}</h4><p>{task.content}</p>{task.preview_image_url && <ImagePreview src={task.preview_image_url} title={task.material_title || '已审核图片'}/>} {task.publish_blocked_reason && <p className="gbp-help warning">{task.publish_blocked_reason}</p>}{task.material_id && <div className={`gbp-image-note ${!task.has_public_image ? 'warning' : ''}`}><FileText aria-hidden="true"/><span>{task.material_title || '已审核素材'}{!task.has_public_image && <small>该素材尚无可供 Google 读取的公开图片地址，请先处理素材后再发布。</small>}</span></div>}{task.content.length > 1500 && <p className="gbp-help warning">内容超过 Google 帖子 1500 字限制，请先退回任务修改并重新审核。</p>}<footer><Button variant="outline" onClick={() => onOpenTask(task.id, owner && task.can_return === true && task.publish_blocked_reason ? 'return' : undefined)} disabled={busy || unknown || controlNeedsRefresh}>{owner && task.can_return === true && task.publish_blocked_reason ? '前往任务退回修改' : '查看原任务'}</Button><Button onClick={() => open({ kind: 'publish', binding: selected, task })} disabled={busy || unknown || controlNeedsRefresh || !task.content.trim() || task.content.length > 1500 || Boolean(task.material_id && !task.has_public_image) || Boolean(task.publish_blocked_reason)}><Send aria-hidden="true"/>预览并发布</Button></footer></article>)}</div>}</section>}
            {section === 'actions' && <section aria-label="Google 操作记录"><div className="gbp-section-heading"><span>最近 50 条操作<small>Google 处理中与已确认结果分别显示。</small></span><Button variant="ghost" onClick={() => void loadActions(selected)} disabled={actionsLoading || busy || unknown} aria-label="刷新操作记录"><RefreshCw className={actionsLoading ? 'animate-spin' : ''} aria-hidden="true"/></Button></div>{actionsError ? <div className="gbp-inline-error" role="alert">{actionsError}</div> : actionsLoading ? <Loading label="正在读取操作记录…"/> : !actions.length ? <Empty title="暂无 Google 操作记录" text="评论回复和帖子提交后会在此留下操作者与结果。"/> : <div className="gbp-action-list">{actions.map(action => <button className="gbp-action-row" key={action.id} onClick={() => open({ kind: 'action', action })} disabled={busy || unknown || controlNeedsRefresh}><span><strong>{action.kind === 'review_reply' ? '回复评论' : '发布帖子'}{action.task_id && <small> · 任务 #{action.task_id}</small>}</strong><small>{action.actor_name} · {formatTime(action.created_at)}</small></span><span className={`gbp-pill gbp-result-${action.status}`}>{gbpActionLabels[action.status]}</span><ArrowRight aria-hidden="true"/></button>)}</div>}</section>}
          </>}
        </div>}
      </div>}
    </>}
    <Dialog open={modal !== null} onOpenChange={value => { if (!value) close(); }}>
      <CrmFormDialogContent className="gbp-dialog" onEscapeKeyDown={event => { if (busy || unknown || controlNeedsRefresh || dirty) { event.preventDefault(); if (!busy && !unknown && !controlNeedsRefresh) setLeaveChoice(true); } }} onPointerDownOutside={event => { if (busy || unknown || controlNeedsRefresh || dirty) { event.preventDefault(); if (!busy && !unknown && !controlNeedsRefresh) setLeaveChoice(true); } }}>
        <CrmFormDialogHeader><DialogTitle>{title}</DialogTitle><DialogDescription>{modal?.kind === 'reply' || modal?.kind === 'publish' || modal?.kind === 'grants' || modal?.kind === 'disconnect_binding' ? `${modal.binding.customer_name} · ${modal.binding.title}` : modal?.kind === 'action' ? `操作 #${modal.action.id} · ${modal.action.kind === 'review_reply' ? '评论回复' : '帖子发布'}` : 'Google 连接由老板管理，门店操作按员工单独授权。'}</DialogDescription></CrmFormDialogHeader>
        <CrmFormDialogBody>
          {leaveChoice && <div className="gbp-alert gbp-alert-warn"><div><strong>还有未保存的修改</strong><p>可以继续编辑，或放弃本次修改。</p></div><Button variant="outline" onClick={() => setLeaveChoice(false)}>继续编辑</Button><Button variant="ghost" onClick={discard}>放弃修改</Button></div>}
          {modal?.kind === 'connect' && <div className="gbp-dialog-copy"><Globe2 aria-hidden="true"/><h3>用你有权管理门店的 Google 账号授权</h3><p>Google 将请求商家管理权限。本系统将其用于读取门店及评论，并供你指定的员工回复评论、发布帖子。</p><p>下一步会前往 Google 官方授权页面。Google 密码不会交给运营员工；门店绑定和员工操作权限仍由你决定。</p><p className="gbp-help">授权被撤销或失效后，需要你重新连接。尚未获批的 Google API 项目不能通过连接绕过接入限制。</p></div>}
          {modal?.kind === 'bind' && <div className="gbp-form"><label>CRM 客户<NativeSelect aria-label="绑定的 CRM 客户" value={customerChoice} onChange={value => { setCustomerChoice(value); setConfirmed(false); }} disabled={busy || controlNeedsRefresh} options={[{ value: '', label: '选择对应客户' }, ...options.customers.filter(row => !state?.bindings.some(binding => binding.active && binding.customer_id === row.id)).map(row => ({ value: String(row.id), label: row.name }))]}/></label><label>Google 连接<NativeSelect aria-label="选择 Google 连接" value={connectionChoice} onChange={value => void chooseConnection(value)} disabled={busy || controlNeedsRefresh} options={[{ value: '', label: '选择已连接的 Google 账号' }, ...(state?.connections || []).filter(row => row.active && !row.needs_reconnect).map(row => ({ value: String(row.id), label: row.label || `连接 #${row.id}` }))]}/></label><label>Google 门店<NativeSelect aria-label="选择 Google 门店" value={locationChoice} onChange={value => { setLocationChoice(value); setConfirmed(false); }} disabled={busy || locationsLoading || !connectionChoice || controlNeedsRefresh} options={[{ value: '', label: locationsLoading ? '正在读取 Google 门店…' : '选择对应门店' }, ...unusedLocations.map(row => ({ value: row.location_name, label: `${row.title}${row.address ? ` · ${row.address}` : ''}` }))]}/></label>{pickedLocation && <div className="gbp-location-preview"><strong>{pickedLocation.title}</strong><span>{pickedLocation.address || 'Google 未返回地址，请进一步核对门店。'}</span><small>请确认与上面选定的 CRM 客户一致。</small></div>}{locations.truncated && <p className="gbp-help warning">本次门店列表未完整返回；未找到对应门店时先不要绑定。</p>}</div>}
          {modal?.kind === 'grants' && <div className="gbp-form">{grantsLoading && !grants ? <Loading label="正在读取当前授权…"/> : grants && <><p>仅可选择已获该客户交付协作授权的有效员工。内部任务编辑权不会自动获得下列权限。</p><label>员工<NativeSelect aria-label="Google 操作授权员工" value={employeeChoice} onChange={chooseEmployee} disabled={busy || controlNeedsRefresh} options={[{ value: '', label: '选择员工' }, ...grants.employees.filter(row => row.eligible || row.can_reply || row.can_publish).map(row => ({ value: String(row.employee_id), label: row.name + (row.eligible ? '' : ' · 原协作授权已失效') }))]}/></label>{currentGrant && <><label className="gbp-check"><input type="checkbox" checked={grantReply} onChange={event => { setGrantReply(event.target.checked); setConfirmed(false); }} disabled={busy || controlNeedsRefresh || !currentGrant.eligible && !grantReply}/><span><strong>回复 Google 评论</strong><small>可代表此门店直接提交和修改评论回复。</small></span></label><label className="gbp-check"><input type="checkbox" checked={grantPublish} onChange={event => { setGrantPublish(event.target.checked); setConfirmed(false); }} disabled={busy || controlNeedsRefresh || !currentGrant.eligible && !grantPublish}/><span><strong>发布 Google 帖子</strong><small>可将此客户已审核的 Google 任务发布到此门店。</small></span></label>{(currentGrant.can_reply && !grantReply || currentGrant.can_publish && !grantPublish) && <p className="gbp-help warning">撤销会阻止后续操作，已提交给 Google 的请求需等待结果。</p>}<div className="gbp-location-preview"><strong>{currentGrant.name} 的权限预览</strong><span>{[grantReply && '可回复评论', grantPublish && '可发布已审核帖子'].filter(Boolean).join(' · ') || '撤销此门店的 Google 操作授权'}</span><small>仅针对 {modal.binding.title}，不开放其他客户、财务或私人空间。</small></div></>}{!grants.employees.some(row => row.eligible) && <p className="gbp-help">暂无具备客户交付协作权限的员工。请先在客户中心完成原有邀请授权。</p>}<div className="gbp-grant-summary"><h4>当前已开放</h4>{grants.employees.filter(row => row.can_reply || row.can_publish).map(row => <p key={row.employee_id}><strong>{row.name}</strong><span>{[row.can_reply && '评论回复', row.can_publish && '帖子发布'].filter(Boolean).join(' · ')}</span></p>)}{!grants.employees.some(row => row.can_reply || row.can_publish) && <p>尚未向员工开放 Google 操作。</p>}</div></>}</div>}
          {modal?.kind === 'reply' && <div className="gbp-form"><div className="gbp-original-review"><strong>{modal.review.reviewer_name || 'Google 用户'}<span>{ratingNumber(modal.review.rating)} 星</span></strong><p>{modal.review.comment || '这条评价没有文字内容。'}</p></div><GoogleReviewAssistant scope={scope} bindingId={modal.binding.id} customerName={modal.binding.customer_name} review={modal.review} reply={reply} isOwner={owner} onReply={value => { setReply(value); setAiApproval(null); setConfirmed(false); }} onApproval={setAiApproval} onBusy={changeAiBusy}/><label>公开回复内容<Textarea aria-label="Google 评论回复内容" value={reply} onChange={event => { setReply(event.target.value); setConfirmed(false); setModalError(''); }} rows={7} maxLength={4096} disabled={busy || aiBusy || unknown}/><span className={`gbp-help ${googleReplyBytes(reply.trim()) > 4096 ? 'warning' : ''}`}>已用 {googleReplyBytes(reply)} / 4096 字节 · 将以商家身份提交，公开展示以 Google 确认为准。</span></label>{needsOwnerApproval && <p className="gbp-help warning">需老板批准当前回复文本。可在上方保存并交老板复核。</p>}{modal.review.reply && <p className="gbp-help warning">该评论已有回复，本次确认将修改现有商家回复。</p>}</div>}
          {modal?.kind === 'publish' && <div className="gbp-form"><div className="gbp-location-preview"><strong>发布到：{modal.binding.title}</strong><span>{modal.binding.address}</span></div><div className="gbp-publish-preview"><span className="gbp-pill gbp-pill-success">审核已通过 · 任务 #{modal.task.id}</span><h3>{modal.task.title}</h3><p>{modal.task.content}</p>{modal.task.preview_image_url && <ImagePreview src={modal.task.preview_image_url} title={modal.task.material_title || '已审核图片'}/>} {modal.task.publish_blocked_reason && <p className="gbp-help warning">{modal.task.publish_blocked_reason}</p>}{modal.task.material_id && <small>图片：{modal.task.material_title || '已审核素材'} · 使用老板审核的图片链接，外部来源仍可能更新图片内容。</small>}</div><p className="gbp-help">按已审核版本发布。Google 可能继续处理或审核内容，提交成功不等于已经公开展示。</p></div>}
          {modal?.kind === 'disconnect_connection' && <div className="gbp-dialog-copy"><Unplug aria-hidden="true"/><h3>{modal.connection.label}</h3><p>将停止这个连接下所有门店的 CRM 操作，并撤销员工的相关 Google 操作授权。</p><p>撤销会阻止后续操作，已提交给 Google 的请求需等待结果。</p><p>不会删除 Google 门店或已发布内容。再次使用需要重新连接、绑定并授权。</p></div>}
          {modal?.kind === 'disconnect_binding' && <div className="gbp-dialog-copy"><Unplug aria-hidden="true"/><h3>停止此门店的 Google 操作</h3><p>此门店的员工回复和发布授权将停止，不影响其他门店。</p><p>撤销会阻止后续操作，已提交给 Google 的请求需等待结果。</p><p>原客户资料、邀请权限和 Google 已发布内容保持原样。</p></div>}
          {modal?.kind === 'action' && <div className="gbp-action-detail"><span className={`gbp-pill gbp-result-${modal.action.status}`}>{gbpActionLabels[modal.action.status]}</span><h3>{modal.action.kind === 'review_reply' ? '评论回复结果' : '帖子发布结果'}</h3><p>{modal.action.message}</p>{modal.action.content && <section className="gbp-audit-content"><h4>本次提交内容</h4><p>{modal.action.content}</p></section>}<dl><div><dt>操作者</dt><dd>{modal.action.actor_name}</dd></div><div><dt>提交时间</dt><dd>{formatTime(modal.action.created_at)}（北京时间）</dd></div><div><dt>最近确认</dt><dd>{formatTime(modal.action.updated_at)}（北京时间）</dd></div>{modal.action.provider_state && <div><dt>Google 状态</dt><dd>{providerStateLabel(modal.action.provider_state)}</dd></div>}</dl>{googlePublicUrl(modal.action.provider_url) && <a className="gbp-external" href={googlePublicUrl(modal.action.provider_url)!} target="_blank" rel="noopener noreferrer">查看 Google 页面<ExternalLink aria-hidden="true"/></a>}{modal.action.can_reconcile && <p className="gbp-help">查询只读取 Google 结果，不会再次回复或发布。</p>}{modal.action.kind === 'post_publish' && modal.action.status === 'succeeded' && <p className="gbp-help">Google 已确认发布。对应运营任务仍可按原流程提交链接凭证后完成。</p>}</div>}
          {modal && modal.kind !== 'action' && <label className="gbp-confirm"><input type="checkbox" checked={confirmed} onChange={event => setConfirmed(event.target.checked)} disabled={busy || unknown || controlNeedsRefresh}/><span>{confirmLabel}</span></label>}
          {modalError && <div className="gbp-alert gbp-alert-warn" role="alert"><AlertCircle aria-hidden="true"/><span>{modalError}</span></div>}
          {unknown && <p className="gbp-help">原请求编号：{pending.current?.requestId}</p>}
        </CrmFormDialogBody>
        <CrmFormDialogFooter>{unknown ? <><Button variant="outline" onClick={() => void recover()} disabled={busy}>{busy && <Loader2 className="animate-spin" aria-hidden="true"/>}查询原请求</Button>{notReserved && <Button onClick={() => { if (pending.current) void writePublic(pending.current); }} disabled={busy}>以原编号重新提交</Button>}</> : controlNeedsRefresh ? <Button onClick={() => void refreshControlResult()} disabled={busy}>{busy && <Loader2 className="animate-spin" aria-hidden="true"/>}重新读取实际状态</Button> : modal?.kind === 'action' ? <><Button variant="outline" onClick={close} disabled={busy}>关闭</Button>{modal.action.can_reconcile && <Button onClick={() => void reconcile(modal.action)} disabled={busy}>{busy ? <Loader2 className="animate-spin" aria-hidden="true"/> : <RefreshCw aria-hidden="true"/>}查询 Google 结果</Button>}</> : <><Button variant="outline" onClick={close} disabled={busy}>取消</Button><Button onClick={submitModal} disabled={saveDisabled}>{busy ? <Loader2 className="animate-spin" aria-hidden="true"/> : <Check aria-hidden="true"/>}{busy ? '正在处理…' : modal?.kind === 'connect' ? '前往 Google 授权' : modal?.kind === 'reply' ? '确认公开回复' : modal?.kind === 'publish' ? '确认发布到 Google' : modal?.kind === 'bind' ? '确认绑定门店' : modal?.kind === 'grants' ? '保存门店授权' : '确认断开'}</Button></>}</CrmFormDialogFooter>
      </CrmFormDialogContent>
    </Dialog>
  </section>;
}

function ImagePreview({ src, title }: { src: string; title: string }) {
  const [failed, setFailed] = useState(false);
  const url = googlePreviewImageUrl(src);
  useEffect(() => { setFailed(false); }, [src]);
  if (!url) return <p className="gbp-help warning">图片地址无法安全预览，请先核对素材来源。</p>;
  return failed ? <p className="gbp-help warning">图片暂时无法预览，请在发布前核对来源。<a href={url} target="_blank" rel="noopener noreferrer">查看图片</a></p> : <img className="gbp-image-preview" src={url} alt={title} loading="lazy" referrerPolicy="no-referrer" onError={() => setFailed(true)}/>;
}
function Loading({ label }: { label: string }) { return <div className="gbp-empty" role="status"><Loader2 className="animate-spin" aria-hidden="true"/><p>{label}</p></div>; }
function Empty({ title, text }: { title: string; text: string }) { return <div className="gbp-empty"><FileText aria-hidden="true"/><h3>{title}</h3><p>{text}</p></div>; }
