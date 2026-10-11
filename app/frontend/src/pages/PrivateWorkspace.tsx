import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from 'react';
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import {
  Archive, ArrowLeft, ArrowUpRight, CalendarDays, Check, ChevronRight, CircleAlert,
  CircleCheck, Clock3, CreditCard, Ellipsis, FileText, FolderOpen, House, Landmark,
  LoaderCircle, LockKeyhole, Mail, Megaphone, Pencil, Plug, Plus, RefreshCw, RotateCcw,
  SlidersHorizontal,
} from 'lucide-react';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { useDialogDraft } from '@/lib/use-dialog-draft';
import { AUTH_SESSION_INVALIDATED_EVENT, getAuthSessionEpoch } from '@/lib/auth-storage';
import {
  formatPrivateAmount, privateStripeRecord, privateStripeSnapshot, privateWorkspaceApi, PrivateWorkspaceApiError, privateSourceActionAvailability,
  PRIVATE_MAIL_BUCKET_NAMES, PRIVATE_MAIL_BUCKETS, privateMailBucket, privateMailChinese, privateMailTranslationNotice, privateMailBriefNotice,
  verifiedPrivateAuthorizationUrl, verifiedPrivateSourceUrl, verifiedBankAuthorizationUrl,
  type PrivateActionStatus, type PrivateItem, type PrivatePriority, type PrivateSource,
  type PrivateSourceId, type PrivateWorkspaceData, type UpdatePrivateItem,
  type PrivateMailBucket, type PrivateMailCounts, type PrivateMailFeedback, type PrivateMailTopic,
  type PrivateWorkspacePreferences, type PrivateMailCapabilities,
} from '@/lib/private-workspace-api';
import { ADS_BUCKET_NAMES, privateAdsObservation, privateAdsDisplayTitle } from '@/lib/private-ads';
import { bossBriefNotice as bossBriefStatusNotice, type PrivateBossBriefData, type PrivateBossPeriod } from '@/lib/private-boss-brief';
import PrivateAdsDashboard, { PrivateAdsDetail } from './PrivateAdsDashboard';
import PrivateMailContent from './PrivateMailContent';
import PrivateMailBrief from './PrivateMailBrief';
import PrivateBossBrief from './PrivateBossBrief';
import PrivateStripeDashboard from './PrivateStripeDashboard';
import PrivateFundsOverview from './PrivateFundsOverview';
import { createPrivateStripeSelection, privateStripeReportDate, type PrivateStripeReport, type PrivateStripeSelection } from '@/lib/private-stripe-report';
import PrivateBankDashboard, { PrivateBankDetail } from './PrivateBankDashboard';
import { PRIVATE_WORKSPACE_VIEWS, privateBackTarget, privateNavigationState, type PrivateWorkspaceView, type PrivateWorkspacePanel } from '@/lib/private-workspace-navigation';
import './private-workspace.css';

type View = PrivateWorkspaceView;
type PrivatePanelEntry = { view: View; kind: 'detail' | PrivateWorkspacePanel; item?: PrivateItem; editor?: 'new' | 'edit'; initialForm?: typeof EMPTY_FORM; snoozeAt?: string };
type PrivatePagePosition = { view: View; scrollY: number; stripeKind: StripeKind; stripeSelection?: PrivateStripeSelection; mailBucket: PrivateMailBucket | 'all'; manualStatus: PrivateActionStatus; briefPeriod: PrivateBossPeriod };
type StripeKind = 'payment' | 'refund' | 'dispute' | 'payout';
const VIEWS: View[] = [...PRIVATE_WORKSPACE_VIEWS];
const PROVIDERS: PrivateSourceId[] = ['gmail', 'google_ads', 'bofa_bank', 'stripe', 'bofa'];
const SOURCE_NAMES: Record<PrivateSourceId, string> = { gmail: 'Gmail', google_ads: 'Google Ads', bofa: '银行邮件提醒', bofa_bank: 'Bank of America', stripe: 'Stripe', manual: '个人事项' };
const VIEW_NAMES: Record<View, string> = { today: '经营简报', gmail: '重要邮件', google_ads: '广告观察', funds: '私人资金', bofa: '银行邮件提醒', bofa_bank: '银行账户', stripe: 'Stripe 财务', manual: '个人事项', connections: '工作接入' };
const SOURCE_ICONS = { gmail: Mail, google_ads: Megaphone, bofa: Mail, bofa_bank: Landmark, stripe: CreditCard, manual: CircleCheck };
const SOURCE_STATUS: Record<string, string> = { not_configured: '尚待配置', disconnected: '尚未连接', connecting: '等待授权', connected: '已连接', error: '需要检查' };
const ACTION_STATUS: Record<PrivateActionStatus, string> = { open: '待处理', done: '已处理', snoozed: '稍后处理', archived: '已归档' };
const STRIPE_KINDS: Record<StripeKind, string> = { payment: '支付', refund: '退款', dispute: '争议', payout: '提现' };
const PRIORITY_NAMES: Record<PrivatePriority, string> = { low: '不急', normal: '普通', high: '重要', urgent: '紧急' };
const EMPTY_FORM = { title: '', summary: '', priority: 'normal' as PrivatePriority, due_at: '' };
const MAIL_TOPICS: Record<PrivateMailTopic, string> = { finance: '资金与支付', ads: '广告投放', security: '账号安全', business: '业务与客户' };
const EMPTY_MAIL_COUNTS: PrivateMailCounts = { urgent: 0, today: 0, digest: 0, low: 0 };
const EMPTY_PREFERENCE_FORM = { topics: [] as PrivateMailTopic[], watch_senders: '', watch_keywords: '', muted_senders: '' };
function preferenceForm(preferences: PrivateWorkspacePreferences) {
  return { topics: [...preferences.gmail.topics], watch_senders: preferences.gmail.watch_senders.join('\n'), watch_keywords: preferences.gmail.watch_keywords.join('\n'), muted_senders: preferences.gmail.muted_senders.join('\n') };
}
function inputLines(value: string): string[] { return [...new Set(value.split(/[\n,，]/).map(line => line.trim()).filter(Boolean))]; }
function senderLabel(item: PrivateItem): string {
  return typeof item.evidence?.from === 'string' ? item.evidence.from : item.mail_relevance?.sender_address || '发件人待确认';
}
function itemDisplayTitle(item: PrivateItem): string {
  return item.source_id === 'google_ads' ? privateAdsDisplayTitle(item) : privateMailChinese(item, 'title');
}

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
function sourceAccountLabel(source: PrivateSource): string {
  const label = typeof source.metadata?.account_label === 'string' ? source.metadata.account_label.trim() : '';
  if (source.id === 'stripe') {
    const account = source.metadata?.stripe_account_id;
    return typeof account === 'string' && /^acct_[A-Za-z0-9]+$/.test(account) ? label && label !== account ? `${label} · ${account}` : account : label;
  }
  if (source.id !== 'google_ads') return label;
  const id = source.metadata?.ads_customer_id;
  if (typeof id !== 'string' || !/^\d{10}$/.test(id)) return label;
  const formatted = `${id.slice(0, 3)}-${id.slice(3, 6)}-${id.slice(6)}`;
  return !label || label === id || label === formatted ? formatted : `${label} · ${formatted}`;
}
function coverageLabel(source: PrivateSource): string {
  if (source.metadata?.sync_window === 'last_60_days') return '近60天邮件 · 局部覆盖';
  if (source.metadata?.sync_window === 'last_30_days') return source.id === 'google_ads' ? '近30天广告系列（不含今天） · 局部覆盖' : '近30天记录 · 局部覆盖';
  if (source.metadata?.record_limit_per_resource) return `最近每类最多 ${source.metadata.record_limit_per_resource} 条记录`;
  return source.metadata?.coverage ? '最近同步记录 · 局部覆盖' : '';
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

function ItemEvidence({ item }: { item: PrivateItem }) {
  if (!Object.keys(item.evidence || {}).length) return null;
  const records = <dl>{Object.entries(item.evidence).slice(0, 10).map(([key, value]) => <div key={key}><dt>{{ type: '依据类型', verification: '核实状态', subject: '原始主题', date: '来源日期', provider_id: '来源记录', reference: '记录参考', from: '发件人', sender_verification: '发件人验证', account: '来源账户', source: '来源' }[key] || key}</dt><dd>{evidenceText(value)}</dd></div>)}</dl>;
  return <details className="pw-evidence pw-mail-evidence"><summary>查看原始依据<ChevronRight aria-hidden="true" /></summary>{records}</details>;
}

function StripeRecordDetails({ item, source, now }: { item: PrivateItem; source?: PrivateSource; now: number }) {
  const record = privateStripeRecord(item, source, now);
  const fields = item.kind === 'payment'
    ? record.paymentState === 'uncaptured_refunded'
      ? [['来源请求金额', record.amountMinor], ['来源捕获字段', record.capturedMinor], ['来源退款字段', record.refundedMinor]] as const
      : [['请求金额', record.authorizedMinor], ['已收款金额', record.capturedMinor], ['已退款金额', record.refundedMinor]] as const
    : [[record.amountLabel, record.amountMinor]] as const;
  return <div className="pw-stripe-detail">
    <section className="pw-stripe-detail-state"><span>Stripe 来源状态</span><strong>{record.statusLabel}</strong><small>{record.freshnessLabel} · {record.mode === 'test' ? '测试模式' : record.mode === 'live' ? '正式模式' : '模式待核实'}</small></section>
    <dl className="pw-stripe-amounts">{fields.map(([label, amount]) => <div key={label}><dt>{label}</dt><dd>{formatPrivateAmount(amount, item.currency, 'stripe')}</dd></div>)}</dl>
    <p className="pw-stripe-note">{item.kind === 'payout' ? record.amountMinor !== null && record.amountMinor < 0 ? '来源为负向划转记录；保留 Stripe 原始金额符号，银行实际资金变化需核对流水。' : '提现是账户间转移，银行是否到账需核对实际流水。' : record.paymentState === 'uncaptured_refunded' ? '此笔付款未捕获；来源退款字段保留原值，具体资金变化请在 Stripe 核对。' : item.kind === 'payment' && record.paymentState === 'authorized' ? '授权金额尚未捕获，不代表实际收款。' : '来源记录用于个人查看，不写入 CRM 账目。'}</p>
    <details className="pw-stripe-evidence"><summary>来源时间与原始依据<ChevronRight aria-hidden="true" /></summary><dl><div><dt>同步时间</dt><dd>{timeLabel(record.observedAt)}</dd></div><div><dt>来源账户</dt><dd>{typeof item.evidence.stripe_account_id === 'string' ? item.evidence.stripe_account_id : '待重新同步'}</dd></div><div><dt>来源原始状态</dt><dd>{item.status || '待核实'}</dd></div>{item.summary && <div><dt>来源说明</dt><dd>{item.summary}</dd></div>}{Object.entries(item.evidence).filter(([key]) => !['stripe_account_id', 'stripe_mode', 'stripe_snapshot_id', 'stripe_observed_at', 'payment_state', 'amount_authorized_minor', 'amount_captured_minor', 'amount_refunded_minor', 'provider_status'].includes(key)).slice(0, 8).map(([key, value]) => <div key={key}><dt>{{ provider_id: '来源记录', accounting_effect: '账目影响', funds_movement: '资金流向', captured: '已捕获', paid: '来源支付标记' }[key] || key}</dt><dd>{key === 'accounting_effect' && value === 'none' ? '独立记录' : evidenceText(value)}</dd></div>)}</dl></details>
  </div>;
}

function ItemRow({ item, source, featured = false, onSelect }: { item: PrivateItem; source?: PrivateSource; featured?: boolean; onSelect: (item: PrivateItem) => void }) {
  const Icon = SOURCE_ICONS[item.source_id] || FileText;
  if (item.source_id === 'stripe' && !featured) {
    const record = privateStripeRecord(item, source);
    return <button type="button" className={`pw-stripe-row ${record.paymentState === 'failed' || item.status === 'needs_response' ? 'pw-stripe-row-attention' : ''}`} onClick={() => onSelect(item)}>
      <span className="pw-stripe-row-copy"><strong>{item.title}</strong><span className="pw-stripe-row-state">{record.statusLabel}{record.mode === 'test' && <small className="pw-stripe-test">测试</small>}</span><small>{item.occurred_at ? timeLabel(item.occurred_at) : '来源时间待核实'}{!record.current || record.freshnessLabel !== '同步记录' ? ` · ${record.freshnessLabel}` : ''}</small>{record.hasRefund && <small>已退款 {formatPrivateAmount(record.refundedMinor, item.currency, 'stripe')}</small>}</span>
      <span className="pw-stripe-row-amount"><strong>{formatPrivateAmount(record.amountMinor, item.currency, 'stripe')}</strong><small>{record.amountLabel}</small></span><ChevronRight className="pw-chevron" aria-hidden="true" />
    </button>;
  }
  if (item.source_id === 'gmail' && !featured) {
    const bucket = privateMailBucket(item);
    return <button type="button" className="pw-mail-row" onClick={() => onSelect(item)}>
      <span className="pw-mail-copy"><span className="pw-mail-title"><strong>{privateMailChinese(item, 'title')}</strong>{['urgent', 'today'].includes(bucket) && <span className={`pw-mail-badge pw-mail-badge-${bucket}`}>{PRIVATE_MAIL_BUCKET_NAMES[bucket]}</span>}</span>
        <span className="pw-mail-row-meta"><span>{senderLabel(item)}</span>{item.occurred_at && <time dateTime={item.occurred_at}>{timeLabel(item.occurred_at, false)}</time>}</span>
        {item.summary && <span className="pw-mail-snippet">{privateMailChinese(item, 'summary')}</span>}
        {item.mail_brief?.state === 'ready' && item.mail_brief.next_action && <span className="pw-mail-reason">下一步 · {item.mail_brief.next_action}</span>}
      </span><ChevronRight className="pw-chevron" aria-hidden="true" />
    </button>;
  }
  const ads = item.source_id === 'google_ads' ? privateAdsObservation(item, source) : null;
  const sender = (item.source_id === 'gmail' || item.source_id === 'bofa') && typeof item.evidence?.from === 'string' ? item.evidence.from : '';
  return <button type="button" className={`pw-item ${featured ? 'pw-featured' : ''}`} onClick={() => onSelect(item)}>
    {featured ? <div className="pw-feature-meta"><span><Icon aria-hidden="true" />{SOURCE_NAMES[item.source_id]}{ads && ` · ${ADS_BUCKET_NAMES[ads.bucket]}`}</span>{item.due_at && <span className="pw-deadline">{timeLabel(item.due_at, false)}前</span>}</div> : <span className="pw-source-icon"><Icon aria-hidden="true" /></span>}
    <span className="pw-item-copy"><strong>{itemDisplayTitle(item)}</strong>{sender && <small className="pw-mail-sender">{sender}</small>}{(ads?.reason || privateMailChinese(item, 'summary')) && <span>{ads?.reason || privateMailChinese(item, 'summary')}</span>}{!featured && <small>{ads ? `Google Ads · ${ADS_BUCKET_NAMES[ads.bucket]}` : bankAlert(item) ? '邮件提醒 · 待核实' : `${SOURCE_NAMES[item.source_id]} · ${actionLabel(item)}`}</small>}</span>
    {item.source_id !== 'bofa_bank' && item.amount_minor !== null && item.currency && <span className="pw-amount">{formatPrivateAmount(item.amount_minor, item.currency, item.source_id)}</span>}
    {featured ? <span className="pw-feature-action">{ads ? '查看投放检查' : '查看并处理'}<ArrowUpRight aria-hidden="true" /></span> : <ChevronRight className="pw-chevron" aria-hidden="true" />}
  </button>;
}

export default function PrivateWorkspace() {
  const [params, setParams] = useSearchParams();
  const location = useLocation();
  const routeNavigate = useNavigate();
  const rawView = params.get('view') as View;
  const callbackSource = params.get('source') as PrivateSourceId;
  const view: View = VIEWS.includes(rawView) ? rawView : PROVIDERS.includes(callbackSource) ? callbackSource : 'today';
  const [adsNow, setAdsNow] = useState(() => Date.now());
  useEffect(() => {
    const check = () => setAdsNow(Date.now());
    const timer = window.setInterval(check, 60_000);
    window.addEventListener('pageshow', check);
    window.addEventListener('focus', check);
    if (typeof document !== 'undefined') document.addEventListener('visibilitychange', check);
    return () => { window.clearInterval(timer); window.removeEventListener('pageshow', check); window.removeEventListener('focus', check); if (typeof document !== 'undefined') document.removeEventListener('visibilitychange', check); };
  }, []);
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
  const [stripeSelection, setStripeSelection] = useState<PrivateStripeSelection>(() => createPrivateStripeSelection());
  const [stripeReport, setStripeReport] = useState<PrivateStripeReport | null>(null);
  const [stripeReportLoading, setStripeReportLoading] = useState(false);
  const [stripeReportError, setStripeReportError] = useState('');
  const stripeReportRequest = useRef(0);
  const [manualStatus, setManualStatus] = useState<PrivateActionStatus>('open');
  const [mailBucket, setMailBucket] = useState<PrivateMailBucket | 'all'>('all');
  const [mailCounts, setMailCounts] = useState<PrivateMailCounts>(EMPTY_MAIL_COUNTS);
  const [preferencesOpen, setPreferencesOpen] = useState(false);
  const [preferencesLoading, setPreferencesLoading] = useState(false);
  const [preferencesReady, setPreferencesReady] = useState(false);
  const [preferencesError, setPreferencesError] = useState('');
  const [preferencesForm, setPreferencesForm] = useState(EMPTY_PREFERENCE_FORM);
  const [applyFeedbackToSender, setApplyFeedbackToSender] = useState(false);
  const [selected, setSelected] = useState<PrivateItem | null>(null);
  const [editor, setEditor] = useState<'new' | 'edit' | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState(EMPTY_FORM);
  const [formError, setFormError] = useState('');
  const [snoozeItem, setSnoozeItem] = useState<PrivateItem | null>(null);
  const [snoozeAt, setSnoozeAt] = useState('');
  const [snoozeError, setSnoozeError] = useState('');
  const [busy, setBusy] = useState('');
  const bankStartPending = useRef(false);
  const bankStartRequest = useRef(0);
  const bankCompletePending = useRef(false);
  const bankCompleteRequest = useRef(0);
  const bankReturnSessionRef = useRef(params.get('bank_session'));
  bankReturnSessionRef.current = params.get('bank_session');
  const [notice, setNotice] = useState('');
  const [translationBusy, setTranslationBusy] = useState(false);
  const [translationUnavailable, setTranslationUnavailable] = useState(false);
  const [translationLimited, setTranslationLimited] = useState(false);
  const [translationNotice, setTranslationNotice] = useState('');
  const [bodyTranslationNotice, setBodyTranslationNotice] = useState<{ id: string; message: string } | null>(null);
  const [mailCapabilities, setMailCapabilities] = useState<PrivateMailCapabilities | null>(null);
  const [mailCapabilitiesLoading, setMailCapabilitiesLoading] = useState(true);
  const [mailCapabilitiesNotice, setMailCapabilitiesNotice] = useState('');
  const [mailBriefNotice, setMailBriefNotice] = useState<{ id: string; message: string } | null>(null);
  const [briefPeriod, setBriefPeriod] = useState<PrivateBossPeriod>('today');
  const [bossBrief, setBossBrief] = useState<PrivateBossBriefData | null>(null);
  const [bossBriefLoading, setBossBriefLoading] = useState(false);
  const [bossBriefError, setBossBriefError] = useState('');
  const [bossBriefNotice, setBossBriefNotice] = useState('');
  const bossBriefRequest = useRef(0);
  const bossLoadedPeriod = useRef<PrivateBossPeriod | null>(null);
  const bossExplainRequest = useRef(0);
  const bossExplainPending = useRef(false);
  const capabilitiesRequest = useRef(0);
  const mailBriefRequest = useRef(0);
  const mailBriefPending = useRef(false);
  const autoTranslationAttempted = useRef(false);
  const translationAttemptedIds = useRef(new Set<string>());
  const translationRequest = useRef(0);
  const translationPending = useRef(false);
  const bodyTranslationRequest = useRef(0);
  const bodyTranslationPending = useRef(false);
  const alive = useRef(true);
  const workspaceRequest = useRef(0);
  const listRequest = useRef(0);
  const preferencesRequest = useRef(0);
  const sessionEpoch = useRef(getAuthSessionEpoch());
  const isActive = useCallback(() => alive.current && sessionEpoch.current === getAuthSessionEpoch(), []);
  const draft = useDialogDraft(Boolean(editor), form);
  const snoozeDraft = useDialogDraft(Boolean(snoozeItem), snoozeAt);
  const preferencesDraft = useDialogDraft(preferencesOpen && !preferencesLoading, preferencesForm);
  const currentSource = data?.sources.find(source => source.id === view);
  const sourceById = useMemo(() => new Map((data?.sources || []).map(source => [source.id, source])), [data?.sources]);

  // Only navigation metadata goes into router history; record references stay in this session's memory.
  const privateKeys = useRef(new Set<string>());
  privateKeys.current.add(location.key);
  const panelSequence = useRef(0);
  const privatePanels = useRef(new Map<string, PrivatePanelEntry>());
  const pagePositions = useRef(new Map<string, PrivatePagePosition>());
  const lastPrivateLocation = useRef<string | null>(null);
  const reopenPreferences = useRef<() => void>(() => undefined);
  const pendingScroll = useRef<{ key: string; top: number; signature: string } | null>(null);
  const listReadySignature = useRef('');
  const adsNavigationMemory = useRef<Parameters<typeof PrivateAdsDashboard>[0]['initialNavigation']>();
  const navigationEntry = useMemo(() => privateNavigationState(location.state, sessionEpoch.current), [location.state]);
  const backTarget = privateBackTarget(navigationEntry, privateKeys.current);
  const backLabel = `返回${VIEW_NAMES[backTarget.view]}`;
  const rememberLoadedItems = useCallback((items: PrivateItem[]) => {
    const latest = new Map(items.map(item => [item.id, item]));
    const refreshed = (previous: PrivateItem) => {
      const item = latest.get(previous.id);
      if (!item || item.source_id !== previous.source_id) return previous;
      const unchangedText = item.title === previous.title && item.summary === previous.summary;
      return { ...item,
        ...(unchangedText && previous.mail_translation?.body_available && item.mail_translation?.updated_at
          && item.mail_translation.updated_at === previous.mail_translation.updated_at ? { mail_translation: {
            ...item.mail_translation, body_zh: previous.mail_translation.body_zh, body_original: previous.mail_translation.body_original,
            body_available: true, truncated: previous.mail_translation.truncated,
          } } : {}),
        ...(unchangedText && previous.mail_brief?.original_body && item.mail_brief?.updated_at
          && item.mail_brief.updated_at === previous.mail_brief.updated_at ? { mail_brief: {
            ...item.mail_brief, original_body: previous.mail_brief.original_body, source_evidence: previous.mail_brief.source_evidence,
            deadline: item.mail_brief.deadline && item.mail_brief.deadline.at === previous.mail_brief.deadline?.at
              && item.mail_brief.deadline.text === previous.mail_brief.deadline.text ? { ...item.mail_brief.deadline, evidence: previous.mail_brief.deadline.evidence } : item.mail_brief.deadline,
          } } : {}),
      };
    };
    for (const [token, panel] of privatePanels.current) if (panel.item && latest.has(panel.item.id)) privatePanels.current.set(token, { ...panel, item: refreshed(panel.item) });
    setSelected(previous => previous && latest.has(previous.id) ? refreshed(previous) : previous);
  }, []);

  useEffect(() => {
    if (lastPrivateLocation.current === location.key) return;
    lastPrivateLocation.current = location.key;
    const position = pagePositions.current.get(location.key);
    if (position?.view === view) {
      setStripeKind(position.stripeKind); if (position.stripeSelection) setStripeSelection(position.stripeSelection); setMailBucket(position.mailBucket);
      setManualStatus(position.manualStatus); setBriefPeriod(position.briefPeriod);
    }
    pendingScroll.current = { key: location.key, top: position?.view === view ? position.scrollY : 0, signature: `${view}:${position?.stripeKind || stripeKind}:${position?.manualStatus || manualStatus}:${position?.mailBucket || mailBucket}` };
    const panel = navigationEntry?.panelToken ? privatePanels.current.get(navigationEntry.panelToken) : undefined;
    if ((params.has('item') || params.has('panel')) && (!panel || panel.view !== view)) {
      // Direct links, refresh and a new login have no live private detail layer to return through.
      const next = new URLSearchParams(params); next.delete('item'); next.delete('panel');
      setParams(next, { replace: true });
      setSelected(null); setEditor(null); setSnoozeItem(null); setPreferencesOpen(false);
      return;
    }
    setSelected(panel?.item || null);
    if (params.get('panel') === 'editor' && panel?.kind === 'editor') {
      setEditor(panel.editor || 'new'); setEditingId(panel.editor === 'edit' ? panel.item?.id || null : null);
      if (panel.editor === 'edit' && panel.item) setForm({ title: panel.item.title, summary: panel.item.summary || '', priority: panel.item.priority, due_at: localDateInput(panel.item.due_at) });
      else setForm({ ...(panel.initialForm || EMPTY_FORM) });
      setFormError('');
    } else setEditor(null);
    if (params.get('panel') === 'snooze' && panel?.kind === 'snooze' && panel.item) {
      setSnoozeItem(panel.item); setSnoozeAt(panel.snoozeAt || tomorrowMorning()); setSnoozeError('');
    } else setSnoozeItem(null);
    if (params.get('panel') !== 'preferences') { preferencesRequest.current++; setPreferencesOpen(false); }
  }, [location.key, navigationEntry, params, setParams, view, stripeKind, manualStatus, mailBucket]);



  const deny = useCallback(() => {
    stripeReportRequest.current++; setStripeReport(null); setStripeReportLoading(false); setStripeReportError(''); setStripeSelection(createPrivateStripeSelection());
    bankStartRequest.current++; bankStartPending.current = false;
    bankCompleteRequest.current++; bankCompletePending.current = false;
    bossBriefRequest.current++; bossExplainRequest.current++; bossExplainPending.current = false;
    bossLoadedPeriod.current = null;
    setBossBrief(null); setBossBriefLoading(false); setBossBriefError(''); setBossBriefNotice('');
    workspaceRequest.current++; listRequest.current++; preferencesRequest.current++; translationRequest.current++; bodyTranslationRequest.current++; capabilitiesRequest.current++; mailBriefRequest.current++; translationPending.current = false; bodyTranslationPending.current = false; mailBriefPending.current = false;
    privateKeys.current.clear(); privatePanels.current.clear(); pagePositions.current.clear(); adsNavigationMemory.current = undefined;
    setAccess('denied'); setData(null); setError(''); setList([]); setListError(''); setTotal(0); setMailCounts(EMPTY_MAIL_COUNTS); setMailBucket('all'); setSelected(null); setEditor(null); setEditingId(null); setForm(EMPTY_FORM); setFormError(''); setSnoozeItem(null); setSnoozeAt(''); setSnoozeError('');
    setPreferencesOpen(false); setPreferencesForm(EMPTY_PREFERENCE_FORM); setPreferencesError(''); setPreferencesLoading(false); setPreferencesReady(false); setApplyFeedbackToSender(false); setNotice(''); setBusy(''); setTranslationBusy(false); setTranslationUnavailable(false); setTranslationLimited(false); setTranslationNotice(''); setBodyTranslationNotice(null); translationAttemptedIds.current.clear();
    setMailCapabilities(null); setMailCapabilitiesLoading(false); setMailCapabilitiesNotice(''); setMailBriefNotice(null);
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
      if (!isActive() || request !== workspaceRequest.current) return;
      if (!permission.allowed) { deny(); return; }
      const response = await privateWorkspaceApi.overview();
      if (!isActive() || request !== workspaceRequest.current) return;
      rememberLoadedItems(response.items); setData(response); setAccess('allowed');
    } catch (failure) {
      if (!isActive() || request !== workspaceRequest.current) return;
      const message = handleFailure(failure);
      if (!(failure instanceof PrivateWorkspaceApiError && [401, 403].includes(failure.status))) setAccess('error');
      setError(message);
    } finally { if (isActive() && request === workspaceRequest.current) setLoading(false); }
  }, [deny, handleFailure, isActive, rememberLoadedItems]);

  useEffect(() => {
    const lifecycle = alive;
    const workspaceSequence = workspaceRequest;
    const listSequence = listRequest;
    const preferenceSequence = preferencesRequest;
    const translationSequence = translationRequest;
    const bodySequence = bodyTranslationRequest;
    const capabilitiesSequence = capabilitiesRequest;
    const briefSequence = mailBriefRequest;
    const bossSequence = bossBriefRequest;
    const bossExplainSequence = bossExplainRequest;
    const stripeSequence = stripeReportRequest;
    lifecycle.current = true;
    void loadWorkspace();
    const invalidate = () => { if (sessionEpoch.current !== getAuthSessionEpoch()) deny(); };
    window.addEventListener(AUTH_SESSION_INVALIDATED_EVENT, invalidate);
    window.addEventListener('storage', invalidate);
    return () => { lifecycle.current = false; workspaceSequence.current++; listSequence.current++; preferenceSequence.current++; translationSequence.current++; bodySequence.current++; capabilitiesSequence.current++; briefSequence.current++; bossSequence.current++; bossExplainSequence.current++; stripeSequence.current++; window.removeEventListener(AUTH_SESSION_INVALIDATED_EVENT, invalidate); window.removeEventListener('storage', invalidate); };
  }, [loadWorkspace, deny]);

  useEffect(() => { setApplyFeedbackToSender(false); }, [selected?.id]);

  useEffect(() => {
    if (access !== 'allowed') return;
    const sequence = capabilitiesRequest;
    const request = ++sequence.current;
    setMailCapabilitiesLoading(true); setMailCapabilitiesNotice('');
    void privateWorkspaceApi.mailCapabilities()
      .then(response => { if (isActive() && request === sequence.current) setMailCapabilities(response); })
      .catch(failure => {
        if (!isActive() || request !== sequence.current) return;
        if (failure instanceof PrivateWorkspaceApiError && [401, 403].includes(failure.status)) handleFailure(failure);
        else { setMailCapabilities(null); setMailCapabilitiesNotice('暂时无法检查智能整理服务，可先查看邮件原文'); }
      })
      .finally(() => { if (isActive() && request === sequence.current) setMailCapabilitiesLoading(false); });
    return () => { if (sequence.current === request) sequence.current++; };
  }, [access, refresh, handleFailure, isActive]);
  const smartMailEnabled = mailCapabilities?.smart_brief?.enabled !== false;
  const smartMailConfigured = mailCapabilities?.smart_brief?.enabled === true && mailCapabilities.smart_brief.configured === true;
  const legacyTranslationEnabled = mailCapabilities?.smart_brief?.enabled === false && mailCapabilities?.translation?.enabled === true && mailCapabilities.translation.configured === true;

  useEffect(() => {
    if (bossExplainPending.current) return;
    const sequence = bossBriefRequest;
    const request = ++sequence.current;
    setBossBrief(previous => previous?.period === briefPeriod ? previous : null); setBossBriefError('');
    if (access !== 'allowed' || view !== 'today') { setBossBriefLoading(false); return; }
    setBossBriefLoading(bossLoadedPeriod.current !== briefPeriod);
    void privateWorkspaceApi.brief(briefPeriod)
      .then(response => { if (isActive() && request === sequence.current && response.period === briefPeriod) { bossLoadedPeriod.current = briefPeriod; setBossBrief(response); } })
      .catch(failure => { if (isActive() && request === sequence.current) { setBossBrief(null); bossLoadedPeriod.current = null; setBossBriefError(handleFailure(failure)); } })
      .finally(() => { if (isActive() && request === sequence.current) setBossBriefLoading(false); });
    return () => { if (sequence.current === request) sequence.current++; };
  }, [access, view, briefPeriod, refresh, adsNow, handleFailure, isActive]);

  async function explainBossBrief() {
    if (busy || bossExplainPending.current || bossBriefLoading || !bossBrief?.capabilities.configured || bossBrief.period !== briefPeriod || !isActive()) return;
    const snapshotId = bossBrief.snapshot_id;
    const request = ++bossExplainRequest.current;
    bossExplainPending.current = true; setBusy('boss-brief'); setBossBriefNotice('');
    try {
      const response = await privateWorkspaceApi.explainBrief(briefPeriod, snapshotId);
      if (!isActive() || request !== bossExplainRequest.current) return;
      if (response.period !== briefPeriod || response.snapshot_id !== snapshotId) {
        setBossBriefNotice('来源数据已更新，请查看新简报后再生成解读。'); setRefresh(value => value + 1); return;
      }
      setBossBrief(response);
      if (response.ai?.state !== 'ready') setBossBriefNotice(bossBriefStatusNotice(response.ai?.code || response.capabilities.code));
    } catch (failure) {
      if (!isActive() || request !== bossExplainRequest.current) return;
      setBossBriefNotice(handleFailure(failure));
    } finally { if (isActive() && request === bossExplainRequest.current) { bossExplainPending.current = false; setBusy(''); } }
  }

  useEffect(() => {
    const sequence = stripeReportRequest;
    const request = ++sequence.current;
    if (access !== 'allowed' || view !== 'stripe') { setStripeReportLoading(false); return; }
    setStripeReport(null); setStripeReportError('');
    if (stripeSelection.preset === 'custom' && (!privateStripeReportDate(stripeSelection.start_date)
        || !privateStripeReportDate(stripeSelection.end_date) || stripeSelection.start_date > stripeSelection.end_date)) {
      setStripeReportError('请选择有效的开始和结束日期'); setStripeReportLoading(false); return;
    }
    setStripeReportLoading(true);
    void privateWorkspaceApi.stripeReport({ period: stripeSelection.preset,
      ...(stripeSelection.preset === 'custom' ? { start_date: stripeSelection.start_date, end_date: stripeSelection.end_date } : {}), refresh: refresh > 0 })
      .then(response => { if (isActive() && request === sequence.current) setStripeReport(response); })
      .catch(failure => { if (isActive() && request === sequence.current) setStripeReportError(handleFailure(failure)); })
      .finally(() => { if (isActive() && request === sequence.current) setStripeReportLoading(false); });
    return () => { if (sequence.current === request) sequence.current++; };
  }, [access, view, stripeSelection.preset, stripeSelection.start_date, stripeSelection.end_date, refresh, handleFailure, isActive]);

  useEffect(() => {
    const sequence = listRequest;
    const request = ++sequence.current;
    listReadySignature.current = '';
    setList([]); setTotal(0); setListError(''); setMailCounts(EMPTY_MAIL_COUNTS);
    if (access !== 'allowed' || view === 'today' || view === 'connections' || view === 'funds') { setListLoading(false); return; }
    setListLoading(true);
    void privateWorkspaceApi.items({ source_id: view, ...(view === 'stripe' ? { kind: stripeKind } : {}), ...(view === 'manual' ? { action_status: manualStatus } : {}), ...(view === 'gmail' && mailBucket !== 'all' ? { mail_bucket: mailBucket } : {}), limit: 100 })
      .then(response => { if (isActive() && request === listRequest.current) { rememberLoadedItems(response.items); setList(response.items); setTotal(response.total); setMailCounts(response.mail_counts || EMPTY_MAIL_COUNTS); } })
      .catch(failure => { if (isActive() && request === listRequest.current) setListError(handleFailure(failure)); })
      .finally(() => { if (isActive() && request === listRequest.current) { listReadySignature.current = `${view}:${stripeKind}:${manualStatus}:${mailBucket}`; setListLoading(false); } });
    return () => { if (sequence.current === request) sequence.current++; };
  }, [access, view, stripeKind, manualStatus, mailBucket, refresh, handleFailure, isActive, rememberLoadedItems]);

  useEffect(() => {
    if (loading || listLoading || bossBriefLoading || stripeReportLoading || !pendingScroll.current || pendingScroll.current.key !== location.key) return;
    if (!['today', 'connections', 'funds'].includes(view) && listReadySignature.current !== pendingScroll.current.signature) return;
    if (view === 'today' && bossLoadedPeriod.current !== briefPeriod && !bossBriefError) return;
    const target = pendingScroll.current.top; pendingScroll.current = null;
    if (typeof window.scrollTo === 'function') window.scrollTo({ top: target, behavior: 'instant' });
  }, [location.key, view, briefPeriod, loading, listLoading, bossBriefLoading, bossBriefError, stripeReportLoading]);

  useEffect(() => {
    const remember = () => pagePositions.current.set(location.key, { view, scrollY: window.scrollY || 0, stripeKind, stripeSelection, mailBucket, manualStatus, briefPeriod });
    window.addEventListener('scroll', remember, { passive: true });
    return () => { remember(); window.removeEventListener('scroll', remember); };
  }, [location.key, view, stripeKind, stripeSelection, mailBucket, manualStatus, briefPeriod]);


  const translatePreviews = useCallback(async (items: PrivateItem[]) => {
    if (!legacyTranslationEnabled || mailCapabilitiesLoading || translationPending.current || translationUnavailable || translationLimited || !isActive()) return;
    const candidates = items.filter(item => item.source_id === 'gmail' && item.mail_translation?.state !== 'ready' && !translationAttemptedIds.current.has(item.id)).slice(0, 10);
    if (!candidates.length) return;
    const request = ++translationRequest.current;
    const originals = new Map(candidates.map(item => [item.id, { title: item.title, summary: item.summary }]));
    candidates.forEach(item => translationAttemptedIds.current.add(item.id));
    translationPending.current = true; setTranslationBusy(true); setTranslationNotice('');
    try {
      const response = await privateWorkspaceApi.translateMailPreviews(candidates.map(item => item.id));
      if (!isActive() || request !== translationRequest.current) return;
      if (!response.configured) { setTranslationUnavailable(true); setTranslationNotice('中文翻译尚未开通'); return; }
      const translations = new Map((response.items || []).filter(result => result.translation?.state === 'ready').map(result => {
        const { state, title_zh, summary_zh, updated_at } = result.translation;
        return [result.item_id, { state, title_zh, summary_zh, updated_at, body_available: false, truncated: false }] as const;
      }));
      const apply = (item: PrivateItem): PrivateItem => {
        const original = originals.get(item.id); const translation = translations.get(item.id);
        return translation && original?.title === item.title && original.summary === item.summary && !item.mail_translation?.body_available ? { ...item, mail_translation: translation } : item;
      };
      for (const [token, panel] of privatePanels.current) if (panel.item) privatePanels.current.set(token, { ...panel, item: apply(panel.item) });
      setList(previous => previous.map(apply)); setData(previous => previous ? { ...previous, items: previous.items.map(apply) } : previous); setSelected(previous => previous ? apply(previous) : previous);
      if (response.code === 'limit_reached') setTranslationLimited(true);
      if (response.code || translations.size < candidates.length) setTranslationNotice(privateMailTranslationNotice(response.code));
    } catch (failure) {
      if (!isActive() || request !== translationRequest.current) return;
      if (failure instanceof PrivateWorkspaceApiError && [401, 403].includes(failure.status)) handleFailure(failure);
      else setTranslationNotice('中文翻译暂时无法完成，可先查看原文');
    } finally { if (isActive() && request === translationRequest.current) { translationPending.current = false; setTranslationBusy(false); } }
  }, [legacyTranslationEnabled, mailCapabilitiesLoading, translationUnavailable, translationLimited, isActive, handleFailure]);

  useEffect(() => {
    if (!legacyTranslationEnabled || mailCapabilitiesLoading || view !== 'gmail' || access !== 'allowed' || listLoading || listError || !list.length || autoTranslationAttempted.current) return;
    autoTranslationAttempted.current = true;
    void translatePreviews(list);
  }, [legacyTranslationEnabled, mailCapabilitiesLoading, view, access, listLoading, listError, list, translatePreviews]);

  async function translateBody(item: PrivateItem) {
    if (!legacyTranslationEnabled || mailCapabilitiesLoading || busy || bodyTranslationPending.current || translationUnavailable || !isActive()) return;
    const request = ++bodyTranslationRequest.current;
    bodyTranslationPending.current = true;
    setBusy(`translate-body-${item.id}`); setBodyTranslationNotice(null);
    try {
      const response = await privateWorkspaceApi.translateMailBody(item.id);
      if (!isActive() || request !== bodyTranslationRequest.current) return;
      if (!response.configured) { setTranslationUnavailable(true); setTranslationNotice('中文翻译尚未开通'); setBodyTranslationNotice({ id: item.id, message: '中文翻译尚未开通' }); return; }
      if (response.translation?.state === 'ready') {
        rememberUpdatedItem({ ...item, mail_translation: response.translation });
        setSelected(previous => previous?.id === item.id && previous.title === item.title && previous.summary === item.summary ? { ...previous, mail_translation: response.translation } : previous);
        const { state, title_zh, summary_zh, updated_at } = response.translation;
        const preview = { state, title_zh, summary_zh, updated_at, body_available: false, truncated: false };
        const apply = (current: PrivateItem) => current.id === item.id && current.title === item.title && current.summary === item.summary ? { ...current, mail_translation: preview } : current;
        setList(previous => previous.map(apply)); setData(previous => previous ? { ...previous, items: previous.items.map(apply) } : previous);
        if (!response.translation.body_available || !response.translation.body_original) setBodyTranslationNotice({ id: item.id, message: privateMailTranslationNotice('body_unavailable') });
      } else { if (response.code === 'limit_reached') { setTranslationLimited(true); setTranslationNotice(privateMailTranslationNotice(response.code)); } setBodyTranslationNotice({ id: item.id, message: privateMailTranslationNotice(response.code || (response.translation?.state === 'unavailable' ? 'body_unavailable' : undefined)) }); }
    } catch (failure) {
      if (!isActive() || request !== bodyTranslationRequest.current) return;
      if (failure instanceof PrivateWorkspaceApiError && [401, 403].includes(failure.status)) handleFailure(failure);
      else setBodyTranslationNotice({ id: item.id, message: '中文翻译暂时无法完成，可先查看原文' });
    } finally { if (isActive() && request === bodyTranslationRequest.current) { bodyTranslationPending.current = false; setBusy(''); } }
  }
  async function organizeMail(item: PrivateItem) {
    if (busy || mailBriefPending.current || mailCapabilitiesLoading || !smartMailConfigured || item.source_id !== 'gmail' || !isActive()) return;
    const request = ++mailBriefRequest.current;
    mailBriefPending.current = true; setBusy(`mail-brief-${item.id}`); setMailBriefNotice(null);
    try {
      const response = await privateWorkspaceApi.organizeMail(item.id);
      if (!isActive() || request !== mailBriefRequest.current || response.item_id !== item.id) return;
      if (!response.configured) {
        setMailCapabilities(previous => previous ? { ...previous, smart_brief: { ...previous.smart_brief, configured: false, code: response.code || 'not_configured' } } : previous);
        setMailBriefNotice({ id: item.id, message: privateMailBriefNotice(response.code || 'not_configured', mailCapabilities?.budget) }); return;
      }
      if (response.brief?.state === 'ready') {
        rememberUpdatedItem({ ...item, mail_brief: response.brief });
        setSelected(previous => previous?.id === item.id && previous.title === item.title && previous.summary === item.summary ? { ...previous, mail_brief: response.brief } : previous);
        const preview = { ...response.brief, original_body: undefined, source_evidence: undefined, deadline: response.brief.deadline ? { ...response.brief.deadline, evidence: undefined } : null };
        const apply = (current: PrivateItem) => current.id === item.id && current.title === item.title && current.summary === item.summary ? { ...current, mail_brief: preview } : current;
        setList(previous => previous.map(apply)); setData(previous => previous ? { ...previous, items: previous.items.map(apply) } : previous);
        if (response.brief.source_scope === 'preview') setMailBriefNotice({ id: item.id, message: privateMailBriefNotice('body_unavailable') });
      } else setMailBriefNotice({ id: item.id, message: privateMailBriefNotice(response.code || response.brief?.code || (response.brief?.state === 'pending' ? 'pending' : undefined), mailCapabilities?.budget) });
    } catch (failure) {
      if (!isActive() || request !== mailBriefRequest.current) return;
      if (failure instanceof PrivateWorkspaceApiError && [401, 403].includes(failure.status)) handleFailure(failure);
      else setMailBriefNotice({ id: item.id, message: privateMailBriefNotice('upstream_unavailable') });
    } finally { if (isActive() && request === mailBriefRequest.current) { mailBriefPending.current = false; setBusy(''); } }
  }
  const moreTranslationAvailable = list.some(item => item.source_id === 'gmail' && item.mail_translation?.state !== 'ready' && !translationAttemptedIds.current.has(item.id));

  function rememberPrivatePosition() {
    pagePositions.current.set(location.key, { view, scrollY: window.scrollY || 0, stripeKind, stripeSelection, mailBucket, manualStatus, briefPeriod });
  }
  function privateHistoryState(panelToken?: string) {
    return { privateWorkspace: { session: sessionEpoch.current, parentKey: location.key, parentView: view, ...(panelToken ? { panelToken } : {}) } };
  }
  function pushPrivatePanel(entry: PrivatePanelEntry, options?: { replace?: boolean }) {
    rememberPrivatePosition();
    const token = `panel-${++panelSequence.current}`; privatePanels.current.set(token, entry);
    const next = new URLSearchParams(params); next.set('view', view); next.delete('panel'); next.delete('item');
    if (entry.item) next.set('item', entry.item.id);
    if (entry.kind !== 'detail') next.set('panel', entry.kind);
    setParams(next, { replace: options?.replace, state: options?.replace ? { privateWorkspace: { ...navigationEntry, session: sessionEpoch.current, panelToken: token } } : privateHistoryState(token) });
  }
  function rememberUpdatedItem(item: PrivateItem) {
    for (const [token, panel] of privatePanels.current) if (panel.item?.id === item.id) privatePanels.current.set(token, { ...panel, item });
  }
  function openItem(item: PrivateItem) {
    if (busy || !draft.confirmDiscard() || !snoozeDraft.confirmDiscard() || !preferencesDraft.confirmDiscard()) return;
    setSelected(item); pushPrivatePanel({ view, kind: 'detail', item });
  }
  function closePrivateLayer() {
    if (busy || !draft.confirmDiscard() || !snoozeDraft.confirmDiscard() || !preferencesDraft.confirmDiscard()) return;
    rememberPrivatePosition();
    if (backTarget.history) routeNavigate(-1);
    else {
      const next = new URLSearchParams(params); next.delete('item'); next.delete('panel');
      setParams(next, { replace: true });
    }
  }
  function backWithinPrivate() {
    if (busy || !draft.confirmDiscard() || !snoozeDraft.confirmDiscard() || !preferencesDraft.confirmDiscard()) return;
    if (params.has('item') || params.has('panel')) { closePrivateLayer(); return; }
    rememberPrivatePosition();
    if (backTarget.history) routeNavigate(-1);
    else setParams({ view: 'today' }, { replace: true });
  }
  function navigate(next: View) {
    if (busy || !draft.confirmDiscard() || !snoozeDraft.confirmDiscard() || !preferencesDraft.confirmDiscard()) return;
    if (next === view && !params.has('item') && !params.has('panel')) return;
    rememberPrivatePosition(); preferencesRequest.current++;
    setEditor(null); setSnoozeItem(null); setPreferencesOpen(false); setSelected(null); setNotice('');
    setParams({ view: next }, { state: privateHistoryState() });
  }
  function returnToCrm(event: React.MouseEvent<HTMLAnchorElement>) { if (busy || !draft.confirmDiscard() || !snoozeDraft.confirmDiscard() || !preferencesDraft.confirmDiscard()) event.preventDefault(); }
  function openSnooze(item: PrivateItem) {
    const at = tomorrowMorning(); setSnoozeItem(item); setSnoozeAt(at); setSnoozeError('');
    pushPrivatePanel({ view, kind: 'snooze', item, snoozeAt: at });
  }
  function openEditor(item?: PrivateItem) {
    if (!draft.confirmDiscard()) return;
    setEditingId(item?.id || null);
    const initialForm = item ? { title: item.title, summary: item.summary || '', priority: item.priority, due_at: localDateInput(item.due_at) } : { ...EMPTY_FORM };
    setForm(initialForm);
    setFormError(''); setEditor(item ? 'edit' : 'new');
    pushPrivatePanel({ view, kind: 'editor', editor: item ? 'edit' : 'new', initialForm, ...(item ? { item } : {}) });
  }
  function openBriefTask(proposal: { title: string; summary: string }) {
    if (busy || !isActive() || !draft.confirmDiscard()) return;
    const initialForm = { ...EMPTY_FORM, title: proposal.title.slice(0, 240), summary: proposal.summary.slice(0, 5000) };
    setEditingId(null); setForm(initialForm);
    setFormError(''); setEditor('new');
    pushPrivatePanel({ view, kind: 'editor', editor: 'new', initialForm });
  }
  function openItemTask(item: PrivateItem) {
    const title = itemDisplayTitle(item);
    const nextAction = item.source_id === 'gmail' && item.mail_brief?.state === 'ready' ? item.mail_brief.next_action : item.source_id === 'google_ads' ? privateAdsObservation(item, sourceById.get('google_ads'), adsNow).nextAction : null;
    const sourceUrl = verifiedPrivateSourceUrl(item.source_id, item.source_url);
    openBriefTask({ title: `处理${SOURCE_NAMES[item.source_id]}：${title}`.slice(0, 240),
      summary: [`来源：${SOURCE_NAMES[item.source_id]} · ${title}`, `下一步：${nextAction || '核对原始来源后确定下一步。'}`, sourceUrl ? `来源链接：${sourceUrl}` : ''].filter(Boolean).join('\n') });
  }
  function openBriefItem(id: string) {
    if (busy || !isActive()) return;
    const issue = bossBrief?.issues.find(value => value.item_id === id);
    if (!issue) return;
    const item = data?.items.find(value => value.id === id && value.source_id === issue.source_id);
    if (item) openItem(item);
    else navigate(issue.source_id);
  }
  async function refreshAfterWrite() { await loadWorkspace(); if (isActive()) setRefresh(value => value + 1); }
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
      if (!isActive()) return;
      draft.markSaved(); rememberUpdatedItem(response.item); setEditor(null); setForm(EMPTY_FORM); setSelected(response.item); setNotice('个人事项已保存。');
      if (editor === 'edit' && backTarget.history) routeNavigate(-1);
      else pushPrivatePanel({ view, kind: 'detail', item: response.item }, { replace: true });
      await refreshAfterWrite();
    } catch (failure) { if (isActive()) setFormError(handleFailure(failure)); }
    finally { if (isActive()) setBusy(''); }
  }
  async function updateAction(item: PrivateItem, patch: UpdatePrivateItem, archive = false) {
    if (busy) return;
    setBusy(`item-${item.id}`); setNotice('');
    try {
      const response = archive ? await privateWorkspaceApi.archive(item.id) : await privateWorkspaceApi.update(item.id, patch);
      if (!isActive()) return;
      rememberUpdatedItem(response.item); setSelected(previous => previous?.id === response.item.id ? response.item : previous);
      setNotice(archive ? '事项已归档，可在归档列表恢复。' : bankAlert(item) ? '工作台阅读状态已保存；银行提醒仍待核实。' : '工作台处理状态已保存。');
      snoozeDraft.markSaved(); setSnoozeItem(null); setSnoozeError('');
      if (params.get('panel') === 'snooze' && backTarget.history) routeNavigate(-1);
      await refreshAfterWrite();
    } catch (failure) { if (isActive()) { const message = handleFailure(failure); setNotice(message); if (snoozeItem) setSnoozeError(message); } }
    finally { if (isActive()) setBusy(''); }
  }
  async function sourceAction(source: PrivateSource, action: 'connect' | 'disconnect' | 'sync') {
    const startsBank = source.id === 'bofa_bank' && action === 'connect';
    if (busy || (startsBank && bankStartPending.current)) return;
    const bankRequest = startsBank ? ++bankStartRequest.current : 0;
    if (startsBank) bankStartPending.current = true;
    setBusy(`${action}-${source.id}`); setNotice('');
    try {
      if (action === 'connect') {
        if (source.id === 'bofa_bank') {
          const result = await privateWorkspaceApi.bankLinkStart();
          if (!isActive() || bankRequest !== bankStartRequest.current) return;
          const url = verifiedBankAuthorizationUrl(result.authorization_url);
          if (!url) throw new Error('银行授权地址暂不可打开，请重新连接。');
          window.location.assign(url);
          return;
        }
        const response = await privateWorkspaceApi.connect(source.id);
        if (!isActive()) return;
        if (response.requires_redirect) {
          const url = verifiedPrivateAuthorizationUrl(source.id, response.authorization_url);
          if (!url) throw new Error('授权地址暂不可打开，请联系管理员检查配置。');
          window.location.assign(url);
          return;
        }
        setNotice(response.source.status === 'connected' ? '来源已连接。' : SOURCE_STATUS[response.source.status] || '来源状态已更新。');
      } else if (action === 'sync') {
        const response = await privateWorkspaceApi.sync(source.id);
        if (!isActive()) return;
        setNotice(`同步完成：新增 ${response.counts.created} 条，更新 ${response.counts.updated} 条。`);
      } else {
        await privateWorkspaceApi.disconnect(source.id);
        if (!isActive()) return;
        setNotice('同步已停止，本地连接凭据已清除。如需撤销平台授权，请到对应平台的账号设置中操作。');
      }
      await refreshAfterWrite();
    } catch (failure) { if (isActive()) { setNotice(handleFailure(failure)); await loadWorkspace(); } }
    finally {
      if (startsBank && bankRequest === bankStartRequest.current) bankStartPending.current = false;
      if (isActive()) setBusy('');
    }
  }

  async function completeBankConnection() {
    const session = params.get('bank_session');
    if (busy || bankCompletePending.current || !isActive() || !session || !/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(session)) return;
    bankCompletePending.current = true;
    const request = ++bankCompleteRequest.current;
    setBusy('complete-bofa_bank'); setNotice('');
    try {
      const result = await privateWorkspaceApi.bankLinkComplete(session);
      if (!isActive() || request !== bankCompleteRequest.current || bankReturnSessionRef.current !== session) return;
      if (result.session_id !== session || result.source_id !== 'bofa_bank' || !['pending', 'connected'].includes(result.state)) throw new Error('银行授权确认结果不匹配，请重新打开当前连接。');
      if (result.state === 'pending') { setNotice('银行授权尚未完成，请在授权页面完成后再确认连接。'); return; }
      setNotice('银行已连接，正在读取账户和交易记录…');
      await privateWorkspaceApi.sync('bofa_bank');
      if (isActive() && request === bankCompleteRequest.current && bankReturnSessionRef.current === session) {
        setNotice('银行账户与交易记录已同步。');
        setParams({ view: 'bofa_bank' }, { replace: true });
        await refreshAfterWrite();
      }
    } catch (failure) { if (isActive() && request === bankCompleteRequest.current && bankReturnSessionRef.current === session) { setNotice(handleFailure(failure)); await loadWorkspace(); } }
    finally { if (request === bankCompleteRequest.current) { bankCompletePending.current = false; if (isActive()) setBusy(''); } }
  }

  function closePreferences() {
    if (busy || !preferencesDraft.confirmDiscard()) return;
    preferencesRequest.current++; setPreferencesOpen(false); setPreferencesError(''); setPreferencesForm(EMPTY_PREFERENCE_FORM);
    closePrivateLayer();
  }
  async function openPreferences() {
    if (busy || !draft.confirmDiscard() || !snoozeDraft.confirmDiscard()) return;
    const request = ++preferencesRequest.current;
    if (params.get('panel') !== 'preferences') pushPrivatePanel({ view, kind: 'preferences' });
    setEditor(null); setSnoozeItem(null); setPreferencesOpen(true); setPreferencesLoading(true); setPreferencesReady(false); setPreferencesError(''); setPreferencesForm(EMPTY_PREFERENCE_FORM);
    try {
      const response = await privateWorkspaceApi.preferences();
      if (!isActive() || request !== preferencesRequest.current) return;
      setPreferencesForm(preferenceForm(response));
      setPreferencesReady(true);
    } catch (failure) { if (isActive() && request === preferencesRequest.current) setPreferencesError(handleFailure(failure)); }
    finally { if (isActive() && request === preferencesRequest.current) setPreferencesLoading(false); }
  }
  reopenPreferences.current = () => { void openPreferences(); };
  useEffect(() => {
    const panel = navigationEntry?.panelToken ? privatePanels.current.get(navigationEntry.panelToken) : undefined;
    if (access === 'allowed' && params.get('panel') === 'preferences' && panel?.kind === 'preferences' && !preferencesOpen) reopenPreferences.current();
  }, [access, location.key, navigationEntry, params, preferencesOpen]);

  async function savePreferences(event: FormEvent) {
    event.preventDefault();
    if (busy || preferencesLoading || !preferencesReady) return;
    const watch_senders = inputLines(preferencesForm.watch_senders).map(value => value.toLowerCase());
    const muted_senders = inputLines(preferencesForm.muted_senders).map(value => value.toLowerCase());
    const watch_keywords = inputLines(preferencesForm.watch_keywords);
    const domain = /^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$/i;
    const validSender = (value: string) => domain.test(value) || /^[^\s@<>]+@[^\s@<>]+$/.test(value) && domain.test(value.split('@')[1]);
    if ([...watch_senders, ...muted_senders].some(value => value.length > 254 || !validSender(value))) { setPreferencesError('请填写完整邮箱或域名，例如 name@example.com 或 example.com。'); return; }
    if (watch_senders.length > 50 || muted_senders.length > 50) { setPreferencesError('每组发件人最多填写 50 个。'); return; }
    if (watch_keywords.length > 30 || watch_keywords.some(value => value.length > 80)) { setPreferencesError('关键词最多 30 个，每个不超过 80 个字。'); return; }
    setBusy('save-preferences'); setPreferencesError('');
    try {
      await privateWorkspaceApi.updatePreferences({ gmail: { topics: preferencesForm.topics, watch_senders, watch_keywords, muted_senders } });
      if (!isActive()) return;
      preferencesDraft.markSaved(); setPreferencesOpen(false); setPreferencesForm(EMPTY_PREFERENCE_FORM); setNotice('关注设置已保存，现有邮件已按新规则整理。');
      if (backTarget.history) routeNavigate(-1); else { const next = new URLSearchParams(params); next.delete('panel'); setParams(next, { replace: true }); }
      await refreshAfterWrite();
    } catch (failure) { if (isActive()) setPreferencesError(handleFailure(failure)); }
    finally { if (isActive()) setBusy(''); }
  }
  async function giveMailFeedback(item: PrivateItem, feedback: PrivateMailFeedback) {
    if (busy) return;
    const applyToSender = Boolean(applyFeedbackToSender && item.mail_relevance?.sender_address);
    setBusy(`feedback-${item.id}`); setNotice('');
    try {
      const response = await privateWorkspaceApi.mailFeedback(item.id, feedback, applyToSender);
      if (!isActive()) return;
      rememberUpdatedItem(response.item); setSelected(previous => previous?.id === response.item.id ? response.item : previous); setApplyFeedbackToSender(false);
      setNotice(feedback === null ? applyToSender ? '本封及发件人的反馈已取消；手动填写的关注与低优先名单保留。' : '本封邮件的反馈已取消，恢复按关注规则整理。' : '反馈已保存。');
      await refreshAfterWrite();
    } catch (failure) { if (isActive()) setNotice(handleFailure(failure)); }
    finally { if (isActive()) setBusy(''); }
  }

  const balances = (data?.balances || []).filter(balance => balance.source_id === 'stripe');
  const safeSelectedUrl = selected ? verifiedPrivateSourceUrl(selected.source_id, selected.source_url) : null;
  const callbackSourceName = SOURCE_NAMES[callbackSource] || SOURCE_NAMES[view as PrivateSourceId] || '该来源';
  const callbackMessage = params.get('connection') === 'connected' && sourceById.get(callbackSource)?.status === 'connected'
    ? '授权已完成，请查看来源与同步状态。' : params.get('connection') === 'incomplete' ? '授权未完成，请在工作接入中重试。' : params.get('connection') === 'expired' ? `这次授权链接已失效，请到工作接入重新连接 ${callbackSourceName}。` : '';
  const bankReturnSession = params.get('bank_session');
  const bankReturnNotice = access === 'allowed' && view === 'bofa_bank' && bankReturnSession && /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(bankReturnSession) ? <div className="pw-notice" role="status"><span>已返回银行授权，请确认连接并读取数据。</span><button type="button" className="pw-button pw-button-primary" disabled={Boolean(busy)} onClick={() => void completeBankConnection()}>{busy === 'complete-bofa_bank' ? '正在确认…' : '确认银行连接'}</button></div> : null;
  const callbackNotice = callbackMessage && access === 'allowed' ? <div className="pw-notice pw-callback-notice" role="status">{callbackMessage}{params.get('connection') === 'expired' && <button type="button" className="pw-text-button" onClick={() => navigate('connections')}>打开工作接入<ChevronRight aria-hidden="true" /></button>}</div> : null;
  const dateLabel = new Date().toLocaleDateString('zh-CN', { month: 'long', day: 'numeric', weekday: 'long' });

  function renderSource(source: PrivateSource) {
    const Icon = SOURCE_ICONS[source.id];
    const actions = privateSourceActionAvailability(source);
    return <section key={source.id} className="pw-connection">
      <div className="pw-connection-heading"><span className="pw-source-icon"><Icon aria-hidden="true" /></span><div><h3>{SOURCE_NAMES[source.id]}</h3><span className={`pw-status ${source.status === 'error' ? 'pw-status-warning' : ''}`}>{SOURCE_STATUS[source.status] || '状态待确认'}</span></div></div>
      {sourceAccountLabel(source) && <p className="pw-account-label">{source.id === 'google_ads' ? '广告账户：' : ''}{sourceAccountLabel(source)}</p>}
      <p className="pw-sync-time">最后成功同步：{timeLabel(source.last_sync)}</p>
      {source.error && <p className="pw-source-error">{source.error}</p>}
      {source.id === 'bofa' && <p className="pw-connection-note">银行邮件提醒保持待核实；实际余额与流水在银行账户查看。</p>}{source.id === 'bofa_bank' && <p className="pw-connection-note">通过 Plaid 安全授权读取所选账户的余额与交易流水。</p>}
      {actions.pendingConfiguration && <p className="pw-connection-note">来源配置尚未完成，暂时无法连接或同步。</p>}
      {source.id === 'google_ads' && actions.canConnect && <p id="pw-google-ads-consent-note" className="pw-connection-note">Google 授权包含查看、修改、创建和删除广告账号及数据。当前工作空间仅查询广告表现。</p>}
      {(actions.canConnect || actions.canSync || actions.canDisconnect) && <div className="pw-source-actions">
        {actions.canConnect && <button type="button" className="pw-button pw-button-primary" aria-describedby={source.id === 'google_ads' ? 'pw-google-ads-consent-note' : undefined} disabled={Boolean(busy)} onClick={() => void sourceAction(source, 'connect')}>{source.status === 'error' ? '重新连接 / 授权' : source.status === 'connecting' ? '继续授权' : '连接来源'}</button>}
        {actions.canSync && <button type="button" className="pw-button" disabled={Boolean(busy)} onClick={() => void sourceAction(source, 'sync')}><RefreshCw aria-hidden="true" />{busy === `sync-${source.id}` ? '正在同步…' : '同步'}</button>}
        {actions.canDisconnect && <button type="button" className="pw-button pw-button-quiet" disabled={Boolean(busy)} onClick={() => void sourceAction(source, 'disconnect')}>停止同步</button>}
      </div>}
    </section>;
  }
  function sourceBanner(source?: PrivateSource) {
    if (!source) return null;
    return <div className="pw-source-banner pw-source-banner-compact"><div className="pw-source-summary"><span className="pw-status">{SOURCE_STATUS[source.status] || '状态待确认'}</span><span>同步 {timeLabel(source.last_sync)}</span>{source.metadata?.partial && <span className="pw-status">部分记录</span>}{source.metadata?.mode === 'test' && <span className="pw-status-warning">测试数据</span>}</div><details className="pw-source-description"><summary>来源与范围<ChevronRight aria-hidden="true" /></summary>{sourceAccountLabel(source) && <p>{sourceAccountLabel(source)}</p>}{coverageLabel(source) && <p>{coverageLabel(source)}</p>}{source.metadata?.partial && <p>尚有记录未包含，当前列表不代表完整账户汇总。</p>}<button type="button" className="pw-text-button" onClick={() => navigate('connections')}>管理接入<ChevronRight aria-hidden="true" /></button></details>{source.error && <p className="pw-source-error" role="status">{source.error}</p>}</div>;
  }
  function renderList() {
    if (listLoading) return <div className="pw-load" role="status"><LoaderCircle aria-hidden="true" />正在读取当前来源…</div>;
    if (listError) return <div className="pw-load pw-error" role="alert"><p>{listError}</p><button type="button" className="pw-button" onClick={() => setRefresh(value => value + 1)}>重新读取</button></div>;
    if (!list.length) return <Empty title={view === 'manual' ? '这里还没有个人事项' : view === 'gmail' && mailBucket !== 'all' ? `暂无${PRIVATE_MAIL_BUCKET_NAMES[mailBucket]}的邮件` : '当前没有可查看的数据'} detail={view === 'manual' ? '创建一项工作，下一步会更清楚。' : view === 'gmail' && mailBucket !== 'all' && currentSource?.status === 'connected' ? '可以查看全部邮件，或调整关注设置。' : currentSource?.status === 'connected' ? '该来源尚未返回这一类记录，可在工作接入中同步。' : '来源尚未授权或配置，连接后才会显示真实数据。'} action={view === 'manual' && manualStatus === 'open' ? <button className="pw-button pw-button-primary" onClick={() => openEditor()}><Plus aria-hidden="true" />新增事项</button> : undefined} />;
    if (view === 'gmail') {
      const buckets = mailBucket === 'all' ? PRIVATE_MAIL_BUCKETS : [mailBucket];
      return <div className="pw-mail-groups">{buckets.map(bucket => {
        const items = list.filter(item => privateMailBucket(item) === bucket);
        if (!items.length && !mailCounts[bucket]) return null;
        const count = mailCounts[bucket] || items.length;
        const content = <><div className="pw-list">{items.map(item => <ItemRow key={item.id} item={item} source={sourceById.get(item.source_id)} onSelect={openItem} />)}</div>{mailBucket === 'all' && count > items.length && <button type="button" className="pw-text-button pw-mail-view-group" onClick={() => setMailBucket(bucket)}>查看该组邮件<ChevronRight aria-hidden="true" /></button>}</>;
        return bucket === 'low' && mailBucket === 'all'
          ? <details key={bucket} className="pw-mail-group pw-mail-low"><summary><span>{PRIVATE_MAIL_BUCKET_NAMES[bucket]}<small>{count}</small></span><ChevronRight aria-hidden="true" /></summary>{content}</details>
          : <section key={bucket} className={`pw-mail-group pw-mail-group-${bucket}`}><div className="pw-section-heading"><h2>{PRIVATE_MAIL_BUCKET_NAMES[bucket]}<small>{count}</small></h2></div>{content}</section>;
      })}{total > list.length && <p className="pw-list-footnote">{mailBucket === 'all' ? `当前显示前 ${list.length} 封已同步邮件，选择上方分组可查看该组。` : `当前显示前 ${list.length} 封，已同步的该组共 ${total} 封；更早邮件请在 Gmail 查看。`}</p>}</div>;
    }
    return <>{view !== 'manual' && view !== 'stripe' && <p className="pw-list-footnote pw-coverage-note">当前列表为最近同步的局部记录。</p>}<div className="pw-list">{list.map(item => <ItemRow key={item.id} item={item} source={sourceById.get(item.source_id)} onSelect={openItem} />)}</div>{total > list.length && <p className="pw-list-footnote">当前显示最近 {list.length} 条，共 {total} 条。</p>}</>;
  }
  function renderStripeSnapshot() {
    const snapshot = privateStripeSnapshot(currentSource, adsNow);
    const resourceName = { payment: 'charges', refund: 'refunds', dispute: 'disputes', payout: 'payouts' }[stripeKind];
    const resource = currentSource?.metadata?.resources?.[resourceName];
    const account = currentSource ? sourceAccountLabel(currentSource) : '';
    return <div className="pw-stripe-view">
      <div className="pw-stripe-source"><div><strong>{account || 'Stripe 账户待确认'}</strong><span>{snapshot.mode === 'test' ? '测试模式' : snapshot.mode === 'live' ? '正式模式' : '模式待确认'} · {currentSource ? SOURCE_STATUS[currentSource.status] : '尚未连接'}</span></div><button type="button" className="pw-text-button" onClick={() => navigate('connections')}>管理接入<ChevronRight aria-hidden="true" /></button></div>
      <div className="pw-stripe-snapshot-heading"><h2>{snapshot.label}</h2><span>{snapshot.observedAt ? timeLabel(snapshot.observedAt) : '尚无已核对快照'}</span></div>
      <div className={`pw-balance-groups pw-stripe-balances ${snapshot.state !== 'fresh' ? 'pw-stripe-balances-stale' : ''}`}>{snapshot.state !== 'unverified' && balances.length ? balances.map(balance => <section key={`${balance.source_id}-${balance.currency}`} className="pw-balance-group"><h2>{balance.currency}</h2><div><span>可用<strong>{formatPrivateAmount(balance.available_minor, balance.currency, 'stripe')}</strong></span><span>待结算<strong>{formatPrivateAmount(balance.pending_minor, balance.currency, 'stripe')}</strong></span></div></section>) : <div className="pw-stripe-balance-empty">{snapshot.state === 'unverified' ? '连接并同步后查看余额，不显示估算金额。' : '这次快照没有余额数据，请重新同步。'}</div>}</div>
      {currentSource?.error && <p className="pw-source-error pw-stripe-sync-error" role="status">{currentSource.error}</p>}
      <details className="pw-stripe-coverage"><summary>同步范围与依据<ChevronRight aria-hidden="true" /></summary><div><p>余额是来源同步时的快照；不同币种分别查看。</p><p>{resource ? `本次${STRIPE_KINDS[stripeKind]}读取 ${resource.fetched} 条${resource.partial ? '，还有较早记录未包含' : '，当前范围已读取'}。` : '记录覆盖范围待重新同步确认。'} 列表金额不代表完整经营收入。</p><p>退款记录保留来源状态；提现不代表银行已到账。未捕获授权不计为实际收款。</p></div></details>
      <div className="pw-filter-row pw-stripe-tabs" aria-label="Stripe 记录类型">{(Object.keys(STRIPE_KINDS) as StripeKind[]).map(kind => <button key={kind} type="button" aria-pressed={stripeKind === kind} className="pw-filter" onClick={() => setStripeKind(kind)}>{STRIPE_KINDS[kind]}</button>)}</div>
      {renderList()}
    </div>;
  }
  function renderStripe() {
    return <><PrivateStripeDashboard report={stripeReport} selection={stripeSelection} loading={stripeReportLoading}
      error={stripeReportError} busy={Boolean(busy)} connectionLabel={currentSource ? sourceAccountLabel(currentSource) : ''}
      connected={currentSource?.status === 'connected'} onChangeSelection={setStripeSelection}
      onRetry={() => setRefresh(value => value + 1)} onManageConnection={() => navigate('connections')} />
      {stripeReportError && <details className="pw-stripe-coverage"><summary>查看已有同步记录<ChevronRight aria-hidden="true" /></summary>
        <p>以下是最近同步的局部记录，不能作为完整期间汇总。</p>{renderStripeSnapshot()}</details>}</>;
  }
  function renderToday() {
    return <PrivateBossBrief data={bossBrief} period={briefPeriod} loading={bossBriefLoading} error={bossBriefError}
      busy={Boolean(busy)} aiConfigured={bossBrief?.capabilities.configured === true} aiBusy={busy === 'boss-brief'} aiNotice={bossBriefNotice}
      onPeriodChange={next => { if (!busy) setBriefPeriod(next); }} onExplain={() => void explainBossBrief()}
      onOpenSource={navigate} onOpenItem={openBriefItem} onCreateTask={openBriefTask}
      fundsPreview={<PrivateFundsOverview compact data={data} now={adsNow} busy={Boolean(busy)} onOpen={navigate} />}
      onRefresh={() => setRefresh(value => value + 1)} />;
  }
  function renderContent() {
    if (view === 'today') return renderToday();
    if (view === 'funds') return <PrivateFundsOverview data={data} now={adsNow} busy={Boolean(busy)} onOpen={navigate} />;
    if (view === 'gmail') return <div className="pw-gmail-view">{sourceBanner(currentSource)}<div className="pw-mail-toolbar"><div className="pw-mail-filters" aria-label="邮件优先级"><button type="button" aria-pressed={mailBucket === 'all'} onClick={() => setMailBucket('all')}>全部已同步<small>{listLoading || listError || currentSource?.status !== 'connected' ? '—' : Object.values(mailCounts).reduce((sum, count) => sum + count, 0)}</small></button>{PRIVATE_MAIL_BUCKETS.map(bucket => <button key={bucket} type="button" aria-pressed={mailBucket === bucket} onClick={() => setMailBucket(bucket)}>{PRIVATE_MAIL_BUCKET_NAMES[bucket]}<small>{listLoading || listError || currentSource?.status !== 'connected' ? '—' : mailCounts[bucket]}</small></button>)}</div><button type="button" className="pw-button pw-mail-settings" disabled={Boolean(busy)} onClick={() => void openPreferences()}><SlidersHorizontal aria-hidden="true" />关注设置</button></div><div className="pw-mail-translation-toolbar">{smartMailEnabled && !mailCapabilitiesLoading && (mailCapabilitiesNotice || !smartMailConfigured) && <p role="status">{mailCapabilitiesNotice || privateMailBriefNotice(mailCapabilities?.smart_brief?.code || 'not_configured')}</p>}{!smartMailEnabled && (translationBusy || translationNotice) && <p role="status">{translationBusy ? '正在准备中文摘要，原文仍可查看…' : translationNotice}</p>}{legacyTranslationEnabled && moreTranslationAvailable && !translationUnavailable && !translationLimited && <button type="button" className="pw-text-button" disabled={translationBusy || Boolean(busy)} onClick={() => void translatePreviews(list)}>翻译更多摘要<ChevronRight aria-hidden="true" /></button>}</div>{renderList()}</div>;
    if (view === 'bofa_bank') return <PrivateBankDashboard now={adsNow} source={currentSource} items={list} total={total} loading={listLoading} error={listError} busy={Boolean(busy)} syncing={busy === 'sync-bofa_bank'} onSelect={openItem} onConnect={() => currentSource?.status === 'connected' ? navigate('connections') : currentSource && void sourceAction(currentSource, 'connect')} onSync={() => { if (currentSource) void sourceAction(currentSource, 'sync'); }} onRefresh={() => setRefresh(value => value + 1)} />;
    if (view === 'google_ads') return <PrivateAdsDashboard now={adsNow} source={currentSource} accountLabel={currentSource ? sourceAccountLabel(currentSource) : ''} items={list} total={total} loading={listLoading} error={listError} busy={Boolean(busy)} syncing={busy === 'sync-google_ads'} onSelect={openItem} onManage={() => navigate('connections')} onSync={() => { if (currentSource) void sourceAction(currentSource, 'sync'); }} onRetry={() => setRefresh(value => value + 1)} initialNavigation={adsNavigationMemory.current} onNavigationChange={next => { adsNavigationMemory.current = next; }} />;
    if (view === 'connections') return <><div className="pw-mobile-more"><div className="pw-list">{PROVIDERS.map(id => { const Icon = SOURCE_ICONS[id]; const source = sourceById.get(id); return <button key={id} type="button" className="pw-function-row" onClick={() => navigate(id)}><span className="pw-source-icon"><Icon aria-hidden="true" /></span><span><strong>{VIEW_NAMES[id]}</strong><small>{SOURCE_NAMES[id]}</small></span><small>{source ? SOURCE_STATUS[source.status] : '状态待确认'}</small><ChevronRight aria-hidden="true" /></button>; })}</div></div><Link to="/apps" className="pw-mobile-crm-exit" onClick={returnToCrm}><span><strong>返回客户系统</strong><small>离开私人空间，进入客户业务</small></span><ArrowUpRight aria-hidden="true" /></Link><div className="pw-connections-grid">{PROVIDERS.map(id => sourceById.get(id)).filter((source): source is PrivateSource => Boolean(source)).map(renderSource)}</div><section className="pw-future"><h2>更多个人工作</h2><div><span><CalendarDays aria-hidden="true" />日程</span><span><FileText aria-hidden="true" />合同</span><span><FolderOpen aria-hidden="true" />项目</span></div><p>后续可继续接入，当前尚未启用。</p></section></>;
    if (view === 'stripe') return renderStripe();
    return <>{view !== 'manual' && sourceBanner(currentSource)}{view === 'bofa' && <p className="pw-finance-note">邮件提醒 · 待核实；实际到账与扣款以 Bank of America 流水为准。</p>}{view === 'manual' && <div className="pw-manual-toolbar"><div className="pw-filter-row" aria-label="个人事项状态">{(['open', 'snoozed', 'done', 'archived'] as PrivateActionStatus[]).map(status => <button type="button" key={status} className="pw-filter" aria-pressed={manualStatus === status} onClick={() => setManualStatus(status)}>{ACTION_STATUS[status]}</button>)}</div><button type="button" className="pw-button pw-button-primary" onClick={() => openEditor()}><Plus aria-hidden="true" />新增事项</button></div>}{renderList()}</>;
  }

  function renderMailDetail(item: PrivateItem) {
    if (item.source_id !== 'gmail') return null;
    const relevance = item.mail_relevance;
    const protectedAlert = relevance?.feedback === 'not_relevant' && ['urgent', 'today'].includes(privateMailBucket(item)) && ['finance', 'security'].includes(relevance?.category);
    return <><p className="pw-mail-sender-verification">发件人身份待核实</p><details className="pw-mail-detail-reason"><summary><h3>为什么显示这封邮件</h3><span className={`pw-mail-badge pw-mail-badge-${privateMailBucket(item)}`}>{PRIVATE_MAIL_BUCKET_NAMES[privateMailBucket(item)]}</span><ChevronRight aria-hidden="true" /></summary><ul>{(relevance?.reasons?.length ? relevance.reasons : ['最近同步的邮件，尚无个人关注规则命中']).map((reason, index) => <li key={index}>{reason}</li>)}</ul></details><section className="pw-mail-feedback"><h3>这封邮件对你有用吗？</h3><div className="pw-mail-feedback-actions"><button type="button" className="pw-button" aria-pressed={relevance?.feedback === 'important'} disabled={Boolean(busy)} onClick={() => void giveMailFeedback(item, 'important')}>需要关注</button><button type="button" className="pw-button" aria-pressed={relevance?.feedback === 'not_relevant'} disabled={Boolean(busy)} onClick={() => void giveMailFeedback(item, 'not_relevant')}>不相关</button>{(relevance?.feedback || relevance?.sender_address) && <button type="button" className="pw-text-button" disabled={Boolean(busy) || !relevance?.feedback && !applyFeedbackToSender} onClick={() => void giveMailFeedback(item, null)}>{applyFeedbackToSender ? '取消本封及发件人反馈' : '取消本封反馈'}</button>}</div><label className="pw-mail-sender-choice"><input type="checkbox" checked={applyFeedbackToSender} disabled={Boolean(busy) || !relevance?.sender_address} onChange={event => setApplyFeedbackToSender(event.target.checked)} /><span>对这个发件人的后续邮件生效</span></label>{applyFeedbackToSender && <p className="pw-detail-footnote">取消时会同时重置发件人的反馈；手动填写的关注与低优先名单保留。</p>}{protectedAlert && <p className="pw-mail-protected">已记录反馈；这封资金或安全提醒仍保留，等待核实。</p>}</section></>;
  }

  return <div className="pw-app">
    <aside className="pw-sidebar"><div className="pw-sidebar-brand">私人工作空间<span>T24 · PRIVATE WORKSPACE</span></div><div className="pw-sidebar-owner"><LockKeyhole aria-hidden="true" />私人工作空间 · 仅本人</div><nav aria-label="私人工作空间"><button type="button" className={view === 'today' ? 'is-active' : ''} onClick={() => navigate('today')}><House aria-hidden="true" />经营简报</button><button type="button" className={view === 'manual' ? 'is-active' : ''} onClick={() => navigate('manual')}><CircleCheck aria-hidden="true" />个人事项</button><div className="pw-nav-label">我的工作</div>{(['gmail', 'google_ads'] as PrivateSourceId[]).map(id => { const Icon = SOURCE_ICONS[id]; return <button key={id} type="button" className={view === id ? 'is-active' : ''} onClick={() => navigate(id)}><Icon aria-hidden="true" />{VIEW_NAMES[id]}</button>; })}<div className="pw-nav-label">私人资金</div><button type="button" className={view === 'funds' ? 'is-active' : ''} onClick={() => navigate('funds')}><Landmark aria-hidden="true" />资金总览</button>{(['bofa_bank', 'stripe'] as PrivateSourceId[]).map(id => { const Icon = SOURCE_ICONS[id]; return <button key={id} type="button" className={view === id ? 'is-active' : ''} onClick={() => navigate(id)}><Icon aria-hidden="true" />{VIEW_NAMES[id]}</button>; })}<button type="button" className={view === 'connections' ? 'is-active' : ''} onClick={() => navigate('connections')}><Plug aria-hidden="true" />工作接入</button></nav><Link className="pw-back-crm" to="/apps" onClick={returnToCrm}><ArrowUpRight aria-hidden="true" />返回客户系统</Link></aside>
    <div className="pw-workarea"><header className="pw-mobile-header">{view !== 'today' && <button type="button" className="pw-private-back" onClick={backWithinPrivate} disabled={Boolean(busy)} aria-label={backLabel}><ArrowLeft aria-hidden="true" /><span>{backLabel}</span></button>}<strong>私人空间</strong><span><LockKeyhole aria-hidden="true" />仅本人</span></header><header className="pw-page-header"><div><div className="pw-page-context">{view !== 'today' && <button type="button" className="pw-private-back pw-desktop-back" disabled={Boolean(busy)} onClick={backWithinPrivate}><ArrowLeft aria-hidden="true" />{backLabel}</button>}<p className="pw-eyebrow">私人工作空间 · 仅本人</p></div><h1>{view === 'today' ? '今天，先看重点' : VIEW_NAMES[view]}</h1><p className="pw-date">{dateLabel}</p></div><button type="button" className="pw-button pw-refresh" disabled={loading || Boolean(busy)} onClick={() => void refreshAfterWrite()} aria-label="重新读取工作空间"><RefreshCw aria-hidden="true" /><span>刷新</span></button></header>
      <main className="pw-main" aria-busy={loading}>{callbackNotice}{bankReturnNotice}{access === 'denied' ? <Empty title="此空间仅对本人开放" detail="当前账号没有查看私人工作内容的权限。" action={<Link className="pw-button" to="/apps">返回 CRM</Link>} /> : loading || access === 'checking' ? <div className="pw-load" role="status"><LoaderCircle aria-hidden="true" />正在读取私人工作空间…</div> : access === 'error' || error ? <div className="pw-load pw-error" role="alert"><h2>暂时无法读取工作空间</h2><p>{error}</p><button type="button" className="pw-button" onClick={() => void loadWorkspace()}>重新读取</button></div> : renderContent()}{notice && <p className="pw-notice" role="status" aria-live="polite">{notice}</p>}</main>
      {access === 'allowed' && <nav className="pw-bottom-nav" aria-label="手机版工作空间">{([{ view: 'today', label: '简报', Icon: House }, { view: 'manual', label: '事项', Icon: CircleCheck }, { view: 'gmail', label: '邮件', Icon: Mail }, { view: 'funds', label: '资金', Icon: Landmark }, { view: 'connections', label: '更多', Icon: Ellipsis }] as const).map(entry => { const active = view === entry.view || entry.view === 'funds' && ['stripe', 'bofa', 'bofa_bank'].includes(view); return <button type="button" key={entry.view} aria-current={active ? 'page' : undefined} className={active ? 'is-active' : ''} onClick={() => navigate(entry.view)}><entry.Icon aria-hidden="true" /><span>{entry.label}</span></button>; })}</nav>}
    </div>

    <Dialog open={preferencesOpen && access === 'allowed'} onOpenChange={open => { if (!open) closePreferences(); }}><DialogContent className="pw-surface pw-dialog pw-preferences-dialog"><DialogHeader><DialogTitle>邮件关注设置</DialogTitle><DialogDescription>按标题、发件人和邮件摘要筛选，完整内容仍在 Gmail 查看。</DialogDescription></DialogHeader>{preferencesLoading ? <div className="pw-load" role="status"><LoaderCircle aria-hidden="true" />正在读取关注设置…</div> : <form className="pw-form" onSubmit={savePreferences}><fieldset disabled={Boolean(busy) || !preferencesReady}><legend>关注哪些工作</legend><div className="pw-mail-topics">{(Object.keys(MAIL_TOPICS) as PrivateMailTopic[]).map(topic => <label key={topic} className="pw-mail-topic"><input type="checkbox" checked={preferencesForm.topics.includes(topic)} onChange={event => setPreferencesForm(previous => ({ ...previous, topics: event.target.checked ? [...previous.topics, topic] : previous.topics.filter(value => value !== topic) }))} /><span>{MAIL_TOPICS[topic]}</span></label>)}</div><label>关注的发件人<textarea rows={3} placeholder="name@example.com 或 example.com，每行一个" value={preferencesForm.watch_senders} onChange={event => setPreferencesForm(previous => ({ ...previous, watch_senders: event.target.value }))} /></label><label>关注的关键词<textarea rows={2} placeholder="例如：争议、客户名、项目名，每行一个" value={preferencesForm.watch_keywords} onChange={event => setPreferencesForm(previous => ({ ...previous, watch_keywords: event.target.value }))} /></label><details className="pw-mail-muted-setting"><summary>低优先发件人（可选）<ChevronRight aria-hidden="true" /></summary><label>这些发件人的普通邮件放到低优先<textarea rows={2} placeholder="完整邮箱或域名，每行一个" value={preferencesForm.muted_senders} onChange={event => setPreferencesForm(previous => ({ ...previous, muted_senders: event.target.value }))} /></label></details></fieldset><p className="pw-preferences-note">资金或安全异常保留待核实；关注发件人不会认证其身份。</p>{preferencesError && <p className="pw-form-error" role="alert">{preferencesError}</p>}<div className="pw-form-actions"><button type="button" className="pw-button" disabled={Boolean(busy)} onClick={closePreferences}>取消</button>{!preferencesReady ? <button type="button" className="pw-button" onClick={() => void openPreferences()}>重新读取</button> : <button type="submit" className="pw-button pw-button-primary" disabled={Boolean(busy)}>{busy === 'save-preferences' ? '正在保存…' : '保存关注设置'}</button>}</div></form>}</DialogContent></Dialog>

    <Sheet open={Boolean(selected) && params.get('item') === selected?.id && access === 'allowed'} onOpenChange={open => { if (!open && !busy) closePrivateLayer(); }}><SheetContent className="pw-surface pw-detail-sheet" overlayClassName="pw-sheet-overlay"><button type="button" className="pw-private-back pw-detail-back" disabled={Boolean(busy)} onClick={closePrivateLayer}><ArrowLeft aria-hidden="true" />返回{VIEW_NAMES[view]}</button><SheetHeader className="pw-detail-heading"><SheetTitle>{selected ? itemDisplayTitle(selected) : '事项详情'}</SheetTitle><SheetDescription>{selected ? SOURCE_NAMES[selected.source_id] : ''} · 仅本人可见</SheetDescription></SheetHeader>{selected && (selected.source_id === 'google_ads' ? <><PrivateAdsDetail now={adsNow} item={selected} source={sourceById.get('google_ads')} /><div className="pw-item-actions"><button type="button" className="pw-button" disabled={Boolean(busy)} onClick={() => openItemTask(selected)}><Plus aria-hidden="true" />加入个人事项</button></div></> : <div className="pw-detail-body"><div className="pw-detail-meta"><span>{actionLabel(selected)}</span>{selected.due_at && <span>{selected.source_id === 'stripe' && selected.kind === 'payout' ? '来源预计日期' : '截止'}：{timeLabel(selected.due_at)}</span>}{selected.occurred_at && <span>来源时间：{timeLabel(selected.occurred_at)}</span>}</div>{selected.source_id === 'gmail' && smartMailEnabled ? <PrivateMailBrief key={selected.id} item={selected} busy={busy === `mail-brief-${selected.id}`} loading={mailCapabilitiesLoading} configured={smartMailConfigured} notice={mailBriefNotice?.id === selected.id ? mailBriefNotice.message : mailCapabilitiesNotice || (!smartMailConfigured && !mailCapabilitiesLoading ? privateMailBriefNotice(mailCapabilities?.smart_brief?.code || 'not_configured') : '')} onOrganize={() => void organizeMail(selected)} /> : selected.source_id === 'gmail' ? <PrivateMailContent key={selected.id} item={selected} previewBusy={translationBusy && translationAttemptedIds.current.has(selected.id)} busy={busy === `translate-body-${selected.id}`} unavailable={!legacyTranslationEnabled || translationUnavailable} notice={bodyTranslationNotice?.id === selected.id ? bodyTranslationNotice.message : translationUnavailable ? '中文翻译尚未开通' : translationLimited ? privateMailTranslationNotice('limit_reached') : ''} onTranslateBody={() => void translateBody(selected)} /> : !['stripe', 'bofa_bank'].includes(selected.source_id) && selected.summary && <p className="pw-detail-summary">{selected.summary}</p>}{renderMailDetail(selected)}{selected.source_id === 'bofa_bank' && <PrivateBankDetail item={selected} source={sourceById.get('bofa_bank')} now={adsNow} />}{selected.source_id === 'stripe' && <StripeRecordDetails item={selected} source={sourceById.get('stripe')} now={adsNow} />}{!['stripe', 'bofa_bank'].includes(selected.source_id) && selected.amount_minor !== null && selected.currency && <div className="pw-detail-amount"><span>来源记录金额</span><strong>{formatPrivateAmount(selected.amount_minor, selected.currency, selected.source_id)}</strong></div>}{!['manual', 'stripe', 'bofa_bank'].includes(selected.source_id) && <div className="pw-provider-state"><span>来源状态 · 仅查看</span><strong>{providerState(selected)}</strong></div>}{selected.source_id === 'bofa' && <p className="pw-finance-note">邮件提醒不会确认银行入账，请核对实际流水。</p>}{!['stripe', 'bofa_bank'].includes(selected.source_id) && <ItemEvidence item={selected} />}{safeSelectedUrl && selected.source_id !== 'bofa_bank' && <a className="pw-button pw-source-link" href={safeSelectedUrl} target="_blank" rel="noopener noreferrer">{selected.source_id === 'gmail' ? '在 Gmail 查看完整邮件' : selected.source_id === 'bofa' ? '查看原始邮件' : '查看原始来源'}<ArrowUpRight aria-hidden="true" /></a>}<div className="pw-item-actions">{selected.source_id !== 'manual' && <button type="button" className="pw-button" disabled={Boolean(busy)} onClick={() => openItemTask(selected)}><Plus aria-hidden="true" />加入个人事项</button>}<button type="button" className="pw-button pw-button-primary" disabled={Boolean(busy)} onClick={() => void updateAction(selected, { action_status: selected.action_status === 'done' || selected.action_status === 'archived' ? 'open' : 'done', snoozed_until: null })}><Check aria-hidden="true" />{selected.action_status === 'archived' ? '恢复事项' : selected.action_status === 'done' ? '恢复待处理' : bankAlert(selected) ? '标记已阅' : '标记已处理'}</button>{selected.action_status !== 'archived' && <button type="button" className="pw-button" disabled={Boolean(busy)} onClick={() => openSnooze(selected)}><Clock3 aria-hidden="true" />稍后处理</button>}{selected.action_status === 'snoozed' && <button type="button" className="pw-button" disabled={Boolean(busy)} onClick={() => void updateAction(selected, { action_status: 'open', snoozed_until: null })}><RotateCcw aria-hidden="true" />现在处理</button>}{selected.source_id === 'manual' && <><button type="button" className="pw-button" disabled={Boolean(busy)} onClick={() => openEditor(selected)}><Pencil aria-hidden="true" />编辑</button>{selected.action_status !== 'archived' && <button type="button" className="pw-button pw-button-quiet" disabled={Boolean(busy)} onClick={() => void updateAction(selected, {}, true)}><Archive aria-hidden="true" />归档</button>}</>}</div>{selected.source_id !== 'manual' && <p className="pw-detail-footnote">这些操作只记录你的工作台处理状态。</p>}</div>)}</SheetContent></Sheet>

    <Dialog open={Boolean(editor) && params.get('panel') === 'editor' && access === 'allowed'} onOpenChange={open => { if (!open) closePrivateLayer(); }}><DialogContent className="pw-surface pw-dialog"><DialogHeader><DialogTitle>{editor === 'edit' ? '编辑个人事项' : '新增个人事项'}</DialogTitle><DialogDescription>保存到你的私人工作空间，仅本人可见。</DialogDescription></DialogHeader><form className="pw-form" onSubmit={saveItem}><label>事项名称<input autoFocus value={form.title} maxLength={240} required onChange={event => setForm(previous => ({ ...previous, title: event.target.value }))} placeholder="下一件需要处理的工作" disabled={Boolean(busy)} /></label><label>备注<textarea value={form.summary} maxLength={5000} rows={4} onChange={event => setForm(previous => ({ ...previous, summary: event.target.value }))} disabled={Boolean(busy)} /></label>{editor === 'new' && <div className="pw-form-row"><label>优先级<select value={form.priority} onChange={event => setForm(previous => ({ ...previous, priority: event.target.value as PrivatePriority }))} disabled={Boolean(busy)}>{(Object.keys(PRIORITY_NAMES) as PrivatePriority[]).map(priority => <option key={priority} value={priority}>{PRIORITY_NAMES[priority]}</option>)}</select></label><label>截止时间<input type="datetime-local" value={form.due_at} onChange={event => setForm(previous => ({ ...previous, due_at: event.target.value }))} disabled={Boolean(busy)} /></label></div>}{formError && <p className="pw-form-error" role="alert">{formError}</p>}<div className="pw-form-actions"><button type="button" className="pw-button" disabled={Boolean(busy)} onClick={closePrivateLayer}>取消</button><button type="submit" className="pw-button pw-button-primary" disabled={Boolean(busy)}>{busy === 'save-item' ? '正在保存…' : '保存事项'}</button></div></form></DialogContent></Dialog>
    <Dialog open={Boolean(snoozeItem) && params.get('panel') === 'snooze' && access === 'allowed'} onOpenChange={open => { if (!open) closePrivateLayer(); }}><DialogContent className="pw-surface pw-dialog"><DialogHeader><DialogTitle>稍后处理</DialogTitle><DialogDescription>{snoozeItem?.title}</DialogDescription></DialogHeader><form className="pw-form" onSubmit={event => { event.preventDefault(); const date = new Date(snoozeAt); if (!snoozeItem || !Number.isFinite(date.getTime()) || date.getTime() <= Date.now()) { setSnoozeError('请选择未来的处理时间。'); return; } void updateAction(snoozeItem, { action_status: 'snoozed', snoozed_until: date.toISOString() }); }}><label>再次处理时间<input type="datetime-local" value={snoozeAt} required onChange={event => setSnoozeAt(event.target.value)} disabled={Boolean(busy)} /></label><p className="pw-connection-note">到期后回到工作空间的待处理事项。</p>{snoozeError && <p className="pw-form-error" role="alert">{snoozeError}</p>}<div className="pw-form-actions"><button type="button" className="pw-button" disabled={Boolean(busy)} onClick={closePrivateLayer}>取消</button><button type="submit" className="pw-button pw-button-primary" disabled={Boolean(busy)}>保存时间</button></div></form></DialogContent></Dialog>
  </div>;
}
