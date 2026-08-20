import { useEffect, useMemo, useRef, useState } from 'react';
import { BarChart3, CalendarClock, CheckCircle2, ChevronRight, Clipboard, ClipboardList, Headphones, History, Link2, MoreHorizontal, PhoneCall, RefreshCw, ShieldAlert, Sparkles, Target, Users } from 'lucide-react';
import { toast } from 'sonner';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { NativeSelect } from '@/components/ui/native-select';
import { Textarea } from '@/components/ui/textarea';
import { useRole } from '@/lib/role-context';
import { invokeWithAuth } from '@/lib/tokenStore';
import { useAutoRefresh } from '@/lib/use-auto-refresh';

type Lead = { id: number; business_name: string; contact_name?: string; phone: string; industry?: string; city?: string; state?: string; country?: string; status: string; next_follow_up_at?: string; last_contact_at?: string; do_not_contact: boolean; is_blacklisted: boolean };
type Task = { task_id: number; task_status: string; completed_at?: string; priority?: 'urgent' | 'high' | 'normal'; next_action_label?: string; queue_category?: 'new' | 'retry' | 'recycled' | 'follow_up'; lead: Lead };
type Workbench = { salesperson: { id: number; name: string }; quota: number; assigned_count: number; completed_count: number; remaining_count: number; is_target_complete: boolean; categories: { unfinished: number; callback: number; interested: number; appointment: number; new: number; retry: number; recycled: number; follow_up: number }; performance: { attempted: number; connected: number; interested: number; appointments: number; callbacks_due: number; connection_rate: number }; items: Task[] };
type AutomationOverview = { counts: { eligible: number; assigned: number; protected: number; cooling: number; blocked: number; closed: number }; total: number; reusable: number; active_sales: number; daily_capacity: number; estimated_pool_days?: number; rules: { unstarted_release_hours: number; same_sales_no_answer_attempts: number; no_answer_cooldown_days: number; soft_reject_cooldown_days: number; existing_provider_cooldown_days: number } };
type Assignee = { id: number; name: string };
type HistoryItem = { id: number; outcome: string; outcome_label: string; notes?: string; next_follow_up_at?: string; called_at: string; sales_employee_name?: string };
type Analysis = { available: boolean; message?: string; analysis?: { warning?: string; cards: { title: string; content: string; kind: string; sources: { label: string; value?: string | number; updated_at?: string }[] }[] } };
type RecoveryAlert = { lead_id: number; business_name: string; state: 'watch' | 'recoverable'; message: string; deadline?: string; extension_request?: { reason?: string } | null };
type PersonalPerformance = { rank: number; score: number; confidence: string; score_breakdown: { execution: number; discipline: number; opportunity: number; results: number; documentation: number }; metrics: { completion_rate: number; connection_rate: number; interest_rate: number; note_quality_rate: number; overdue_followups: number }; suggestions: string[] };
type RingCentralStatus = { configured: boolean; connected: boolean; degraded?: boolean; needs_reconnect?: boolean; extension_number?: string; last_synced_at?: string; last_error?: string; message?: string };
type WorkbenchReturnContext = { filter?: string; selectedSalesId?: string; date?: string; leadId?: number; scrollY?: number };

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
const ringCentralDialNumber = (phone: string) => {
  const digits = phone.replace(/\D/g, '');
  if (digits.length === 10) return `1${digits}`;
  return digits;
};
const e164PhoneNumber = (phone: string) => {
  const number = ringCentralDialNumber(phone);
  return number ? `+${number}` : '';
};
const priorityStyle: Record<string, string> = { urgent: 'bg-rose-100 text-rose-700', high: 'bg-amber-100 text-amber-800', normal: 'bg-slate-100 text-slate-700' };
const priorityLabel: Record<string, string> = { urgent: '优先处理', high: '今日重点', normal: '正常任务' };
const workbenchReturnKey = 't24:sales-workbench:return-context';
const workbenchFilters = ['all', 'overdue', 'unfinished', 'callback', 'interested', 'appointment'] as const;

function readWorkbenchReturnContext() {
  try {
    return JSON.parse(sessionStorage.getItem(workbenchReturnKey) || '{}') as WorkbenchReturnContext;
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

export default function SalesWorkbench() {
  const { role, isAdmin, employee } = useRole();
  const canManage = isAdmin || role === 'sales_manager';
  const [assignees, setAssignees] = useState<Assignee[]>([]);
  const [selectedSalesId, setSelectedSalesId] = useState('');
  const [date, setDate] = useState(today());
  const [workbench, setWorkbench] = useState<Workbench | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [filter, setFilter] = useState<'all' | 'overdue' | 'unfinished' | 'callback' | 'interested' | 'appointment'>('all');
  const [activeTask, setActiveTask] = useState<Task | null>(null);
  const [focusedTask, setFocusedTask] = useState<Task | null>(null);
  const [supplementalFollowUp, setSupplementalFollowUp] = useState(false);
  const [outcome, setOutcome] = useState('no_answer');
  const [notes, setNotes] = useState('');
  const [nextFollowUpAt, setNextFollowUpAt] = useState('');
  const [saving, setSaving] = useState(false);
  const [historyTask, setHistoryTask] = useState<Task | null>(null);
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [analysisTask, setAnalysisTask] = useState<Task | null>(null);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [quotaInput, setQuotaInput] = useState('100');
  const [recoveryAlerts, setRecoveryAlerts] = useState<RecoveryAlert[]>([]);
  const [extensionBusy, setExtensionBusy] = useState<number | null>(null);
  const [personalPerformance, setPersonalPerformance] = useState<PersonalPerformance | null>(null);
  const [ringCentral, setRingCentral] = useState<RingCentralStatus | null>(null);
  const [returnLeadId, setReturnLeadId] = useState<number | null>(null);
  const [visibleCount, setVisibleCount] = useState(20);
  const [automationOverview, setAutomationOverview] = useState<AutomationOverview | null>(null);
  const [automationBusy, setAutomationBusy] = useState(false);
  const [assigneesLoaded, setAssigneesLoaded] = useState(false);
  const [assigneeLoadError, setAssigneeLoadError] = useState<string | null>(null);
  const workbenchRequestRef = useRef(0);

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
      setSelectedSalesId(current => current || (records[0] ? String(records[0].id) : ''));
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
      setRingCentral(response.data);
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
      sessionStorage.setItem(workbenchReturnKey, JSON.stringify({ filter, selectedSalesId, date, leadId, scrollY: window.scrollY }));
      window.location.assign(authorizationUrl);
    } catch (error: any) { toast.error(error?.data?.detail || error?.message || '无法发起 RingCentral 连接'); }
  };

  useEffect(() => { void loadAssignees(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [canManage]);
  useEffect(() => {
    setWorkbench(null);
    setLoadError(null);
    setLoading(true);
    void loadWorkbench();
    void loadRecoveryAlerts();
    void loadPersonalPerformance();
    void loadAutomationOverview();
    /* eslint-disable-next-line react-hooks/exhaustive-deps */
    return () => { workbenchRequestRef.current += 1; };
  }, [selectedSalesId, date, canManage, role]);
  useEffect(() => {
    void loadRingCentral();
    const url = new URL(window.location.href);
    const result = url.searchParams.get('ringcentral');
    if (!result) return;

    const context = readWorkbenchReturnContext();
    if (context.date) setDate(context.date);
    if (canManage && context.selectedSalesId) setSelectedSalesId(context.selectedSalesId);
    if (context.filter && workbenchFilters.includes(context.filter as typeof workbenchFilters[number])) {
      setFilter(context.filter as typeof workbenchFilters[number]);
    }
    setReturnLeadId(context.leadId || null);
    sessionStorage.removeItem(workbenchReturnKey);
    url.searchParams.delete('ringcentral');
    window.history.replaceState({}, '', `${url.pathname}${url.search}${url.hash}`);

    if (result === 'connected') toast.success('RingCentral 已连接，已返回刚才的工作位置。');
    if (result === 'failed') toast.error('RingCentral 连接失败，已返回刚才的工作位置。');
    if (result === 'cancelled') toast.message('已取消 RingCentral 授权，已返回刚才的工作位置。');
    if (!context.leadId && typeof context.scrollY === 'number') {
      window.requestAnimationFrame(() => window.scrollTo({ top: context.scrollY, behavior: 'smooth' }));
    }
  }, [canManage]);
  useEffect(() => {
    if (!returnLeadId || loading || !workbench) return;
    const target = document.querySelector<HTMLElement>(`[data-lead-id="${returnLeadId}"]`);
    if (!target) return;
    window.requestAnimationFrame(() => target.scrollIntoView({ behavior: 'smooth', block: 'center' }));
    setReturnLeadId(null);
  }, [loading, returnLeadId, workbench]);
  useAutoRefresh(async () => { await loadWorkbench({ background: true }); await loadRecoveryAlerts(); await loadPersonalPerformance(); await loadRingCentral(); }, { intervalMs: 30000, enabled: !activeTask && !historyTask && !analysisTask && (!canManage || !!selectedSalesId) });

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
      const currentTask = current && filteredTasks.find(task => task.task_id === current.task_id);
      if (currentTask && currentTask.task_status !== 'completed') return currentTask;
      return filteredTasks.find(task => task.task_status !== 'completed') || filteredTasks[0] || null;
    });
  }, [filteredTasks]);

  const openCall = (task: Task) => {
    if (task.task_status === 'completed') { toast.message('该任务今日已完成，可查看历史联系记录'); return; }
    setSupplementalFollowUp(false); setActiveTask(task); setOutcome('no_answer'); setNotes(''); setNextFollowUpAt(suggestedFollowUpValue('no_answer'));
  };
  const openSupplementalFollowUp = (task: Task) => {
    setSupplementalFollowUp(true); setActiveTask(task); setOutcome(task.lead.status === 'appointment' ? 'appointment' : task.lead.status === 'interested' ? 'interested' : 'callback'); setNotes(''); setNextFollowUpAt(suggestedFollowUpValue(task.lead.status === 'appointment' ? 'appointment' : task.lead.status === 'interested' ? 'interested' : 'callback'));
  };
  const copyPhone = async (task = activeTask) => {
    const number = task ? e164PhoneNumber(task.lead.phone || '') : '';
    if (!number) return toast.error('该线索没有可用电话号码');
    try { await navigator.clipboard.writeText(number); toast.success(`已复制 ${number}`); }
    catch { toast.error('复制失败，请手动选择号码'); }
  };
  const startRingCentralDial = (task = activeTask) => {
    if (!task) return;
    const phone = task.lead.phone || '';
    const number = ringCentralDialNumber(phone);
    if (!number) { toast.error('该线索没有可用电话号码'); return; }
    if (number.length < 10) { toast.error('电话号码位数不足，请先补充正确号码'); return; }
    if (!phone.trim().startsWith('+')) toast.warning(`已按国际号码 ${e164PhoneNumber(phone)} 拨打，建议后续按此格式保存。`);

    // RingCentral's desktop URI expects digits only; an encoded plus sign can fail intermittently.
    window.location.assign(`rcmobile://call?number=${number}`);
    toast.message('已尝试调起 RingCentral；只有保存通话结果后才计入执行记录。');
  };
  const startRingCentralWebDial = (task = activeTask) => {
    if (!task) return;
    const number = ringCentralDialNumber(task.lead.phone || '');
    if (number.length < 10) { toast.error('该线索没有可用电话号码'); return; }
    window.open(`https://app.ringcentral.com/r/call?number=${number}`, '_blank', 'noopener,noreferrer');
    toast.message('已打开 RingCentral 网页拨号；本次不会重复增加拨号记录。');
  };
  const startSystemDial = (task = activeTask) => {
    if (!task) return;
    const number = e164PhoneNumber(task.lead.phone || '');
    if (!number) { toast.error('该线索没有可用电话号码'); return; }
    window.location.assign(`tel:${number}`);
  };
  const submitResult = async () => {
    if (!activeTask) return;
    if (outcome === 'callback' && !nextFollowUpAt) { toast.error('待回访请设置下次跟进时间'); return; }
    if (outcome === 'do_not_contact' && !notes.trim()) { toast.error('禁止再联系请填写商家要求或原因'); return; }
    if (['interested', 'appointment'].includes(outcome) && (!notes.trim() || !nextFollowUpAt)) { toast.error('有意向或已预约必须填写跟进内容和下次跟进时间'); return; }
    setSaving(true);
    try {
      const url = supplementalFollowUp ? `/api/v1/sales-leads/${activeTask.lead.id}/follow-up` : `/api/v1/sales-leads/workbench/tasks/${activeTask.task_id}/result`;
      const response = await invokeWithAuth({ url, method: 'POST', data: { outcome, notes: notes || null, next_follow_up_at: nextFollowUpAt ? new Date(`${nextFollowUpAt}:00+08:00`).toISOString() : null } });
      const defaultMessage = supplementalFollowUp ? '追加跟进已记录，不影响今日任务完成数' : '通话结果已记录，今日任务进度已更新';
      toast.success(response.data?.used_suggested_follow_up ? `${response.data?.message || '通话结果已记录'}，${response.data?.next_action_label || '已自动安排下一步'}` : (response.data?.message || defaultMessage)); setActiveTask(null); setSupplementalFollowUp(false); await loadWorkbench(); await loadRecoveryAlerts(); await loadPersonalPerformance();
    } catch (error: any) { toast.error(error?.data?.detail || error?.message || '通话结果保存失败'); } finally { setSaving(false); }
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

  const progress = !loading && workbench ? `${workbench.completed_count}/${workbench.quota}` : '—/—';
  const dashboardStats = [
    { label: '未完成', value: workbench?.categories.unfinished, icon: ClipboardList },
    { label: '待回访', value: workbench?.categories.callback, icon: CalendarClock },
    { label: '有意向', value: workbench?.categories.interested, icon: Target },
    { label: '已预约', value: workbench?.categories.appointment, icon: CheckCircle2 },
  ];
  return <div className="sales-v3-page">
    <header className="sales-v3-topbar"><div><p className="sales-v3-kicker"><Headphones className="h-3.5 w-3.5" /> T24 Marketing · Sales OS</p><h2>销售今日工作台</h2></div><div className="sales-v3-stats"><span><b>{progress}</b> 今日目标</span><span><b>{loading ? '—' : workbench?.performance.attempted ?? '—'}</b> 已记录</span><span><b>{loading ? '—' : `${workbench?.performance.connection_rate ?? '—'}%`}</b> 接通率</span><span><b>{loading ? '—' : workbench?.performance.interested ?? '—'}</b> 有意向</span><span><b>{loading ? '—' : workbench?.performance.appointments ?? '—'}</b> 已预约</span></div><div className="flex items-end gap-2"><label aria-label="任务日期（北京时间）" className="hidden text-[11px] text-slate-400 lg:block">任务日期<Input className="mt-1 h-8 w-36 bg-white/10 text-white" type="date" value={date} onChange={event => setDate(event.target.value)} /></label>{canManage && <NativeSelect className="h-8 w-32 text-xs" value={selectedSalesId} onChange={setSelectedSalesId} disabled={!assigneesLoaded || !!assigneeLoadError} options={[{ value: '', label: '选择销售' }, ...assignees.map(item => ({ value: String(item.id), label: item.name }))]} />}</div></header>
    {assigneeLoadError && <div className="sales-v3-alert" role="alert">销售人员列表暂时无法读取：{assigneeLoadError}<Button size="sm" variant="outline" onClick={() => void loadAssignees()}>重新加载</Button></div>}
    {loadError && <div className="sales-v3-alert" role="alert">今日任务暂时无法更新：{workbench ? '继续显示上一次成功读取的任务。' : loadError}<Button size="sm" variant="outline" onClick={() => void loadWorkbench()}>重新加载</Button></div>}
    <div className="sales-v3-shell">
      <aside className="sales-v3-queue"><div className="sales-v3-queue-head"><div className="flex items-center justify-between"><h3>今日任务队列</h3><span>{workbench?.assigned_count ?? '—'} 条</span></div><div className="mt-3 flex items-center gap-2"><div className="sales-v3-progress"><span style={{ width: `${workbench ? Math.min(100, Math.round((workbench.completed_count / Math.max(workbench.quota, 1)) * 100)) : 0}%` }} /></div><b>{loading ? '加载中' : canManage && !selectedSalesId ? '未选择' : progress}</b></div><div className="mt-3 grid grid-cols-2 gap-1.5"><Button size="sm" variant={filter === 'all' ? 'default' : 'outline'} onClick={() => setFilter('all')}>全部任务</Button><Button size="sm" variant={filter === 'overdue' ? 'default' : 'outline'} className={overdueFollowUpCount ? 'border-rose-200 text-rose-700' : ''} onClick={() => setFilter('overdue')}>逾期跟进 ({overdueFollowUpCount})</Button></div></div><div className="sales-v3-queue-list">{loading ? <p className="p-5 text-sm text-slate-400">正在加载任务…</p> : visibleTasks.map((task, index) => { const done = task.task_status === 'completed'; const overdue = !done && isFollowUpOverdue(task.lead.next_follow_up_at); const selected = focusedTask?.task_id === task.task_id; return <button key={task.task_id} type="button" data-lead-id={task.lead.id} onClick={() => setFocusedTask(task)} className={`sales-v3-queue-item ${selected ? 'is-active' : ''} ${done ? 'is-done' : ''}`}><span className={`sales-v3-queue-index ${overdue ? 'is-overdue' : ''}`}>{done ? '✓' : index + 1}</span><span className="min-w-0 flex-1"><span className="sales-v3-queue-name" data-name={task.lead.business_name} /><span className="mt-1 block truncate text-[11px] text-slate-500">{task.lead.phone || '未填写电话'} · {task.lead.industry || '行业未采集'}</span></span><span className={`sales-v3-status ${overdue ? 'is-overdue' : ''}`}>{done ? '已完成' : overdue ? '逾期' : statusLabels[task.lead.status] || '待打'}</span></button>; })}{visibleTasks.length < filteredTasks.length && <Button className="m-3 w-[calc(100%-1.5rem)]" size="sm" variant="outline" onClick={() => setVisibleCount(count => count + 20)}>显示更多</Button>}</div></aside>
      <div className="sales-v3-main">{canManage && !selectedSalesId ? <div className="sales-v3-empty">{assigneesLoaded && assignees.length === 0 ? <><p className="font-medium text-slate-700">暂无可用销售人员</p><p className="mt-1 text-xs text-slate-500">请先在员工管理中新增或启用销售员工。</p></> : '请选择销售人员后查看固定任务批次。'}</div> : !focusedTask ? <div className="sales-v3-empty">本分类暂无任务。请从待清洗商家池转入并分配线索。</div> : <><section className="sales-v3-customer"><div className="flex items-start justify-between gap-4"><div className="flex min-w-0 items-center gap-3"><div className="sales-v3-avatar">{focusedTask.lead.business_name.slice(0, 1)}</div><div className="min-w-0"><div className="flex flex-wrap items-center gap-2"><h1>{focusedTask.lead.business_name}</h1><Badge className={statusColor[focusedTask.lead.status] || statusColor.new}>{statusLabels[focusedTask.lead.status] || focusedTask.lead.status}</Badge>{focusedTask.priority && <Badge className={priorityStyle[focusedTask.priority]}>{priorityLabel[focusedTask.priority]}</Badge>}</div><p>#{focusedTask.lead.id} · {focusedTask.lead.industry || '行业未采集'} · {focusedTask.lead.city || focusedTask.lead.state || '地区未采集'}</p></div></div><span className="text-right text-xs text-slate-400">队列<br /><b className="text-lg text-slate-800">{filteredTasks.findIndex(task => task.task_id === focusedTask.task_id) + 1}</b></span></div><div className="mt-5 grid gap-2 sm:grid-cols-3"><div><small>联系人</small><strong>{focusedTask.lead.contact_name || '未填写'}</strong></div><div className="sales-v3-phone"><small>电话</small><strong>{focusedTask.lead.phone || '未填写'}</strong></div><div><small>下次跟进</small><strong>{formatDate(focusedTask.lead.next_follow_up_at)}</strong></div></div><div className="sales-v3-next"><span>下一步</span>{focusedTask.next_action_label || '完成本次联系并如实记录结果'}<Button size="sm" variant="ghost" onClick={() => void openHistory(focusedTask)}><History className="mr-1 h-3.5 w-3.5" />联系历史</Button></div></section><section className="sales-v3-call"><div className="flex items-center justify-between"><h3><PhoneCall className="h-4 w-4 text-blue-600" /> 通话操作</h3><span>拨号只提供辅助入口；保存结果后才计入执行</span></div><div className="mt-4 flex flex-wrap gap-2"><Button className="sales-v3-call-button" disabled={focusedTask.task_status === 'completed' || focusedTask.lead.do_not_contact || focusedTask.lead.is_blacklisted} onClick={() => void startRingCentralDial(focusedTask)}><PhoneCall className="mr-2 h-4 w-4" />开始拨打</Button><Button variant="outline" onClick={() => void copyPhone(focusedTask)}><Clipboard className="mr-1.5 h-3.5 w-3.5" />复制号码</Button><Button variant="outline" onClick={() => void startRingCentralWebDial(focusedTask)}>网页拨号</Button><Button variant="outline" onClick={() => openCall(focusedTask)}><ClipboardList className="mr-1.5 h-3.5 w-3.5" />记录通话</Button></div><div className="mt-5 grid grid-cols-2 gap-2 sm:grid-cols-4">{outcomeOptions.slice(0, 4).map(item => <button key={item.value} type="button" className="sales-v3-outcome" onClick={() => { setOutcome(item.value); setNextFollowUpAt(suggestedFollowUpValue(item.value)); openCall(focusedTask); }}>{item.label}</button>)}</div></section></>}</div>
      <aside className="sales-v3-side"><section><h3>快捷话术</h3><button type="button" onClick={() => toast.message('请在销售知识库维护团队话术。')}><b>开场白</b><span>介绍服务并确认商家当前获客需求</span></button><button type="button" onClick={() => toast.message('请在销售知识库维护团队话术。')}><b>价格异议</b><span>先确认预算，再说明套餐与效果边界</span></button><button type="button" onClick={() => toast.message('请在销售知识库维护团队话术。')}><b>促成预约</b><span>明确时间、联系人和下一步资料</span></button></section><section><h3>当前提示</h3><p>优先查看客户已有的联系记录和下次跟进安排。</p><Button size="sm" variant="outline" className="mt-3 w-full" disabled={!focusedTask} onClick={() => focusedTask && void openAnalysis(focusedTask)}><Sparkles className="mr-1.5 h-3.5 w-3.5" />AI 分析卡</Button></section></aside>
    </div>
    <details className="sales-v3-more"><summary>拨号辅助、线索循环与个人复盘</summary><div className="mt-4 grid gap-3 lg:grid-cols-2"><Card className="border-sky-100"><CardContent className="p-4"><p className="font-semibold text-slate-800">拨号辅助（可选）</p><p className="mt-1 text-xs text-slate-500">RingCentral 已连接只代表授权可用，不代表浏览器已成功拨号或接通。</p>{ringCentral?.configured && <Button className="mt-3" size="sm" variant="outline" onClick={() => void connectRingCentral()}>{ringCentral.connected ? '检查 / 重连' : '连接 RingCentral'}</Button>}</CardContent></Card>{canManage && <Card><CardContent className="p-4"><p className="font-semibold text-slate-800">主管任务配额</p><div className="mt-3 flex gap-2"><Input className="w-24" type="number" min="1" max="300" value={quotaInput} onChange={event => setQuotaInput(event.target.value)} /><Button disabled={!selectedSalesId} onClick={() => void updateQuota()}>保存数量</Button></div></CardContent></Card>}</div></details>
    <Dialog open={!!activeTask} onOpenChange={open => { if (!open) { setActiveTask(null); setSupplementalFollowUp(false); } }}><DialogContent><DialogHeader><DialogTitle>{supplementalFollowUp ? '追加跟进记录' : '记录通话结果'} · {activeTask?.lead.business_name}</DialogTitle></DialogHeader><div className="space-y-4"><div className="rounded-lg border border-blue-100 bg-blue-50 p-3 text-sm text-blue-900"><p className="text-xs font-medium text-blue-700">客户号码</p><Button type="button" size="sm" className="mt-2" onClick={() => void copyPhone()}><Clipboard className="mr-1.5 h-3.5 w-3.5" />复制 {activeTask ? e164PhoneNumber(activeTask.lead.phone) : '-'}</Button><p className="mt-2 text-xs text-blue-700">{supplementalFollowUp ? '这是独立追加跟进，不会重复增加今日任务完成数。' : '请先手动完成拨打，再如实选择结果；只有保存结果才计入执行。'}</p><div className="mt-3 flex flex-wrap gap-2"><Button size="sm" variant="outline" onClick={() => void startRingCentralDial(activeTask)}><PhoneCall className="mr-1 h-3.5 w-3.5" />RingCentral 桌面端</Button><Button size="sm" variant="outline" onClick={() => void startRingCentralWebDial()}><Link2 className="mr-1 h-3.5 w-3.5" />网页拨号</Button><Button size="sm" variant="outline" onClick={() => void startSystemDial()}><PhoneCall className="mr-1 h-3.5 w-3.5" />系统电话</Button></div><p className="mt-2 text-xs text-blue-700">以上均为可选拨号入口，无法自动证明是否接通；最终以员工保存的结果为准。</p></div><div><Label>通话结果</Label><NativeSelect value={outcome} onChange={value => { setOutcome(value); setNextFollowUpAt(suggestedFollowUpValue(value)); }} options={outcomeOptions} /></div><div><Label>下次跟进时间 {['callback', 'interested', 'appointment'].includes(outcome) && '*'}</Label><Input type="datetime-local" value={nextFollowUpAt} onChange={event => setNextFollowUpAt(event.target.value)} disabled={outcome === 'not_interested' || outcome === 'do_not_contact'} /><p className="mt-1 text-xs text-slate-500">系统会按结果先给出建议时间，您可根据商家约定自行调整。</p></div><div><Label>通话备注</Label><Textarea rows={4} value={notes} onChange={event => setNotes(event.target.value)} placeholder="记录商家反馈、需求、预算或禁联原因" /></div><div className="rounded-lg bg-slate-50 p-3 text-xs text-slate-600">当前为员工手动记录，系统不把 RingCentral“已连接”当作真实拨打或接通证明。有意向、已预约和禁联必须填写完整备注。</div><div className="flex justify-end gap-2"><Button variant="outline" onClick={() => { setActiveTask(null); setSupplementalFollowUp(false); }}>取消</Button><Button disabled={saving} onClick={() => void submitResult()}>{saving ? '保存中...' : supplementalFollowUp ? '记录追加跟进' : '完成并记录'}</Button></div></div></DialogContent></Dialog>
    <Dialog open={!!historyTask} onOpenChange={open => !open && setHistoryTask(null)}><DialogContent className="max-h-[80vh] overflow-y-auto"><DialogHeader><DialogTitle>{historyTask?.lead.business_name} · 历史联系记录</DialogTitle></DialogHeader><div className="space-y-3">{history.length ? history.map(item => <div key={item.id} className="rounded-lg border p-3"><div className="flex items-center justify-between"><Badge className={statusColor[item.outcome === 'callback' ? 'follow_up' : item.outcome === 'interested' ? 'interested' : item.outcome === 'appointment' ? 'appointment' : 'contacted']}>{item.outcome_label}</Badge><span className="text-xs text-slate-500">{formatDate(item.called_at)}</span></div><p className="mt-2 whitespace-pre-line text-sm text-slate-700">{item.notes || '未填写备注'}</p><p className="mt-2 text-xs text-slate-500">下次跟进：{formatDate(item.next_follow_up_at)} · 记录人：{item.sales_employee_name || '-'}</p></div>) : <p className="py-8 text-center text-sm text-slate-500">暂无联系记录</p>}</div></DialogContent></Dialog>
    <Dialog open={!!analysisTask} onOpenChange={open => !open && setAnalysisTask(null)}><DialogContent className="max-h-[86vh] max-w-3xl overflow-y-auto"><DialogHeader><DialogTitle>{analysisTask?.lead.business_name} · AI 销售分析卡</DialogTitle></DialogHeader>{!analysis ? <p className="py-8 text-center text-sm text-slate-500">正在读取经主管确认的资料...</p> : !analysis.available ? <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">{analysis.message}</div> : <div className="space-y-3">{analysis.analysis?.warning && <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">{analysis.analysis.warning}</div>}{analysis.analysis?.cards.map((card, index) => <Card key={`${card.title}-${index}`}><CardContent className="p-4"><div className="flex justify-between gap-2"><p className="font-semibold text-slate-900">{card.title}</p><Badge className={card.kind === 'insufficient' ? 'bg-amber-100 text-amber-800' : 'bg-blue-100 text-blue-700'}>{card.kind === 'insufficient' ? '信息不足' : '资料建议'}</Badge></div><p className="mt-2 whitespace-pre-line text-sm leading-6 text-slate-700">{card.content}</p><div className="mt-3 border-t pt-2 text-xs text-slate-500">{card.sources.map((source, sourceIndex) => <p key={sourceIndex}>{source.label}{source.value ? `：${source.value}` : ''} · {formatDate(source.updated_at)}</p>)}</div></CardContent></Card>)}</div>}</DialogContent></Dialog>
  </div>;
}
