import { useEffect, useMemo, useState } from 'react';
import { BarChart3, CalendarClock, CheckCircle2, ChevronRight, ClipboardList, Headphones, History, Link2, PhoneCall, ShieldAlert, Sparkles, Target, Users } from 'lucide-react';
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
type Task = { task_id: number; task_status: string; completed_at?: string; priority?: 'urgent' | 'high' | 'normal'; next_action_label?: string; lead: Lead };
type Workbench = { salesperson: { id: number; name: string }; quota: number; assigned_count: number; completed_count: number; remaining_count: number; is_target_complete: boolean; categories: { unfinished: number; callback: number; interested: number; appointment: number }; performance: { attempted: number; connected: number; interested: number; appointments: number; callbacks_due: number; connection_rate: number }; items: Task[] };
type Assignee = { id: number; name: string };
type HistoryItem = { id: number; outcome: string; outcome_label: string; notes?: string; next_follow_up_at?: string; called_at: string; sales_employee_name?: string };
type Analysis = { available: boolean; message?: string; analysis?: { warning?: string; cards: { title: string; content: string; kind: string; sources: { label: string; value?: string | number; updated_at?: string }[] }[] } };
type RecoveryAlert = { lead_id: number; business_name: string; state: 'watch' | 'recoverable'; message: string; deadline?: string; extension_request?: { reason?: string } | null };
type PersonalPerformance = { rank: number; score: number; confidence: string; score_breakdown: { results: number; execution: number; discipline: number; documentation: number; compliance: number }; metrics: { completion_rate: number; connection_rate: number; interest_rate: number; note_quality_rate: number; overdue_followups: number }; suggestions: string[] };
type RingCentralStatus = { configured: boolean; connected: boolean; degraded?: boolean; needs_reconnect?: boolean; extension_number?: string; last_synced_at?: string; last_error?: string; message?: string };
type WorkbenchReturnContext = { filter?: string; selectedSalesId?: string; date?: string; leadId?: number; scrollY?: number };

const outcomeOptions = [
  { value: 'no_answer', label: '未接通' }, { value: 'callback', label: '待回访' },
  { value: 'interested', label: '有意向' }, { value: 'appointment', label: '已预约' },
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
  if (value === 'not_interested' || value === 'do_not_contact') return '';
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
  useEffect(() => { void loadWorkbench(); void loadRecoveryAlerts(); void loadPersonalPerformance(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [selectedSalesId, date, canManage, role]);
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

  const visibleTasks = useMemo(() => (workbench?.items || []).filter(task => {
    if (filter === 'unfinished') return task.task_status !== 'completed';
    if (filter === 'callback') return task.lead.status === 'follow_up';
    if (filter === 'interested') return task.lead.status === 'interested';
    if (filter === 'appointment') return task.lead.status === 'appointment';
    return true;
  }), [filter, workbench]);

  const openCall = (task: Task) => {
    if (task.task_status === 'completed') { toast.message('该任务今日已完成，可查看历史联系记录'); return; }
    setSupplementalFollowUp(false); setActiveTask(task); setOutcome('no_answer'); setNotes(''); setNextFollowUpAt(suggestedFollowUpValue('no_answer'));
    startRingCentralDial(task, true);
  };
  const openSupplementalFollowUp = (task: Task) => {
    setSupplementalFollowUp(true); setActiveTask(task); setOutcome(task.lead.status === 'appointment' ? 'appointment' : task.lead.status === 'interested' ? 'interested' : 'callback'); setNotes(''); setNextFollowUpAt(suggestedFollowUpValue(task.lead.status === 'appointment' ? 'appointment' : task.lead.status === 'interested' ? 'interested' : 'callback'));
  };
  const recordDialStarted = async (task: Task) => {
    for (let attempt = 0; attempt < 2; attempt += 1) {
      try {
        await invokeWithAuth({ url: `/api/v1/sales-leads/workbench/tasks/${task.task_id}/dial-started`, method: 'POST', data: {} });
        return;
      } catch {
        if (attempt === 0) {
          await new Promise(resolve => window.setTimeout(resolve, 400));
          continue;
        }
        toast.error('电话已调起，但拨号时间暂未同步；请在通话后正常保存结果。');
      }
    }
  };
  const startRingCentralDial = (task = activeTask, shouldRecord = false) => {
    if (!task) return;
    const phone = task.lead.phone || '';
    const number = ringCentralDialNumber(phone);
    if (!number) { toast.error('该线索没有可用电话号码'); return; }
    if (number.length < 10) { toast.error('电话号码位数不足，请先补充正确号码'); return; }
    if (!phone.trim().startsWith('+')) toast.warning(`已按国际号码 ${e164PhoneNumber(phone)} 拨打，建议后续按此格式保存。`);

    // RingCentral's desktop URI expects digits only; an encoded plus sign can fail intermittently.
    window.location.assign(`rcmobile://call?number=${number}`);
    toast.message(shouldRecord ? '已调起 RingCentral；拨号记录正在后台同步。' : '已重新调起 RingCentral；请在通话后保存通话结果。');
    if (shouldRecord) void recordDialStarted(task);
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
  return <div className="space-y-5">
    <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between"><div><div className="mb-1 flex items-center gap-2 text-sm font-medium text-blue-600"><Headphones className="h-4 w-4" /> 独立售前执行区</div><h2 className="text-2xl font-bold text-slate-900">每日100条拨打工作台</h2><p className="mt-1 text-sm text-slate-500">固定每日任务批次，完成后不会自动补充新线索，避免无效刷量。</p></div><div className="flex flex-wrap gap-2"><Input className="w-40" type="date" value={date} onChange={event => setDate(event.target.value)} />{canManage && <NativeSelect className="w-40" value={selectedSalesId} onChange={setSelectedSalesId} options={[{ value: '', label: '选择销售' }, ...assignees.map(item => ({ value: String(item.id), label: item.name }))]} />}</div></div>
    <Card className="border-blue-100 bg-gradient-to-r from-blue-50 to-indigo-50 shadow-sm"><CardContent className="grid gap-4 p-5 lg:grid-cols-[1.3fr_repeat(4,1fr)]"><div><p className="text-sm font-medium text-blue-700">今日任务</p><p className="mt-1 text-4xl font-bold text-slate-900">{progress}</p><p className="mt-1 text-xs text-slate-500">{workbench?.salesperson.name || employee?.name || '当前销售'} · 已固定 {workbench?.assigned_count || 0} 条任务</p></div>{[{ label: '未完成', value: workbench?.categories.unfinished || 0, icon: ClipboardList }, { label: '待回访', value: workbench?.performance.callbacks_due || 0, icon: CalendarClock }, { label: '有意向', value: workbench?.performance.interested || 0, icon: Target }, { label: '已预约', value: workbench?.performance.appointments || 0, icon: CheckCircle2 }].map(stat => <div key={stat.label} className="rounded-xl bg-white/80 p-3"><stat.icon className="h-4 w-4 text-blue-600" /><p className="mt-2 text-xl font-bold text-slate-900">{stat.value}</p><p className="text-xs text-slate-500">{stat.label}</p></div>)}</CardContent></Card>
    <Card className="border-sky-100 shadow-sm"><CardContent className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center"><div className={`flex h-9 w-9 items-center justify-center rounded-full ${ringCentral?.degraded ? 'bg-amber-100 text-amber-700' : ringCentral?.connected ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-100 text-slate-600'}`}><Link2 className="h-4 w-4" /></div><div className="flex-1"><p className="text-sm font-semibold text-slate-800">RingCentral 拨号连接</p><p className={`mt-0.5 text-xs ${ringCentral?.degraded ? 'text-amber-700' : 'text-slate-500'}`}>{ringCentral?.message || (ringCentral?.connected ? `已连接${ringCentral.extension_number ? ` · 分机 ${ringCentral.extension_number}` : ''}。点击拨号会调起您已登录的 RingCentral 桌面应用。` : '正在检查 RingCentral 配置...')}</p></div>{ringCentral?.connected && !ringCentral.needs_reconnect ? <Badge className={`w-fit ${ringCentral.degraded ? 'bg-amber-100 text-amber-700' : 'bg-emerald-100 text-emerald-700'}`}>{ringCentral.degraded ? '连接波动' : '已连接'}</Badge> : <Button size="sm" disabled={!ringCentral?.configured} onClick={() => void connectRingCentral(activeTask?.lead.id)}>{ringCentral?.configured ? '重新连接 RingCentral' : '等待服务器配置'}</Button>}</CardContent></Card>
    {role === 'sales' && personalPerformance && <Card className="border-violet-100 bg-violet-50/50 shadow-sm"><CardContent className="flex flex-col gap-4 p-4 lg:flex-row lg:items-center"><BarChart3 className="h-7 w-7 text-violet-600" /><div className="flex-1"><p className="font-semibold text-slate-900">个人成长评分</p><p className="mt-1 text-xs text-slate-600">近 30 天 #{personalPerformance.rank} · {personalPerformance.confidence}。分数用于帮助改进，不会自动影响薪资或线索归属。</p><div className="mt-3 flex flex-wrap gap-2 text-xs"><Badge className="bg-violet-100 text-violet-700">总分 {personalPerformance.score}/100</Badge><Badge className="bg-white text-slate-700">结果 {personalPerformance.score_breakdown.results}/40</Badge><Badge className="bg-white text-slate-700">执行 {personalPerformance.score_breakdown.execution}/25</Badge><Badge className="bg-white text-slate-700">纪律 {personalPerformance.score_breakdown.discipline}/20</Badge><Badge className="bg-white text-slate-700">备注 {personalPerformance.score_breakdown.documentation}/10</Badge></div></div><div className="max-w-md rounded-lg bg-white/80 p-3 text-sm text-slate-700"><p className="font-medium text-violet-800">本周建议</p><p className="mt-1">{personalPerformance.suggestions[0]}</p></div></CardContent></Card>}
    {role === 'sales' && recoveryAlerts.length > 0 && <Card className="border-amber-200 bg-amber-50/70 shadow-sm"><CardContent className="p-4"><div className="flex items-start gap-3"><ShieldAlert className="mt-0.5 h-5 w-5 text-amber-700" /><div className="min-w-0 flex-1"><p className="font-semibold text-amber-950">线索保护提醒</p><p className="mt-1 text-sm text-amber-900">以下线索尚未完成有效跟进。系统不会自动转给其他销售，但主管可能在查看后回收；如已和商家约好时间，可申请延期保护。</p><div className="mt-3 space-y-2">{recoveryAlerts.slice(0, 5).map(alert => <div key={alert.lead_id} className="flex flex-col gap-2 rounded-lg border border-amber-200 bg-white/80 p-3 sm:flex-row sm:items-center"><div className="flex-1"><p className="text-sm font-medium text-slate-900">{alert.business_name}</p><p className="text-xs text-slate-600">{alert.message}{alert.deadline ? ` · 截止：${formatDate(alert.deadline)}` : ''}</p></div><Button size="sm" variant="outline" disabled={!!alert.extension_request || extensionBusy === alert.lead_id} onClick={() => void requestExtension(alert)}>{alert.extension_request ? '已申请延期' : extensionBusy === alert.lead_id ? '提交中...' : '申请延期'}</Button></div>)}</div></div></div></CardContent></Card>}
    <Card className="border-slate-200 shadow-sm"><CardContent className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center"><div className="flex-1"><p className="text-sm font-semibold text-slate-800">今日执行表现</p><p className="text-xs text-slate-500">只统计今天已保存的通话结果，用于帮助销售调整节奏，不与正式客户成交数据混合。</p></div><div className="grid grid-cols-3 gap-4 text-center sm:flex sm:gap-6"><div><p className="text-lg font-bold text-slate-900">{workbench?.performance.attempted || 0}</p><p className="text-xs text-slate-500">已拨打</p></div><div><p className="text-lg font-bold text-slate-900">{workbench?.performance.connection_rate || 0}%</p><p className="text-xs text-slate-500">接通率</p></div><div><p className="text-lg font-bold text-slate-900">{workbench?.performance.connected || 0}</p><p className="text-xs text-slate-500">有效接通</p></div></div></CardContent></Card>
    {canManage && <Card className="border-slate-200 shadow-sm"><CardContent className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center"><Users className="h-5 w-5 text-indigo-600" /><div className="flex-1"><p className="text-sm font-semibold text-slate-800">主管任务配额</p><p className="text-xs text-slate-500">默认 100 条；调整只影响当前固定任务批次上限，不会在完成后无限自动补充。</p></div><Input className="w-24" type="number" min="1" max="300" value={quotaInput} onChange={event => setQuotaInput(event.target.value)} /><Button disabled={!selectedSalesId} onClick={() => void updateQuota()}>保存数量</Button></CardContent></Card>}
    <div className="flex flex-wrap gap-2">{([{ key: 'all', label: '全部任务', value: workbench?.assigned_count || 0 }, { key: 'unfinished', label: '未完成', value: workbench?.categories.unfinished || 0 }, { key: 'callback', label: '待回访', value: workbench?.categories.callback || 0 }, { key: 'interested', label: '有意向', value: workbench?.categories.interested || 0 }, { key: 'appointment', label: '已预约', value: workbench?.categories.appointment || 0 }] as const).map(item => <Button key={item.key} size="sm" variant={filter === item.key ? 'default' : 'outline'} onClick={() => setFilter(item.key)}>{item.label} ({item.value})</Button>)}</div>
    <div className="grid gap-3">{loading ? <Card><CardContent className="py-12 text-center text-sm text-slate-500">正在加载今日拨打任务...</CardContent></Card> : visibleTasks.length === 0 ? <Card><CardContent className="py-12 text-center text-sm text-slate-500">本分类暂无任务。请由主管从待清洗商家池转入并分配线索。</CardContent></Card> : visibleTasks.map(task => { const done = task.task_status === 'completed'; const canAddFollowUp = done && ['follow_up', 'interested', 'appointment'].includes(task.lead.status) && !task.lead.do_not_contact && !task.lead.is_blacklisted; return <Card key={task.task_id} data-lead-id={task.lead.id} className={done ? 'border-emerald-100 bg-emerald-50/30' : 'border-slate-200 shadow-sm'}><CardContent className="flex flex-col gap-4 p-4 lg:flex-row lg:items-center"><div className="min-w-0 flex-1"><div className="flex flex-wrap items-center gap-2"><p className={`font-semibold ${done ? 'text-slate-500 line-through' : 'text-slate-900'}`}>{task.lead.business_name}</p><Badge className={done ? 'bg-emerald-100 text-emerald-700' : (statusColor[task.lead.status] || statusColor.new)}>{done ? '今日已完成' : (statusLabels[task.lead.status] || task.lead.status)}</Badge>{done && ['follow_up', 'interested', 'appointment'].includes(task.lead.status) && <Badge className={statusColor[task.lead.status]}>{statusLabels[task.lead.status]}</Badge>}{!done && task.priority && <Badge className={priorityStyle[task.priority]}>{priorityLabel[task.priority]}</Badge>}</div><p className="mt-1 text-sm text-slate-600">{task.lead.contact_name || '未填写联系人'} · {task.lead.phone} · {[task.lead.city, task.lead.state, task.lead.country].filter(Boolean).join(', ') || '地区未采集'}</p><p className="mt-1 text-xs text-slate-500">行业：{task.lead.industry || '未采集'} · 下次跟进：{formatDate(task.lead.next_follow_up_at)}</p>{!done && <p className="mt-1 text-xs font-medium text-indigo-600">下一步：{task.next_action_label || '完成本次联系并记录结果'}</p>}{canAddFollowUp && <p className="mt-1 text-xs font-medium text-emerald-700">该商家仍在跟进中，可追加新的通话与回访记录。</p>}</div><div className="flex flex-wrap gap-2"><Button size="sm" variant="outline" onClick={() => void openAnalysis(task)}><Sparkles className="mr-1 h-3.5 w-3.5" />AI分析卡</Button><Button size="sm" variant="outline" onClick={() => void openHistory(task)}><History className="mr-1 h-3.5 w-3.5" />历史</Button>{canAddFollowUp ? <Button size="sm" onClick={() => openSupplementalFollowUp(task)}><PhoneCall className="mr-1 h-3.5 w-3.5" />追加跟进</Button> : <Button size="sm" disabled={done || task.lead.do_not_contact || task.lead.is_blacklisted} onClick={() => openCall(task)}><PhoneCall className="mr-1 h-3.5 w-3.5" />一键拨打</Button>}</div></CardContent></Card>; })}</div>
    <Dialog open={!!activeTask} onOpenChange={open => { if (!open) { setActiveTask(null); setSupplementalFollowUp(false); } }}><DialogContent><DialogHeader><DialogTitle>{supplementalFollowUp ? '追加跟进记录' : '快速标记通话结果'} · {activeTask?.lead.business_name}</DialogTitle></DialogHeader><div className="space-y-4"><div className="rounded-lg border border-blue-100 bg-blue-50 p-3 text-sm text-blue-900"><p className="text-xs font-medium text-blue-700">拨号号码</p><Button type="button" size="sm" className="mt-2" onClick={() => void startRingCentralDial(activeTask, false)}><PhoneCall className="mr-1.5 h-3.5 w-3.5" />拨打 {activeTask ? e164PhoneNumber(activeTask.lead.phone) : '-'}</Button><p className="mt-2 text-xs text-blue-700">{supplementalFollowUp ? '这是独立追加跟进，不会重复增加今日任务完成数。' : '系统已记录首次发起拨打；下面的重试和备用入口不会重复增加记录。'}</p><div className="mt-3 flex flex-wrap gap-2"><Button size="sm" variant="outline" onClick={() => void startRingCentralDial(activeTask, false)}><PhoneCall className="mr-1 h-3.5 w-3.5" />RingCentral 桌面端</Button><Button size="sm" variant="outline" onClick={() => void startRingCentralWebDial()}><Link2 className="mr-1 h-3.5 w-3.5" />网页拨号</Button><Button size="sm" variant="outline" onClick={() => void startSystemDial()}><PhoneCall className="mr-1 h-3.5 w-3.5" />系统电话</Button></div><p className="mt-2 text-xs text-blue-700">桌面端没有响应时，请使用“网页拨号”；手机访问时可使用“系统电话”。</p></div><div><Label>通话结果</Label><NativeSelect value={outcome} onChange={value => { setOutcome(value); setNextFollowUpAt(suggestedFollowUpValue(value)); }} options={outcomeOptions} /></div><div><Label>下次跟进时间 {outcome === 'callback' && '*'}</Label><Input type="datetime-local" value={nextFollowUpAt} onChange={event => setNextFollowUpAt(event.target.value)} disabled={outcome === 'not_interested' || outcome === 'do_not_contact'} /><p className="mt-1 text-xs text-slate-500">系统会按结果先给出建议时间，您可根据商家约定自行调整。</p></div><div><Label>通话备注</Label><Textarea rows={4} value={notes} onChange={event => setNotes(event.target.value)} placeholder="记录商家反馈、需求、预算或禁联原因" /></div><div className="rounded-lg bg-slate-50 p-3 text-xs text-slate-600">通话接通结果、时长及录音将在管理员完成 RingCentral OAuth 授权后自动同步；当前阶段由销售完成结果标记。</div><div className="flex justify-end gap-2"><Button variant="outline" onClick={() => { setActiveTask(null); setSupplementalFollowUp(false); }}>取消</Button><Button disabled={saving} onClick={() => void submitResult()}>{saving ? '保存中...' : supplementalFollowUp ? '记录追加跟进' : '完成并记录'}</Button></div></div></DialogContent></Dialog>
    <Dialog open={!!historyTask} onOpenChange={open => !open && setHistoryTask(null)}><DialogContent className="max-h-[80vh] overflow-y-auto"><DialogHeader><DialogTitle>{historyTask?.lead.business_name} · 历史联系记录</DialogTitle></DialogHeader><div className="space-y-3">{history.length ? history.map(item => <div key={item.id} className="rounded-lg border p-3"><div className="flex items-center justify-between"><Badge className={statusColor[item.outcome === 'callback' ? 'follow_up' : item.outcome === 'interested' ? 'interested' : item.outcome === 'appointment' ? 'appointment' : 'contacted']}>{item.outcome_label}</Badge><span className="text-xs text-slate-500">{formatDate(item.called_at)}</span></div><p className="mt-2 whitespace-pre-line text-sm text-slate-700">{item.notes || '未填写备注'}</p><p className="mt-2 text-xs text-slate-500">下次跟进：{formatDate(item.next_follow_up_at)} · 记录人：{item.sales_employee_name || '-'}</p></div>) : <p className="py-8 text-center text-sm text-slate-500">暂无联系记录</p>}</div></DialogContent></Dialog>
    <Dialog open={!!analysisTask} onOpenChange={open => !open && setAnalysisTask(null)}><DialogContent className="max-h-[86vh] max-w-3xl overflow-y-auto"><DialogHeader><DialogTitle>{analysisTask?.lead.business_name} · AI 销售分析卡</DialogTitle></DialogHeader>{!analysis ? <p className="py-8 text-center text-sm text-slate-500">正在读取经主管确认的资料...</p> : !analysis.available ? <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">{analysis.message}</div> : <div className="space-y-3">{analysis.analysis?.warning && <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">{analysis.analysis.warning}</div>}{analysis.analysis?.cards.map((card, index) => <Card key={`${card.title}-${index}`}><CardContent className="p-4"><div className="flex justify-between gap-2"><p className="font-semibold text-slate-900">{card.title}</p><Badge className={card.kind === 'insufficient' ? 'bg-amber-100 text-amber-800' : 'bg-blue-100 text-blue-700'}>{card.kind === 'insufficient' ? '信息不足' : '资料建议'}</Badge></div><p className="mt-2 whitespace-pre-line text-sm leading-6 text-slate-700">{card.content}</p><div className="mt-3 border-t pt-2 text-xs text-slate-500">{card.sources.map((source, sourceIndex) => <p key={sourceIndex}>{source.label}{source.value ? `：${source.value}` : ''} · {formatDate(source.updated_at)}</p>)}</div></CardContent></Card>)}</div>}</DialogContent></Dialog>
  </div>;
}
