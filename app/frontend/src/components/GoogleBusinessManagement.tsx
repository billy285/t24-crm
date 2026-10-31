import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AlertCircle, Archive, ArrowRight, BarChart3, CalendarDays, CheckCircle2, ChevronLeft, ChevronRight, Clock3, ExternalLink, Link2, Loader2, MessageSquare, Pause, Play, RefreshCw, Search, ShieldCheck, Store, Users } from 'lucide-react';
import GoogleBusinessWorkspace from './GoogleBusinessWorkspace';
import MediaPublicationPreview from './MediaPublicationPreview';
import { PublicationImagePreview } from './MediaPublicationImage';
import { verifiedPublicationImage } from '@/lib/media-publication-images';
import { publicationEquivalent } from './media-publication';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { NativeSelect } from '@/components/ui/native-select';
import { Dialog, DialogDescription, DialogTitle, CrmFormDialogBody, CrmFormDialogContent, CrmFormDialogFooter, CrmFormDialogHeader } from '@/components/ui/dialog';
import { confirmDiscardAllChanges, useHardNavigationBlock, useUnsavedChanges } from '@/lib/use-unsaved-changes';
import { gbpActionLabels, googleBusinessApi, googlePreviewImageUrl, googlePublicUrl, type GbpActionStatus, type GbpBinding, type GbpReadyTask } from '@/lib/google-business-api';
import { mediaError, mediaErrorStatus, mediaLocalToUtc, mediaOperationsApi, mediaRequestId, mediaStatusLabels, mediaTimezones, mediaUtcToLocal, verifiedMediaTask, type MediaTask } from '@/lib/media-operations-api';
import { calendarDates, calendarTaskDate, customerPermissionUrl, gpmLifecycleLabels, gpmScheduleLabels, managementDateRange, managementToday, readCalendar, readPortfolio, readStatistics, shiftDate, verifiedAssignmentPreview, type GpmAssignmentPreview, type GpmAssignmentResult, type GpmCalendar, type GpmCalendarTask, type GpmLifecycle, type GpmMerchant, type GpmPortfolio, type GpmStatistics } from '@/lib/google-management-api';
import '@/pages/google-management.css';

type Props = { scope: string; isOwner: boolean; onOpenTask: (id: number, nextAction?: 'return') => void; onCreateTask: () => void };
type Section = 'merchants' | 'reviews' | 'calendar' | 'statistics';
type ManagementWrite = { path: string; data: Record<string, unknown>; kind: 'assignment' | 'lifecycle' | 'schedule' | 'cancel'; requestId?: string };
type Modal = { kind: 'assignment'; rows: GpmMerchant[] } | { kind: 'lifecycle'; row: GpmMerchant; action: 'pause' | 'stop' | 'resume' } | { kind: 'schedule'; task: GpmCalendarTask } | { kind: 'cancel'; task: GpmCalendarTask };
const sectionLabels: Record<Section, string> = { merchants: '商家管理', reviews: '评论待办', calendar: '内容日历', statistics: '运营统计' };
const sectionIcons = { merchants: Store, reviews: MessageSquare, calendar: CalendarDays, statistics: BarChart3 };
const pendingResult = (cause: unknown) => !mediaErrorStatus(cause) || [408, 429].includes(mediaErrorStatus(cause) || 0) || (mediaErrorStatus(cause) || 0) >= 500;
const readableTime = (value: string, timezone = 'Asia/Shanghai') => mediaUtcToLocal(value, timezone).replace('T', ' ') || '时间待核对';
const taskState = (row: GpmCalendarTask) => row.schedule ? gpmScheduleLabels[row.schedule.status] : mediaStatusLabels[row.status as keyof typeof mediaStatusLabels] || '状态待确认';
const changeLabels = { pause: '暂停代运营', stop: '停止代运营', resume: '恢复代运营' };

export default function GoogleBusinessManagement({ scope, isOwner, onOpenTask, onCreateTask }: Props) {
  const [resolvedScope, setResolvedScope] = useState(scope);
  const [section, setSection] = useState<Section>(() => typeof window !== 'undefined' && new URLSearchParams(window.location.search).get('google') === 'connected' ? 'reviews' : isOwner ? 'merchants' : 'reviews');
  const [entry, setEntry] = useState<{ key: number; bindingId?: number; customerId?: number; kind?: 'bind' | 'grants' } | undefined>();
  const [portfolio, setPortfolio] = useState<GpmPortfolio | null>(null);
  const [portfolioLoading, setPortfolioLoading] = useState(true);
  const [portfolioError, setPortfolioError] = useState('');
  const [query, setQuery] = useState('');
  const [lifecycle, setLifecycle] = useState<GpmLifecycle | 'all'>('all');
  const [page, setPage] = useState(1);
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [calendar, setCalendar] = useState<GpmCalendar | null>(null);
  const [calendarLoading, setCalendarLoading] = useState(false);
  const [calendarError, setCalendarError] = useState('');
  const [anchor, setAnchor] = useState(managementToday);
  const [calendarView, setCalendarView] = useState<'week' | 'month'>('month');
  const [selectedDay, setSelectedDay] = useState(managementToday);
  const [calendarBinding, setCalendarBinding] = useState('all');
  const [statistics, setStatistics] = useState<GpmStatistics | null>(null);
  const [statisticsLoading, setStatisticsLoading] = useState(false);
  const [statisticsError, setStatisticsError] = useState('');
  const [period, setPeriod] = useState<'today' | 'week' | 'month' | 'custom'>('month');
  const [fromDate, setFromDate] = useState(() => `${managementToday().slice(0, 7)}-01`);
  const [toDate, setToDate] = useState(managementToday);
  const [statisticsEmployee, setStatisticsEmployee] = useState('all');
  const [modal, setModal] = useState<Modal | null>(null);
  const [employee, setEmployee] = useState('');
  const [canReply, setCanReply] = useState(true);
  const [canPublish, setCanPublish] = useState(true);
  const [preview, setPreview] = useState<GpmAssignmentPreview | null>(null);
  const [assignmentResult, setAssignmentResult] = useState<GpmAssignmentResult | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [reason, setReason] = useState('');
  const [localTime, setLocalTime] = useState('');
  const [timezone, setTimezone] = useState('America/New_York');
  const [modalError, setModalError] = useState('');
  const [scheduleDetail, setScheduleDetail] = useState<MediaTask | null>(null);
  const [scheduleImage, setScheduleImage] = useState<string | null>(null);
  const [scheduleImageVerified, setScheduleImageVerified] = useState(false);
  const [scheduleDetailLoading, setScheduleDetailLoading] = useState(false);
  const [scheduleDetailError, setScheduleDetailError] = useState('');
  const [busy, setBusy] = useState(false);
  const [uncertain, setUncertain] = useState(false);
  const [notFound, setNotFound] = useState(false);
  const [notice, setNotice] = useState('');
  const scopeRef = useRef(scope); scopeRef.current = scope;
  const portfolioSeq = useRef(0), calendarSeq = useRef(0), statisticsSeq = useRef(0), scheduleDetailSeq = useRef(0);
  const durableRef = useRef(false), pendingWrite = useRef<ManagementWrite | null>(null);
  const busyRef = useRef(false), writeId = useRef(''), entryId = useRef(0), sectionRef = useRef(section); sectionRef.current = section;
  const dirty = !!modal && (confirmed || !!reason.trim() || !!localTime || !!employee);
  const guard = useUnsavedChanges(dirty), hold = useHardNavigationBlock(busy || uncertain);
  const days = useMemo(() => calendarDates(anchor, calendarView), [anchor, calendarView]);
  const selectedRows = useMemo(() => portfolio?.items.filter(row => row.binding_id !== null && selectedIds.includes(row.binding_id)) || [], [portfolio?.items, selectedIds]);
  const selectableRows = useMemo(() => portfolio?.items.filter(row => row.binding_id !== null && row.lifecycle === 'active') || [], [portfolio?.items]);
  const dayRows = useMemo(() => calendar?.items.filter(row => calendarTaskDate(row) === selectedDay) || [], [calendar?.items, selectedDay]);
  const dayMap = useMemo(() => { const map = new Map<string, GpmCalendarTask[]>(); for (const row of calendar?.items || []) { const key = calendarTaskDate(row); map.set(key, [...(map.get(key) || []), row]); } return map; }, [calendar?.items]);

  const loadPortfolio = useCallback(async () => {
    if (!isOwner) return;
    const seq = ++portfolioSeq.current, identity = scope;
    setPortfolioLoading(true); setPortfolioError('');
    try {
      const data = await readPortfolio(new URLSearchParams({ q: query.trim(), lifecycle, skip: String((page - 1) * 50), limit: '50' }));
      if (seq !== portfolioSeq.current || scopeRef.current !== identity) return;
      setPortfolio(data); setSelectedIds(current => current.filter(id => data.items.some(row => row.binding_id === id && row.lifecycle === 'active')));
    } catch (cause) { if (seq === portfolioSeq.current && scopeRef.current === identity) { setPortfolio(null); setSelectedIds([]); setPortfolioError(mediaError(cause)); } }
    finally { if (seq === portfolioSeq.current && scopeRef.current === identity) setPortfolioLoading(false); }
  }, [isOwner, lifecycle, page, query, scope]);
  const loadCalendar = useCallback(async () => {
    const seq = ++calendarSeq.current, identity = scope;
    setCalendarLoading(true); setCalendarError('');
    try {
      const range = managementDateRange(days[0], days[days.length - 1]), params = new URLSearchParams(range);
      if (calendarBinding !== 'all') params.set('binding_id', calendarBinding);
      const data = await readCalendar(params);
      if (seq === calendarSeq.current && scopeRef.current === identity) setCalendar(data);
    } catch (cause) { if (seq === calendarSeq.current && scopeRef.current === identity) { setCalendar(null); setCalendarError(mediaError(cause)); } }
    finally { if (seq === calendarSeq.current && scopeRef.current === identity) setCalendarLoading(false); }
  }, [calendarBinding, days, scope]);
  const loadStatistics = useCallback(async () => {
    if (!isOwner) return;
    const seq = ++statisticsSeq.current, identity = scope;
    setStatisticsLoading(true); setStatisticsError('');
    try {
      const params = new URLSearchParams(managementDateRange(fromDate, toDate));
      if (statisticsEmployee !== 'all') params.set('employee_id', statisticsEmployee);
      const data = await readStatistics(params);
      if (seq === statisticsSeq.current && scopeRef.current === identity) setStatistics(data);
    } catch (cause) { if (seq === statisticsSeq.current && scopeRef.current === identity) { setStatistics(null); setStatisticsError(mediaError(cause, cause instanceof Error ? cause.message : undefined)); } }
    finally { if (seq === statisticsSeq.current && scopeRef.current === identity) setStatisticsLoading(false); }
  }, [fromDate, isOwner, scope, statisticsEmployee, toDate]);
  useEffect(() => {
    portfolioSeq.current++; calendarSeq.current++; statisticsSeq.current++; scheduleDetailSeq.current++;
    setPortfolio(null); setSelectedIds([]); setCalendar(null); setStatistics(null); setModal(null); setPreview(null); setAssignmentResult(null);
    setScheduleDetail(null); setScheduleImage(null); setScheduleImageVerified(false); setScheduleDetailLoading(false); setScheduleDetailError('');
    setNotice(''); setUncertain(false); setNotFound(false); pendingWrite.current = null; durableRef.current = false; setResolvedScope(scope); busyRef.current = false; setBusy(false); writeId.current = ''; guard.markSaved(); hold.release();
    setSection(isOwner && !new URLSearchParams(window.location.search).has('google') ? 'merchants' : 'reviews');
    return () => { portfolioSeq.current++; calendarSeq.current++; statisticsSeq.current++; scheduleDetailSeq.current++; };
  }, [scope, isOwner]);
  useEffect(() => { if (isOwner && section !== 'reviews') void loadPortfolio(); }, [isOwner, section, loadPortfolio]);
  useEffect(() => { if (section === 'calendar') void loadCalendar(); }, [section, loadCalendar]);
  useEffect(() => { if (section === 'statistics') void loadStatistics(); }, [section, loadStatistics]);
  function chooseSection(next: Section) { if (next === section || busyRef.current || uncertain || !confirmDiscardAllChanges()) return; guard.markSaved(); setModal(null); setPreview(null); setModalError(''); if (next === 'reviews') setEntry(undefined); setSection(next); }
  function openGoogle(row?: GpmMerchant, kind?: 'bind' | 'grants') {
    if (busyRef.current || uncertain || !confirmDiscardAllChanges()) return;
    setEntry({ key: ++entryId.current, ...(row?.binding_id ? { bindingId: row.binding_id } : {}), ...(row ? { customerId: row.customer_id } : {}), ...(kind ? { kind } : {}) });
    setSection('reviews');
  }
  function open(next: Modal) {
    if (busyRef.current || uncertain) return;
    scheduleDetailSeq.current++; setScheduleDetail(null); setScheduleImage(null); setScheduleImageVerified(false); setScheduleDetailLoading(false); setScheduleDetailError('');
    setModal(next); setModalError(''); setConfirmed(false); setReason(''); setEmployee(''); setCanReply(true); setCanPublish(true); setPreview(null); setAssignmentResult(null); setLocalTime('');
    setTimezone(next.kind === 'schedule' ? next.task.timezone : 'America/New_York'); writeId.current = mediaRequestId();
    if (next.kind === 'schedule') void loadScheduleDetail(next.task);
  }
  async function loadScheduleDetail(task: GpmCalendarTask) {
    const seq = ++scheduleDetailSeq.current, identity = scope;
    setScheduleDetail(null); setScheduleImage(null); setScheduleImageVerified(false); setScheduleDetailLoading(true); setScheduleDetailError(''); setConfirmed(false);
    try {
      const detail = verifiedMediaTask(await mediaOperationsApi<MediaTask>(`/${task.task_id}`), task.task_id);
      if (detail.customer_id !== task.customer_id || detail.revision !== task.revision || detail.status !== 'ready' || detail.platform !== 'google_business') throw new Error('已审核内容或归属已变化，请取消并刷新日历后重新安排。');
      if (typeof detail.content !== 'string' || !detail.content.trim()) throw new Error('已审核正文为空，不能确认排期。请先核对原任务。');
      let image: string | null = null;
      if (detail.material_id) {
        const ready = await googleBusinessApi<{ items: GbpReadyTask[] }>(`/bindings/${task.binding_id}/ready-tasks`);
        const item = ready?.items?.find(row => row.id === task.task_id);
        if (!item || item.revision !== detail.revision || item.content !== detail.content || !publicationEquivalent(item.publication, detail.publication) || item.material_id !== detail.material_id || item.publish_blocked_reason || !item.has_public_image) throw new Error('已审核图片或发布版本暂无法核对，请取消并刷新日历后重新安排。');
        if (detail.image_version_id) {
          if (!detail.publication_image || !item.publication_image || item.image_version_id !== detail.image_version_id || item.image_sha256 !== detail.publication_image.image_sha256 || item.publication_image.id !== detail.publication_image.id) throw new Error('固定配图与当前审核版本不一致，请重新读取任务。');
          verifiedPublicationImage(detail.publication_image,detail.customer_id,detail.material_id);
        } else {
          image = googlePreviewImageUrl(item.preview_image_url);
          if (!image) throw new Error('已审核图片地址无法安全预览，请先核对原任务素材。');
        }
      }
      if (seq !== scheduleDetailSeq.current || scopeRef.current !== identity) return;
      setScheduleDetail(detail); setScheduleImage(image);
    } catch (cause) {
      if (seq === scheduleDetailSeq.current && scopeRef.current === identity) setScheduleDetailError(mediaError(cause, cause instanceof Error ? cause.message : '已审核正文暂时无法读取，请重试后核对。'));
    } finally { if (seq === scheduleDetailSeq.current && scopeRef.current === identity) setScheduleDetailLoading(false); }
  }
  function close() { if (busyRef.current || uncertain || !guard.confirmDiscard()) return; scheduleDetailSeq.current++; guard.markSaved(); setModal(null); setModalError(''); setPreview(null); setAssignmentResult(null); }
  function lock() { busyRef.current = true; setBusy(true); hold.lock(); }
  function unlock() { busyRef.current = false; setBusy(false); if (!durableRef.current) hold.release(); }
  async function assignmentPreview() {
    if (modal?.kind !== 'assignment' || busyRef.current || !employee || !(canReply || canPublish)) return;
    const identity = scope; lock(); setModalError(''); setConfirmed(false);
    try {
      const data = verifiedAssignmentPreview(await googleBusinessApi<GpmAssignmentPreview>('/assignments/preview', 'POST', { binding_ids: modal.rows.map(row => row.binding_id), employee_id: Number(employee), can_reply: canReply, can_publish: canPublish }));
      if (scopeRef.current === identity) setPreview(data);
    } catch (cause) { if (scopeRef.current === identity) { setPreview(null); setModalError(mediaError(cause)); } }
    finally { if (scopeRef.current === identity) unlock(); }
  }
  function makeWrite(): ManagementWrite {
    if (!modal) throw new Error('请重新打开要处理的项目。');
    if (modal.kind === 'assignment') {
      if (!preview || !preview.eligible_count || Date.parse(preview.expires_at) <= Date.now()) throw new Error('权限预览已过期，请重新预览。');
      return { kind: 'assignment', path: '/assignments/apply', requestId: writeId.current, data: { confirmed: true, request_id: writeId.current, preview_id: preview.preview_id } };
    }
    if (modal.kind === 'lifecycle') return { kind: 'lifecycle', path: `/bindings/${modal.row.binding_id}/lifecycle`, requestId: writeId.current, data: { confirmed: true, request_id: writeId.current, expected_revision: modal.row.revision, action: modal.action, reason: reason.trim() } };
    if (modal.kind === 'schedule') {
      if (!modal.task.binding_id) throw new Error('请先绑定此客户的 Google 门店。');
      if (scheduleDetail?.image_version_id && !scheduleImageVerified) throw new Error('请先成功读取并核对固定配图，再确认排期。');
      if (scheduleDetailLoading || scheduleDetailError || !scheduleDetail || scheduleDetail.id !== modal.task.task_id || scheduleDetail.revision !== modal.task.revision) throw new Error('请先重新读取并核对当前已审核正文，版本一致后才能安排。');
      return { kind: 'schedule', path: `/bindings/${modal.task.binding_id}/schedules`, requestId: writeId.current, data: { confirmed: true, request_id: writeId.current, task_id: modal.task.task_id, expected_revision: modal.task.revision, planned_at: mediaLocalToUtc(localTime, timezone), timezone } };
    }
    if (!modal.task.schedule) throw new Error('原排期已不可用，请重新读取。');
    return { kind: 'cancel', path: `/schedules/${modal.task.schedule.id}/cancel`, data: { confirmed: true, expected_revision: modal.task.schedule.revision } };
  }
  async function acceptResult(value: unknown, request: ManagementWrite) {
    if (request.kind === 'assignment') {
      const result = value as GpmAssignmentResult;
      if (!result || result.request_id !== request.requestId || !Array.isArray(result.items) || !Number.isSafeInteger(result.applied_count) || !Number.isSafeInteger(result.skipped_count)) throw new Error('分配结果返回不完整，请按原编号查询。');
      setAssignmentResult(result); setNotice(`已分配 ${result.applied_count} 家${result.skipped_count ? `，${result.skipped_count} 家需处理` : ''}。`); setSelectedIds([]);
    } else {
      const result = value as { id: number; revision: number };
      if (!result || !Number.isSafeInteger(result.id) || result.id < 1 || !Number.isSafeInteger(result.revision) || result.revision < 1) throw new Error('保存结果返回不完整，请按原编号查询。');
      setModal(null); setNotice(request.kind === 'schedule' ? '排期已保存。请留意自动发布启用状态。' : request.kind === 'cancel' ? '已取消尚未提交的排期。' : '商家管理状态已更新。');
    }
    pendingWrite.current = null; durableRef.current = false; setUncertain(false); setNotFound(false); setConfirmed(false); setModalError(''); guard.markSaved();
    await Promise.all([loadPortfolio(), ...(sectionRef.current === 'calendar' ? [loadCalendar()] : [])]);
  }
  async function mutate(request: ManagementWrite) {
    if (busyRef.current) return;
    const identity = scope; pendingWrite.current = request; lock(); setModalError('');
    try {
      const result = await googleBusinessApi(request.path, 'POST', request.data);
      if (scopeRef.current === identity) await acceptResult(result, request);
    } catch (cause) {
      if (scopeRef.current !== identity) return;
      if (pendingResult(cause)) { durableRef.current = true; setUncertain(true); hold.lock(); setModalError('保存结果待确认。请先查询原请求，确认前不会重复提交。'); }
      else { pendingWrite.current = null; durableRef.current = false; setUncertain(false); setModalError(mediaError(cause, cause instanceof Error ? cause.message : undefined)); if (mediaErrorStatus(cause) === 409) { setPreview(null); setConfirmed(false); } }
    } finally { if (scopeRef.current === identity) unlock(); }
  }
  async function submit() {
    if (!modal || !confirmed || busyRef.current || uncertain) return;
    try { await mutate(makeWrite()); } catch (cause) { setModalError(cause instanceof Error ? cause.message : '请核对后重试。'); }
  }
  async function refreshUncertain() {
    const request = pendingWrite.current;
    if (!request || busyRef.current) return;
    const identity = scope; lock(); setModalError('');
    try {
      if (request.requestId) {
        const receipt = await googleBusinessApi<{ request_id: string; kind: string; result: unknown }>(`/management-requests/${encodeURIComponent(request.requestId)}`);
        if (!receipt || receipt.request_id !== request.requestId || typeof receipt.kind !== 'string') throw new Error('原请求查询返回不完整。');
        if (scopeRef.current === identity) await acceptResult(receipt.result, request);
      } else {
        const range = managementDateRange(days[0], days[days.length - 1]);
        const latest = await readCalendar(new URLSearchParams(range));
        const target = modal?.kind === 'cancel' ? latest.items.find(row => row.schedule?.id === modal.task.schedule?.id)?.schedule : null;
        if (!target || target.status !== 'cancelled') { setNotFound(true); setModalError('尚未读到已取消结果，可继续查询，或明确重试原取消请求。'); return; }
        if (scopeRef.current === identity) await acceptResult(target, request);
      }
    } catch (cause) {
      if (scopeRef.current !== identity) return;
      setNotFound(mediaErrorStatus(cause) === 404);
      setModalError(mediaErrorStatus(cause) === 404 ? '尚未找到这个请求。可继续查询，或以原编号明确重新提交。' : mediaError(cause, '仍无法确认结果，请继续查询原请求。'));
    } finally { if (scopeRef.current === identity) unlock(); }
  }
  function choosePeriod(next: typeof period) {
    const today = managementToday(); setPeriod(next);
    if (next === 'today') { setFromDate(today); setToDate(today); }
    if (next === 'week') { setFromDate(calendarDates(today, 'week')[0]); setToDate(today); }
    if (next === 'month') { setFromDate(`${today.slice(0, 7)}-01`); setToDate(today); }
  }
  function stepCalendar(direction: number) {
    if (calendarView === 'week') { const next = shiftDate(anchor, direction * 7); setAnchor(next); setSelectedDay(next); }
    else { const date = new Date(`${anchor.slice(0, 7)}-01T12:00:00Z`); date.setUTCMonth(date.getUTCMonth() + direction); const next = date.toISOString().slice(0, 10); setAnchor(next); setSelectedDay(next); }
  }
  const sections = isOwner ? (['merchants', 'reviews', 'calendar', 'statistics'] as Section[]) : (['reviews', 'calendar'] as Section[]);
  const modalTitle = modal?.kind === 'assignment' ? assignmentResult ? '分配结果' : preview ? '核对权限变更' : '批量分配运营' : modal?.kind === 'lifecycle' ? changeLabels[modal.action] : modal?.kind === 'schedule' ? '安排发布' : '取消排期';
  const checkboxLabel = modal?.kind === 'assignment' ? '我已核对本次商家、运营及操作权限，确认仅应用以上可分配项目。' : modal?.kind === 'schedule' ? '我已核对商家、已审核正文、帖子设置和两个时区的发布时间，确认保存本次排期。' : modal?.kind === 'cancel' ? '我确认取消这项尚未提交到 Google 的排期。' : modal?.kind === 'lifecycle' && modal.action === 'resume' ? '我已核对合作状态与门店归属，确认恢复后再重新分配运营权限。' : '我确认撤销此商家的 Google 员工权限，并停止尚未发布的排期。';
  const scheduleBeijing = useMemo(() => { if (!localTime) return ''; try { return readableTime(mediaLocalToUtc(localTime, timezone)); } catch (cause) { return cause instanceof Error ? cause.message : ''; } }, [localTime, timezone]);
  const scheduleReady = modal?.kind === 'schedule' && !scheduleDetailLoading && !scheduleDetailError && scheduleDetail?.id === modal.task.task_id && scheduleDetail.revision === modal.task.revision && (!scheduleDetail.image_version_id || scheduleImageVerified);
  const canSubmit = !busy && !uncertain && confirmed && (modal?.kind !== 'assignment' || !!preview?.eligible_count && Date.parse(preview.expires_at) > Date.now()) && (modal?.kind !== 'schedule' || !!localTime && scheduleReady) && (modal?.kind !== 'lifecycle' || reason.trim().length >= 3);

  if (resolvedScope !== scope) return <Loading label="正在确认当前账号的管理范围…"/>;
  return <section className={`gpm-workspace gpm-section-${section}`} aria-label="代运营商家管理工作区">
    <nav className="gpm-nav" aria-label="代运营管理功能">{sections.map(key => { const Icon = sectionIcons[key]; return <button key={key} className={section === key ? 'active' : ''} aria-current={section === key ? 'page' : undefined} onClick={() => chooseSection(key)}><Icon aria-hidden="true"/>{sectionLabels[key]}</button>; })}</nav>
    <p className="sr-only" role="status" aria-live="polite">{notice}</p>
    {notice && <div className="gpm-notice"><CheckCircle2 aria-hidden="true"/>{notice}</div>}
    {section === 'reviews' ? <GoogleBusinessWorkspace scope={scope} isOwner={isOwner} onOpenTask={onOpenTask} entry={entry}/> : <>
      <header className="gpm-header"><div><h2>{sectionLabels[section]}</h2><p>{section === 'merchants' ? '核对合作商家，安排一位主要运营，按门店开放操作。' : section === 'calendar' ? '按北京时间编排工作，同时核对门店当地发布时间。' : '按确认结果查看工作量，草稿和公开完成分别统计。'}</p></div><div className="gpm-header-tools"><Button variant="outline" aria-label={`刷新${sectionLabels[section]}`} onClick={() => { if (section === 'merchants') void loadPortfolio(); else if (section === 'calendar') void loadCalendar(); else void loadStatistics(); }} disabled={busy || uncertain || section === 'merchants' && portfolioLoading || section === 'calendar' && calendarLoading || section === 'statistics' && statisticsLoading}><RefreshCw aria-hidden="true"/><span className="gpm-refresh-text">刷新</span></Button>{section === 'merchants' ? <Button onClick={() => openGoogle(undefined, 'bind')}><Link2 aria-hidden="true"/>绑定商家</Button> : section === 'calendar' ? <Button onClick={onCreateTask}><CalendarDays aria-hidden="true"/>准备内容</Button> : null}</div></header>
      {section === 'merchants' && <>
        <div className="gpm-overview" aria-label="合作商家概况">{(['unbound', 'active', 'paused', 'stopped'] as GpmLifecycle[]).map(key => <button key={key} className={`gpm-metric ${lifecycle === key ? 'selected' : ''}`} onClick={() => { setLifecycle(value => value === key ? 'all' : key); setPage(1); setSelectedIds([]); }}><span>{gpmLifecycleLabels[key]}</span><strong>{portfolioLoading ? '—' : portfolio?.summary[key] ?? '—'}</strong><small>{key === 'unbound' ? '核对 Google 门店' : key === 'active' ? '可分配运营' : key === 'paused' ? '恢复后重新授权' : '保留历史记录'}</small></button>)}</div>
        <div className="gpm-scope"><ShieldCheck aria-hidden="true"/><span>仅老板可分配。员工需要已有的客户交付协作权限；财务和私人资料不随 Google 操作开放。</span></div>
        <div className="gpm-panel"><div className="gpm-toolbar"><label className="gpm-search"><Search aria-hidden="true"/><Input aria-label="搜索合作商家" placeholder="搜索商家名称" value={query} onChange={event => { setQuery(event.target.value); setPage(1); setSelectedIds([]); }}/></label><NativeSelect aria-label="筛选商家管理状态" className="gpm-filter" value={lifecycle} onChange={value => { setLifecycle(value as typeof lifecycle); setPage(1); setSelectedIds([]); }} options={[{ value: 'all', label: '全部管理状态' }, ...Object.entries(gpmLifecycleLabels).map(([value, label]) => ({ value, label }))]}/></div>
          {portfolioError ? <ErrorPanel message={portfolioError} onRetry={() => void loadPortfolio()}/> : portfolioLoading ? <Loading label="正在读取商家合作状态和分配范围…"/> : !portfolio?.items.length ? <Empty title="当前范围没有商家" text="调整筛选后查看，或先在客户中心确认合作客户。"/> : <>
            <div className="gpm-merchants-head"><label className="gpm-merchant-check gpm-head-select"><input type="checkbox" aria-label="选择本页可分配商家" checked={!!selectableRows.length && selectableRows.every(row => selectedIds.includes(row.binding_id!))} onChange={event => setSelectedIds(event.target.checked ? selectableRows.map(row => row.binding_id!) : [])}/><span className="gpm-stat-label">选择本页可分配商家</span></label><span>商家</span><span className="gpm-merchant-industry">行业 / 地区</span><span>状态</span><span>主要运营</span><span style={{ textAlign: 'right' }}>操作</span></div>
            {portfolio.items.map(row => <article className={`gpm-merchant ${row.binding_id && selectedIds.includes(row.binding_id) ? 'is-selected' : ''}`} key={row.customer_id}><label className="gpm-merchant-check"><input type="checkbox" aria-label={`选择 ${row.customer_name}`} disabled={!row.binding_id || row.lifecycle !== 'active'} checked={!!row.binding_id && selectedIds.includes(row.binding_id)} onChange={event => { const checked = event.target.checked; setSelectedIds(ids => row.binding_id ? checked ? [...new Set([...ids, row.binding_id])] : ids.filter(id => id !== row.binding_id) : ids); }}/></label><div className="gpm-merchant-name"><strong>{row.customer_name}</strong><small>{row.cooperation_eligible ? row.binding_id ? row.connection_needs_reconnect ? 'Google 需重新授权' : 'Google 已绑定' : '待核对门店后绑定' : row.cooperation_reason || '合作状态需核对'}</small></div><div className="gpm-merchant-meta gpm-merchant-industry">{row.industry || '行业待补充'}<small>{row.region || '地区待补充'}</small></div><div className="gpm-merchant-status"><span className={`gpm-pill gpm-pill-${row.lifecycle === 'active' && !row.primary_operator_id ? 'unassigned' : row.lifecycle}`}>{row.lifecycle === 'active' && !row.primary_operator_id ? '待分配' : gpmLifecycleLabels[row.lifecycle]}</span></div><div className="gpm-merchant-meta gpm-merchant-owner">{row.primary_operator_name || '尚未分配'}<small>{row.primary_operator_id ? '主要运营' : row.lifecycle === 'active' ? '勾选后可批量分配' : '恢复后重新分配'}</small></div><div className="gpm-merchant-actions">{!row.binding_id ? <Button variant="outline" disabled={!row.cooperation_eligible} onClick={() => openGoogle(row, 'bind')}>绑定门店</Button> : row.lifecycle === 'active' ? <><Button variant="ghost" onClick={() => openGoogle(row)}>评论<ArrowRight aria-hidden="true"/></Button><Button variant="outline" onClick={() => open({ kind: 'assignment', rows: [row] })}>分配</Button><Button variant="ghost" title="暂停代运营" aria-label={`暂停 ${row.customer_name}`} onClick={() => open({ kind: 'lifecycle', row, action: 'pause' })}><Pause aria-hidden="true"/></Button><Button className="gpm-stop-button" variant="ghost" title="停止代运营" aria-label={`停止 ${row.customer_name}`} onClick={() => open({ kind: 'lifecycle', row, action: 'stop' })}><Archive aria-hidden="true"/></Button></> : <><Button variant="outline" disabled={!row.cooperation_eligible} onClick={() => open({ kind: 'lifecycle', row, action: 'resume' })}><Play aria-hidden="true"/>恢复</Button>{row.lifecycle === 'paused' && <Button variant="ghost" onClick={() => open({ kind: 'lifecycle', row, action: 'stop' })}>结束合作</Button>}</>}</div></article>)}
            <div className="gpm-bulkbar"><span>已选 <strong>{selectedIds.length}</strong> 家<span className="gpm-context"> · 仅本页已绑定商家</span></span><div>{selectedIds.length > 0 && <Button variant="ghost" onClick={() => setSelectedIds([])}>取消选择</Button>}<Button disabled={!selectedRows.length || busy || uncertain} onClick={() => open({ kind: 'assignment', rows: selectedRows })}><Users aria-hidden="true"/>批量分配</Button></div></div>
            <footer className="gpm-bulkbar"><span>共 {portfolio.total} 家 · 第 {page} / {Math.max(1, Math.ceil(portfolio.total / 50))} 页</span><div><Button variant="outline" disabled={page === 1} aria-label="上一页商家" onClick={() => { setPage(value => value - 1); setSelectedIds([]); }}><ChevronLeft aria-hidden="true"/></Button><Button variant="outline" disabled={page * 50 >= portfolio.total} aria-label="下一页商家" onClick={() => { setPage(value => value + 1); setSelectedIds([]); }}><ChevronRight aria-hidden="true"/></Button></div></footer>
          </>}
        </div>
      </>}
      {section === 'calendar' && <>
        {calendar && !calendar.scheduler.enabled && <div className="gpm-alert"><Clock3 aria-hidden="true"/><div><strong>自动发布尚未启用</strong><p>现在可保存排期；自动发布启用后只处理届时有效的新排期，历史逾期内容不会自动补发。任务截止时间不等于发布时间。</p></div></div>}
        <div className="gpm-panel"><div className="gpm-calendar-top"><div className="gpm-calendar-controls"><Button variant="ghost" aria-label="上一段日历" onClick={() => stepCalendar(-1)}><ChevronLeft aria-hidden="true"/></Button><strong>{calendarView === 'month' ? `${anchor.slice(0, 4)} 年 ${Number(anchor.slice(5, 7))} 月` : `${days[0].slice(5)} — ${days[6].slice(5)}`}</strong><Button variant="ghost" aria-label="下一段日历" onClick={() => stepCalendar(1)}><ChevronRight aria-hidden="true"/></Button><Button variant="ghost" onClick={() => { setAnchor(managementToday()); setSelectedDay(managementToday()); }}>今天</Button></div><div className="gpm-view-toggle" role="group" aria-label="日历显示方式"><button className={calendarView === 'week' ? 'active' : ''} aria-pressed={calendarView === 'week'} onClick={() => setCalendarView('week')}>周</button><button className={calendarView === 'month' ? 'active' : ''} aria-pressed={calendarView === 'month'} onClick={() => setCalendarView('month')}>月</button></div></div>
          <div className="gpm-toolbar"><span className="gpm-context" style={{ margin: 0 }}>日历日期以北京时间显示 · 点日期查看内容</span>{isOwner && <NativeSelect aria-label="筛选日历商家" className="gpm-filter" value={calendarBinding} onChange={setCalendarBinding} options={[{ value: 'all', label: '全部授权商家' }, ...(portfolio?.items.filter(row => row.binding_id).map(row => ({ value: String(row.binding_id), label: row.customer_name })) || [])]}/>}</div>
          {calendarError ? <ErrorPanel message={calendarError} onRetry={() => void loadCalendar()}/> : calendarLoading ? <Loading label="正在读取已授权的内容计划…"/> : <><div className="gpm-calendar-grid" aria-label="内容计划日历">{['一', '二', '三', '四', '五', '六', '日'].map(day => <div className="gpm-weekday" key={day}>周{day}</div>)}{days.map(day => { const rows = dayMap.get(day) || []; return <button className={`gpm-day ${day.slice(0, 7) !== anchor.slice(0, 7) ? 'outside' : ''} ${day === selectedDay ? 'selected' : ''} ${day === managementToday() ? 'is-today' : ''}`} key={day} aria-label={`${day}，${rows.length} 项内容`} aria-pressed={day === selectedDay} onClick={() => setSelectedDay(day)}><span className="gpm-day-number">{Number(day.slice(-2))}</span>{rows.slice(0, 2).map(row => <span className={`gpm-calendar-entry ${['failed', 'unknown', 'blocked', 'missed'].includes(row.schedule?.status || '') ? 'is-failed' : ''}`} key={row.task_id}><strong>{row.customer_name}</strong>{row.title}<small>{taskState(row)}</small></span>)}{rows.length > 0 && <span className="gpm-day-count">{rows.length} 项</span>}</button>; })}</div><section className="gpm-agenda" aria-label="所选日期内容"><h3>{selectedDay} · {dayRows.length} 项内容</h3>{!dayRows.length ? <p className="gpm-context">这一天没有已授权的内容计划。可先准备内容，再安排审核和发布。</p> : dayRows.map(row => <article className="gpm-agenda-row" key={row.task_id}><div><strong>{row.customer_name} · {row.title}</strong><small>{row.assignee_name} 负责 · <span className={`gpm-pill gpm-pill-${row.schedule?.status || row.status}`}>{taskState(row)}</span></small><small>{row.schedule ? `门店时间 ${readableTime(row.schedule.planned_at, row.schedule.timezone)} · ${row.schedule.timezone}；北京时间 ${readableTime(row.schedule.planned_at)}` : `任务截止 ${readableTime(row.due_at, row.timezone)} · ${row.timezone}（尚未排期）`}</small>{row.schedule?.message && <small>{row.schedule.message}</small>}{!row.schedule && row.status === 'ready' && row.schedule_blocked_reason && <small>{row.schedule_blocked_reason}</small>}</div><Button variant="ghost" onClick={() => onOpenTask(row.task_id)}>查看内容</Button>{row.schedule && ['scheduled', 'blocked'].includes(row.schedule.status) ? <Button variant="outline" onClick={() => open({ kind: 'cancel', task: row })}>取消排期</Button> : row.status === 'ready' && row.binding_id && (!row.schedule || ['cancelled', 'missed', 'failed'].includes(row.schedule.status)) ? <Button variant="outline" disabled={row.can_schedule !== true} title={row.schedule_blocked_reason || (row.can_schedule === true ? '核对内容和时间后安排发布' : '请先确认主运营及发布权限')} onClick={() => open({ kind: 'schedule', task: row })}>安排发布</Button> : null}</article>)}</section></>}
        </div>
      </>}
      {section === 'statistics' && <>
        <div className="gpm-toolbar gpm-panel" style={{ marginBottom: 15 }}><div className="gpm-period">{(['today', 'week', 'month', 'custom'] as const).map(key => <button key={key} className={period === key ? 'active' : ''} aria-pressed={period === key} onClick={() => choosePeriod(key)}>{{ today: '今天', week: '本周', month: '本月', custom: '自定义' }[key]}</button>)}{period === 'custom' && <label><Input type="date" aria-label="统计开始日期" value={fromDate} onChange={event => setFromDate(event.target.value)}/>至<Input type="date" aria-label="统计结束日期" value={toDate} onChange={event => setToDate(event.target.value)}/></label>}<NativeSelect aria-label="筛选统计运营" value={statisticsEmployee} onChange={setStatisticsEmployee} options={[{ value: 'all', label: '全部运营' }, ...(portfolio?.assignees.map(row => ({ value: String(row.id), label: row.name })) || [])]}/></div></div>
        {statisticsError ? <div className="gpm-panel"><ErrorPanel message={statisticsError} onRetry={() => void loadStatistics()}/></div> : <><div className="gpm-overview" aria-label="运营确认结果"><Metric label="成功回复" value={statisticsLoading ? null : statistics?.totals.reply_succeeded} note="Google 已确认的回复"/><Metric label="已公开帖子" value={statisticsLoading ? null : statistics?.totals.post_succeeded} note="Google 已确认公开"/><Metric label="平台处理中" value={statisticsLoading ? null : statistics ? statistics.totals.pending + statistics.totals.accepted : null} note="尚未计入公开完成"/><Metric label="需要处理" value={statisticsLoading ? null : statistics ? statistics.totals.failed + statistics.totals.rejected + statistics.totals.unknown : null} note="失败、未通过、结果待确认"/></div><div className="gpm-scope"><ShieldCheck aria-hidden="true"/><span>仅统计 CRM 内能确认归属的操作；生成草稿、内部任务完成与 Google 公开结果分别计算。日期范围按北京时间，成功时间以首次平台确认计。</span></div><div className="gpm-panel">{statisticsLoading ? <Loading label="正在核对运营工作结果…"/> : !statistics?.employees.length ? <Empty title="此期间暂无可确认的运营操作" text="尚未发生的工作不计为完成。真实回复和发布确认后会显示在这里。"/> : <><div className="gpm-stat-head"><span>运营</span><span>成功回复</span><span>已公开帖子</span><span>处理中</span><span>待确认</span><span>失败 / 未通过</span></div>{statistics.employees.map(row => <div className="gpm-stat-row" key={row.employee_id}><strong>{row.employee_name}</strong><span><small className="gpm-stat-label">成功回复</small>{row.reply_succeeded}</span><span><small className="gpm-stat-label">已公开帖子</small>{row.post_succeeded}</span><span><small className="gpm-stat-label">处理中</small>{row.pending + row.accepted}</span><span><small className="gpm-stat-label">待确认</small>{row.unknown}</span><span><small className="gpm-stat-label">失败 / 未通过</small>{row.failed + row.rejected}</span></div>)}</>}<footer className="gpm-footer">内部内容任务：待准备 {statistics?.totals.draft ?? '—'} · 待审核 {statistics?.totals.in_review ?? '—'} · 待发布 {statistics?.totals.ready ?? '—'} · 已提交凭证 {statistics?.totals.completed ?? '—'}。{statistics?.legacy_success_time_fallback_count ? ` ${statistics.legacy_success_time_fallback_count} 条旧记录使用最后更新时间统计。` : ''}</footer></div>{!!statistics?.records?.length && <section className="gpm-panel gpm-records" aria-label="运营操作明细"><header><h3>本期操作明细</h3><span>最多展示最近 100 条，汇总按全部匹配记录计算</span></header>{statistics.records.map(row => <article key={row.id}><div><strong>{row.customer_name} · {row.kind === 'review_reply' ? '回复评论' : '发布帖子'}</strong><small>{row.actor_name} · {readableTime(row.confirmed_at || row.created_at)}（北京时间）</small>{row.content && <p>{row.content}</p>}</div><span className={`gpm-pill gpm-pill-${row.status}`}>{gbpActionLabels[row.status as GbpActionStatus] || '状态待确认'}</span>{googlePublicUrl(row.provider_url) && <a className="gpm-link" href={googlePublicUrl(row.provider_url)!} target="_blank" rel="noopener noreferrer">查看公开结果<ExternalLink aria-hidden="true"/></a>}</article>)}</section>}</>}
      </>}
    </>}
    <Dialog open={!!modal} onOpenChange={value => { if (!value) close(); }}><CrmFormDialogContent className="gpm-dialog" aria-busy={busy} onEscapeKeyDown={event => { if (busyRef.current || uncertain) event.preventDefault(); }} onPointerDownOutside={event => { if (busyRef.current || uncertain || dirty) event.preventDefault(); }}><CrmFormDialogHeader><DialogTitle>{modalTitle}</DialogTitle><DialogDescription>{modal?.kind === 'assignment' ? '仅变更本次选择的 Google 门店权限，原客户邀请与财务权限保持原样。' : modal?.kind === 'schedule' ? '以已审核内容保存明确的发布时间。' : '商家历史工作记录保留，操作结果会留下记录。'}</DialogDescription></CrmFormDialogHeader><CrmFormDialogBody>{modalError && <div className="gpm-alert" role="alert"><AlertCircle aria-hidden="true"/><div>{modalError}</div></div>}{modal?.kind === 'assignment' ? assignmentResult ? <div className="gpm-form"><div className="gpm-summary-note"><strong>已分配 {assignmentResult.applied_count} 家</strong>，{assignmentResult.skipped_count} 家未变更。请处理原因后重新预览。</div><div className="gpm-preview-list">{assignmentResult.items.map(row => <div className={`gpm-preview-row ${!row.applied ? 'blocked' : ''}`} key={row.binding_id}><div><strong>{modal.rows.find(item => item.binding_id === row.binding_id)?.customer_name || '本次门店'}</strong><p>{row.applied ? '主要运营和 Google 权限已更新' : row.reason || '未变更，请重新核对'}</p></div>{!row.applied && <a className="gpm-link" href={customerPermissionUrl(row.customer_permissions_url, modal.rows.find(item => item.binding_id === row.binding_id)?.customer_id)}>客户权限<ExternalLink aria-hidden="true"/></a>}</div>)}</div></div> : <div className="gpm-form"><div className="gpm-summary-note">本次选择 <strong>{modal.rows.length} 家商家</strong>。主要运营负责日常管理，其他已授权协作者保持原样。</div><label>主要运营<NativeSelect aria-label="批量分配主要运营" value={employee} onChange={value => { setEmployee(value); setPreview(null); setConfirmed(false); }} disabled={busy} options={[{ value: '', label: '选择负责运营' }, ...(portfolio?.assignees.map(row => ({ value: String(row.id), label: row.name })) || [])]}/></label><div className="gpm-check-options"><label className="gpm-checkbox"><input type="checkbox" checked={canReply} disabled={busy} onChange={event => { setCanReply(event.target.checked); setPreview(null); setConfirmed(false); }}/>允许回复评论</label><label className="gpm-checkbox"><input type="checkbox" checked={canPublish} disabled={busy} onChange={event => { setCanPublish(event.target.checked); setPreview(null); setConfirmed(false); }}/>允许发布已审核帖文</label></div>{preview && <><div className="gpm-summary-note">可分配 <strong>{preview.eligible_count} 家</strong> · 需处理 {preview.ineligible_count} 家。预览有效至 {readableTime(preview.expires_at)}（北京时间）。</div><div className="gpm-preview-list">{preview.items.map(row => <div className={`gpm-preview-row ${!row.eligible ? 'blocked' : ''}`} key={row.binding_id}><div><strong>{row.customer_name}</strong><p>{row.eligible ? `主要运营：${portfolio?.assignees.find(item => item.id === preview.employee_id)?.name || '已选运营'} · ${[canReply && '可回复', canPublish && '可发布'].filter(Boolean).join(' / ')}` : row.reason || '请先确认客户交付协作权限'}</p></div>{!row.eligible && <a className="gpm-link" href={customerPermissionUrl(row.customer_permissions_url, row.customer_id)}>处理权限<ExternalLink aria-hidden="true"/></a>}</div>)}</div></>}</div> : modal?.kind === 'lifecycle' ? <div className="gpm-form"><div className="gpm-summary-note"><strong>{modal.row.customer_name}</strong><br/>{modal.action === 'resume' ? '恢复后保留原门店对应关系。员工权限需要你重新分配，已取消的排期不会自动恢复。' : '此门店的员工 Google 操作权限将撤销，未提交的排期将停止。客户资料、财务及历史公开内容保持原样。'}</div><label>记录原因（至少 3 字）<Textarea aria-label="商家状态变更原因" maxLength={1000} value={reason} onChange={event => { setReason(event.target.value); setConfirmed(false); }} placeholder={modal.action === 'stop' ? '例如：本月合作结束' : modal.action === 'pause' ? '例如：暂停服务，等待客户补充资料' : '例如：已确认恢复合作'}/></label></div> : modal?.kind === 'schedule' ? <div className="gpm-form"><div className="gpm-summary-note"><strong>{modal.task.customer_name} · {modal.task.title}</strong><br/>{modal.task.assignee_name} 负责 · 已审核内容，发布前会再次核对<br/>只有门店主要运营、客户权限和已审核版本仍有效时，排期才可执行。</div><section className="gpm-schedule-content" aria-label="本次排期已审核内容">{scheduleDetailLoading ? <Loading label="正在读取当前已审核正文…"/> : scheduleDetailError ? <div className="gpm-alert" role="alert"><AlertCircle aria-hidden="true"/><div>{scheduleDetailError}<Button variant="outline" disabled={busy || uncertain} onClick={() => void loadScheduleDetail(modal.task)}>重新读取已审核内容</Button></div></div> : scheduleDetail && <><header><strong>已审核正文</strong><span>任务 #{scheduleDetail.id} · 版本 {scheduleDetail.revision}</span></header><h3>{scheduleDetail.title}</h3><p>{scheduleDetail.content}</p><MediaPublicationPreview publication={scheduleDetail.publication} timezone={scheduleDetail.timezone} heading="本次排期的帖子设置"/>{scheduleDetail.publication_image && <PublicationImagePreview scope={scope} image={scheduleDetail.publication_image} title="本次排期使用的固定配图" onStateChange={state=>{setScheduleImageVerified(state==='ready');if(state!=='ready')setConfirmed(false);}}/>}{scheduleImage && <><img src={scheduleImage} alt={scheduleDetail.material_title || "已审核配图"} loading="lazy" referrerPolicy="no-referrer" onError={() => { setScheduleDetailError("图片暂时无法预览，请核对原任务素材后重新安排。"); setConfirmed(false); }}/><small>配图：{scheduleDetail.material_title || "已审核配图"}。外部图片内容仍可能更新，请核对实际预览。</small></>}</>}</section><div className="gpm-form-two"><label>商家时区<NativeSelect aria-label="排期商家时区" value={timezone} onChange={value => { setTimezone(value); setConfirmed(false); }} options={mediaTimezones}/></label><label>商家当地发布时间<Input type="datetime-local" aria-label="商家当地发布时间" value={localTime} onChange={event => { setLocalTime(event.target.value); setConfirmed(false); }}/></label></div><div className="gpm-summary-note">北京时间：<strong>{scheduleBeijing || '选择当地时间后显示'}</strong></div>{calendar && !calendar.scheduler.enabled && <div className="gpm-alert"><Clock3 aria-hidden="true"/><div>自动发布尚未启用，本次只保存 CRM 排期。请在正式启用后重新核对执行范围。</div></div>}</div> : modal?.kind === 'cancel' ? <div className="gpm-summary-note"><strong>{modal.task.customer_name} · {modal.task.title}</strong><br/>原排期：{modal.task.schedule ? readableTime(modal.task.schedule.planned_at, modal.task.schedule.timezone) : '待确认'}<br/>取消后保留已审核内容和历史；调整时间需重新明确安排。</div> : null}{!assignmentResult && (modal?.kind !== 'assignment' || !!preview) && <label className="gpm-checkbox" style={{ marginTop: 18 }}><input type="checkbox" checked={confirmed} disabled={busy || uncertain || modal?.kind === 'schedule' && !scheduleReady} onChange={event => setConfirmed(event.target.checked)}/>{checkboxLabel}</label>}</CrmFormDialogBody><CrmFormDialogFooter>{uncertain ? <><Button variant="outline" disabled={busy} onClick={() => void refreshUncertain()}>{busy && <Loader2 className="animate-spin" aria-hidden="true"/>}查询原请求</Button>{notFound && <Button disabled={busy} onClick={() => { const request = pendingWrite.current; if (request) void mutate(request); }}>{pendingWrite.current?.requestId ? '以原编号重新提交' : '重试原取消请求'}</Button>}</> : assignmentResult ? <Button onClick={() => { guard.markSaved(); setModal(null); setAssignmentResult(null); }}>完成</Button> : <><Button variant="outline" onClick={close} disabled={busy}>取消</Button>{modal?.kind === 'assignment' && !preview ? <Button onClick={() => void assignmentPreview()} disabled={busy || !employee || !(canReply || canPublish)}>{busy ? <Loader2 className="animate-spin" aria-hidden="true"/> : <Users aria-hidden="true"/>}预览变更</Button> : <Button onClick={() => void submit()} disabled={!canSubmit}>{busy ? <Loader2 className="animate-spin" aria-hidden="true"/> : <CheckCircle2 aria-hidden="true"/>}{modal?.kind === 'assignment' ? '确认分配' : modal?.kind === 'schedule' ? '确认保存排期' : modal?.kind === 'cancel' ? '确认取消排期' : modal ? changeLabels[modal.action] : '确认'}</Button>}</>}</CrmFormDialogFooter></CrmFormDialogContent></Dialog>
  </section>;
}
function Metric({ label, value, note }: { label: string; value?: number | null; note: string }) { return <div className="gpm-metric"><span>{label}</span><strong>{value == null ? '—' : value}</strong><small>{note}</small></div>; }
function Loading({ label }: { label: string }) { return <div className="gpm-empty" role="status"><Loader2 className="animate-spin" aria-hidden="true"/><h3>{label}</h3><p>资料完整返回后再显示统计和操作范围。</p></div>; }
function Empty({ title, text }: { title: string; text: string }) { return <div className="gpm-empty"><Store aria-hidden="true"/><h3>{title}</h3><p>{text}</p></div>; }
function ErrorPanel({ message, onRetry }: { message: string; onRetry: () => void }) { return <div className="gpm-empty" role="alert"><AlertCircle aria-hidden="true"/><h3>资料暂时无法读取</h3><p>{message}</p><Button variant="outline" onClick={onRetry}>重新读取</Button></div>; }
