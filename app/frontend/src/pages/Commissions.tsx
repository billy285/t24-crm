import './financial-workspaces-polish.css';
import CompactFinanceTable from '@/components/CompactFinanceTable';
import './crm-org-compact.css';
import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useRole } from '@/lib/role-context';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { CrmFormDialogBody, CrmFormDialogContent, CrmFormDialogFooter, CrmFormDialogHeader, Dialog, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { NativeSelect } from '@/components/ui/native-select';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import './commissions.css';
import { useUnsavedChanges } from '@/lib/use-unsaved-changes';
import PageLoadState from '@/components/PageLoadState';
import { Textarea } from '@/components/ui/textarea';
import { invokeWithAuth } from '@/lib/tokenStore';
import { ArrowLeft, ArrowRight, ChevronDown, SlidersHorizontal, AlertTriangle, BadgeDollarSign, Building2, HandCoins, RefreshCw, ShieldCheck, Sparkles } from 'lucide-react';
import { toast } from 'sonner';
import { useIsMobile } from '@/hooks/use-mobile';
import { groupCommissionSettlements } from '@/lib/commission-presentation';

type Partner = { id: number; partner_code: string; name: string; partner_type: string; employee_id?: number; status: string; joined_at: string; stopped_at?: string; notes?: string; login_account?: { id: number; name: string; email?: string; status: string } | null };
type Agreement = { calculation_version?: string; renewal_policy?: string; id: number; partner_id: number; version: number; business_line_id?: number; product_id?: number; first_order_rate: number; renewal_rate: number; activity_decay: Record<string, number>; refund_guard_days: number; effective_from: string; effective_to?: string; status: string };
type Attribution = { commission_mode?: string; commission_start_date?: string; first_service_start?: string; history_basis?: string; id: number; customer_id: number; customer_name?: string; engagement_id?: number; partner_id: number; partner_name?: string; effective_from: string; effective_to?: string; is_active: boolean; source_note?: string };
type Entry = { calculation_version?: string; commission_mode?: string; service_period_start?: string; service_period_end?: string; first_service_start?: string; allocation_basis?: string; id: number; partner_id?: number; partner_code?: string; partner_name?: string; customer_id: number; customer_name?: string; payment_id: number; refund_id?: number; entry_type: string; status: string; service_month: string; occurred_at: string; currency: string; gross_receipt_amount: number; eligible_service_amount: number; contract_rate: number; inactivity_months: number; activity_multiplier: number; commission_amount: number; payout_reference?: string };
type QualityIssue = { key: string; type: string; severity: string; title: string; description: string; customer_id?: number; customer_name?: string; engagement_id?: number; payment_id?: number; partner_id?: number; partner_name?: string };
type QualitySummary = { issue_count: number; high_count: number; covered_count: number; examined_count: number; coverage_rate: number };
type DashboardData = { summary: { partner_count: number; active_partner_count: number; pending_count: number; currencies: Record<string, Record<string, number>>; accounting_rule: string; quality?: QualitySummary }; quality_issues: QualityIssue[]; partners: Partner[]; agreements: Agreement[]; attributions: Attribution[]; entries: Entry[] };
type OptionsData = { employees: Array<{ id: number; name: string; employee_code?: string; role: string }>; customers: Array<{ id: number; name: string; code?: string }>; business_lines: Array<{ id: number; name: string; code: string }>; products: Array<{ id: number; name: string; business_line_id: number }>; engagements: Array<{ id: number; customer_id: number; package_name?: string; status: string }> };
type BulkAttributionItem = { customer_id: number; customer_code?: string; customer_name: string; engagement_id?: number; engagement_name?: string; effective_from: string; partner_id?: number; partner_name?: string; partner_type?: string; status: 'ready' | 'manual_review'; basis: string; issue_keys: string[] };
type BulkAttributionPreview = { preview_token: string; source_issue_count: number; target_count: number; ready_count: number; employee_count: number; direct_count: number; manual_review_count: number; items: BulkAttributionItem[] };

const partnerTypeLabels: Record<string, string> = { agency: '代理商', partner: '销售合伙人', employee: '内部销售', direct: '公司直营' };
const partnerStatusLabels: Record<string, string> = { active: '合作中', suspended: '暂停结算', terminated: '已终止', settled: '已结清' };
const entryTypeLabels: Record<string, string> = { first_order: '首期佣金', renewal: '续费佣金', refund_reversal: '退款冲回' };
const commissionModeLabels: Record<string, string> = { first_month_then_renewal: '首服务月＋续费', renewal_only: '仅续费', none: '不计佣', legacy: '历史首笔规则' };
const isLegacy = (version?: string) => version !== 'service_month_v2';
const ruleLabel = (row: { calculation_version?: string; renewal_policy?: string }) => isLegacy(row.calculation_version) ? '历史首笔规则' : `首服务月计佣 · ${row.renewal_policy === 'activity_decay' ? '续费活跃衰减' : '续费固定比例'}`;
const periodLabel = (row: { service_period_start?: string; service_period_end?: string }) => row.service_period_start && row.service_period_end ? `${row.service_period_start} 至 ${row.service_period_end}（不含结束日）` : row.service_period_start ? `${row.service_period_start} · 按到账日期归类` : '服务周期待核对';
const entryStatusLabels: Record<string, string> = { pending_confirmation: '待确认', confirmed: '已确认入账', payable: '待发放', paid: '已发放', reversed: '已作废' };
const today = () => new Intl.DateTimeFormat('en-CA', {
  timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit',
}).format(new Date());
const percent = (value: number) => `${Number((Number(value || 0) * 100).toFixed(6))}%`;
const money = (value: number, currency: string) => `${currency === 'CNY' ? '¥' : '$'}${Number(value || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const errorMessage = (error: any) => error?.data?.detail || error?.response?.data?.detail || error?.message || '操作失败';

// Desktop summary contracts retain every original field in the full detail drawer.
const commissionLedger = {
  label: "佣金台账",
  columns: [
    {"label": "月份 / 客户", "indexes": [0], "width": 2.5, "summaryMode": "first"},
    {"label": "类型", "indexes": [1], "width": 1, "priority": 2},
    {"label": "计佣基数", "indexes": [2], "width": 1.15, "align": "right", "summaryMode": "first", "priority": 2},
    {"label": "佣金", "indexes": [4], "width": 1.15, "align": "right"},
    {"label": "状态", "indexes": [5], "width": 1.1}
  ],
  expectedHeaders: ["月份 / 对象", "类型", "计佣基数", "适用比例", "佣金", "状态", "操作"],
  actionIndexes: [6],
} as const;

const commissionSettlements = {
  label: "渠道月度结算",
  columns: [
    {"label": "渠道", "indexes": [0], "width": 1.8},
    {"label": "币种", "indexes": [1], "width": 0.6},
    {"label": "待确认", "indexes": [3], "width": 1.1, "align": "right", "priority": 2},
    {"label": "已确认费用", "indexes": [4], "width": 1.15, "align": "right"},
    {"label": "待发放", "indexes": [5], "width": 1.1, "align": "right"},
    {"label": "已发放", "indexes": [6], "width": 1.1, "align": "right", "priority": 2}
  ],
  expectedHeaders: ["渠道", "币种", "记录", "待确认", "已确认费用", "待发放", "已发放", "退款冲回"],
  actionIndexes: [],
} as const;

const commissionAttributions = {
  label: "客户归属",
  columns: [
    {"label": "客户", "indexes": [0], "width": 2},
    {"label": "归属渠道", "indexes": [1], "width": 1.5},
    {"label": "项目", "indexes": [2], "width": 1.2, "priority": 2},
    {"label": "生效期间", "indexes": [3], "width": 1.8, "priority": 2},
    {"label": "状态", "indexes": [4], "width": 1}
  ],
  expectedHeaders: ["客户", "归属渠道", "项目", "生效期间", "计佣方式", "操作"],
  actionIndexes: [5],
} as const;

export default function Commissions() {
  const navigate = useNavigate();
  const { isAdmin, employee } = useRole();
  const isMobile = useIsMobile();
  const [data, setData] = useState<DashboardData | null>(null);
  const [options, setOptions] = useState<OptionsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);
  const [month, setMonth] = useState('');
  const [loadError, setLoadError] = useState<string | null>(null);
  const loadSequence = useRef(0);
  const optionsSequence = useRef(0);
  const loginOptionsSequence = useRef(0);
  const [optionsLoading, setOptionsLoading] = useState(false);
  const [optionsError, setOptionsError] = useState<string | null>(null);
  const [loginOptionsLoading, setLoginOptionsLoading] = useState(false);
  const actorKey = String(employee?.id ?? 'guest');
  const actorRef = useRef(actorKey);
  actorRef.current = actorKey;
  const [mobileView, setMobileView] = useState('ledger');
  const [entryStatus, setEntryStatus] = useState('all');
  const [visibleLimit, setVisibleLimit] = useState(20);
  const [ledgerPage, setLedgerPage] = useState(1);
  const [transitionTarget, setTransitionTarget] = useState<{entry: Entry; status: string; reason: string; reference: string} | null>(null);
  const [partnerTransition, setPartnerTransition] = useState<{partner: Partner; status: string; reason: string; date: string} | null>(null);
  const [search, setSearch] = useState('');
  const [activeTab, setActiveTab] = useState('ledger');
  const [showFilters, setShowFilters] = useState(false);
  const managementLabels: Record<string, string> = { partners: '渠道与协议', attributions: '客户归属', quality: '待办事项', rules: '计算规则' };
  const isManagementView = Boolean(managementLabels[activeTab]);
  const [customerSearch, setCustomerSearch] = useState('');
  const [dialog, setDialog] = useState<'partner' | 'agreement' | 'attribution' | 'bulkAttribution' | 'login' | null>(null);
  const [loginOptions, setLoginOptions] = useState<Array<{ id: number; name: string; email?: string; employee_code?: string }>>([]);
  const [loginOptionsError, setLoginOptionsError] = useState(false);
  const [loginTarget, setLoginTarget] = useState<Partner | null>(null);
  const [loginEmployeeId, setLoginEmployeeId] = useState('');
  const [attributionPreview, setAttributionPreview] = useState<{ signature: string; blocked: boolean; conflicts: Array<{ entry_id: number; payment_id: number; status: string }>; affected_pending_count: number; legacy_count: number; message: string } | null>(null);
  const [paymentPreview, setPaymentPreview] = useState<{ issue: QualityIssue; data: { currency?: string; payment_id: number; partner_id?: number; attribution_id?: number; eligible_service_amount: number; issues: string[]; segments: Array<{ entry_type: string; service_period_start?: string; service_period_end?: string; allocated_service_amount: number; contract_rate: number; commission_amount: number }> } } | null>(null);
  const [bulkPreview, setBulkPreview] = useState<BulkAttributionPreview | null>(null);
  const [partnerForm, setPartnerForm] = useState({ partner_code: '', name: '', partner_type: 'partner', employee_id: '', joined_at: today(), contact_name: '', contact_phone: '', contact_email: '', notes: '' });
  const [agreementForm, setAgreementForm] = useState({ partner_id: '', business_line_id: 'all', product_id: 'all', first_order_rate: '50', renewal_rate: '20', refund_guard_days: '30', effective_from: today(), notes: '' });
  const [attributionForm, setAttributionForm] = useState({ customer_id: '', partner_id: '', engagement_id: 'all', effective_from: today(), commission_mode: 'first_month_then_renewal', commission_start_date: today(), first_service_start: '', history_basis: '', source_note: '' });

  const draftBaseline = useRef<{key: string; value: string}>({key: '', value: ''});
  const draftKey = dialog || (transitionTarget ? `entry-${transitionTarget.entry.id}` : partnerTransition ? `partner-${partnerTransition.partner.id}` : '');
  const draftValue = JSON.stringify(dialog === 'partner' ? partnerForm : dialog === 'agreement' ? agreementForm : dialog === 'attribution' ? attributionForm : dialog === 'login' ? loginEmployeeId : transitionTarget || partnerTransition);
  useEffect(() => { draftBaseline.current = {key: draftKey, value: draftValue}; }, [draftKey]);
  const { confirmDiscard } = useUnsavedChanges(Boolean(draftKey && draftBaseline.current.key === draftKey && draftBaseline.current.value !== draftValue));
  const closeDialog = () => { if (!working && confirmDiscard()) { setDialog(null); setTransitionTarget(null); setPartnerTransition(null); setAttributionPreview(null); setPaymentPreview(null); } };
  useEffect(() => { setVisibleLimit(20); setLedgerPage(1); }, [search, month, entryStatus, mobileView]);
  const loadOptions = async () => {
    const sequence = ++optionsSequence.current;
    if (isMobile) { setOptions(null); setOptionsLoading(false); setOptionsError(null); return; }
    setOptionsLoading(true); setOptionsError(null); setOptions(null);
    try {
      const response = await invokeWithAuth({ url: '/api/v1/commissions/options', method: 'GET' });
      if (sequence === optionsSequence.current && actorRef.current === actorKey) setOptions(response.data);
    } catch (error) {
      if (sequence === optionsSequence.current && actorRef.current === actorKey) setOptionsError(errorMessage(error));
    } finally {
      if (sequence === optionsSequence.current && actorRef.current === actorKey) setOptionsLoading(false);
    }
  };
  const loadLoginOptions = async () => {
    const sequence = ++loginOptionsSequence.current;
    if (isMobile) { setLoginOptions([]); setLoginOptionsLoading(false); setLoginOptionsError(false); return; }
    setLoginOptionsLoading(true); setLoginOptionsError(false); setLoginOptions([]);
    try {
      const response = await invokeWithAuth({ url: '/api/v1/commissions/partner-login-options', method: 'GET' });
      if (sequence === loginOptionsSequence.current && actorRef.current === actorKey) setLoginOptions(response.data?.items || []);
    } catch {
      if (sequence === loginOptionsSequence.current && actorRef.current === actorKey) setLoginOptionsError(true);
    } finally {
      if (sequence === loginOptionsSequence.current && actorRef.current === actorKey) setLoginOptionsLoading(false);
    }
  };
  const loadAuxiliaryOptions = () => { void loadOptions(); void loadLoginOptions(); };
  const load = async (refreshOptions = true) => {
    const sequence = ++loadSequence.current;
    setLoading(true);
    if (refreshOptions) loadAuxiliaryOptions();
    try {
      const dashboardResponse = await invokeWithAuth({ url: `/api/v1/commissions/dashboard${month ? `?month=${month}` : ''}`, method: 'GET' });
      if (sequence !== loadSequence.current || actorRef.current !== actorKey) return;
      setData(dashboardResponse.data); setLoadError(null);
    } catch (error) { if (sequence === loadSequence.current && actorRef.current === actorKey) setLoadError(errorMessage(error)); }
    finally { if (sequence === loadSequence.current && actorRef.current === actorKey) setLoading(false); }
  };

  useEffect(() => { void load(false); return () => { loadSequence.current += 1; }; }, [isMobile, month, actorKey]);
  useEffect(() => {
    setData(null); setOptions(null); setLoginOptions([]); setLoadError(null);
    loadAuxiliaryOptions();
    return () => { optionsSequence.current += 1; loginOptionsSequence.current += 1; };
  }, [isMobile, actorKey]);
  const formOptionsUnavailable = optionsLoading || Boolean(optionsError) || !options;
  const optionsNotice = !isMobile && (optionsLoading || optionsError) ? <div className="commission-option-notice" role={optionsError ? 'alert' : 'status'}><span>{optionsLoading ? '正在读取录入选项，台账可继续查看。' : `录入选项暂不可用：${optionsError}。涉及这些选项的表单暂不能保存。`}</span>{optionsError && <Button size="sm" variant="outline" disabled={optionsLoading} onClick={() => void loadOptions()}>重试录入选项</Button>}</div> : null;
  const loginOptionsNotice = !isMobile && (loginOptionsLoading || loginOptionsError) ? <div className="commission-option-notice" role={loginOptionsError ? 'alert' : 'status'}><span>{loginOptionsLoading ? '正在读取可绑定账号…' : '账号选项读取失败，台账和其他录入不受影响。'}</span>{loginOptionsError && <Button size="sm" variant="outline" disabled={loginOptionsLoading} onClick={() => void loadLoginOptions()}>重试账号选项</Button>}</div> : null;

  const filteredEntries = useMemo(() => (data?.entries || []).filter(item => `${item.partner_name || ''} ${item.customer_name || ''} ${item.payment_id}`.toLowerCase().includes(search.toLowerCase())), [data?.entries, search]);
  const visibleEntries = filteredEntries.filter(entry => entryStatus === 'all' || entry.status === entryStatus);
  const ledgerPages = Math.max(1, Math.ceil(visibleEntries.length / 20));
  const safeLedgerPage = Math.min(ledgerPage, ledgerPages);
  const pagedEntries = visibleEntries.slice((safeLedgerPage - 1) * 20, safeLedgerPage * 20);
  const filteredAttributions = useMemo(() => (data?.attributions || []).filter(item => `${item.partner_name || ''} ${item.customer_name || ''}`.toLowerCase().includes(search.toLowerCase())), [data?.attributions, search]);
  const settlements = useMemo(() => groupCommissionSettlements(filteredEntries.map(entry => ({
    ...entry, partner_code: data?.partners.find(partner => partner.id === entry.partner_id)?.partner_code,
  }))), [filteredEntries, data?.partners]);
  const selectedLineId = agreementForm.business_line_id === 'all' ? undefined : Number(agreementForm.business_line_id);
  const agreementProducts = (options?.products || []).filter(product => !selectedLineId || product.business_line_id === selectedLineId);
  const selectedCustomerId = Number(attributionForm.customer_id || 0);
  const customerEngagements = (options?.engagements || []).filter(item => item.customer_id === selectedCustomerId);
  const customerOptions = (options?.customers || []).filter(item => `${item.code || ''} ${item.name}`.toLowerCase().includes(customerSearch.toLowerCase())).slice(0, 80);

  const configureAttribution = (item: Attribution) => {
    setCustomerSearch(item.customer_name || '');
    setAttributionForm({ customer_id: String(item.customer_id), partner_id: String(item.partner_id), engagement_id: item.engagement_id ? String(item.engagement_id) : 'all', effective_from: today(), commission_mode: item.commission_mode && item.commission_mode !== 'legacy' ? item.commission_mode : 'first_month_then_renewal', commission_start_date: today(), first_service_start: item.first_service_start || '', history_basis: item.history_basis || '', source_note: item.source_note || '' });
    setAttributionPreview(null); setDialog('attribution');
  };
  const openLogin = (partner: Partner) => {
    setLoginTarget(partner); setLoginEmployeeId(''); setDialog('login');
  };
  const attributionIsDirect = data?.partners.find(partner => partner.id === Number(attributionForm.partner_id))?.partner_type === 'direct';
  const attributionRequiresHistory = attributionForm.commission_mode === 'renewal_only';
  const attributionReady = Boolean(attributionForm.customer_id && attributionForm.partner_id && attributionForm.effective_from
    && attributionForm.commission_start_date && attributionForm.commission_start_date >= attributionForm.effective_from
    && (attributionIsDirect || (attributionForm.commission_mode !== 'first_month_then_renewal' || attributionForm.first_service_start)
      && (!attributionRequiresHistory || attributionForm.history_basis.trim())));
  const attributionPayload = {
    ...attributionForm, commission_mode: attributionIsDirect ? 'none' : attributionForm.commission_mode,
    first_service_start: attributionForm.first_service_start || null, history_basis: attributionForm.history_basis.trim() || null,
    customer_id: Number(attributionForm.customer_id), partner_id: Number(attributionForm.partner_id),
    engagement_id: attributionForm.engagement_id === 'all' ? null : Number(attributionForm.engagement_id),
  };
  const attributionSignature = JSON.stringify(attributionPayload);
  const currentAttributionPreview = attributionPreview?.signature === attributionSignature ? attributionPreview : null;
  const previewAttribution = async () => {
    if (!attributionReady || working || loading || loadError || isMobile) return;
    setWorking(true); setAttributionPreview(null);
    try {
      const response = await invokeWithAuth({ url: '/api/v1/commissions/attributions/preview', method: 'POST', data: attributionPayload });
      setAttributionPreview({ ...response.data, signature: attributionSignature });
    } catch (error) { toast.error(errorMessage(error)); }
    finally { setWorking(false); }
  };
  const submit = async () => {
    if (isMobile || loading || loadError || working) return;
    if (dialog === 'attribution' && (!attributionReady || !currentAttributionPreview || currentAttributionPreview.blocked)) return;
    setWorking(true);
    try {
      if (dialog === 'partner') {
        await invokeWithAuth({ url: '/api/v1/commissions/partners', method: 'POST', data: { ...partnerForm, employee_id: partnerForm.employee_id ? Number(partnerForm.employee_id) : null } });
      } else if (dialog === 'agreement') {
        await invokeWithAuth({ url: '/api/v1/commissions/agreements', method: 'POST', data: {
          ...agreementForm,
          partner_id: Number(agreementForm.partner_id), business_line_id: agreementForm.business_line_id === 'all' ? null : Number(agreementForm.business_line_id),
          product_id: agreementForm.product_id === 'all' ? null : Number(agreementForm.product_id),
          first_order_rate: Number(agreementForm.first_order_rate) / 100, renewal_rate: Number(agreementForm.renewal_rate) / 100,
          refund_guard_days: Number(agreementForm.refund_guard_days),
          activity_decay: { 0: 1, 6: 1 }, renewal_policy: 'fixed',
        } });
      } else if (dialog === 'attribution') {
        await invokeWithAuth({ url: '/api/v1/commissions/attributions', method: 'POST', data: attributionPayload });
      } else if (dialog === 'login' && loginTarget && loginEmployeeId) {
        await invokeWithAuth({ url: `/api/v1/commissions/partners/${loginTarget.id}/login-account`, method: 'POST', data: { employee_id: Number(loginEmployeeId) } });
      }
      toast.success('已保存；历史协议和已确认佣金快照未被改写');
      setDialog(null);
      await load();
    } catch (error) { toast.error(errorMessage(error)); }
    finally { setWorking(false); }
  };

  const scan = async () => {
    if (isMobile || loading || loadError || working) return;
    setWorking(true);
    try {
      const response = await invokeWithAuth({ url: '/api/v1/commissions/scan', method: 'POST' });
      toast.success(`扫描完成，新生成 ${response.data.entries_created} 条佣金记录`);
      await load();
    } catch (error) { toast.error(errorMessage(error)); }
    finally { setWorking(false); }
  };

  const previewBulkAttribution = async () => {
    setWorking(true);
    try {
      const response = await invokeWithAuth({ url: '/api/v1/commissions/attributions/bulk-preview', method: 'GET' });
      setBulkPreview(response.data);
      setDialog('bulkAttribution');
    } catch (error) { toast.error(errorMessage(error)); }
    finally { setWorking(false); }
  };

  const applyBulkAttribution = async () => {
    if (isMobile || loading || loadError || working || !bulkPreview?.ready_count) return;
    setWorking(true);
    try {
      const response = await invokeWithAuth({
        url: '/api/v1/commissions/attributions/bulk-apply',
        method: 'POST',
        data: { preview_token: bulkPreview.preview_token },
      });
      toast.success(`已补齐 ${response.data.assigned_count} 项归属；新生成 ${response.data.entries_created} 条待确认佣金`);
      setDialog(null);
      setBulkPreview(null);
      await load();
    } catch (error) { toast.error(errorMessage(error)); }
    finally { setWorking(false); }
  };

  const transition = (entry: Entry, to_status: string) => {
    if (isMobile || loading || loadError) return;
    setTransitionTarget({entry, status: to_status, reason: '', reference: ''});
  };
  const confirmTransition = async () => {
    if (!transitionTarget || working || loading || loadError || isMobile) return;
    const {entry, status, reason, reference} = transitionTarget;
    if (status === 'reversed' && !reason.trim()) return toast.error('请填写作废原因');
    if (status === 'paid' && !reference.trim()) return toast.error('请填写付款流水号或凭证编号');
    setWorking(true);
    try {
      await invokeWithAuth({ url: `/api/v1/commissions/entries/${entry.id}/transition`, method: 'POST', data: { to_status: status, reason: reason || null, payout_reference: reference || null } });
      toast.success('佣金状态已更新'); setTransitionTarget(null); await load();
    } catch (error) { toast.error(errorMessage(error)); }
    finally { setWorking(false); }
  };
  const changePartnerStatus = (partner: Partner, next: string) => {
    if (isMobile || loading || loadError) return;
    setPartnerTransition({partner, status: next, reason: '', date: today()});
  };
  const confirmPartnerTransition = async () => {
    if (!partnerTransition || working || loading || loadError || isMobile) return;
    if (!partnerTransition.reason.trim() || !partnerTransition.date) return toast.error('请填写原因和生效日期');
    setWorking(true);
    try {
      await invokeWithAuth({ url: `/api/v1/commissions/partners/${partnerTransition.partner.id}/status`, method: 'POST', data: { status: partnerTransition.status, effective_date: partnerTransition.date, reason: partnerTransition.reason } });
      toast.success('渠道状态已更新，历史已确认佣金保持不变'); setPartnerTransition(null); await load();
    } catch (error) { toast.error(errorMessage(error)); }
    finally { setWorking(false); }
  };

  const resolveIssue = async (issue: QualityIssue) => {
    if (issue.type === 'commission_rule_review' && issue.payment_id) {
      if (working || loading || loadError || isMobile) return;
      setWorking(true);
      try { const response = await invokeWithAuth({ url: `/api/v1/commissions/payments/${issue.payment_id}/preview`, method: 'GET' }); setPaymentPreview({ issue, data: response.data }); }
      catch (error) { toast.error(errorMessage(error)); }
      finally { setWorking(false); }
      return;
    }
    if (issue.partner_id && ['partner_without_agreement', 'payment_without_agreement'].includes(issue.type)) {
      setAgreementForm(value => ({ ...value, partner_id: String(issue.partner_id) }));
      setDialog('agreement');
      return;
    }
    if (issue.customer_id) {
      setCustomerSearch(issue.customer_name || String(issue.customer_id));
      setAttributionForm(value => ({
        ...value,
        customer_id: String(issue.customer_id), partner_id: issue.partner_id ? String(issue.partner_id) : '', first_service_start: '', history_basis: '',
        engagement_id: issue.engagement_id ? String(issue.engagement_id) : 'all',
      }));
      setDialog('attribution');
    }
  };

  const exportSettlements = () => {
    const rows = [
      ['月份', '渠道编号', '渠道', '币种', '记录数', '待确认', '已确认费用', '待发放', '已发放', '退款冲回'],
      ...settlements.map(row => [month || '全部', row.partner_code || (row.partner_id ? `#${row.partner_id}` : '身份待核对'), row.partner_name, row.currency, row.entry_count, row.pending, row.confirmed, row.payable, row.paid, row.adjustments]),
    ];
    const csv = `\uFEFF${rows.map(row => row.map(value => `"${String(value).replace(/"/g, '""')}"`).join(',')).join('\n')}`;
    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
    const link = document.createElement('a');
    link.href = url;
    link.download = `渠道结算单_${month || '全部月份'}.csv`;
    link.click();
    URL.revokeObjectURL(url);
  };

  if (loading && !data) return <div className="app-page"><div className="app-loading">正在读取渠道与分润台账...</div></div>;

  return <div className="financial-workspace financial-workspace--commissions crm-org-compact app-page commission-page">
    {loadError && <PageLoadState error={`分润数据读取失败：${loadError}${data ? '，当前保留上次数据，修改暂不可用' : ''}`} onRetry={() => void load()} />}
    {optionsError && optionsNotice}{loginOptionsError && loginOptionsNotice}
    <div className="commission-heading">
      <div><p className="text-xs text-slate-500">渠道合作</p><h1 className="mt-2 text-2xl font-semibold tracking-tight text-slate-900">渠道与分润</h1></div>
      <div className="commission-heading-actions"><Button variant="outline" size="sm" disabled={loading} onClick={() => void load()}><RefreshCw className={loading ? "mr-1 h-4 w-4 animate-spin" : "mr-1 h-4 w-4"} />刷新台账</Button>{!isMobile && <DropdownMenu><DropdownMenuTrigger asChild><Button variant="ghost" className="gap-2 text-slate-600">渠道管理<ChevronDown className="h-4 w-4" /></Button></DropdownMenuTrigger><DropdownMenuContent align="end">
        <DropdownMenuItem onSelect={() => setActiveTab('partners')}>渠道与协议 · {data?.summary.partner_count ?? 0}</DropdownMenuItem>
        <DropdownMenuItem onSelect={() => setActiveTab('attributions')}>客户归属 · {data?.attributions.length ?? 0}</DropdownMenuItem>
        <DropdownMenuItem onSelect={() => setActiveTab('quality')}>待办事项 · {data?.summary.quality?.issue_count ?? 0}</DropdownMenuItem>
        <DropdownMenuItem onSelect={() => setActiveTab('rules')}>计算规则</DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={() => setDialog('partner')}>新增渠道</DropdownMenuItem>
        <DropdownMenuItem onSelect={() => setDialog('agreement')}>新增协议版本</DropdownMenuItem>
        <DropdownMenuItem onSelect={() => setDialog('attribution')}>设置客户归属</DropdownMenuItem>
      </DropdownMenuContent></DropdownMenu>}</div>
    </div>

    {!!data?.summary.quality?.issue_count && !isManagementView && <section className="commission-priority" aria-label="分润待办">
      <p className="text-xs text-amber-700">需要处理</p>
      <h2 className="mt-3 text-xl font-medium text-slate-900">还有 {data.summary.quality.issue_count} 项分润数据待补齐</h2>
      <p className="mt-2 text-sm text-slate-500">先核对客户归属，再处理协议或冲突。</p>
      {!isMobile ? <Button className="mt-6 gap-2" onClick={() => setActiveTab('quality')}>查看待办<ArrowRight className="h-4 w-4" /></Button> : <p className="mt-5 text-xs text-slate-500">请在电脑端处理待办事项。</p>}
    </section>}

    <div className="commission-record-heading">
      <div>{isManagementView ? <div className="flex flex-wrap items-center gap-3"><Button variant="ghost" size="sm" className="gap-1 text-slate-500" onClick={() => setActiveTab('ledger')}><ArrowLeft className="h-4 w-4" />返回台账</Button><h2 className="text-lg font-medium">{managementLabels[activeTab]}</h2></div> : <h2 className="text-lg font-medium text-slate-900">{isMobile ? '结算摘要' : '佣金台账'}</h2>}</div>
      {!isManagementView && !isMobile && <div className="flex gap-5" aria-label="分润记录视图"><Button variant="ghost" aria-pressed={activeTab === 'ledger'} className="commission-view-button" onClick={() => setActiveTab('ledger')}>佣金记录</Button><Button variant="ghost" aria-pressed={activeTab === 'settlements'} className="commission-view-button" onClick={() => setActiveTab('settlements')}>月度结算</Button></div>}
    </div>
    <div className="commission-toolbar">
      <p className="text-sm text-slate-500">{activeTab === 'partners' ? <>合作中 <span className="ml-2 font-medium text-slate-900">{data?.summary.active_partner_count ?? 0} 个</span></> : activeTab === 'quality' || activeTab === 'attributions' ? <>归属覆盖率 <span className="ml-2 font-medium text-slate-900">{data?.summary.quality?.coverage_rate ?? '—'}%</span></> : <>待确认佣金 <span className="ml-2 font-medium text-slate-900">{data?.summary.pending_count ?? 0} 笔</span></>}</p>
      <div className="flex flex-wrap gap-2">
        {['ledger', 'settlements', 'attributions'].includes(activeTab) && <Button variant="ghost" size="sm" aria-expanded={showFilters} aria-controls="commission-filters" onClick={() => setShowFilters(v => !v)} className="gap-2 text-slate-500"><SlidersHorizontal className="h-4 w-4" />{search || month ? '筛选已启用' : '筛选'}</Button>}
        {!isMobile && ['ledger', 'settlements'].includes(activeTab) && <Button variant="ghost" size="sm" onClick={scan} disabled={working} className="gap-2 text-slate-600"><RefreshCw className={`h-4 w-4 ${working ? 'animate-spin' : ''}`} />扫描实收与退款</Button>}
        {!isMobile && activeTab === 'partners' && <><Button variant="outline" size="sm" onClick={() => setDialog('agreement')}>新增协议版本</Button><Button size="sm" onClick={() => setDialog('partner')}>新增渠道</Button></>}
        {!isMobile && activeTab === 'attributions' && <Button size="sm" onClick={() => setDialog('attribution')}>设置归属</Button>}
        {!isMobile && activeTab === 'quality' && <Button size="sm" onClick={previewBulkAttribution} disabled={working}><Sparkles className="mr-2 h-4 w-4" />批量补齐预览</Button>}
      </div>
    </div>
    {(['ledger', 'settlements', 'attributions'].includes(activeTab) && (showFilters || activeTab === 'settlements')) && <div id="commission-filters" className="commission-filters">
      <Input aria-label="搜索渠道、客户或收款编号" className="w-full md:max-w-sm" placeholder="搜索渠道、客户或收款编号" value={search} onChange={event => setSearch(event.target.value)} />
      <Input aria-label="结算月份" type="month" className="w-full md:w-44" value={month} onChange={event => setMonth(event.target.value)} />
      {(month || search) && <Button variant="ghost" onClick={() => { setMonth(''); setSearch(''); }}>清除筛选</Button>}
    </div>}

    {isMobile && <section className="mobile-commission-records" aria-label="手机分润明细">
      <p className="text-sm text-slate-500">手机只读查看，确认与发放沿用电脑端权限流程。</p>
      <div className="commission-mobile-tabs">{[['ledger', '佣金台账'], ['settlements', '月度结算']].map(([value, label]) => <button type="button" key={value} aria-pressed={mobileView === value} onClick={() => setMobileView(value)}>{label}</button>)}</div>
      <Input aria-label="搜索手机分润" placeholder="搜索渠道、客户或收款编号" value={search} onChange={event => setSearch(event.target.value)} />
      <Input aria-label="手机分润月份" type="month" value={month} onChange={event => setMonth(event.target.value)} />
      {mobileView === 'ledger' && <NativeSelect value={entryStatus} onChange={setEntryStatus} options={[{value:'all', label:'全部状态'}, ...Object.entries(entryStatusLabels).map(([value, label]) => ({value, label}))]} />}
      {(month || search || entryStatus !== 'all') && <Button variant="ghost" onClick={() => { setMonth(''); setSearch(''); setEntryStatus('all'); }}>清除筛选</Button>}
      {mobileView === 'ledger' ? visibleEntries.slice(0, visibleLimit).map(entry => <details key={entry.id} className="commission-mobile-card"><summary><div><strong>{entry.customer_name || `客户 #${entry.customer_id}`}</strong><p>{entry.partner_name} · {entry.service_month}</p></div><strong>{money(entry.commission_amount, entry.currency)} {entry.currency}</strong><Badge variant="outline">{entryStatusLabels[entry.status] || entry.status}</Badge></summary><dl><div><dt>规则版本</dt><dd>{isLegacy(entry.calculation_version) ? '历史快照' : '首服务月规则'}</dd></div><div><dt>付款日期</dt><dd>{entry.occurred_at?.slice(0, 10) || '待核对'}</dd></div>{!isLegacy(entry.calculation_version) && <div><dt>服务段</dt><dd>{periodLabel(entry)}</dd></div>}<div><dt>收款编号</dt><dd>#{entry.payment_id}</dd></div><div><dt>类型</dt><dd>{entryTypeLabels[entry.entry_type] || entry.entry_type}</dd></div><div><dt>计佣基数</dt><dd>{money(entry.eligible_service_amount, entry.currency)} {entry.currency}</dd></div><div><dt>适用比例</dt><dd>{isLegacy(entry.calculation_version) ? `${percent(entry.contract_rate)} × ${percent(entry.activity_multiplier)}` : percent(entry.contract_rate)}</dd></div>{isLegacy(entry.calculation_version) ? <div><dt>无新客月份</dt><dd>{entry.inactivity_months}</dd></div> : <div><dt>比例规则</dt><dd>{entry.entry_type === 'first_order' ? '首服务月比例' : entry.entry_type === 'renewal' ? '固定续费比例' : '沿用原佣金比例'}</dd></div>}<div><dt>原始实收</dt><dd>{money(entry.gross_receipt_amount, entry.currency)} {entry.currency}</dd></div><div><dt>退款编号</dt><dd>{entry.refund_id ? `#${entry.refund_id}` : '—'}</dd></div><div><dt>发放凭证</dt><dd>{entry.payout_reference || '未登记'}</dd></div></dl></details>) : settlements.slice(0, visibleLimit).map(row => <Card key={row.key}><CardContent className="p-4"><div className="flex items-center justify-between"><strong>{row.partner_name}<small className="ml-2 font-normal text-slate-500">{row.partner_code || (row.partner_id ? `#${row.partner_id}` : '身份待核对')}</small></strong><Badge variant="outline">{row.currency} · {row.entry_count} 条</Badge></div><dl className="commission-mobile-amounts">{[['待确认', row.pending], ['已确认费用', row.confirmed], ['待发放', row.payable], ['已发放', row.paid], ['退款冲回', row.adjustments]].map(([label, amount]) => <div key={String(label)}><dt>{label}</dt><dd>{money(Number(amount), row.currency)}</dd></div>)}</dl></CardContent></Card>)}
      {(mobileView === 'ledger' ? visibleEntries.length : settlements.length) === 0 && <div className="app-empty">当前筛选范围暂无记录</div>}
      <p className="text-sm text-slate-500" role="status">已显示 {Math.min(visibleLimit, mobileView === 'ledger' ? visibleEntries.length : settlements.length)} / 共 {mobileView === 'ledger' ? visibleEntries.length : settlements.length} 条</p>
      {visibleLimit < (mobileView === 'ledger' ? visibleEntries.length : settlements.length) && <Button variant="outline" onClick={() => setVisibleLimit(value => value + 20)}>加载更多分润</Button>}
    </section>}

    {!isMobile && <>
    <div>

      <section hidden={activeTab !== 'ledger'} aria-label="佣金记录">{activeTab === 'ledger' && <><div className="commission-status-filter mb-3"><NativeSelect value={entryStatus} onChange={setEntryStatus} options={[{value:'all', label:'全部状态'}, ...Object.entries(entryStatusLabels).map(([value, label]) => ({value, label}))]} /></div><Card><CardHeader><CardTitle className="flex items-center gap-2 text-base"><BadgeDollarSign className="h-5 w-5 text-blue-600" />佣金记录</CardTitle><details className="mt-2 text-sm text-slate-500"><summary className="cursor-pointer">查看计佣条件</summary><p className="mt-3">归属、有效协议、计佣起点与真实服务周期共同确定佣金。新规则按首服务月区分首期与续费；已付首期请设为仅续费。历史已确认记录保留原快照，计佣不改公司收入月份。</p></details></CardHeader><CardContent className="overflow-x-auto p-0">{visibleEntries.length > 0 ? <CompactFinanceTable {...commissionLedger} legacyClassName="w-full min-w-[1080px] text-sm"><thead className="bg-slate-50 text-left text-xs text-slate-500"><tr><th className="px-4 py-3">月份 / 对象</th><th>类型</th><th>计佣基数</th><th>适用比例</th><th>佣金</th><th>状态</th><th className="px-4">操作</th></tr></thead><tbody>{pagedEntries.map(entry => <tr key={entry.id} className="border-t"><td className="px-4 py-3"><p className="font-medium">{entry.service_month} · {entry.customer_name || `客户 #${entry.customer_id}`}</p><p className="text-xs text-slate-400">{entry.partner_name} · 收款 #{entry.payment_id}{entry.refund_id ? ` · 退款 #${entry.refund_id}` : ''}</p><p className="text-xs text-slate-500">付款 {entry.occurred_at?.slice(0, 10) || '待核对'}</p>{!isLegacy(entry.calculation_version) && <p className="text-xs text-slate-500">服务段 {periodLabel(entry)}</p>}</td><td><Badge variant="outline">{entryTypeLabels[entry.entry_type] || entry.entry_type}</Badge><p className="mt-1 text-xs text-slate-500">{isLegacy(entry.calculation_version) ? '历史快照' : '首服务月规则'}</p></td><td>{money(entry.eligible_service_amount, entry.currency)}<p className="text-xs text-slate-400">实收 {money(entry.gross_receipt_amount, entry.currency)}</p></td><td>{isLegacy(entry.calculation_version) ? `${percent(entry.contract_rate)} × ${percent(entry.activity_multiplier)}` : percent(entry.contract_rate)}<p className="text-xs text-slate-400">{isLegacy(entry.calculation_version) ? `${entry.inactivity_months} 月无新客 · 历史倍率` : entry.entry_type === 'first_order' ? '首服务月比例' : entry.entry_type === 'renewal' ? '固定续费比例' : '沿用原佣金比例'}</p></td><td className={entry.commission_amount < 0 ? 'font-semibold text-red-600' : 'font-semibold text-blue-700'}>{money(entry.commission_amount, entry.currency)}</td><td><Badge className={entry.status === 'paid' ? 'bg-emerald-100 text-emerald-700' : entry.status === 'pending_confirmation' ? 'bg-amber-100 text-amber-700' : 'bg-blue-100 text-blue-700'}>{entryStatusLabels[entry.status] || entry.status}</Badge></td><td className="px-4"><div className="flex gap-1">{entry.status === 'pending_confirmation' && (isLegacy(entry.calculation_version) ? <Button size="sm" variant="outline" onClick={() => void resolveIssue({ key: `entry-${entry.id}`, type: 'commission_rule_review', severity: 'high', title: '历史规则待核对', description: '', payment_id: entry.payment_id, partner_id: entry.partner_id, customer_id: entry.customer_id, customer_name: entry.customer_name })}>核对计佣</Button> : <Button size="sm" variant="outline" onClick={() => transition(entry, 'confirmed')}>确认</Button>)}{entry.status === 'confirmed' && <Button size="sm" variant="outline" onClick={() => transition(entry, 'payable')}>转应付</Button>}{entry.status === 'payable' && <Button size="sm" onClick={() => transition(entry, 'paid')}>已发放</Button>}{['pending_confirmation', 'confirmed'].includes(entry.status) && <Button size="sm" variant="ghost" className="text-red-600" onClick={() => transition(entry, 'reversed')}>作废</Button>}</div></td></tr>)}{filteredEntries.length === 0 && <tr><td colSpan={7} className="py-12 text-center text-slate-400"><p>当前没有符合计佣条件的记录。</p><p className="mt-1 text-xs">请确认归属生效日期、有效协议和生效日后的已确认服务实收，再执行“扫描实收与退款”。</p></td></tr>}</tbody></CompactFinanceTable> : <div className="commission-empty"><BadgeDollarSign className="mx-auto h-6 w-6 text-slate-400" /><p className="mt-5 font-medium text-slate-700">{search || month ? '没有匹配的佣金记录' : '暂无佣金记录'}</p><p className="mt-2 text-sm text-slate-500">{search || month ? '可以调整筛选条件后再查看。' : '扫描实收后，符合计佣条件的记录会显示在这里。'}</p></div>}</CardContent></Card></>}</section>
      {activeTab === 'ledger' && visibleEntries.length > 20 && <div className="flex items-center justify-end gap-3 py-3"><span>{safeLedgerPage} / {ledgerPages} 页 · {visibleEntries.length} 条</span><Button variant="outline" disabled={safeLedgerPage <= 1} onClick={() => setLedgerPage(value => value - 1)}>上一页</Button><Button variant="outline" disabled={safeLedgerPage >= ledgerPages} onClick={() => setLedgerPage(value => value + 1)}>下一页</Button></div>}
      <section hidden={activeTab !== 'settlements'} aria-label="月度结算">{activeTab === 'settlements' && <><Card><CardHeader><div className="flex flex-wrap items-center justify-between gap-2"><div><CardTitle className="text-base">渠道月度结算单</CardTitle><p className="mt-1 text-xs text-slate-500">使用上方月份筛选生成结算口径；待确认不进入费用，已确认、待发放和已发放不会重复计费。</p></div><Button variant="outline" onClick={exportSettlements} disabled={!settlements.length}>导出结算 CSV</Button></div></CardHeader><CardContent className="overflow-x-auto p-0"><CompactFinanceTable {...commissionSettlements} legacyClassName="w-full min-w-[900px] text-sm"><thead className="bg-slate-50 text-left text-xs text-slate-500"><tr><th className="px-4 py-3">渠道</th><th>币种</th><th>记录</th><th>待确认</th><th>已确认费用</th><th>待发放</th><th>已发放</th><th>退款冲回</th></tr></thead><tbody>{settlements.map(row => <tr key={row.key} className="border-t"><td className="px-4 py-3 font-medium">{row.partner_name}<p className="text-xs font-normal text-slate-500">{row.partner_code || (row.partner_id ? `#${row.partner_id}` : '身份待核对')}</p></td><td>{row.currency}</td><td>{row.entry_count}</td><td className="text-amber-700">{money(row.pending, row.currency)}</td><td className="font-semibold text-blue-700">{money(row.confirmed, row.currency)}</td><td>{money(row.payable, row.currency)}</td><td className="text-emerald-700">{money(row.paid, row.currency)}</td><td className={row.adjustments < 0 ? 'text-red-600' : ''}>{money(row.adjustments, row.currency)}</td></tr>)}{!settlements.length && <tr><td colSpan={8} className="py-12 text-center text-slate-400">当前月份暂无可结算佣金</td></tr>}</tbody></CompactFinanceTable></CardContent></Card></>}</section>
      <section hidden={activeTab !== 'partners'} aria-label="渠道与协议">{activeTab === 'partners' && <><div className="grid gap-4 lg:grid-cols-2">{(data?.partners || []).map(partner => { const rules = (data?.agreements || []).filter(item => item.partner_id === partner.id); return <Card key={partner.id}><CardHeader className="pb-3"><div className="flex items-start justify-between"><div><CardTitle className="text-base">{partner.name}</CardTitle><p className="text-xs text-slate-400">{partner.partner_code} · {partnerTypeLabels[partner.partner_type]}</p></div><Badge>{partnerStatusLabels[partner.status]}</Badge></div></CardHeader><CardContent>{['agency', 'partner'].includes(partner.partner_type) && <div className="commission-login-row"><div><span className={partner.employee_id ? 'text-emerald-700' : 'text-amber-700'}>{partner.employee_id ? '登录账号已绑定' : '尚未开通渠道查看'}</span><p>{partner.login_account ? `${partner.login_account.name} · ${partner.login_account.email || `账号 #${partner.login_account.id}`} · ${partner.login_account.status === 'active' || partner.login_account.status === 'probation' ? '有效' : '已停用'}` : partner.employee_id ? `账号 #${partner.employee_id}` : '合作档案与登录账号需要明确绑定'}</p></div>{!partner.employee_id && <Button size="sm" variant="outline" onClick={() => openLogin(partner)}>开通登录</Button>}</div>}<div className="space-y-2">{rules.map(rule => <div key={rule.id} className="rounded-lg border bg-slate-50 p-3 text-sm"><div className="flex justify-between"><span>协议 V{rule.version}</span><Badge variant="outline">{rule.status === 'active' ? '当前生效' : '历史版本'}</Badge></div><p className="mt-1 text-xs text-slate-500">{ruleLabel(rule)}</p><p className="mt-1 text-slate-600">{isLegacy(rule.calculation_version) ? '首笔' : '首服务月'} {percent(rule.first_order_rate)} · 续费 {percent(rule.renewal_rate)} · 观察期 {rule.refund_guard_days} 天</p><p className="text-xs text-slate-400">{rule.effective_from} 至 {rule.effective_to || '长期'}</p></div>)}{rules.length === 0 && <p className={`text-sm ${partner.partner_type === 'direct' ? 'text-emerald-700' : 'text-amber-600'}`}>{partner.partner_type === 'direct' ? '直营归属不产生外部佣金，无需协议' : '尚未配置分润协议'}</p>}</div>{partner.partner_type !== 'direct' && partner.status === 'active' && <div className="mt-4 flex gap-2"><Button size="sm" variant="outline" onClick={() => changePartnerStatus(partner, 'suspended')}>暂停结算</Button><Button size="sm" variant="outline" className="text-red-600" onClick={() => changePartnerStatus(partner, 'terminated')}>停止合作</Button></div>}{partner.partner_type !== 'direct' && partner.status === 'suspended' && <Button className="mt-4" size="sm" onClick={() => changePartnerStatus(partner, 'active')}>恢复合作</Button>}</CardContent></Card>})}{!data?.partners.length && <Card><CardContent className="py-12 text-center text-slate-400">先新增销售合伙人、代理商或内部销售。</CardContent></Card>}</div></>}</section>
      <section hidden={activeTab !== 'attributions'} aria-label="客户归属">{activeTab === 'attributions' && <><Card><CardContent className="overflow-x-auto p-0"><CompactFinanceTable {...commissionAttributions} legacyClassName="w-full text-sm"><thead className="bg-slate-50 text-left text-xs text-slate-500"><tr><th className="px-4 py-3">客户</th><th>归属渠道</th><th>项目</th><th>生效期间</th><th>计佣方式</th><th>操作</th></tr></thead><tbody>{filteredAttributions.map(item => <tr className="border-t" key={item.id}><td className="px-4 py-3 font-medium">{item.customer_name || `客户 #${item.customer_id}`}</td><td>{item.partner_name}</td><td>{item.engagement_id ? `项目 #${item.engagement_id}` : '客户全部项目'}</td><td>{item.effective_from} 至 {item.effective_to || '当前'}</td><td><Badge className={item.is_active ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-100 text-slate-600'}>{item.is_active ? '当前归属' : '历史归属'}</Badge><p className="mt-1 text-xs">{commissionModeLabels[item.commission_mode || 'legacy'] || '规则待核对'}</p><p className="text-xs text-slate-500">{item.commission_start_date ? `计佣起点 ${item.commission_start_date}` : '请明确计佣起点'}</p>{item.first_service_start && <p className="text-xs text-slate-500">首期起始 {item.first_service_start}</p>}</td><td>{item.is_active && <Button size="sm" variant="outline" onClick={() => configureAttribution(item)}>设置规则</Button>}</td></tr>)}</tbody></CompactFinanceTable></CardContent></Card></>}</section>
      <section hidden={activeTab !== 'quality'} aria-label="待办事项">{activeTab === 'quality' && <><div className="space-y-3">{(data?.quality_issues || []).map(issue => <Card key={issue.key} className={issue.severity === 'high' ? 'border-amber-200' : ''}><CardContent className="flex flex-wrap items-center justify-between gap-3 p-4"><div><div className="flex items-center gap-2"><Badge className={issue.severity === 'high' ? 'bg-amber-100 text-amber-800' : 'bg-slate-100 text-slate-700'}>{issue.severity === 'high' ? '高优先级' : '待补齐'}</Badge><p className="font-semibold text-slate-900">{issue.title}</p></div><p className="mt-2 text-sm text-slate-600">{issue.customer_name ? `${issue.customer_name} · ` : ''}{issue.description}</p></div><Button size="sm" variant="outline" onClick={() => resolveIssue(issue)}>{issue.type === 'commission_rule_review' ? '核对计佣' : ['partner_without_agreement', 'payment_without_agreement'].includes(issue.type) ? '补充协议' : '设置归属'}</Button></CardContent></Card>)}{!data?.quality_issues?.length && <Card><CardContent className="py-12 text-center"><ShieldCheck className="mx-auto h-8 w-8 text-emerald-500" /><p className="mt-3 font-semibold text-emerald-800">分润数据检查通过</p><p className="mt-1 text-sm text-slate-500">当前付费项目和服务实收均有归属或适用协议。</p></CardContent></Card>}</div></>}</section>
      <section hidden={activeTab !== 'rules'} aria-label="计算规则">{activeTab === 'rules' && <><div className="grid gap-4 lg:grid-cols-3"><Card><CardContent className="p-5"><HandCoins className="h-6 w-6 text-blue-600" /><h3 className="mt-3 font-semibold">首服务月与续费分开</h3><p className="mt-1 text-sm text-slate-500">新协议按真实服务起始日划分首服务月；一期内分次收款沿用首期比例。服务跨期按覆盖天数拆分。旧协议与已确认快照保留历史规则。</p></CardContent></Card><Card><CardContent className="p-5"><AlertTriangle className="h-6 w-6 text-amber-600" /><h3 className="mt-3 font-semibold">续费方式明确约定</h3><p className="mt-1 text-sm text-slate-500">新协议默认固定续费比例；历史协议的活跃规则仍保留在原台账快照中。已付首期的客户可设置“仅续费”并登记历史依据。</p></CardContent></Card><Card><CardContent className="p-5"><Building2 className="h-6 w-6 text-emerald-600" /><h3 className="mt-3 font-semibold">计佣与公司账目分别核对</h3><p className="mt-1 text-sm text-slate-500">佣金只基于有效服务实收，广告代充值排除。待确认不计费用；已确认、应付、已发放只记一次。停止合作保留历史记录。</p></CardContent></Card></div></>}</section>
    </div>
    {!isManagementView && <details className="commission-accounting"><summary className="cursor-pointer text-sm text-slate-500">财务汇总与记账规则</summary><div className="mt-5 space-y-4">
      {Object.entries(data?.summary.currencies || {}).map(([currency, values]) => <div key={currency} className="flex flex-wrap gap-x-6 gap-y-2 text-sm"><span className="font-medium">{currency}</span><span>已确认 {money(values.confirmed_expense, currency)}</span><span>待发放 {money(values.payable, currency)}</span><span>已发放 {money(values.paid, currency)}</span></div>)}
      <p className="text-sm leading-6 text-slate-500">{data?.summary.accounting_rule}。广告代充值不会参与佣金计算；退款生成独立负数冲回记录。</p>
    </div></details>}


    <Dialog open={Boolean(transitionTarget)} onOpenChange={open => { if (!open) closeDialog(); }}><CrmFormDialogContent className="financial-workspace-form"><CrmFormDialogHeader><DialogTitle>确认佣金状态变更</DialogTitle></CrmFormDialogHeader><CrmFormDialogBody>{transitionTarget && <div className="space-y-3"><p>{transitionTarget.entry.customer_name} · {transitionTarget.entry.partner_name} · {transitionTarget.entry.service_month}</p><p className="text-xl font-semibold">{money(transitionTarget.entry.commission_amount, transitionTarget.entry.currency)} {transitionTarget.entry.currency}</p><p>{entryStatusLabels[transitionTarget.entry.status]} → {entryStatusLabels[transitionTarget.status]}</p>{transitionTarget.status === 'paid' && <div><Label htmlFor="commission-payout">付款流水号或凭证编号 *</Label><Input id="commission-payout" value={transitionTarget.reference} onChange={event => setTransitionTarget({...transitionTarget, reference: event.target.value})} /></div>}{transitionTarget.status === 'reversed' && <div><Label htmlFor="commission-reason">作废原因 *</Label><Textarea id="commission-reason" value={transitionTarget.reason} onChange={event => setTransitionTarget({...transitionTarget, reason: event.target.value})} /></div>}</div>}</CrmFormDialogBody><CrmFormDialogFooter><Button variant="outline" onClick={closeDialog}>取消</Button><Button disabled={working || loading || Boolean(loadError)} onClick={confirmTransition}>确认变更</Button></CrmFormDialogFooter></CrmFormDialogContent></Dialog>
    <Dialog open={Boolean(partnerTransition)} onOpenChange={open => { if (!open) closeDialog(); }}><CrmFormDialogContent className="financial-workspace-form"><CrmFormDialogHeader><DialogTitle>确认渠道状态变更</DialogTitle></CrmFormDialogHeader><CrmFormDialogBody>{partnerTransition && <div className="space-y-3"><p>{partnerTransition.partner.name} · {partnerStatusLabels[partnerTransition.partner.status]} → {partnerStatusLabels[partnerTransition.status]}</p><div><Label htmlFor="partner-status-date">生效日期 *</Label><Input id="partner-status-date" type="date" value={partnerTransition.date} onChange={event => setPartnerTransition({...partnerTransition, date:event.target.value})} /></div><div><Label htmlFor="partner-status-reason">原因 *</Label><Textarea id="partner-status-reason" value={partnerTransition.reason} onChange={event => setPartnerTransition({...partnerTransition, reason:event.target.value})} /></div><p className="text-sm text-slate-500">历史已确认佣金保持不变。</p></div>}</CrmFormDialogBody><CrmFormDialogFooter><Button variant="outline" onClick={closeDialog}>取消</Button><Button disabled={working || loading || Boolean(loadError)} onClick={confirmPartnerTransition}>确认变更</Button></CrmFormDialogFooter></CrmFormDialogContent></Dialog>
    <Dialog open={Boolean(paymentPreview)} onOpenChange={open => { if (!open) closeDialog(); }}><CrmFormDialogContent className="financial-workspace-form"><CrmFormDialogHeader><DialogTitle>核对计佣依据</DialogTitle></CrmFormDialogHeader>{paymentPreview && <><CrmFormDialogBody><div className="space-y-4"><p className="font-medium">{paymentPreview.issue.customer_name} · 收款 #{paymentPreview.data.payment_id}</p>{paymentPreview.data.issues.length > 0 && <ul className="space-y-2 text-sm text-amber-800">{paymentPreview.data.issues.map((issue, index) => <li key={index}>{issue}</li>)}</ul>}{paymentPreview.data.segments.map((segment, index) => <div key={index} className="commission-rule-note"><strong>{entryTypeLabels[segment.entry_type] || segment.entry_type}</strong><p>{periodLabel(segment)}</p><p>计佣基数 {paymentPreview.data.currency} {segment.allocated_service_amount} · 合同比例 {percent(segment.contract_rate)} · 佣金 {paymentPreview.data.currency} {segment.commission_amount}</p></div>)}<p className="text-xs text-slate-500">这是核对预览，不会生成或修改佣金。服务覆盖资料请回到收入管理核对原收款。</p></div></CrmFormDialogBody><CrmFormDialogFooter><Button variant="outline" onClick={() => { const id = paymentPreview.data.partner_id || paymentPreview.issue.partner_id; setPaymentPreview(null); setAgreementForm(value => ({ ...value, partner_id: id ? String(id) : '' })); setDialog('agreement'); }}>协议版本</Button><Button variant="outline" onClick={() => { const current = data?.attributions.find(row => row.id === paymentPreview.data.attribution_id); const issue = paymentPreview.issue; setPaymentPreview(null); if (current) configureAttribution(current); else void resolveIssue({ ...issue, type: 'unattributed_payment' }); }}>客户计佣规则</Button><Button onClick={() => navigate('/finance?tab=income')}>查看收入管理</Button></CrmFormDialogFooter></>}</CrmFormDialogContent></Dialog>
    <Dialog open={dialog === 'login'} onOpenChange={open => { if (!open) closeDialog(); }}><CrmFormDialogContent className="financial-workspace-form"><CrmFormDialogHeader><DialogTitle>绑定渠道登录账号</DialogTitle></CrmFormDialogHeader><CrmFormDialogBody>{loginOptionsNotice}<p className="font-medium">{loginTarget?.name} · {loginTarget?.partner_code}</p><p className="text-sm text-slate-500">绑定后，该账号可查看此渠道归属客户、协议和佣金。不会开放公司财务或其他渠道。</p><Label>选择未绑定的销售合伙人账号</Label><NativeSelect aria-label="渠道登录账号" value={loginEmployeeId} onChange={setLoginEmployeeId} placeholder="选择账号" options={loginOptions.map(item => ({ value: String(item.id), label: `${item.name} · ${item.email || item.employee_code || item.id}` }))} disabled={loginOptionsError || !loginOptions.length} />{(loginOptionsError || !loginOptions.length) && <p role="status" className="text-sm text-amber-700">{loginOptionsError ? '账号列表读取失败，可重试账号选项，或创建专属账号。' : '没有可绑定账号，可为此渠道创建专属登录账号。创建时会绑定现有档案，不另建重复渠道。'}</p>}<p className="text-xs text-slate-500">不会按邮箱自动匹配，也不能在此替换其他渠道的已有绑定。</p></CrmFormDialogBody><CrmFormDialogFooter><Button variant="outline" onClick={closeDialog}>取消</Button>{isAdmin && <Button variant="outline" disabled={working || !loginTarget} onClick={() => { if (confirmDiscard()) navigate(`/employees?create_partner_account=${loginTarget?.id}`); }}>创建专属账号</Button>}<Button disabled={loginOptionsLoading || working || !loginEmployeeId || loginOptionsError || !loginTarget} onClick={submit}>确认绑定</Button></CrmFormDialogFooter></CrmFormDialogContent></Dialog>
    <Dialog open={dialog === 'partner'} onOpenChange={open => { if (!open) closeDialog(); }}><CrmFormDialogContent className="financial-workspace-form"><CrmFormDialogHeader><DialogTitle>新增渠道或销售身份</DialogTitle></CrmFormDialogHeader><CrmFormDialogBody>{optionsNotice}{loginOptionsNotice}<div className="grid gap-3 sm:grid-cols-2"><div><Label>渠道编号 *</Label><Input value={partnerForm.partner_code} onChange={e => setPartnerForm(v => ({ ...v, partner_code: e.target.value }))} placeholder="例如 PARTNER-001" /></div><div><Label>名称 *</Label><Input value={partnerForm.name} onChange={e => setPartnerForm(v => ({ ...v, name: e.target.value }))} /></div><div><Label>身份类型</Label><NativeSelect value={partnerForm.partner_type} onChange={value => setPartnerForm(v => ({ ...v, partner_type: value, employee_id: '' }))} options={Object.entries(partnerTypeLabels).filter(([value]) => value !== 'direct').map(([value, label]) => ({ value, label }))} /></div><div><Label>加入日期</Label><Input type="date" value={partnerForm.joined_at} onChange={e => setPartnerForm(v => ({ ...v, joined_at: e.target.value }))} /></div>{partnerForm.partner_type === 'employee' && <div className="sm:col-span-2"><Label>关联员工 *</Label><NativeSelect value={partnerForm.employee_id} onChange={value => setPartnerForm(v => ({ ...v, employee_id: value }))} placeholder="选择员工" options={(options?.employees || []).map(item => ({ value: String(item.id), label: `${item.name}${item.employee_code ? ` · ${item.employee_code}` : ''}` }))} /></div>}{['agency', 'partner'].includes(partnerForm.partner_type) && <div className="sm:col-span-2"><Label>登录账号</Label><NativeSelect aria-label="新渠道登录账号" value={partnerForm.employee_id} onChange={value => setPartnerForm(v => ({ ...v, employee_id: value }))} options={[{ value: '', label: '暂不绑定，仅建立合作档案' }, ...loginOptions.map(item => ({ value: String(item.id), label: `${item.name} · ${item.email || item.employee_code || item.id}` }))]} /><p className="mt-1 text-xs text-slate-500">{loginOptionsError ? '登录账号列表读取失败，请刷新后重试。' : '只可选未绑定的有效销售合伙人账号；也可保存渠道后点击“开通登录”创建专属账号。'}</p></div>}<div><Label>联系人</Label><Input value={partnerForm.contact_name} onChange={e => setPartnerForm(v => ({ ...v, contact_name: e.target.value }))} /></div><div><Label>联系电话</Label><Input value={partnerForm.contact_phone} onChange={e => setPartnerForm(v => ({ ...v, contact_phone: e.target.value }))} /></div><div className="sm:col-span-2"><Label>邮箱</Label><Input value={partnerForm.contact_email} onChange={e => setPartnerForm(v => ({ ...v, contact_email: e.target.value }))} /></div><div className="sm:col-span-2"><Label>备注</Label><Textarea value={partnerForm.notes} onChange={e => setPartnerForm(v => ({ ...v, notes: e.target.value }))} /></div></div></CrmFormDialogBody><CrmFormDialogFooter><Button variant="outline" onClick={closeDialog}>取消</Button><Button disabled={formOptionsUnavailable || working || !partnerForm.partner_code || !partnerForm.name || (partnerForm.partner_type === 'employee' && !partnerForm.employee_id)} onClick={submit}>保存渠道</Button></CrmFormDialogFooter></CrmFormDialogContent></Dialog>
    <Dialog open={dialog === 'agreement'} onOpenChange={open => { if (!open) closeDialog(); }}><CrmFormDialogContent className="financial-workspace-form"><CrmFormDialogHeader><DialogTitle>新增协议版本</DialogTitle></CrmFormDialogHeader><CrmFormDialogBody>{optionsNotice}<div className="space-y-3"><div><Label>渠道 *</Label><NativeSelect value={agreementForm.partner_id} onChange={value => setAgreementForm(v => ({ ...v, partner_id: value }))} placeholder="选择渠道" options={(data?.partners || []).filter(item => item.partner_type !== 'direct' && !['terminated', 'settled'].includes(item.status)).map(item => ({ value: String(item.id), label: `${item.name} · ${item.partner_code}` }))} /><p className="mt-1 text-xs text-slate-400">这里只显示合作中或暂停结算的非直营渠道。</p></div><div className="grid grid-cols-1 gap-3 sm:grid-cols-2"><div><Label>业务线</Label><NativeSelect value={agreementForm.business_line_id} onChange={value => setAgreementForm(v => ({ ...v, business_line_id: value, product_id: 'all' }))} options={[{ value: 'all', label: '全部业务线' }, ...(options?.business_lines || []).map(item => ({ value: String(item.id), label: item.name }))]} /></div><div><Label>具体产品</Label><NativeSelect value={agreementForm.product_id} onChange={value => setAgreementForm(v => ({ ...v, product_id: value }))} options={[{ value: 'all', label: '该范围全部产品' }, ...agreementProducts.map(item => ({ value: String(item.id), label: item.name }))]} /></div></div><p className="text-xs text-slate-500">比例相同时选择“全部业务线 / 该范围全部产品”；只有某条业务或某个产品比例不同时才缩小范围。</p><div className="grid grid-cols-1 gap-3 sm:grid-cols-3"><div><Label>首服务月比例 %</Label><Input type="number" min="0" max="100" value={agreementForm.first_order_rate} onChange={e => setAgreementForm(v => ({ ...v, first_order_rate: e.target.value }))} /></div><div><Label>续费比例 %</Label><Input type="number" min="0" max="100" value={agreementForm.renewal_rate} onChange={e => setAgreementForm(v => ({ ...v, renewal_rate: e.target.value }))} /></div><div><Label>退款观察天数</Label><Input type="number" min="0" value={agreementForm.refund_guard_days} onChange={e => setAgreementForm(v => ({ ...v, refund_guard_days: e.target.value }))} /></div></div><div className="commission-rule-note"><strong>按首个服务月结算</strong><p>从客户实际服务起始日到次月同日为首期；同一期分次收款均用首期比例。季度或年度预付跨期按服务覆盖天数分摊。</p></div><div className="commission-rule-note"><strong>固定续费比例</strong><p>新协议的续费比例不随无新客月份衰减。历史协议保持原有规则，生效日期之后使用新版本。</p></div><div><Label>生效日期</Label><Input type="date" value={agreementForm.effective_from} onChange={e => setAgreementForm(v => ({ ...v, effective_from: e.target.value }))} /></div><div className="rounded-lg bg-amber-50 p-3 text-xs text-amber-800">保存后新建首服务月规则版本。旧已确认、待发放和已发放记录保留原比例与金额；历史协议不会被自动改成新规则。</div><div><Label>备注</Label><Textarea value={agreementForm.notes} onChange={e => setAgreementForm(v => ({ ...v, notes: e.target.value }))} /></div></div></CrmFormDialogBody><CrmFormDialogFooter><Button variant="outline" onClick={closeDialog}>取消</Button><Button disabled={formOptionsUnavailable || working || !agreementForm.partner_id} onClick={submit}>保存协议版本</Button></CrmFormDialogFooter></CrmFormDialogContent></Dialog>
    <Dialog open={dialog === 'attribution'} onOpenChange={open => { if (!open) closeDialog(); }}><CrmFormDialogContent className="financial-workspace-form"><CrmFormDialogHeader><DialogTitle>设置客户归属与计佣</DialogTitle></CrmFormDialogHeader><CrmFormDialogBody>{optionsNotice}<div className="space-y-3"><div><Label>搜索客户编号或名称</Label><Input value={customerSearch} onChange={event => setCustomerSearch(event.target.value)} placeholder="输入客户编号或商家名称筛选" /></div><div><Label>客户 *</Label><NativeSelect aria-label="归属客户" value={attributionForm.customer_id} onChange={value => setAttributionForm(v => ({ ...v, customer_id: value, engagement_id: 'all' }))} placeholder={customerOptions.length ? '从搜索结果选择客户' : '没有匹配客户'} disabled={!customerOptions.length} options={customerOptions.map(item => ({ value: String(item.id), label: `${item.code ? `${item.code} · ` : ''}${item.name}` }))} /><p className="mt-1 text-xs text-slate-400">客户较多时先输入客户编号或商家名称，再从结果中选择。</p></div><div><Label>具体项目</Label><NativeSelect aria-label="归属项目" value={attributionForm.engagement_id} onChange={value => setAttributionForm(v => ({ ...v, engagement_id: value }))} disabled={!attributionForm.customer_id} options={[{ value: 'all', label: '客户全部项目' }, ...customerEngagements.map(item => ({ value: String(item.id), label: `${item.package_name || `项目 #${item.id}`} · ${item.status}` }))]} /></div><div><Label>归属渠道 *</Label><NativeSelect aria-label="归属渠道" value={attributionForm.partner_id} onChange={value => setAttributionForm(v => ({ ...v, partner_id: value }))} placeholder="选择合作中的渠道" options={(data?.partners || []).filter(item => item.status === 'active').map(item => ({ value: String(item.id), label: `${item.name} · ${partnerTypeLabels[item.partner_type]}` }))} /></div><div><Label>生效日期</Label><Input type="date" value={attributionForm.effective_from} onChange={e => setAttributionForm(v => ({ ...v, effective_from: e.target.value }))} /></div><div className="commission-rule-fields"><div><Label>计佣方式</Label><NativeSelect aria-label="客户计佣方式" disabled={attributionIsDirect} value={attributionIsDirect ? 'none' : attributionForm.commission_mode} onChange={value => setAttributionForm(v => ({ ...v, commission_mode: value }))} options={[{ value: 'first_month_then_renewal', label: '首服务月＋后续续费' }, { value: 'renewal_only', label: '历史首期已完成，仅续费' }, { value: 'none', label: '不计佣' }]} /></div><div><Label>计佣模式生效日期 *</Label><Input aria-label="计佣模式生效日期" type="date" value={attributionForm.commission_start_date} onChange={e => setAttributionForm(v => ({ ...v, commission_start_date: e.target.value }))} /></div>{!attributionIsDirect && attributionForm.commission_mode !== 'none' && <div><Label>{attributionForm.commission_mode === 'first_month_then_renewal' ? '客户实际服务起始日 *' : '首期服务起始日（可选）'}</Label><Input aria-label="客户实际服务起始日" type="date" value={attributionForm.first_service_start} onChange={e => setAttributionForm(v => ({ ...v, first_service_start: e.target.value }))} /><p className="mt-1 text-xs text-slate-500">{attributionForm.commission_mode === 'first_month_then_renewal' ? '使用真实首期起始日，不是本次录入日期。首服务月从此日起至次月同日。' : '历史首期在系统外完成且日期未知时可留空；从约定计佣日期起按续费结算。'}</p></div>}{!attributionIsDirect && attributionRequiresHistory && <div><Label>历史首期依据 *</Label><Textarea aria-label="历史首期依据" value={attributionForm.history_basis} onChange={e => setAttributionForm(v => ({ ...v, history_basis: e.target.value }))} placeholder="例如首期已在2026年9月支付，凭证编号…；本次仅从约定续费期起计佣" /></div>}</div><p className="text-xs text-slate-500">归属只决定谁可查看；计佣方式决定如何结算。历史依据不新增收款，也不改变公司收入。</p><div><Label>归属依据</Label><Textarea value={attributionForm.source_note} onChange={e => setAttributionForm(v => ({ ...v, source_note: e.target.value }))} placeholder="例如：由该合伙人开发并完成首笔服务费收款" /></div>{attributionForm.commission_start_date < attributionForm.effective_from && <p role="alert" className="text-sm text-amber-700">计佣模式生效日期不能早于归属生效日期。</p>}{currentAttributionPreview && <div className="commission-rule-note" role="status"><strong>{currentAttributionPreview.blocked ? '需要调整生效日期' : '保存影响已核对'}</strong><p>{currentAttributionPreview.message}</p><p>受影响待确认记录 {currentAttributionPreview.affected_pending_count} 条 · 历史规则记录 {currentAttributionPreview.legacy_count} 条</p>{currentAttributionPreview.conflicts?.length > 0 && <p>受保护台账：{currentAttributionPreview.conflicts.map(row => `#${row.entry_id}（${entryStatusLabels[row.status] || row.status}）`).join('、')}</p>}</div>}</div></CrmFormDialogBody><CrmFormDialogFooter><Button variant="outline" onClick={closeDialog}>取消</Button><Button variant="outline" disabled={formOptionsUnavailable || working || !attributionReady} onClick={previewAttribution}>预览影响</Button><Button disabled={formOptionsUnavailable || working || !attributionReady || !currentAttributionPreview || currentAttributionPreview.blocked} onClick={submit}>确认保存归属</Button></CrmFormDialogFooter></CrmFormDialogContent></Dialog>
    <Dialog open={dialog === 'bulkAttribution'} onOpenChange={open => { if (!open) closeDialog(); }}><CrmFormDialogContent className="financial-workspace-form max-w-4xl"><CrmFormDialogHeader><DialogTitle>一键补齐客户归属</DialogTitle></CrmFormDialogHeader><CrmFormDialogBody>{bulkPreview && <div className="space-y-4"><div className="rounded-lg border border-blue-100 bg-blue-50 p-3 text-sm text-blue-900"><p className="font-semibold">执行前预览，不覆盖任何已有归属</p><p className="mt-1 text-blue-700">系统只自动处理依据明确的记录：匹配到内部销售则归该员工，否则归公司直营；冲突数据继续保留人工确认。</p></div><div className="grid grid-cols-2 gap-3 sm:grid-cols-4"><div className="rounded-lg border p-3"><p className="text-xs text-slate-500">可自动补齐</p><p className="mt-1 text-2xl font-bold text-blue-700">{bulkPreview.ready_count}</p></div><div className="rounded-lg border p-3"><p className="text-xs text-slate-500">内部销售</p><p className="mt-1 text-2xl font-bold">{bulkPreview.employee_count}</p></div><div className="rounded-lg border p-3"><p className="text-xs text-slate-500">公司直营</p><p className="mt-1 text-2xl font-bold text-emerald-700">{bulkPreview.direct_count}</p></div><div className="rounded-lg border p-3"><p className="text-xs text-slate-500">人工确认</p><p className="mt-1 text-2xl font-bold text-amber-600">{bulkPreview.manual_review_count}</p></div></div><div className="max-h-[45vh] overflow-auto rounded-lg border"><table className="w-full min-w-[760px] text-sm"><thead className="sticky top-0 bg-slate-50 text-left text-xs text-slate-500"><tr><th className="px-3 py-2">客户 / 项目</th><th>建议归属</th><th>生效日期</th><th className="px-3">判断依据</th></tr></thead><tbody>{bulkPreview.items.map(item => <tr key={`${item.customer_id}-${item.engagement_id || 'all'}`} className="border-t"><td className="px-3 py-3"><p className="font-medium">{item.customer_code ? `${item.customer_code} · ` : ''}{item.customer_name}</p><p className="text-xs text-slate-400">{item.engagement_id ? item.engagement_name || `项目 #${item.engagement_id}` : '客户全部项目'}</p></td><td><Badge className={item.status === 'ready' ? item.partner_type === 'direct' ? 'bg-emerald-100 text-emerald-700' : 'bg-blue-100 text-blue-700' : 'bg-amber-100 text-amber-800'}>{item.status === 'ready' ? item.partner_name : '待人工确认'}</Badge></td><td>{item.effective_from}</td><td className="px-3 text-xs text-slate-600">{item.basis}</td></tr>)}</tbody></table>{!bulkPreview.items.length && <div className="py-10 text-center text-sm text-emerald-700">当前没有需要补齐的客户归属</div>}</div><p className="text-xs text-slate-500">原始 {bulkPreview.source_issue_count} 条归属问题已按客户和项目合并为 {bulkPreview.target_count} 个处理目标；协议缺失不会在本次批量操作中自动修改。</p></div>}</CrmFormDialogBody><CrmFormDialogFooter><Button variant="outline" onClick={closeDialog}>取消</Button><Button disabled={working || !bulkPreview?.ready_count} onClick={applyBulkAttribution}>{working ? '正在处理...' : `确认补齐 ${bulkPreview?.ready_count || 0} 项`}</Button></CrmFormDialogFooter></CrmFormDialogContent></Dialog>
    </>}
  </div>;
}
