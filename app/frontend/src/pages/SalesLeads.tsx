import '@/pages/crm-sales-visual-polish.css';
import { CrmFormDialogContent, CrmFormDialogHeader, CrmFormDialogBody, CrmFormDialogFooter } from '@/components/ui/dialog';
import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  ArrowRightLeft, Ban, BarChart3, CheckCircle2, ChevronDown, Clipboard, ClipboardCheck, Clock3, Edit3, FileText, History, Link2, MessageSquarePlus, MoreHorizontal, Phone, PhoneCall, PhoneOff, Plus, Radio, Search, ShieldAlert, Timer, Trash2, Users,
} from 'lucide-react';
import { toast } from 'sonner';

import '@/components/sales-center.css';
import './sales-workspace.css';
import './sales-leads-refined.css';
import './crm-sales-compact.css';
import CompactFinanceTable from '@/components/CompactFinanceTable';
import SalesIntelligenceCenter from '@/components/SalesIntelligenceCenter';
import SalesLeadDossier from '@/components/SalesLeadDossier';
import SalesDealHandoffDialog from '@/components/SalesDealHandoffDialog';
import SalesDealHandoffQueue from '@/components/SalesDealHandoffQueue';
import SalesSharedDossiers from '@/components/SalesSharedDossiers';
import SalesFollowUpQuick from '@/components/SalesFollowUpQuick';
import SalesLocalTime, { useSalesContactWindow } from '@/components/SalesLocalTime';
import { useUnsavedChanges } from '@/lib/use-unsaved-changes';
import { useSalesListPosition } from '@/lib/use-sales-list-position';
import { SalesLeadPulse, LeadContactSnapshot, LeadProgressSnapshot, LeadNextStep } from '@/components/SalesLeadSnapshot';
import { salesApi, type LeadInsight } from '@/lib/sales-intelligence';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import CustomerPhoneDial from '@/components/CustomerPhoneDial';
import { Card, CardContent } from '@/components/ui/card';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { NativeSelect } from '@/components/ui/native-select';
import { Textarea } from '@/components/ui/textarea';
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { formatBusinessDateTimeInput, parseBusinessDateTimeInput } from '@/lib/business-date';
import { formatPhoneNumber, getPhoneCopyValue, parsePhoneNumber } from '@/lib/phone-format';
import { readFollowUpDraft, writeFollowUpDraft, removeFollowUpDraft, type DraftPersistence } from '@/lib/sales-followup-draft';
import { useIsMobile } from '@/hooks/use-mobile';
import { useRole } from '@/lib/role-context';
import { invokeWithAuth } from '@/lib/tokenStore';
import { useAutoRefresh } from '@/lib/use-auto-refresh';

type SalesLead = {
  id: number;
  business_name: string;
  contact_name?: string;
  phone: string;
  industry?: string;
  country?: string;
  state?: string;
  city?: string;
  address?: string;
  website?: string;
  source?: string;
  status: string;
  assigned_sales_id?: number;
  assigned_sales_name?: string;
  is_blacklisted: boolean;
  do_not_contact: boolean;
  do_not_contact_reason?: string;
  converted_customer_id?: number;
  notes?: string;
  next_follow_up_at?: string;
  last_contact_at?: string;
  created_at: string;
};

type Assignee = { id: number; name: string; role: string; supervisor?: string };
type ManagementDashboard = { metrics: { assigned: number; completed: number; completion_rate: number; calls: number; connected: number; connection_rate: number; interested: number; interest_rate: number; appointments: number; appointment_rate: number; converted: number; conversion_rate: number }; source_quality: { source: string; total: number; usable: number; quality_rate: number }[]; salespeople: { salesperson: string; calls: number; connected: number; interested: number; appointments: number }[] };
type RecoveryItem = { lead_id: number; business_name: string; assigned_sales_name?: string; status: string; state: 'watch' | 'recoverable' | 'protected' | 'extended' | 'active'; message: string; deadline?: string; extension_request?: { reason?: string; requested_until?: string; requested_by?: string } | null };
type RecoveryOverview = { items: RecoveryItem[]; summary: { recoverable: number; watch: number; protected: number; extended: number; extension_requests: number } };
type PerformanceItem = { rank: number; sales_employee_id: number; salesperson: string; score: number; confidence: string; score_breakdown: { execution: number; discipline: number; opportunity: number; results: number; documentation: number }; metrics: { assigned: number; completed: number; calls: number; connected: number; interested: number; appointments: number; conversions: number; completion_rate: number; connection_rate: number; interest_rate: number; note_quality_rate: number; overdue_followups: number }; suggestions: string[] };
type PerformanceDashboard = { period: { days: number; start_date: string; end_date: string }; items: PerformanceItem[] };
type SalesCallReport = {
  period: { days: number; start_date: string; end_date: string };
  source: { status: 'verified' | 'waiting_provider_data' | 'no_salespeople'; label: string; provider: string };
  summary: { provider_calls: number; connected: number; not_connected: number; connection_rate: number; total_talk_seconds: number; average_talk_seconds: number; crm_records: number; linked_records: number; link_rate: number; interested: number; appointments: number; conversions: number; assigned: number; completed: number; completion_rate: number };
  result_breakdown: { label: string; count: number; rate: number }[];
  daily: { date: string; calls: number; connected: number; talk_seconds: number; connection_rate: number }[];
  employees: { sales_employee_id: number; salesperson: string; provider_calls: number; connected: number; not_connected: number; connection_rate: number; total_talk_seconds: number; average_talk_seconds: number; crm_records: number; linked_records: number; link_rate: number; interested: number; appointments: number; no_answer_records: number; conversions: number; assigned: number; completed: number; completion_rate: number }[];
  recent_calls: { id: number; salesperson: string; business_name?: string; remote_phone?: string; started_at?: string; connected: boolean; duration_seconds: number; result: string; crm_recorded: boolean }[];
};
type CallHistoryItem = { id: number; outcome: string; outcome_label: string; notes?: string; next_follow_up_at?: string; called_at: string; sales_employee_name?: string };
const statusOptions = [
  { value: 'new', label: '新线索' },
  { value: 'contacted', label: '已联系' },
  { value: 'follow_up', label: '待跟进' },
  { value: 'interested', label: '有意向' },
  { value: 'appointment', label: '已预约' },
  { value: 'lost', label: '无意向' },
  { value: 'blocked', label: '禁止联系' },
];

const statusLabels = Object.fromEntries(statusOptions.map(item => [item.value, item.label]));
const statusColors: Record<string, string> = {
  new: 'bg-slate-100 text-slate-700',
  contacted: 'bg-blue-100 text-blue-700',
  follow_up: 'bg-amber-100 text-amber-700',
  interested: 'bg-emerald-100 text-emerald-700',
  appointment: 'bg-cyan-100 text-cyan-700',
  lost: 'bg-zinc-100 text-zinc-600',
  blocked: 'bg-rose-100 text-rose-700',
};

const followUpOutcomeOptions = [
  { value: 'no_answer', label: '未接通' },
  { value: 'callback', label: '待回访' },
  { value: 'interested', label: '有意向' },
  { value: 'appointment', label: '已预约' },
  { value: 'not_interested', label: '无意向' },
  { value: 'do_not_contact', label: '禁止再联系' },
];
const emptyForm = {
  business_name: '', contact_name: '', phone: '', industry: '', country: 'US', state: '', city: '',
  address: '', website: '', source: 'manual', status: 'new', assigned_sales_id: '', notes: '',
  is_blacklisted: false, do_not_contact: false, do_not_contact_reason: '', next_follow_up_at: '',
};

function formatDate(value?: string) {
  if (!value) return '-';
  return formatBusinessDateTimeInput(value).replace('T', ' ');
}

function formatDuration(seconds: number) {
  const safeSeconds = Math.max(0, Math.round(seconds || 0));
  const hours = Math.floor(safeSeconds / 3600);
  const minutes = Math.floor((safeSeconds % 3600) / 60);
  const remainSeconds = safeSeconds % 60;
  if (hours) return `${hours}小时${minutes}分`;
  if (minutes) return `${minutes}分${remainSeconds}秒`;
  return `${remainSeconds}秒`;
}

function LeadCommunication({ notes, insight, loading }: { notes?: string; insight?: LeadInsight; loading: boolean }) {
  return <div className="slr-communication">
    <div className="slr-note-line"><p className={notes ? 'slr-note' : 'slr-note slr-muted'}>{notes || '暂无沟通摘要'}</p></div>
    <details className="slr-contact-details">
      <summary><span>历史与详情</span><ChevronDown size={14} /></summary>
      <div className="slr-contact-content">{notes && <p className="slr-full-note">{notes}</p>}<LeadContactSnapshot insight={insight} loading={loading} /><LeadProgressSnapshot insight={insight} loading={loading} /></div>
    </details>
  </div>;
}

export default function SalesLeads() {
  const { employee, role } = useRole();
  return <SalesLeadWorkspace key={`${employee?.id || 'unknown'}:${role || 'unknown'}`} />;
}

function SalesLeadWorkspace() {
  const navigate = useNavigate();
  const { role, isAdmin, employee } = useRole();
  const isMobile = useIsMobile();
  const canManage = isAdmin || role === 'sales_manager';
  const [items, setItems] = useState<SalesLead[]>([]);
  const [assignees, setAssignees] = useState<Assignee[]>([]);
  const [stats, setStats] = useState({ total: 0, assigned: 0, unassigned: 0, blacklisted: 0, do_not_contact: 0 });
  const [statsReady, setStatsReady] = useState(false);
  const [leadInsights, setLeadInsights] = useState<Record<number, LeadInsight>>({});
  const [insightsLoading, setInsightsLoading] = useState(false);
  const [insightsError, setInsightsError] = useState(false);
  const [insightRetry, setInsightRetry] = useState(0);
  const [compactRows, setCompactRows] = useState(false);
  const [loading, setLoading] = useState(true);
  const [listError, setListError] = useState(false);
  const [dataErrors, setDataErrors] = useState<string[]>([]);
  const [initialParams] = useState(() => new URLSearchParams(window.location.search));
  const [view, setView] = useState<'leads' | 'calls' | 'performance' | 'intelligence' | 'shared' | 'handoffs'>(() => ['calls', 'performance', 'intelligence', 'shared', 'handoffs'].includes(initialParams.get('view') || '') ? initialParams.get('view') as 'calls' | 'performance' | 'intelligence' | 'shared' | 'handoffs' : 'leads');
  const [dossierId, setDossierId] = useState<number | null>(() => { const value = Number(initialParams.get('dossier')); return Number.isSafeInteger(value) && value > 0 ? value : null; });
  const requestedQuoteRef = useRef(false);
  const [search, setSearch] = useState(() => initialParams.get('search')?.slice(0,200) || '');
  const [statusFilter, setStatusFilter] = useState(() => statusOptions.some(item => item.value === initialParams.get('status')) ? initialParams.get('status')! : '');
  const [dueRange, setDueRange] = useState(() => ['today', 'overdue'].includes(initialParams.get('due_range') || '') ? initialParams.get('due_range')! : '');
  const [contactFilter, setContactFilter] = useState(() => ['contactable', 'do_not_contact', 'blacklisted'].includes(initialParams.get('contact_rule') || '') ? initialParams.get('contact_rule')! : '');
  const [filtersExpanded, setFiltersExpanded] = useState(false);
  const [page, setPage] = useState(() => Math.max(1, Math.min(100000, Number(initialParams.get('page')) || 1)));
  const [pageSize, setPageSize] = useState(() => [20,50,100].includes(Number(initialParams.get('page_size'))) ? Number(initialParams.get('page_size')) : 20);
  const [total, setTotal] = useState(0);
  const [showForm, setShowForm] = useState(false);
  const [followUpOnly, setFollowUpOnly] = useState(false);
  const [editing, setEditing] = useState<SalesLead | null>(null);
  const [form, setForm] = useState(emptyForm);
  const [saving, setSaving] = useState(false);
  const [dashboard, setDashboard] = useState<ManagementDashboard | null>(null);
  const [dealLeadId, setDealLeadId] = useState<number | null>(null);
  const [handoffQueueVersion, setHandoffQueueVersion] = useState(0);
  const [recoveryOverview, setRecoveryOverview] = useState<RecoveryOverview | null>(null);
  const [recoveryOpen, setRecoveryOpen] = useState(false);
  const [recoveryBusy, setRecoveryBusy] = useState<number | null>(null);
  const [performanceDays, setPerformanceDays] = useState(30);
  const [performanceDashboard, setPerformanceDashboard] = useState<PerformanceDashboard | null>(null);
  const [callReportDays, setCallReportDays] = useState(7);
  const [callReport, setCallReport] = useState<SalesCallReport | null>(null);
  const [callHistory, setCallHistory] = useState<CallHistoryItem[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const historyRequestRef = useRef(0);
  const [followUpSaving, setFollowUpSaving] = useState(false);
  const [followUpPersistence, setFollowUpPersistence] = useState<DraftPersistence>('none');
  const followUpBaseline = useRef('');
  const [followUpForm, setFollowUpForm] = useState({ outcome: 'callback', notes: '', next_follow_up_at: '' });
  const [selectedRecoveryIds, setSelectedRecoveryIds] = useState<number[]>([]);
  const [selectedLeadIds, setSelectedLeadIds] = useState<number[]>([]);
  const [bulkAssigneeId, setBulkAssigneeId] = useState('');
  const loadRequestSeqRef = useRef(0);
  const formBaseline = useRef(JSON.stringify(emptyForm));
  useSalesListPosition(`${employee?.id}:${role}`, !loading);
  const formGuard = useUnsavedChanges(showForm && !followUpOnly && JSON.stringify(form) !== formBaseline.current);
  const contactWindow = useSalesContactWindow(followUpOnly && showForm ? editing?.id : null);
  const sourceReturn = initialParams.get('returnTo') || '';
  const safeReturn = /^\/(sales-workbench|sales-leads|merchant-pool)(?:\?|$)/.test(sourceReturn) && !sourceReturn.includes('\\') ? sourceReturn : '';
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const fields = { view: view === 'leads' ? '' : view, search, status: statusFilter, contact_rule: contactFilter, due_range: dueRange, page: page > 1 ? String(page) : '', page_size: pageSize !== 20 ? String(pageSize) : '' };
    Object.entries(fields).forEach(([key, value]) => value ? params.set(key, value) : params.delete(key));
    window.history.replaceState(window.history.state, '', `/sales-leads${params.size ? `?${params}` : ''}`);
  }, [view, search, statusFilter, contactFilter, dueRange, page, pageSize]);

  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const loadData = async (options?: { page?: number; background?: boolean }) => {
    const requestId = ++loadRequestSeqRef.current;
    const requestPage = options?.page ?? page;
    if (!options?.background) setLoading(true);
    const params = new URLSearchParams({ skip: String((requestPage - 1) * pageSize), limit: String(pageSize) });
    if (search.trim()) params.set('search', search.trim());
    if (statusFilter) params.set('status', statusFilter);
    if (contactFilter) params.set('contact_rule', contactFilter);
    if (dueRange) params.set('due_range', dueRange);
    try {
      const coreRequests = [
        invokeWithAuth({ url: `/api/v1/sales-leads?${params.toString()}`, method: 'GET' }),
        invokeWithAuth({ url: '/api/v1/sales-leads/stats', method: 'GET' }),
        invokeWithAuth({ url: `/api/v1/sales-leads/dashboard/call-report?days=${callReportDays}`, method: 'GET' }),
      ];
      const managementRequests = canManage ? [
        invokeWithAuth({ url: '/api/v1/sales-leads/assignees', method: 'GET' }),
        invokeWithAuth({ url: '/api/v1/sales-leads/dashboard/management', method: 'GET' }),
        invokeWithAuth({ url: `/api/v1/sales-leads/dashboard/performance?days=${performanceDays}`, method: 'GET' }),
        invokeWithAuth({ url: '/api/v1/sales-leads/recovery/overview', method: 'GET' }),
      ] : [];
      const [coreResults, managementResults] = await Promise.all([
        Promise.allSettled(coreRequests),
        Promise.allSettled(managementRequests),
      ]);
      if (requestId !== loadRequestSeqRef.current) return;

      const [listResult, statsResult, callReportResult] = coreResults;
      const failedSections: string[] = [];
      if (listResult.status === 'fulfilled') {
        const nextItems = listResult.value.data?.items || [];
        setItems(nextItems);
        setListError(false);
        setTotal(listResult.value.data?.total || 0);
        setSelectedLeadIds(current => current.filter(id => nextItems.some((item: SalesLead) => item.id === id)));
      } else {
        setListError(true);
        setSelectedLeadIds([]);
        failedSections.push('线索列表');
      }
      if (statsResult.status === 'fulfilled') { setStats(statsResult.value.data || stats); setStatsReady(true); }
      else failedSections.push('统计');
      if (callReportResult.status === 'fulfilled') setCallReport(callReportResult.value.data || null);
      else failedSections.push('真实通话报告');

      if (canManage) {
        const [assigneeResult, dashboardResult, performanceResult, recoveryResult] = managementResults;
        if (assigneeResult?.status === 'fulfilled') setAssignees(assigneeResult.value.data || []);
        else failedSections.push('负责人');
        if (dashboardResult?.status === 'fulfilled') setDashboard(dashboardResult.value.data || null);
        else failedSections.push('管理看板');
        if (performanceResult?.status === 'fulfilled') setPerformanceDashboard(performanceResult.value.data || null);
        else failedSections.push('绩效');
        if (recoveryResult?.status === 'fulfilled') setRecoveryOverview(recoveryResult.value.data || null);
        else failedSections.push('保护提醒');
      }
      setDataErrors(failedSections.filter(section => section !== '线索列表'));
    } catch (error: any) {
      if (requestId === loadRequestSeqRef.current) { setListError(true); setSelectedLeadIds([]); }
    } finally {
      if (requestId === loadRequestSeqRef.current) setLoading(false);
    }
  };

  useEffect(() => {
    const timer = window.setTimeout(() => void loadData(), search.trim() ? 300 : 0);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, pageSize, search, statusFilter, contactFilter, dueRange, performanceDays, callReportDays]);
  useEffect(() => () => { loadRequestSeqRef.current += 1; historyRequestRef.current += 1; }, []);

  useAutoRefresh(() => loadData({ background: true }), { intervalMs: 30000, enabled: !showForm && !dealLeadId });

  useEffect(() => {
    if (view !== 'leads' || !items.length) return;
    let current = true;
    setInsightsLoading(true);
    setInsightsError(false);
    setLeadInsights({});
    const params = new URLSearchParams({ limit: String(items.length) });
    items.forEach(item => params.append('lead_ids', String(item.id)));
    salesApi<{ items: LeadInsight[] }>(`/leads?${params}`)
      .then(data => { if (current) setLeadInsights(Object.fromEntries(data.items.map(item => [item.id, item]))); })
      .catch(() => { if (current) setInsightsError(true); })
      .finally(() => { if (current) setInsightsLoading(false); });
    return () => { current = false; };
  }, [items, view, insightRetry]);

  const scopeText = useMemo(() => {
    if (isAdmin) return '全部线索';
    if (role === 'sales_manager') return '直属团队线索';
    return `${employee?.name || '当前销售'}的线索`;
  }, [employee?.name, isAdmin, role]);

  const copyLeadPhone = async (lead: SalesLead) => {
    try {
      const value = getPhoneCopyValue(lead.phone, lead.country);
      if (!value) { toast.error('请先补齐国家和有效电话号码'); return; }
      await navigator.clipboard.writeText(value);
      toast.success(`已复制 ${lead.business_name} 的电话`);
    } catch {
      toast.error('电话号码复制失败，请长按号码复制');
    }
  };

  const openCreate = () => {
    setEditing(null);
    setFollowUpOnly(false);
    formBaseline.current = JSON.stringify(emptyForm);
    setForm(emptyForm);
    setShowForm(true);
  };

  const loadCallHistory = async (leadId: number) => {
    const requestId = ++historyRequestRef.current;
    setHistoryLoading(true);
    try {
      const response = await invokeWithAuth({ url: `/api/v1/sales-leads/${leadId}/call-history`, method: 'GET' });
      if (requestId === historyRequestRef.current) setCallHistory(response.data || []);
    } catch (error: any) {
      if (requestId !== historyRequestRef.current) return;
      setCallHistory([]);
      toast.error(error?.data?.detail || error?.message || '跟进时间线加载失败');
    } finally {
      if (requestId === historyRequestRef.current) setHistoryLoading(false);
    }
  };

  const openEdit = (lead: SalesLead, followUp = false) => {
    if (!followUp) { setDossierId(lead.id); return; }
    setFollowUpOnly(followUp);
    setEditing(lead);
    const nextForm = {
      business_name: lead.business_name || '', contact_name: lead.contact_name || '', phone: lead.phone || '',
      industry: lead.industry || '', country: lead.country || '', state: lead.state || '', city: lead.city || '',
      address: lead.address || '', website: lead.website || '', source: lead.source || '', status: lead.status || 'new',
      assigned_sales_id: lead.assigned_sales_id ? String(lead.assigned_sales_id) : '', notes: lead.notes || '',
      is_blacklisted: !!lead.is_blacklisted, do_not_contact: !!lead.do_not_contact,
      do_not_contact_reason: lead.do_not_contact_reason || '', next_follow_up_at: formatBusinessDateTimeInput(lead.next_follow_up_at),
    };
    formBaseline.current = JSON.stringify(nextForm);
    setForm(nextForm);
    setCallHistory([]);
    const initial = { outcome: lead.status === 'appointment' ? 'appointment' : lead.status === 'interested' ? 'interested' : 'callback', notes: '', next_follow_up_at: formatBusinessDateTimeInput(lead.next_follow_up_at) };
    followUpBaseline.current = JSON.stringify(initial);
    const saved = followUp && !lead.do_not_contact && !lead.is_blacklisted && !lead.converted_customer_id
      ? readFollowUpDraft({ userId: Number(employee?.id), salesId: lead.assigned_sales_id, leadId: lead.id }) : null;
    setFollowUpForm(saved?.value || initial);
    setFollowUpPersistence(saved?.persistence || 'none');
    setShowForm(true);
    void loadCallHistory(lead.id);
  };

  const hasFollowUpDraft = () => !!editing && followUpOnly && JSON.stringify(followUpForm) !== followUpBaseline.current;
  useEffect(() => {
    if (!showForm || !followUpOnly || !editing || editing.do_not_contact || editing.is_blacklisted || editing.converted_customer_id) return;
    if (JSON.stringify(followUpForm) === followUpBaseline.current) return;
    setFollowUpPersistence(writeFollowUpDraft({ userId: Number(employee?.id), salesId: editing.assigned_sales_id, leadId: editing.id }, followUpForm));
  }, [showForm, followUpOnly, followUpForm, editing, employee?.id]);

  useEffect(() => {
    if (!followUpOnly || !hasFollowUpDraft() || followUpPersistence === 'session') return;
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ''; };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [showForm, followUpOnly, followUpForm, followUpPersistence]);

  const discardFollowUpDraft = () => {
    if (!editing || saving || followUpSaving || !window.confirm('确认清空本次草稿？已保存的历史记录会保留。')) return;
    if (!removeFollowUpDraft({ userId: Number(employee?.id), salesId: editing.assigned_sales_id, leadId: editing.id })) toast.warning('本页已清空草稿；浏览器存储不可写，刷新可能恢复旧内容');
    setFollowUpForm(JSON.parse(followUpBaseline.current));
    setFollowUpPersistence('none');
  };
  const closeForm = (open: boolean) => {
    if (!open && (saving || followUpSaving)) return;
    if (!open && !followUpOnly && !formGuard.confirmDiscard()) return;
    if (!open) historyRequestRef.current += 1;
    setShowForm(open);
  };

  const recordFollowUp = async (nextAction: 'stay' | 'quote' = 'stay') => {
    if (!editing || saving || followUpSaving || editing.status === 'new' || editing.is_blacklisted || editing.do_not_contact || editing.converted_customer_id) return;
    if (!followUpForm.notes.trim()) {
      toast.error('请填写本次沟通内容，避免产生空白跟进记录');
      return;
    }
    if (['callback', 'interested', 'appointment'].includes(followUpForm.outcome) && !followUpForm.next_follow_up_at) {
      toast.error('请设置下次跟进时间');
      return;
    }
    const draftScope = { userId: Number(employee?.id), salesId: editing.assigned_sales_id, leadId: editing.id };
    setFollowUpSaving(true);
    try {
      const response = await invokeWithAuth({
        url: `/api/v1/sales-leads/${editing.id}/follow-up`,
        method: 'POST',
        data: {
          outcome: followUpForm.outcome,
          notes: followUpForm.notes.trim(),
          next_follow_up_at: followUpForm.next_follow_up_at ? parseBusinessDateTimeInput(followUpForm.next_follow_up_at) : null,
        },
      });
      if (!removeFollowUpDraft(draftScope)) toast.warning('记录已保存；浏览器存储不可写，刷新可能恢复旧草稿，请勿重复提交');
      setFollowUpPersistence('none');
      const nextValue = formatBusinessDateTimeInput(response.data?.next_follow_up_at);
      followUpBaseline.current = JSON.stringify({ ...followUpForm, notes: '', next_follow_up_at: nextValue });
      const updatedLead = response.data?.lead as SalesLead | undefined;
      const stoppedContact = updatedLead?.do_not_contact || followUpForm.outcome === 'do_not_contact';
      const assignmentChanged = updatedLead && updatedLead.assigned_sales_id !== editing.assigned_sales_id;
      setForm(current => ({
        ...current, status: response.data?.status || current.status, notes: followUpForm.notes.trim(), next_follow_up_at: nextValue,
        ...(stoppedContact ? { do_not_contact: true, do_not_contact_reason: updatedLead?.do_not_contact_reason || followUpForm.notes.trim() } : {}),
        ...(assignmentChanged ? { assigned_sales_id: updatedLead?.assigned_sales_id ? String(updatedLead.assigned_sales_id) : '' } : {}),
      }));
      setEditing(current => current ? ({ ...current, ...updatedLead, status: response.data?.status || current.status, notes: followUpForm.notes.trim(), next_follow_up_at: response.data?.next_follow_up_at || undefined, ...(stoppedContact ? { do_not_contact: true, do_not_contact_reason: updatedLead?.do_not_contact_reason || followUpForm.notes.trim() } : {}) }) : current);
      setFollowUpForm(current => ({ ...current, notes: '', next_follow_up_at: nextValue }));
      await Promise.all([loadCallHistory(editing.id), loadData()]);
      toast.success(response.data?.message || '跟进记录已加入时间线');
      if (nextAction === 'quote') {
        const refreshed = { ...editing, ...updatedLead, status: response.data?.status || editing.status };
        if (!refreshed.do_not_contact && !refreshed.is_blacklisted && !refreshed.converted_customer_id && ['interested', 'appointment'].includes(refreshed.status)) {
          setShowForm(false);
          await openDealControl(refreshed);
        }
      }
    } catch (error: any) {
      toast.error(error?.data?.detail || error?.response?.data?.detail || error?.message || '跟进记录保存失败');
    } finally {
      setFollowUpSaving(false);
    }
  };

  const handleSave = async () => {
    if (saving || followUpSaving) return;
    if (hasFollowUpDraft()) { toast.error('本次跟进尚未保存，请先点击“保存本次跟进”，再保存资料。'); return; }
    if (canManage && (!editing || form.phone !== editing.phone || form.country !== (editing.country || ''))) {
      const phone = parsePhoneNumber(form.phone, form.country);
      if (phone.status !== 'valid') { toast.error(phone.reason || '请填写完整国际电话号码和国家'); return; }
    }
    if (canManage && (!form.business_name.trim() || !form.phone.trim())) {
      toast.error('请填写商家名称和电话');
      return;
    }
    if (form.do_not_contact && !form.do_not_contact_reason.trim()) {
      toast.error('标记禁止再联系时，请填写原因');
      return;
    }
    setSaving(true);
    try {
      const limitedPayload = {
        status: form.status,
        notes: form.notes || null,
        do_not_contact: form.do_not_contact,
        do_not_contact_reason: form.do_not_contact_reason || null,
        next_follow_up_at: form.next_follow_up_at ? (editing && form.next_follow_up_at === formatBusinessDateTimeInput(editing.next_follow_up_at) ? editing.next_follow_up_at : parseBusinessDateTimeInput(form.next_follow_up_at)) : null,
      };
      const managerPayload = {
        ...limitedPayload,
        business_name: form.business_name.trim(), contact_name: form.contact_name || null, phone: form.phone,
        industry: form.industry || null, country: form.country || null, state: form.state || null, city: form.city || null,
        address: form.address || null, website: form.website || null, source: form.source || null,
        assigned_sales_id: form.assigned_sales_id ? Number(form.assigned_sales_id) : null,
        is_blacklisted: form.is_blacklisted,
      };
      if (editing) {
        await invokeWithAuth({
          url: `/api/v1/sales-leads/${editing.id}`,
          method: 'PUT',
          data: canManage ? managerPayload : limitedPayload,
        });
        toast.success('线索已更新');
      } else {
        await invokeWithAuth({ url: '/api/v1/sales-leads', method: 'POST', data: managerPayload });
        toast.success('线索已加入独立销售线索库');
      }
      formGuard.markSaved();
      setShowForm(false);
      await loadData();
    } catch (error: any) {
      toast.error(error?.data?.detail || error?.response?.data?.detail || error?.message || '保存失败');
    } finally {
      setSaving(false);
    }
  };

  const updateProtection = async (lead: SalesLead, field: 'do_not_contact' | 'is_blacklisted', value: boolean) => {
    const reason = field === 'do_not_contact' && value
      ? window.prompt('请输入禁止再联系的原因，例如：商家明确拒绝')
      : undefined;
    if (field === 'do_not_contact' && value && !reason?.trim()) return;
    try {
      await invokeWithAuth({
        url: `/api/v1/sales-leads/${lead.id}`,
        method: 'PUT',
        data: field === 'do_not_contact'
          ? { do_not_contact: value, do_not_contact_reason: value ? reason : null }
          : { is_blacklisted: value },
      });
      toast.success(value ? '已设置保护标记' : '已解除保护标记');
      await loadData();
    } catch (error: any) {
      toast.error(error?.data?.detail || error?.message || '操作失败');
    }
  };

  const openDealControl = (lead: SalesLead) => { setDealLeadId(lead.id); };

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const id = Number(params.get('lead_id'));
    const action = params.get('action');
    if (!Number.isSafeInteger(id) || id <= 0 || !['deal', 'quote', 'followup'].includes(action || '') || requestedQuoteRef.current) return;
    requestedQuoteRef.current = true;
    if (action === 'deal' || action === 'quote') { setDealLeadId(id); return; }
    invokeWithAuth({ url: `/api/v1/sales-leads/${id}`, method: 'GET' })
      .then(response => {
        if (response.data?.id !== id) throw new Error('商机资料与当前客户不一致');
        if (response.data?.status === 'new') { toast.error('新线索请先进入今日拨打'); return; }
        openEdit(response.data, true);
      })
      .catch(error => toast.error(error?.data?.detail || '该商机无法读取，请检查归属权限'));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleRecoveryAction = async (item: RecoveryItem, action: 'reclaim' | 'approve-extension') => {
    const defaultReason = action === 'reclaim' ? '超过保护期未完成有效跟进，主管回收至待分配队列。' : '主管确认当前跟进计划，批准延长线索保护期。';
    const reason = window.prompt('请填写操作原因（会永久保留在归属日志中）', defaultReason);
    if (!reason?.trim()) return;
    setRecoveryBusy(item.lead_id);
    try {
      const endpoint = action === 'reclaim' ? 'reclaim' : 'approve-extension';
      const response = await invokeWithAuth({ url: `/api/v1/sales-leads/${item.lead_id}/recovery/${endpoint}`, method: 'POST', data: { reason: reason.trim() } });
      toast.success(response.data?.message || '操作已完成');
      await loadData();
    } catch (error: any) {
      toast.error(error?.data?.detail || error?.response?.data?.detail || error?.message || '操作失败');
    } finally { setRecoveryBusy(null); }
  };

  const handleBulkRecovery = async (action: 'reclaim' | 'reassign', leadIds = selectedRecoveryIds) => {
    if (listError) return toast.error('请重新加载线索列表后再进行批量操作');
    if (!leadIds.length) return toast.error('请先勾选需要处理的线索');
    if (action === 'reassign' && !bulkAssigneeId) return toast.error('请选择新的销售负责人');
    const reason = window.prompt('请填写本次批量操作原因（会逐条保留在归属日志）', action === 'reclaim' ? '超过保护期未完成有效跟进，批量回收至待分配。' : '主管根据当前线索负荷重新分配。');
    if (!reason?.trim()) return;
    const selectedItems = (recoveryOverview?.items || []).filter(item => leadIds.includes(item.lead_id));
    const hasProtected = selectedItems.some(item => item.state === 'protected');
    if (hasProtected && action === 'reassign' && !window.confirm('选中项包含有意向或已预约线索。确认填写原因并转交吗？')) return;
    setRecoveryBusy(-1);
    try {
      const response = await invokeWithAuth({
        url: '/api/v1/sales-leads/recovery/batch', method: 'POST', data: {
          lead_ids: leadIds, action, reason: reason.trim(),
          assigned_sales_id: action === 'reassign' ? Number(bulkAssigneeId) : null,
          confirm_protected_transfer: hasProtected,
        },
      });
      toast.success(response.data?.message || '批量操作已完成');
      setSelectedRecoveryIds([]);
      setSelectedLeadIds([]);
      setBulkAssigneeId('');
      await loadData();
    } catch (error: any) {
      toast.error(error?.data?.detail || error?.response?.data?.detail || error?.message || '批量操作失败');
    } finally { setRecoveryBusy(null); }
  };

  const customerDetailPath = (customerId: number) => `/customers?detail=${customerId}&tab=info&returnTo=${encodeURIComponent(window.location.pathname + window.location.search)}`;

  const renderLeadAction = (lead: SalesLead) => {
    const protectedLead = lead.is_blacklisted || lead.do_not_contact;
    if (protectedLead) return <Button size="sm" variant="outline" onClick={() => openEdit(lead)}>查看保护</Button>;
    if (lead.converted_customer_id) return <Button size="sm" variant="outline" onClick={() => openDealControl(lead)}>查看成交</Button>;
    if (lead.status === 'new') return <Button size="sm" variant="outline" onClick={() => navigate(`/sales-workbench?lead_id=${lead.id}${lead.assigned_sales_id ? `&sales_employee_id=${lead.assigned_sales_id}` : ''}&returnTo=${encodeURIComponent(window.location.pathname + window.location.search)}`)}>首次拨打</Button>;
    if (['interested', 'appointment'].includes(lead.status)) return isMobile
      ? <Button size="sm" variant="outline" aria-label={`记录跟进：${lead.business_name}`} onClick={() => openEdit(lead, true)}>继续跟进</Button>
      : <><Button size="sm" variant="outline" onClick={() => void openDealControl(lead)}>登记成交</Button><Button size="sm" variant="ghost" aria-label={`记录跟进：${lead.business_name}`} onClick={() => openEdit(lead, true)}><MessageSquarePlus size={16} /></Button></>;
    return <Button size="sm" variant="outline" onClick={() => openEdit(lead, true)}>继续跟进</Button>;
  };

  return (
    <div className={`t24-directory-page t24-sales-leads-page sales-center-ui sc-directory sl-clarity calm-sales-page calm-leads-page app-page crm-sales-compact slr-page slr-view-${view}`}>
      <div className="sc-section-heading slr-page-heading">
        <div>{safeReturn && <Button size="sm" variant="ghost" onClick={() => navigate(safeReturn)}>返回拨打位置</Button>}<h2>{view === 'leads' ? '联系进展' : view === 'calls' ? '通话数据' : view === 'intelligence' ? '经营中心' : view === 'shared' ? '协作档案' : view === 'handoffs' ? '成交与交接' : '历史跟进参考'}</h2></div>
        <div className="slr-heading-tools"><Button type="button" variant={view === 'shared' ? 'secondary' : 'outline'} onClick={() => setView('shared')}>协作档案</Button><span className="slr-scope">{scopeText}</span><DropdownMenu><DropdownMenuTrigger asChild><Button type="button" variant="ghost">更多视图<ChevronDown size={15} /></Button></DropdownMenuTrigger><DropdownMenuContent align="end"><DropdownMenuItem onSelect={() => setView('leads')}>联系进展</DropdownMenuItem><DropdownMenuItem onSelect={() => setView('calls')}>通话数据</DropdownMenuItem><DropdownMenuItem onSelect={() => setView('intelligence')}>经营中心</DropdownMenuItem><DropdownMenuItem onSelect={() => setView('shared')}>协作档案</DropdownMenuItem><DropdownMenuItem onSelect={() => setView('handoffs')}>成交与交接</DropdownMenuItem>{canManage && <DropdownMenuItem onSelect={() => setView('performance')}>历史跟进参考</DropdownMenuItem>}</DropdownMenuContent></DropdownMenu>{canManage && <Button onClick={openCreate}><Plus className="mr-2 h-4 w-4" />新增线索</Button>}</div>
      </div>

      {listError && <div role="alert" className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">线索列表更新失败，当前显示上次读取的结果；批量操作已暂停。<Button variant="outline" className="ml-3" onClick={() => void loadData()}>重新加载列表</Button></div>}
      {dataErrors.length > 0 && <div role="status" className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">部分数据未能更新：{dataErrors.join('、')}。已保留其他可用数据。<Button variant="outline" className="ml-3" onClick={() => void loadData({ background: true })}>重试更新</Button></div>}
      <SalesLeadDossier leadId={dossierId} onClose={() => setDossierId(null)} onSaved={() => void loadData()} />
      {(view === 'leads' || view === 'calls') && <div className="slr-utilities">
        <details className="slr-overview"><summary><BarChart3 size={15} />数据一览<ChevronDown size={14} /></summary><SalesLeadPulse stats={stats} report={callReport} days={callReportDays} onCalls={() => setView('calls')} loading={!statsReady} /></details>
        {view === 'leads' && canManage && recoveryOverview && <details className="sl-recovery">
          <summary><ShieldAlert size={16} /><strong>线索保护</strong><span>可回收 <b>{recoveryOverview.summary.recoverable}</b></span><span>保护期提醒 <b>{recoveryOverview.summary.watch}</b></span>{recoveryOverview.summary.extension_requests > 0 && <span>待审批 <b>{recoveryOverview.summary.extension_requests}</b></span>}<small>查看规则与处理</small><ChevronDown size={14} /></summary>
          <div><p>系统只提示，主管确认后才回收。受保护 {recoveryOverview.summary.protected} 条 · 延期保护 {recoveryOverview.summary.extended} 条 · 禁止联系 {stats.do_not_contact} 条 · 黑名单 {stats.blacklisted} 条。</p>{isMobile ? <p>批量回收与改派请在电脑端处理。</p> : <Button size="sm" variant="outline" onClick={() => setRecoveryOpen(true)}>查看并处理</Button>}</div>
        </details>}
      </div>}
      {view === 'intelligence' && <SalesIntelligenceCenter />}
      {view === 'shared' && <SalesSharedDossiers onOpen={setDossierId} />}
      {view === 'handoffs' && <SalesDealHandoffQueue key={handoffQueueVersion} onOpenLead={setDealLeadId} />}
      {view === 'calls' && !callReport && <div className="sc-panel sc-empty">通话数据暂不可用，请刷新后重试。</div>}
      {view === 'performance' && !dashboard && !performanceDashboard && <div className="sc-panel sc-empty">跟进参考暂不可用，请刷新后重试。</div>}
      {view === 'calls' && callReport && <Card className="overflow-hidden border-blue-200 bg-white shadow-sm">
        <CardContent className="p-0">
          <div className="border-b border-blue-100 bg-gradient-to-br from-slate-950 via-blue-950 to-blue-800 p-4 text-white sm:p-5">
            <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
              <div>
                <div className="flex items-center gap-2"><Radio className="h-5 w-5 text-cyan-300" /><h3 className="text-lg font-bold">真实通话数据报告</h3></div>
                <p className="mt-1 max-w-2xl text-xs leading-5 text-blue-100">拨打、接通、未接通和通话时长只使用RingCentral官方记录；意向、预约和成交使用CRM销售结果，两种口径不混算。</p>
                <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
                  <Badge className={callReport.source.status === 'verified' ? 'bg-emerald-400 text-emerald-950' : 'bg-amber-300 text-amber-950'}>{callReport.source.status === 'verified' ? '官方数据已核验' : '等待官方通话数据'}</Badge>
                  <span className="text-blue-100">{callReport.period.start_date} 至 {callReport.period.end_date}</span>
                </div>
              </div>
              <div className="grid grid-cols-3 gap-1 rounded-xl bg-white/10 p-1 backdrop-blur">
                {[1, 7, 30].map(days => <button key={days} type="button" onClick={() => setCallReportDays(days)} className={`min-h-10 rounded-lg px-3 text-xs font-semibold transition ${callReportDays === days ? 'bg-white text-blue-800 shadow-sm' : 'text-blue-100 hover:bg-white/10'}`}>{days === 1 ? '今日' : `${days}天`}</button>)}
              </div>
            </div>
            <div className="mt-5 grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
              {[
                { label: '真实拨出', value: callReport.summary.provider_calls, helper: 'RingCentral', icon: PhoneCall },
                { label: '已接通', value: callReport.summary.connected, helper: `${callReport.summary.connection_rate}%`, icon: Phone },
                { label: '未接通', value: callReport.summary.not_connected, helper: '官方结果', icon: PhoneOff },
                { label: '接通率', value: `${callReport.summary.connection_rate}%`, helper: `${callReport.summary.connected}/${callReport.summary.provider_calls}`, icon: BarChart3 },
                { label: '接通总时长', value: formatDuration(callReport.summary.total_talk_seconds), helper: '仅已接通', icon: Timer },
                { label: '平均通话', value: formatDuration(callReport.summary.average_talk_seconds), helper: '每次接通', icon: Clock3 },
              ].map(item => <div key={item.label} className="rounded-2xl border border-white/10 bg-white/10 p-3"><div className="flex items-center justify-between"><p className="text-[11px] text-blue-100">{item.label}</p><item.icon className="h-4 w-4 text-cyan-300" /></div><p className="mt-2 text-xl font-bold tracking-tight">{item.value}</p><p className="mt-1 text-[10px] text-blue-200">{item.helper}</p></div>)}
            </div>
          </div>

          <div className="space-y-5 p-4 sm:p-5">
            <div className="grid gap-3 lg:grid-cols-[1.35fr_.65fr]">
              <section className="rounded-2xl border border-slate-200 p-4">
                <div className="flex items-start justify-between gap-3"><div><h4 className="font-semibold text-slate-900">业务转化结果</h4><p className="mt-1 text-xs text-slate-500">销售保存结果后进入统计，不代替RingCentral官方通话事实。</p></div><Badge variant="outline">CRM记录 {callReport.summary.crm_records}</Badge></div>
                <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
                  {[
                    ['有意向', callReport.summary.interested, 'text-emerald-700 bg-emerald-50'],
                    ['已预约', callReport.summary.appointments, 'text-cyan-700 bg-cyan-50'],
                    ['转客户', callReport.summary.conversions, 'text-violet-700 bg-violet-50'],
                    ['任务完成率', `${callReport.summary.completion_rate}%`, 'text-blue-700 bg-blue-50'],
                  ].map(([label, value, tone]) => <div key={label} className={`rounded-xl p-3 ${tone}`}><p className="text-[11px] opacity-70">{label}</p><p className="mt-1 text-xl font-bold">{value}</p></div>)}
                </div>
                <div className="mt-4 flex items-center gap-3 rounded-xl bg-slate-50 px-3 py-2 text-xs text-slate-600"><Link2 className="h-4 w-4 shrink-0 text-blue-600" /><span>官方通话已关联CRM结果 {callReport.summary.linked_records}/{callReport.summary.provider_calls}，匹配覆盖率 <strong className="text-slate-900">{callReport.summary.link_rate}%</strong></span></div>
              </section>

              <section className="rounded-2xl border border-slate-200 p-4">
                <h4 className="font-semibold text-slate-900">未接通原因</h4><p className="mt-1 text-xs text-slate-500">直接采用RingCentral返回结果。</p>
                <div className="mt-3 space-y-2">{callReport.result_breakdown.filter(item => item.label !== '已接通').map(item => <div key={item.label} className="flex items-center justify-between rounded-lg bg-slate-50 px-3 py-2 text-sm"><span className="text-slate-600">{item.label}</span><span className="font-semibold text-slate-900">{item.count} <small className="font-normal text-slate-400">· {item.rate}%</small></span></div>)}{callReport.result_breakdown.filter(item => item.label !== '已接通').length === 0 && <p className="rounded-lg bg-slate-50 px-3 py-6 text-center text-xs text-slate-400">统计期内暂无未接通官方记录</p>}</div>
              </section>
            </div>

            <section>
              <div className="flex items-end justify-between gap-3"><div><h4 className="font-semibold text-slate-900">销售员工数据</h4><p className="mt-1 text-xs text-slate-500">比较工作量、接通质量、通话时长和客户推进结果。</p></div><span className="text-xs text-slate-400">{callReport.employees.length} 位销售</span></div>
              <div className="mt-3 space-y-3 md:hidden">{callReport.employees.map(item => <article key={item.sales_employee_id} className="rounded-2xl border border-slate-200 p-4"><div className="flex items-center justify-between"><div><p className="font-semibold text-slate-950">{item.salesperson}</p><p className="mt-1 text-xs text-slate-500">任务完成 {item.completed}/{item.assigned} · CRM记录 {item.crm_records}</p></div><div className="text-right"><p className="text-2xl font-bold text-blue-700">{item.connection_rate}%</p><p className="text-[10px] text-slate-400">接通率</p></div></div><div className="mt-3 grid grid-cols-3 gap-2 text-center text-xs"><div className="rounded-xl bg-blue-50 p-2"><p className="font-bold text-blue-800">{item.provider_calls}</p><p className="mt-1 text-slate-500">拨出</p></div><div className="rounded-xl bg-emerald-50 p-2"><p className="font-bold text-emerald-800">{item.connected}</p><p className="mt-1 text-slate-500">接通</p></div><div className="rounded-xl bg-rose-50 p-2"><p className="font-bold text-rose-700">{item.not_connected}</p><p className="mt-1 text-slate-500">未接通</p></div></div><div className="mt-3 grid grid-cols-2 gap-2 text-xs text-slate-600"><p>总时长 <strong className="text-slate-900">{formatDuration(item.total_talk_seconds)}</strong></p><p>平均 <strong className="text-slate-900">{formatDuration(item.average_talk_seconds)}</strong></p><p>意向 <strong className="text-slate-900">{item.interested}</strong></p><p>预约 / 转客户 <strong className="text-slate-900">{item.appointments} / {item.conversions}</strong></p></div></article>)}{callReport.employees.length === 0 && <p className="py-8 text-center text-sm text-slate-400">暂无可统计销售</p>}</div>
              <div className="mt-3 hidden overflow-x-auto rounded-2xl border border-slate-200 md:block"><CompactFinanceTable label="销售员工通话数据" legacyClassName="w-full min-w-[1080px] text-left text-sm" expectedHeaders={['销售', '真实拨出', '接通 / 未接通', '接通率', '总时长 / 平均', '意向 / 预约', '转客户', '任务完成', '匹配覆盖']} columns={[
                { label: '销售', indexes: [0], width: 20 }, { label: '真实拨出', indexes: [1], width: 12, align: 'right' },
                { label: '接通 / 未接通', indexes: [2], width: 17, align: 'right' }, { label: '接通率', indexes: [3], width: 12, align: 'right' },
                { label: '意向 / 预约', indexes: [5], width: 16, align: 'right', priority: 2 }, { label: '任务完成', indexes: [7], width: 17, summaryMode: 'first', priority: 2 },
              ]}><thead className="bg-slate-50 text-xs text-slate-500"><tr><th className="px-4 py-3">销售</th><th>真实拨出</th><th>接通 / 未接通</th><th>接通率</th><th>总时长 / 平均</th><th>意向 / 预约</th><th>转客户</th><th>任务完成</th><th>匹配覆盖</th></tr></thead><tbody className="divide-y divide-slate-100">{callReport.employees.map(item => <tr key={item.sales_employee_id}><td className="px-4 py-3 font-semibold text-slate-900">{item.salesperson}</td><td>{item.provider_calls}</td><td><span className="text-emerald-700">{item.connected}</span> / <span className="text-rose-600">{item.not_connected}</span></td><td className="font-semibold text-blue-700">{item.connection_rate}%</td><td>{formatDuration(item.total_talk_seconds)}<p className="text-xs text-slate-400">平均 {formatDuration(item.average_talk_seconds)}</p></td><td>{item.interested} / {item.appointments}</td><td>{item.conversions}</td><td>{item.completed}/{item.assigned}<p className="text-xs text-slate-400">{item.completion_rate}%</p></td><td>{item.linked_records}/{item.provider_calls}<p className="text-xs text-slate-400">{item.link_rate}%</p></td></tr>)}{callReport.employees.length === 0 && <tr><td colSpan={9} className="px-4 py-10 text-center text-slate-400">暂无可统计销售</td></tr>}</tbody></CompactFinanceTable></div>
            </section>

            <section>
              <div><h4 className="font-semibold text-slate-900">最近官方通话</h4><p className="mt-1 text-xs text-slate-500">用于逐条核对销售、商家、接通结果、时长和CRM记录。</p></div>
              <div className="mt-3 divide-y divide-slate-100 overflow-hidden rounded-2xl border border-slate-200">{callReport.recent_calls.slice(0, 12).map(call => <div key={call.id} className="grid gap-2 px-4 py-3 text-sm sm:grid-cols-[minmax(0,1fr)_140px_100px_100px] sm:items-center"><div className="min-w-0"><p className="truncate font-semibold text-slate-900">{call.business_name || (call.remote_phone ? formatPhoneNumber(call.remote_phone) : '未匹配商家')}</p><p className="mt-1 truncate text-xs text-slate-500">{call.salesperson} · {formatDate(call.started_at)}</p></div><Badge className={call.connected ? 'w-fit bg-emerald-100 text-emerald-700' : 'w-fit bg-rose-100 text-rose-700'}>{call.result}</Badge><p className="text-xs text-slate-600">{formatDuration(call.duration_seconds)}</p><p className={`text-xs font-medium ${call.crm_recorded ? 'text-blue-700' : 'text-amber-700'}`}>{call.crm_recorded ? '已记录结果' : '待补CRM结果'}</p></div>)}{callReport.recent_calls.length === 0 && <p className="px-4 py-10 text-center text-sm text-slate-400">统计期内暂无RingCentral官方通话记录</p>}</div>
            </section>
          </div>
        </CardContent>
      </Card>}

      {view === 'performance' && canManage && (dashboard || performanceDashboard) && <details open className="group rounded-2xl border border-violet-100 bg-white shadow-sm">
        <summary className="flex cursor-pointer list-none items-center justify-between gap-3 rounded-2xl px-4 py-4 marker:hidden sm:px-5">
          <div className="flex min-w-0 items-start gap-3"><div className="rounded-xl bg-violet-50 p-2 text-violet-600"><BarChart3 className="h-5 w-5" /></div><div><p className="font-semibold text-slate-900">CRM跟进参考</p><p className="mt-1 text-xs leading-5 text-slate-500">手工保存的跟进与评分，不作为RingCentral官方接通率；手机端按需展开。</p></div></div>
          <ChevronDown className="h-5 w-5 shrink-0 text-slate-400 transition-transform group-open:rotate-180" />
        </summary>
        <div className="space-y-4 border-t border-violet-100 p-3 sm:p-4">
      {dashboard && <Card className="border-indigo-100 bg-gradient-to-r from-indigo-50 via-white to-blue-50 shadow-sm"><CardContent className="p-5"><div className="mb-4 flex items-center gap-2"><BarChart3 className="h-5 w-5 text-indigo-600" /><div><p className="font-semibold text-slate-900">CRM销售管理驾驶舱</p><p className="text-xs text-slate-500">仅统计销售在CRM中保存的跟进结果，不代表真实通话总量。</p></div></div><div className="grid grid-cols-2 gap-3 md:grid-cols-4 lg:grid-cols-7">{[
        ['任务完成', `${dashboard.metrics.completed}/${dashboard.metrics.assigned}`, `${dashboard.metrics.completion_rate}%`], ['接通率', `${dashboard.metrics.connected}/${dashboard.metrics.calls}`, `${dashboard.metrics.connection_rate}%`], ['意向率', String(dashboard.metrics.interested), `${dashboard.metrics.interest_rate}%`], ['预约率', String(dashboard.metrics.appointments), `${dashboard.metrics.appointment_rate}%`], ['成交率', String(dashboard.metrics.converted), `${dashboard.metrics.conversion_rate}%`], ['来源质量', String(dashboard.source_quality.reduce((sum, item) => sum + item.usable, 0)), `${dashboard.source_quality.reduce((sum, item) => sum + item.total, 0)} 条可追溯`], ['销售人数', String(dashboard.salespeople.length), '今日有保存结果']
      ].map(([label, value, sub]) => <div key={label} className="rounded-xl border border-white bg-white/80 p-3"><p className="text-xs text-slate-500">{label}</p><p className="mt-1 text-xl font-bold text-slate-900">{value}</p><p className="mt-1 text-xs text-indigo-600">{sub}</p></div>)}</div></CardContent></Card>}

      {performanceDashboard && (
        <Card className="border-violet-100 bg-gradient-to-r from-violet-50 via-white to-fuchsia-50 shadow-sm">
          <CardContent className="p-4 sm:p-5">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
              <div>
                <div className="flex items-center gap-2"><BarChart3 className="h-5 w-5 text-violet-600" /><p className="font-semibold text-slate-900">销售绩效参考评分</p></div>
                <p className="mt-1 text-xs leading-5 text-slate-500">执行25 + 跟进纪律20 + 商机质量20 + 销售结果25 + 记录合规10。仅统计员工保存的数据，不自动影响工资；少于10条只作参考。</p>
              </div>
              <div className="flex gap-2">{[7, 30].map(days => <Button className="h-11 min-w-16 sm:h-9" key={days} size="sm" variant={performanceDays === days ? 'default' : 'outline'} onClick={() => setPerformanceDays(days)}>{days}天</Button>)}</div>
            </div>
            <div data-testid="sales-performance-mobile-list" className="mt-4 space-y-3 md:hidden">
              {performanceDashboard.items.map(item => (
                <article key={item.sales_employee_id} className="rounded-xl border border-violet-100 bg-white/90 p-4 shadow-sm">
                  <div className="flex items-start justify-between gap-3">
                    <div><p className="font-semibold text-slate-950">#{item.rank} {item.salesperson}</p><p className="mt-0.5 text-xs text-slate-500">{item.confidence}</p></div>
                    <div className="text-right"><p className="text-3xl font-bold tracking-tight text-violet-700">{item.score}</p><p className="text-xs text-slate-400">满分 100</p></div>
                  </div>
                  <div className="mt-3 grid grid-cols-3 gap-2 text-center text-xs">
                    <div className="rounded-lg bg-violet-50 p-2"><p className="font-semibold text-violet-800">{item.metrics.completion_rate}%</p><p className="mt-0.5 text-slate-500">完成率</p></div>
                    <div className="rounded-lg bg-blue-50 p-2"><p className="font-semibold text-blue-800">{item.metrics.connection_rate}%</p><p className="mt-0.5 text-slate-500">接通率</p></div>
                    <div className="rounded-lg bg-amber-50 p-2"><p className="font-semibold text-amber-800">{item.metrics.overdue_followups}</p><p className="mt-0.5 text-slate-500">逾期</p></div>
                  </div>
                  <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 text-xs text-slate-600">
                    <div className="flex justify-between gap-2"><dt>执行</dt><dd className="font-medium text-slate-800">{item.score_breakdown.execution}/25</dd></div>
                    <div className="flex justify-between gap-2"><dt>纪律</dt><dd className="font-medium text-slate-800">{item.score_breakdown.discipline}/20</dd></div>
                    <div className="flex justify-between gap-2"><dt>商机质量</dt><dd className="font-medium text-slate-800">{item.score_breakdown.opportunity}/20</dd></div>
                    <div className="flex justify-between gap-2"><dt>销售结果</dt><dd className="font-medium text-slate-800">{item.score_breakdown.results}/25</dd></div>
                    <div className="col-span-2 flex justify-between gap-2"><dt>记录合规</dt><dd className="font-medium text-slate-800">{item.score_breakdown.documentation}/10</dd></div>
                  </dl>
                  <p className="mt-3 break-words rounded-lg bg-slate-50 p-3 text-xs leading-5 text-slate-600">建议：{item.suggestions[0] || '暂无系统建议'}</p>
                </article>
              ))}
              {performanceDashboard.items.length === 0 && <p className="py-8 text-center text-sm text-slate-500">暂无可评分销售数据</p>}
            </div>
            <div data-testid="sales-performance-desktop-table" className="mt-4 hidden overflow-x-auto md:block"><CompactFinanceTable label="销售绩效" legacyClassName="w-full min-w-[980px] text-left text-sm" expectedHeaders={['排名 / 销售', '总分', '执行', '纪律', '商机质量', '销售结果', '记录合规', '关键数据', '系统建议']} columns={[
                { label: '排名 / 销售', indexes: [0], width: 26, summaryMode: 'first' }, { label: '总分', indexes: [1], width: 12, align: 'right', summaryMode: 'first' },
                { label: '执行', indexes: [2], width: 12, align: 'right', priority: 2 }, { label: '纪律', indexes: [3], width: 12, align: 'right', priority: 2 },
                { label: '商机质量', indexes: [4], width: 14, align: 'right', priority: 3 }, { label: '销售结果', indexes: [5], width: 14, align: 'right' },
              ]}><thead className="border-b text-xs text-slate-500"><tr><th className="pb-2">排名 / 销售</th><th className="pb-2">总分</th><th className="pb-2">执行</th><th className="pb-2">纪律</th><th className="pb-2">商机质量</th><th className="pb-2">销售结果</th><th className="pb-2">记录合规</th><th className="pb-2">关键数据</th><th className="pb-2">系统建议</th></tr></thead><tbody className="divide-y divide-violet-100">{performanceDashboard.items.map(item => <tr key={item.sales_employee_id}><td className="py-3"><p className="font-semibold text-slate-900">#{item.rank} {item.salesperson}</p><p className="text-xs text-slate-500">{item.confidence}</p></td><td className="py-3"><p className="text-2xl font-bold text-violet-700">{item.score}</p><p className="text-xs text-slate-500">/100</p></td><td className="py-3">{item.score_breakdown.execution}/25</td><td className="py-3">{item.score_breakdown.discipline}/20</td><td className="py-3">{item.score_breakdown.opportunity}/20</td><td className="py-3">{item.score_breakdown.results}/25</td><td className="py-3">{item.score_breakdown.documentation}/10</td><td className="py-3 text-xs text-slate-600">完成 {item.metrics.completion_rate}% · 接通 {item.metrics.connection_rate}%<br />意向 {item.metrics.interest_rate}% · 逾期 {item.metrics.overdue_followups}</td><td className="max-w-xs py-3 text-xs text-slate-600">{item.suggestions[0]}</td></tr>)}{performanceDashboard.items.length === 0 && <tr><td colSpan={9} className="py-8 text-center text-sm text-slate-500">暂无可评分销售数据</td></tr>}</tbody></CompactFinanceTable></div>
          </CardContent>
        </Card>
      )}
        </div>
      </details>}

      <section className="sc-lead-panel space-y-4" hidden={view !== 'leads'} aria-label="销售线索列表">
      <Card className={`sc-table-card sl-lead-table ${compactRows ? 'sl-compact' : ''} overflow-hidden border-slate-200 shadow-sm`}>
        <CardContent className="p-0">
          <div className="sl-table-toolbar">
            <div className="slr-list-tools"><nav className="sl-due-views" aria-label="回访时间范围">{[{ value: '', label: '全部进展' }, { value: 'today', label: '今天需跟进' }, { value: 'overdue', label: '逾期' }].map(item => <Button key={item.label} variant="ghost" size="sm" aria-pressed={dueRange === item.value} onClick={() => { setDueRange(item.value); setPage(1); }}>{item.label}</Button>)}</nav>
              <div className="sl-quick-filters" aria-label="快捷线索状态">{[{ value: 'follow_up', label: '待回访' }, { value: 'interested', label: '有意向' }, { value: 'appointment', label: '已预约' }, { value: '', label: '全部' }].map(option => <button key={option.value} type="button" aria-pressed={statusFilter === option.value} onClick={() => { setStatusFilter(option.value); setPage(1); }}>{option.label}</button>)}</div>
              <div className="sl-search-row">
              <div className="relative flex-1"><Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" /><Input aria-label="搜索销售线索" className="pl-9" value={search} onChange={event => { setSearch(event.target.value); setPage(1); }} placeholder="搜索商家、联系人、电话或城市" /></div>
              <Button type="button" variant="outline" aria-expanded={filtersExpanded} aria-controls="sales-lead-extra-filters" onClick={() => setFiltersExpanded(current => !current)}><ChevronDown className="h-4 w-4" />筛选{contactFilter ? ' · 1' : ''}</Button>
              </div>
            </div>
            {filtersExpanded && <div id="sales-lead-extra-filters" className="calm-sales-extra-filters">
              <label><span className="sc-filter-label">线索状态</span><NativeSelect value={statusFilter} onChange={value => { setStatusFilter(value); setPage(1); }} options={[{ value: '', label: '全部状态' }, ...statusOptions]} /></label>
              <label><span className="sc-filter-label">联系规则</span><NativeSelect value={contactFilter} onChange={value => { setContactFilter(value); setPage(1); }} options={[{ value: '', label: '全部联系规则' }, { value: 'contactable', label: '允许联系' }, { value: 'do_not_contact', label: '禁止再联系' }, { value: 'blacklisted', label: '黑名单' }]} /></label>
              {!isMobile && <div><span className="sc-filter-label">列表密度</span><div className="sl-density"><button type="button" aria-pressed={!compactRows} onClick={() => setCompactRows(false)}>标准</button><button type="button" aria-pressed={compactRows} onClick={() => setCompactRows(true)}>紧凑</button></div></div>}
            </div>}
            {(search || statusFilter || contactFilter || dueRange) && <div className="slr-active-filters"><span>{dueRange ? dueRange === 'today' ? '今天需跟进 · ' : '逾期 · ' : ''}{statusFilter ? statusLabels[statusFilter] || statusFilter : '全部状态'}{contactFilter ? ` · ${contactFilter === 'contactable' ? '允许联系' : contactFilter === 'do_not_contact' ? '禁止再联系' : '黑名单'}` : ''}{search && ` · “${search}”`}</span><button type="button" onClick={() => { setSearch(''); setStatusFilter(''); setContactFilter(''); setDueRange(''); setPage(1); }}>清空筛选</button></div>}
          </div>
          {insightsError && <div className="sl-inline-error" role="alert">累计联系数据暂时未能加载，商家资料仍可查看。<Button size="sm" variant="ghost" onClick={() => setInsightRetry(value => value + 1)}>重试</Button></div>}
          {canManage && !isMobile && selectedLeadIds.length > 0 && <div className="sc-bulk-bar flex flex-col gap-3 border-b bg-blue-50/60 px-4 py-3 sm:flex-row sm:items-center"><p className="flex-1 text-sm font-medium text-slate-700">当前页已选 {selectedLeadIds.length} 条，可批量补齐待分配线索或调整负责人</p><NativeSelect className="sm:w-52" value={bulkAssigneeId} onChange={setBulkAssigneeId} options={[{ value: '', label: '选择目标销售' }, ...assignees.map(item => ({ value: String(item.id), label: item.name }))]} /><Button size="sm" variant="outline" disabled={!selectedLeadIds.length || !bulkAssigneeId || recoveryBusy === -1} onClick={() => void handleBulkRecovery('reassign', selectedLeadIds)}>批量分配 / 改派</Button></div>}
          <div data-testid="sales-leads-mobile-list" className="slr-mobile-list divide-y divide-slate-100 md:hidden">
            {loading ? <p className="px-4 py-12 text-center text-sm text-slate-400">正在加载线索...</p>
              : items.length === 0 ? <p className="px-4 py-12 text-center text-sm text-slate-400">当前范围暂无销售线索</p>
              : items.map(lead => {
                const protectedLead = lead.is_blacklisted || lead.do_not_contact;
                return (
                  <article key={lead.id} data-testid="sales-lead-mobile-card" className={`slr-mobile-card ${protectedLead ? 'bg-rose-50/40' : 'bg-white'}`}>
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <button type="button" className="slr-card-name" onClick={() => setDossierId(lead.id)}>{lead.business_name}</button>
                        <p className="mt-0.5 text-xs text-slate-500">{[lead.contact_name, lead.assigned_sales_name || '待分配'].filter(Boolean).join(' · ')}</p>
                      </div>
                      <Badge className={`shrink-0 ${statusColors[lead.status] || statusColors.new}`}>{statusLabels[lead.status] || lead.status}</Badge>
                    </div>
                    {Boolean(protectedLead || lead.converted_customer_id) && <div className="slr-card-flags">{lead.do_not_contact && <Badge className="bg-rose-100 text-rose-700">禁止再联系</Badge>}{lead.is_blacklisted && <Badge className="bg-slate-800 text-white">黑名单</Badge>}{lead.converted_customer_id && <Badge className="bg-emerald-100 text-emerald-700">已转正式客户</Badge>}</div>}
                    <div className="slr-card-meta"><span className={protectedLead ? 'text-slate-400 line-through' : 'text-slate-700'}>{formatPhoneNumber(lead.phone, lead.country)}</span>{(lead.city || lead.state || lead.industry) && <span>{[[lead.city, lead.state].filter(Boolean).join(', '), lead.industry].filter(Boolean).join(' · ')}</span>}</div>
                    {Boolean(lead.status !== 'new' || lead.notes || lead.last_contact_at || leadInsights[lead.id]?.calls || leadInsights[lead.id]?.records) && <LeadCommunication notes={lead.notes} insight={leadInsights[lead.id]} loading={insightsLoading} />}
                    {Boolean(lead.status !== 'new' || protectedLead || lead.converted_customer_id || lead.next_follow_up_at || lead.last_contact_at || leadInsights[lead.id]?.last_contact_at) && <div className="sl-mobile-next"><LeadNextStep insight={leadInsights[lead.id]} nextAt={lead.next_follow_up_at} lastAt={lead.last_contact_at} stopped={protectedLead} converted={!!lead.converted_customer_id} /></div>}
                    <div className="slr-card-actions">
                      {protectedLead ? <Button className="h-11 px-2" variant="outline" disabled><Phone className="h-4 w-4" />拨号</Button> : <CustomerPhoneDial country={lead.country} phone={lead.phone} label="RingCentral" className="w-full" />}
                      {renderLeadAction(lead)}
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild><Button className="h-11 w-11 p-0" variant="outline" aria-label={`更多线索操作：${lead.business_name}`}><MoreHorizontal className="h-5 w-5" /></Button></DropdownMenuTrigger>
                        <DropdownMenuContent align="end" className="w-56">
                          <DropdownMenuItem className="min-h-11" onSelect={() => setDossierId(lead.id)}>累计档案</DropdownMenuItem>{!protectedLead && !lead.converted_customer_id && lead.status !== 'new' && <DropdownMenuItem className="min-h-11" onSelect={() => openEdit(lead, true)}>记录跟进</DropdownMenuItem>}
                          <DropdownMenuItem className="min-h-11" disabled={protectedLead} onSelect={() => { void copyLeadPhone(lead); }}><Clipboard className="mr-2 h-4 w-4" />复制电话</DropdownMenuItem>
                          {canManage && <DropdownMenuItem className="min-h-11" onSelect={() => openEdit(lead)}><Edit3 className="mr-2 h-4 w-4" />编辑线索资料</DropdownMenuItem>}
                          {!lead.converted_customer_id && !protectedLead && <DropdownMenuItem className="min-h-11" onSelect={() => { void openDealControl(lead); }}><ClipboardCheck className="mr-2 h-4 w-4" />{['interested', 'appointment'].includes(lead.status) ? '登记成交' : '登记成交'}</DropdownMenuItem>}
                          {lead.converted_customer_id && <DropdownMenuItem className="min-h-11" onSelect={() => openDealControl(lead)}><CheckCircle2 className="mr-2 h-4 w-4" />查看成交与交接</DropdownMenuItem>}
                          <DropdownMenuItem className="min-h-11" onSelect={() => openEdit(lead)}><ShieldAlert className="mr-2 h-4 w-4" />{canManage ? '保护与黑名单设置' : '禁止联系设置'}</DropdownMenuItem>
                        </DropdownMenuContent>
                      </DropdownMenu>
                    </div>
                  </article>
                );
              })}
          </div>
          {!isMobile && <div data-testid="sales-leads-desktop-table" className="sl-table-scroll">
            <table className="sl-data-table">
              <thead><tr>{canManage && <th className="sl-select-cell"><input type="checkbox" aria-label="选择当前页全部线索" disabled={listError} checked={items.length > 0 && items.every(item => selectedLeadIds.includes(item.id))} onChange={event => setSelectedLeadIds(event.target.checked ? items.map(item => item.id) : [])} /></th>}<th className="slr-merchant-column">商家 / 负责人</th><th className="slr-contact-column">沟通摘要</th><th className="slr-next-column">下一步 <small>北京时间</small></th><th className="sl-actions-cell">操作</th></tr></thead>
              <tbody>
                {loading ? <tr><td colSpan={canManage ? 5 : 4} className="sl-empty">正在加载线索…</td></tr> : items.length === 0 ? <tr><td colSpan={canManage ? 5 : 4} className="sl-empty">当前筛选没有匹配的商家，请调整搜索或筛选条件。</td></tr> : items.map(lead => {
                  const protectedLead = lead.is_blacklisted || lead.do_not_contact;
                  return <tr key={lead.id} className={protectedLead ? 'sl-protected-row' : ''}>
                    {canManage && <td className="sl-select-cell"><input type="checkbox" aria-label={`选择 ${lead.business_name}`} disabled={listError} checked={selectedLeadIds.includes(lead.id)} onChange={event => setSelectedLeadIds(current => event.target.checked ? [...current, lead.id] : current.filter(id => id !== lead.id))} /></td>}
                    <td className="sl-identity-cell"><div className="slr-compact-identity"><button type="button" className="sl-business-name" title={lead.business_name} onClick={() => setDossierId(lead.id)}>{lead.business_name}</button><div className="slr-legacy-identity-meta min-[1024px]:hidden"><div className="sl-identity-meta"><span>{lead.assigned_sales_name || '待分配'}</span><span>{lead.industry || '未分类'}{lead.city || lead.state ? ` · ${[lead.city, lead.state].filter(Boolean).join(', ')}` : ''}</span></div></div><details className="slr-merchant-context hidden min-[1024px]:block"><summary aria-label={`查看${lead.business_name}负责人和地区`}>{lead.assigned_sales_name || '待分配'}<ChevronDown size={11} /></summary><div className="sl-identity-meta"><span>{lead.assigned_sales_name || '待分配'}</span><span>{lead.industry || '未分类'}{lead.city || lead.state ? ` · ${[lead.city, lead.state].filter(Boolean).join(', ')}` : ''}</span></div></details><div className={`sl-identity-phone ${protectedLead ? 'sl-blocked' : ''}`}><Phone size={12} /><span className="slr-phone-number">{formatPhoneNumber(lead.phone, lead.country)}</span></div><div className="slr-identity-flags"><Badge className={statusColors[lead.status] || statusColors.new}>{statusLabels[lead.status] || lead.status}</Badge>{protectedLead && <span>禁止拨打</span>}</div></div></td>
                    <td><LeadCommunication notes={lead.notes} insight={leadInsights[lead.id]} loading={insightsLoading} /></td>
                    <td><LeadNextStep insight={leadInsights[lead.id]} nextAt={lead.next_follow_up_at} lastAt={lead.last_contact_at} stopped={protectedLead} converted={!!lead.converted_customer_id} /></td>
                    <td className="sl-actions-cell"><div className="sl-row-actions">{renderLeadAction(lead)}<DropdownMenu><DropdownMenuTrigger asChild><Button size="sm" variant="ghost" aria-label={`更多线索操作：${lead.business_name}`}><MoreHorizontal size={16} /></Button></DropdownMenuTrigger><DropdownMenuContent align="end" className="sales-center-menu"><DropdownMenuItem onSelect={() => setDossierId(lead.id)}>查看档案</DropdownMenuItem>{!protectedLead && !lead.converted_customer_id && lead.status !== 'new' && <DropdownMenuItem onSelect={() => openEdit(lead, true)}>记录跟进</DropdownMenuItem>}<DropdownMenuItem onSelect={() => openEdit(lead)}>{canManage ? '编辑资料' : '保护设置'}</DropdownMenuItem>{!lead.converted_customer_id && !protectedLead && <DropdownMenuItem onSelect={() => void openDealControl(lead)}><ClipboardCheck className="mr-2 h-4 w-4" />登记成交</DropdownMenuItem>}{lead.converted_customer_id && <DropdownMenuItem onSelect={() => openDealControl(lead)}>查看成交与交接</DropdownMenuItem>}<DropdownMenuItem onSelect={() => lead.do_not_contact ? setDossierId(lead.id) : void updateProtection(lead, 'do_not_contact', true)}>{lead.do_not_contact ? '查看禁联保护' : '禁止联系'}</DropdownMenuItem>{canManage && <DropdownMenuItem onSelect={() => lead.is_blacklisted ? setDossierId(lead.id) : void updateProtection(lead, 'is_blacklisted', true)}>{lead.is_blacklisted ? '查看黑名单保护' : '加入黑名单'}</DropdownMenuItem>}</DropdownMenuContent></DropdownMenu></div></td>
                  </tr>;
                })}
              </tbody>
            </table>
          </div>}
          <div className="flex flex-col gap-3 border-t bg-white px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-xs text-slate-500">共 {total} 条，第 {page}/{totalPages} 页</p>
            <div className="flex items-center gap-2"><NativeSelect className="w-24" value={String(pageSize)} onChange={value => { setPageSize(Number(value)); setPage(1); }} options={[20, 50, 100].map(value => ({ value: String(value), label: `${value}条` }))} /><Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage(value => value - 1)}>上一页</Button><Button variant="outline" size="sm" disabled={page >= totalPages} onClick={() => setPage(value => value + 1)}>下一页</Button></div>
          </div>
        </CardContent>
      </Card>

      </section>


      <Sheet open={showForm && followUpOnly} onOpenChange={closeForm}>
        <SheetContent className="sales-center-ui slr-followup-sheet" overlayClassName="slr-followup-overlay" aria-describedby="slr-followup-description">
          <SheetHeader className="slr-followup-heading">
            <SheetTitle>{editing?.business_name}</SheetTitle>
            <SheetDescription id="slr-followup-description">{formatPhoneNumber(editing?.phone, editing?.country)}</SheetDescription>
          </SheetHeader>
          {editing && <>
            <SalesLocalTime {...contactWindow} /><div className="slr-followup-tools"><Badge className={statusColors[editing.status] || statusColors.new}>{statusLabels[editing.status] || editing.status}</Badge><CustomerPhoneDial country={editing.country} phone={editing.phone} label="拨打电话" disabled={saving || followUpSaving || editing.do_not_contact || editing.is_blacklisted || !!editing.converted_customer_id} /></div>
            {editing.do_not_contact || editing.is_blacklisted || editing.converted_customer_id
              ? <div role="status" className="slr-protection-note">{editing.converted_customer_id ? '已转正式客户' : '已停止联系'}{editing.do_not_contact_reason && <p>{editing.do_not_contact_reason}</p>}</div>
              : <fieldset disabled={saving || followUpSaving} className="slr-followup-form">
                  <div><Label htmlFor="slr-followup-outcome">本次结果</Label><NativeSelect id="slr-followup-outcome" value={followUpForm.outcome} onChange={value => setFollowUpForm(current => ({ ...current, outcome: value }))} options={followUpOutcomeOptions} /></div>
                  <div><Label htmlFor="slr-followup-notes">沟通记录 *</Label><Textarea id="slr-followup-notes" maxLength={20000} rows={7} value={followUpForm.notes} onChange={event => setFollowUpForm(current => ({ ...current, notes: event.target.value }))} placeholder="记录客户反馈和约定的下一步…" /></div>
                  {!['not_interested', 'do_not_contact'].includes(followUpForm.outcome) && <div><Label htmlFor="slr-followup-time">下次回访 · 北京时间</Label><Input id="slr-followup-time" type="datetime-local" value={followUpForm.next_follow_up_at} onChange={event => setFollowUpForm(current => ({ ...current, next_follow_up_at: event.target.value }))} /><SalesFollowUpQuick value={followUpForm.next_follow_up_at} timezone={contactWindow.timezone} onChange={next_follow_up_at => setFollowUpForm(current => ({ ...current, next_follow_up_at }))} /></div>}
                  {hasFollowUpDraft() && <div className="slr-draft-state"><span role="status">{followUpPersistence === 'session' ? '草稿已暂存' : '草稿仅保留在当前页面'}</span><Button type="button" size="sm" variant="ghost" aria-label="清空跟进草稿" onClick={discardFollowUpDraft}><Trash2 size={14} /></Button></div>}
                  <div className="slr-followup-save-row"><Button type="button" className="slr-followup-save" disabled={followUpSaving || editing.status === 'new'} onClick={() => void recordFollowUp()}>{followUpSaving ? '保存中…' : '保存跟进'}</Button>{['interested', 'appointment'].includes(followUpForm.outcome) && <Button type="button" variant="outline" className="slr-followup-save" disabled={followUpSaving || editing.status === 'new'} onClick={() => void recordFollowUp('quote')}>保存并登记成交</Button>}</div>
                </fieldset>}
            <details className="slr-followup-history"><summary><History size={16} />历史记录 <span>{callHistory.length}</span><ChevronDown size={15} /></summary>{historyLoading ? <p>正在加载…</p> : callHistory.length ? callHistory.map(item => <article key={item.id}><div><strong>{item.outcome_label}</strong><time>{formatDate(item.called_at)}</time></div><p>{item.notes || '未填写沟通内容'}</p><small>{item.sales_employee_name || '—'} · 下次：{formatDate(item.next_follow_up_at)}</small></article>) : <p>暂无历史记录</p>}</details>
          </>}
        </SheetContent>
      </Sheet>

      <Dialog open={showForm && !followUpOnly} onOpenChange={closeForm}>
        <CrmFormDialogContent className="sales-center-ui slr-details-dialog max-w-3xl crm-sales-dialog-polish">
<CrmFormDialogHeader><DialogTitle>{editing ? (canManage ? '编辑销售线索' : '记录跟进结果') : '新增销售线索'}</DialogTitle></CrmFormDialogHeader>
<CrmFormDialogBody className="crm-sales-dialog-body"><fieldset disabled={saving || followUpSaving} className="grid min-w-0 gap-4 sm:grid-cols-2">
            {canManage && <>
              <div><Label>商家名称 *</Label><Input value={form.business_name} onChange={event => setForm({ ...form, business_name: event.target.value })} /></div>
              <div><Label>电话 *</Label><Input value={form.phone} onChange={event => setForm({ ...form, phone: event.target.value })} /></div>
              <div><Label>联系人</Label><Input value={form.contact_name} onChange={event => setForm({ ...form, contact_name: event.target.value })} /></div>
              <div><Label>行业</Label><Input value={form.industry} onChange={event => setForm({ ...form, industry: event.target.value })} placeholder="如：餐厅、美业" /></div>
              <div><Label>国家</Label><Input value={form.country} onChange={event => setForm({ ...form, country: event.target.value })} /></div>
              <div><Label>州/省</Label><Input value={form.state} onChange={event => setForm({ ...form, state: event.target.value })} /></div>
              <div><Label>城市</Label><Input value={form.city} onChange={event => setForm({ ...form, city: event.target.value })} /></div>
              <div><Label>地址</Label><Input value={form.address} onChange={event => setForm({ ...form, address: event.target.value })} /></div>
              <div><Label>网站</Label><Input value={form.website} onChange={event => setForm({ ...form, website: event.target.value })} /></div>
              <div><Label>数据来源</Label><Input value={form.source} onChange={event => setForm({ ...form, source: event.target.value })} /></div>
              <div><Label>{editing ? '主要负责人' : '分配销售'}</Label>{editing ? <div className="flex flex-wrap items-center gap-2 pt-1"><span className="text-sm text-slate-700">{editing.assigned_sales_name || '待分配'}</span><Button type="button" size="sm" variant="outline" onClick={() => { if (formGuard.confirmDiscard()) { setShowForm(false); setDossierId(editing.id); } }}>通过档案转交负责人</Button></div> : <NativeSelect value={form.assigned_sales_id} onChange={value => setForm({ ...form, assigned_sales_id: value })} options={[{ value: '', label: '暂不分配' }, ...assignees.map(item => ({ value: String(item.id), label: item.name }))]} />}</div>
            </>}
            <div><Label>跟进状态</Label><NativeSelect disabled={Boolean(editing && ['follow_up','interested','appointment'].includes(editing.status))} value={form.status} onChange={value => setForm({ ...form, status: value })} options={statusOptions} />{editing && ['follow_up','interested','appointment'].includes(editing.status) && <p className="mt-1 text-xs text-slate-500">跟进保护中的状态请通过真实沟通结果更新。</p>}</div>
            <div><Label>下次跟进 · 北京时间</Label><Input type="datetime-local" value={form.next_follow_up_at} onChange={event => setForm({ ...form, next_follow_up_at: event.target.value })} /></div>
            <div className="sm:col-span-2"><Label>当前跟进摘要</Label><Textarea rows={3} value={form.notes} onChange={event => setForm({ ...form, notes: event.target.value })} placeholder="这里显示最近一次摘要；完整沟通过程请使用下方跟进时间线" /></div>
            <div className="sm:col-span-2 rounded-xl border border-rose-100 bg-rose-50/60 p-4">
              <div className="flex flex-wrap gap-5">
                <label className="flex items-center gap-2 text-sm font-medium text-rose-800"><input type="checkbox" checked={form.do_not_contact} onChange={event => setForm({ ...form, do_not_contact: event.target.checked })} />禁止再联系</label>
                {canManage && <label className="flex items-center gap-2 text-sm font-medium text-slate-800"><input type="checkbox" checked={form.is_blacklisted} onChange={event => setForm({ ...form, is_blacklisted: event.target.checked })} />加入黑名单</label>}
              </div>
              {form.do_not_contact && <Input className="mt-3 bg-white" value={form.do_not_contact_reason} onChange={event => setForm({ ...form, do_not_contact_reason: event.target.value })} placeholder="必填：禁止再联系原因" />}
            </div>
          </fieldset></CrmFormDialogBody>
<CrmFormDialogFooter><div className="sticky bottom-0 -mx-4 mt-4 flex gap-2 border-t bg-white/95 px-4 py-3 pb-[calc(.75rem+env(safe-area-inset-bottom))] backdrop-blur sm:static sm:mx-0 sm:justify-end sm:border-0 sm:bg-transparent sm:px-0 sm:py-0 sm:pb-0"><Button className="h-11 flex-1 sm:flex-none" variant="outline" onClick={() => closeForm(false)}>取消</Button><Button className="h-11 flex-1 sm:flex-none" disabled={saving || followUpSaving} onClick={handleSave}>{saving ? '保存中...' : '保存资料'}</Button></div></CrmFormDialogFooter>
</CrmFormDialogContent>
      </Dialog>

      {!isMobile && <Dialog open={recoveryOpen} onOpenChange={setRecoveryOpen}>
        <CrmFormDialogContent className="max-w-3xl crm-sales-dialog-polish">
<CrmFormDialogHeader><DialogTitle>线索保护与回收</DialogTitle></CrmFormDialogHeader>
<CrmFormDialogBody className="crm-sales-dialog-body"><div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">未触达线索超过 48 小时，或下次跟进已逾期 3 天，会进入主管可回收名单。系统不会自动抢线索；有意向、已预约线索始终受保护。</div>
<div className="sticky top-0 z-10 rounded-xl border border-blue-200 bg-white p-3 shadow-sm"><div className="flex flex-col gap-3 sm:flex-row sm:items-center"><div className="flex-1 text-sm font-medium text-slate-700">已选择 {selectedRecoveryIds.length} 条</div><NativeSelect className="sm:w-52" value={bulkAssigneeId} onChange={setBulkAssigneeId} options={[{ value: '', label: '选择重新分配的销售' }, ...assignees.map(item => ({ value: String(item.id), label: item.name }))]} /><Button variant="outline" disabled={!selectedRecoveryIds.length || recoveryBusy === -1} onClick={() => void handleBulkRecovery('reassign')}>批量重新分配</Button><Button variant="outline" className="border-rose-200 text-rose-700" disabled={!selectedRecoveryIds.length || recoveryBusy === -1} onClick={() => void handleBulkRecovery('reclaim')}>批量回收</Button></div><p className="mt-2 text-xs text-slate-500">批量回收只允许“可回收”线索；重新分配受保护线索时会再次确认并记录原因。</p></div>
<div className="space-y-3">{(recoveryOverview?.items || []).filter(item => item.state !== 'active').map(item => <div key={item.lead_id} className="rounded-xl border border-slate-200 p-4"><div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between"><div className="flex gap-3"><input className="mt-1 h-4 w-4" type="checkbox" checked={selectedRecoveryIds.includes(item.lead_id)} onChange={event => setSelectedRecoveryIds(current => event.target.checked ? [...current, item.lead_id] : current.filter(id => id !== item.lead_id))} /><div><div className="flex flex-wrap items-center gap-2"><p className="font-semibold text-slate-900">{item.business_name}</p><Badge className={item.state === 'recoverable' ? 'bg-rose-100 text-rose-700' : item.state === 'protected' ? 'bg-emerald-100 text-emerald-700' : item.state === 'extended' ? 'bg-blue-100 text-blue-700' : 'bg-amber-100 text-amber-800'}>{item.state === 'recoverable' ? '可回收' : item.state === 'protected' ? '受保护' : item.state === 'extended' ? '已延期保护' : '提醒跟进'}</Badge></div><p className="mt-1 text-sm text-slate-600">当前负责人：{item.assigned_sales_name || '待分配'} · {item.message}</p>{item.deadline && <p className="mt-1 text-xs text-slate-500">保护/提醒截止：{formatDate(item.deadline)}</p>}{item.extension_request && <p className="mt-1 text-xs text-violet-700">延期申请：{item.extension_request.requested_by || item.assigned_sales_name || '销售'} - {item.extension_request.reason || '未说明原因'}</p>}</div></div><div className="flex shrink-0 flex-wrap gap-2">{item.extension_request && <Button size="sm" variant="outline" disabled={recoveryBusy === item.lead_id} onClick={() => void handleRecoveryAction(item, 'approve-extension')}>{recoveryBusy === item.lead_id ? '处理中...' : '批准延期'}</Button>}{item.state === 'recoverable' && <Button size="sm" variant="outline" className="border-rose-200 text-rose-700" disabled={recoveryBusy === item.lead_id} onClick={() => void handleRecoveryAction(item, 'reclaim')}>{recoveryBusy === item.lead_id ? '处理中...' : '回收至待分配'}</Button>}</div></div></div>)}{!(recoveryOverview?.items || []).some(item => item.state !== 'active') && <p className="py-10 text-center text-sm text-slate-500">目前没有需要处理的线索保护提醒。</p>}</div></CrmFormDialogBody>

</CrmFormDialogContent>
      </Dialog>}

      <SalesDealHandoffDialog leadId={dealLeadId} onClose={() => setDealLeadId(null)} onOpenDossier={setDossierId} onRegistered={async () => { setHandoffQueueVersion(value => value + 1); await loadData(); }} />
    </div>
  );
}
