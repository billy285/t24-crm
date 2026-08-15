import { useEffect, useMemo, useRef, useState } from 'react';
import {
  ArrowRightLeft, Ban, BarChart3, Building2, CheckCircle2, Clipboard, ClipboardCheck, Clock3, Edit3, FileText, Headphones, History, MessageSquarePlus, MoreHorizontal, Phone, Plus, Search, ShieldAlert, UserCheck, Users,
} from 'lucide-react';
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
import { businessDateKey } from '@/lib/business-date';
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
type CallHistoryItem = { id: number; outcome: string; outcome_label: string; notes?: string; next_follow_up_at?: string; called_at: string; sales_employee_name?: string };
type Quote = { id: number; business_line_id?: number; product_id?: number; product_plan_id?: number; package_name: string; selected_platforms: string[]; billing_mode: string; billing_cycle: string; payment_method: string; currency: string; list_amount: number; discount_amount: number; final_amount: number; service_start_date?: string; service_end_date?: string; special_terms?: string; status: 'submitted' | 'approved' | 'rejected' | 'superseded'; submitted_by_name?: string; reviewed_by_name?: string; review_notes?: string };
type Handoff = { quote_id?: number; customer_goal?: string; key_contacts?: string; service_start_date?: string; service_end_date?: string; special_commitments?: string; operations_owner?: string; operations_owner_employee_id?: number; collaborator_employee_ids?: number[]; operations_group_created?: boolean; finance_payment_confirmed?: boolean; payment_status?: string; amount_received?: number; payment_date?: string; payment_reference?: string; payment_confirmed_by_name?: string; generated_deal_id?: number; generate_service_board?: boolean; handoff_notes?: string };
type DealReadiness = { lead: { id: number; business_name: string; converted_customer_id?: number }; quotes: Quote[]; handoff: Handoff; blockers: string[] };
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
  return value.slice(0, 16).replace('T', ' ');
}

function nextLeadAction(lead: SalesLead) {
  if (lead.converted_customer_id) return '查看已转入的正式客户';
  if (lead.do_not_contact || lead.is_blacklisted) return '已停止联系，等待主管复核';
  if (lead.status === 'new') return '完成首次联系并记录结果';
  if (lead.next_follow_up_at) return `按计划跟进 · ${formatDate(lead.next_follow_up_at)}`;
  return '补充下一步跟进时间';
}

function phoneHref(phone: string) {
  return `tel:${phone.replace(/[^+\d]/g, '')}`;
}

export default function SalesLeads() {
  const { role, isAdmin, employee } = useRole();
  const isMobile = useIsMobile();
  const canManage = isAdmin || role === 'sales_manager';
  const [items, setItems] = useState<SalesLead[]>([]);
  const [assignees, setAssignees] = useState<Assignee[]>([]);
  const [stats, setStats] = useState({ total: 0, assigned: 0, unassigned: 0, blacklisted: 0, do_not_contact: 0 });
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [contactFilter, setContactFilter] = useState('');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [total, setTotal] = useState(0);
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState<SalesLead | null>(null);
  const [form, setForm] = useState(emptyForm);
  const [saving, setSaving] = useState(false);
  const [dashboard, setDashboard] = useState<ManagementDashboard | null>(null);
  const [convertingId, setConvertingId] = useState<number | null>(null);
  const [dealLead, setDealLead] = useState<SalesLead | null>(null);
  const [dealReadiness, setDealReadiness] = useState<DealReadiness | null>(null);
  const [dealLoading, setDealLoading] = useState(false);
  const [dealSaving, setDealSaving] = useState(false);
  const [quoteForm, setQuoteForm] = useState(emptyQuoteForm);
  const [handoffForm, setHandoffForm] = useState(emptyHandoffForm);
  const [paymentForm, setPaymentForm] = useState(createEmptyPaymentForm);
  const [recoveryOverview, setRecoveryOverview] = useState<RecoveryOverview | null>(null);
  const [recoveryOpen, setRecoveryOpen] = useState(false);
  const [recoveryBusy, setRecoveryBusy] = useState<number | null>(null);
  const [performanceDays, setPerformanceDays] = useState(30);
  const [performanceDashboard, setPerformanceDashboard] = useState<PerformanceDashboard | null>(null);
  const [callHistory, setCallHistory] = useState<CallHistoryItem[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [followUpSaving, setFollowUpSaving] = useState(false);
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

      const [listResult, statsResult] = coreResults;
      const failedSections: string[] = [];
      if (listResult.status === 'fulfilled') {
        const nextItems = listResult.value.data?.items || [];
        setItems(nextItems);
        setTotal(listResult.value.data?.total || 0);
        setSelectedLeadIds(current => current.filter(id => nextItems.some((item: SalesLead) => item.id === id)));
      } else {
        failedSections.push('线索列表');
      }
      if (statsResult.status === 'fulfilled') setStats(statsResult.value.data || stats);
      else failedSections.push('统计');

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
    void loadData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, pageSize, statusFilter, contactFilter, performanceDays]);

  useEffect(() => {
    setPage(1);
    const timer = window.setTimeout(() => void loadData({ page: 1 }), 300);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search]);

  useAutoRefresh(loadData, { intervalMs: 30000, enabled: !showForm });

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
      await navigator.clipboard.writeText(lead.phone);
      toast.success(`已复制 ${lead.business_name} 的电话`);
    } catch {
      toast.error('电话号码复制失败，请长按号码复制');
    }
  };

  const openCreate = () => {
    setEditing(null);
    setForm(emptyForm);
    setShowForm(true);
  };

  const loadCallHistory = async (leadId: number) => {
    setHistoryLoading(true);
    try {
      const response = await invokeWithAuth({ url: `/api/v1/sales-leads/${leadId}/call-history`, method: 'GET' });
      setCallHistory(response.data || []);
    } catch (error: any) {
      setCallHistory([]);
      toast.error(error?.data?.detail || error?.message || '跟进时间线加载失败');
    } finally {
      setHistoryLoading(false);
    }
  };

  const openEdit = (lead: SalesLead) => {
    setEditing(lead);
    setForm({
      business_name: lead.business_name || '', contact_name: lead.contact_name || '', phone: lead.phone || '',
      industry: lead.industry || '', country: lead.country || 'US', state: lead.state || '', city: lead.city || '',
      address: lead.address || '', website: lead.website || '', source: lead.source || '', status: lead.status || 'new',
      assigned_sales_id: lead.assigned_sales_id ? String(lead.assigned_sales_id) : '', notes: lead.notes || '',
      is_blacklisted: !!lead.is_blacklisted, do_not_contact: !!lead.do_not_contact,
      do_not_contact_reason: lead.do_not_contact_reason || '', next_follow_up_at: lead.next_follow_up_at?.slice(0, 16) || '',
    });
    setCallHistory([]);
    setFollowUpForm({ outcome: lead.status === 'appointment' ? 'appointment' : lead.status === 'interested' ? 'interested' : 'callback', notes: '', next_follow_up_at: lead.next_follow_up_at?.slice(0, 16) || '' });
    setShowForm(true);
    void loadCallHistory(lead.id);
  };

  const recordFollowUp = async () => {
    if (!editing) return;
    if (!followUpForm.notes.trim()) {
      toast.error('请填写本次沟通内容，避免产生空白跟进记录');
      return;
    }
    if (followUpForm.outcome === 'callback' && !followUpForm.next_follow_up_at) {
      toast.error('待回访请设置下次跟进时间');
      return;
    }
    setFollowUpSaving(true);
    try {
      const response = await invokeWithAuth({
        url: `/api/v1/sales-leads/${editing.id}/follow-up`,
        method: 'POST',
        data: {
          outcome: followUpForm.outcome,
          notes: followUpForm.notes.trim(),
          next_follow_up_at: followUpForm.next_follow_up_at ? new Date(followUpForm.next_follow_up_at).toISOString() : null,
        },
      });
      const nextValue = response.data?.next_follow_up_at?.slice(0, 16) || '';
      setForm(current => ({ ...current, status: response.data?.status || current.status, notes: followUpForm.notes.trim(), next_follow_up_at: nextValue }));
      setEditing(current => current ? ({ ...current, status: response.data?.status || current.status, notes: followUpForm.notes.trim(), next_follow_up_at: response.data?.next_follow_up_at || current.next_follow_up_at }) : current);
      setFollowUpForm(current => ({ ...current, notes: '', next_follow_up_at: nextValue }));
      await Promise.all([loadCallHistory(editing.id), loadData()]);
      toast.success(response.data?.message || '跟进记录已加入时间线');
    } catch (error: any) {
      toast.error(error?.data?.detail || error?.response?.data?.detail || error?.message || '跟进记录保存失败');
    } finally {
      setFollowUpSaving(false);
    }
  };

  const handleSave = async () => {
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
        next_follow_up_at: form.next_follow_up_at ? new Date(form.next_follow_up_at).toISOString() : null,
      };
      const managerPayload = {
        ...limitedPayload,
        business_name: form.business_name.trim(), contact_name: form.contact_name || null, phone: form.phone.trim(),
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

  const loadDealReadiness = async (lead: SalesLead) => {
    setDealLoading(true);
    try {
      const response = await invokeWithAuth({ url: `/api/v1/sales-deal-controls/${lead.id}/readiness`, method: 'GET' });
      const readiness = response.data as DealReadiness;
      setDealReadiness(readiness);
      const handoff = readiness.handoff || {};
      const activeQuote = readiness.quotes.find(quote => quote.status === 'approved');
      setHandoffForm({
        quote_id: handoff.quote_id ? String(handoff.quote_id) : (activeQuote ? String(activeQuote.id) : ''), customer_goal: handoff.customer_goal || '', key_contacts: handoff.key_contacts || '',
        service_start_date: handoff.service_start_date || activeQuote?.service_start_date || '', service_end_date: handoff.service_end_date || activeQuote?.service_end_date || '', special_commitments: handoff.special_commitments || '',
        operations_owner: handoff.operations_owner || '', operations_owner_employee_id: handoff.operations_owner_employee_id ? String(handoff.operations_owner_employee_id) : '',
        collaborator_employee_ids: handoff.collaborator_employee_ids || [], operations_group_created: !!handoff.operations_group_created,
        generate_service_board: !!handoff.generate_service_board, handoff_notes: handoff.handoff_notes || '',
      });
      setPaymentForm({
        payment_status: handoff.payment_status || (handoff.finance_payment_confirmed ? 'paid' : 'pending'),
        amount_received: handoff.amount_received ? String(handoff.amount_received) : '',
        payment_date: handoff.payment_date || businessDateKey(), payment_reference: handoff.payment_reference || '',
      });
    } catch (error: any) {
      toast.error(error?.data?.detail || error?.message || '成交审核信息加载失败');
    } finally { setDealLoading(false); }
  };

  const openDealControl = async (lead: SalesLead) => {
    setDealLead(lead);
    setDealReadiness(null);
    setQuoteForm(emptyQuoteForm);
    setHandoffForm(emptyHandoffForm);
    setPaymentForm(createEmptyPaymentForm());
    await loadDealReadiness(lead);
  };

  const submitQuote = async () => {
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
    if (!dealLead) return;
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
      await loadDealReadiness(dealLead);
    } catch (error: any) {
      toast.error(error?.data?.detail || error?.message || '成交交接清单保存失败');
    } finally { setDealSaving(false); }
  };

  const savePaymentStatus = async () => {
    if (!dealLead) return;
    setDealSaving(true);
    try {
      await invokeWithAuth({
        url: `/api/v1/sales-deal-controls/${dealLead.id}/handoff/finance-confirmation`, method: 'POST', data: {
          payment_status: paymentForm.payment_status, amount_received: Number(paymentForm.amount_received || 0),
          payment_date: paymentForm.payment_date || null, payment_reference: paymentForm.payment_reference || null,
        },
      });
      toast.success('收款状态已更新');
      await loadDealReadiness(dealLead);
    } catch (error: any) {
      toast.error(error?.data?.detail || error?.message || '收款确认失败');
    } finally { setDealSaving(false); }
  };

  const convertToCustomer = async () => {
    if (!dealLead) return;
    if (!window.confirm(`确认 ${dealLead.business_name} 已正式合作，并转入客户管理吗？此操作会保留销售线索、报价和通话历史。`)) return;
    const lead = dealLead;
    setConvertingId(lead.id);
    try {
      const response = await invokeWithAuth({ url: `/api/v1/sales-leads/${lead.id}/convert-to-customer`, method: 'POST', data: { confirmation_notes: '报价已审批、成交交接清单已完成，主管确认合作。' } });
      toast.success(`已转入正式客户：${response.data?.customer_code || ''}`);
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

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <div className="mb-1 flex items-center gap-2 text-sm font-medium text-blue-600">
            <Headphones className="h-4 w-4" /> 独立售前数据区
          </div>
          <h2 className="text-2xl font-bold text-slate-900">{canManage ? '电话销售中心' : '我的销售线索'}</h2>
          <p className="mt-1 text-sm text-slate-500">当前范围：{scopeText}。这里的陌生商家不会进入正式客户管理。</p>
        </div>
        {canManage && <Button className="h-11 w-full sm:w-auto" onClick={openCreate}><Plus className="mr-2 h-4 w-4" />新增线索</Button>}
      </div>

      <div className="rounded-xl border border-blue-100 bg-blue-50/70 px-4 py-3 text-sm leading-6 text-blue-900 md:hidden">
        手机端优先完成拨号、复制号码和记录跟进。批量改派等管理操作请使用电脑；禁联、黑名单与成交审核收在单条线索的“更多”中。
      </div>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        {[
          { label: '可见线索', value: stats.total, icon: Building2, color: 'text-blue-600 bg-blue-50' },
          { label: '已分配', value: stats.assigned, icon: UserCheck, color: 'text-emerald-600 bg-emerald-50' },
          { label: '待分配', value: stats.unassigned, icon: Users, color: 'text-amber-600 bg-amber-50' },
          { label: '禁止再联系', value: stats.do_not_contact, icon: Ban, color: 'text-rose-600 bg-rose-50' },
          { label: '黑名单', value: stats.blacklisted, icon: ShieldAlert, color: 'text-slate-700 bg-slate-100' },
        ].map(stat => (
          <Card key={stat.label} className="border-slate-200 shadow-sm">
            <CardContent className="flex items-center gap-3 p-4">
              <div className={`rounded-xl p-2.5 ${stat.color}`}><stat.icon className="h-5 w-5" /></div>
              <div><p className="text-xs text-slate-500">{stat.label}</p><p className="text-2xl font-bold text-slate-900">{stat.value}</p></div>
            </CardContent>
          </Card>
        ))}
      </div>

      {canManage && dashboard && <Card className="border-indigo-100 bg-gradient-to-r from-indigo-50 via-white to-blue-50 shadow-sm"><CardContent className="p-5"><div className="mb-4 flex items-center gap-2"><BarChart3 className="h-5 w-5 text-indigo-600" /><div><p className="font-semibold text-slate-900">销售管理驾驶舱</p><p className="text-xs text-slate-500">仅统计电话销售线索，不混入正式客户与财务数据。</p></div></div><div className="grid grid-cols-2 gap-3 md:grid-cols-4 lg:grid-cols-7">{[
        ['任务完成', `${dashboard.metrics.completed}/${dashboard.metrics.assigned}`, `${dashboard.metrics.completion_rate}%`], ['接通率', `${dashboard.metrics.connected}/${dashboard.metrics.calls}`, `${dashboard.metrics.connection_rate}%`], ['意向率', String(dashboard.metrics.interested), `${dashboard.metrics.interest_rate}%`], ['预约率', String(dashboard.metrics.appointments), `${dashboard.metrics.appointment_rate}%`], ['成交率', String(dashboard.metrics.converted), `${dashboard.metrics.conversion_rate}%`], ['来源质量', String(dashboard.source_quality.reduce((sum, item) => sum + item.usable, 0)), `${dashboard.source_quality.reduce((sum, item) => sum + item.total, 0)} 条可追溯`], ['销售人数', String(dashboard.salespeople.length), '今日有保存结果']
      ].map(([label, value, sub]) => <div key={label} className="rounded-xl border border-white bg-white/80 p-3"><p className="text-xs text-slate-500">{label}</p><p className="mt-1 text-xl font-bold text-slate-900">{value}</p><p className="mt-1 text-xs text-indigo-600">{sub}</p></div>)}</div></CardContent></Card>}

      {canManage && performanceDashboard && (
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

      {canManage && recoveryOverview && <Card className="border-amber-200 bg-amber-50/60 shadow-sm"><CardContent className="flex flex-col gap-4 p-5 lg:flex-row lg:items-center"><ShieldAlert className="h-8 w-8 text-amber-600" /><div className="flex-1"><p className="font-semibold text-slate-900">线索保护与回收</p><p className="mt-1 text-sm text-slate-600">系统只提示，主管确认后才会回收。已联系、有意向和已预约的线索不会被系统自动转走。</p><div className="mt-3 flex flex-wrap gap-2 text-xs"><Badge className="bg-rose-100 text-rose-700">可回收 {recoveryOverview.summary.recoverable}</Badge><Badge className="bg-amber-100 text-amber-800">提醒跟进 {recoveryOverview.summary.watch}</Badge><Badge className="bg-emerald-100 text-emerald-700">受保护 {recoveryOverview.summary.protected}</Badge><Badge className="bg-blue-100 text-blue-700">延期保护 {recoveryOverview.summary.extended}</Badge>{recoveryOverview.summary.extension_requests > 0 && <Badge className="bg-violet-100 text-violet-700">待审批延期 {recoveryOverview.summary.extension_requests}</Badge>}</div></div>{isMobile ? <p className="text-xs font-medium text-amber-800">批量回收与改派请在电脑端处理</p> : <Button variant="outline" onClick={() => setRecoveryOpen(true)}>查看并处理</Button>}</CardContent></Card>}

      <Card className="border-slate-200 shadow-sm">
        <CardContent className="p-4">
          <div className="flex flex-col gap-3 lg:flex-row">
            <div className="relative flex-1">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
              <Input className="pl-9" value={search} onChange={event => setSearch(event.target.value)} placeholder="搜索商家、联系人、电话或城市" />
            </div>
            <NativeSelect className="lg:w-40" value={statusFilter} onChange={setStatusFilter} options={[{ value: '', label: '全部状态' }, ...statusOptions]} />
            <NativeSelect className="lg:w-44" value={contactFilter} onChange={setContactFilter} options={[
              { value: '', label: '全部联系规则' }, { value: 'contactable', label: '允许联系' },
              { value: 'do_not_contact', label: '禁止再联系' }, { value: 'blacklisted', label: '黑名单' },
            ]} />
          </div>
        </CardContent>
      </Card>

      <Card className="overflow-hidden border-slate-200 shadow-sm">
        <CardContent className="p-0">
          {canManage && !isMobile && <div className="flex flex-col gap-3 border-b bg-blue-50/60 px-4 py-3 sm:flex-row sm:items-center"><p className="flex-1 text-sm font-medium text-slate-700">当前页已选 {selectedLeadIds.length} 条，可批量补齐待分配线索或调整负责人</p><NativeSelect className="sm:w-52" value={bulkAssigneeId} onChange={setBulkAssigneeId} options={[{ value: '', label: '选择目标销售' }, ...assignees.map(item => ({ value: String(item.id), label: item.name }))]} /><Button size="sm" variant="outline" disabled={!selectedLeadIds.length || !bulkAssigneeId || recoveryBusy === -1} onClick={() => void handleBulkRecovery('reassign', selectedLeadIds)}>批量分配 / 改派</Button></div>}
          <div data-testid="sales-leads-mobile-list" className="divide-y divide-slate-100 md:hidden">
            {loading ? <p className="px-4 py-12 text-center text-sm text-slate-400">正在加载线索...</p>
              : items.length === 0 ? <p className="px-4 py-12 text-center text-sm text-slate-400">当前范围暂无销售线索</p>
              : items.map(lead => {
                const protectedLead = lead.is_blacklisted || lead.do_not_contact;
                return (
                  <article key={lead.id} data-testid="sales-lead-mobile-card" className={protectedLead ? 'bg-rose-50/40 p-4' : 'bg-white p-4'}>
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <p className="break-words font-semibold leading-6 text-slate-950">{lead.business_name}</p>
                        <p className="mt-0.5 text-xs text-slate-500">{lead.contact_name || '未填写联系人'} · {lead.assigned_sales_name || '待分配'}</p>
                      </div>
                      <Badge className={`shrink-0 ${statusColors[lead.status] || statusColors.new}`}>{statusLabels[lead.status] || lead.status}</Badge>
                    </div>
                    <div className="mt-3 flex flex-wrap gap-1.5">{lead.do_not_contact && <Badge className="bg-rose-100 text-rose-700">禁止再联系</Badge>}{lead.is_blacklisted && <Badge className="bg-slate-800 text-white">黑名单</Badge>}{lead.converted_customer_id && <Badge className="bg-emerald-100 text-emerald-700">已转正式客户</Badge>}</div>
                    <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-3 text-sm">
                      <div><dt className="text-xs text-slate-400">电话</dt><dd className={protectedLead ? 'mt-0.5 break-words text-slate-400 line-through' : 'mt-0.5 break-words font-medium text-blue-700'}>{lead.phone}</dd></div>
                      <div><dt className="text-xs text-slate-400">地区 / 行业</dt><dd className="mt-0.5 break-words text-slate-700">{[lead.city, lead.state].filter(Boolean).join(', ') || '地区未采集'} · {lead.industry || '未分类'}</dd></div>
                    </dl>
                    <div className="mt-3 rounded-lg bg-slate-50 px-3 py-2.5 text-sm leading-5 text-slate-700"><span className="font-medium text-indigo-700">下一步：</span>{nextLeadAction(lead)}</div>
                    <div className="mt-4 grid grid-cols-2 gap-2">
                      {protectedLead ? <Button className="h-11 px-2" variant="outline" disabled><Phone className="h-4 w-4" />拨号</Button> : <Button className="h-11 px-2" variant="outline" asChild><a href={phoneHref(lead.phone)}><Phone className="h-4 w-4" />拨号</a></Button>}
                      <Button className="h-11 px-2" variant="outline" disabled={protectedLead} onClick={() => { void copyLeadPhone(lead); }}><Clipboard className="h-4 w-4" />复制</Button>
                      <Button className="h-11 px-2" onClick={() => openEdit(lead)}>{protectedLead ? <ShieldAlert className="h-4 w-4" /> : <MessageSquarePlus className="h-4 w-4" />}{protectedLead ? '查看保护' : '记录跟进'}</Button>
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild><Button className="h-11 w-11 p-0" variant="outline" aria-label={`更多线索操作：${lead.business_name}`}><MoreHorizontal className="h-5 w-5" /></Button></DropdownMenuTrigger>
                        <DropdownMenuContent align="end" className="w-56">
                          {canManage && <DropdownMenuItem className="min-h-11" onSelect={() => openEdit(lead)}><Edit3 className="mr-2 h-4 w-4" />编辑线索资料</DropdownMenuItem>}
                          {!lead.converted_customer_id && !protectedLead && <DropdownMenuItem className="min-h-11" onSelect={() => { void openDealControl(lead); }}><ClipboardCheck className="mr-2 h-4 w-4" />成交审核</DropdownMenuItem>}
                          {lead.converted_customer_id && <DropdownMenuItem className="min-h-11" onSelect={() => window.location.assign(`/customers?detail=${lead.converted_customer_id}&tab=info`)}><CheckCircle2 className="mr-2 h-4 w-4" />查看正式客户</DropdownMenuItem>}
                          <DropdownMenuItem className="min-h-11" onSelect={() => openEdit(lead)}><ShieldAlert className="mr-2 h-4 w-4" />{canManage ? '保护与黑名单设置' : '禁止联系设置'}</DropdownMenuItem>
                        </DropdownMenuContent>
                      </DropdownMenu>
                    </div>
                  </article>
                );
              })}
          </div>
          {!isMobile && <div data-testid="sales-leads-desktop-table" className="overflow-x-auto">
            <table className="w-full min-w-[1080px] text-left text-sm">
              <thead className="border-b bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                <tr>{canManage && <th className="w-12 px-4 py-3"><input type="checkbox" aria-label="选择当前页全部线索" checked={items.length > 0 && items.every(item => selectedLeadIds.includes(item.id))} onChange={event => setSelectedLeadIds(event.target.checked ? items.map(item => item.id) : [])} /></th>}<th className="px-4 py-3">商家</th><th className="px-4 py-3">电话</th><th className="px-4 py-3">地区/行业</th><th className="px-4 py-3">负责人</th><th className="px-4 py-3">状态</th><th className="px-4 py-3">下次跟进</th><th className="px-4 py-3 text-right">操作</th></tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {loading ? <tr><td colSpan={canManage ? 8 : 7} className="py-12 text-center text-slate-400">正在加载线索...</td></tr>
                : items.length === 0 ? <tr><td colSpan={canManage ? 8 : 7} className="py-12 text-center text-slate-400">当前范围暂无销售线索</td></tr>
                : items.map(lead => {
                  const protectedLead = lead.is_blacklisted || lead.do_not_contact;
                  return (
                    <tr key={lead.id} className={protectedLead ? 'bg-rose-50/40' : 'hover:bg-slate-50/70'}>
                      {canManage && <td className="px-4 py-3"><input type="checkbox" aria-label={`选择 ${lead.business_name}`} checked={selectedLeadIds.includes(lead.id)} onChange={event => setSelectedLeadIds(current => event.target.checked ? [...current, lead.id] : current.filter(id => id !== lead.id))} /></td>}
                      <td className="px-4 py-3"><p className="font-semibold text-slate-900">{lead.business_name}</p><p className="text-xs text-slate-500">{lead.contact_name || '未填写联系人'} · #{lead.id}</p></td>
                      <td className="px-4 py-3"><div className={`flex items-center gap-2 font-medium ${protectedLead ? 'text-slate-400 line-through' : 'text-blue-700'}`}><Phone className="h-3.5 w-3.5" />{lead.phone}</div>{protectedLead && <p className="mt-1 text-xs text-rose-600">禁止拨打</p>}</td>
                      <td className="px-4 py-3 text-slate-600"><p>{[lead.city, lead.state, lead.country].filter(Boolean).join(', ') || '-'}</p><p className="text-xs text-slate-400">{lead.industry || '未分类'}</p></td>
                      <td className="px-4 py-3">{lead.assigned_sales_name || <span className="text-amber-600">待分配</span>}</td>
                      <td className="px-4 py-3"><div className="flex flex-wrap gap-1"><Badge className={statusColors[lead.status] || statusColors.new}>{statusLabels[lead.status] || lead.status}</Badge>{lead.do_not_contact && <Badge className="bg-rose-100 text-rose-700">禁止再联系</Badge>}{lead.is_blacklisted && <Badge className="bg-slate-800 text-white">黑名单</Badge>}</div></td>
                      <td className="px-4 py-3 text-slate-600">{formatDate(lead.next_follow_up_at)}</td>
                      <td className="px-4 py-3"><div className="flex justify-end gap-1.5"><Button size="sm" variant="outline" onClick={() => openEdit(lead)}><Edit3 className="mr-1 h-3.5 w-3.5" />{canManage ? '编辑' : '跟进'}</Button>{!lead.converted_customer_id && !protectedLead && <Button size="sm" variant="outline" className="border-emerald-200 text-emerald-700" onClick={() => void openDealControl(lead)}><ClipboardCheck className="mr-1 h-3.5 w-3.5" />成交审核</Button>}{lead.converted_customer_id && <Button size="sm" variant="outline" className="text-emerald-700" onClick={() => window.location.assign(`/customers?detail=${lead.converted_customer_id}&tab=info`)}>正式客户</Button>}<Button size="sm" variant="outline" className={lead.do_not_contact ? 'text-emerald-700' : 'text-rose-700'} onClick={() => updateProtection(lead, 'do_not_contact', !lead.do_not_contact)}>{lead.do_not_contact ? '解除禁联' : '禁止联系'}</Button>{canManage && <Button size="sm" variant="outline" onClick={() => updateProtection(lead, 'is_blacklisted', !lead.is_blacklisted)}>{lead.is_blacklisted ? '移出黑名单' : '黑名单'}</Button>}</div></td>
                    </tr>
                  );
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

      <Dialog open={showForm} onOpenChange={setShowForm}>
        <DialogContent className="!h-[100dvh] !max-h-[100dvh] !w-screen !max-w-none rounded-none pb-0 sm:!h-auto sm:!max-h-[90vh] sm:!w-full sm:!max-w-4xl sm:rounded-lg sm:pb-6">
          <DialogHeader><DialogTitle>{editing ? (canManage ? '编辑销售线索' : '记录跟进结果') : '新增销售线索'}</DialogTitle></DialogHeader>
          <div className="grid gap-4 sm:grid-cols-2">
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
            <div><Label>下次跟进</Label><Input type="datetime-local" value={form.next_follow_up_at} onChange={event => setForm({ ...form, next_follow_up_at: event.target.value })} /></div>
            <div className="sm:col-span-2"><Label>当前跟进摘要</Label><Textarea rows={3} value={form.notes} onChange={event => setForm({ ...form, notes: event.target.value })} placeholder="这里显示最近一次摘要；完整沟通过程请使用下方跟进时间线" /></div>
            {editing && <div className="sm:col-span-2 rounded-xl border border-blue-100 bg-blue-50/40 p-4">
              <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between"><div className="flex items-center gap-2"><History className="h-5 w-5 text-blue-600" /><div><p className="font-semibold text-slate-900">持续跟进时间线</p><p className="text-xs text-slate-500">每次保存都会新增一条记录，不会覆盖之前的沟通内容。</p></div></div><Badge className="w-fit bg-white text-blue-700">共 {callHistory.length} 条</Badge></div>
              {!editing.is_blacklisted && !editing.do_not_contact && <div className="mt-4 grid gap-3 rounded-lg border border-blue-100 bg-white p-3 sm:grid-cols-2">
                <div><Label>本次跟进结果</Label><NativeSelect value={followUpForm.outcome} onChange={value => setFollowUpForm(current => ({ ...current, outcome: value }))} options={followUpOutcomeOptions} /></div>
                <div><Label>下次跟进时间</Label><Input type="datetime-local" value={followUpForm.next_follow_up_at} onChange={event => setFollowUpForm(current => ({ ...current, next_follow_up_at: event.target.value }))} disabled={['not_interested', 'do_not_contact'].includes(followUpForm.outcome)} /></div>
                <div className="sm:col-span-2"><Label>本次沟通内容 *</Label><Textarea rows={3} value={followUpForm.notes} onChange={event => setFollowUpForm(current => ({ ...current, notes: event.target.value }))} placeholder="记录客户反馈、需求、异议、已发送资料和下一步安排" /></div>
                <div className="sm:col-span-2 flex justify-end"><Button type="button" disabled={followUpSaving || editing.status === 'new'} onClick={() => void recordFollowUp()}><MessageSquarePlus className="mr-1.5 h-4 w-4" />{followUpSaving ? '记录中...' : '新增跟进记录'}</Button></div>
                {editing.status === 'new' && <p className="sm:col-span-2 text-xs text-amber-700">首次拨打请先在“每日拨打工作台”完成，之后即可在这里持续追加跟进。</p>}
              </div>}
              <div className="relative mt-4 space-y-0 pl-5 before:absolute before:bottom-2 before:left-[7px] before:top-2 before:w-px before:bg-blue-200">
                {historyLoading ? <p className="py-5 text-sm text-slate-500">正在加载跟进记录...</p> : callHistory.length === 0 ? <p className="py-5 text-sm text-slate-500">暂无历史跟进。首次联系完成后，记录会按时间显示在这里。</p> : callHistory.map(item => <div key={item.id} className="relative pb-4"><span className="absolute -left-5 top-1 h-3.5 w-3.5 rounded-full border-2 border-white bg-blue-500 shadow" /><div className="rounded-lg border border-slate-200 bg-white p-3"><div className="flex flex-wrap items-center justify-between gap-2"><Badge className={item.outcome === 'interested' || item.outcome === 'appointment' ? 'bg-emerald-100 text-emerald-700' : item.outcome === 'callback' ? 'bg-amber-100 text-amber-700' : 'bg-slate-100 text-slate-700'}>{item.outcome_label}</Badge><span className="flex items-center gap-1 text-xs text-slate-500"><Clock3 className="h-3.5 w-3.5" />{formatDate(item.called_at)}</span></div><p className="mt-2 whitespace-pre-line text-sm text-slate-700">{item.notes || '未填写沟通内容'}</p><p className="mt-2 text-xs text-slate-500">记录人：{item.sales_employee_name || '-'} · 下次跟进：{formatDate(item.next_follow_up_at)}</p></div></div>)}
              </div>
            </div>}
            <div className="sm:col-span-2 rounded-xl border border-rose-100 bg-rose-50/60 p-4">
              <div className="flex flex-wrap gap-5">
                <label className="flex items-center gap-2 text-sm font-medium text-rose-800"><input type="checkbox" checked={form.do_not_contact} onChange={event => setForm({ ...form, do_not_contact: event.target.checked })} />禁止再联系</label>
                {canManage && <label className="flex items-center gap-2 text-sm font-medium text-slate-800"><input type="checkbox" checked={form.is_blacklisted} onChange={event => setForm({ ...form, is_blacklisted: event.target.checked })} />加入黑名单</label>}
              </div>
              {form.do_not_contact && <Input className="mt-3 bg-white" value={form.do_not_contact_reason} onChange={event => setForm({ ...form, do_not_contact_reason: event.target.value })} placeholder="必填：禁止再联系原因" />}
            </div>
          </div>
          <div className="sticky bottom-0 -mx-4 mt-4 flex gap-2 border-t bg-white/95 px-4 py-3 pb-[calc(.75rem+env(safe-area-inset-bottom))] backdrop-blur sm:static sm:mx-0 sm:justify-end sm:border-0 sm:bg-transparent sm:px-0 sm:py-0 sm:pb-0"><Button className="h-11 flex-1 sm:flex-none" variant="outline" onClick={() => setShowForm(false)}>取消</Button><Button className="h-11 flex-1 sm:flex-none" disabled={saving} onClick={handleSave}>{saving ? '保存中...' : '保存'}</Button></div>
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

      <Dialog open={!!dealLead} onOpenChange={open => { if (!open) { setDealLead(null); setDealReadiness(null); } }}>
        <DialogContent className="!h-[100dvh] !max-h-[100dvh] !w-screen !max-w-none rounded-none pb-0 sm:!h-auto sm:!max-h-[90vh] sm:!w-full sm:!max-w-4xl sm:rounded-lg sm:pb-6">
          <DialogHeader><DialogTitle>成交审核 · {dealLead?.business_name}</DialogTitle></DialogHeader>
          <p className="-mt-2 text-sm text-slate-500">报价审批、运营交接和收款确认完成前，线索不会进入正式客户管理、成交或财务数据。</p>
          {dealLoading ? <div className="py-16 text-center text-sm text-slate-500">正在加载成交审核资料...</div> : <div className="space-y-5">
            <div className="rounded-xl border border-amber-200 bg-amber-50 p-4"><div className="flex items-start gap-2"><FileText className="mt-0.5 h-4 w-4 text-amber-700" /><div><p className="font-semibold text-amber-900">当前待完成项</p><div className="mt-2 flex flex-wrap gap-2">{(dealReadiness?.blockers || []).map(item => <Badge key={item} className="bg-white text-amber-800 ring-1 ring-amber-200">{item}</Badge>)}{dealReadiness && dealReadiness.blockers.length === 0 && <Badge className="bg-emerald-100 text-emerald-800">审核完成，可转入正式客户</Badge>}</div></div></div></div>

            <section className="rounded-xl border border-slate-200 p-4"><div className="mb-4 flex items-center gap-2"><FileText className="h-5 w-5 text-blue-600" /><div><p className="font-semibold text-slate-900">1. 报价审批单</p><p className="text-xs text-slate-500">销售提交报价；销售主管或系统管理员审批。历史报价会保留，不会覆盖。</p></div></div>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                <div><Label>业务线 *</Label><NativeSelect value={quoteForm.business_line_id} onChange={value => setQuoteForm(current => ({ ...current, business_line_id: value, product_id: '', product_plan_id: '', package_name: '', selected_platforms: '' }))} options={[{ value: '', label: '请选择业务线' }, ...businessLines.map(item => ({ value: String(item.id), label: item.name }))]} /></div>
                <div><Label>具体产品 *</Label><NativeSelect value={quoteForm.product_id} onChange={value => { const product = products.find(item => String(item.id) === value); setQuoteForm(current => ({ ...current, product_id: value, product_plan_id: '', package_name: product?.name || '', currency: product?.default_currency || current.currency, selected_platforms: '' })); }} options={[{ value: '', label: '请选择具体产品' }, ...quoteProducts.map(item => ({ value: String(item.id), label: item.name }))]} /></div>
                <div><Label>套餐 / 版本</Label><NativeSelect value={quoteForm.product_plan_id} onChange={value => { const plan = productPlans.find(item => String(item.id) === value); setQuoteForm(current => ({ ...current, product_plan_id: value, package_name: plan?.name || current.package_name, currency: plan?.default_currency || current.currency, billing_cycle: plan?.default_billing_cycle || current.billing_cycle, list_amount: plan?.standard_price == null ? current.list_amount : String(plan.standard_price), selected_platforms: '' })); }} options={[{ value: '', label: quotePlans.length ? '请选择套餐版本' : '当前产品暂无套餐版本' }, ...quotePlans.map(item => ({ value: String(item.id), label: `${item.name}${item.standard_price == null ? ' · 待定价' : ` · ${item.default_currency} ${item.standard_price}`}` }))]} /></div>
                <div><Label>收费周期 *</Label><NativeSelect value={quoteForm.billing_cycle} onChange={value => setQuoteForm({ ...quoteForm, billing_cycle: value, billing_mode: value === 'one_time' ? 'manual' : quoteForm.billing_mode })} options={billingCycleOptions} /></div>
                <div><Label>收款方式</Label><NativeSelect value={quoteForm.billing_mode} onChange={value => setQuoteForm({ ...quoteForm, billing_mode: value })} options={[{ value: 'manual', label: '人工收款 / 支票 / 转账' }, { value: 'subscription', label: '自动订阅扣款' }]} /></div>
                <div><Label>支付渠道</Label><NativeSelect value={quoteForm.payment_method} onChange={value => setQuoteForm({ ...quoteForm, payment_method: value })} options={[{ value: 'stripe', label: 'Stripe' }, { value: 'check', label: '支票' }, { value: 'zelle', label: 'Zelle' }, { value: 'bank_transfer', label: '银行转账' }, { value: 'other', label: '其他' }]} /></div>
                <div className="sm:col-span-2 lg:col-span-3"><div className="flex items-center justify-between"><Label>实际运营平台 / 服务范围</Label>{selectedQuotePlan?.platform_limit && <span className="text-xs text-slate-500">最多 {selectedQuotePlan.platform_limit} 项，已选 {selectedPlatforms.length}</span>}</div><div className="mt-2 flex flex-wrap gap-2">{platformOptions.map(platform => { const checked = selectedPlatforms.includes(platform); const limitReached = !!selectedQuotePlan?.platform_limit && selectedPlatforms.length >= selectedQuotePlan.platform_limit && !checked; return <label key={platform} className={`flex cursor-pointer items-center gap-2 rounded-lg border px-3 py-2 text-sm ${checked ? 'border-blue-300 bg-blue-50 text-blue-700' : 'border-slate-200 bg-white text-slate-600'} ${limitReached ? 'cursor-not-allowed opacity-50' : ''}`}><input type="checkbox" checked={checked} disabled={limitReached} onChange={() => { const next = checked ? selectedPlatforms.filter(item => item !== platform) : [...selectedPlatforms, platform]; setQuoteForm({ ...quoteForm, selected_platforms: next.join(', ') }); }} />{platform}</label>; })}</div><Input className="mt-2" value={quoteForm.selected_platforms} onChange={event => setQuoteForm({ ...quoteForm, selected_platforms: event.target.value })} placeholder="可补充其他平台或服务范围，用逗号分隔" /></div>
                <div><Label>原报价 *</Label><Input type="number" min="0" value={quoteForm.list_amount} onChange={event => setQuoteForm({ ...quoteForm, list_amount: event.target.value })} /></div><div><Label>优惠金额</Label><Input type="number" min="0" value={quoteForm.discount_amount} onChange={event => setQuoteForm({ ...quoteForm, discount_amount: event.target.value })} /></div><div><Label>币种</Label><NativeSelect value={quoteForm.currency} onChange={value => setQuoteForm({ ...quoteForm, currency: value })} options={[{ value: 'USD', label: 'USD 美元' }, { value: 'CNY', label: 'CNY 人民币' }]} /></div>
                <div><Label>服务开始</Label><Input type="date" value={quoteForm.service_start_date} onChange={event => setQuoteForm({ ...quoteForm, service_start_date: event.target.value })} /></div><div><Label>服务结束</Label><Input type="date" value={quoteForm.service_end_date} onChange={event => setQuoteForm({ ...quoteForm, service_end_date: event.target.value })} /></div><div className="flex items-end"><Button className="w-full" disabled={dealSaving} onClick={() => void submitQuote()}>提交报价审批</Button></div>
                <div className="sm:col-span-2 lg:col-span-3"><Label>特殊条款 / 折扣原因</Label><Textarea rows={2} value={quoteForm.special_terms} onChange={event => setQuoteForm({ ...quoteForm, special_terms: event.target.value })} placeholder="例如：客户需求、折扣依据、交付范围" /></div>
              </div>
              <div className="mt-4 space-y-2">{(dealReadiness?.quotes || []).map(quote => <div key={quote.id} className={`flex flex-col gap-2 rounded-lg border p-3 sm:flex-row sm:items-center sm:justify-between ${quote.status === 'superseded' ? 'bg-slate-100 opacity-70' : 'bg-slate-50'}`}><div><p className="font-medium text-slate-900">{quote.package_name} · {quote.currency} {quote.final_amount.toFixed(2)}</p><p className="text-xs text-slate-500">{quote.selected_platforms.join('、') || '未指定平台'} · {billingCycleOptions.find(item => item.value === quote.billing_cycle)?.label || quote.billing_cycle} · {quote.billing_mode === 'subscription' ? '自动扣款' : '人工收款'} · {quote.payment_method}</p>{!quote.business_line_id && <p className="mt-1 text-xs text-amber-700">历史报价：尚未关联业务线与产品，后续新报价将自动归类</p>}{quote.review_notes && <p className="mt-1 text-xs text-slate-600">审批备注：{quote.review_notes}</p>}</div><div className="flex items-center gap-2"><Badge className={quote.status === 'approved' ? 'bg-emerald-100 text-emerald-700' : quote.status === 'rejected' ? 'bg-rose-100 text-rose-700' : quote.status === 'superseded' ? 'bg-slate-200 text-slate-600' : 'bg-amber-100 text-amber-800'}>{quote.status === 'approved' ? '当前生效' : quote.status === 'rejected' ? '已驳回' : quote.status === 'superseded' ? '历史失效' : '待审批'}</Badge>{canManage && quote.status === 'submitted' && <><Button size="sm" variant="outline" className="border-emerald-200 text-emerald-700" disabled={dealSaving} onClick={() => void reviewQuote(quote, 'approved')}>批准</Button><Button size="sm" variant="outline" className="border-rose-200 text-rose-700" disabled={dealSaving} onClick={() => void reviewQuote(quote, 'rejected')}>驳回</Button></>}</div></div>)}{!(dealReadiness?.quotes || []).length && <p className="py-3 text-center text-sm text-slate-400">尚未提交报价</p>}</div>
            </section>

            <section className="rounded-xl border border-slate-200 p-4"><div className="mb-4 flex items-center gap-2"><ClipboardCheck className="h-5 w-5 text-violet-600" /><div><p className="font-semibold text-slate-900">2. 成交交接清单</p><p className="text-xs text-slate-500">成交前把客户目标、对接人和运营安排写清楚，避免销售与运营信息断层。</p></div></div><div className="grid gap-3 sm:grid-cols-2"><div><Label>关联当前生效报价</Label><NativeSelect value={handoffForm.quote_id} onChange={value => setHandoffForm({ ...handoffForm, quote_id: value })} options={[{ value: '', label: '请选择已批准报价' }, ...(dealReadiness?.quotes || []).filter(quote => quote.status === 'approved').map(quote => ({ value: String(quote.id), label: `${quote.package_name} · ${quote.currency} ${quote.final_amount}` }))]} /></div><div><Label>运营对接负责人 *</Label><NativeSelect value={handoffForm.operations_owner_employee_id} onChange={value => { const owner = dealEmployees.find(item => String(item.id) === value); setHandoffForm({ ...handoffForm, operations_owner_employee_id: value, operations_owner: owner?.name || '' }); }} options={[{ value: '', label: '请选择在职员工' }, ...dealEmployees.map(item => ({ value: String(item.id), label: `${item.name} · ${item.department || item.position || item.role}` }))]} /></div><div className="sm:col-span-2"><Label>协作人（可多选）</Label><div className="mt-2 flex flex-wrap gap-2">{dealEmployees.filter(item => String(item.id) !== handoffForm.operations_owner_employee_id).map(item => { const checked = handoffForm.collaborator_employee_ids.includes(item.id); return <label key={item.id} className={`flex cursor-pointer items-center gap-2 rounded-lg border px-3 py-2 text-sm ${checked ? 'border-violet-300 bg-violet-50 text-violet-700' : 'border-slate-200 bg-white text-slate-600'}`}><input type="checkbox" checked={checked} onChange={() => setHandoffForm({ ...handoffForm, collaborator_employee_ids: checked ? handoffForm.collaborator_employee_ids.filter(id => id !== item.id) : [...handoffForm.collaborator_employee_ids, item.id] })} />{item.name}<span className="text-xs opacity-70">{item.department || item.role}</span></label>; })}</div></div><div className="sm:col-span-2"><Label>客户目标 *</Label><Textarea rows={2} value={handoffForm.customer_goal} onChange={event => setHandoffForm({ ...handoffForm, customer_goal: event.target.value })} placeholder="例如：提升本地搜索曝光、预约量或内容更新频率" /></div><div className="sm:col-span-2"><Label>关键联系人 / 对接方式 *</Label><Textarea rows={2} value={handoffForm.key_contacts} onChange={event => setHandoffForm({ ...handoffForm, key_contacts: event.target.value })} placeholder="联系人姓名、电话、邮箱、谁负责提供素材或权限" /></div><div><Label>服务开始</Label><Input type="date" value={handoffForm.service_start_date} onChange={event => setHandoffForm({ ...handoffForm, service_start_date: event.target.value })} /></div><div><Label>服务结束</Label><Input type="date" value={handoffForm.service_end_date} onChange={event => setHandoffForm({ ...handoffForm, service_end_date: event.target.value })} /></div><div className="sm:col-span-2"><Label>特殊承诺 / 注意事项</Label><Textarea rows={2} value={handoffForm.special_commitments} onChange={event => setHandoffForm({ ...handoffForm, special_commitments: event.target.value })} /></div><div className="sm:col-span-2"><Label>交接备注</Label><Textarea rows={2} value={handoffForm.handoff_notes} onChange={event => setHandoffForm({ ...handoffForm, handoff_notes: event.target.value })} /></div></div><div className="mt-4 flex flex-wrap gap-5 rounded-lg bg-slate-50 p-3"><label className="flex items-center gap-2 text-sm font-medium text-slate-700"><input type="checkbox" checked={handoffForm.operations_group_created} onChange={event => setHandoffForm({ ...handoffForm, operations_group_created: event.target.checked })} />已建立运营对接群 *</label><label className="flex items-center gap-2 text-sm font-medium text-slate-700"><input type="checkbox" checked={handoffForm.generate_service_board} onChange={event => setHandoffForm({ ...handoffForm, generate_service_board: event.target.checked })} />转入后生成服务看板</label></div><div className="mt-4"><Button disabled={dealSaving} onClick={() => void saveHandoff()}>保存成交交接清单</Button></div></section>

            {canManage && <section className="rounded-xl border border-cyan-200 bg-cyan-50/40 p-4"><div className="mb-4 flex items-center gap-2"><CheckCircle2 className="h-5 w-5 text-cyan-700" /><div><p className="font-semibold text-slate-900">3. 收款确认</p><p className="text-xs text-slate-500">订金不会被当成全额收入；只有“已全额支付”后才允许转入正式客户。</p></div></div><div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4"><div><Label>收款状态</Label><NativeSelect value={paymentForm.payment_status} onChange={value => setPaymentForm({ ...paymentForm, payment_status: value })} options={[{ value: 'pending', label: '待收款' }, { value: 'deposit_paid', label: '已收订金' }, { value: 'paid', label: '已全额支付' }, { value: 'failed', label: '支付失败' }, { value: 'refunded', label: '已退款' }]} /></div><div><Label>实收金额</Label><Input type="number" min="0" value={paymentForm.amount_received} onChange={event => setPaymentForm({ ...paymentForm, amount_received: event.target.value })} placeholder="全额支付可留空自动带入" /></div><div><Label>实际收款日期</Label><Input type="date" value={paymentForm.payment_date} onChange={event => setPaymentForm({ ...paymentForm, payment_date: event.target.value })} /></div><div><Label>交易号 / 支票号</Label><Input value={paymentForm.payment_reference} onChange={event => setPaymentForm({ ...paymentForm, payment_reference: event.target.value })} /></div></div><div className="mt-4 flex flex-wrap items-center justify-between gap-3"><div className="text-xs text-slate-500">{dealReadiness?.handoff?.payment_confirmed_by_name ? `最近确认：${dealReadiness.handoff.payment_confirmed_by_name}` : '尚未由主管确认收款状态'}</div><Button disabled={dealSaving || !dealReadiness?.handoff} onClick={() => void savePaymentStatus()}>保存收款状态</Button></div></section>}

            {canManage && <div className="sticky bottom-0 -mx-4 flex justify-end border-t bg-white/95 px-4 py-3 pb-[calc(.75rem+env(safe-area-inset-bottom))] backdrop-blur sm:static sm:mx-0 sm:bg-transparent sm:px-0 sm:pb-0 sm:pt-4"><Button disabled={dealSaving || !!dealReadiness?.blockers?.length || convertingId === dealLead?.id} className="h-11 w-full bg-emerald-600 hover:bg-emerald-700 sm:w-auto" onClick={() => void convertToCustomer()}><CheckCircle2 className="mr-2 h-4 w-4" />{convertingId === dealLead?.id ? '转入中...' : dealReadiness?.blockers?.length ? '请先完成审核项' : '确认合作并转入正式客户'}</Button></div>}
          </div>}
        </DialogContent>
      </Dialog>
    </div>
  );
}
