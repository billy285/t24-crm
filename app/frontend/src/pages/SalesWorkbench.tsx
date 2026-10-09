import { formatBusinessDateTimeInput, parseBusinessDateTimeInput } from '@/lib/business-date';
import { formatPhoneNumber, getPhoneCopyValue } from '@/lib/phone-format';
import { useEffect, useMemo, useRef, useState } from 'react';
import { CheckCircle2, ChevronDown, ChevronRight, Clipboard, MoreHorizontal } from 'lucide-react';
import { toast } from 'sonner';

import SalesLeadDossier from '@/components/SalesLeadDossier';
import SalesCallRecord, { type SalesCallValues } from '@/components/SalesCallRecord';
import SalesRecentHistory from '@/components/SalesRecentHistory';
import { SalesTeamToday } from '@/components/SalesTeamPerformance';
import '@/components/sales-center.css';
import './sales-workspace.css';
import './sales-workbench-refined.css';
import SalesKnowledgeAssistant from '@/components/SalesKnowledgeAssistant';
import CustomerPhoneDial from '@/components/CustomerPhoneDial';
import MobileSalesQueue from '@/components/MobileSalesQueue';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { Input } from '@/components/ui/input';
import { NativeSelect } from '@/components/ui/native-select';
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle, SheetTrigger } from '@/components/ui/sheet';
import { useRole } from '@/lib/role-context';
import { invokeWithAuth } from '@/lib/tokenStore';
import { useAutoRefresh } from '@/lib/use-auto-refresh';
import { useIsMobile } from '@/hooks/use-mobile';
import { wasExplicitlyLoggedOut } from '@/lib/auth-storage';
import { clearSalesCallDraftMemory, legacySalesCallDraftKey, readSalesWorkbenchFocus, salesCallDraftKey, setSalesCallDraftOwner, writeSalesWorkbenchFocus } from '@/lib/sales-call-draft';
import { isSalesWorkspaceDate, isSalesWorkspaceFilter, readSalesWorkspaceViewState, salesWorkspaceFilters, writeSalesWorkspaceViewState, type SalesWorkspaceViewState } from '@/lib/sales-workspace-view-state';

type Lead = { id: number; business_name: string; contact_name?: string; phone: string; industry?: string; city?: string; state?: string; country?: string; status: string; next_follow_up_at?: string; last_contact_at?: string; do_not_contact: boolean; is_blacklisted: boolean; converted_customer_id?: number | null };
type Task = { task_id: number; task_status: string; completed_at?: string; priority?: 'urgent' | 'high' | 'normal'; next_action_label?: string; queue_category?: 'new' | 'retry' | 'recycled' | 'follow_up'; lead: Lead };
type Workbench = { salesperson: { id: number; name: string }; quota: number; assigned_count: number; completed_count: number; remaining_count: number; is_target_complete: boolean; categories: { unfinished: number; callback: number; interested: number; appointment: number; new: number; retry: number; recycled: number; follow_up: number }; performance: { attempted: number; connected: number; interested: number; appointments: number; callbacks_due: number; connection_rate: number }; items: Task[] };
type AutomationOverview = { counts: { eligible: number; assigned: number; protected: number; cooling: number; blocked: number; closed: number }; total: number; reusable: number; active_sales: number; daily_capacity: number; estimated_pool_days?: number; rules: { unstarted_release_hours: number; same_sales_no_answer_attempts: number; no_answer_cooldown_days: number; soft_reject_cooldown_days: number; existing_provider_cooldown_days: number } };
type Assignee = { id: number; name: string };
type HistoryItem = { id: number; outcome: string; outcome_label: string; notes?: string; next_follow_up_at?: string; called_at: string; sales_employee_name?: string; call_duration_seconds?: number; sync_status?: string };
type Analysis = { available: boolean; message?: string; analysis?: { warning?: string; cards: { title: string; content: string; kind: string; sources: { label: string; value?: string | number; updated_at?: string }[] }[] } };
type RecoveryAlert = { lead_id: number; business_name: string; state: 'watch' | 'recoverable'; message: string; deadline?: string; extension_request?: { reason?: string } | null };
type PersonalPerformance = { rank: number; score: number; confidence: string; score_breakdown: { execution: number; discipline: number; opportunity: number; results: number; documentation: number }; metrics: { completion_rate: number; connection_rate: number; interest_rate: number; note_quality_rate: number; overdue_followups: number }; suggestions: string[] };
type RingCentralStatus = { configured: boolean; connected: boolean; degraded?: boolean; needs_reconnect?: boolean; realtime_sync_enabled?: boolean; sync_health?: 'enabled' | 'attention' | 'pending' | 'disconnected'; authorization_status?: 'connected' | 'reconnect_required' | 'not_connected'; extension_number?: string; last_synced_at?: string; last_error?: string; message?: string; webhook_status?: string; webhook_expires_at?: string; last_event_at?: string };
type RingCentralCallStatus = { available: boolean; sync_status: 'waiting' | 'event_received' | 'awaiting_call_log' | 'verified'; provider_status?: string; provider_result?: string; connected?: boolean; duration_seconds?: number; sales_employee_name?: string };
type WorkbenchReturnContext = { filter?: string; selectedSalesId?: string; date?: string; leadId?: number; scrollY?: number };
type SavedCallReceipt = { leadId: number; name: string; action?: 'quote' | 'followup'; nextFollowUpAt?: string };

const outcomeOptions = [
  { value: 'no_answer', label: '未接通' }, { value: 'callback', label: '待回访' },
  { value: 'interested', label: '有意向' }, { value: 'appointment', label: '已预约' },
  { value: 'not_now', label: '暂时不需要（60天后轮换）' }, { value: 'existing_provider', label: '已有服务商（90天后轮换）' },
  { value: 'not_interested', label: '无意向' }, { value: 'do_not_contact', label: '禁止再联系' },
];
const statusLabels: Record<string, string> = { new: '新线索', contacted: '已联系', follow_up: '待回访', interested: '有意向', appointment: '已预约', lost: '无意向', blocked: '禁止联系' };
const statusColor: Record<string, string> = { new: 'bg-slate-100 text-slate-700', contacted: 'bg-blue-100 text-blue-700', follow_up: 'bg-amber-100 text-amber-800', interested: 'bg-emerald-100 text-emerald-700', appointment: 'bg-cyan-100 text-cyan-700', lost: 'bg-slate-100 text-slate-600', blocked: 'bg-rose-100 text-rose-700' };
const shanghaiParts = (value: Date) => Object.fromEntries(
  new Intl.DateTimeFormat('en-US', {
    timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
  }).formatToParts(value).map(part => [part.type, part.value]),
);
const today = () => {
  const parts = shanghaiParts(new Date());
  return `${parts.year}-${parts.month}-${parts.day}`;
};
const shanghaiDateTimeValue = (value: Date) => {
  const parts = shanghaiParts(value);
  return `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}`;
};
const parseBackendDate = (value?: string) => {
  if (!value) return null;
  const raw = String(value).trim();
  if (!raw || /^\d{4}-\d{2}-\d{2}$/.test(raw)) return null;
  // SQLite removes timezone metadata from stored UTC datetimes. Match the
  // backend contract by restoring UTC before converting to business time.
  const normalized = /(Z|[+-]\d{2}:?\d{2})$/i.test(raw) ? raw : `${raw.replace(' ', 'T')}Z`;
  const parsed = new Date(normalized);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
};
const businessDateForValue = (value?: string) => {
  if (!value) return '';
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return value;
  const parsed = parseBackendDate(value);
  if (!parsed) return '';
  const parts = shanghaiParts(parsed);
  return `${parts.year}-${parts.month}-${parts.day}`;
};
const isFollowUpOverdue = (value?: string) => {
  const businessDate = businessDateForValue(value);
  return Boolean(businessDate && businessDate < today());
};
const formatDate = (value?: string) => {
  if (!value) return '-';
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return `${value}（北京时间）`;
  const parsed = parseBackendDate(value);
  if (!parsed) return value;
  return `${shanghaiDateTimeValue(parsed).replace('T', ' ')}（北京时间）`;
};
const priorityStyle: Record<string, string> = { urgent: 'bg-rose-100 text-rose-700', high: 'bg-amber-100 text-amber-800', normal: 'bg-slate-100 text-slate-700' };
const priorityLabel: Record<string, string> = { urgent: '优先处理', high: '今日重点', normal: '正常任务' };
const workbenchFilters = salesWorkspaceFilters;
const scopedStorageKey = (kind: string, userId?: number) => Number.isSafeInteger(userId) && Number(userId) > 0 ? `t24:sales-workbench:${kind}:v2:${userId}` : null;
const removeSessionValue = (key: string | null) => { if (key) { try { sessionStorage.removeItem(key); } catch { /* Optional browser context cannot invalidate a saved business record. */ } } };

function readWorkbenchReturnContext(userId?: number) {
  try {
    const key = scopedStorageKey('return-context', userId);
    const value = key ? JSON.parse(sessionStorage.getItem(key) || '{}') : {};
    if (!value || typeof value !== 'object' || Array.isArray(value)) return {};
    return {
      filter: typeof value.filter === 'string' && workbenchFilters.includes(value.filter) ? value.filter : undefined,
      selectedSalesId: typeof value.selectedSalesId === 'string' && /^\d+$/.test(value.selectedSalesId) ? value.selectedSalesId : undefined,
      date: typeof value.date === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value.date) ? value.date : undefined,
      leadId: Number.isSafeInteger(value.leadId) && value.leadId > 0 ? value.leadId : undefined,
      scrollY: typeof value.scrollY === 'number' && Number.isFinite(value.scrollY) && value.scrollY >= 0 ? value.scrollY : undefined,
    } as WorkbenchReturnContext;
  } catch {
    return {};
  }
}

function rememberPendingDial(task: Task, userId?: number, salesId?: number, date?: string) {
  const key = scopedStorageKey('pending-dial', userId);
  if (!key) return;
  try { sessionStorage.setItem(key, JSON.stringify({
    userId, salesId, date,
    taskId: task.task_id,
    leadId: task.lead.id,
    createdAt: Date.now(),
  })); } catch { /* Dial handoff is independent of browser storage availability. */ }
}

function readPendingDial(userId?: number, salesId?: number, date?: string) {
  try {
    const key = scopedStorageKey('pending-dial', userId);
    const value = key ? JSON.parse(sessionStorage.getItem(key) || '{}') : {};
    if (value.userId !== userId || value.salesId !== salesId || value.date !== date || !Number.isSafeInteger(value.taskId) || value.taskId <= 0 || !Number.isSafeInteger(value.leadId) || value.leadId <= 0 || !Number.isFinite(value.createdAt) || value.createdAt <= 0 || value.createdAt > Date.now() + 60000) return {};
    return value as {
      taskId?: number;
      leadId?: number;
      createdAt?: number;
    };
  } catch {
    return {};
  }
}

function suggestedFollowUpValue(value: string) {
  if (['not_interested', 'do_not_contact', 'not_now', 'existing_provider'].includes(value)) return '';
  const next = new Date(Date.now() + 24 * 60 * 60 * 1000);
  next.setUTCMinutes(0, 0, 0);
  return shanghaiDateTimeValue(next);
}

function initialWorkspaceView(userId: number | undefined, role: string, canManage: boolean): SalesWorkspaceViewState {
  const day = today();
  const saved = readSalesWorkspaceViewState(userId, role, day);
  const params = new URLSearchParams(window.location.search);
  const explicitSales = params.has('sales_employee_id');
  const salesId = Number(params.get('sales_employee_id'));
  const selectedSalesId = !canManage ? '' : explicitSales
    ? Number.isSafeInteger(salesId) && salesId > 0 ? String(salesId) : ''
    : saved?.selectedSalesId || '';
  const explicitLead = params.has('lead_id');
  const explicitDate = params.get('target_date') ?? params.get('date');
  const date = explicitDate !== null ? isSalesWorkspaceDate(explicitDate) ? explicitDate : day
    : explicitLead ? day : saved?.date || day;
  const sameScope = saved?.date === date && saved.selectedSalesId === selectedSalesId;
  const explicitFilter = params.get('filter');
  const filter = explicitFilter !== null ? isSalesWorkspaceFilter(explicitFilter) ? explicitFilter : 'all'
    : explicitLead ? 'all' : sameScope ? saved.filter : 'all';
  const teamView = canManage && !explicitSales && !explicitLead && !params.has('ringcentral') && (saved?.teamView ?? true);
  return { date, selectedSalesId, filter, teamView };
}

export default function SalesWorkbench() {
  const { employee, role } = useRole();
  return <SalesWorkspace key={`${employee?.id || 'unknown'}:${role || 'unknown'}`} />;
}

function SalesWorkspace() {
  const { role, isAdmin, employee } = useRole();
  const isMobile = useIsMobile();
  const [dossierId, setDossierId] = useState<number | null>(null);
  const canManage = isAdmin || role === 'sales_manager';
  const [initialView] = useState(() => initialWorkspaceView(employee?.id, role, canManage));
  const [teamView, setTeamView] = useState(initialView.teamView);
  useEffect(() => { if (!canManage) setTeamView(false); }, [canManage]);
  const [assignees, setAssignees] = useState<Assignee[]>([]);
  const [selectedSalesId, setSelectedSalesId] = useState(initialView.selectedSalesId);
  const [date, setDate] = useState(initialView.date);
  const [workbench, setWorkbench] = useState<Workbench | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [preparing, setPreparing] = useState(false);
  const requestedLeadRef = useRef(Number(new URLSearchParams(window.location.search).get('lead_id')) || null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [filter, setFilter] = useState(initialView.filter);
  const [activeTask, setActiveTask] = useState<Task | null>(null);
  const [focusedTask, setFocusedTask] = useState<Task | null>(null);
  const [supplementalFollowUp, setSupplementalFollowUp] = useState(false);
  const [saving, setSaving] = useState(false);
  const [savedReceipt, setSavedReceipt] = useState<SavedCallReceipt | null>(null);
  const [historyTask, setHistoryTask] = useState<Task | null>(null);
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [analysisTask, setAnalysisTask] = useState<Task | null>(null);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [quotaInput, setQuotaInput] = useState('100');
  const [recoveryAlerts, setRecoveryAlerts] = useState<RecoveryAlert[]>([]);
  const [extensionBusy, setExtensionBusy] = useState<number | null>(null);
  const [personalPerformance, setPersonalPerformance] = useState<PersonalPerformance | null>(null);
  const [ringCentral, setRingCentral] = useState<RingCentralStatus | null>(null);
  const [providerCall, setProviderCall] = useState<RingCentralCallStatus | null>(null);
  const [providerCallTaskId, setProviderCallTaskId] = useState<number | null>(null);
  const [returnLeadId, setReturnLeadId] = useState<number | null>(null);
  const [visibleCount, setVisibleCount] = useState(20);
  const [automationOverview, setAutomationOverview] = useState<AutomationOverview | null>(null);
  const [automationBusy, setAutomationBusy] = useState(false);
  const [assigneesLoaded, setAssigneesLoaded] = useState(false);
  const [assigneeLoadError, setAssigneeLoadError] = useState<string | null>(null);
  const [knowledgeExpanded, setKnowledgeExpanded] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [scopeOpen, setScopeOpen] = useState(false);
  const workbenchRequestRef = useRef(0);
  const ringCentralSubscriptionRequestedRef = useRef(false);
  const ringCentralBackfillRequestedRef = useRef(false);
  const pendingDialRestoreAttemptedRef = useRef(false);
  const restoredFocusScopeRef = useRef('');

  useEffect(() => {
    writeSalesWorkspaceViewState(employee?.id, role, today(), { date, selectedSalesId: canManage ? selectedSalesId : '', filter, teamView: canManage && teamView });
  }, [employee?.id, role, date, selectedSalesId, filter, teamView, canManage]);


  useEffect(() => {
    setSalesCallDraftOwner(employee?.id);
    return () => { if (wasExplicitlyLoggedOut()) clearSalesCallDraftMemory(); };
  }, [employee?.id]);
  useEffect(() => { setSavedReceipt(null); }, [employee?.id, selectedSalesId, date, teamView]);

  const salesIdParam = canManage ? selectedSalesId : '';
  const loadAssignees = async () => {
    if (!canManage) {
      setAssigneesLoaded(true);
      setAssigneeLoadError(null);
      return;
    }
    setAssigneesLoaded(false);
    setAssigneeLoadError(null);
    try {
      const response = await invokeWithAuth({ url: '/api/v1/sales-leads/assignees', method: 'GET' });
      const records = Array.isArray(response.data) ? response.data : [];
      setAssignees(records);
      setAssigneesLoaded(true);
      setAssigneeLoadError(null);
      setSelectedSalesId(current => records.some(record => Number(record.id) === Number(current)) ? current : records[0] ? String(records[0].id) : '');
      if (records.length === 0) setLoading(false);
    } catch (error: any) {
      setAssignees([]);
      setAssigneesLoaded(true);
      setAssigneeLoadError(error?.data?.detail || error?.message || '销售人员列表加载失败');
      setLoading(false);
    }
  };
  const loadWorkbench = async ({ background = false }: { background?: boolean } = {}) => {
    const requestId = ++workbenchRequestRef.current;
    if (teamView) { setLoading(false); setRefreshing(false); return; }
    if (canManage && !selectedSalesId) {
      setWorkbench(null);
      setLoadError(null);
      setLoading(false);
      setRefreshing(false);
      return;
    }
    if (background && workbench) setRefreshing(true);
    else setLoading(true);
    try {
      const params = new URLSearchParams({ target_date: date });
      if (salesIdParam) params.set('sales_employee_id', salesIdParam);
      const response = await invokeWithAuth({ url: `/api/v1/sales-leads/workbench/today?${params}`, method: 'GET' });
      if (requestId !== workbenchRequestRef.current) return;
      const expectedSalesId = canManage ? Number(selectedSalesId) : employee?.id;
      if (!response.data || !Array.isArray(response.data.items) || expectedSalesId && Number(response.data.salesperson?.id) !== expectedSalesId) throw new Error('任务所属销售不匹配，请重新读取');
      setWorkbench(response.data);
      setQuotaInput(String(response.data?.quota || 100));
      setLoadError(null);
    } catch (error: any) {
      if (requestId !== workbenchRequestRef.current) return;
      const message = error?.data?.detail || error?.message || '每日任务加载失败';
      setLoadError(message);
      if (!workbench) toast.error(message);
    } finally {
      if (requestId === workbenchRequestRef.current) {
        setLoading(false);
        setRefreshing(false);
      }
    }
  };
  const prepareWorkbench = async () => {
    if (preparing || saving || date !== today() || (canManage && !selectedSalesId)) return;
    setPreparing(true);
    try {
      const params = new URLSearchParams({ target_date: date });
      if (salesIdParam) params.set('sales_employee_id', salesIdParam);
      const response = await invokeWithAuth({ url: `/api/v1/sales-leads/workbench/prepare?${params}`, method: 'POST' });
      toast.success(response.data?.message || '今日任务已准备');
      await loadWorkbench();
    } catch (error: any) { toast.error(error?.data?.detail || error?.message || '生成今日任务失败'); }
    finally { setPreparing(false); }
  };
  const prepareButton = <Button disabled={preparing || saving || date !== today() || Boolean(loadError) || (canManage && !selectedSalesId)} onClick={() => void prepareWorkbench()}>{preparing ? '正在生成…' : '生成今日任务'}</Button>;
  const loadRecoveryAlerts = async () => {
    if (role !== 'sales') { setRecoveryAlerts([]); return; }
    try {
      const response = await invokeWithAuth({ url: '/api/v1/sales-leads/recovery/my-alerts', method: 'GET' });
      setRecoveryAlerts(response.data?.items || []);
    } catch { setRecoveryAlerts([]); }
  };
  const loadPersonalPerformance = async () => {
    if (role !== 'sales') { setPersonalPerformance(null); return; }
    try {
      const response = await invokeWithAuth({ url: '/api/v1/sales-leads/dashboard/performance?days=30', method: 'GET' });
      setPersonalPerformance(response.data?.items?.[0] || null);
    } catch { setPersonalPerformance(null); }
  };
  const loadRingCentral = async () => {
    try {
      const response = await invokeWithAuth({ url: '/api/ringcentral/status', method: 'GET' });
      let status = response.data as RingCentralStatus;
      const webhookExpiry = status.webhook_expires_at ? new Date(status.webhook_expires_at).getTime() : 0;
      const webhookNeedsRenewal = status.webhook_status !== 'active' || !webhookExpiry || webhookExpiry <= Date.now() + 24 * 60 * 60 * 1000;
      if (status.connected && webhookNeedsRenewal && !ringCentralSubscriptionRequestedRef.current) {
        ringCentralSubscriptionRequestedRef.current = true;
        try {
          const subscription = await invokeWithAuth({ url: '/api/ringcentral/subscription/ensure', method: 'POST' });
          status = subscription.data;
        } catch {
          // The status card exposes the provider error; manual calling remains available.
        }
      }
      setRingCentral(status);
      if (status.connected && !ringCentralBackfillRequestedRef.current) {
        ringCentralBackfillRequestedRef.current = true;
        void invokeWithAuth({ url: '/api/ringcentral/sync?days=2', method: 'POST' }).catch(() => undefined);
      }
    } catch { setRingCentral(null); }
  };
  const loadAutomationOverview = async () => {
    if (!canManage) return;
    try {
      const response = await invokeWithAuth({ url: '/api/v1/sales-leads/automation/overview', method: 'GET' });
      const overview = response.data;
      setAutomationOverview(overview?.counts && overview?.rules ? overview : null);
    } catch { setAutomationOverview(null); }
  };
  const runAutomation = async () => {
    setAutomationBusy(true);
    try {
      const response = await invokeWithAuth({ url: '/api/v1/sales-leads/automation/run', method: 'POST' });
      toast.success(response.data?.message || '自动循环扫描完成');
      await Promise.all([loadAutomationOverview(), loadWorkbench()]);
    } catch (error: any) { toast.error(error?.data?.detail || error?.message || '自动扫描失败'); }
    finally { setAutomationBusy(false); }
  };
  const connectRingCentral = async (leadId?: number) => {
    try {
      const response = await invokeWithAuth({ url: '/api/ringcentral/connect', method: 'GET' });
      const authorizationUrl = response.data?.authorization_url;
      if (!authorizationUrl) throw new Error('未获得授权链接');
      const contextKey = scopedStorageKey('return-context', employee?.id);
      if (contextKey) { try { sessionStorage.setItem(contextKey, JSON.stringify({ filter, selectedSalesId, date, leadId, scrollY: window.scrollY })); } catch { /* The draft component warns if browser storage is unavailable. */ } }
      window.location.assign(authorizationUrl);
    } catch (error: any) { toast.error(error?.data?.detail || error?.message || '无法发起 RingCentral 连接'); }
  };

  useEffect(() => { void loadAssignees(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [canManage]);
  useEffect(() => {
    if (canManage && (!assigneesLoaded || assigneeLoadError)) return;
    setWorkbench(null);
    setLoadError(null);
    setLoading(true);
    void loadWorkbench();
    void loadRecoveryAlerts();
    void loadPersonalPerformance();
    void loadAutomationOverview();
    /* eslint-disable-next-line react-hooks/exhaustive-deps */
    return () => { workbenchRequestRef.current += 1; };
  }, [selectedSalesId, date, canManage, role, teamView, assigneesLoaded, assigneeLoadError]);
  useEffect(() => {
    if (teamView) return;
    void loadRingCentral();
    const url = new URL(window.location.href);
    const result = url.searchParams.get('ringcentral');
    if (!result) return;

    const context = readWorkbenchReturnContext(employee?.id);
    if (context.date) setDate(context.date);
    if (canManage && context.selectedSalesId) setSelectedSalesId(context.selectedSalesId);
    if (context.filter && workbenchFilters.includes(context.filter as typeof workbenchFilters[number])) {
      setFilter(context.filter as typeof workbenchFilters[number]);
    }
    setReturnLeadId(context.leadId || null);
    removeSessionValue(scopedStorageKey('return-context', employee?.id));
    url.searchParams.delete('ringcentral');
    window.history.replaceState({}, '', `${url.pathname}${url.search}${url.hash}`);

    if (result === 'connected') toast.success('RingCentral 已连接，已返回刚才的工作位置。');
    if (result === 'failed') toast.error('RingCentral 连接失败，已返回刚才的工作位置。');
    if (result === 'cancelled') toast.message('已取消 RingCentral 授权，已返回刚才的工作位置。');
    if (!context.leadId && typeof context.scrollY === 'number') {
      window.requestAnimationFrame(() => window.scrollTo({ top: context.scrollY, behavior: 'smooth' }));
    }
  }, [canManage, teamView]);
  useEffect(() => {
    if (!returnLeadId || loading || !workbench) return;
    const target = document.querySelector<HTMLElement>(`[data-lead-id="${returnLeadId}"]`);
    if (!target) return;
    window.requestAnimationFrame(() => target.scrollIntoView({ behavior: 'smooth', block: 'center' }));
    setReturnLeadId(null);
  }, [loading, returnLeadId, workbench]);
  useEffect(() => {
    if (loading || !workbench || pendingDialRestoreAttemptedRef.current) return;
    pendingDialRestoreAttemptedRef.current = true;
    const pending = readPendingDial(employee?.id, workbench.salesperson.id, date);
    if (!pending.taskId || !pending.createdAt) return;
    // Do not resurrect an abandoned result sheet on a later workday.
    if (Date.now() - pending.createdAt > 4 * 60 * 60 * 1000) {
      removeSessionValue(scopedStorageKey('pending-dial', employee?.id));
      return;
    }
    const task = workbench.items.find(item => item.task_id === pending.taskId);
    removeSessionValue(scopedStorageKey('pending-dial', employee?.id));
    if (!activeTask && task && task.lead.id === pending.leadId && task.task_status !== 'completed') openCall(task);
  }, [activeTask, loading, workbench, employee?.id, date]);
  useAutoRefresh(async () => { await loadWorkbench({ background: true }); await loadRecoveryAlerts(); await loadPersonalPerformance(); await loadRingCentral(); }, { intervalMs: 30000, enabled: !teamView && !activeTask && !historyTask && !analysisTask && (!canManage || !!selectedSalesId) });

  const overdueFollowUpCount = useMemo(() => (workbench?.items || []).filter(task => (
    task.task_status !== 'completed'
    && isFollowUpOverdue(task.lead.next_follow_up_at)
  )).length, [workbench]);
  const filteredTasks = useMemo(() => (workbench?.items || []).filter(task => {
    if (filter === 'overdue') return task.task_status !== 'completed' && isFollowUpOverdue(task.lead.next_follow_up_at);
    if (filter === 'unfinished') return task.task_status !== 'completed';
    if (filter === 'callback') return task.lead.status === 'follow_up';
    if (filter === 'interested') return task.lead.status === 'interested';
    if (filter === 'appointment') return task.lead.status === 'appointment';
    return true;
  }).sort((a, b) => {
    const doneDifference = Number(a.task_status === 'completed') - Number(b.task_status === 'completed');
    if (doneDifference !== 0) return doneDifference;
    const priorityOrder = { urgent: 0, high: 1, normal: 2 };
    const priorityDifference = (priorityOrder[a.priority || 'normal'] ?? 9) - (priorityOrder[b.priority || 'normal'] ?? 9);
    if (priorityDifference !== 0) return priorityDifference;
    const aTime = parseBackendDate(a.lead.next_follow_up_at)?.getTime() ?? Number.POSITIVE_INFINITY;
    const bTime = parseBackendDate(b.lead.next_follow_up_at)?.getTime() ?? Number.POSITIVE_INFINITY;
    return aTime - bTime;
  }), [filter, workbench]);
  const visibleTasks = useMemo(() => filteredTasks.slice(0, visibleCount), [filteredTasks, visibleCount]);
  useEffect(() => { setVisibleCount(20); }, [filter, workbench?.salesperson.id, date]);
  useEffect(() => {
    setFocusedTask(current => {
      const requestedTask = requestedLeadRef.current && filteredTasks.find(task => task.lead.id === requestedLeadRef.current);
      if (requestedTask) { requestedLeadRef.current = null; return requestedTask; }
      const focusScope = `${employee?.id}:${workbench?.salesperson.id}:${date}`;
      if (workbench && restoredFocusScopeRef.current !== focusScope) {
        restoredFocusScopeRef.current = focusScope;
        const saved = readSalesWorkbenchFocus(employee?.id, workbench.salesperson.id, date);
        const restored = saved && filteredTasks.find(task => task.task_id === saved.taskId && task.lead.id === saved.leadId);
        if (restored) return restored;
      }
      const currentTask = current && filteredTasks.find(task => task.task_id === current.task_id);
      if (currentTask && currentTask.task_status !== 'completed') return currentTask;
      return filteredTasks.find(task => task.task_status !== 'completed') || filteredTasks[0] || null;
    });
  }, [filteredTasks, employee?.id, workbench, date]);
  useEffect(() => {
    if (teamView || loading || !focusedTask || !workbench?.items.some(task => task.task_id === focusedTask.task_id && task.lead.id === focusedTask.lead.id)) return;
    writeSalesWorkbenchFocus(employee?.id, workbench.salesperson.id, date, focusedTask.task_id, focusedTask.lead.id);
  }, [focusedTask, workbench, employee?.id, date, loading, teamView]);

  useEffect(() => {
    const providerTask = supplementalFollowUp ? activeTask : focusedTask;
    setProviderCall(null);
    if (!providerTask) return;
    let cancelled = false;
    const loadProviderCall = async () => {
      try {
        const response = await invokeWithAuth({ url: `/api/ringcentral/calls/recent?task_id=${providerTask.task_id}`, method: 'GET' });
        if (!cancelled) { setProviderCallTaskId(providerTask.task_id); setProviderCall(response.data); }
      } catch {
        if (!cancelled) setProviderCall(null);
      }
    };
    void loadProviderCall();
    const timer = window.setInterval(() => void loadProviderCall(), 5000);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [activeTask, focusedTask, supplementalFollowUp]);

  const openCall = (task: Task) => {
    if (task.task_status === 'completed' || task.lead.do_not_contact || task.lead.is_blacklisted || task.lead.converted_customer_id) return;
    setFocusedTask(task);
    setSupplementalFollowUp(false);
    setActiveTask(null);
  };
  const markDialStarted = (task: Task) => {
    if (saving || task.task_status === 'completed' || task.lead.do_not_contact || task.lead.is_blacklisted || task.lead.converted_customer_id) return;
    rememberPendingDial(task, employee?.id, workbench?.salesperson.id, date);
    void invokeWithAuth({ url: `/api/v1/sales-leads/workbench/tasks/${task.task_id}/dial-started`, method: 'POST' }).catch(() => undefined);
    openCall(task);
  };
  const openSupplementalFollowUp = (task: Task) => {
    if (saving || task.task_status !== 'completed' || task.lead.do_not_contact || task.lead.is_blacklisted || task.lead.converted_customer_id) return;
    setSupplementalFollowUp(true);
    setActiveTask(task);
  };
  const copyPhone = async (task = activeTask) => {
    const number = task ? getPhoneCopyValue(task.lead.phone || '', task.lead.country) : '';
    if (!number) return toast.error('该线索没有可用电话号码');
    try { await navigator.clipboard.writeText(number); toast.success(`已复制 ${number}`); }
    catch { toast.error('复制失败，请手动选择号码'); }
  };
  const submitResult = async (task: Task, values: SalesCallValues, supplemental = false): Promise<boolean> => {
    const { outcome: result, notes: resultNotes, nextFollowUpAt: followUpTime } = values;
    if (!task || saving || task.lead.do_not_contact || task.lead.is_blacklisted || task.lead.converted_customer_id || (!supplemental && task.task_status === 'completed')) return false;
    if (result === 'callback' && !followUpTime) { toast.error('待回访请设置下次跟进时间'); return false; }
    if (result === 'do_not_contact' && !resultNotes.trim()) { toast.error('禁止再联系请填写商家要求或原因'); return false; }
    if (['interested', 'appointment'].includes(result) && (!resultNotes.trim() || !followUpTime)) { toast.error('有意向或已预约必须填写跟进内容和下次跟进时间'); return false; }
    setSaving(true);
    try {
      const url = supplemental ? `/api/v1/sales-leads/${task.lead.id}/follow-up` : `/api/v1/sales-leads/workbench/tasks/${task.task_id}/result`;
      const response = await invokeWithAuth({ url, method: 'POST', data: { outcome: result, contact_details: values.contactDetails || null, notes: resultNotes || null, next_follow_up_at: followUpTime ? parseBusinessDateTimeInput(followUpTime) : null } });
      const returnedLead = response.data?.lead;
      const responseMatches = Number(response.data?.lead_id || returnedLead?.id) === task.lead.id;
      const protectedAfterSave = result === 'do_not_contact' || Boolean(returnedLead?.do_not_contact || returnedLead?.is_blacklisted || returnedLead?.converted_customer_id);
      const action = responseMatches && !protectedAfterSave ? ['interested', 'appointment'].includes(result) ? 'quote' : result === 'callback' ? 'followup' : undefined : undefined;
      setSavedReceipt({ leadId: task.lead.id, name: task.lead.business_name, action, nextFollowUpAt: responseMatches ? response.data?.next_follow_up_at || returnedLead?.next_follow_up_at : undefined });
      if (!supplemental) setWorkbench(current => current ? { ...current, completed_count: current.completed_count + Number(current.items.some(item => item.task_id === task.task_id && item.task_status !== 'completed')), remaining_count: Math.max(0, current.remaining_count - Number(current.items.some(item => item.task_id === task.task_id && item.task_status !== 'completed'))), items: current.items.map(item => item.task_id === task.task_id ? { ...item, task_status: 'completed', lead: responseMatches && returnedLead ? { ...item.lead, ...returnedLead } : item.lead } : item) } : current);
      const defaultMessage = supplemental ? '追加跟进已记录，不影响今日任务完成数' : '通话结果已记录，今日任务进度已更新';
      toast.success(response.data?.used_suggested_follow_up ? `${response.data?.message || '通话结果已记录'}，${response.data?.next_action_label || '已自动安排下一步'}` : (response.data?.message || defaultMessage)); removeSessionValue(scopedStorageKey('pending-dial', employee?.id)); setActiveTask(null); setSupplementalFollowUp(false); await loadWorkbench(); await loadRecoveryAlerts(); await loadPersonalPerformance();
      if (!supplemental) {
        const position = filteredTasks.findIndex(item => item.task_id === task.task_id);
        const remaining = [...filteredTasks.slice(position + 1), ...filteredTasks.slice(0, position)].filter(item => item.task_id !== task.task_id && item.task_status !== 'completed');
        setFocusedTask(remaining[0] || null);
      }
      return true;
    } catch (error: any) { toast.error(error?.response?.data?.detail || error?.data?.detail || error?.message || '通话结果保存失败'); return false; } finally { setSaving(false); }
  };
  const openHistory = async (task: Task) => {
    setHistoryTask(task); setHistory([]);
    try { const response = await invokeWithAuth({ url: `/api/v1/sales-leads/${task.lead.id}/call-history`, method: 'GET' }); setHistory(response.data || []); }
    catch (error: any) { toast.error(error?.data?.detail || error?.message || '联系记录加载失败'); }
  };
  const openAnalysis = async (task: Task) => {
    setAnalysisTask(task); setAnalysis(null);
    try { const response = await invokeWithAuth({ url: `/api/v1/sales-leads/workbench/tasks/${task.task_id}/analysis`, method: 'GET' }); setAnalysis(response.data); }
    catch (error: any) { toast.error(error?.data?.detail || error?.message || '销售分析加载失败'); }
  };
  const updateQuota = async () => {
    if (!selectedSalesId || !Number(quotaInput)) return;
    try {
      await invokeWithAuth({ url: '/api/v1/sales-leads/workbench/quota', method: 'PUT', data: { sales_employee_id: Number(selectedSalesId), target_date: date, target_count: Number(quotaInput) } });
      toast.success('每日任务数量已更新；今日已有任务不会自动无限增加'); await loadWorkbench();
    } catch (error: any) { toast.error(error?.data?.detail || error?.message || '任务数量更新失败'); }
  };
  const requestExtension = async (alert: RecoveryAlert) => {
    const reason = window.prompt('说明还需要保留该线索的原因，例如：商家约定周五回电。');
    if (!reason?.trim()) return;
    setExtensionBusy(alert.lead_id);
    try {
      const response = await invokeWithAuth({ url: `/api/v1/sales-leads/${alert.lead_id}/recovery/request-extension`, method: 'POST', data: { reason: reason.trim(), requested_days: 3 } });
      toast.success(response.data?.message || '延期申请已提交');
      await loadRecoveryAlerts();
    } catch (error: any) { toast.error(error?.data?.detail || error?.message || '延期申请失败'); }
    finally { setExtensionBusy(null); }
  };

  const resetDesktopScope = () => {
    workbenchRequestRef.current += 1;
    setWorkbench(null);
    setFocusedTask(null);
    setActiveTask(null);
    setLoading(true);
  };
  const currentPosition = focusedTask ? filteredTasks.findIndex(task => task.task_id === focusedTask.task_id) + 1 : 0;
  const draftScope = { userId: employee?.id, salesId: workbench?.salesperson.id, leadId: focusedTask?.lead.id, taskId: focusedTask?.task_id, date };
  const draftKey = salesCallDraftKey(draftScope);
  const legacyDraftKey = legacySalesCallDraftKey(draftScope);
  const supplementalDraftScope = { ...draftScope, leadId: activeTask?.lead.id, taskId: activeTask?.task_id, supplemental: true };
  const supplementalDraftKey = salesCallDraftKey(supplementalDraftScope);
  const disabledReason = focusedTask?.lead.do_not_contact || focusedTask?.lead.is_blacklisted
    ? '该商家已被保护或禁止联系，不能发起拨打。'
    : focusedTask?.lead.converted_customer_id ? '该商家已转为正式客户，可查看客户档案。'
    : focusedTask?.task_status === 'completed' ? '该任务今日已完成，可查看联系历史或追加跟进。' : !draftKey ? '正在确认当前销售身份…' : undefined;

  const chooseTask = (task: Task) => {
    if (saving) return;
    setActiveTask(null);
    setSupplementalFollowUp(false);
    setFocusedTask(task);
  };
  const moveCustomer = (step: number) => {
    const task = filteredTasks[currentPosition - 1 + step];
    if (task) chooseTask(task);
  };
  const openSalesTasks = (employeeId: number) => {
    if (saving) return;
    resetDesktopScope();
    setSelectedSalesId(String(employeeId));
    setTeamView(false);
  };
  const currentProvider = providerCallTaskId === focusedTask?.task_id ? providerCall : null;
  const canPrepareQuote = focusedTask && ['interested', 'appointment'].includes(focusedTask.lead.status) && !focusedTask.lead.do_not_contact && !focusedTask.lead.is_blacklisted && !focusedTask.lead.converted_customer_id;
  const providerLabel = currentProvider?.sync_status === 'verified'
    ? `官方${currentProvider.connected ? '接通' : '未接通'} · ${Math.floor((currentProvider.duration_seconds || 0) / 60)}:${String((currentProvider.duration_seconds || 0) % 60).padStart(2, '0')}`
    : currentProvider?.available ? '等待官方确认' : 'RingCentral';

  const scopeControls = <>
    <label className="sc-date-control"><span className={isMobile ? '' : 'sr-only'}>任务日期 · 北京时间</span><Input aria-label="任务日期（北京时间）" type="date" value={date} onChange={event => { resetDesktopScope(); setDate(event.target.value); }} disabled={saving} /></label>
    {canManage ? <label className="sc-date-control"><span className={isMobile ? '' : 'sr-only'}>当前销售</span><NativeSelect value={teamView ? '' : selectedSalesId} onChange={value => { if (value) openSalesTasks(Number(value)); else setTeamView(true); }} disabled={saving || !assigneesLoaded || Boolean(assigneeLoadError)} options={[{ value: '', label: teamView ? '全部销售' : '选择销售' }, ...assignees.map(item => ({ value: String(item.id), label: item.name }))]} /></label> : <span className="sw-salesperson">{employee?.name}</span>}
  </>;
  const managerModes = canManage && <nav className="sw-mode-switch" aria-label="主管任务视角"><button type="button" aria-pressed={teamView} disabled={saving} onClick={() => setTeamView(true)}>团队</button><button type="button" aria-pressed={!teamView} disabled={saving} onClick={() => setTeamView(false)}>客户任务</button></nav>;
  const workbenchMenu = <DropdownMenu><DropdownMenuTrigger asChild><Button variant="ghost" size="icon" aria-label="更多工作台功能"><MoreHorizontal size={18} /></Button></DropdownMenuTrigger><DropdownMenuContent align="end" className="sales-center-ui sales-center-menu">{!teamView && <DropdownMenuItem disabled={preparing || saving || date !== today() || Boolean(loadError) || (canManage && !selectedSalesId)} onSelect={() => void prepareWorkbench()}>生成今日任务</DropdownMenuItem>}<DropdownMenuItem onSelect={() => window.location.assign('/sales-leads?view=intelligence')}>经营中心</DropdownMenuItem>{!teamView && <DropdownMenuItem onSelect={() => setSettingsOpen(true)}>拨号与任务设置</DropdownMenuItem>}</DropdownMenuContent></DropdownMenu>;
  const currentSalesName = canManage ? teamView ? '全部销售' : assignees.find(item => String(item.id) === selectedSalesId)?.name || '选择销售' : employee?.name || '当前销售';

  return <div className="sales-center-ui sc-workbench calm-sales-page calm-sales-workbench sw-refined app-page" data-testid={isMobile ? 'sales-workbench-mobile' : 'sales-workbench-desktop'}>
    <div className="sw-workspace-heading">
    <header className="sc-page-heading">
      <h1>{teamView ? date === today() ? '团队今日任务' : '团队任务' : date === today() ? '今日拨打' : '拨打记录'}</h1>
      {isMobile ? <div className="sw-phone-scope-controls"><Sheet open={scopeOpen} onOpenChange={setScopeOpen}><SheetTrigger asChild><Button type="button" variant="ghost" className="sw-scope-trigger" aria-label="调整任务范围" disabled={saving}><span><time dateTime={date}>{date}</time><strong>{currentSalesName}</strong></span><ChevronDown size={14} /></Button></SheetTrigger><SheetContent side="bottom" className="sales-center-ui sw-mobile-sheet sw-scope-sheet"><SheetHeader><SheetTitle>任务范围</SheetTitle><SheetDescription className="sr-only">选择北京时间日期及销售人员，不会自动生成或完成任务。</SheetDescription></SheetHeader><div className="sw-phone-scope-fields">{scopeControls}</div>{managerModes}{!teamView && <div className="sw-scope-review"><span>有意向 <strong>{workbench?.performance.interested ?? '—'}</strong></span><span>已预约 <strong>{workbench?.performance.appointments ?? '—'}</strong></span><span>逾期 <strong>{overdueFollowUpCount}</strong></span></div>}<Button type="button" onClick={() => setScopeOpen(false)}>返回工作台</Button></SheetContent></Sheet>{workbenchMenu}</div> : <div className="sw-scope-controls">{scopeControls}{workbenchMenu}</div>}
    </header>
    {!isMobile && managerModes}
    {!teamView && <section className="sw-progress-row" aria-label="今日执行进度"><div className="sw-progress-value">今日已记录 <strong>{loading ? '—' : workbench?.completed_count ?? '—'}</strong><span> / {loading ? '—' : workbench?.quota ?? '—'}</span></div><div className="sc-progress-track" role="progressbar" aria-label="任务完成进度" aria-valuemin={0} aria-valuemax={workbench?.quota || 100} aria-valuenow={workbench?.completed_count || 0}><span style={{ width: `${workbench ? Math.min(100, workbench.completed_count / Math.max(workbench.quota, 1) * 100) : 0}%` }} /></div>{refreshing && <span className="sw-refresh-status" role="status">更新中</span>}
      {!isMobile && <details className="sw-review"><summary>今日复盘</summary><div><span>有意向 <strong>{workbench?.performance.interested ?? '—'}</strong></span><span>已预约 <strong>{workbench?.performance.appointments ?? '—'}</strong></span><span>逾期 <strong>{overdueFollowUpCount}</strong></span></div></details>}
    </section>}
    </div>
    {!teamView && savedReceipt && <section className="sw-save-receipt" role="status" aria-label="上次保存结果"><CheckCircle2 size={17} /><span>已保存 · <strong>{savedReceipt.name}</strong>{savedReceipt.nextFollowUpAt && <time> · 回访 {formatDate(savedReceipt.nextFollowUpAt)}</time>}</span>{savedReceipt.action && <Button variant="outline" onClick={() => window.location.assign(`/sales-leads?lead_id=${savedReceipt.leadId}&action=${savedReceipt.action}`)}>{savedReceipt.action === 'quote' ? '准备报价' : '查看跟进'}</Button>}</section>}
    {assigneeLoadError && <div className="sales-v3-alert" role="alert">销售人员暂时无法读取<Button size="sm" variant="outline" onClick={() => void loadAssignees()}>重新加载</Button></div>}
    {!teamView && loadError && <div className="sales-v3-alert" role="alert">今日任务暂时无法更新{workbench ? '，保留上次读取的任务' : ''}<Button size="sm" variant="outline" onClick={() => void loadWorkbench()}>重新加载</Button></div>}
    {teamView && canManage ? assigneesLoaded && !assigneeLoadError ? <SalesTeamToday employees={assignees} targetDate={date} onOpenWorkbench={openSalesTasks} /> : <div className="sc-empty">{assigneeLoadError ? '销售人员暂不可用' : '正在读取团队任务…'}</div> : <>
    {isMobile ? <MobileSalesQueue key={`${employee?.id}:${role}:${date}:${canManage ? selectedSalesId : employee?.id}`} workspaceScope={{ userId: employee?.id, role, date, salesId: canManage ? Number(selectedSalesId) : employee?.id }} businessDay={today()} tasks={filteredTasks} selectedTaskId={focusedTask?.task_id} filter={filter} overdueCount={overdueFollowUpCount} disabled={saving} onFilterChange={setFilter} onSelect={taskId => { const task = filteredTasks.find(item => item.task_id === taskId); if (task) chooseTask(task); }} /> : <div className="sw-mobile-queue"><label><span className="sr-only">选择客户</span><select aria-label="选择客户" value={focusedTask?.task_id || ''} disabled={saving} onChange={event => { const task = filteredTasks.find(item => String(item.task_id) === event.target.value); if (task) chooseTask(task); }}><option value="" disabled>选择客户</option>{filteredTasks.map((task, index) => <option key={task.task_id} value={task.task_id}>{index + 1}. {task.lead.business_name}{task.task_status === 'completed' ? ' · 已完成' : ''}</option>)}</select></label><label><span className="sr-only">队列状态</span><NativeSelect value={filter} onChange={value => setFilter(value as typeof filter)} disabled={saving} options={[{value:'all',label:'全部任务'},{value:'unfinished',label:'未完成'},{value:'overdue',label:`逾期 ${overdueFollowUpCount}`}]} /></label></div>}

    <div className="sc-call-layout">
      <aside className="sc-queue" aria-label="今日客户队列"><div className="sc-queue-head"><div className="sc-panel-heading"><h3>接下来</h3><span>{workbench?.remaining_count ?? '—'} 位</span></div><div className="sc-queue-filters"><button type="button" aria-pressed={filter !== 'overdue'} onClick={() => setFilter('all')} disabled={saving}>全部</button><button type="button" aria-pressed={filter === 'overdue'} onClick={() => setFilter('overdue')} disabled={saving}>逾期 {overdueFollowUpCount}</button></div></div>
        <div className="sc-queue-list">{loading && !workbench ? <p className="sc-muted-state">正在加载…</p> : !visibleTasks.length ? <p className="sc-muted-state">暂无任务</p> : visibleTasks.map((task, index) => <button key={task.task_id} type="button" data-lead-id={task.lead.id} disabled={saving} aria-pressed={focusedTask?.task_id === task.task_id} onClick={() => chooseTask(task)} className={`sc-queue-item ${task.task_status === 'completed' ? 'is-done' : ''}`}><span className="sc-queue-number">{task.task_status === 'completed' ? <CheckCircle2 size={14} /> : String(index + 1).padStart(2, '0')}</span><span className="sc-queue-copy"><strong title={task.lead.business_name}>{task.lead.business_name}</strong><small>{task.task_status === 'completed' ? '已记录' : isFollowUpOverdue(task.lead.next_follow_up_at) ? '逾期跟进' : statusLabels[task.lead.status] || '待联系'}{task.lead.industry ? ` · ${task.lead.industry}` : ''}</small></span></button>)}{visibleTasks.length < filteredTasks.length && <Button className="sc-load-more" size="sm" variant="ghost" onClick={() => setVisibleCount(count => count + 20)}>显示更多客户</Button>}</div><div className="sc-queue-footer">共 {filteredTasks.length} 位</div>
      </aside>
      <div className="sc-call-center sw-current">
        {loading && !workbench ? <div className="sc-empty">正在准备今天的任务…</div> : canManage && !selectedSalesId ? <div className="sc-empty">{assigneesLoaded && assignees.length === 0 ? '暂无可用销售人员，请先新增或启用销售员工。' : '请选择销售人员'}</div> : !focusedTask ? <div className="sc-empty"><CheckCircle2 size={28} /><h3>{loadError ? '今日任务暂不可用' : filter !== 'all' ? '当前筛选暂无任务' : '当前队列暂无任务'}</h3>{!loadError && (filter !== 'all' ? <Button variant="outline" onClick={() => setFilter('all')}>查看全部任务</Button> : prepareButton)}</div> : <>
          <section className="sc-customer" aria-label="当前客户与拨号">
            <div className="sw-customer-heading"><div><div className="sw-customer-context">{!isMobile && <span>当前客户</span>}<Badge className={statusColor[focusedTask.lead.status] || statusColor.new}>{statusLabels[focusedTask.lead.status] || focusedTask.lead.status}</Badge></div><h2>{focusedTask.lead.business_name}</h2><p>{[focusedTask.lead.industry, focusedTask.lead.city || focusedTask.lead.state, focusedTask.lead.contact_name].filter(Boolean).join(' · ') || '资料待补充'}</p>{focusedTask.lead.next_follow_up_at && <p className="sw-followup-plan">回访 · <time>{formatDate(focusedTask.lead.next_follow_up_at)}</time></p>}</div><div className="sw-customer-navigation"><Button variant="ghost" size="icon" aria-label="上一位客户" disabled={saving || currentPosition <= 1} onClick={() => moveCustomer(-1)}><ChevronRight className="rotate-180" size={17} /></Button><Button variant="ghost" size="icon" aria-label="下一位客户" disabled={saving || currentPosition >= filteredTasks.length} onClick={() => moveCustomer(1)}><ChevronRight size={17} /></Button><DropdownMenu><DropdownMenuTrigger asChild><Button variant="ghost" size="icon" aria-label="更多客户操作"><MoreHorizontal size={17} /></Button></DropdownMenuTrigger><DropdownMenuContent align="end" className="sales-center-ui sales-center-menu"><DropdownMenuItem onSelect={() => void openHistory(focusedTask)}>历史联系</DropdownMenuItem><DropdownMenuItem onSelect={() => setDossierId(focusedTask.lead.id)}>累计档案</DropdownMenuItem><DropdownMenuItem onSelect={() => void openAnalysis(focusedTask)}>AI 分析卡</DropdownMenuItem>{focusedTask.task_status === 'completed' && !focusedTask.lead.do_not_contact && !focusedTask.lead.is_blacklisted && !focusedTask.lead.converted_customer_id && <DropdownMenuItem onSelect={() => openSupplementalFollowUp(focusedTask)}>追加跟进</DropdownMenuItem>}</DropdownMenuContent></DropdownMenu></div></div>
            <div className="sw-dial-row"><div><div className="sw-phone"><strong>{formatPhoneNumber(focusedTask.lead.phone, focusedTask.lead.country) || '电话未填写'}</strong><Button size="icon" variant="ghost" aria-label="复制客户号码" disabled={!focusedTask.lead.phone} onClick={() => void copyPhone(focusedTask)}><Clipboard size={14} /></Button></div><span className="sw-provider-status" role="status">{providerLabel}</span></div><div className="sw-dial-actions">{canPrepareQuote && <Button variant="outline" disabled={saving} onClick={() => window.location.assign(`/sales-leads?lead_id=${focusedTask.lead.id}&action=quote`)}>准备报价</Button>}<CustomerPhoneDial country={focusedTask.lead.country} phone={focusedTask.lead.phone} label="拨打电话" variant="outline" className="sw-dial-button" disabled={Boolean(disabledReason) || saving} onLaunched={() => markDialStarted(focusedTask)} /></div></div>
            <SalesRecentHistory compact key={focusedTask.lead.id} leadId={focusedTask.lead.id} lastContactAt={focusedTask.lead.last_contact_at} onOpenAll={() => void openHistory(focusedTask)} formatDate={formatDate} />
          </section>
          <SalesCallRecord key={draftKey} draftKey={draftKey} legacyDraftKey={legacyDraftKey} options={outcomeOptions} suggestedFollowUp={suggestedFollowUpValue} saving={saving} disabledReason={disabledReason} providerCall={null} onOpenKnowledge={() => setKnowledgeExpanded(true)} onSave={values => submitResult(focusedTask, values)} />
        </>}
      </div>
    </div>
    </>}
    <Dialog open={knowledgeExpanded} onOpenChange={setKnowledgeExpanded}><DialogContent className="sw-knowledge-dialog sales-center-ui max-h-[85dvh] overflow-y-auto"><DialogHeader><DialogTitle>销售话术</DialogTitle></DialogHeader><SalesKnowledgeAssistant contextLabel={focusedTask?.lead.industry} /></DialogContent></Dialog>
    <Dialog open={settingsOpen} onOpenChange={setSettingsOpen}><DialogContent className="sales-center-ui max-h-[85dvh] overflow-y-auto"><DialogHeader><DialogTitle>拨号与任务设置</DialogTitle></DialogHeader><div className="space-y-4"><div><h3>RingCentral</h3><p className="mt-2 text-sm text-slate-500">{ringCentral?.realtime_sync_enabled ? '实时通话同步已启用' : ringCentral?.last_error || ringCentral?.message || '官方通话状态待同步'}</p>{ringCentral?.configured && <Button className="mt-3" variant="outline" onClick={() => void connectRingCentral()}>{ringCentral.connected ? '检查 / 重连' : '连接 RingCentral'}</Button>}</div>{canManage && <div><h3>每日任务配额</h3><div className="mt-3 flex gap-2"><Input aria-label="每日任务数量" className="w-24" type="number" min="1" max="300" value={quotaInput} onChange={event => setQuotaInput(event.target.value)} /><Button disabled={!selectedSalesId} onClick={() => void updateQuota()}>保存数量</Button></div></div>}</div></DialogContent></Dialog>
    <SalesLeadDossier leadId={dossierId} onClose={() => setDossierId(null)} />
    <Dialog open={supplementalFollowUp && Boolean(activeTask)} onOpenChange={open => { if (!open && !saving) { setActiveTask(null); setSupplementalFollowUp(false); } }}><DialogContent className="sales-center-ui sw-refined sw-supplemental max-h-[85dvh] overflow-y-auto"><DialogHeader><DialogTitle>追加跟进 · {activeTask?.lead.business_name}</DialogTitle></DialogHeader>{activeTask && <div className="sw-supplemental-dial"><span>{formatPhoneNumber(activeTask.lead.phone, activeTask.lead.country)}</span><CustomerPhoneDial country={activeTask.lead.country} phone={activeTask.lead.phone} label="再次拨打" disabled={saving || activeTask.lead.do_not_contact || activeTask.lead.is_blacklisted || Boolean(activeTask.lead.converted_customer_id)} /><Button type="button" variant="ghost" disabled={saving || !activeTask.lead.phone} onClick={() => void copyPhone(activeTask)}>复制号码</Button></div>}{activeTask && <SalesCallRecord key={supplementalDraftKey} draftKey={supplementalDraftKey} legacyDraftKey={legacySalesCallDraftKey(supplementalDraftScope)} saving={saving} disabledReason={activeTask.lead.do_not_contact || activeTask.lead.is_blacklisted || activeTask.lead.converted_customer_id ? '该商家已受保护，不能追加跟进' : undefined} providerCall={providerCallTaskId === activeTask.task_id ? providerCall : null} options={outcomeOptions} suggestedFollowUp={suggestedFollowUpValue} submitLabel="保存跟进" onSave={values => submitResult(activeTask, values, true)} />}</DialogContent></Dialog>
    <Dialog open={!!historyTask} onOpenChange={open => !open && setHistoryTask(null)}><DialogContent className="sales-center-ui max-h-[80vh] overflow-y-auto"><DialogHeader><DialogTitle>{historyTask?.lead.business_name} · 历史联系记录</DialogTitle></DialogHeader><div className="space-y-3">{history.length ? history.map(item => <div key={item.id} className="rounded-lg border p-3"><div className="flex items-center justify-between"><Badge className={statusColor[item.outcome === 'callback' ? 'follow_up' : item.outcome === 'interested' ? 'interested' : item.outcome === 'appointment' ? 'appointment' : 'contacted']}>{item.outcome_label}</Badge><span className="text-xs text-slate-500">{formatDate(item.called_at)}</span></div><p className="mt-2 whitespace-pre-line text-sm text-slate-700">{item.notes || '未填写备注'}</p><p className="mt-2 text-xs text-slate-500">下次跟进：{formatDate(item.next_follow_up_at)} · 记录人：{item.sales_employee_name || '-'}</p></div>) : <p className="py-8 text-center text-sm text-slate-500">暂无联系记录</p>}</div></DialogContent></Dialog>
    <Dialog open={!!analysisTask} onOpenChange={open => !open && setAnalysisTask(null)}><DialogContent className="sales-center-ui max-h-[86vh] max-w-3xl overflow-y-auto"><DialogHeader><DialogTitle>{analysisTask?.lead.business_name} · AI 销售分析卡</DialogTitle></DialogHeader>{!analysis ? <p className="py-8 text-center text-sm text-slate-500">正在读取经主管确认的资料...</p> : !analysis.available ? <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">{analysis.message}</div> : <div className="space-y-3">{analysis.analysis?.warning && <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">{analysis.analysis.warning}</div>}{analysis.analysis?.cards.map((card, index) => <Card key={`${card.title}-${index}`}><CardContent className="p-4"><div className="flex justify-between gap-2"><p className="font-semibold text-slate-900">{card.title}</p><Badge className={card.kind === 'insufficient' ? 'bg-amber-100 text-amber-800' : 'bg-blue-100 text-blue-700'}>{card.kind === 'insufficient' ? '信息不足' : '资料建议'}</Badge></div><p className="mt-2 whitespace-pre-line text-sm leading-6 text-slate-700">{card.content}</p><div className="mt-3 border-t pt-2 text-xs text-slate-500">{card.sources.map((source, sourceIndex) => <p key={sourceIndex}>{source.label}{source.value ? `：${source.value}` : ''} · {formatDate(source.updated_at)}</p>)}</div></CardContent></Card>)}</div>}</DialogContent></Dialog>
  </div>;
}
