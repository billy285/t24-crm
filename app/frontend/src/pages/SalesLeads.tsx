import { useEffect, useMemo, useRef, useState } from 'react';
import {
  ArrowRightLeft, Ban, BarChart3, CheckCircle2, ChevronDown, Clipboard, ClipboardCheck, Clock3, Edit3, FileText, History, Link2, MessageSquarePlus, MoreHorizontal, Phone, PhoneCall, PhoneOff, Plus, Radio, Search, ShieldAlert, Timer, Trash2, Users,
} from 'lucide-react';
import { toast } from 'sonner';

import '@/components/sales-center.css';
import './sales-workspace.css';
import './sales-leads-refined.css';
import SalesIntelligenceCenter from '@/components/SalesIntelligenceCenter';
import SalesLeadDossier from '@/components/SalesLeadDossier';
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
import { businessDateKey, formatBusinessDateTimeInput, parseBusinessDateTimeInput } from '@/lib/business-date';
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
type Quote = { id: number; business_line_id?: number; product_id?: number; product_plan_id?: number; package_name: string; selected_platforms: string[]; billing_mode: string; billing_cycle: string; payment_method: string; currency: string; list_amount: number; discount_amount: number; final_amount: number; service_start_date?: string; service_end_date?: string; special_terms?: string; status: 'submitted' | 'approved' | 'rejected' | 'superseded'; submitted_by_name?: string; reviewed_by_name?: string; review_notes?: string };
type Handoff = { quote_id?: number; customer_goal?: string; key_contacts?: string; service_start_date?: string; service_end_date?: string; special_commitments?: string; operations_owner?: string; operations_owner_employee_id?: number; collaborator_employee_ids?: number[]; operations_group_created?: boolean; finance_payment_confirmed?: boolean; payment_status?: string; amount_received?: number; payment_date?: string; payment_reference?: string; payment_confirmed_by_name?: string; generated_deal_id?: number; generate_service_board?: boolean; handoff_notes?: string };
type DealReadiness = { lead: SalesLead; quotes: Quote[]; handoff: Handoff; blockers: string[] };
type BusinessLineOption = { id: number; code: string; name: string };
type ProductOption = { id: number; business_line_id: number; name: string; default_currency: string };
type PlanOption = { id: number; product_id: number; name: string; standard_price?: number; default_currency: string; default_billing_cycle?: string; platform_limit?: number; scope_type: string };
type DealEmployeeOption = { id: number; name: string; role: string; department?: string; position?: string };

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
const platformOptions = ['Google Business Profile', 'Google Ads', 'Facebook', 'Instagram', 'TikTok', 'Yelp', '小红书', '官网'];
const billingCycleOptions = [
  { value: 'monthly', label: '月付' }, { value: 'quarterly', label: '季付' },
  { value: 'semi_annual', label: '半年付' }, { value: 'annual', label: '年付' }, { value: 'one_time', label: '一次性' },
];

const emptyForm = {
  business_name: '', contact_name: '', phone: '', industry: '', country: 'US', state: '', city: '',
  address: '', website: '', source: 'manual', status: 'new', assigned_sales_id: '', notes: '',
  is_blacklisted: false, do_not_contact: false, do_not_contact_reason: '', next_follow_up_at: '',
};

const emptyQuoteForm = { business_line_id: '', product_id: '', product_plan_id: '', package_name: '', selected_platforms: '', billing_mode: 'manual', billing_cycle: 'monthly', payment_method: 'stripe', currency: 'USD', list_amount: '', discount_amount: '0', service_start_date: '', service_end_date: '', special_terms: '' };
const emptyHandoffForm = { quote_id: '', customer_goal: '', key_contacts: '', service_start_date: '', service_end_date: '', special_commitments: '', operations_owner: '', operations_owner_employee_id: '', collaborator_employee_ids: [] as number[], operations_group_created: false, generate_service_board: false, handoff_notes: '' };
const createEmptyPaymentForm = () => ({ payment_status: 'pending', amount_received: '', payment_date: businessDateKey(), payment_reference: '' });

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
  const [view, setView] = useState<'leads' | 'calls' | 'performance' | 'intelligence'>(()=>new URLSearchParams(window.location.search).get('view')==='intelligence'?'intelligence':'leads');
  const [dossierId, setDossierId] = useState<number | null>(null);
  const requestedQuoteRef = useRef(false);
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [contactFilter, setContactFilter] = useState('');
  const [filtersExpanded, setFiltersExpanded] = useState(false);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [total, setTotal] = useState(0);
  const [showForm, setShowForm] = useState(false);
  const [followUpOnly, setFollowUpOnly] = useState(false);
  const [editing, setEditing] = useState<SalesLead | null>(null);
  const [form, setForm] = useState(emptyForm);
  const [saving, setSaving] = useState(false);
  const [dashboard, setDashboard] = useState<ManagementDashboard | null>(null);
  const [convertingId, setConvertingId] = useState<number | null>(null);
  const [dealLead, setDealLead] = useState<SalesLead | null>(null);
  const [dealStep, setDealStep] = useState<'quote' | 'handoff' | 'payment'>('quote');
  const dealBaselinesRef = useRef({ handoff: JSON.stringify(emptyHandoffForm), payment: JSON.stringify(createEmptyPaymentForm()) });
  const [conversionReceipt, setConversionReceipt] = useState<{ customer_id: number; customer_code: string; operations_owner?: string; operations_access_status?: string } | null>(null);
  const [dealReadiness, setDealReadiness] = useState<DealReadiness | null>(null);
  const [dealLoading, setDealLoading] = useState(false);
  const dealRequestRef = useRef(0);
  const [dealError, setDealError] = useState(false);
  const [dealSaving, setDealSaving] = useState(false);
  const [quoteForm, setQuoteForm] = useState(emptyQuoteForm);
  const [handoffForm, setHandoffForm] = useState(emptyHandoffForm);
  const [paymentForm, setPaymentForm] = useState(createEmptyPaymentForm);
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
  const [businessLines, setBusinessLines] = useState<BusinessLineOption[]>([]);
  const [products, setProducts] = useState<ProductOption[]>([]);
  const [productPlans, setProductPlans] = useState<PlanOption[]>([]);
  const [dealEmployees, setDealEmployees] = useState<DealEmployeeOption[]>([]);
  const [selectedRecoveryIds, setSelectedRecoveryIds] = useState<number[]>([]);
  const [selectedLeadIds, setSelectedLeadIds] = useState<number[]>([]);
  const [bulkAssigneeId, setBulkAssigneeId] = useState('');
  const loadRequestSeqRef = useRef(0);

  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const quoteProducts = useMemo(() => products.filter(item => String(item.business_line_id) === quoteForm.business_line_id), [products, quoteForm.business_line_id]);
  const quotePlans = useMemo(() => productPlans.filter(item => String(item.product_id) === quoteForm.product_id), [productPlans, quoteForm.product_id]);
  const selectedQuotePlan = useMemo(() => productPlans.find(item => String(item.id) === quoteForm.product_plan_id), [productPlans, quoteForm.product_plan_id]);
  const selectedPlatforms = useMemo(() => quoteForm.selected_platforms.split(/[，,\n]/).map(item => item.trim()).filter(Boolean), [quoteForm.selected_platforms]);

  const loadData = async (options?: { page?: number }) => {
    const requestId = ++loadRequestSeqRef.current;
    const requestPage = options?.page ?? page;
    setLoading(true);
    const params = new URLSearchParams({ skip: String((requestPage - 1) * pageSize), limit: String(pageSize) });
    if (search.trim()) params.set('search', search.trim());
    if (statusFilter) params.set('status', statusFilter);
    if (contactFilter) params.set('contact_rule', contactFilter);
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
      if (failedSections.length) toast.error(`${failedSections.join('、')}加载失败，已保留其他可用数据`);
    } catch (error: any) {
      if (requestId === loadRequestSeqRef.current) toast.error(error?.data?.detail || error?.message || '线索数据加载失败');
    } finally {
      if (requestId === loadRequestSeqRef.current) setLoading(false);
    }
  };

  useEffect(() => {
    const timer = window.setTimeout(() => void loadData(), search.trim() ? 300 : 0);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, pageSize, search, statusFilter, contactFilter, performanceDays, callReportDays]);

  useAutoRefresh(loadData, { intervalMs: 30000, enabled: !showForm });

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

  useEffect(() => {
    const loadDealOptions = async () => {
      try {
        const [catalogResponse, employeeResponse] = await Promise.all([
          invokeWithAuth({ url: '/api/v1/product-plans?active_only=true', method: 'GET' }),
          invokeWithAuth({ url: '/api/v1/sales-deal-controls/options', method: 'GET' }),
        ]);
        setBusinessLines(catalogResponse.data?.business_lines || []);
        setProducts(catalogResponse.data?.products || []);
        setProductPlans(catalogResponse.data?.plans || []);
        setDealEmployees(employeeResponse.data?.employees || []);
      } catch (error: any) {
        toast.error(error?.data?.detail || error?.message || '成交选项加载失败');
      }
    };
    void loadDealOptions();
  }, []);

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
    setFollowUpOnly(followUp);
    setEditing(lead);
    setForm({
      business_name: lead.business_name || '', contact_name: lead.contact_name || '', phone: lead.phone || '',
      industry: lead.industry || '', country: lead.country || '', state: lead.state || '', city: lead.city || '',
      address: lead.address || '', website: lead.website || '', source: lead.source || '', status: lead.status || 'new',
      assigned_sales_id: lead.assigned_sales_id ? String(lead.assigned_sales_id) : '', notes: lead.notes || '',
      is_blacklisted: !!lead.is_blacklisted, do_not_contact: !!lead.do_not_contact,
      do_not_contact_reason: lead.do_not_contact_reason || '', next_follow_up_at: formatBusinessDateTimeInput(lead.next_follow_up_at),
    });
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

  const loadDealReadiness = async (lead: SalesLead, resetDrafts = false) => {
    const requestId = ++dealRequestRef.current;
    setDealLoading(true);
    setDealError(false);
    setDealReadiness(null);
    try {
      const [response, leadResponse] = await Promise.all([
        invokeWithAuth({ url: `/api/v1/sales-deal-controls/${lead.id}/readiness`, method: 'GET' }),
        invokeWithAuth({ url: `/api/v1/sales-leads/${lead.id}`, method: 'GET' }),
      ]);
      if (requestId !== dealRequestRef.current) return;
      const receivedReadiness = response.data as DealReadiness;
      const freshLead = leadResponse.data as SalesLead;
      if (receivedReadiness.lead.id !== lead.id || freshLead.id !== lead.id) throw new Error('成交资料与当前商机不一致，请重新加载');
      const readiness = { ...receivedReadiness, lead: { ...freshLead, converted_customer_id: receivedReadiness.lead.converted_customer_id || freshLead.converted_customer_id } };
      setDealReadiness(readiness);
      const handoff = readiness.handoff || {};
      const activeQuote = readiness.quotes.find(quote => quote.status === 'approved');
      const loadedHandoff = {
        quote_id: handoff.quote_id ? String(handoff.quote_id) : (activeQuote ? String(activeQuote.id) : ''), customer_goal: handoff.customer_goal || '', key_contacts: handoff.key_contacts || '',
        service_start_date: handoff.service_start_date || activeQuote?.service_start_date || '', service_end_date: handoff.service_end_date || activeQuote?.service_end_date || '', special_commitments: handoff.special_commitments || '',
        operations_owner: handoff.operations_owner || '', operations_owner_employee_id: handoff.operations_owner_employee_id ? String(handoff.operations_owner_employee_id) : '',
        collaborator_employee_ids: handoff.collaborator_employee_ids || [], operations_group_created: !!handoff.operations_group_created,
        generate_service_board: !!handoff.generate_service_board, handoff_notes: handoff.handoff_notes || '',
      };
      if (resetDrafts || JSON.stringify(handoffForm) === dealBaselinesRef.current.handoff) setHandoffForm(loadedHandoff);
      const loadedPayment = {
        payment_status: handoff.payment_status || (handoff.finance_payment_confirmed ? 'paid' : 'pending'),
        amount_received: handoff.amount_received ? String(handoff.amount_received) : '',
        payment_date: handoff.payment_date || businessDateKey(), payment_reference: handoff.payment_reference || '',
      };
      if (resetDrafts || JSON.stringify(paymentForm) === dealBaselinesRef.current.payment) setPaymentForm(loadedPayment);
      dealBaselinesRef.current = { handoff: JSON.stringify(loadedHandoff), payment: JSON.stringify(loadedPayment) };
    } catch (error: any) {
      if (requestId !== dealRequestRef.current) return;
      setDealError(true);
      toast.error(error?.data?.detail || error?.message || '成交审核信息加载失败');
    } finally { if (requestId === dealRequestRef.current) setDealLoading(false); }
  };

  const openDealControl = async (lead: SalesLead) => {
    if (lead.converted_customer_id || lead.do_not_contact || lead.is_blacklisted) {
      toast.error(lead.converted_customer_id ? '已转为正式客户，请在客户中心继续处理' : '该商家已停止联系');
      return;
    }
    setDealStep('quote');
    setDealLead(lead);
    setDealReadiness(null);
    setQuoteForm(emptyQuoteForm);
    setHandoffForm(emptyHandoffForm);
    setPaymentForm(createEmptyPaymentForm());
    await loadDealReadiness(lead, true);
  };

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const id = Number(params.get('lead_id'));
    const action = params.get('action');
    if (!Number.isSafeInteger(id) || id <= 0 || !['quote', 'followup'].includes(action || '') || requestedQuoteRef.current) return;
    requestedQuoteRef.current = true;
    invokeWithAuth({ url: `/api/v1/sales-leads/${id}`, method: 'GET' })
      .then(response => {
        if (response.data?.id !== id) throw new Error('商机资料与当前客户不一致');
        if (action === 'quote') return openDealControl(response.data);
        if (response.data?.status === 'new') { toast.error('新线索请先进入今日拨打'); return; }
        openEdit(response.data, true);
      })
      .catch(error => toast.error(error?.data?.detail || '该商机无法读取，请检查归属权限'));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const hasDealDraft = () => !!dealLead && !dealLoading && !dealError && (JSON.stringify(quoteForm) !== JSON.stringify(emptyQuoteForm) || JSON.stringify(handoffForm) !== dealBaselinesRef.current.handoff || JSON.stringify(paymentForm) !== dealBaselinesRef.current.payment);
  const canEditDeal = !!dealLead && !dealSaving && !dealLoading && !dealError && !!dealReadiness && dealReadiness.lead.id === dealLead.id && !dealReadiness.lead.converted_customer_id && !dealReadiness.lead.do_not_contact && !dealReadiness.lead.is_blacklisted;
  const closeDealControl = (open: boolean) => {
    if (open || dealSaving || convertingId !== null) return;
    if (hasDealDraft() && !window.confirm('报价或交接有未保存内容，确认放弃并关闭吗？')) return;
    dealRequestRef.current += 1;
    setDealLead(null);
    setDealReadiness(null);
  };
  useEffect(() => {
    if (!hasDealDraft()) return;
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ''; };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dealLead, quoteForm, handoffForm, paymentForm]);

  const submitQuote = async () => {
    if (!canEditDeal) return;
    if (!dealLead || !quoteForm.business_line_id || !quoteForm.product_id || !quoteForm.list_amount) {
      toast.error('请选择业务线、具体产品并填写报价金额');
      return;
    }
    setDealSaving(true);
    try {
      await invokeWithAuth({
        url: `/api/v1/sales-deal-controls/${dealLead.id}/quotes`, method: 'POST', data: {
          business_line_id: Number(quoteForm.business_line_id), product_id: Number(quoteForm.product_id),
          product_plan_id: quoteForm.product_plan_id ? Number(quoteForm.product_plan_id) : null,
          package_name: quoteForm.package_name.trim() || '待确认套餐', selected_platforms: quoteForm.selected_platforms.split(/[，,\n]/).map(item => item.trim()).filter(Boolean),
          billing_mode: quoteForm.billing_mode, billing_cycle: quoteForm.billing_cycle,
          payment_method: quoteForm.payment_method, currency: quoteForm.currency || 'USD',
          list_amount: Number(quoteForm.list_amount), discount_amount: Number(quoteForm.discount_amount || 0),
          service_start_date: quoteForm.service_start_date || null, service_end_date: quoteForm.service_end_date || null, special_terms: quoteForm.special_terms || null,
        },
      });
      toast.success('报价已提交，等待主管审批');
      setQuoteForm(emptyQuoteForm);
      await loadDealReadiness(dealLead);
    } catch (error: any) {
      toast.error(error?.data?.detail || error?.message || '报价提交失败');
    } finally { setDealSaving(false); }
  };

  const reviewQuote = async (quote: Quote, decision: 'approved' | 'rejected') => {
    if (!canManage || !canEditDeal) return;
    const reviewNotes = window.prompt(decision === 'approved' ? '可填写审批备注（可留空）' : '请填写驳回原因') || '';
    if (decision === 'rejected' && !reviewNotes.trim()) return;
    setDealSaving(true);
    try {
      await invokeWithAuth({ url: `/api/v1/sales-deal-controls/quotes/${quote.id}/review`, method: 'POST', data: { decision, review_notes: reviewNotes || null } });
      toast.success(decision === 'approved' ? '报价已批准' : '报价已驳回');
      if (dealLead) await loadDealReadiness(dealLead);
    } catch (error: any) {
      toast.error(error?.data?.detail || error?.message || '报价审批失败');
    } finally { setDealSaving(false); }
  };

  const saveHandoff = async () => {
    if (!dealLead || !canEditDeal) return;
    setDealSaving(true);
    try {
      await invokeWithAuth({
        url: `/api/v1/sales-deal-controls/${dealLead.id}/handoff`, method: 'PUT', data: {
          quote_id: handoffForm.quote_id ? Number(handoffForm.quote_id) : null, customer_goal: handoffForm.customer_goal || null,
          key_contacts: handoffForm.key_contacts || null, service_start_date: handoffForm.service_start_date || null, service_end_date: handoffForm.service_end_date || null,
          special_commitments: handoffForm.special_commitments || null, operations_owner: handoffForm.operations_owner || null,
          operations_owner_employee_id: handoffForm.operations_owner_employee_id ? Number(handoffForm.operations_owner_employee_id) : null,
          collaborator_employee_ids: handoffForm.collaborator_employee_ids,
          operations_group_created: handoffForm.operations_group_created, generate_service_board: handoffForm.generate_service_board, handoff_notes: handoffForm.handoff_notes || null,
        },
      });
      toast.success('成交交接清单已保存');
      dealBaselinesRef.current.handoff = JSON.stringify(handoffForm);
      await loadDealReadiness(dealLead);
    } catch (error: any) {
      toast.error(error?.data?.detail || error?.message || '成交交接清单保存失败');
    } finally { setDealSaving(false); }
  };

  const savePaymentStatus = async () => {
    if (!canManage || !dealLead || !canEditDeal) return;
    const received = Number(paymentForm.amount_received);
    if (!Number.isFinite(received) || received < 0 || (['paid', 'deposit_paid'].includes(paymentForm.payment_status) && (!paymentForm.amount_received.trim() || received <= 0))) {
      toast.error('请填写已核对的实收金额，不能以报价代替到账');
      return;
    }
    if (['paid', 'deposit_paid'].includes(paymentForm.payment_status) && !paymentForm.payment_date) {
      toast.error('请填写实际收款日期');
      return;
    }
    setDealSaving(true);
    try {
      await invokeWithAuth({
        url: `/api/v1/sales-deal-controls/${dealLead.id}/handoff/finance-confirmation`, method: 'POST', data: {
          payment_status: paymentForm.payment_status, amount_received: received,
          payment_date: paymentForm.payment_date || null, payment_reference: paymentForm.payment_reference || null,
        },
      });
      toast.success('收款状态已更新');
      dealBaselinesRef.current.payment = JSON.stringify(paymentForm);
      await loadDealReadiness(dealLead);
    } catch (error: any) {
      toast.error(error?.data?.detail || error?.message || '收款确认失败');
    } finally { setDealSaving(false); }
  };

  const convertToCustomer = async () => {
    if (!canManage || !dealLead || !canEditDeal || !dealReadiness || dealReadiness.blockers.length) return;
    if (!window.confirm(`确认 ${dealLead.business_name} 已正式合作，并转入客户管理吗？此操作会保留销售线索、报价和通话历史。`)) return;
    const lead = dealLead;
    setConvertingId(lead.id);
    try {
      const response = await invokeWithAuth({ url: `/api/v1/sales-leads/${lead.id}/convert-to-customer`, method: 'POST', data: { confirmation_notes: '报价已审批、成交交接清单已完成，主管确认合作。' } });
      toast.success(`已转入正式客户：${response.data?.customer_code || ''}`);
      setConversionReceipt(response.data);
      setDealLead(null);
      setDealReadiness(null);
      await loadData();
    } catch (error: any) {
      const detail = error?.data?.detail || error?.response?.data?.detail;
      toast.error(typeof detail === 'object' ? `${detail.message}${detail.blockers?.length ? `：${detail.blockers.join('、')}` : ''}` : (detail || error?.message || '转入失败'));
      await loadDealReadiness(lead);
    } finally { setConvertingId(null); }
  };

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
    if (lead.converted_customer_id) return <Button size="sm" variant="outline" onClick={() => window.location.assign(customerDetailPath(lead.converted_customer_id!))}>查看客户</Button>;
    if (lead.status === 'new') return <Button size="sm" variant="outline" onClick={() => window.location.assign(`/sales-workbench?lead_id=${lead.id}${lead.assigned_sales_id ? `&sales_employee_id=${lead.assigned_sales_id}` : ''}`)}>首次拨打</Button>;
    if (['interested', 'appointment'].includes(lead.status)) return isMobile
      ? <Button size="sm" variant="outline" aria-label={`记录跟进：${lead.business_name}`} onClick={() => openEdit(lead, true)}>继续跟进</Button>
      : <><Button size="sm" variant="outline" onClick={() => void openDealControl(lead)}>准备报价</Button><Button size="sm" variant="ghost" aria-label={`记录跟进：${lead.business_name}`} onClick={() => openEdit(lead, true)}><MessageSquarePlus size={16} /></Button></>;
    return <Button size="sm" variant="outline" onClick={() => openEdit(lead, true)}>继续跟进</Button>;
  };

  return (
    <div className={`t24-directory-page t24-sales-leads-page sales-center-ui sc-directory sl-clarity calm-sales-page calm-leads-page app-page slr-page slr-view-${view}`}>
      <div className="sc-section-heading slr-page-heading">
        <h2>{view === 'leads' ? '联系进展' : view === 'calls' ? '通话数据' : view === 'intelligence' ? '经营中心' : '历史跟进参考'}</h2>
        <div className="slr-heading-tools"><span className="slr-scope">{scopeText}</span><DropdownMenu><DropdownMenuTrigger asChild><Button type="button" variant="ghost">更多视图<ChevronDown size={15} /></Button></DropdownMenuTrigger><DropdownMenuContent align="end"><DropdownMenuItem onSelect={() => setView('leads')}>联系进展</DropdownMenuItem><DropdownMenuItem onSelect={() => setView('calls')}>通话数据</DropdownMenuItem><DropdownMenuItem onSelect={() => setView('intelligence')}>经营中心</DropdownMenuItem>{canManage && <DropdownMenuItem onSelect={() => setView('performance')}>历史跟进参考</DropdownMenuItem>}</DropdownMenuContent></DropdownMenu>{canManage && <Button onClick={openCreate}><Plus className="mr-2 h-4 w-4" />新增线索</Button>}</div>
      </div>

      {listError && <div role="alert" className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">线索列表更新失败，当前显示上次读取的结果；批量操作已暂停。<Button variant="outline" className="ml-3" onClick={() => void loadData()}>重新加载列表</Button></div>}
      <SalesLeadDossier leadId={dossierId} onClose={() => setDossierId(null)} onSaved={() => void loadData()} />
      {(view === 'leads' || view === 'calls') && <div className="slr-utilities">
        <details className="slr-overview"><summary><BarChart3 size={15} />数据一览<ChevronDown size={14} /></summary><SalesLeadPulse stats={stats} report={callReport} days={callReportDays} onCalls={() => setView('calls')} loading={!statsReady} /></details>
        {view === 'leads' && canManage && recoveryOverview && <details className="sl-recovery">
          <summary><ShieldAlert size={16} /><strong>线索保护</strong><span>可回收 <b>{recoveryOverview.summary.recoverable}</b></span><span>保护期提醒 <b>{recoveryOverview.summary.watch}</b></span>{recoveryOverview.summary.extension_requests > 0 && <span>待审批 <b>{recoveryOverview.summary.extension_requests}</b></span>}<small>查看规则与处理</small><ChevronDown size={14} /></summary>
          <div><p>系统只提示，主管确认后才回收。受保护 {recoveryOverview.summary.protected} 条 · 延期保护 {recoveryOverview.summary.extended} 条 · 禁止联系 {stats.do_not_contact} 条 · 黑名单 {stats.blacklisted} 条。</p>{isMobile ? <p>批量回收与改派请在电脑端处理。</p> : <Button size="sm" variant="outline" onClick={() => setRecoveryOpen(true)}>查看并处理</Button>}</div>
        </details>}
      </div>}
      {view === 'intelligence' && <SalesIntelligenceCenter />}
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
              <div className="mt-3 hidden overflow-x-auto rounded-2xl border border-slate-200 md:block"><table className="w-full min-w-[1080px] text-left text-sm"><thead className="bg-slate-50 text-xs text-slate-500"><tr><th className="px-4 py-3">销售</th><th>真实拨出</th><th>接通 / 未接通</th><th>接通率</th><th>总时长 / 平均</th><th>意向 / 预约</th><th>转客户</th><th>任务完成</th><th>匹配覆盖</th></tr></thead><tbody className="divide-y divide-slate-100">{callReport.employees.map(item => <tr key={item.sales_employee_id}><td className="px-4 py-3 font-semibold text-slate-900">{item.salesperson}</td><td>{item.provider_calls}</td><td><span className="text-emerald-700">{item.connected}</span> / <span className="text-rose-600">{item.not_connected}</span></td><td className="font-semibold text-blue-700">{item.connection_rate}%</td><td>{formatDuration(item.total_talk_seconds)}<p className="text-xs text-slate-400">平均 {formatDuration(item.average_talk_seconds)}</p></td><td>{item.interested} / {item.appointments}</td><td>{item.conversions}</td><td>{item.completed}/{item.assigned}<p className="text-xs text-slate-400">{item.completion_rate}%</p></td><td>{item.linked_records}/{item.provider_calls}<p className="text-xs text-slate-400">{item.link_rate}%</p></td></tr>)}{callReport.employees.length === 0 && <tr><td colSpan={9} className="px-4 py-10 text-center text-slate-400">暂无可统计销售</td></tr>}</tbody></table></div>
            </section>

            <section>
              <div><h4 className="font-semibold text-slate-900">最近官方通话</h4><p className="mt-1 text-xs text-slate-500">用于逐条核对销售、商家、接通结果、时长和CRM记录。</p></div>
              <div className="mt-3 divide-y divide-slate-100 overflow-hidden rounded-2xl border border-slate-200">{callReport.recent_calls.slice(0, 12).map(call => <div key={call.id} className="grid gap-2 px-4 py-3 text-sm sm:grid-cols-[minmax(0,1fr)_140px_100px_100px] sm:items-center"><div className="min-w-0"><p className="truncate font-semibold text-slate-900">{call.business_name || call.remote_phone || '未匹配商家'}</p><p className="mt-1 truncate text-xs text-slate-500">{call.salesperson} · {formatDate(call.started_at)}</p></div><Badge className={call.connected ? 'w-fit bg-emerald-100 text-emerald-700' : 'w-fit bg-rose-100 text-rose-700'}>{call.result}</Badge><p className="text-xs text-slate-600">{formatDuration(call.duration_seconds)}</p><p className={`text-xs font-medium ${call.crm_recorded ? 'text-blue-700' : 'text-amber-700'}`}>{call.crm_recorded ? '已记录结果' : '待补CRM结果'}</p></div>)}{callReport.recent_calls.length === 0 && <p className="px-4 py-10 text-center text-sm text-slate-400">统计期内暂无RingCentral官方通话记录</p>}</div>
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
            <div data-testid="sales-performance-desktop-table" className="mt-4 hidden overflow-x-auto md:block"><table className="w-full min-w-[980px] text-left text-sm"><thead className="border-b text-xs text-slate-500"><tr><th className="pb-2">排名 / 销售</th><th className="pb-2">总分</th><th className="pb-2">执行</th><th className="pb-2">纪律</th><th className="pb-2">商机质量</th><th className="pb-2">销售结果</th><th className="pb-2">记录合规</th><th className="pb-2">关键数据</th><th className="pb-2">系统建议</th></tr></thead><tbody className="divide-y divide-violet-100">{performanceDashboard.items.map(item => <tr key={item.sales_employee_id}><td className="py-3"><p className="font-semibold text-slate-900">#{item.rank} {item.salesperson}</p><p className="text-xs text-slate-500">{item.confidence}</p></td><td className="py-3"><p className="text-2xl font-bold text-violet-700">{item.score}</p><p className="text-xs text-slate-500">/100</p></td><td className="py-3">{item.score_breakdown.execution}/25</td><td className="py-3">{item.score_breakdown.discipline}/20</td><td className="py-3">{item.score_breakdown.opportunity}/20</td><td className="py-3">{item.score_breakdown.results}/25</td><td className="py-3">{item.score_breakdown.documentation}/10</td><td className="py-3 text-xs text-slate-600">完成 {item.metrics.completion_rate}% · 接通 {item.metrics.connection_rate}%<br />意向 {item.metrics.interest_rate}% · 逾期 {item.metrics.overdue_followups}</td><td className="max-w-xs py-3 text-xs text-slate-600">{item.suggestions[0]}</td></tr>)}{performanceDashboard.items.length === 0 && <tr><td colSpan={9} className="py-8 text-center text-sm text-slate-500">暂无可评分销售数据</td></tr>}</tbody></table></div>
          </CardContent>
        </Card>
      )}
        </div>
      </details>}

      <section className="sc-lead-panel space-y-4" hidden={view !== 'leads'} aria-label="销售线索列表">
      <Card className={`sc-table-card sl-lead-table ${compactRows ? 'sl-compact' : ''} overflow-hidden border-slate-200 shadow-sm`}>
        <CardContent className="p-0">
          <div className="sl-table-toolbar">
            <div className="slr-list-tools">
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
            {(search || statusFilter || contactFilter) && <div className="slr-active-filters"><span>{statusFilter ? statusLabels[statusFilter] || statusFilter : '全部状态'}{contactFilter ? ` · ${contactFilter === 'contactable' ? '允许联系' : contactFilter === 'do_not_contact' ? '禁止再联系' : '黑名单'}` : ''}{search && ` · “${search}”`}</span><button type="button" onClick={() => { setSearch(''); setStatusFilter(''); setContactFilter(''); setPage(1); }}>清空筛选</button></div>}
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
                    {(protectedLead || lead.converted_customer_id) && <div className="slr-card-flags">{lead.do_not_contact && <Badge className="bg-rose-100 text-rose-700">禁止再联系</Badge>}{lead.is_blacklisted && <Badge className="bg-slate-800 text-white">黑名单</Badge>}{lead.converted_customer_id && <Badge className="bg-emerald-100 text-emerald-700">已转正式客户</Badge>}</div>}
                    <div className="slr-card-meta"><span className={protectedLead ? 'text-slate-400 line-through' : 'text-slate-700'}>{formatPhoneNumber(lead.phone, lead.country)}</span>{(lead.city || lead.state || lead.industry) && <span>{[[lead.city, lead.state].filter(Boolean).join(', '), lead.industry].filter(Boolean).join(' · ')}</span>}</div>
                    {(lead.status !== 'new' || lead.notes || lead.last_contact_at || leadInsights[lead.id]?.calls || leadInsights[lead.id]?.records) && <LeadCommunication notes={lead.notes} insight={leadInsights[lead.id]} loading={insightsLoading} />}
                    {(lead.status !== 'new' || protectedLead || lead.converted_customer_id || lead.next_follow_up_at || lead.last_contact_at || leadInsights[lead.id]?.last_contact_at) && <div className="sl-mobile-next"><LeadNextStep insight={leadInsights[lead.id]} nextAt={lead.next_follow_up_at} lastAt={lead.last_contact_at} stopped={protectedLead} converted={!!lead.converted_customer_id} /></div>}
                    <div className="slr-card-actions">
                      {protectedLead ? <Button className="h-11 px-2" variant="outline" disabled><Phone className="h-4 w-4" />拨号</Button> : <CustomerPhoneDial country={lead.country} phone={lead.phone} label="RingCentral" className="w-full" />}
                      {renderLeadAction(lead)}
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild><Button className="h-11 w-11 p-0" variant="outline" aria-label={`更多线索操作：${lead.business_name}`}><MoreHorizontal className="h-5 w-5" /></Button></DropdownMenuTrigger>
                        <DropdownMenuContent align="end" className="w-56">
                          <DropdownMenuItem className="min-h-11" onSelect={() => setDossierId(lead.id)}>累计档案</DropdownMenuItem>{!protectedLead && !lead.converted_customer_id && lead.status !== 'new' && <DropdownMenuItem className="min-h-11" onSelect={() => openEdit(lead, true)}>记录跟进</DropdownMenuItem>}
                          <DropdownMenuItem className="min-h-11" disabled={protectedLead} onSelect={() => { void copyLeadPhone(lead); }}><Clipboard className="mr-2 h-4 w-4" />复制电话</DropdownMenuItem>
                          {canManage && <DropdownMenuItem className="min-h-11" onSelect={() => openEdit(lead)}><Edit3 className="mr-2 h-4 w-4" />编辑线索资料</DropdownMenuItem>}
                          {!lead.converted_customer_id && !protectedLead && <DropdownMenuItem className="min-h-11" onSelect={() => { void openDealControl(lead); }}><ClipboardCheck className="mr-2 h-4 w-4" />{['interested', 'appointment'].includes(lead.status) ? '准备报价' : '成交审核'}</DropdownMenuItem>}
                          {lead.converted_customer_id && <DropdownMenuItem className="min-h-11" onSelect={() => window.location.assign(customerDetailPath(lead.converted_customer_id!))}><CheckCircle2 className="mr-2 h-4 w-4" />查看正式客户</DropdownMenuItem>}
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
                    <td className="sl-identity-cell"><button type="button" className="sl-business-name" onClick={() => setDossierId(lead.id)}>{lead.business_name}</button><div className="sl-identity-meta"><span>{lead.assigned_sales_name || '待分配'}</span><span>{lead.industry || '未分类'}{lead.city || lead.state ? ` · ${[lead.city, lead.state].filter(Boolean).join(', ')}` : ''}</span></div><div className={`sl-identity-phone ${protectedLead ? 'sl-blocked' : ''}`}><Phone size={12} /><span className="slr-phone-number">{formatPhoneNumber(lead.phone, lead.country)}</span></div><div className="slr-identity-flags"><Badge className={statusColors[lead.status] || statusColors.new}>{statusLabels[lead.status] || lead.status}</Badge>{protectedLead && <span>禁止拨打</span>}</div></td>
                    <td><LeadCommunication notes={lead.notes} insight={leadInsights[lead.id]} loading={insightsLoading} /></td>
                    <td><LeadNextStep insight={leadInsights[lead.id]} nextAt={lead.next_follow_up_at} lastAt={lead.last_contact_at} stopped={protectedLead} converted={!!lead.converted_customer_id} /></td>
                    <td className="sl-actions-cell"><div className="sl-row-actions">{renderLeadAction(lead)}<DropdownMenu><DropdownMenuTrigger asChild><Button size="sm" variant="ghost" aria-label={`更多线索操作：${lead.business_name}`}><MoreHorizontal size={16} /></Button></DropdownMenuTrigger><DropdownMenuContent align="end" className="sales-center-menu"><DropdownMenuItem onSelect={() => setDossierId(lead.id)}>查看档案</DropdownMenuItem>{!protectedLead && !lead.converted_customer_id && lead.status !== 'new' && <DropdownMenuItem onSelect={() => openEdit(lead, true)}>记录跟进</DropdownMenuItem>}<DropdownMenuItem onSelect={() => openEdit(lead)}>{canManage ? '编辑资料' : '保护设置'}</DropdownMenuItem>{!lead.converted_customer_id && !protectedLead && <DropdownMenuItem onSelect={() => void openDealControl(lead)}><ClipboardCheck className="mr-2 h-4 w-4" />成交审核</DropdownMenuItem>}{lead.converted_customer_id && <DropdownMenuItem onSelect={() => window.location.assign(customerDetailPath(lead.converted_customer_id!))}>查看正式客户</DropdownMenuItem>}<DropdownMenuItem onSelect={() => void updateProtection(lead, 'do_not_contact', !lead.do_not_contact)}>{lead.do_not_contact ? '解除禁联' : '禁止联系'}</DropdownMenuItem>{canManage && <DropdownMenuItem onSelect={() => void updateProtection(lead, 'is_blacklisted', !lead.is_blacklisted)}>{lead.is_blacklisted ? '移出黑名单' : '加入黑名单'}</DropdownMenuItem>}</DropdownMenuContent></DropdownMenu></div></td>
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
      {conversionReceipt && <div role="status" className="rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-sm"><p className="font-semibold">已创建正式客户 {conversionReceipt.customer_code}</p><p className="mt-1">运营对接：{conversionReceipt.operations_owner || '待指定'} · {conversionReceipt.operations_access_status === 'authorized' ? '等待负责人继续交接' : '客户访问待授权，请管理员在客户详情设置权限后继续交接'}</p><Button variant="outline" className="mt-3" onClick={() => window.location.assign(customerDetailPath(conversionReceipt.customer_id))}>查看客户与交接</Button></div>}

      <Sheet open={showForm && followUpOnly} onOpenChange={closeForm}>
        <SheetContent className="sales-center-ui slr-followup-sheet" overlayClassName="slr-followup-overlay" aria-describedby="slr-followup-description">
          <SheetHeader className="slr-followup-heading">
            <SheetTitle>{editing?.business_name}</SheetTitle>
            <SheetDescription id="slr-followup-description">{formatPhoneNumber(editing?.phone, editing?.country)}</SheetDescription>
          </SheetHeader>
          {editing && <>
            <div className="slr-followup-tools"><Badge className={statusColors[editing.status] || statusColors.new}>{statusLabels[editing.status] || editing.status}</Badge><CustomerPhoneDial country={editing.country} phone={editing.phone} label="拨打电话" disabled={saving || followUpSaving || editing.do_not_contact || editing.is_blacklisted || !!editing.converted_customer_id} /></div>
            {editing.do_not_contact || editing.is_blacklisted || editing.converted_customer_id
              ? <div role="status" className="slr-protection-note">{editing.converted_customer_id ? '已转正式客户' : '已停止联系'}{editing.do_not_contact_reason && <p>{editing.do_not_contact_reason}</p>}</div>
              : <fieldset disabled={saving || followUpSaving} className="slr-followup-form">
                  <div><Label htmlFor="slr-followup-outcome">本次结果</Label><NativeSelect id="slr-followup-outcome" value={followUpForm.outcome} onChange={value => setFollowUpForm(current => ({ ...current, outcome: value }))} options={followUpOutcomeOptions} /></div>
                  <div><Label htmlFor="slr-followup-notes">沟通记录 *</Label><Textarea id="slr-followup-notes" maxLength={20000} rows={7} value={followUpForm.notes} onChange={event => setFollowUpForm(current => ({ ...current, notes: event.target.value }))} placeholder="记录客户反馈和约定的下一步…" /></div>
                  {!['not_interested', 'do_not_contact'].includes(followUpForm.outcome) && <div><Label htmlFor="slr-followup-time">下次回访 · 北京时间</Label><Input id="slr-followup-time" type="datetime-local" value={followUpForm.next_follow_up_at} onChange={event => setFollowUpForm(current => ({ ...current, next_follow_up_at: event.target.value }))} /></div>}
                  {hasFollowUpDraft() && <div className="slr-draft-state"><span role="status">{followUpPersistence === 'session' ? '草稿已暂存' : '草稿仅保留在当前页面'}</span><Button type="button" size="sm" variant="ghost" aria-label="清空跟进草稿" onClick={discardFollowUpDraft}><Trash2 size={14} /></Button></div>}
                  <div className="slr-followup-save-row"><Button type="button" className="slr-followup-save" disabled={followUpSaving || editing.status === 'new'} onClick={() => void recordFollowUp()}>{followUpSaving ? '保存中…' : '保存跟进'}</Button>{['interested', 'appointment'].includes(followUpForm.outcome) && <Button type="button" variant="outline" className="slr-followup-save" disabled={followUpSaving || editing.status === 'new'} onClick={() => void recordFollowUp('quote')}>保存并准备报价</Button>}</div>
                </fieldset>}
            <details className="slr-followup-history"><summary><History size={16} />历史记录 <span>{callHistory.length}</span><ChevronDown size={15} /></summary>{historyLoading ? <p>正在加载…</p> : callHistory.length ? callHistory.map(item => <article key={item.id}><div><strong>{item.outcome_label}</strong><time>{formatDate(item.called_at)}</time></div><p>{item.notes || '未填写沟通内容'}</p><small>{item.sales_employee_name || '—'} · 下次：{formatDate(item.next_follow_up_at)}</small></article>) : <p>暂无历史记录</p>}</details>
          </>}
        </SheetContent>
      </Sheet>

      <Dialog open={showForm && !followUpOnly} onOpenChange={closeForm}>
        <DialogContent className="sales-center-ui slr-details-dialog !h-[100dvh] !max-h-[100dvh] !w-screen !max-w-none rounded-none pb-0 sm:!h-auto sm:!max-h-[90vh] sm:!w-full sm:!max-w-4xl sm:rounded-lg sm:pb-6">
          <DialogHeader><DialogTitle>{editing ? (canManage ? '编辑销售线索' : '记录跟进结果') : '新增销售线索'}</DialogTitle></DialogHeader>
          <fieldset disabled={saving || followUpSaving} className="grid min-w-0 gap-4 sm:grid-cols-2">
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
              <div><Label>分配销售</Label><NativeSelect value={form.assigned_sales_id} onChange={value => setForm({ ...form, assigned_sales_id: value })} options={[{ value: '', label: '暂不分配' }, ...assignees.map(item => ({ value: String(item.id), label: item.name }))]} /></div>
            </>}
            <div><Label>跟进状态</Label><NativeSelect value={form.status} onChange={value => setForm({ ...form, status: value })} options={statusOptions} /></div>
            <div><Label>下次跟进 · 北京时间</Label><Input type="datetime-local" value={form.next_follow_up_at} onChange={event => setForm({ ...form, next_follow_up_at: event.target.value })} /></div>
            <div className="sm:col-span-2"><Label>当前跟进摘要</Label><Textarea rows={3} value={form.notes} onChange={event => setForm({ ...form, notes: event.target.value })} placeholder="这里显示最近一次摘要；完整沟通过程请使用下方跟进时间线" /></div>
            <div className="sm:col-span-2 rounded-xl border border-rose-100 bg-rose-50/60 p-4">
              <div className="flex flex-wrap gap-5">
                <label className="flex items-center gap-2 text-sm font-medium text-rose-800"><input type="checkbox" checked={form.do_not_contact} onChange={event => setForm({ ...form, do_not_contact: event.target.checked })} />禁止再联系</label>
                {canManage && <label className="flex items-center gap-2 text-sm font-medium text-slate-800"><input type="checkbox" checked={form.is_blacklisted} onChange={event => setForm({ ...form, is_blacklisted: event.target.checked })} />加入黑名单</label>}
              </div>
              {form.do_not_contact && <Input className="mt-3 bg-white" value={form.do_not_contact_reason} onChange={event => setForm({ ...form, do_not_contact_reason: event.target.value })} placeholder="必填：禁止再联系原因" />}
            </div>
          </fieldset>
          <div className="sticky bottom-0 -mx-4 mt-4 flex gap-2 border-t bg-white/95 px-4 py-3 pb-[calc(.75rem+env(safe-area-inset-bottom))] backdrop-blur sm:static sm:mx-0 sm:justify-end sm:border-0 sm:bg-transparent sm:px-0 sm:py-0 sm:pb-0"><Button className="h-11 flex-1 sm:flex-none" variant="outline" onClick={() => closeForm(false)}>取消</Button><Button className="h-11 flex-1 sm:flex-none" disabled={saving || followUpSaving} onClick={handleSave}>{saving ? '保存中...' : '保存资料'}</Button></div>
        </DialogContent>
      </Dialog>

      {!isMobile && <Dialog open={recoveryOpen} onOpenChange={setRecoveryOpen}>
        <DialogContent className="max-h-[82vh] max-w-3xl overflow-y-auto">
          <DialogHeader><DialogTitle>线索保护与回收</DialogTitle></DialogHeader>
          <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">未触达线索超过 48 小时，或下次跟进已逾期 3 天，会进入主管可回收名单。系统不会自动抢线索；有意向、已预约线索始终受保护。</div>
          <div className="sticky top-0 z-10 rounded-xl border border-blue-200 bg-white p-3 shadow-sm"><div className="flex flex-col gap-3 sm:flex-row sm:items-center"><div className="flex-1 text-sm font-medium text-slate-700">已选择 {selectedRecoveryIds.length} 条</div><NativeSelect className="sm:w-52" value={bulkAssigneeId} onChange={setBulkAssigneeId} options={[{ value: '', label: '选择重新分配的销售' }, ...assignees.map(item => ({ value: String(item.id), label: item.name }))]} /><Button variant="outline" disabled={!selectedRecoveryIds.length || recoveryBusy === -1} onClick={() => void handleBulkRecovery('reassign')}>批量重新分配</Button><Button variant="outline" className="border-rose-200 text-rose-700" disabled={!selectedRecoveryIds.length || recoveryBusy === -1} onClick={() => void handleBulkRecovery('reclaim')}>批量回收</Button></div><p className="mt-2 text-xs text-slate-500">批量回收只允许“可回收”线索；重新分配受保护线索时会再次确认并记录原因。</p></div>
          <div className="space-y-3">{(recoveryOverview?.items || []).filter(item => item.state !== 'active').map(item => <div key={item.lead_id} className="rounded-xl border border-slate-200 p-4"><div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between"><div className="flex gap-3"><input className="mt-1 h-4 w-4" type="checkbox" checked={selectedRecoveryIds.includes(item.lead_id)} onChange={event => setSelectedRecoveryIds(current => event.target.checked ? [...current, item.lead_id] : current.filter(id => id !== item.lead_id))} /><div><div className="flex flex-wrap items-center gap-2"><p className="font-semibold text-slate-900">{item.business_name}</p><Badge className={item.state === 'recoverable' ? 'bg-rose-100 text-rose-700' : item.state === 'protected' ? 'bg-emerald-100 text-emerald-700' : item.state === 'extended' ? 'bg-blue-100 text-blue-700' : 'bg-amber-100 text-amber-800'}>{item.state === 'recoverable' ? '可回收' : item.state === 'protected' ? '受保护' : item.state === 'extended' ? '已延期保护' : '提醒跟进'}</Badge></div><p className="mt-1 text-sm text-slate-600">当前负责人：{item.assigned_sales_name || '待分配'} · {item.message}</p>{item.deadline && <p className="mt-1 text-xs text-slate-500">保护/提醒截止：{formatDate(item.deadline)}</p>}{item.extension_request && <p className="mt-1 text-xs text-violet-700">延期申请：{item.extension_request.requested_by || item.assigned_sales_name || '销售'} - {item.extension_request.reason || '未说明原因'}</p>}</div></div><div className="flex shrink-0 flex-wrap gap-2">{item.extension_request && <Button size="sm" variant="outline" disabled={recoveryBusy === item.lead_id} onClick={() => void handleRecoveryAction(item, 'approve-extension')}>{recoveryBusy === item.lead_id ? '处理中...' : '批准延期'}</Button>}{item.state === 'recoverable' && <Button size="sm" variant="outline" className="border-rose-200 text-rose-700" disabled={recoveryBusy === item.lead_id} onClick={() => void handleRecoveryAction(item, 'reclaim')}>{recoveryBusy === item.lead_id ? '处理中...' : '回收至待分配'}</Button>}</div></div></div>)}{!(recoveryOverview?.items || []).some(item => item.state !== 'active') && <p className="py-10 text-center text-sm text-slate-500">目前没有需要处理的线索保护提醒。</p>}</div>
        </DialogContent>
      </Dialog>}

      <Dialog open={!!dealLead} onOpenChange={closeDealControl}>
        <DialogContent className="sales-center-ui slr-deal-dialog !h-[100dvh] !max-h-[100dvh] !w-screen !max-w-none rounded-none pb-0 sm:!h-auto sm:!max-h-[90vh] sm:!w-full sm:!max-w-4xl sm:rounded-lg sm:pb-6">
          <DialogHeader><DialogTitle>成交审核 · {dealLead?.business_name}</DialogTitle></DialogHeader>
          <nav className="slr-deal-steps" aria-label="成交步骤"><Button variant="ghost" aria-pressed={dealStep === 'quote'} onClick={() => setDealStep('quote')}>1 报价</Button><Button variant="ghost" aria-pressed={dealStep === 'handoff'} onClick={() => setDealStep('handoff')}>2 交接</Button>{canManage && <Button variant="ghost" aria-pressed={dealStep === 'payment'} onClick={() => setDealStep('payment')}>3 收款确认</Button>}</nav>
          {dealReadiness && (dealReadiness.lead.converted_customer_id || dealReadiness.lead.do_not_contact || dealReadiness.lead.is_blacklisted) && <div role="status" className="rounded-xl border bg-slate-50 p-4 text-sm text-slate-700">{dealReadiness.lead.converted_customer_id ? <>已转为正式客户，售前资料只读。<a className="ml-3 font-medium text-blue-600" href={`/customers?detail=${dealReadiness.lead.converted_customer_id}&tab=info`}>查看客户</a></> : '该商家已停止联系，售前资料只读。'}</div>}
          {dealError ? <div role="alert" className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm">成交审核资料读取失败，请重新加载后继续。<Button className="ml-3" variant="outline" onClick={() => dealLead && void loadDealReadiness(dealLead)}>重新加载审核资料</Button></div> : dealLoading ? <div className="py-16 text-center text-sm text-slate-500">正在加载成交审核资料...</div> : <fieldset disabled={!canEditDeal || convertingId !== null} className="space-y-5">
            <div className="rounded-xl border border-amber-200 bg-amber-50 p-4"><div className="flex items-start gap-2"><FileText className="mt-0.5 h-4 w-4 text-amber-700" /><div><p className="font-semibold text-amber-900">当前待完成项</p><div className="mt-2 flex flex-wrap gap-2">{(dealReadiness?.blockers || []).map(item => <Badge key={item} className="bg-white text-amber-800 ring-1 ring-amber-200">{item}</Badge>)}{dealReadiness && dealReadiness.blockers.length === 0 && <Badge className="bg-emerald-100 text-emerald-800">审核完成，可转入正式客户</Badge>}</div></div></div></div>

            <section hidden={dealStep !== 'quote'} className="slr-deal-section rounded-xl border border-slate-200 p-4"><div className="mb-4 flex items-center gap-2"><FileText className="h-5 w-5 text-blue-600" /><div><p className="font-semibold text-slate-900">1. 报价审批单</p><p className="text-xs text-slate-500">销售提交报价；销售主管或系统管理员审批。历史报价会保留，不会覆盖。</p></div></div>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                <div><Label htmlFor="slr-quoteForm-business_line_id">业务线 *</Label><NativeSelect id="slr-quoteForm-business_line_id" value={quoteForm.business_line_id} onChange={value => setQuoteForm(current => ({ ...current, business_line_id: value, product_id: '', product_plan_id: '', package_name: '', selected_platforms: '' }))} options={[{ value: '', label: '请选择业务线' }, ...businessLines.map(item => ({ value: String(item.id), label: item.name }))]} /></div>
                <div><Label htmlFor="slr-quoteForm-product_id">具体产品 *</Label><NativeSelect id="slr-quoteForm-product_id" value={quoteForm.product_id} onChange={value => { const product = products.find(item => String(item.id) === value); setQuoteForm(current => ({ ...current, product_id: value, product_plan_id: '', package_name: product?.name || '', currency: product?.default_currency || current.currency, selected_platforms: '' })); }} options={[{ value: '', label: '请选择具体产品' }, ...quoteProducts.map(item => ({ value: String(item.id), label: item.name }))]} /></div>
                <div><Label htmlFor="slr-quoteForm-product_plan_id">套餐 / 版本</Label><NativeSelect id="slr-quoteForm-product_plan_id" value={quoteForm.product_plan_id} onChange={value => { const plan = productPlans.find(item => String(item.id) === value); setQuoteForm(current => ({ ...current, product_plan_id: value, package_name: plan?.name || current.package_name, currency: plan?.default_currency || current.currency, billing_cycle: plan?.default_billing_cycle || current.billing_cycle, list_amount: plan?.standard_price == null ? current.list_amount : String(plan.standard_price), selected_platforms: '' })); }} options={[{ value: '', label: quotePlans.length ? '请选择套餐版本' : '当前产品暂无套餐版本' }, ...quotePlans.map(item => ({ value: String(item.id), label: `${item.name}${item.standard_price == null ? ' · 待定价' : ` · ${item.default_currency} ${item.standard_price}`}` }))]} /></div>
                <div><Label htmlFor="slr-quoteForm-billing_cycle">收费周期 *</Label><NativeSelect id="slr-quoteForm-billing_cycle" value={quoteForm.billing_cycle} onChange={value => setQuoteForm({ ...quoteForm, billing_cycle: value, billing_mode: value === 'one_time' ? 'manual' : quoteForm.billing_mode })} options={billingCycleOptions} /></div>
                <div><Label htmlFor="slr-quoteForm-billing_mode">收款方式</Label><NativeSelect id="slr-quoteForm-billing_mode" value={quoteForm.billing_mode} onChange={value => setQuoteForm({ ...quoteForm, billing_mode: value })} options={[{ value: 'manual', label: '人工收款 / 支票 / 转账' }, { value: 'subscription', label: '自动订阅扣款' }]} /></div>
                <div><Label htmlFor="slr-quoteForm-payment_method">支付渠道</Label><NativeSelect id="slr-quoteForm-payment_method" value={quoteForm.payment_method} onChange={value => setQuoteForm({ ...quoteForm, payment_method: value })} options={[{ value: 'stripe', label: 'Stripe' }, { value: 'check', label: '支票' }, { value: 'zelle', label: 'Zelle' }, { value: 'bank_transfer', label: '银行转账' }, { value: 'other', label: '其他' }]} /></div>
                <div className="sm:col-span-2 lg:col-span-3"><div className="flex items-center justify-between"><Label>实际运营平台 / 服务范围</Label>{selectedQuotePlan?.platform_limit && <span className="text-xs text-slate-500">最多 {selectedQuotePlan.platform_limit} 项，已选 {selectedPlatforms.length}</span>}</div><div className="mt-2 flex flex-wrap gap-2">{platformOptions.map(platform => { const checked = selectedPlatforms.includes(platform); const limitReached = !!selectedQuotePlan?.platform_limit && selectedPlatforms.length >= selectedQuotePlan.platform_limit && !checked; return <label key={platform} className={`flex cursor-pointer items-center gap-2 rounded-lg border px-3 py-2 text-sm ${checked ? 'border-blue-300 bg-blue-50 text-blue-700' : 'border-slate-200 bg-white text-slate-600'} ${limitReached ? 'cursor-not-allowed opacity-50' : ''}`}><input type="checkbox" checked={checked} disabled={limitReached} onChange={() => { const next = checked ? selectedPlatforms.filter(item => item !== platform) : [...selectedPlatforms, platform]; setQuoteForm({ ...quoteForm, selected_platforms: next.join(', ') }); }} />{platform}</label>; })}</div><Input className="mt-2" value={quoteForm.selected_platforms} onChange={event => setQuoteForm({ ...quoteForm, selected_platforms: event.target.value })} placeholder="可补充其他平台或服务范围，用逗号分隔" /></div>
                <div><Label htmlFor="slr-quoteForm-list_amount">原报价 *</Label><Input id="slr-quoteForm-list_amount" type="number" min="0" value={quoteForm.list_amount} onChange={event => setQuoteForm({ ...quoteForm, list_amount: event.target.value })} /></div><div><Label htmlFor="slr-quoteForm-discount_amount">优惠金额</Label><Input id="slr-quoteForm-discount_amount" type="number" min="0" value={quoteForm.discount_amount} onChange={event => setQuoteForm({ ...quoteForm, discount_amount: event.target.value })} /></div><div><Label htmlFor="slr-quoteForm-currency">币种</Label><NativeSelect id="slr-quoteForm-currency" value={quoteForm.currency} onChange={value => setQuoteForm({ ...quoteForm, currency: value })} options={[{ value: 'USD', label: 'USD 美元' }, { value: 'CNY', label: 'CNY 人民币' }]} /></div>
                <div><Label htmlFor="slr-quoteForm-service_start_date">服务开始</Label><Input id="slr-quoteForm-service_start_date" type="date" value={quoteForm.service_start_date} onChange={event => setQuoteForm({ ...quoteForm, service_start_date: event.target.value })} /></div><div><Label htmlFor="slr-quoteForm-service_end_date">服务结束</Label><Input id="slr-quoteForm-service_end_date" type="date" value={quoteForm.service_end_date} onChange={event => setQuoteForm({ ...quoteForm, service_end_date: event.target.value })} /></div><div className="flex items-end"><Button className="w-full" disabled={dealSaving} onClick={() => void submitQuote()}>提交报价审批</Button></div>
                <div className="sm:col-span-2 lg:col-span-3"><Label htmlFor="slr-quoteForm-special_terms">特殊条款 / 折扣原因</Label><Textarea id="slr-quoteForm-special_terms" rows={2} value={quoteForm.special_terms} onChange={event => setQuoteForm({ ...quoteForm, special_terms: event.target.value })} placeholder="例如：客户需求、折扣依据、交付范围" /></div>
              </div>
              <div className="mt-4 space-y-2">{(dealReadiness?.quotes || []).map(quote => <div key={quote.id} className={`flex flex-col gap-2 rounded-lg border p-3 sm:flex-row sm:items-center sm:justify-between ${quote.status === 'superseded' ? 'bg-slate-100 opacity-70' : 'bg-slate-50'}`}><div><p className="font-medium text-slate-900">{quote.package_name} · {quote.currency} {quote.final_amount.toFixed(2)}</p><p className="text-xs text-slate-500">{quote.selected_platforms.join('、') || '未指定平台'} · {billingCycleOptions.find(item => item.value === quote.billing_cycle)?.label || quote.billing_cycle} · {quote.billing_mode === 'subscription' ? '自动扣款' : '人工收款'} · {quote.payment_method}</p>{!quote.business_line_id && <p className="mt-1 text-xs text-amber-700">历史报价：尚未关联业务线与产品，后续新报价将自动归类</p>}{quote.review_notes && <p className="mt-1 text-xs text-slate-600">审批备注：{quote.review_notes}</p>}</div><div className="flex items-center gap-2"><Badge className={quote.status === 'approved' ? 'bg-emerald-100 text-emerald-700' : quote.status === 'rejected' ? 'bg-rose-100 text-rose-700' : quote.status === 'superseded' ? 'bg-slate-200 text-slate-600' : 'bg-amber-100 text-amber-800'}>{quote.status === 'approved' ? '当前生效' : quote.status === 'rejected' ? '已驳回' : quote.status === 'superseded' ? '历史失效' : '待审批'}</Badge>{canManage && quote.status === 'submitted' && <><Button size="sm" variant="outline" className="border-emerald-200 text-emerald-700" disabled={dealSaving} onClick={() => void reviewQuote(quote, 'approved')}>批准</Button><Button size="sm" variant="outline" className="border-rose-200 text-rose-700" disabled={dealSaving} onClick={() => void reviewQuote(quote, 'rejected')}>驳回</Button></>}</div></div>)}{!(dealReadiness?.quotes || []).length && <p className="py-3 text-center text-sm text-slate-400">尚未提交报价</p>}</div>
            </section>

            <section hidden={dealStep !== 'handoff'} className="slr-deal-section rounded-xl border border-slate-200 p-4"><div className="mb-4 flex items-center gap-2"><ClipboardCheck className="h-5 w-5 text-violet-600" /><div><p className="font-semibold text-slate-900">2. 成交交接清单</p><p className="text-xs text-slate-500">成交前把客户目标、对接人和运营安排写清楚，避免销售与运营信息断层。</p></div></div><div className="grid gap-3 sm:grid-cols-2"><div><Label htmlFor="slr-handoffForm-quote_id">关联当前生效报价</Label><NativeSelect id="slr-handoffForm-quote_id" value={handoffForm.quote_id} onChange={value => setHandoffForm({ ...handoffForm, quote_id: value })} options={[{ value: '', label: '请选择已批准报价' }, ...(dealReadiness?.quotes || []).filter(quote => quote.status === 'approved').map(quote => ({ value: String(quote.id), label: `${quote.package_name} · ${quote.currency} ${quote.final_amount}` }))]} /></div><div><Label htmlFor="slr-handoffForm-operations_owner_employee_id">运营对接负责人 *</Label><NativeSelect id="slr-handoffForm-operations_owner_employee_id" value={handoffForm.operations_owner_employee_id} onChange={value => { const owner = dealEmployees.find(item => String(item.id) === value); setHandoffForm({ ...handoffForm, operations_owner_employee_id: value, operations_owner: owner?.name || '' }); }} options={[{ value: '', label: '请选择在职员工' }, ...dealEmployees.map(item => ({ value: String(item.id), label: `${item.name} · ${item.department || item.position || item.role}` }))]} /></div><div className="sm:col-span-2"><Label>协作人（可多选）</Label><div className="mt-2 flex flex-wrap gap-2">{dealEmployees.filter(item => String(item.id) !== handoffForm.operations_owner_employee_id).map(item => { const checked = handoffForm.collaborator_employee_ids.includes(item.id); return <label key={item.id} className={`flex cursor-pointer items-center gap-2 rounded-lg border px-3 py-2 text-sm ${checked ? 'border-violet-300 bg-violet-50 text-violet-700' : 'border-slate-200 bg-white text-slate-600'}`}><input type="checkbox" checked={checked} onChange={() => setHandoffForm({ ...handoffForm, collaborator_employee_ids: checked ? handoffForm.collaborator_employee_ids.filter(id => id !== item.id) : [...handoffForm.collaborator_employee_ids, item.id] })} />{item.name}<span className="text-xs opacity-70">{item.department || item.role}</span></label>; })}</div></div><div className="sm:col-span-2"><Label htmlFor="slr-handoffForm-customer_goal">客户目标 *</Label><Textarea id="slr-handoffForm-customer_goal" rows={2} value={handoffForm.customer_goal} onChange={event => setHandoffForm({ ...handoffForm, customer_goal: event.target.value })} placeholder="例如：提升本地搜索曝光、预约量或内容更新频率" /></div><div className="sm:col-span-2"><Label htmlFor="slr-handoffForm-key_contacts">关键联系人 / 对接方式 *</Label><Textarea id="slr-handoffForm-key_contacts" rows={2} value={handoffForm.key_contacts} onChange={event => setHandoffForm({ ...handoffForm, key_contacts: event.target.value })} placeholder="联系人姓名、电话、邮箱、谁负责提供素材或权限" /></div><div><Label htmlFor="slr-handoffForm-service_start_date">服务开始</Label><Input id="slr-handoffForm-service_start_date" type="date" value={handoffForm.service_start_date} onChange={event => setHandoffForm({ ...handoffForm, service_start_date: event.target.value })} /></div><div><Label htmlFor="slr-handoffForm-service_end_date">服务结束</Label><Input id="slr-handoffForm-service_end_date" type="date" value={handoffForm.service_end_date} onChange={event => setHandoffForm({ ...handoffForm, service_end_date: event.target.value })} /></div><div className="sm:col-span-2"><Label htmlFor="slr-handoffForm-special_commitments">特殊承诺 / 注意事项</Label><Textarea id="slr-handoffForm-special_commitments" rows={2} value={handoffForm.special_commitments} onChange={event => setHandoffForm({ ...handoffForm, special_commitments: event.target.value })} /></div><div className="sm:col-span-2"><Label htmlFor="slr-handoffForm-handoff_notes">交接备注</Label><Textarea id="slr-handoffForm-handoff_notes" rows={2} value={handoffForm.handoff_notes} onChange={event => setHandoffForm({ ...handoffForm, handoff_notes: event.target.value })} /></div></div><div className="mt-4 flex flex-wrap gap-5 rounded-lg bg-slate-50 p-3"><label className="flex items-center gap-2 text-sm font-medium text-slate-700"><input type="checkbox" checked={handoffForm.operations_group_created} onChange={event => setHandoffForm({ ...handoffForm, operations_group_created: event.target.checked })} />已建立运营对接群 *</label><label className="flex items-center gap-2 text-sm font-medium text-slate-700"><input type="checkbox" checked={handoffForm.generate_service_board} onChange={event => setHandoffForm({ ...handoffForm, generate_service_board: event.target.checked })} />转入后生成服务看板</label></div><div className="mt-4"><Button disabled={dealSaving} onClick={() => void saveHandoff()}>保存成交交接清单</Button></div></section>

            {canManage && <section hidden={dealStep !== 'payment'} className="slr-deal-section rounded-xl border border-cyan-200 bg-cyan-50/40 p-4"><div className="mb-4 flex items-center gap-2"><CheckCircle2 className="h-5 w-5 text-cyan-700" /><div><p className="font-semibold text-slate-900">3. 收款确认</p><p className="text-xs text-slate-500">由主管按财务核对结果确认；全额支付后才可转入正式客户。</p></div></div><div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4"><div><Label htmlFor="slr-paymentForm-payment_status">收款状态</Label><NativeSelect id="slr-paymentForm-payment_status" value={paymentForm.payment_status} onChange={value => setPaymentForm({ ...paymentForm, payment_status: value })} options={[{ value: 'pending', label: '待收款' }, { value: 'deposit_paid', label: '已收订金' }, { value: 'paid', label: '已全额支付' }, { value: 'failed', label: '支付失败' }, { value: 'refunded', label: '已退款' }]} /></div><div><Label htmlFor="slr-paymentForm-amount_received">实收金额</Label><Input id="slr-paymentForm-amount_received" type="number" min="0" value={paymentForm.amount_received} onChange={event => setPaymentForm({ ...paymentForm, amount_received: event.target.value })} step="0.01" placeholder="填写已核对的实际到账金额" /></div><div><Label htmlFor="slr-paymentForm-payment_date">实际收款日期</Label><Input id="slr-paymentForm-payment_date" type="date" value={paymentForm.payment_date} onChange={event => setPaymentForm({ ...paymentForm, payment_date: event.target.value })} /></div><div><Label htmlFor="slr-paymentForm-payment_reference">交易号 / 支票号</Label><Input id="slr-paymentForm-payment_reference" value={paymentForm.payment_reference} onChange={event => setPaymentForm({ ...paymentForm, payment_reference: event.target.value })} /></div></div><div className="mt-4 flex flex-wrap items-center justify-between gap-3"><div className="text-xs text-slate-500">{dealReadiness?.handoff?.payment_confirmed_by_name ? `最近确认：${dealReadiness.handoff.payment_confirmed_by_name}` : '尚未由主管确认收款状态'}</div><Button disabled={dealSaving || !dealReadiness?.handoff} onClick={() => void savePaymentStatus()}>保存收款状态</Button></div></section>}

            {dealStep !== 'payment' && <div className="slr-deal-next"><Button variant="outline" disabled={dealSaving} onClick={() => setDealStep(dealStep === 'quote' ? 'handoff' : canManage ? 'payment' : 'quote')}>{dealStep === 'quote' ? '继续填写交接' : canManage ? '继续收款确认' : '返回报价'}</Button></div>}
            {canManage && dealStep === 'payment' && <div className="sticky bottom-0 -mx-4 flex justify-end border-t bg-white/95 px-4 py-3 pb-[calc(.75rem+env(safe-area-inset-bottom))] backdrop-blur sm:static sm:mx-0 sm:bg-transparent sm:px-0 sm:pb-0 sm:pt-4"><Button disabled={dealSaving || dealLoading || dealError || !dealReadiness || !!dealReadiness.blockers.length || convertingId === dealLead?.id} className="h-11 w-full bg-emerald-600 hover:bg-emerald-700 sm:w-auto" onClick={() => void convertToCustomer()}><CheckCircle2 className="mr-2 h-4 w-4" />{convertingId === dealLead?.id ? '转入中...' : dealReadiness?.blockers?.length ? '请先完成审核项' : '确认合作并转入正式客户'}</Button></div>}
          </fieldset>}
        </DialogContent>
      </Dialog>
    </div>
  );
}
