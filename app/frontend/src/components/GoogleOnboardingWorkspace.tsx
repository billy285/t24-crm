import { useEffect, useRef, useState } from 'react';
import { AlertCircle, ArrowLeft, ArrowRight, CheckCircle2, ChevronDown, ClipboardCheck, Globe2, History, Link2, Loader2, MapPin, RefreshCw, Search, ShieldCheck, Store } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { NativeSelect } from '@/components/ui/native-select';
import { mediaError, mediaErrorStatus, mediaRequestId } from '@/lib/media-operations-api';
import { batchItemLabels, batchLabels, catalogLabels, comparisonLabels, googleOnboardingApi, onboardingAddress, onboardingExpired, onboardingLocationKey, onboardingPending, onboardingRecoveryPointer, verifiedBatchResponse, verifiedCatalogResponse, verifiedOnboardingContext, verifiedOnboardingMutation, verifiedOnboardingRequest, type BatchResponse, type CatalogResponse, type ComparisonState, type GoogleIdentity, type OnboardingComparison, type OnboardingContext, type OnboardingCustomer, type OnboardingExpected, type OnboardingPair, type OnboardingRecoveryPointer } from '@/lib/google-onboarding-api';
import '@/pages/google-onboarding.css';

type Props = { scope: string; isOwner: boolean; customerId?: number; onClose: () => void; onChanged?: () => void };
type Choice = { location_name: string; checked: boolean };
type Pending = { path: string | null; body: Record<string, unknown> | null; expected: OnboardingExpected };
const uncertain = (cause: unknown) => !mediaErrorStatus(cause) || [408, 429].includes(mediaErrorStatus(cause) || 0) || (mediaErrorStatus(cause) || 0) >= 500;
const timeLabel = (value: string | null | undefined) => value && Number.isFinite(Date.parse(value)) ? new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(new Date(value)) : '尚未核验';
const groupOrder: ComparisonState[] = ['eligible', 'review_needed', 'already_bound', 'unmatched', 'inactive'];

export default function GoogleOnboardingWorkspace(props: Props) {
  if (!props.isOwner || props.customerId !== undefined && (!Number.isSafeInteger(props.customerId) || props.customerId < 1)) return null;
  return <OwnerOnboarding key={`${props.scope}:${props.customerId || 'all'}`} {...props}/>;
}

function OwnerOnboarding({ scope, customerId, onClose, onChanged }: Props) {
  const customerScope = customerId ?? null, identity = `${scope}:${customerScope ?? 'all'}`;
  const identityRef = useRef(identity); identityRef.current = identity;
  const alive = useRef(true), loadSeq = useRef(0), resourceSeq = useRef(0), busyRef = useRef(false), pending = useRef<Pending | null>(null), changed = useRef(onChanged); changed.current = onChanged;
  const storageKey = `t24-google-onboarding-request:v1:${identity}`;
  const parkedKey = `${storageKey}:retained`;
  const [context, setContext] = useState<OnboardingContext | null>(null), [catalog, setCatalog] = useState<CatalogResponse | null>(null), [batch, setBatch] = useState<BatchResponse | null>(null);
  const [connectionId, setConnectionId] = useState(''), [choices, setChoices] = useState<Record<number, Choice>>({}), [group, setGroup] = useState<ComparisonState>('eligible'), [search, setSearch] = useState('');
  const [loading, setLoading] = useState(true), [busy, setBusy] = useState(false), [unknown, setUnknown] = useState(false), [notFound, setNotFound] = useState(false), [retryConfirmed, setRetryConfirmed] = useState(false);
  const [parkConfirmed, setParkConfirmed] = useState(false), [parked, setParked] = useState<OnboardingRecoveryPointer[]>(readParked);
  const [error, setError] = useState(''), [notice, setNotice] = useState(''), [confirmed, setConfirmed] = useState(false), [cancelOpen, setCancelOpen] = useState(false), [cancelReason, setCancelReason] = useState(''), [cancelConfirmed, setCancelConfirmed] = useState(false);
  const [pollPaused, setPollPaused] = useState(false), [pollEpoch, setPollEpoch] = useState(0), [clock, setClock] = useState(Date.now);
  const contextRef = useRef(context); contextRef.current = context;
  const catalogRef = useRef(catalog); catalogRef.current = catalog;
  const batchRef = useRef(batch); batchRef.current = batch;
  const focus = useRef(''), notified = useRef('');
  const current = () => alive.current && identityRef.current === identity;
  const blocked = loading || busy || unknown;
  const activeBatch = !!batch && onboardingPending(batch.batch.status);
  const activeCatalog = !!catalog && onboardingPending(catalog.catalog.status);
  const batchConnectionId = batch ? catalog?.catalog.id === batch.batch.catalog_id ? catalog.catalog.connection_id : context?.recent_catalogs.find(row => row.id === batch.batch.catalog_id)?.connection_id : null;
  const catalogFresh = catalog?.catalog.status === 'ready' && String(catalog.catalog.connection_id) === connectionId && !onboardingExpired(catalog.catalog.expires_at, clock);
  const previewFresh = batch?.batch.status === 'preview' && !!batchConnectionId && String(batchConnectionId) === connectionId && !onboardingExpired(batch.batch.expires_at, clock);
  const selectedPairs: OnboardingPair[] = Object.entries(choices).filter(([, value]) => value.checked).map(([id, value]) => ({ customer_id: Number(id), location_name: value.location_name }));
  const selectionUnique = new Set(selectedPairs.map(row => onboardingLocationKey(row.location_name))).size === selectedPairs.length;
  const recentCatalogs = context?.recent_catalogs.filter(row => row.customer_id === customerScope) || [];
  const recentBatches = context?.recent_batches.filter(row => row.customer_id === customerScope) || [];
  const availableConnections = context?.connections.filter(row => row.active && !row.needs_reconnect) || [];

  function savePointer(expected: OnboardingExpected) {
    const pointer: OnboardingRecoveryPointer = { request_id: expected.request_id, kind: expected.kind, customer_id: customerScope, ...(expected.resource_id ? { resource_id: expected.resource_id } : {}) };
    try { sessionStorage.setItem(storageKey, JSON.stringify(pointer)); } catch { setNotice('本浏览器无法保留请求编号；已保存的操作仍可从下方最近记录继续核对。'); }
  }
  function clearPointer() { try { sessionStorage.removeItem(storageKey); } catch { /* Server history remains authoritative. */ } }
  function readPointer() { try { return onboardingRecoveryPointer(sessionStorage.getItem(storageKey), customerScope); } catch { return null; } }
  function readParked(): OnboardingRecoveryPointer[] { try { const values = JSON.parse(sessionStorage.getItem(parkedKey) || '[]'); return Array.isArray(values) ? values.slice(0, 10).map(value => onboardingRecoveryPointer(JSON.stringify(value), customerScope)).filter((value): value is OnboardingRecoveryPointer => !!value) : []; } catch { return []; } }
  function retainPointers(values: OnboardingRecoveryPointer[]) { setParked(values); try { sessionStorage.setItem(parkedKey, JSON.stringify(values)); } catch { setNotice('浏览器无法保留原请求编号；请保存下方编号，已保存的服务器记录仍可在最近记录查询。'); } }
  function parkWaiting() {
    const original = pending.current?.expected;
    if (busyRef.current || !unknown || !notFound || !parkConfirmed || !original) return;
    const pointer: OnboardingRecoveryPointer = { request_id: original.request_id, kind: original.kind, customer_id: customerScope, ...(original.resource_id ? { resource_id: original.resource_id } : {}) };
    resourceSeq.current++; focus.current = ''; pending.current = null; clearPointer(); setUnknown(false); setNotFound(false); setRetryConfirmed(false); setParkConfirmed(false); setBatch(null); batchRef.current = null; setCatalog(null); catalogRef.current = null; setChoices({}); setConfirmed(false); setError('');
    setNotice('已结束本页等待，原编号保留在下方。服务器是否执行仍待确认；这不会撤销或重新提交后台请求。');
    retainPointers([pointer, ...parked.filter(row => row.request_id !== pointer.request_id)].slice(0, 10)); void readContext();
  }
  function queryRetained(pointer: OnboardingRecoveryPointer) { if (busyRef.current) return; pending.current = { path: null, body: null, expected: pointer }; savePointer(pointer); setUnknown(true); setParkConfirmed(false); void recover(pointer); }
  function applyCatalog(value: CatalogResponse, reset = false) {
    const previous = catalogRef.current;
    if (previous?.catalog.id === value.catalog.id && previous.catalog.revision > value.catalog.revision) return;
    catalogRef.current = value; setCatalog(value); setConnectionId(String(value.catalog.connection_id)); setBatch(null); batchRef.current = null; setConfirmed(false); setCancelOpen(false);
    if (reset) { setChoices({}); setSearch(''); setGroup(value.comparisons.some(row => row.match_state === 'eligible') ? 'eligible' : 'review_needed'); }
  }
  function applyBatch(value: BatchResponse) {
    const previous = batchRef.current;
    if (previous?.batch.id === value.batch.id && previous.batch.revision > value.batch.revision) return;
    if (previous?.batch.id !== value.batch.id || previous.batch.revision !== value.batch.revision || previous.batch.preview_hash !== value.batch.preview_hash) setConfirmed(false);
    if (previous?.batch.id !== value.batch.id || previous.batch.preview_hash !== value.batch.preview_hash) { setCancelConfirmed(false); setCancelOpen(false); setCancelReason(''); }
    batchRef.current = value; setBatch(value);
    const originalConnection = catalogRef.current?.catalog.id === value.batch.catalog_id ? catalogRef.current.catalog.connection_id : contextRef.current?.recent_catalogs.find(row => row.id === value.batch.catalog_id)?.connection_id;
    setConnectionId(originalConnection ? String(originalConnection) : '');
    if (value.batch.counts.bound && notified.current !== `${value.batch.id}:${value.batch.counts.bound}`) { notified.current = `${value.batch.id}:${value.batch.counts.bound}`; changed.current?.(); }
  }
  function accept(value: CatalogResponse | BatchResponse) { if ('catalog' in value) { focus.current = `catalog:${value.catalog.id}`; applyCatalog(value, true); } else { focus.current = `batch:${value.batch.id}`; applyBatch(value); } setClock(Date.now()); setPollPaused(false); }
  function denySensitive(cause: unknown) { if ([401, 403].includes(mediaErrorStatus(cause) || 0)) { contextRef.current = null; setContext(null); setCatalog(null); setBatch(null); setChoices({}); clearPointer(); retainPointers([]); pending.current = null; setUnknown(false); } }

  async function readContext(signal?: AbortSignal) {
    const seq = ++loadSeq.current;
    try {
      const value = verifiedOnboardingContext(await googleOnboardingApi<OnboardingContext>(`/context${customerScope ? `?customer_id=${customerScope}` : ''}`, 'GET', undefined, signal), customerScope);
      if (!current() || signal?.aborted || seq !== loadSeq.current) return null;
      contextRef.current = value; setContext(value); if (!batchRef.current && !catalogRef.current && value.connections.filter(row => row.active && !row.needs_reconnect).length === 1) setConnectionId(String(value.connections.find(row => row.active && !row.needs_reconnect)!.id)); return value;
    } catch (cause) { if (current() && !signal?.aborted && seq === loadSeq.current) { setError(mediaError(cause, cause instanceof Error ? cause.message : '接入工作台暂时无法读取。')); denySensitive(cause); } return null; }
  }
  async function openCatalog(id: string, signal?: AbortSignal) {
    if (busyRef.current) return;
    const seq = ++resourceSeq.current; focus.current = `catalog:${id}`; setError(''); setPollPaused(false);
    try { const value = verifiedCatalogResponse(await googleOnboardingApi<CatalogResponse>(`/catalogs/${id}`, 'GET', undefined, signal), customerScope, id); if (current() && !signal?.aborted && seq === resourceSeq.current) { applyCatalog(value, true); setConnectionId(String(value.catalog.connection_id)); setClock(Date.now()); } }
    catch (cause) { if (current() && !signal?.aborted && seq === resourceSeq.current) { setError(mediaError(cause, cause instanceof Error ? cause.message : '原门店目录暂时无法读取。')); denySensitive(cause); } }
  }
  async function openBatch(id: string, signal?: AbortSignal) {
    if (busyRef.current) return;
    const seq = ++resourceSeq.current; focus.current = `batch:${id}`; setError(''); setPollPaused(false);
    try { const value = verifiedBatchResponse(await googleOnboardingApi<BatchResponse>(`/batches/${id}`, 'GET', undefined, signal), customerScope, id); if (current() && !signal?.aborted && seq === resourceSeq.current) { applyBatch(value); setClock(Date.now()); } }
    catch (cause) { if (current() && !signal?.aborted && seq === resourceSeq.current) { setError(mediaError(cause, cause instanceof Error ? cause.message : '原接入批次暂时无法读取。')); denySensitive(cause); } }
  }
  async function recover(expected = pending.current?.expected, signal?: AbortSignal) {
    if (!expected || busyRef.current) return;
    resourceSeq.current++; focus.current = ''; busyRef.current = true; setBusy(true); setError(''); setNotFound(false); setParkConfirmed(false);
    try {
      const value = verifiedOnboardingRequest(await googleOnboardingApi(`/requests/${expected.request_id}`, 'GET', undefined, signal), expected);
      if (!current() || signal?.aborted) return;
      accept(value); pending.current = null; setUnknown(false); setRetryConfirmed(false); retainPointers(parked.filter(row => row.request_id !== expected.request_id)); setNotice('已读取原请求的当前实际结果，没有再次提交接入。');
      void readContext();
    } catch (cause) { if (current() && !signal?.aborted) { setUnknown(true); setNotFound(mediaErrorStatus(cause) === 404); setError(mediaError(cause, cause instanceof Error ? cause.message : '原请求暂时无法确认，请继续查询原编号。')); denySensitive(cause); } }
    finally { if (current()) { busyRef.current = false; setBusy(false); } }
  }
  async function mutate(path: string, body: Record<string, unknown>, expected: OnboardingExpected, replayOriginal = false) {
    if (busyRef.current || unknown && !replayOriginal) return;
    resourceSeq.current++; focus.current = '';
    pending.current = { path, body, expected }; savePointer(expected); busyRef.current = true; setBusy(true); setError(''); setNotice(''); setNotFound(false); setRetryConfirmed(false);
    try {
      const value = verifiedOnboardingMutation(await googleOnboardingApi<CatalogResponse | BatchResponse>(path, 'POST', body), expected);
      if (!current()) return;
      accept(value); pending.current = null; setUnknown(false); void readContext();
    } catch (cause) {
      if (!current()) return;
      setError(mediaError(cause, cause instanceof Error ? cause.message : '本次结果暂时无法确认。'));
      if (uncertain(cause)) setUnknown(true);
      else { pending.current = null; clearPointer(); if (mediaErrorStatus(cause) === 409) setNotice('资料或批次版本已变化，请读取当前结果后再核对。'); denySensitive(cause); }
    } finally { if (current()) { busyRef.current = false; setBusy(false); } }
  }

  useEffect(() => {
    alive.current = true; const controller = new AbortController();
    void readContext(controller.signal).then(value => {
      if (!value || !current() || controller.signal.aborted) return;
      const pointer = readPointer();
      if (pointer) { pending.current = { path: null, body: null, expected: pointer }; setUnknown(true); void recover(pointer, controller.signal); }
      else {
        const recent = value.recent_batches.find(row => row.customer_id === customerScope && ['preview', 'queued', 'processing', 'unknown'].includes(row.status));
        const directory = value.recent_catalogs.find(row => row.customer_id === customerScope && ['queued', 'processing', 'ready', 'unknown'].includes(row.status));
        if (recent) void openBatch(recent.id, controller.signal); else if (directory) void openCatalog(directory.id, controller.signal);
      }
    }).finally(() => { if (current() && !controller.signal.aborted) setLoading(false); });
    return () => { alive.current = false; controller.abort(); loadSeq.current++; resourceSeq.current++; pending.current = null; };
    // The keyed owner/scope instance owns its complete request lifecycle.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [identity]);

  useEffect(() => {
    const expires = batch?.batch.status === 'preview' ? batch.batch.expires_at : catalog?.catalog.status === 'ready' ? catalog.catalog.expires_at : null;
    if (!expires || onboardingExpired(expires)) return;
    const timer = setTimeout(() => setClock(Date.now()), Math.max(20, Date.parse(expires) - Date.now() + 20)); return () => clearTimeout(timer);
  }, [batch?.batch.id, batch?.batch.expires_at, batch?.batch.status, catalog?.catalog.id, catalog?.catalog.expires_at, catalog?.catalog.status]);

  useEffect(() => {
    const type = activeBatch ? 'batch' : activeCatalog ? 'catalog' : null;
    const id = type === 'batch' ? batch?.batch.id : catalog?.catalog.id;
    if (!type || !id || pollPaused || unknown) return;
    const controller = new AbortController(), started = Date.now(); let timer: ReturnType<typeof setTimeout>;
    const tick = async () => {
      if (controller.signal.aborted || !current() || focus.current !== `${type}:${id}`) return;
      if (Date.now() - started >= 120000) { setPollPaused(true); return; }
      if (typeof document !== 'undefined' && document.visibilityState === 'hidden') { timer = setTimeout(tick, 4000); return; }
      try {
        if (type === 'batch') { const value = verifiedBatchResponse(await googleOnboardingApi<BatchResponse>(`/batches/${id}`, 'GET', undefined, controller.signal), customerScope, id); if (!controller.signal.aborted && current() && focus.current === `batch:${id}`) applyBatch(value); }
        else { const value = verifiedCatalogResponse(await googleOnboardingApi<CatalogResponse>(`/catalogs/${id}`, 'GET', undefined, controller.signal), customerScope, id); if (!controller.signal.aborted && current() && focus.current === `catalog:${id}`) { applyCatalog(value); if (value.catalog.status === 'ready') setGroup(value.comparisons.some(row => row.match_state === 'eligible') ? 'eligible' : 'review_needed'); } }
      } catch (cause) { if (!controller.signal.aborted && current()) { setError(mediaError(cause, '后台任务仍保留，请稍后读取实际结果。')); denySensitive(cause); } }
      finally { if (!controller.signal.aborted && current()) timer = setTimeout(tick, 2500); }
    };
    timer = setTimeout(tick, 1500); return () => { controller.abort(); clearTimeout(timer); };
    // Revisions update within this one bounded polling session; no POST retries.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [batch?.batch.id, batch?.batch.status, catalog?.catalog.id, catalog?.catalog.status, pollPaused, pollEpoch, unknown]);

  function changeConnection(value: string) {
    if (blocked || activeBatch || activeCatalog) return;
    resourceSeq.current++; focus.current = ''; clearPointer(); pending.current = null; setConnectionId(value); setCatalog(null); catalogRef.current = null; setBatch(null); batchRef.current = null; setChoices({}); setConfirmed(false); setCancelOpen(false); setUnknown(false); setError(''); setNotice('连接已切换，请重新读取这个连接的门店资料。');
  }
  function discover() {
    if (blocked || activeBatch || activeCatalog || !connectionId || !context?.worker_enabled) return;
    const requestId = mediaRequestId(); setChoices({}); setBatch(null); batchRef.current = null;
    void mutate('/catalogs', { request_id: requestId, connection_id: Number(connectionId), ...(customerScope ? { customer_id: customerScope } : {}) }, { request_id: requestId, kind: 'discovery', customer_id: customerScope, connection_id: Number(connectionId) });
  }
  function choose(row: OnboardingComparison, locationName: string) { setChoices(previous => ({ ...previous, [row.customer.id]: { location_name: locationName, checked: false } })); }
  function toggle(row: OnboardingComparison, checked: boolean) { setChoices(previous => ({ ...previous, [row.customer.id]: { location_name: previous[row.customer.id]?.location_name || '', checked } })); }
  function preview() {
    if (!catalogFresh || !catalog || onboardingExpired(catalog.catalog.expires_at) || blocked || !selectionUnique || !selectedPairs.length || selectedPairs.length > 50) return;
    const requestId = mediaRequestId(); void mutate('/previews', { request_id: requestId, catalog_id: catalog.catalog.id, expected_catalog_revision: catalog.catalog.revision, items: selectedPairs }, { request_id: requestId, kind: 'preview', customer_id: customerScope, pairs: selectedPairs });
  }
  function confirmBatch() {
    if (!batch || !previewFresh || onboardingExpired(batch.batch.expires_at) || blocked || !confirmed || !context?.worker_enabled) return;
    const requestId = mediaRequestId(); void mutate(`/batches/${batch.batch.id}/confirm`, { request_id: requestId, expected_revision: batch.batch.revision, preview_hash: batch.batch.preview_hash, confirmed_item_ids: batch.items.map(row => row.id), confirmed: true }, { request_id: requestId, kind: 'confirm', customer_id: customerScope, resource_id: batch.batch.id, preview_hash: batch.batch.preview_hash, pairs: batch.items.map(row => ({ customer_id: row.customer.id, location_name: row.google.location_name })) });
  }
  function stopRemaining() {
    if (!batch || blocked || !cancelConfirmed || !cancelReason.trim() || cancelReason.length > 200) return;
    const requestId = mediaRequestId(); void mutate(`/batches/${batch.batch.id}/cancel`, { request_id: requestId, expected_revision: batch.batch.revision, reason: cancelReason.trim(), confirmed: true }, { request_id: requestId, kind: 'cancel', customer_id: customerScope, resource_id: batch.batch.id, preview_hash: batch.batch.preview_hash });
  }
  function refreshVisible() { setPollPaused(false); setPollEpoch(value => value + 1); if (batch) void openBatch(batch.batch.id); else if (catalog) void openCatalog(catalog.catalog.id); else { setLoading(true); void readContext().finally(() => { if (current()) setLoading(false); }); } }

  const step = batch && batch.batch.status !== 'preview' ? 3 : batch || catalog?.catalog.status === 'ready' ? 2 : 1;
  const comparisons = catalog?.comparisons || [], groupRows = comparisons.filter(row => row.match_state === group && `${row.customer.name} ${onboardingAddress(row.customer)} ${row.candidates.map(value => value.title).join(' ')}`.toLowerCase().includes(search.trim().toLowerCase()));
  const existingLocations = new Set(context?.bindings.map(row => onboardingLocationKey(row.location_name)));
  const viewOnly = blocked || !catalogFresh || !!batch;
  const selectedConnection = context?.connections.find(row => String(row.id) === connectionId);
  return <section className="gbo-workspace" aria-label="Google 门店接入工作台">
    <header className="gbo-header"><div><span className="gbo-eyebrow"><ShieldCheck/>仅老板 · 接入与归属核对</span><h2>{customerScope ? '核对这位客户的 Google 门店' : '批量接入 Google 门店'}</h2><p>先读取门店资料，再逐组核对对应关系，最后保存接入结果。</p></div><Button variant="outline" disabled={busy} onClick={onClose}><ArrowLeft/>返回工作区</Button></header>
    <div className="gbo-boundary"><Link2/><span>这里只建立客户与门店的绑定；不发布内容，不开放员工权限，不修改客户资料。</span></div>
    <ol className="gbo-steps" aria-label="门店接入进度">{['读取门店', '对照确认', '接入结果'].map((label, index) => <li key={label} aria-current={step === index + 1 ? 'step' : undefined} data-complete={step > index + 1}><span>{step > index + 1 ? <CheckCircle2/> : index + 1}</span>{label}</li>)}</ol>
    {error && <div className="gbo-alert" role="alert"><AlertCircle/><div><strong>{unknown ? '先查询原请求，避免重复接入' : '需要核对当前状态'}</strong><p>{error}</p></div></div>}
    {notice && <p className="gbo-notice" role="status">{notice}</p>}
    {unknown && <section className="gbo-recovery"><div><strong>原请求已保留</strong><p>网络中断不代表没有保存。查询会读取原结果，不会再次执行接入。</p></div><Button disabled={busy} onClick={() => void recover()}>{busy ? <Loader2 className="animate-spin"/> : <RefreshCw/>}查询原请求</Button>{notFound && <p>当前尚未查到原编号，请先继续查询。不要重新建立同一批次。</p>}{notFound && pending.current?.path && pending.current.body && <><label className="gbo-check"><input type="checkbox" checked={retryConfirmed} onChange={event => setRetryConfirmed(event.target.checked)} disabled={busy}/><span>已查询原编号且当前未查到，使用完全相同的编号与内容重新提交。</span></label><Button variant="outline" disabled={busy || !retryConfirmed} onClick={() => { const original = pending.current; if (original?.path && original.body) { setUnknown(false); void mutate(original.path, original.body, original.expected, true); } }}>以原编号重新提交</Button></>}{notFound && <div className="gbo-local-wait"><p>也可以先查看下面的服务器最近记录。若暂时结束本页等待，原编号仍保留可查，不代表服务器失败，也不会撤销后台请求。</p><label className="gbo-check"><input type="checkbox" checked={parkConfirmed} onChange={event => setParkConfirmed(event.target.checked)} disabled={busy}/><span>我理解只是结束本页等待，原请求的后台结果仍需核对。</span></label><Button variant="outline" disabled={busy || !parkConfirmed} onClick={parkWaiting}>结束本地等待，保留原编号</Button></div>}</section>}
    {loading && !context ? <div className="gbo-loading" role="status"><Loader2 className="animate-spin"/>正在读取接入范围和最近记录…</div> : !context ? <Button variant="outline" onClick={refreshVisible}>重新读取接入工作台</Button> : <>
      <section className="gbo-panel gbo-source"><div className="gbo-section-title"><div><span className="gbo-number">01</span><h3>选择要核对的 Google 连接</h3></div>{customerScope && <span className="gbo-tag">客户范围已锁定</span>}</div><div className="gbo-source-controls"><label><span>已授权连接</span><NativeSelect aria-label="接入使用的 Google 连接" value={connectionId} onChange={value => changeConnection(value)} disabled={blocked || activeBatch || activeCatalog} options={[{ value: '', label: '选择你已授权的 Google 账号' }, ...availableConnections.map(row => ({ value: String(row.id), label: row.label || `Google 连接 ${row.id}` }))]}/></label><Button disabled={blocked || activeBatch || activeCatalog || !connectionId || !context.worker_enabled} onClick={discover}>{activeCatalog ? <Loader2 className="animate-spin"/> : <RefreshCw/>}{catalog || batch ? '重新读取门店资料' : '读取 Google 门店'}</Button></div><p className="gbo-caption">后台读取，关闭此页后任务仍保留。Google 门店资料来自此账号当前授权范围，不代表 Google Maps 展示或 Google 认证状态。</p>{selectedConnection?.needs_reconnect && <p className="gbo-warning">此连接需要重新授权，请返回 Google 连接面板处理。</p>}{!availableConnections.length && <p className="gbo-warning">尚无有效连接，请先返回 Google 商家面板完成本人授权。</p>}{!context.worker_enabled && <p className="gbo-warning">接入后台尚未启用；现有结果仍可查看，暂不能开始新接入。</p>}</section>
      {catalog && !batch && <section className="gbo-panel"><div className="gbo-section-title"><div><span className="gbo-number">02</span><h3>{catalogLabels[catalog.catalog.status]}</h3></div><Button variant="outline" disabled={busy} onClick={refreshVisible}><RefreshCw/>读取当前结果</Button></div><p className="gbo-caption">{catalog.catalog.message}</p>{activeCatalog && <div className="gbo-progress" role="status"><Loader2 className="animate-spin"/><div><strong>正在后台核对授权门店清单</strong><p>读取完成后再显示可核对的对应关系；现在不会创建任何绑定。</p></div></div>}{(pollPaused || catalog.catalog.status === 'unknown') && <p className="gbo-warning">自动查询已暂停，任务仍保留。点击“读取当前结果”继续核对，不会重新发起读取任务。</p>}{catalog.catalog.truncated && <p className="gbo-warning">本次门店清单未完整返回。没有出现的门店仍待补查，不能据此判断不存在或未授权。</p>}{catalog.catalog.status === 'ready' && <>
        <div className="gbo-read-meta"><span><Globe2/>{catalog.locations.length} 家门店资料</span><span>本次核验：{timeLabel(catalog.catalog.observed_at)}（北京时间）</span><span>{catalogFresh ? '目录有效期 10 分钟' : '目录已过期，请重新读取'}</span></div>
        <div className="gbo-groups" role="group" aria-label="门店对应关系分组">{groupOrder.map(value => <button type="button" key={value} aria-pressed={group === value} onClick={() => setGroup(value)}>{value === 'unmatched' ? catalog.catalog.truncated ? '待补查' : '本次未匹配' : comparisonLabels[value]}<span>{comparisons.filter(row => row.match_state === value).length}</span></button>)}</div>
        <label className="gbo-search"><Search/><Input aria-label="搜索待核对客户或地址" placeholder="搜索客户名称、地址或 Google 门店名称" value={search} onChange={event => setSearch(event.target.value)}/></label>
        {!groupRows.length ? <p className="gbo-empty">当前分组没有匹配记录；可切换分组或调整搜索。</p> : <div className="gbo-comparisons">{groupRows.map(row => {
          const choice = choices[row.customer.id], chosen = catalog.locations.find(value => value.location_name === choice?.location_name), suggested = row.candidates[0] || row.existing_binding?.google_identity || null;
          const canSelect = !['already_bound', 'inactive'].includes(row.match_state) && !row.existing_binding;
          const options = catalog.locations.filter(value => !existingLocations.has(onboardingLocationKey(value.location_name)) && (!Object.entries(choices).some(([other, picked]) => Number(other) !== row.customer.id && picked.checked && onboardingLocationKey(picked.location_name) === onboardingLocationKey(value.location_name))));
          const recommended = new Set(row.candidates.map(value => value.location_name)); options.sort((a, b) => Number(recommended.has(b.location_name)) - Number(recommended.has(a.location_name)));
          return <article className="gbo-comparison" key={row.customer.id}><header><strong>{row.customer.name}</strong><span className={`gbo-tag ${row.match_state === 'review_needed' ? 'warning' : ''}`}>{row.match_state === 'unmatched' && catalog.catalog.truncated ? '清单未完整 · 待补查' : comparisonLabels[row.match_state]}</span></header><IdentityComparison customer={row.customer} google={chosen || suggested} googleHint={!chosen && canSelect ? '建议资料，尚未选定' : row.candidates.length ? '本次读取资料' : row.existing_binding?.google_identity ? '已保存的身份摘要' : undefined}/>{row.reasons.length > 0 && <ul className="gbo-reasons">{row.reasons.map((reason, index) => <li key={index}>{reason}</li>)}</ul>}{row.existing_binding && !suggested && <p className="gbo-caption">此客户已有绑定。本次未保留可展示的 Google 身份摘要；原绑定保持不变，不会重新绑定。</p>}{canSelect ? <div className="gbo-choice"><label><span>明确选择对应的 Google 门店</span><NativeSelect aria-label={`为 ${row.customer.name} 选择 Google 门店`} value={choice?.location_name || ''} onChange={value => choose(row, value)} disabled={viewOnly} options={[{ value: '', label: '请核对后选择，不会自动选中' }, ...options.map(value => ({ value: value.location_name, label: `${recommended.has(value.location_name) ? '建议 · ' : ''}${value.title} · ${value.address || '地址待核对'}` }))]}/></label><label className="gbo-check"><input type="checkbox" aria-label={`确认 ${row.customer.name} 的名称地址并加入本批`} checked={!!choice?.checked} onChange={event => toggle(row, event.target.checked)} disabled={viewOnly || !chosen || !chosen.title.trim() || !chosen.address.trim() || !choice?.checked && selectedPairs.length >= 50}/><span>我已核对两侧名称和地址，确认同一家门店，加入本批。</span></label></div> : <p className="gbo-caption">{row.match_state === 'inactive' ? '不在当前合作范围，不加入新接入。' : '已有对应关系，本批不会修改或重复创建绑定。'}</p>}</article>;
        })}</div>}
        <footer className="gbo-actionbar"><div><strong>已逐项核对 {selectedPairs.length} 家</strong><span>每批最多 50 家 · 下一步仍是预检，不会立即绑定</span>{!selectionUnique && <span className="gbo-warning">同一 Google 门店不能分配给不同客户，请调整选择。</span>}</div><Button disabled={viewOnly || !selectionUnique || !selectedPairs.length || selectedPairs.length > 50} onClick={preview}>预检所选对应关系<ArrowRight/></Button></footer>
      </>}</section>}
      {batch && <section className="gbo-panel gbo-batch"><div className="gbo-section-title"><div><span className="gbo-number">{batch.batch.status === 'preview' ? '02' : '03'}</span><h3>{batchLabels[batch.batch.status]}</h3></div><Button variant="outline" disabled={busy} onClick={refreshVisible}><RefreshCw/>刷新本批结果</Button></div><p className="gbo-caption">{batch.batch.message}</p><div className="gbo-counts"><div><span>本批客户</span><strong>{batch.batch.counts.total}</strong></div><div><span>已绑定</span><strong>{batch.batch.counts.bound}</strong></div><div><span>处理中</span><strong>{batch.batch.counts.queued + batch.batch.counts.processing}</strong></div><div><span>需核对</span><strong>{batch.batch.counts.conflict + batch.batch.counts.failed + batch.batch.counts.unknown}</strong></div></div>{batch.batch.status === 'preview' ? <p className={previewFresh ? 'gbo-caption' : 'gbo-warning'}>此预检尚未创建绑定。{previewFresh ? `请在 ${timeLabel(batch.batch.expires_at)}（北京时间）前核对并确认。` : '预检已过期，请回到目录重新预检。'}</p> : <p className="gbo-caption">每行独立保存实际结果。已成功的不会因为其他行失败而重复接入；存在疑问的单独保留。</p>}{(pollPaused || batch.batch.status === 'unknown') && <p className="gbo-warning">请刷新原批次查看实际结果；不要重新提交同一批。暂未确认的行不会显示为已成功。</p>}
        <div className="gbo-batch-items">{batch.items.map(row => <article className="gbo-comparison" key={row.id}><header><strong>{row.position + (batch.items.some(item => item.position === 0) ? 1 : 0)}. {row.customer.name}</strong><span className={`gbo-tag ${row.status === 'bound' ? 'success' : ['conflict', 'failed', 'unknown'].includes(row.status) ? 'warning' : ''}`}>{batchItemLabels[row.status]}</span></header><IdentityComparison customer={row.customer} google={row.google}/>{row.warnings.length > 0 && <ul className="gbo-reasons">{row.warnings.map((message, index) => <li key={index}>{message}</li>)}</ul>}<p className={['conflict', 'failed', 'unknown'].includes(row.status) ? 'gbo-warning' : 'gbo-caption'}>{row.message}</p></article>)}</div>
        {batch.batch.status === 'preview' && <footer className="gbo-confirmation"><label className="gbo-check"><input type="checkbox" checked={confirmed} disabled={blocked || !previewFresh} onChange={event => setConfirmed(event.target.checked)}/><span>我已核对本批 {batch.items.length} 组客户与门店，确认一一对应，只保存绑定，不发布内容或开放员工权限。</span></label><div className="gbo-confirm-actions">{batch.batch.catalog_id && <Button variant="outline" disabled={blocked} onClick={() => void openCatalog(batch.batch.catalog_id!)}>返回目录调整选择</Button>}<Button disabled={blocked || !previewFresh || !confirmed || !context.worker_enabled} onClick={confirmBatch}>{busy ? <Loader2 className="animate-spin"/> : <ClipboardCheck/>}确认接入 {batch.items.length} 家</Button></div></footer>}
        {(batch.batch.counts.queued > 0 || batch.batch.counts.processing > 0) && <div className="gbo-stop"><Button variant="outline" disabled={blocked} onClick={() => { setCancelOpen(value => !value); setCancelConfirmed(false); }}>停止尚未完成的接入</Button>{cancelOpen && <div><label>停止原因<Textarea aria-label="停止本批剩余接入的原因" value={cancelReason} onChange={event => setCancelReason(event.target.value)} maxLength={200} rows={2} disabled={blocked}/></label><label className="gbo-check"><input type="checkbox" checked={cancelConfirmed} onChange={event => setCancelConfirmed(event.target.checked)} disabled={blocked}/><span>仅停止还未完成的行；已经成功绑定的客户保持不变。</span></label><Button variant="outline" disabled={blocked || !cancelConfirmed || !cancelReason.trim()} onClick={stopRemaining}>确认停止剩余接入</Button></div>}</div>}
        <details className="gbo-evidence"><summary>查看本批操作凭据<ChevronDown/></summary><dl><div><dt>保存时间</dt><dd>{timeLabel(batch.batch.created_at)}（北京时间）</dd></div><div><dt>最近更新</dt><dd>{timeLabel(batch.batch.updated_at)}（北京时间）</dd></div><div><dt>批次编号</dt><dd>{batch.batch.id}</dd></div><div><dt>预检版本</dt><dd>{batch.batch.preview_hash}</dd></div></dl></details>
      </section>}
      {(recentBatches.length > 0 || recentCatalogs.length > 0 || parked.length > 0) && <details className="gbo-panel gbo-history"><summary><span><History/>最近读取与接入记录</span><ChevronDown/></summary><p className="gbo-caption">记录保存在系统中。打开只读取当前结果，不会重新绑定。</p>{parked.map(row => <div className="gbo-retained-request" key={row.request_id}><div><strong>保留的原请求 · 结果待核对</strong><code>{row.request_id}</code></div><Button variant="outline" disabled={busy} onClick={() => queryRetained(row)}>查询保留请求</Button></div>)}{recentBatches.map(row => <button type="button" key={row.id} disabled={busy} onClick={() => void openBatch(row.id)}><span><strong>{batchLabels[row.status]}</strong><small>{timeLabel(row.updated_at)} · {row.counts.total} 家 · 已绑定 {row.counts.bound}</small></span><ArrowRight/></button>)}{recentCatalogs.map(row => <button type="button" key={row.id} disabled={busy} onClick={() => void openCatalog(row.id)}><span><strong>{catalogLabels[row.status]}</strong><small>{row.observed_at ? `${timeLabel(row.observed_at)} · ` : ''}{row.total_locations} 家门店资料{row.truncated ? ' · 清单未完整' : ''}</small></span><ArrowRight/></button>)}</details>}
    </>}
  </section>;
}

function IdentityComparison({ customer, google, googleHint }: { customer: OnboardingCustomer; google: GoogleIdentity | null; googleHint?: string }) {
  const status = customer.status === 'closed' ? '合作中' : customer.status ? '非合作已成交状态' : '合作状态待核对';
  return <div className="gbo-identity-grid"><section><span className="gbo-identity-label"><Store/>CRM 客户<span>{status}</span></span><strong>{customer.name}</strong><p><MapPin/>{onboardingAddress(customer)}</p><small>客户编号 {customer.id} · 客户资料保持原样</small></section><section><span className="gbo-identity-label"><Globe2/>Google 门店资料</span>{google ? <><strong>{google.title || '名称待核对'}</strong><p><MapPin/>{google.address || 'Google 未返回地址，先不要绑定'}</p><small>{googleHint ? `${googleHint} · ` : ''}本次核验 {timeLabel(google.observed_at)}（北京时间）</small></> : <><strong>尚无可核对的门店资料</strong><p>请先完成读取或明确选择门店，不能按名称猜测归属。</p></>}</section></div>;
}
