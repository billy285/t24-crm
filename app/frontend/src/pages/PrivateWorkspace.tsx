import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import {
  Archive, ArrowLeft, ArrowUpRight, CalendarDays, Check, ChevronRight, CircleAlert,
  CircleCheck, Clock3, CreditCard, Ellipsis, FileText, FolderOpen, House, Landmark,
  LoaderCircle, LockKeyhole, Mail, Megaphone, Pencil, Plug, Plus, RefreshCw, RotateCcw,
} from 'lucide-react';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { useDialogDraft } from '@/lib/use-dialog-draft';
import {
  formatPrivateAmount, privateWorkspaceApi, PrivateWorkspaceApiError, privateSourceActionAvailability,
  verifiedPrivateAuthorizationUrl, verifiedPrivateSourceUrl,
  type PrivateActionStatus, type PrivateItem, type PrivatePriority, type PrivateSource,
  type PrivateSourceId, type PrivateWorkspaceData, type UpdatePrivateItem,
} from '@/lib/private-workspace-api';
import './private-workspace.css';

type View = 'today' | PrivateSourceId | 'connections';
type StripeKind = 'payment' | 'refund' | 'dispute' | 'payout';
const VIEWS: View[] = ['today', 'gmail', 'google_ads', 'bofa', 'stripe', 'manual', 'connections'];
const PROVIDERS: PrivateSourceId[] = ['gmail', 'google_ads', 'bofa', 'stripe'];
const SOURCE_NAMES: Record<PrivateSourceId, string> = { gmail: 'Gmail', google_ads: 'Google Ads', bofa: 'Bank of America', stripe: 'Stripe', manual: '个人事项' };
const VIEW_NAMES: Record<View, string> = { today: '今日重点', gmail: '重要邮件', google_ads: '广告观察', bofa: '银行动态', stripe: 'Stripe 财务', manual: '个人事项', connections: '工作接入' };
const SOURCE_ICONS = { gmail: Mail, google_ads: Megaphone, bofa: Landmark, stripe: CreditCard, manual: CircleCheck };
const SOURCE_STATUS: Record<string, string> = { not_configured: '尚待配置', disconnected: '尚未连接', connecting: '等待授权', connected: '已连接', error: '需要检查' };
const ACTION_STATUS: Record<PrivateActionStatus, string> = { open: '待处理', done: '已处理', snoozed: '稍后处理', archived: '已归档' };
const STRIPE_KINDS: Record<StripeKind, string> = { payment: '收款', refund: '退款', dispute: '争议', payout: '提现' };
const PRIORITY_NAMES: Record<PrivatePriority, string> = { low: '不急', normal: '普通', high: '重要', urgent: '紧急' };
const EMPTY_FORM = { title: '', summary: '', priority: 'normal' as PrivatePriority, due_at: '' };

function timeLabel(value: string | null | undefined, includeTime = true): string {
  if (!value) return '尚未同步';
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return '时间待确认';
  return date.toLocaleString('zh-CN', { month: 'long', day: 'numeric', ...(includeTime ? { hour: '2-digit', minute: '2-digit' } : {}) });
}
function localDateInput(value: string | null | undefined): string {
  if (!value) return '';
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return '';
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}
function tomorrowMorning(): string { const date = new Date(); date.setDate(date.getDate() + 1); date.setHours(9, 0, 0, 0); return localDateInput(date.toISOString()); }
function bankAlert(item: PrivateItem): boolean { return item.source_id === 'bofa'; }
function providerState(item: PrivateItem): string {
  if (bankAlert(item)) return '邮件提醒 · 待核实';
  if (item.source_id === 'stripe' && item.kind === 'payout') {
    if (item.status === 'paid') return 'Stripe 标记支付，银行待核对';
    if (item.status === 'pending') return 'Stripe 待处理';
    if (item.status === 'in_transit') return '转账途中';
  }
  const labels: Record<string, string> = { succeeded: '成功', paid: '已支付', failed: '失败', canceled: '已取消', cancelled: '已取消', needs_response: '待回应', under_review: '审核中', won: '争议已胜诉', lost: '争议未胜诉', unread: '未读', read: '已读', ENABLED: '投放中', PAUSED: '已暂停', REMOVED: '已移除', manual: '个人事项' };
  return labels[item.status] || item.status || '来源状态待确认';
}
function actionLabel(item: PrivateItem): string { return bankAlert(item) && item.action_status === 'done' ? '已阅 · 待核实' : ACTION_STATUS[item.action_status] || '待处理'; }
function coverageLabel(source: PrivateSource): string {
  if (source.metadata?.sync_window === 'last_60_days') return '近60天邮件 · 局部覆盖';
  if (source.metadata?.sync_window === 'last_30_days') return '近30天记录 · 局部覆盖';
  if (source.metadata?.record_limit_per_resource) return `最近每类最多 ${source.metadata.record_limit_per_resource} 条记录`;
  return source.metadata?.coverage ? '最近同步记录 · 局部覆盖' : '';
}
function isCurrent(item: PrivateItem): boolean {
  if (item.action_status === 'done' || item.action_status === 'archived') return false;
  return !item.snoozed_until || new Date(item.snoozed_until).getTime() <= Date.now();
}
function evidenceText(value: unknown): string {
  const labels: Record<string, string> = { unverified: '待核实', email_alert: '邮件提醒' };
  if (typeof value === 'string') return labels[value] || value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  if (value === null) return '未提供';
  try { return JSON.stringify(value).slice(0, 500); } catch { return '暂不可读'; }
}

function Empty({ title, detail, action }: { title: string; detail?: string; action?: React.ReactNode }) {
  return <div className="pw-empty"><CircleCheck aria-hidden="true" /><h3>{title}</h3>{detail && <p>{detail}</p>}{action}</div>;
}

function ItemRow({ item, featured = false, onSelect }: { item: PrivateItem; featured?: boolean; onSelect: (item: PrivateItem) => void }) {
  const Icon = SOURCE_ICONS[item.source_id] || FileText;
  return <button type="button" className={`pw-item ${featured ? 'pw-featured' : ''}`} onClick={() => onSelect(item)}>
    {featured ? <div className="pw-feature-meta"><span><Icon aria-hidden="true" />{SOURCE_NAMES[item.source_id]}</span>{item.due_at && <span className="pw-deadline">{timeLabel(item.due_at, false)}前</span>}</div> : <span className="pw-source-icon"><Icon aria-hidden="true" /></span>}
    <span className="pw-item-copy"><strong>{item.title}</strong>{item.summary && <span>{item.summary}</span>}{!featured && <small>{bankAlert(item) ? '邮件提醒 · 待核实' : `${SOURCE_NAMES[item.source_id]} · ${actionLabel(item)}`}</small>}</span>
    {item.amount_minor !== null && item.currency && <span className="pw-amount">{formatPrivateAmount(item.amount_minor, item.currency, item.source_id)}</span>}
    {featured ? <span className="pw-feature-action">查看并处理<ArrowUpRight aria-hidden="true" /></span> : <ChevronRight className="pw-chevron" aria-hidden="true" />}
  </button>;
}

export default function PrivateWorkspace() {
  const [params, setParams] = useSearchParams();
  const rawView = params.get('view') as View;
  const callbackSource = params.get('source') as PrivateSourceId;
  const view: View = VIEWS.includes(rawView) ? rawView : PROVIDERS.includes(callbackSource) ? callbackSource : 'today';
  const [access, setAccess] = useState<'checking' | 'allowed' | 'denied' | 'error'>('checking');
  const [data, setData] = useState<PrivateWorkspaceData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [list, setList] = useState<PrivateItem[]>([]);
  const [total, setTotal] = useState(0);
  const [listLoading, setListLoading] = useState(false);
  const [listError, setListError] = useState('');
  const [refresh, setRefresh] = useState(0);
  const [stripeKind, setStripeKind] = useState<StripeKind>('payment');
  const [manualStatus, setManualStatus] = useState<PrivateActionStatus>('open');
  const [selected, setSelected] = useState<PrivateItem | null>(null);
  const [editor, setEditor] = useState<'new' | 'edit' | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState(EMPTY_FORM);
  const [formError, setFormError] = useState('');
  const [snoozeItem, setSnoozeItem] = useState<PrivateItem | null>(null);
  const [snoozeAt, setSnoozeAt] = useState('');
  const [snoozeError, setSnoozeError] = useState('');
  const [busy, setBusy] = useState('');
  const [notice, setNotice] = useState('');
  const alive = useRef(true);
  const workspaceRequest = useRef(0);
  const listRequest = useRef(0);
  const draft = useDialogDraft(Boolean(editor), form);
  const snoozeDraft = useDialogDraft(Boolean(snoozeItem), snoozeAt);
  const currentSource = data?.sources.find(source => source.id === view);
  const sourceById = useMemo(() => new Map((data?.sources || []).map(source => [source.id, source])), [data?.sources]);

  const deny = useCallback(() => {
    setAccess('denied'); setData(null); setList([]); setSelected(null); setEditor(null); setForm(EMPTY_FORM); setSnoozeItem(null); setSnoozeAt('');
  }, []);
  const handleFailure = useCallback((failure: unknown) => {
    if (failure instanceof PrivateWorkspaceApiError && [401, 403].includes(failure.status)) deny();
    return failure instanceof Error ? failure.message : '操作暂时无法完成，请重试。';
  }, [deny]);

  const loadWorkspace = useCallback(async () => {
    const request = ++workspaceRequest.current;
    setLoading(true); setError('');
    try {
      const permission = await privateWorkspaceApi.access();
      if (!alive.current || request !== workspaceRequest.current) return;
      if (!permission.allowed) { deny(); return; }
      const response = await privateWorkspaceApi.overview();
      if (!alive.current || request !== workspaceRequest.current) return;
      setData(response); setAccess('allowed');
    } catch (failure) {
      if (!alive.current || request !== workspaceRequest.current) return;
      const message = handleFailure(failure);
      if (!(failure instanceof PrivateWorkspaceApiError && [401, 403].includes(failure.status))) setAccess('error');
      setError(message);
    } finally { if (alive.current && request === workspaceRequest.current) setLoading(false); }
  }, [deny, handleFailure]);

  useEffect(() => {
    const lifecycle = alive;
    const workspaceSequence = workspaceRequest;
    const listSequence = listRequest;
    lifecycle.current = true;
    void loadWorkspace();
    return () => { lifecycle.current = false; workspaceSequence.current++; listSequence.current++; };
  }, [loadWorkspace]);

  useEffect(() => {
    const sequence = listRequest;
    const request = ++sequence.current;
    setList([]); setTotal(0); setListError('');
    if (access !== 'allowed' || view === 'today' || view === 'connections') { setListLoading(false); return; }
    setListLoading(true);
    void privateWorkspaceApi.items({ source_id: view, ...(view === 'stripe' ? { kind: stripeKind } : {}), ...(view === 'manual' ? { action_status: manualStatus } : {}), limit: 100 })
      .then(response => { if (alive.current && request === listRequest.current) { setList(response.items); setTotal(response.total); } })
      .catch(failure => { if (alive.current && request === listRequest.current) setListError(handleFailure(failure)); })
      .finally(() => { if (alive.current && request === listRequest.current) setListLoading(false); });
    return () => { if (sequence.current === request) sequence.current++; };
  }, [access, view, stripeKind, manualStatus, refresh, handleFailure]);

  function navigate(next: View) {
    if (!draft.confirmDiscard() || !snoozeDraft.confirmDiscard()) return;
    setEditor(null); setSnoozeItem(null); setSelected(null); setNotice('');
    setParams({ view: next });
  }
  function returnToCrm(event: React.MouseEvent<HTMLAnchorElement>) { if (!draft.confirmDiscard() || !snoozeDraft.confirmDiscard()) event.preventDefault(); }
  function openEditor(item?: PrivateItem) {
    if (!draft.confirmDiscard()) return;
    setEditingId(item?.id || null);
    setForm(item ? { title: item.title, summary: item.summary || '', priority: item.priority, due_at: localDateInput(item.due_at) } : { ...EMPTY_FORM });
    setFormError(''); setEditor(item ? 'edit' : 'new');
  }
  async function refreshAfterWrite() { await loadWorkspace(); if (alive.current) setRefresh(value => value + 1); }
  async function saveItem(event: FormEvent) {
    event.preventDefault();
    if (busy || !form.title.trim()) { setFormError('请填写事项名称。'); return; }
    const due = form.due_at ? new Date(form.due_at) : null;
    if (due && !Number.isFinite(due.getTime())) { setFormError('请填写有效的截止时间。'); return; }
    setBusy('save-item'); setFormError('');
    try {
      const response = editor === 'edit' && editingId
        ? await privateWorkspaceApi.update(editingId, { title: form.title.trim(), summary: form.summary.trim() })
        : await privateWorkspaceApi.create({ title: form.title.trim(), summary: form.summary.trim(), priority: form.priority, due_at: due?.toISOString() || null });
      if (!alive.current) return;
      draft.markSaved(); setEditor(null); setForm(EMPTY_FORM); setSelected(response.item); setNotice('个人事项已保存。');
      await refreshAfterWrite();
    } catch (failure) { if (alive.current) setFormError(handleFailure(failure)); }
    finally { if (alive.current) setBusy(''); }
  }
  async function updateAction(item: PrivateItem, patch: UpdatePrivateItem, archive = false) {
    if (busy) return;
    setBusy(`item-${item.id}`); setNotice('');
    try {
      const response = archive ? await privateWorkspaceApi.archive(item.id) : await privateWorkspaceApi.update(item.id, patch);
      if (!alive.current) return;
      setSelected(previous => previous?.id === response.item.id ? response.item : previous);
      setNotice(archive ? '事项已归档，可在归档列表恢复。' : bankAlert(item) ? '工作台阅读状态已保存；银行提醒仍待核实。' : '工作台处理状态已保存。');
      snoozeDraft.markSaved(); setSnoozeItem(null); setSnoozeError('');
      await refreshAfterWrite();
    } catch (failure) { if (alive.current) { const message = handleFailure(failure); setNotice(message); if (snoozeItem) setSnoozeError(message); } }
    finally { if (alive.current) setBusy(''); }
  }
  async function sourceAction(source: PrivateSource, action: 'connect' | 'disconnect' | 'sync') {
    if (busy) return;
    setBusy(`${action}-${source.id}`); setNotice('');
    try {
      if (action === 'connect') {
        const response = await privateWorkspaceApi.connect(source.id);
        if (!alive.current) return;
        if (response.requires_redirect) {
          const url = verifiedPrivateAuthorizationUrl(source.id, response.authorization_url);
          if (!url) throw new Error('授权地址暂不可打开，请联系管理员检查配置。');
          window.location.assign(url);
          return;
        }
        setNotice(response.source.status === 'connected' ? '来源已连接。' : SOURCE_STATUS[response.source.status] || '来源状态已更新。');
      } else if (action === 'sync') {
        const response = await privateWorkspaceApi.sync(source.id);
        if (!alive.current) return;
        setNotice(`同步完成：新增 ${response.counts.created} 条，更新 ${response.counts.updated} 条。`);
      } else {
        await privateWorkspaceApi.disconnect(source.id);
        if (!alive.current) return;
        setNotice('来源已断开。');
      }
      await refreshAfterWrite();
    } catch (failure) { if (alive.current) { setNotice(handleFailure(failure)); await loadWorkspace(); } }
    finally { if (alive.current) setBusy(''); }
  }

  const prioritized = useMemo(() => (data?.items || []).filter(isCurrent).filter(item =>
    item.source_id !== 'bofa' && (item.source_id === 'manual' || item.source_id === 'gmail' || item.priority === 'high' || item.priority === 'urgent')
  ).sort((a, b) => {
    const ranks = { urgent: 4, high: 3, normal: 2, low: 1 };
    return (ranks[b.priority] || 0) - (ranks[a.priority] || 0) || (a.due_at ? new Date(a.due_at).getTime() : Infinity) - (b.due_at ? new Date(b.due_at).getTime() : Infinity);
  }), [data]);
  const priorityItems = prioritized.slice(0, 3);
  const remaining = prioritized.slice(3);
  const bankItems = (data?.items || []).filter(item => item.source_id === 'bofa' && item.action_status !== 'archived');
  const balances = (data?.balances || []).filter(balance => balance.source_id === 'stripe');
  const safeSelectedUrl = selected ? verifiedPrivateSourceUrl(selected.source_id, selected.source_url) : null;
  const callbackMessage = params.get('connection') === 'connected' && sourceById.get(callbackSource)?.status === 'connected'
    ? '授权已完成，请查看来源与同步状态。' : params.get('connection') === 'incomplete' ? '授权未完成，请在工作接入中重试。' : '';
  const dateLabel = new Date().toLocaleDateString('zh-CN', { month: 'long', day: 'numeric', weekday: 'long' });

  function renderSource(source: PrivateSource) {
    const Icon = SOURCE_ICONS[source.id];
    const actions = privateSourceActionAvailability(source);
    return <section key={source.id} className="pw-connection">
      <div className="pw-connection-heading"><span className="pw-source-icon"><Icon aria-hidden="true" /></span><div><h3>{SOURCE_NAMES[source.id]}</h3><span className={`pw-status ${source.status === 'error' ? 'pw-status-warning' : ''}`}>{SOURCE_STATUS[source.status] || '状态待确认'}</span></div></div>
      <p className="pw-sync-time">最后成功同步：{timeLabel(source.last_sync)}</p>
      {source.error && <p className="pw-source-error">{source.error}</p>}
      {source.id === 'bofa' && <p className="pw-connection-note">先接银行邮件提醒；提醒保持待核实，详细流水需另行授权。</p>}
      {actions.pendingConfiguration && <p className="pw-connection-note">来源配置尚未完成，暂时无法连接或同步。</p>}
      {(actions.canConnect || actions.canSync || actions.canDisconnect) && <div className="pw-source-actions">
        {actions.canConnect && <button type="button" className="pw-button pw-button-primary" disabled={Boolean(busy)} onClick={() => void sourceAction(source, 'connect')}>{source.status === 'error' ? '重新连接 / 授权' : source.status === 'connecting' ? '继续授权' : '连接来源'}</button>}
        {actions.canSync && <button type="button" className="pw-button" disabled={Boolean(busy)} onClick={() => void sourceAction(source, 'sync')}><RefreshCw aria-hidden="true" />同步</button>}
        {actions.canDisconnect && <button type="button" className="pw-button pw-button-quiet" disabled={Boolean(busy)} onClick={() => void sourceAction(source, 'disconnect')}>断开</button>}
      </div>}
    </section>;
  }
  function sourceBanner(source?: PrivateSource) {
    if (!source) return null;
    return <div className="pw-source-banner"><div><span className="pw-status">{SOURCE_STATUS[source.status] || '状态待确认'}</span>{source.metadata?.mode && <span>{source.metadata.mode === 'test' ? '测试模式' : '正式模式'}</span>}<span>最后成功同步：{timeLabel(source.last_sync)}</span>{coverageLabel(source) && <span>{coverageLabel(source)}</span>}{source.metadata?.partial && <p className="pw-source-error">还有记录未包含，当前列表不代表完整账户汇总。</p>}{source.error && <p className="pw-source-error">{source.error}</p>}</div><button type="button" className="pw-button pw-button-quiet" onClick={() => navigate('connections')}>管理接入<ChevronRight aria-hidden="true" /></button></div>;
  }
  function renderList() {
    if (listLoading) return <div className="pw-load" role="status"><LoaderCircle aria-hidden="true" />正在读取当前来源…</div>;
    if (listError) return <div className="pw-load pw-error" role="alert"><p>{listError}</p><button type="button" className="pw-button" onClick={() => setRefresh(value => value + 1)}>重新读取</button></div>;
    if (!list.length) return <Empty title={view === 'manual' ? '这里还没有个人事项' : '当前没有可查看的数据'} detail={view === 'manual' ? '创建一项工作，下一步会更清楚。' : currentSource?.status === 'connected' ? '该来源尚未返回这一类记录，可在工作接入中同步。' : '来源尚未授权或配置，连接后才会显示真实数据。'} action={view === 'manual' && manualStatus === 'open' ? <button className="pw-button pw-button-primary" onClick={() => openEditor()}><Plus aria-hidden="true" />新增事项</button> : undefined} />;
    return <>{view !== 'manual' && <p className="pw-list-footnote pw-coverage-note">{view === 'stripe' ? '列表为近期同步记录，金额不代表完整总额。' : '当前列表为最近同步的局部记录。'}</p>}<div className="pw-list">{list.map(item => <ItemRow key={item.id} item={item} onSelect={setSelected} />)}</div>{total > list.length && <p className="pw-list-footnote">当前显示最近 {list.length} 条，共 {total} 条。</p>}</>;
  }
  function renderToday() {
    return <div className="pw-today-grid"><div className="pw-focus-column">
      <section className="pw-section"><div className="pw-section-heading"><h2>先处理这件事</h2><button type="button" className="pw-text-button" onClick={() => openEditor()}><Plus aria-hidden="true" />个人事项</button></div>{priorityItems.length ? <><ItemRow item={priorityItems[0]} featured onSelect={setSelected} />{priorityItems.length > 1 && <div className="pw-list pw-priority-rows">{priorityItems.slice(1).map(item => <ItemRow key={item.id} item={item} onSelect={setSelected} />)}</div>}</> : <Empty title="目前没有需要处理的重点" detail="接入来源，或添加一项自己的工作。" action={<button type="button" className="pw-button" onClick={() => navigate('connections')}>查看工作接入</button>} />}</section>
      <section className="pw-section"><div className="pw-section-heading"><h2>等我决定</h2><button type="button" className="pw-text-button" onClick={() => navigate('manual')}>查看事项<ChevronRight aria-hidden="true" /></button></div>{remaining.length ? <div className="pw-list">{remaining.slice(0, 3).map(item => <ItemRow key={item.id} item={item} onSelect={setSelected} />)}</div> : <p className="pw-quiet-empty">暂时没有其他待处理事项。</p>}</section>
      <section className="pw-section"><div className="pw-section-heading"><h2>资金动态</h2><button type="button" className="pw-text-button" onClick={() => navigate('bofa')}>查看银行动态<ChevronRight aria-hidden="true" /></button></div>{bankItems.length ? <div className="pw-list">{bankItems.slice(0, 2).map(item => <ItemRow key={item.id} item={item} onSelect={setSelected} />)}</div> : <p className="pw-quiet-empty">尚无银行提醒。邮件提醒收到后仍需核对实际流水。</p>}<button type="button" className="pw-function-row" onClick={() => navigate('stripe')}><span className="pw-source-icon"><CreditCard aria-hidden="true" /></span><span><strong>Stripe 财务</strong><small>按币种查看余额与记录</small></span><ChevronRight aria-hidden="true" /></button></section>
    </div><aside className="pw-source-aside"><div className="pw-section-heading"><h2>我的工作接入</h2><button type="button" className="pw-text-button" onClick={() => navigate('connections')}>管理</button></div>{PROVIDERS.map(id => { const source = sourceById.get(id); const Icon = SOURCE_ICONS[id]; return <button key={id} type="button" className="pw-source-overview" onClick={() => navigate(id)}><Icon aria-hidden="true" /><span><strong>{SOURCE_NAMES[id]}</strong><small>{source ? SOURCE_STATUS[source.status] : '状态待确认'} · {source?.last_sync ? timeLabel(source.last_sync) : '尚未同步'}</small></span>{source?.error && <CircleAlert className="pw-warning-icon" aria-label="同步需要检查" />}</button>; })}<p className="pw-aside-note">提醒显示在此工作空间内。</p></aside></div>;
  }
  function renderContent() {
    if (view === 'today') return renderToday();
    if (view === 'connections') return <><div className="pw-mobile-more"><div className="pw-list">{PROVIDERS.map(id => { const Icon = SOURCE_ICONS[id]; const source = sourceById.get(id); return <button key={id} type="button" className="pw-function-row" onClick={() => navigate(id)}><span className="pw-source-icon"><Icon aria-hidden="true" /></span><span><strong>{VIEW_NAMES[id]}</strong><small>{SOURCE_NAMES[id]}</small></span><small>{source ? SOURCE_STATUS[source.status] : '状态待确认'}</small><ChevronRight aria-hidden="true" /></button>; })}</div></div><div className="pw-connections-grid">{PROVIDERS.map(id => sourceById.get(id)).filter((source): source is PrivateSource => Boolean(source)).map(renderSource)}</div><section className="pw-future"><h2>更多个人工作</h2><div><span><CalendarDays aria-hidden="true" />日程</span><span><FileText aria-hidden="true" />合同</span><span><FolderOpen aria-hidden="true" />项目</span></div><p>后续可继续接入，当前尚未启用。</p></section></>;
    return <>{view !== 'manual' && sourceBanner(currentSource)}{view === 'stripe' && <><div className="pw-balance-groups">{balances.length ? balances.map(balance => <section key={`${balance.source_id}-${balance.currency}`} className="pw-balance-group"><h2>{balance.currency}</h2><div><span>可用余额<strong>{formatPrivateAmount(balance.available_minor, balance.currency, balance.source_id)}</strong></span><span>待结算余额<strong>{formatPrivateAmount(balance.pending_minor, balance.currency, balance.source_id)}</strong></span></div></section>) : <div className="pw-balance-empty">余额尚未同步，当前不显示估算金额。</div>}</div><p className="pw-finance-note">不同币种与来源分别查看。提现是账户间转移，不计为新增经营收入。</p><div className="pw-filter-row" aria-label="Stripe 记录类型">{(Object.keys(STRIPE_KINDS) as StripeKind[]).map(kind => <button key={kind} type="button" aria-pressed={stripeKind === kind} className="pw-filter" onClick={() => setStripeKind(kind)}>{STRIPE_KINDS[kind]}</button>)}</div></>}{view === 'bofa' && <p className="pw-finance-note">邮件提醒 · 待核实；实际到账与扣款以 Bank of America 流水为准。</p>}{view === 'manual' && <div className="pw-manual-toolbar"><div className="pw-filter-row" aria-label="个人事项状态">{(['open', 'snoozed', 'done', 'archived'] as PrivateActionStatus[]).map(status => <button type="button" key={status} className="pw-filter" aria-pressed={manualStatus === status} onClick={() => setManualStatus(status)}>{ACTION_STATUS[status]}</button>)}</div><button type="button" className="pw-button pw-button-primary" onClick={() => openEditor()}><Plus aria-hidden="true" />新增事项</button></div>}{renderList()}</>;
  }

  return <div className="pw-app">
    <aside className="pw-sidebar"><div className="pw-sidebar-brand">T24 OS<span>PRIVATE WORKSPACE</span></div><div className="pw-sidebar-owner"><LockKeyhole aria-hidden="true" />私人工作空间 · 仅本人</div><nav aria-label="私人工作空间"><button type="button" className={view === 'today' ? 'is-active' : ''} onClick={() => navigate('today')}><House aria-hidden="true" />今日重点</button><button type="button" className={view === 'manual' ? 'is-active' : ''} onClick={() => navigate('manual')}><CircleCheck aria-hidden="true" />个人事项</button><div className="pw-nav-label">我的工作</div>{(['gmail', 'google_ads'] as PrivateSourceId[]).map(id => { const Icon = SOURCE_ICONS[id]; return <button key={id} type="button" className={view === id ? 'is-active' : ''} onClick={() => navigate(id)}><Icon aria-hidden="true" />{VIEW_NAMES[id]}</button>; })}<div className="pw-nav-label">资金动态</div>{(['bofa', 'stripe'] as PrivateSourceId[]).map(id => { const Icon = SOURCE_ICONS[id]; return <button key={id} type="button" className={view === id ? 'is-active' : ''} onClick={() => navigate(id)}><Icon aria-hidden="true" />{VIEW_NAMES[id]}</button>; })}<button type="button" className={view === 'connections' ? 'is-active' : ''} onClick={() => navigate('connections')}><Plug aria-hidden="true" />工作接入</button></nav><Link className="pw-back-crm" to="/apps" onClick={returnToCrm}><ArrowLeft aria-hidden="true" />返回 CRM</Link></aside>
    <div className="pw-workarea"><header className="pw-mobile-header"><Link to="/apps" onClick={returnToCrm} aria-label="返回 CRM"><ArrowLeft aria-hidden="true" /></Link><strong>T24 OS</strong><span><LockKeyhole aria-hidden="true" />仅本人</span></header><header className="pw-page-header"><div><p className="pw-eyebrow">私人工作空间 · 仅本人</p><h1>{VIEW_NAMES[view]}</h1><p className="pw-date">{dateLabel}</p></div><button type="button" className="pw-button pw-refresh" disabled={loading || Boolean(busy)} onClick={() => void refreshAfterWrite()} aria-label="重新读取工作空间"><RefreshCw aria-hidden="true" /><span>刷新</span></button></header>
      <main className="pw-main" aria-busy={loading}>{access === 'denied' ? <Empty title="此空间仅对本人开放" detail="当前账号没有查看私人工作内容的权限。" action={<Link className="pw-button" to="/apps">返回 CRM</Link>} /> : loading || access === 'checking' ? <div className="pw-load" role="status"><LoaderCircle aria-hidden="true" />正在读取私人工作空间…</div> : access === 'error' || error ? <div className="pw-load pw-error" role="alert"><h2>暂时无法读取工作空间</h2><p>{error}</p><button type="button" className="pw-button" onClick={() => void loadWorkspace()}>重新读取</button></div> : renderContent()}{callbackMessage && access === 'allowed' && <p className="pw-notice" role="status">{callbackMessage}</p>}{notice && <p className="pw-notice" role="status" aria-live="polite">{notice}</p>}</main>
      {access === 'allowed' && <nav className="pw-bottom-nav" aria-label="手机版工作空间">{([{ view: 'today', label: '今日', Icon: House }, { view: 'manual', label: '事项', Icon: CircleCheck }, { view: 'gmail', label: '邮件', Icon: Mail }, { view: 'stripe', label: '资金', Icon: Landmark }, { view: 'connections', label: '更多', Icon: Ellipsis }] as const).map(entry => { const active = view === entry.view || entry.view === 'stripe' && view === 'bofa'; return <button type="button" key={entry.view} aria-current={active ? 'page' : undefined} className={active ? 'is-active' : ''} onClick={() => navigate(entry.view)}><entry.Icon aria-hidden="true" /><span>{entry.label}</span></button>; })}</nav>}
    </div>

    <Sheet open={Boolean(selected) && access === 'allowed'} onOpenChange={open => { if (!open && !busy) setSelected(null); }}><SheetContent className="pw-surface pw-detail-sheet" overlayClassName="pw-sheet-overlay"><SheetHeader><SheetTitle>{selected?.title || '事项详情'}</SheetTitle><SheetDescription>{selected ? SOURCE_NAMES[selected.source_id] : ''} · 仅本人可见</SheetDescription></SheetHeader>{selected && <div className="pw-detail-body"><div className="pw-detail-meta"><span>{actionLabel(selected)}</span>{selected.due_at && <span>{selected.source_id === 'stripe' && selected.kind === 'payout' ? '预计到账' : '截止'}：{timeLabel(selected.due_at)}</span>}{selected.occurred_at && <span>来源时间：{timeLabel(selected.occurred_at)}</span>}</div>{selected.summary && <p className="pw-detail-summary">{selected.summary}</p>}{selected.amount_minor !== null && selected.currency && <div className="pw-detail-amount"><span>来源记录金额</span><strong>{formatPrivateAmount(selected.amount_minor, selected.currency, selected.source_id)}</strong></div>}{selected.source_id !== 'manual' && <div className="pw-provider-state"><span>来源状态 · 仅查看</span><strong>{providerState(selected)}</strong></div>}{selected.source_id === 'bofa' && <p className="pw-finance-note">邮件提醒不会确认银行入账，请核对实际流水。</p>}{selected.source_id === 'stripe' && selected.kind === 'payout' && <p className="pw-finance-note">提现不代表银行已到账，也不计为新增经营收入。</p>}{Object.keys(selected.evidence || {}).length > 0 && <section className="pw-evidence"><h3>原始依据</h3><dl>{Object.entries(selected.evidence).slice(0, 10).map(([key, value]) => <div key={key}><dt>{{ type: '依据类型', verification: '核实状态', subject: '原始主题', date: '来源日期', provider_id: '来源记录', reference: '记录参考', from: '发件人', account: '来源账户', source: '来源' }[key] || key}</dt><dd>{evidenceText(value)}</dd></div>)}</dl></section>}{safeSelectedUrl && <a className="pw-button pw-source-link" href={safeSelectedUrl} target="_blank" rel="noopener noreferrer">{selected.source_id === 'bofa' ? '查看原始邮件' : '查看原始来源'}<ArrowUpRight aria-hidden="true" /></a>}<div className="pw-item-actions"><button type="button" className="pw-button pw-button-primary" disabled={Boolean(busy)} onClick={() => void updateAction(selected, { action_status: selected.action_status === 'done' || selected.action_status === 'archived' ? 'open' : 'done', snoozed_until: null })}><Check aria-hidden="true" />{selected.action_status === 'archived' ? '恢复事项' : selected.action_status === 'done' ? '恢复待处理' : bankAlert(selected) ? '标记已阅' : '标记已处理'}</button>{selected.action_status !== 'archived' && <button type="button" className="pw-button" disabled={Boolean(busy)} onClick={() => { setSnoozeItem(selected); setSnoozeAt(tomorrowMorning()); setSnoozeError(''); }}><Clock3 aria-hidden="true" />稍后处理</button>}{selected.action_status === 'snoozed' && <button type="button" className="pw-button" disabled={Boolean(busy)} onClick={() => void updateAction(selected, { action_status: 'open', snoozed_until: null })}><RotateCcw aria-hidden="true" />现在处理</button>}{selected.source_id === 'manual' && <><button type="button" className="pw-button" disabled={Boolean(busy)} onClick={() => openEditor(selected)}><Pencil aria-hidden="true" />编辑</button>{selected.action_status !== 'archived' && <button type="button" className="pw-button pw-button-quiet" disabled={Boolean(busy)} onClick={() => void updateAction(selected, {}, true)}><Archive aria-hidden="true" />归档</button>}</>}</div>{selected.source_id !== 'manual' && <p className="pw-detail-footnote">这些操作只记录你的工作台处理状态。</p>}</div>}</SheetContent></Sheet>

    <Dialog open={Boolean(editor) && access === 'allowed'} onOpenChange={open => { if (!open && !busy && draft.confirmDiscard()) setEditor(null); }}><DialogContent className="pw-surface pw-dialog"><DialogHeader><DialogTitle>{editor === 'edit' ? '编辑个人事项' : '新增个人事项'}</DialogTitle><DialogDescription>保存到你的私人工作空间，仅本人可见。</DialogDescription></DialogHeader><form className="pw-form" onSubmit={saveItem}><label>事项名称<input autoFocus value={form.title} maxLength={240} required onChange={event => setForm(previous => ({ ...previous, title: event.target.value }))} placeholder="下一件需要处理的工作" disabled={Boolean(busy)} /></label><label>备注<textarea value={form.summary} maxLength={5000} rows={4} onChange={event => setForm(previous => ({ ...previous, summary: event.target.value }))} disabled={Boolean(busy)} /></label>{editor === 'new' && <div className="pw-form-row"><label>优先级<select value={form.priority} onChange={event => setForm(previous => ({ ...previous, priority: event.target.value as PrivatePriority }))} disabled={Boolean(busy)}>{(Object.keys(PRIORITY_NAMES) as PrivatePriority[]).map(priority => <option key={priority} value={priority}>{PRIORITY_NAMES[priority]}</option>)}</select></label><label>截止时间<input type="datetime-local" value={form.due_at} onChange={event => setForm(previous => ({ ...previous, due_at: event.target.value }))} disabled={Boolean(busy)} /></label></div>}{formError && <p className="pw-form-error" role="alert">{formError}</p>}<div className="pw-form-actions"><button type="button" className="pw-button" disabled={Boolean(busy)} onClick={() => { if (draft.confirmDiscard()) setEditor(null); }}>取消</button><button type="submit" className="pw-button pw-button-primary" disabled={Boolean(busy)}>{busy === 'save-item' ? '正在保存…' : '保存事项'}</button></div></form></DialogContent></Dialog>
    <Dialog open={Boolean(snoozeItem) && access === 'allowed'} onOpenChange={open => { if (!open && !busy && snoozeDraft.confirmDiscard()) setSnoozeItem(null); }}><DialogContent className="pw-surface pw-dialog"><DialogHeader><DialogTitle>稍后处理</DialogTitle><DialogDescription>{snoozeItem?.title}</DialogDescription></DialogHeader><form className="pw-form" onSubmit={event => { event.preventDefault(); const date = new Date(snoozeAt); if (!snoozeItem || !Number.isFinite(date.getTime()) || date.getTime() <= Date.now()) { setSnoozeError('请选择未来的处理时间。'); return; } void updateAction(snoozeItem, { action_status: 'snoozed', snoozed_until: date.toISOString() }); }}><label>再次处理时间<input type="datetime-local" value={snoozeAt} required onChange={event => setSnoozeAt(event.target.value)} disabled={Boolean(busy)} /></label><p className="pw-connection-note">到期后回到工作空间的待处理事项。</p>{snoozeError && <p className="pw-form-error" role="alert">{snoozeError}</p>}<div className="pw-form-actions"><button type="button" className="pw-button" disabled={Boolean(busy)} onClick={() => { if (snoozeDraft.confirmDiscard()) setSnoozeItem(null); }}>取消</button><button type="submit" className="pw-button pw-button-primary" disabled={Boolean(busy)}>保存时间</button></div></form></DialogContent></Dialog>
  </div>;
}
