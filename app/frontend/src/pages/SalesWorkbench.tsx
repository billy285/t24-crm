import { useEffect, useMemo, useState } from 'react';
import { BarChart3, CalendarClock, CheckCircle2, ChevronRight, Clipboard, ClipboardList, Headphones, History, Link2, PhoneCall, RefreshCw, ShieldAlert, Sparkles, Target, Users } from 'lucide-react';
import { toast } from 'sonner';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
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
const today = () => new Date().toISOString().slice(0, 10);
const formatDate = (value?: string) => value ? value.slice(0, 16).replace('T', ' ') : '-';
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
const workbenchFilters = ['all', 'unfinished', 'callback', 'interested', 'appointment'] as const;

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
  next.setMinutes(0, 0, 0);
  return new Date(next.getTime() - next.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
}

export default function SalesWorkbench() {
  const { role, isAdmin, employee } = useRole();
  const canManage = isAdmin || role === 'sales_manager';
  const [assignees, setAssignees] = useState<Assignee[]>([]);
  const [selectedSalesId, setSelectedSalesId] = useState('');
  const [date, setDate] = useState(today());
  const [workbench, setWorkbench] = useState<Workbench | null>(null);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<'all' | 'unfinished' | 'callback' | 'interested' | 'appointment'>('all');
  const [activeTask, setActiveTask] = useState<Task | null>(null);
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

  const salesIdParam = canManage ? selectedSalesId : '';
  const loadAssignees = async () => {
    if (!canManage) return;
    const response = await invokeWithAuth({ url: '/api/v1/sales-leads/assignees', method: 'GET' });
    const records = response.data || [];
    setAssignees(records);
    setSelectedSalesId(current => current || (records[0] ? String(records[0].id) : ''));
  };
  const loadWorkbench = async () => {
    if (canManage && !selectedSalesId) return;
    setLoading(true);
    try {
      const params = new URLSearchParams({ target_date: date });
      if (salesIdParam) params.set('sales_employee_id', salesIdParam);
      const response = await invokeWithAuth({ url: `/api/v1/sales-leads/workbench/today?${params}`, method: 'GET' });
      setWorkbench(response.data);
      setQuotaInput(String(response.data?.quota || 100));
    } catch (error: any) {
      toast.error(error?.data?.detail || error?.message || '每日任务加载失败');
    } finally { setLoading(false); }
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
      setAutomationOverview(response.data);
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
  useEffect(() => { void loadWorkbench(); void loadRecoveryAlerts(); void loadPersonalPerformance(); void loadAutomationOverview(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [selectedSalesId, date, canManage, role]);
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
  useAutoRefresh(async () => { await loadWorkbench(); await loadRecoveryAlerts(); await loadPersonalPerformance(); await loadRingCentral(); }, { intervalMs: 30000, enabled: !activeTask && !historyTask && !analysisTask && (!canManage || !!selectedSalesId) });

  const filteredTasks = useMemo(() => (workbench?.items || []).filter(task => {
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
    return String(a.lead.next_follow_up_at || '9999').localeCompare(String(b.lead.next_follow_up_at || '9999'));
  }), [filter, workbench]);
  const visibleTasks = useMemo(() => filteredTasks.slice(0, visibleCount), [filteredTasks, visibleCount]);
  useEffect(() => { setVisibleCount(20); }, [filter, workbench?.salesperson.id, date]);

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
      const response = await invokeWithAuth({ url, method: 'POST', data: { outcome, notes: notes || null, next_follow_up_at: nextFollowUpAt ? new Date(nextFollowUpAt).toISOString() : null } });
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

  const progress = workbench ? `${workbench.completed_count}/${workbench.quota}` : '0/100';
  return <div className="flex flex-col gap-5">
    <div className="order-0 flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between"><div><div className="mb-1 flex items-center gap-2 text-sm font-medium text-blue-600"><Headphones className="h-4 w-4" /> T24 Marketing · Sales Today</div><h2 className="text-2xl font-bold text-slate-900">销售今日工作台</h2><p className="mt-1 text-sm text-slate-500">先完成今天的联系与跟进；系统自动安排固定批次，完成后当天不无限补量。</p></div><div className="flex flex-wrap gap-2"><Input className="w-40" type="date" value={date} onChange={event => setDate(event.target.value)} />{canManage && <NativeSelect className="w-40" value={selectedSalesId} onChange={setSelectedSalesId} options={[{ value: '', label: '选择销售' }, ...assignees.map(item => ({ value: String(item.id), label: item.name }))]} />}</div></div>
    <Card className="order-1 border-blue-100 bg-gradient-to-r from-blue-50 to-indigo-50 shadow-sm"><CardContent className="grid gap-4 p-5 lg:grid-cols-[1.3fr_repeat(4,1fr)]"><div><p className="text-sm font-medium text-blue-700">今日完成进度</p><p className="mt-1 text-4xl font-bold text-slate-900">{progress}</p><p className="mt-1 text-xs text-slate-500">{workbench?.salesperson.name || employee?.name || '当前销售'} · 已固定 {workbench?.assigned_count || 0} 条任务</p></div>{[{ label: '未完成', value: workbench?.categories.unfinished || 0, icon: ClipboardList }, { label: '待回访', value: workbench?.categories.callback || 0, icon: CalendarClock }, { label: '有意向', value: workbench?.categories.interested || 0, icon: Target }, { label: '已预约', value: workbench?.categories.appointment || 0, icon: CheckCircle2 }].map(stat => <div key={stat.label} className="rounded-xl bg-white/80 p-3"><stat.icon className="h-4 w-4 text-blue-600" /><p className="mt-2 text-xl font-bold text-slate-900">{stat.value}</p><p className="text-xs text-slate-500">{stat.label}</p></div>)}</CardContent></Card>
    <details className="order-5 rounded-xl border border-slate-200 bg-white p-4 shadow-sm"><summary className="cursor-pointer text-sm font-semibold text-slate-800">拨号辅助、线索循环与个人复盘 <span className="ml-2 font-normal text-slate-500">需要时再展开</span></summary><div className="mt-4 space-y-4">
    {canManage && automationOverview && <Card className="border-indigo-100 bg-indigo-50/40 shadow-sm"><CardContent className="p-4"><div className="flex flex-col gap-4 lg:flex-row lg:items-center"><div className="flex-1"><div className="flex items-center gap-2"><RefreshCw className="h-5 w-5 text-indigo-600" /><p className="font-semibold text-slate-900">公司线索资产自动循环</p></div><p className="mt-1 text-xs text-slate-600">可复用 {automationOverview.reusable} / 总计 {automationOverview.total} · 当前约可支撑 {automationOverview.estimated_pool_days ?? '-'} 个工作日。成交与分润归属不随执行轮换改变。</p><div className="mt-3 flex flex-wrap gap-2 text-xs"><Badge className="bg-emerald-100 text-emerald-700">现在可分 {automationOverview.counts.eligible}</Badge><Badge className="bg-blue-100 text-blue-700">执行中 {automationOverview.counts.assigned}</Badge><Badge className="bg-amber-100 text-amber-800">跟进保护 {automationOverview.counts.protected}</Badge><Badge className="bg-violet-100 text-violet-700">冷却中 {automationOverview.counts.cooling}</Badge><Badge className="bg-slate-100 text-slate-600">禁止/关闭 {automationOverview.counts.blocked + automationOverview.counts.closed}</Badge></div></div><div className="rounded-lg bg-white p-3 text-xs text-slate-600"><p>未开始 {automationOverview.rules.unstarted_release_hours} 小时自动回收</p><p>未接通 {automationOverview.rules.same_sales_no_answer_attempts} 次后冷却 {automationOverview.rules.no_answer_cooldown_days} 天并换人</p><p>暂不需要 {automationOverview.rules.soft_reject_cooldown_days} 天 · 已有服务商 {automationOverview.rules.existing_provider_cooldown_days} 天</p></div><Button variant="outline" disabled={automationBusy} onClick={() => void runAutomation()}><RefreshCw className={`mr-1.5 h-4 w-4 ${automationBusy ? 'animate-spin' : ''}`} />{automationBusy ? '扫描中' : '立即扫描'}</Button></div></CardContent></Card>}
    <Card className="border-sky-100 shadow-sm"><CardContent className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center"><div className="flex h-9 w-9 items-center justify-center rounded-full bg-sky-100 text-sky-700"><Link2 className="h-4 w-4" /></div><div className="flex-1"><p className="text-sm font-semibold text-slate-800">拨号辅助（可选）</p><p className="mt-0.5 text-xs text-slate-500">默认使用“复制号码 + 手动拨打 + 保存结果”。RingCentral 已连接只代表授权可用，不代表桌面软件一定能被浏览器调起。</p></div>{ringCentral?.configured && <Button size="sm" variant="outline" onClick={() => void connectRingCentral()}>{ringCentral?.connected ? '检查 / 重连' : '连接 RingCentral'}</Button>}</CardContent></Card>
    {role === 'sales' && personalPerformance && <Card className="border-violet-100 bg-violet-50/50 shadow-sm"><CardContent className="flex flex-col gap-4 p-4 lg:flex-row lg:items-center"><BarChart3 className="h-7 w-7 text-violet-600" /><div className="flex-1"><p className="font-semibold text-slate-900">个人成长评分</p><p className="mt-1 text-xs text-slate-600">近 30 天 #{personalPerformance.rank} · {personalPerformance.confidence}。这是管理参考，不自动影响工资或线索归属。</p><div className="mt-3 flex flex-wrap gap-2 text-xs"><Badge className="bg-violet-100 text-violet-700">总分 {personalPerformance.score}/100</Badge><Badge className="bg-white text-slate-700">执行 {personalPerformance.score_breakdown.execution}/25</Badge><Badge className="bg-white text-slate-700">纪律 {personalPerformance.score_breakdown.discipline}/20</Badge><Badge className="bg-white text-slate-700">商机质量 {personalPerformance.score_breakdown.opportunity}/20</Badge><Badge className="bg-white text-slate-700">销售结果 {personalPerformance.score_breakdown.results}/25</Badge><Badge className="bg-white text-slate-700">记录合规 {personalPerformance.score_breakdown.documentation}/10</Badge></div></div><div className="max-w-md rounded-lg bg-white/80 p-3 text-sm text-slate-700"><p className="font-medium text-violet-800">本周建议</p><p className="mt-1">{personalPerformance.suggestions[0]}</p></div></CardContent></Card>}
    </div></details>
    {role === 'sales' && recoveryAlerts.length > 0 && <Card className="order-2 border-amber-200 bg-amber-50/70 shadow-sm"><CardContent className="p-4"><div className="flex items-start gap-3"><ShieldAlert className="mt-0.5 h-5 w-5 text-amber-700" /><div className="min-w-0 flex-1"><p className="font-semibold text-amber-950">线索保护提醒</p><p className="mt-1 text-sm text-amber-900">以下线索尚未完成有效跟进。系统不会自动转给其他销售，但主管可能在查看后回收；如已和商家约好时间，可申请延期保护。</p><div className="mt-3 space-y-2">{recoveryAlerts.slice(0, 5).map(alert => <div key={alert.lead_id} className="flex flex-col gap-2 rounded-lg border border-amber-200 bg-white/80 p-3 sm:flex-row sm:items-center"><div className="flex-1"><p className="text-sm font-medium text-slate-900">{alert.business_name}</p><p className="text-xs text-slate-600">{alert.message}{alert.deadline ? ` · 截止：${formatDate(alert.deadline)}` : ''}</p></div><Button size="sm" variant="outline" disabled={!!alert.extension_request || extensionBusy === alert.lead_id} onClick={() => void requestExtension(alert)}>{alert.extension_request ? '已申请延期' : extensionBusy === alert.lead_id ? '提交中...' : '申请延期'}</Button></div>)}</div></div></div></CardContent></Card>}
    <details className="order-5 rounded-xl border border-slate-200 bg-white p-4 shadow-sm"><summary className="cursor-pointer text-sm font-semibold text-slate-800">执行数据与主管设置 <span className="ml-2 font-normal text-slate-500">需要时再展开</span></summary><div className="mt-4 space-y-4">
    <Card className="border-slate-200 shadow-sm"><CardContent className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center"><div className="flex-1"><p className="text-sm font-semibold text-slate-800">今日执行表现</p><p className="text-xs text-slate-500">只统计员工已保存的通话结果；打开弹窗、复制号码或拨号失败都不计数。</p></div><div className="grid grid-cols-3 gap-4 text-center sm:flex sm:gap-6"><div><p className="text-lg font-bold text-slate-900">{workbench?.performance.attempted || 0}</p><p className="text-xs text-slate-500">已记录</p></div><div><p className="text-lg font-bold text-slate-900">{workbench?.performance.connection_rate || 0}%</p><p className="text-xs text-slate-500">接通率</p></div><div><p className="text-lg font-bold text-slate-900">{workbench?.performance.connected || 0}</p><p className="text-xs text-slate-500">有效接通</p></div></div></CardContent></Card>
    {canManage && <Card className="border-slate-200 shadow-sm"><CardContent className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center"><Users className="h-5 w-5 text-indigo-600" /><div className="flex-1"><p className="text-sm font-semibold text-slate-800">主管任务配额</p><p className="text-xs text-slate-500">默认 100 条；调整只影响当前固定任务批次上限，不会在完成后无限自动补充。</p></div><Input className="w-24" type="number" min="1" max="300" value={quotaInput} onChange={event => setQuotaInput(event.target.value)} /><Button disabled={!selectedSalesId} onClick={() => void updateQuota()}>保存数量</Button></CardContent></Card>}
    </div></details>
    <div className="order-3 flex flex-wrap gap-2">{([{ key: 'all', label: '全部任务', value: workbench?.assigned_count || 0 }, { key: 'unfinished', label: '未完成', value: workbench?.categories.unfinished || 0 }, { key: 'callback', label: '待回访', value: workbench?.categories.callback || 0 }, { key: 'interested', label: '有意向', value: workbench?.categories.interested || 0 }, { key: 'appointment', label: '已预约', value: workbench?.categories.appointment || 0 }] as const).map(item => <Button key={item.key} size="sm" variant={filter === item.key ? 'default' : 'outline'} onClick={() => setFilter(item.key)}>{item.label} ({item.value})</Button>)}</div>
    <div className="order-4 grid gap-3">{loading ? <Card><CardContent className="py-12 text-center text-sm text-slate-500">正在加载今日任务...</CardContent></Card> : visibleTasks.length === 0 ? <Card><CardContent className="py-12 text-center text-sm text-slate-500">本分类暂无任务。请由主管从待清洗商家池转入并分配线索。</CardContent></Card> : visibleTasks.map(task => { const done = task.task_status === 'completed'; const canAddFollowUp = done && ['follow_up', 'interested', 'appointment'].includes(task.lead.status) && !task.lead.do_not_contact && !task.lead.is_blacklisted; const followUpOverdue = !done && Boolean(task.lead.next_follow_up_at) && String(task.lead.next_follow_up_at).slice(0, 10) < today(); return <Card key={task.task_id} data-lead-id={task.lead.id} className={followUpOverdue ? 'border-rose-200 bg-rose-50/40 shadow-sm' : done ? 'border-emerald-100 bg-emerald-50/30' : 'border-slate-200 shadow-sm'}><CardContent className="flex flex-col gap-4 p-4 lg:flex-row lg:items-center"><div className="min-w-0 flex-1"><div className="flex flex-wrap items-center gap-2"><p className={`font-semibold ${done ? 'text-slate-500 line-through' : 'text-slate-900'}`}>{task.lead.business_name}</p><Badge className={done ? 'bg-emerald-100 text-emerald-700' : (statusColor[task.lead.status] || statusColor.new)}>{done ? '今日已完成' : (statusLabels[task.lead.status] || task.lead.status)}</Badge>{followUpOverdue && <Badge className="bg-rose-100 text-rose-700">跟进已逾期</Badge>}{done && ['follow_up', 'interested', 'appointment'].includes(task.lead.status) && <Badge className={statusColor[task.lead.status]}>{statusLabels[task.lead.status]}</Badge>}{!done && task.priority && <Badge className={priorityStyle[task.priority]}>{priorityLabel[task.priority]}</Badge>}</div><p className="mt-1 text-sm text-slate-600">{task.lead.contact_name || '未填写联系人'} · {task.lead.phone} · {[task.lead.city, task.lead.state, task.lead.country].filter(Boolean).join(', ') || '地区未采集'}</p><p className="mt-1 text-xs text-slate-500">行业：{task.lead.industry || '未采集'} · 下次跟进：{formatDate(task.lead.next_follow_up_at)}</p>{!done && <p className="mt-1 text-xs font-medium text-indigo-600">下一步：{task.next_action_label || '完成本次联系并记录结果'}</p>}{canAddFollowUp && <p className="mt-1 text-xs font-medium text-emerald-700">该商家仍在跟进中，可追加新的通话与回访记录。</p>}</div><div className="flex flex-wrap gap-2"><Button size="sm" variant="outline" onClick={() => void openAnalysis(task)}><Sparkles className="mr-1 h-3.5 w-3.5" />AI分析卡</Button><Button size="sm" variant="outline" onClick={() => void openHistory(task)}><History className="mr-1 h-3.5 w-3.5" />历史</Button><Button size="sm" variant="outline" disabled={done || task.lead.do_not_contact || task.lead.is_blacklisted} onClick={() => void copyPhone(task)}><Clipboard className="mr-1 h-3.5 w-3.5" />复制号码</Button>{canAddFollowUp ? <Button size="sm" onClick={() => openSupplementalFollowUp(task)}><PhoneCall className="mr-1 h-3.5 w-3.5" />追加跟进</Button> : <Button size="sm" disabled={done || task.lead.do_not_contact || task.lead.is_blacklisted} onClick={() => openCall(task)}><ClipboardList className="mr-1 h-3.5 w-3.5" />记录通话</Button>}</div></CardContent></Card>; })}</div>{visibleTasks.length < filteredTasks.length && <div className="order-4 flex justify-center"><Button variant="outline" onClick={() => setVisibleCount(count => count + 20)}>继续显示（剩余 {filteredTasks.length - visibleTasks.length} 条）</Button></div>}
    <Dialog open={!!activeTask} onOpenChange={open => { if (!open) { setActiveTask(null); setSupplementalFollowUp(false); } }}><DialogContent><DialogHeader><DialogTitle>{supplementalFollowUp ? '追加跟进记录' : '记录通话结果'} · {activeTask?.lead.business_name}</DialogTitle></DialogHeader><div className="space-y-4"><div className="rounded-lg border border-blue-100 bg-blue-50 p-3 text-sm text-blue-900"><p className="text-xs font-medium text-blue-700">客户号码</p><Button type="button" size="sm" className="mt-2" onClick={() => void copyPhone()}><Clipboard className="mr-1.5 h-3.5 w-3.5" />复制 {activeTask ? e164PhoneNumber(activeTask.lead.phone) : '-'}</Button><p className="mt-2 text-xs text-blue-700">{supplementalFollowUp ? '这是独立追加跟进，不会重复增加今日任务完成数。' : '请先手动完成拨打，再如实选择结果；只有保存结果才计入执行。'}</p><div className="mt-3 flex flex-wrap gap-2"><Button size="sm" variant="outline" onClick={() => void startRingCentralDial(activeTask)}><PhoneCall className="mr-1 h-3.5 w-3.5" />RingCentral 桌面端</Button><Button size="sm" variant="outline" onClick={() => void startRingCentralWebDial()}><Link2 className="mr-1 h-3.5 w-3.5" />网页拨号</Button><Button size="sm" variant="outline" onClick={() => void startSystemDial()}><PhoneCall className="mr-1 h-3.5 w-3.5" />系统电话</Button></div><p className="mt-2 text-xs text-blue-700">以上均为可选拨号入口，无法自动证明是否接通；最终以员工保存的结果为准。</p></div><div><Label>通话结果</Label><NativeSelect value={outcome} onChange={value => { setOutcome(value); setNextFollowUpAt(suggestedFollowUpValue(value)); }} options={outcomeOptions} /></div><div><Label>下次跟进时间 {['callback', 'interested', 'appointment'].includes(outcome) && '*'}</Label><Input type="datetime-local" value={nextFollowUpAt} onChange={event => setNextFollowUpAt(event.target.value)} disabled={outcome === 'not_interested' || outcome === 'do_not_contact'} /><p className="mt-1 text-xs text-slate-500">系统会按结果先给出建议时间，您可根据商家约定自行调整。</p></div><div><Label>通话备注</Label><Textarea rows={4} value={notes} onChange={event => setNotes(event.target.value)} placeholder="记录商家反馈、需求、预算或禁联原因" /></div><div className="rounded-lg bg-slate-50 p-3 text-xs text-slate-600">当前为员工手动记录，系统不把 RingCentral“已连接”当作真实拨打或接通证明。有意向、已预约和禁联必须填写完整备注。</div><div className="flex justify-end gap-2"><Button variant="outline" onClick={() => { setActiveTask(null); setSupplementalFollowUp(false); }}>取消</Button><Button disabled={saving} onClick={() => void submitResult()}>{saving ? '保存中...' : supplementalFollowUp ? '记录追加跟进' : '完成并记录'}</Button></div></div></DialogContent></Dialog>
    <Dialog open={!!historyTask} onOpenChange={open => !open && setHistoryTask(null)}><DialogContent className="max-h-[80vh] overflow-y-auto"><DialogHeader><DialogTitle>{historyTask?.lead.business_name} · 历史联系记录</DialogTitle></DialogHeader><div className="space-y-3">{history.length ? history.map(item => <div key={item.id} className="rounded-lg border p-3"><div className="flex items-center justify-between"><Badge className={statusColor[item.outcome === 'callback' ? 'follow_up' : item.outcome === 'interested' ? 'interested' : item.outcome === 'appointment' ? 'appointment' : 'contacted']}>{item.outcome_label}</Badge><span className="text-xs text-slate-500">{formatDate(item.called_at)}</span></div><p className="mt-2 whitespace-pre-line text-sm text-slate-700">{item.notes || '未填写备注'}</p><p className="mt-2 text-xs text-slate-500">下次跟进：{formatDate(item.next_follow_up_at)} · 记录人：{item.sales_employee_name || '-'}</p></div>) : <p className="py-8 text-center text-sm text-slate-500">暂无联系记录</p>}</div></DialogContent></Dialog>
    <Dialog open={!!analysisTask} onOpenChange={open => !open && setAnalysisTask(null)}><DialogContent className="max-h-[86vh] max-w-3xl overflow-y-auto"><DialogHeader><DialogTitle>{analysisTask?.lead.business_name} · AI 销售分析卡</DialogTitle></DialogHeader>{!analysis ? <p className="py-8 text-center text-sm text-slate-500">正在读取经主管确认的资料...</p> : !analysis.available ? <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">{analysis.message}</div> : <div className="space-y-3">{analysis.analysis?.warning && <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">{analysis.analysis.warning}</div>}{analysis.analysis?.cards.map((card, index) => <Card key={`${card.title}-${index}`}><CardContent className="p-4"><div className="flex justify-between gap-2"><p className="font-semibold text-slate-900">{card.title}</p><Badge className={card.kind === 'insufficient' ? 'bg-amber-100 text-amber-800' : 'bg-blue-100 text-blue-700'}>{card.kind === 'insufficient' ? '信息不足' : '资料建议'}</Badge></div><p className="mt-2 whitespace-pre-line text-sm leading-6 text-slate-700">{card.content}</p><div className="mt-3 border-t pt-2 text-xs text-slate-500">{card.sources.map((source, sourceIndex) => <p key={sourceIndex}>{source.label}{source.value ? `：${source.value}` : ''} · {formatDate(source.updated_at)}</p>)}</div></CardContent></Card>)}</div>}</DialogContent></Dialog>
  </div>;
}
