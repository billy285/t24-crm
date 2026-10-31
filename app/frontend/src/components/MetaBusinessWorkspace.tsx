import { useCallback, useEffect, useRef, useState } from 'react';
import { AlertCircle, CheckCircle2, Link2, Loader2, RefreshCw, ShieldCheck, Unplug } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { NativeSelect } from '@/components/ui/native-select';
import { Dialog, DialogDescription, DialogTitle, CrmFormDialogBody, CrmFormDialogContent, CrmFormDialogFooter, CrmFormDialogHeader } from '@/components/ui/dialog';
import { useHardNavigationBlock, useUnsavedChanges } from '@/lib/use-unsaved-changes';
import { mediaError, mediaErrorStatus, mediaRequestId } from '@/lib/media-operations-api';
import { metaAuthorizationUrl, metaBusinessApi, metaPlatformLabel, metaRequestScope, verifiedMetaAssets, verifiedMetaBinding, verifiedMetaOptions, verifiedMetaStatus, type MetaAsset, type MetaAssets, type MetaAuthorization, type MetaBinding, type MetaConnection, type MetaOAuthStart, type MetaOptions, type MetaStatus } from '@/lib/meta-business-api';
import './meta-business.css';

type Props = { scope: string; isOwner: boolean; onChanged?: () => void };
type Modal = { kind: 'connect'; connection?: MetaConnection } | { kind: 'bind' } | { kind: 'disconnect_binding'; binding: MetaBinding } | { kind: 'disconnect_connection'; connection: MetaConnection };
type OAuthWrite = { kind: 'oauth'; requestId: string; data: { request_id: string; confirmed: true; reconnect_connection_id?: number }; authorization: MetaAuthorization };
type BindWrite = { kind: 'bind'; requestId: string; data: { request_id: string; customer_id: number; connection_id: number; asset_ref: string; confirmed: true }; platform: MetaAsset['platform'] };
type ControlWrite = { kind: 'control'; path: string; data: { confirmed: true; expected_revision?: number }; target: 'binding' | 'connection'; targetId: number };
type Pending = OAuthWrite | BindWrite | ControlWrite;
const emptyOptions: MetaOptions = { customers: [] };
const emptyAssets: MetaAssets = { items: [], truncated: false };
const uncertainError = (cause: unknown) => !mediaErrorStatus(cause) || [408, 429].includes(mediaErrorStatus(cause) || 0) || (mediaErrorStatus(cause) || 0) >= 500;
const formatTime = (value: string | null) => value && Number.isFinite(Date.parse(value)) ? new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(new Date(value)) : '时间待核对';

export default function MetaBusinessWorkspace({ scope, isOwner, onChanged }: Props) {
  const identity = `${scope}:${isOwner ? 'owner' : 'staff'}`, fence = useRef(metaRequestScope(identity)); fence.current.update(identity);
  const [resolvedIdentity, setResolvedIdentity] = useState(identity);
  const [status, setStatus] = useState<MetaStatus | null>(null), [loading, setLoading] = useState(true), [error, setError] = useState(''), [notice, setNotice] = useState('');
  const [modal, setModal] = useState<Modal | null>(null), [modalError, setModalError] = useState('');
  const [confirmed, setConfirmed] = useState(false), [busy, setBusy] = useState(false), [unknown, setUnknown] = useState(false), [notFound, setNotFound] = useState(false), [expired, setExpired] = useState(false);
  const [options, setOptions] = useState<MetaOptions>(emptyOptions), [optionsLoading, setOptionsLoading] = useState(false);
  const [assets, setAssets] = useState<MetaAssets>(emptyAssets), [assetsLoading, setAssetsLoading] = useState(false), [assetsError, setAssetsError] = useState('');
  const [customer, setCustomer] = useState(''), [connection, setConnection] = useState(''), [asset, setAsset] = useState('');
  const statusSeq = useRef(0), modalSeq = useRef(0), assetsSeq = useRef(0), busyRef = useRef(false), pending = useRef<Pending | null>(null);
  const connectionRef = useRef(connection), customerRef = useRef(customer); connectionRef.current = connection; customerRef.current = customer;
  const owner = isOwner && status?.is_owner === true;
  const canConnect = owner && status.enabled && status.configured && !!status.authorization;
  const pickedCustomer = options.customers.find(row => String(row.id) === customer);
  const pickedConnection = status?.connections.find(row => String(row.id) === connection && row.active && !row.needs_reconnect);
  const pickedAsset = assets.items.find(row => row.asset_ref === asset);
  const existingBinding = status?.bindings.find(row => row.active && row.customer_id === pickedCustomer?.id && row.platform === pickedAsset?.platform);
  const dirty = !!modal && (confirmed || modal.kind === 'bind' && Boolean(customer || asset));
  const guard = useUnsavedChanges(dirty), hold = useHardNavigationBlock(busy || unknown);

  const loadStatus = useCallback(async () => {
    if (!isOwner) return null;
    const current = fence.current.capture(), seq = ++statusSeq.current;
    setLoading(true); setError('');
    try {
      const value = verifiedMetaStatus(await metaBusinessApi<MetaStatus>('/status'));
      if (!current() || seq !== statusSeq.current) return null;
      setStatus(value); return value;
    } catch (cause) { if (current() && seq === statusSeq.current) { setStatus(null); setError(mediaError(cause, cause instanceof Error ? cause.message : 'Meta 连接状态暂时无法读取。')); } return null; }
    finally { if (current() && seq === statusSeq.current) setLoading(false); }
  }, [identity, isOwner]);

  useEffect(() => {
    fence.current.activate(); setResolvedIdentity(identity); statusSeq.current++; modalSeq.current++; assetsSeq.current++;
    setStatus(null); setModal(null); setError(''); setModalError(''); setNotice(''); setConfirmed(false); setBusy(false); setUnknown(false); setNotFound(false); setExpired(false);
    setOptions(emptyOptions); setAssets(emptyAssets); setOptionsLoading(false); setAssetsLoading(false); setAssetsError(''); setCustomer(''); setConnection(''); setAsset(''); customerRef.current = ''; connectionRef.current = ''; busyRef.current = false; pending.current = null; guard.markSaved(); hold.release();
    if (isOwner) {
      const current = fence.current.capture();
      void loadStatus().then(value => {
        if (!current() || !value) return;
        const result = new URLSearchParams(window.location.search).get('meta');
        if (result === 'connected') setNotice(value.connections.some(row => row.active && !row.needs_reconnect) ? '已读取实际 Meta 连接。请逐一核对主页或账号与 CRM 客户的对应关系。' : '已返回 CRM，当前尚未发现有效连接，请核对后重试。');
        if (result === 'failed') setNotice('上次 Meta 授权未完成。当前列表显示实际保存的连接状态。');
      });
    } else setLoading(false);
    return () => { fence.current.invalidate(); statusSeq.current++; modalSeq.current++; assetsSeq.current++; };
  }, [identity, isOwner, loadStatus]);

  function lock() { busyRef.current = true; setBusy(true); hold.lock(); }
  function unlock() { busyRef.current = false; setBusy(false); if (!pending.current) hold.release(); }
  function close() {
    if (busyRef.current || unknown || !guard.confirmDiscard()) return;
    modalSeq.current++; assetsSeq.current++; setModal(null); setModalError(''); setConfirmed(false); setOptions(emptyOptions); setAssets(emptyAssets); setAsset(''); setCustomer(''); setConnection(''); connectionRef.current = ''; customerRef.current = ''; guard.markSaved();
  }
  function open(next: Modal) {
    if (!owner || busyRef.current || unknown || pending.current) return;
    const generation = ++modalSeq.current; assetsSeq.current++;
    setModal(next); setModalError(''); setConfirmed(false); setNotFound(false); setExpired(false); setOptions(emptyOptions); setAssets(emptyAssets); setOptionsLoading(false); setAssetsLoading(false); setAssetsError(''); setCustomer(''); setConnection(''); setAsset(''); customerRef.current = ''; connectionRef.current = '';
    if (next.kind === 'bind') {
      const current = fence.current.capture(); setOptionsLoading(true);
      void metaBusinessApi<MetaOptions>('/options').then(verifiedMetaOptions).then(value => { if (current() && modalSeq.current === generation) setOptions(value); })
        .catch(cause => { if (current() && modalSeq.current === generation) setModalError(mediaError(cause, '可绑定客户暂时无法读取。')); })
        .finally(() => { if (current() && modalSeq.current === generation) setOptionsLoading(false); });
    }
  }
  async function loadAssets(connectionId: string) {
    const current = fence.current.capture(), generation = modalSeq.current, seq = ++assetsSeq.current, selectedCustomer = customerRef.current;
    setAssets(emptyAssets); setAsset(''); setConfirmed(false); setAssetsError(''); setAssetsLoading(false);
    if (!connectionId) return;
    setAssetsLoading(true);
    try {
      const value = verifiedMetaAssets(await metaBusinessApi<MetaAssets>(`/connections/${Number(connectionId)}/assets`));
      if (current() && generation === modalSeq.current && seq === assetsSeq.current && connectionRef.current === connectionId && customerRef.current === selectedCustomer) setAssets(value);
    } catch (cause) { if (current() && generation === modalSeq.current && seq === assetsSeq.current) setAssetsError(mediaError(cause, cause instanceof Error ? cause.message : 'Meta 可选账号暂时无法读取。')); }
    finally { if (current() && generation === modalSeq.current && seq === assetsSeq.current) setAssetsLoading(false); }
  }
  function chooseCustomer(value: string) { if (busyRef.current || unknown) return; customerRef.current = value; setCustomer(value); setAsset(''); setConfirmed(false); void loadAssets(connectionRef.current); }
  function chooseConnection(value: string) { if (busyRef.current || unknown) return; connectionRef.current = value; setConnection(value); setAsset(''); setConfirmed(false); void loadAssets(value); }
  function finished(value: MetaBinding, request: BindWrite) {
    verifiedMetaBinding(value);
    if (value.customer_id !== request.data.customer_id || value.connection_id !== request.data.connection_id || value.platform !== request.platform) throw new Error('Meta 绑定结果与本次确认的客户或平台不一致，请查询原请求。');
    pending.current = null; setUnknown(false); setNotFound(false); setExpired(false); setModal(null); setConfirmed(false); setNotice(value.active ? '客户账号绑定已保存。本阶段只建立连接与归属，尚未开放发帖、评论或员工操作。' : '已读取原请求的绑定记录，当前已断开。请按实际状态核对。'); guard.markSaved(); hold.release(); onChanged?.(); void loadStatus();
  }
  function navigateOAuth(value: MetaOAuthStart, request: OAuthWrite) {
    const url = metaAuthorizationUrl(value?.authorization_url, request.authorization);
    if (!url || !Number.isSafeInteger(value.expires_in) || value.expires_in < 1 || value.expires_in > 600) throw new Error('Meta 授权链接或范围无法核实，请查询原请求，不要重复获取新链接。');
    guard.markSaved(); pending.current = null; setUnknown(false); hold.release(); window.location.assign(url);
  }
  async function send(request: Pending) {
    if (busyRef.current || !owner || unknown && pending.current !== request) return;
    const current = fence.current.capture(); pending.current = request; lock(); setModalError(''); setNotFound(false); setExpired(false);
    try {
      if (request.kind === 'oauth') {
        const value = await metaBusinessApi<MetaOAuthStart>('/oauth/start', 'POST', request.data);
        if (current()) navigateOAuth(value, request);
      } else if (request.kind === 'bind') {
        const value = await metaBusinessApi<MetaBinding>('/bindings', 'POST', request.data);
        if (current()) finished(value, request);
      } else {
        await metaBusinessApi(request.path, 'POST', request.data);
        if (!current()) return;
        const value = await loadStatus(); if (!current()) return;
        if (!value) throw new Error('操作后的实际状态尚未确认，请重新读取。');
        const target = request.target === 'binding' ? value.bindings.find(row => row.id === request.targetId) : value.connections.find(row => row.id === request.targetId);
        if (target?.active) throw new Error('当前连接仍显示有效，请重新读取实际状态后核对。');
        pending.current = null; setUnknown(false); setModal(null); setConfirmed(false); setNotice('已核对断开后的实际状态，历史记录保留。'); guard.markSaved(); hold.release(); onChanged?.();
      }
    } catch (cause) {
      if (!current()) return;
      if (uncertainError(cause)) { setUnknown(true); setModalError('保存结果待确认。请查询原请求，确认前不会重复绑定或重新生成授权请求。'); }
      else {
        pending.current = null; setUnknown(false); setConfirmed(false); hold.release(); setModalError(mediaError(cause, '本次操作未完成，请核对后重试。'));
        if ([401, 403, 404].includes(mediaErrorStatus(cause) || 0)) { setModal(null); guard.markSaved(); void loadStatus(); }
        else if (mediaErrorStatus(cause) === 409) {
          if (request.kind === 'control') { setModal(null); guard.markSaved(); setNotice('连接或绑定已变化，请根据重新读取后的实际状态再次核对。'); }
          void loadStatus();
        }
      }
    } finally { if (current()) unlock(); }
  }
  async function recover() {
    const request = pending.current;
    if (!request || busyRef.current) return;
    if (request.kind === 'control') { void readActualState(); return; }
    const current = fence.current.capture(); lock(); setModalError(''); setNotFound(false); setExpired(false);
    try {
      if (request.kind === 'oauth') {
        const value = await metaBusinessApi<MetaOAuthStart>(`/oauth/requests/${encodeURIComponent(request.requestId)}`);
        if (current()) navigateOAuth(value, request);
      } else {
        const value = await metaBusinessApi<MetaBinding>(`/requests/${encodeURIComponent(request.requestId)}`);
        if (current()) finished(value, request);
      }
    } catch (cause) {
      if (!current()) return;
      if ([401, 403].includes(mediaErrorStatus(cause) || 0)) { pending.current = null; setUnknown(false); setModal(null); setStatus(null); guard.markSaved(); hold.release(); void loadStatus(); return; }
      setNotFound(mediaErrorStatus(cause) === 404); setExpired(request.kind === 'oauth' && mediaErrorStatus(cause) === 409);
      setModalError(mediaErrorStatus(cause) === 404 ? '尚未找到原请求。可以继续查询，或明确沿用原编号确认同一操作。' : request.kind === 'oauth' && mediaErrorStatus(cause) === 409 ? '原授权链接已失效或已使用。请读取实际连接状态后结束本次请求，再决定是否重新授权。' : mediaError(cause, '暂时仍无法确认，请稍后继续查询原请求。'));
    } finally { if (current()) unlock(); }
  }
  async function readActualState() {
    if (busyRef.current) return;
    const current = fence.current.capture(); lock();
    try {
      const value = await loadStatus(); if (!current() || !value) return;
      pending.current = null; setUnknown(false); setNotFound(false); setExpired(false); setModal(null); setConfirmed(false); guard.markSaved(); hold.release(); setNotice('已重新读取当前实际连接和绑定状态，请核对列表后继续。'); onChanged?.();
    } finally { if (current()) unlock(); }
  }
  function submit() {
    if (!modal || !owner || busyRef.current || unknown || !confirmed || pending.current) return;
    if (modal.kind === 'connect') {
      if (!canConnect || !status?.authorization) return;
      const requestId = mediaRequestId(); void send({ kind: 'oauth', requestId, authorization: status.authorization, data: { request_id: requestId, confirmed: true, ...(modal.connection ? { reconnect_connection_id: modal.connection.id } : {}) } });
    } else if (modal.kind === 'bind') {
      if (!pickedCustomer || !pickedConnection || !pickedAsset || assetsLoading || optionsLoading || existingBinding) { setModalError('请重新核对客户、有效连接和可选账号。一个客户同一平台只能保留一个有效绑定。'); return; }
      const requestId = mediaRequestId(); void send({ kind: 'bind', requestId, platform: pickedAsset.platform, data: { request_id: requestId, customer_id: pickedCustomer.id, connection_id: pickedConnection.id, asset_ref: pickedAsset.asset_ref, confirmed: true } });
    } else if (modal.kind === 'disconnect_binding') void send({ kind: 'control', target: 'binding', targetId: modal.binding.id, path: `/bindings/${modal.binding.id}/disconnect`, data: { confirmed: true, expected_revision: modal.binding.revision } });
    else void send({ kind: 'control', target: 'connection', targetId: modal.connection.id, path: `/connections/${modal.connection.id}/disconnect`, data: { confirmed: true, expected_revision: modal.connection.revision } });
  }

  if (!isOwner) return <section className="meta-workspace meta-empty" aria-label="Facebook 与 Instagram 连接"><ShieldCheck/><h2>连接阶段仅向老板开放</h2><p>当前不会向员工展示老板的 Meta 连接、账号资产或新增操作权限。现有 Facebook／Instagram 人工任务照常使用。</p></section>;
  if (resolvedIdentity !== identity || loading && !status) return <section className="meta-workspace meta-empty" role="status"><Loader2 className="animate-spin"/><h2>正在读取 Meta 连接范围</h2><p>完整返回后再显示账号与客户绑定。</p></section>;
  const title = modal?.kind === 'connect' ? modal.connection ? '重新授权 Meta' : '连接 Facebook／Instagram' : modal?.kind === 'bind' ? '绑定客户与 Meta 账号' : modal?.kind === 'disconnect_binding' ? '断开客户账号绑定' : '断开 Meta 连接';
  const bindReady = modal?.kind === 'bind' && !!pickedCustomer && !!pickedConnection && !!pickedAsset && !assetsLoading && !optionsLoading && !assetsError && !existingBinding;
  const saveDisabled = busy || unknown || !confirmed || modal?.kind === 'connect' && !canConnect || modal?.kind === 'bind' && !bindReady;
  return <section className="meta-workspace" aria-label="Facebook 与 Instagram 连接">
    <header className="meta-heading"><div><p className="meta-eyebrow">Facebook / Instagram · 第一步</p><h2>平台连接与客户归属</h2><p>先由老板授权并核对账号。发帖、评论和员工操作将逐项接入，现有任务继续人工交付。</p></div><Button variant="outline" aria-label="刷新 Meta 连接状态" disabled={loading || busy || unknown} onClick={() => void loadStatus()}><RefreshCw className={loading ? 'animate-spin' : ''}/><span>刷新</span></Button></header>
    <div className="meta-phase"><ShieldCheck/><div><strong>当前阶段：连接与绑定</strong><p>已连接不代表已开通自动发布、评论回复、排期或员工权限。</p></div></div>
    {notice && <div className="meta-notice" role="status"><CheckCircle2/>{notice}</div>}
    {error && <div className="meta-alert" role="alert"><AlertCircle/><div><strong>连接状态暂时无法读取</strong><p>{error}</p></div><Button variant="outline" onClick={() => void loadStatus()} disabled={busy || unknown}>重新读取</Button></div>}
    {status && !owner && <div className="meta-empty"><ShieldCheck/><h3>当前账号尚未开放 Meta 连接管理</h3><p>连接与绑定由老板操作，本页未展示任何账号资产。</p></div>}
    {status && owner && <>
      {!canConnect && <div className="meta-alert"><AlertCircle/><div><strong>Meta 接入配置待完成</strong><p>应用配置、Business Login 授权配置及回调准备好后，才能前往 Meta 授权。</p>{status.setup_missing.length > 0 && <p>当前有 {status.setup_missing.length} 项配置待核对。</p>}</div></div>}
      <section className="meta-panel"><header><div><h3>Meta 连接</h3><p>由本人完成平台授权，CRM 只展示连接状态。</p></div><Button onClick={() => open({ kind: 'connect' })} disabled={!canConnect || busy || unknown}><Link2/>连接 Meta</Button></header>
        {!status.connections.length ? <div className="meta-empty"><Link2/><h4>尚未建立 Meta 连接</h4><p>授权成功返回后，再选择主页或 Instagram 账号绑定客户。</p></div> : <div className="meta-connections">{status.connections.map(row => <article key={row.id}><div><strong>{row.label || 'Meta 连接'}</strong><small>{row.needs_reconnect ? '需要重新授权' : row.active ? `已授权 · ${formatTime(row.connected_at)}（北京时间）` : '已断开'}</small>{row.last_error && <p>{row.last_error}</p>}</div><span className={`meta-status ${row.active && !row.needs_reconnect ? 'ready' : ''}`}>{row.needs_reconnect ? '需重新授权' : row.active ? '已连接' : '已断开'}</span><div className="meta-row-actions">{(row.active || row.needs_reconnect) && <Button variant="outline" size="sm" onClick={() => open({ kind: 'connect', connection: row })} disabled={!canConnect || busy || unknown}>重新授权</Button>}{row.active && <Button variant="ghost" size="sm" onClick={() => open({ kind: 'disconnect_connection', connection: row })} disabled={busy || unknown}>断开</Button>}</div></article>)}</div>}
      </section>
      <section className="meta-panel"><header><div><h3>客户账号绑定</h3><p>每个客户在同一平台保留一个有效绑定，逐一核对，避免归属出错。</p></div><Button variant="outline" onClick={() => open({ kind: 'bind' })} disabled={!canConnect || !status.connections.some(row => row.active && !row.needs_reconnect) || busy || unknown}><Link2/>绑定客户账号</Button></header>
        {!status.bindings.length ? <div className="meta-empty"><Link2/><h4>尚未绑定客户账号</h4><p>选择 CRM 客户与已授权资产，再明确确认对应关系。</p></div> : <div className="meta-bindings">{status.bindings.map(row => <article key={row.id}><div><strong>{row.customer_name}</strong><span>{metaPlatformLabel(row.platform)} · {row.asset_name}</span>{row.asset_username && <small>@{row.asset_username.replace(/^@/, '')}</small>}<small>发布、评论：尚未接入</small></div><span className={`meta-status ${row.active ? 'ready' : ''}`}>{row.active ? '已绑定' : '已断开'}</span>{row.active && <Button variant="ghost" size="sm" onClick={() => open({ kind: 'disconnect_binding', binding: row })} disabled={busy || unknown}><Unplug/>断开绑定</Button>}</article>)}</div>}
      </section>
    </>}
    <Dialog open={!!modal} onOpenChange={value => { if (!value) close(); }}><CrmFormDialogContent className="meta-dialog" aria-busy={busy} onEscapeKeyDown={event => { if (busyRef.current || unknown) event.preventDefault(); }} onPointerDownOutside={event => { if (busyRef.current || unknown || dirty) event.preventDefault(); }}><CrmFormDialogHeader><DialogTitle>{title}</DialogTitle><DialogDescription>{modal?.kind === 'connect' ? '在 Meta 页面由本人选择账号并核对权限；本阶段只建立连接与客户归属。' : '只调整本次明确选择的 Meta 连接或绑定，历史记录保留。'}</DialogDescription></CrmFormDialogHeader><CrmFormDialogBody>
      {modal?.kind === 'connect' && status?.authorization && <div className="meta-form"><div className="meta-preview"><strong>{status.authorization.flow}</strong><p>{status.authorization.purpose}</p><p>可选资产：{status.authorization.asset_types.join('、')}</p><p>授权后返回：{status.authorization.redirect_uri}</p><p>{status.authorization.token_storage}</p></div><div className="meta-scopes"><strong>本应用配置的请求权限</strong><p>平台授权页的实际权限仍需由本人核对。</p><ul>{status.authorization.requested_scopes.map(item => <li key={item}>{item}</li>)}</ul></div>{modal.connection && <p>本次重新授权：{modal.connection.label || '现有 Meta 连接'}。客户对应关系仍以返回后的实际列表为准。</p>}</div>}
      {modal?.kind === 'bind' && <div className="meta-form"><label>CRM 客户<NativeSelect aria-label="Meta 绑定客户" value={customer} onChange={chooseCustomer} disabled={busy || unknown || optionsLoading} options={[{ value: '', label: optionsLoading ? '正在读取可绑定客户…' : '选择对应客户' }, ...options.customers.map(row => ({ value: String(row.id), label: row.name }))]}/></label><label>有效 Meta 连接<NativeSelect aria-label="Meta 绑定连接" value={connection} onChange={chooseConnection} disabled={busy || unknown} options={[{ value: '', label: '选择已授权连接' }, ...(status?.connections.filter(row => row.active && !row.needs_reconnect).map(row => ({ value: String(row.id), label: row.label || 'Meta 连接' })) || [])]}/></label><label>已授权主页／账号<NativeSelect aria-label="Meta 绑定平台账号" value={asset} onChange={value => { if (busyRef.current || unknown) return; setAsset(value); setConfirmed(false); }} disabled={busy || unknown || assetsLoading || !connection} options={[{ value: '', label: assetsLoading ? '正在读取 Meta 授权资产…' : '选择具体主页或账号' }, ...assets.items.map(row => ({ value: row.asset_ref, label: `${metaPlatformLabel(row.platform)} · ${row.name}${row.username ? ` · @${row.username.replace(/^@/, '')}` : ''}` }))]}/></label>{assetsError && <div className="meta-alert" role="alert"><div>{assetsError}</div><Button variant="outline" disabled={busy || unknown || assetsLoading} onClick={() => void loadAssets(connectionRef.current)}>重新读取账号</Button></div>}{connection && !assetsLoading && !assetsError && !assets.items.length && <p>此连接尚未返回可选主页或关联 Instagram 账号，请核对平台授权范围。</p>}{assets.truncated && <p>本次列表尚未完整返回；没有找到对应账号时请先不要绑定。</p>}{pickedCustomer && pickedAsset && pickedConnection && <div className="meta-preview"><strong>请核对这组对应关系</strong><p>CRM 客户：{pickedCustomer.name}</p><p>{metaPlatformLabel(pickedAsset.platform)}：{pickedAsset.name}{pickedAsset.username && ` · @${pickedAsset.username.replace(/^@/, '')}`}</p>{pickedAsset.linked_page_name && <p>关联主页：{pickedAsset.linked_page_name}</p>}<p>连接：{pickedConnection.label || 'Meta 连接'}</p><p>本次只保存归属，不自动发布、不开放员工权限。</p></div>}{existingBinding && <div className="meta-alert" role="alert">此客户在该平台已有有效绑定：{existingBinding.asset_name}。请先核对现有记录，不能重复绑定。</div>}</div>}
      {modal?.kind === 'disconnect_binding' && <div className="meta-form"><div className="meta-preview"><strong>{modal.binding.customer_name}</strong><p>{metaPlatformLabel(modal.binding.platform)} · {modal.binding.asset_name}</p></div><p>将停止此账号在本客户下的 CRM 连接用途。保留历史绑定记录，不删除平台账号或公开内容。</p></div>}
      {modal?.kind === 'disconnect_connection' && <div className="meta-form"><div className="meta-preview"><strong>{modal.connection.label || 'Meta 连接'}</strong></div><p>将停止此 Meta 连接及其客户账号绑定的后续使用。保留历史记录，不删除 Facebook 主页、Instagram 账号或平台内容。</p></div>}
      {modal && !unknown && <label className="meta-confirm"><input type="checkbox" checked={confirmed} disabled={busy || modal.kind === 'connect' && !canConnect || modal.kind === 'bind' && !bindReady} onChange={event => setConfirmed(event.target.checked)}/><span>{modal.kind === 'connect' ? '我已核对上述账号资产、权限范围和 CRM 接收地址，确认前往 Meta 为此 CRM 建立授权。授权资料由 CRM 服务器独立加密保存，本阶段仅老板管理连接。' : modal.kind === 'bind' ? '我已核对 CRM 客户、具体平台账号和连接，确认保存这组归属关系。' : '我确认停止上述 Meta 连接用途；已公开的平台内容和历史记录保留。'}</span></label>}
      {modalError && <div className="meta-alert" role="alert"><AlertCircle/><div>{modalError}</div></div>}{unknown && pending.current && pending.current.kind !== 'control' && <p className="meta-request-id">原请求编号：{pending.current.requestId}</p>}
    </CrmFormDialogBody><CrmFormDialogFooter>{unknown ? <><Button variant="outline" disabled={busy} onClick={() => void recover()}>{busy && <Loader2 className="animate-spin"/>}{pending.current?.kind === 'control' ? '读取实际连接状态' : '查询原请求'}</Button>{notFound && pending.current && pending.current.kind !== 'control' && <Button disabled={busy} onClick={() => { if (pending.current) void send(pending.current); }}>沿用原编号确认</Button>}{expired && <Button variant="outline" disabled={busy} onClick={() => void readActualState()}>读取实际状态并结束本次请求</Button>}</> : <><Button variant="outline" onClick={close} disabled={busy}>取消</Button><Button onClick={submit} disabled={saveDisabled}>{busy ? <Loader2 className="animate-spin"/> : <CheckCircle2/>}{busy ? '正在处理…' : modal?.kind === 'connect' ? '前往 Meta 授权' : modal?.kind === 'bind' ? '确认绑定客户账号' : '确认断开'}</Button></>}</CrmFormDialogFooter></CrmFormDialogContent></Dialog>
  </section>;
}
