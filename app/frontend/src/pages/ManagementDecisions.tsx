import { useEffect, useMemo, useState } from 'react';
import { Link, useLocation, useSearchParams } from 'react-router-dom';
import {
  Activity, AlertTriangle, ArrowLeft, BarChart3, BriefcaseBusiness, CheckCircle2, Clock3,
  Database, Gauge, Layers3, ListChecks, PlayCircle, RefreshCw, Search, ShieldCheck, TrendingUp, Users, WalletCards,
} from 'lucide-react';
import { toast } from 'sonner';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { client } from '@/lib/api';
import { useRole } from '@/lib/role-context';
import { buildReturnLink } from '@/lib/navigation-state';

type Project = {
  id: number;
  customer_id: number;
  customer_name: string;
  customer_code?: string;
  business_line: { code: string; name: string };
  product: { code: string; name: string };
  package_name?: string;
  status: string;
  billing_cycle?: string;
  collection_method?: string;
  currency: string;
  paid_started_at?: string;
  stopped_at?: string;
  industry?: string;
  sales_person?: string;
  owner_employee_id?: number;
};

type Suggestion = {
  business_line: string;
  product_code: string;
  product_name: string;
  paid_started_at?: string;
  billing_cycle?: string;
  currency: string;
  source_payment_ids: number[];
  source_subscription_ids: number[];
  basis: string[];
};

type ReviewItem = {
  customer_id: number;
  customer_code?: string;
  customer_name: string;
  industry?: string;
  review_status: string;
  review_note?: string;
  reviewed_by_name?: string;
  reviewed_at?: string;
  customer_lifecycle?: { status: string; started_at: string; first_payment_id?: number };
  warnings: Array<{ code: string; message: string; scope: string; source_id?: number }>;
  suggestions: Suggestion[];
  projects: Project[];
};

type ReviewData = {
  start_date: string;
  write_enabled: boolean;
  summary: {
    customers: number;
    payments: number;
    subscriptions: number;
    warning_counts: Record<string, number>;
    review_counts: Record<string, number>;
    project_count: number;
    active_project_count: number;
    at_risk_project_count: number;
    multi_project_customers: number;
    project_line_counts: Record<string, number>;
    project_status_counts: Record<string, number>;
    anomaly_count: number;
    high_anomaly_count: number;
    risk_reminder_count: number;
    line_metrics: Record<string, {
      name: string; project_count: number; customer_count: number; active_count: number;
      stopped_count: number; at_risk_count: number; average_months?: number; churn_rate?: number;
      duration_sample_count: number;
    }>;
    multi_project_combinations: Record<string, number>;
  };
  items: ReviewItem[];
  projects: Project[];
  anomalies: Array<{ code: string; category?: string; severity: string; customer_id: number; customer_name: string; project_id?: number; message: string; suggested_action?: string }>;
  recommendations: Array<{ level: string; title: string; message: string }>;
};

type AutomationData = {
  summary: {
    total: number;
    open: number;
    in_progress: number;
    resolved: number;
    open_task_count: number;
    category_counts: Record<string, number>;
    severity_counts: Record<string, number>;
  };
  items: Array<{
    id: number;
    issue_key: string;
    code: string;
    category: string;
    severity: string;
    status: string;
    customer_id: number;
    project_id?: number;
    customer_name: string;
    message: string;
    suggested_action?: string;
    occurrence_count: number;
    first_detected_at: string;
    last_detected_at: string;
    resolved_at?: string;
    resolution_note?: string;
    task?: { id: number; status: string; assignee_name?: string; due_date?: string; completion_result?: string };
  }>;
  last_run?: {
    id: number;
    trigger: string;
    status: string;
    detected_count: number;
    opened_count: number;
    resolved_count: number;
    task_created_count: number;
    completed_at?: string;
  };
  schedule: {
    enabled: boolean;
    timezone: string;
    hour: number;
    next_run_at: string;
    auto_stop_enabled: boolean;
  };
  write_enabled: boolean;
};

type GrowthData = {
  period: { start_date: string; end_date: string };
  formal_monthly_profit: {
    definition: string; accounting_note: string; missing_rate_months: string[];
    rows: Array<{
      year_month: string; project_contribution_usd: number; project_contribution_cny: number;
      company_expense_usd: number; company_expense_cny: number; exchange_rate: number | null;
      payroll_cost_cny: number; payroll_source: string;
      exchange_rate_source?: string; exchange_rate_status: string; formal_profit_cny: number | null; status: 'ready' | 'cny_only' | 'missing_rate';
    }>;
  };
  unit_economics: {
    definition: string;
    guardrails: string[];
    totals: Record<string, Record<string, number>>;
    unallocated: Record<string, Record<string, number>>;
    coverage: { direct_projects: number; inferred_projects: number; projects_without_finance_data: number };
    business_lines: Array<{
      business_line_code: string; business_line: string; currency: string; project_count: number;
      recognized_revenue: number; contribution_profit: number; average_project_contribution: number; contribution_margin: number | null;
    }>;
    projects: Array<{
      project_id: number; customer_id: number; customer_name: string; customer_code?: string;
      business_line: string; business_line_code: string; product_name: string; status: string;
      confidence: 'direct' | 'single_project_inferred' | 'no_finance_data';
      metrics: Array<Record<string, number | string | null>>;
    }>;
  };
  customer_health: {
    summary: Record<string, number>;
    auto_stop_enabled: boolean;
    updated_through: string;
    items: Array<{
      project_id: number; customer_id: number; customer_name: string; business_line: string; product_name?: string;
      project_status: string; owner_name?: string; score: number; level: 'healthy' | 'watch' | 'risk' | 'critical';
      reasons: Array<{ code: string; points: number; message: string }>; recommended_action: string;
    }>;
  };
  team_capacity: {
    settings: { project_capacity_target: number; capacity_warning_ratio: number };
    summary: { active_projects: number; unassigned_projects: number; overdue_rate: number; near_or_over_capacity: number };
    employees: Array<{
      employee_id: number; employee_name: string; role: string; active_projects: number; open_tasks: number;
      overdue_tasks: number; open_delivery_tasks: number; overdue_delivery_tasks: number;
      capacity_target: number; utilization: number; capacity_level: string;
    }>;
    sales_lead_capacity: any;
    recommendations: Array<{ level: string; title: string; message: string }>;
  };
};

type ProjectForm = {
  engagement_id?: number;
  business_line_code: string;
  product_code: string;
  product_name: string;
  package_name: string;
  status: string;
  billing_cycle: string;
  collection_method: string;
  currency: string;
  paid_started_at: string;
  stopped_at: string;
  source_payment_ids: number[];
  source_subscription_ids: number[];
};

const lineLabels: Record<string, string> = {
  managed_service: '代运营', restaurant_os: '餐饮 OS', beauty_os: '美业 OS', one_time_project: '一次性项目',
};

const lineProducts: Record<string, { code: string; name: string }> = {
  managed_service: { code: 'managed_service_legacy', name: '代运营历史套餐' },
  restaurant_os: { code: 'restaurant_os_legacy', name: '餐饮 OS' },
  beauty_os: { code: 'beauty_os_legacy', name: '美业 OS' },
  one_time_project: { code: 'one_time_legacy', name: '一次性项目' },
};

const projectStatusLabels: Record<string, string> = {
  pending_setup: '待开通', trial: '试用中', active_paid: '付费合作中', at_risk: '有流失风险',
  paused: '项目暂停', pending_stop: '待停止', stopped: '项目已停止', reactivated: '重新合作', completed: '一次性项目完成',
};

const projectStatusClasses: Record<string, string> = {
  pending_setup: 'bg-slate-100 text-slate-700', trial: 'bg-blue-100 text-blue-700', active_paid: 'bg-emerald-100 text-emerald-700',
  at_risk: 'bg-orange-100 text-orange-700', paused: 'bg-amber-100 text-amber-700', pending_stop: 'bg-orange-100 text-orange-700',
  stopped: 'bg-red-100 text-red-700', reactivated: 'bg-cyan-100 text-cyan-700', completed: 'bg-violet-100 text-violet-700',
};

const reviewLabels: Record<string, string> = {
  pending: '待审核', confirmed: '已确认', needs_follow_up: '稍后核对',
};

const collectionLabels: Record<string, string> = {
  stripe_auto: 'Stripe 自动扣款', bank_transfer: '银行转账', check: '支票', zelle: 'Zelle', other: '其他',
};

const qualityCategoryLabels: Record<string, string> = {
  risk: '客户风险',
  integrity: '状态一致性',
  data_quality: '资料完整性',
  finance: '财务闭环',
  customer_success: '客户跟进',
  delivery: '交付执行',
};

type Section = 'overview' | 'insights' | 'projects' | 'exceptions' | 'history';

const sectionQueryValues: Record<Section, string> = {
  overview: 'overview',
  insights: 'insights',
  projects: 'projects',
  exceptions: 'quality',
  history: 'history',
};

const querySectionValues: Record<string, Section> = {
  overview: 'overview',
  insights: 'insights',
  projects: 'projects',
  quality: 'exceptions',
  exceptions: 'exceptions',
  history: 'history',
};

function authOptions() {
  const token = localStorage.getItem('emp_auth_token') || localStorage.getItem('token');
  return token ? { headers: { Authorization: `Bearer ${token}` } } : undefined;
}

function errorMessage(error: any, fallback = '操作失败') {
  return error?.data?.detail || error?.response?.data?.detail || error?.message || fallback;
}

function dateValue(value?: string) {
  return value ? value.slice(0, 10) : '';
}

function money(value: number | null | undefined, currency: string) {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency, maximumFractionDigits: 2 }).format(Number(value || 0));
}

const healthLabels: Record<string, string> = { healthy: '健康', watch: '需关注', risk: '有风险', critical: '高风险' };
const healthClasses: Record<string, string> = {
  healthy: 'bg-emerald-100 text-emerald-700', watch: 'bg-amber-100 text-amber-700',
  risk: 'bg-orange-100 text-orange-700', critical: 'bg-red-100 text-red-700',
};

function suggestionToForm(suggestion: Suggestion): ProjectForm {
  return {
    business_line_code: suggestion.business_line,
    product_code: suggestion.product_code,
    product_name: suggestion.product_name,
    package_name: suggestion.product_name,
    status: 'active_paid',
    billing_cycle: suggestion.billing_cycle || (suggestion.business_line === 'one_time_project' ? 'one_time' : 'monthly'),
    collection_method: 'other',
    currency: suggestion.currency || 'USD',
    paid_started_at: dateValue(suggestion.paid_started_at),
    stopped_at: '',
    source_payment_ids: suggestion.source_payment_ids,
    source_subscription_ids: suggestion.source_subscription_ids,
  };
}

function projectToForm(project: Project): ProjectForm {
  return {
    engagement_id: project.id,
    business_line_code: project.business_line.code,
    product_code: project.product.code,
    product_name: project.product.name,
    package_name: project.package_name || project.product.name,
    status: project.status,
    billing_cycle: project.billing_cycle || '',
    collection_method: project.collection_method || 'other',
    currency: project.currency || 'USD',
    paid_started_at: dateValue(project.paid_started_at),
    stopped_at: dateValue(project.stopped_at),
    source_payment_ids: [],
    source_subscription_ids: [],
  };
}

export default function ManagementDecisions() {
  const { isAdmin } = useRole();
  const location = useLocation();
  const [searchParams, setSearchParams] = useSearchParams();
  const today = new Date().toISOString().slice(0, 10);
  const [startDate, setStartDate] = useState('2026-01-01');
  const [data, setData] = useState<ReviewData | null>(null);
  const [automation, setAutomation] = useState<AutomationData | null>(null);
  const [growth, setGrowth] = useState<GrowthData | null>(null);
  const [projectCapacityTarget, setProjectCapacityTarget] = useState(12);
  const [rateDrafts, setRateDrafts] = useState<Record<string, { rate: string; source: string }>>({});
  const [rateSavingMonth, setRateSavingMonth] = useState('');
  const [loading, setLoading] = useState(true);
  const [scanLoading, setScanLoading] = useState(false);
  const [bulkTaskLoading, setBulkTaskLoading] = useState(false);
  const [search, setSearch] = useState('');
  const [reviewFilter, setReviewFilter] = useState('pending');
  const [section, setSection] = useState<Section>(() => querySectionValues[searchParams.get('section') || ''] || 'overview');
  const [projectSearch, setProjectSearch] = useState('');
  const [projectLineFilter, setProjectLineFilter] = useState('all');
  const [projectStatusFilter, setProjectStatusFilter] = useState('all');
  const [projectIndustryFilter, setProjectIndustryFilter] = useState('all');
  const [qualityStatusFilter, setQualityStatusFilter] = useState(searchParams.get('qualityStatus') || 'active');
  const [qualityCategoryFilter, setQualityCategoryFilter] = useState(searchParams.get('qualityCategory') || 'all');
  const [reviewing, setReviewing] = useState<ReviewItem | null>(null);
  const [projectForms, setProjectForms] = useState<ProjectForm[]>([]);
  const [reviewNote, setReviewNote] = useState('');
  const [saving, setSaving] = useState(false);
  const [statusProject, setStatusProject] = useState<Project | null>(null);
  const [nextStatus, setNextStatus] = useState('active_paid');
  const [statusDate, setStatusDate] = useState(today);
  const [statusReason, setStatusReason] = useState('');

  const loadData = async () => {
    setLoading(true);
    try {
      const [response, automationResponse, growthResponse] = await Promise.all([
        client.apiCall.invoke({
          url: `/api/v1/management-decisions/classification-review?start_date=${startDate}`,
          method: 'GET', options: authOptions(),
        }),
        client.apiCall.invoke({
          url: '/api/v1/management-decisions/automation/overview',
          method: 'GET', options: authOptions(),
        }),
        isAdmin ? client.apiCall.invoke({
          url: `/api/v1/management-decisions/growth-dashboard?start_date=${startDate}&end_date=${today}&project_capacity_target=${projectCapacityTarget}`,
          method: 'GET', options: authOptions(),
        }) : Promise.resolve({ data: null }),
      ]);
      setData(response.data);
      setAutomation(automationResponse.data);
      setGrowth(growthResponse.data);
      if (growthResponse.data?.formal_monthly_profit?.rows) {
        setRateDrafts(Object.fromEntries(growthResponse.data.formal_monthly_profit.rows.map((row: any) => [row.year_month, {
          rate: row.exchange_rate == null ? '' : String(row.exchange_rate),
          source: row.exchange_rate_source || '当月平均汇率（手动核对）',
        }])));
      }
    } catch (error: any) {
      toast.error(errorMessage(error, '经营分类数据加载失败'));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { void loadData(); }, []);

  useEffect(() => {
    const nextSection = querySectionValues[searchParams.get('section') || ''];
    if (nextSection && nextSection !== section) setSection(nextSection);
    const nextStatus = searchParams.get('qualityStatus');
    if (nextStatus && nextStatus !== qualityStatusFilter) setQualityStatusFilter(nextStatus);
    const nextCategory = searchParams.get('qualityCategory');
    if (nextCategory && nextCategory !== qualityCategoryFilter) setQualityCategoryFilter(nextCategory);
  }, [qualityCategoryFilter, qualityStatusFilter, searchParams, section]);

  const changeSection = (nextSection: Section) => {
    setSection(nextSection);
    const next = new URLSearchParams(searchParams);
    if (nextSection === 'overview') next.delete('section');
    else next.set('section', sectionQueryValues[nextSection]);
    setSearchParams(next, { replace: true });
  };

  const changeQualityFilter = (key: 'qualityStatus' | 'qualityCategory', value: string) => {
    if (key === 'qualityStatus') setQualityStatusFilter(value);
    else setQualityCategoryFilter(value);
    const next = new URLSearchParams(searchParams);
    next.set('section', 'quality');
    if ((key === 'qualityStatus' && value === 'active') || (key === 'qualityCategory' && value === 'all')) next.delete(key);
    else next.set(key, value);
    setSearchParams(next, { replace: true });
  };

  const saveExchangeRate = async (yearMonth: string) => {
    const draft = rateDrafts[yearMonth];
    const rate = Number(draft?.rate);
    if (!draft || !Number.isFinite(rate) || rate <= 0 || !draft.source.trim()) {
      toast.error('请填写有效的 USD/CNY 当月平均汇率和来源');
      return;
    }
    setRateSavingMonth(yearMonth);
    try {
      await client.apiCall.invoke({
        url: `/api/v1/management-decisions/exchange-rates/${yearMonth}`,
        method: 'PUT', data: { average_rate: rate, source: draft.source.trim(), status: 'locked' }, options: authOptions(),
      });
      toast.success(`${yearMonth} 汇率已锁定，人民币利润已重新核算`);
      await loadData();
    } catch (error: any) {
      toast.error(errorMessage(error, '月度汇率保存失败'));
    } finally {
      setRateSavingMonth('');
    }
  };

  const currentDecisionPath = () => {
    const next = new URLSearchParams(location.search);
    next.set('section', sectionQueryValues[section]);
    if (section === 'exceptions') {
      if (qualityStatusFilter !== 'active') next.set('qualityStatus', qualityStatusFilter);
      else next.delete('qualityStatus');
      if (qualityCategoryFilter !== 'all') next.set('qualityCategory', qualityCategoryFilter);
      else next.delete('qualityCategory');
    }
    return `${location.pathname}?${next.toString()}`;
  };

  const visibleItems = useMemo(() => {
    const keyword = search.trim().toLowerCase();
    return (data?.items || []).filter(item => {
      if (reviewFilter !== 'all' && item.review_status !== reviewFilter) return false;
      if (!keyword) return true;
      return [item.customer_name, item.customer_code, item.industry]
        .filter(Boolean).some(value => String(value).toLowerCase().includes(keyword));
    });
  }, [data, reviewFilter, search]);

  const industries = useMemo(() => Array.from(new Set((data?.projects || []).map(row => row.industry).filter(Boolean) as string[])).sort(), [data]);
  const visibleProjects = useMemo(() => {
    const keyword = projectSearch.trim().toLowerCase();
    return (data?.projects || []).filter(project => {
      if (projectLineFilter !== 'all' && project.business_line.code !== projectLineFilter) return false;
      if (projectStatusFilter !== 'all' && project.status !== projectStatusFilter) return false;
      if (projectIndustryFilter !== 'all' && project.industry !== projectIndustryFilter) return false;
      if (!keyword) return true;
      return [project.customer_name, project.customer_code, project.package_name, project.sales_person]
        .filter(Boolean).some(value => String(value).toLowerCase().includes(keyword));
    });
  }, [data, projectIndustryFilter, projectLineFilter, projectSearch, projectStatusFilter]);

  const visibleQualityIssues = useMemo(() => (automation?.items || []).filter(row => {
    const statusMatches = qualityStatusFilter === 'all'
      || (qualityStatusFilter === 'active' && row.status !== 'resolved')
      || row.status === qualityStatusFilter;
    const categoryMatches = qualityCategoryFilter === 'all' || row.category === qualityCategoryFilter;
    return statusMatches && categoryMatches;
  }), [automation, qualityCategoryFilter, qualityStatusFilter]);
  const activeQualityCount = (automation?.summary.open || 0) + (automation?.summary.in_progress || 0);
  const visibleIssuesWithoutTask = visibleQualityIssues.filter(row => row.status !== 'resolved' && !row.task);

  const runAutomationScan = async () => {
    setScanLoading(true);
    try {
      const response = await client.apiCall.invoke({
        url: '/api/v1/management-decisions/automation/scan',
        method: 'POST', options: authOptions(),
      });
      setAutomation(response.data.overview);
      toast.success(`扫描完成：发现 ${response.data.scan.detected_count} 项，生成 ${response.data.scan.task_created_count} 个任务`);
      await loadData();
    } catch (error: any) {
      toast.error(errorMessage(error, '自动扫描失败'));
    } finally {
      setScanLoading(false);
    }
  };

  const createQualityTask = async (issueId: number) => {
    try {
      await client.apiCall.invoke({
        url: `/api/v1/management-decisions/automation/issues/${issueId}/task`,
        method: 'POST', options: authOptions(),
      });
      toast.success('已生成闭环任务');
      await loadData();
    } catch (error: any) {
      toast.error(errorMessage(error, '生成任务失败'));
    }
  };

  const createVisibleQualityTasks = async () => {
    if (visibleIssuesWithoutTask.length === 0) return;
    if (!window.confirm(`为当前筛选中的 ${visibleIssuesWithoutTask.length} 个问题生成闭环任务？已有任务不会重复创建。`)) return;
    setBulkTaskLoading(true);
    try {
      const issueIds = visibleIssuesWithoutTask.map(row => row.id);
      let processed = 0;
      let errorCount = 0;
      for (let index = 0; index < issueIds.length; index += 200) {
        const response = await client.apiCall.invoke({
          url: '/api/v1/management-decisions/automation/issues/tasks-batch',
          method: 'POST',
          data: { issue_ids: issueIds.slice(index, index + 200) },
          options: authOptions(),
        });
        processed += Number(response.data?.processed || 0);
        errorCount += Array.isArray(response.data?.errors) ? response.data.errors.length : 0;
      }
      toast.success(errorCount ? `已处理 ${processed} 个问题，${errorCount} 个需人工核对` : `已处理 ${processed} 个问题`);
      await loadData();
    } catch (error: any) {
      toast.error(errorMessage(error, '批量生成任务失败'));
    } finally {
      setBulkTaskLoading(false);
    }
  };

  const openReview = (item: ReviewItem) => {
    setReviewing(item);
    setReviewNote(item.review_note || '');
    if (item.projects.length) setProjectForms(item.projects.map(projectToForm));
    else if (item.suggestions.length) setProjectForms(item.suggestions.map(suggestionToForm));
    else setProjectForms([suggestionToForm({
      business_line: 'managed_service', product_code: 'managed_service_legacy', product_name: '代运营历史套餐',
      currency: 'USD', source_payment_ids: [], source_subscription_ids: [], basis: [],
    })]);
  };

  const updateProjectForm = (index: number, patch: Partial<ProjectForm>) => {
    setProjectForms(current => current.map((row, rowIndex) => {
      if (rowIndex !== index) return row;
      const next = { ...row, ...patch };
      if (patch.business_line_code) {
        const product = lineProducts[patch.business_line_code];
        next.product_code = product.code;
        next.product_name = product.name;
        if (!next.package_name || next.package_name === row.product_name) next.package_name = product.name;
        if (patch.business_line_code === 'one_time_project') next.billing_cycle = 'one_time';
      }
      if (patch.product_name !== undefined && patch.package_name === undefined) {
        next.package_name = patch.product_name;
      }
      return next;
    }));
  };

  const saveReview = async (decision: 'confirmed' | 'needs_follow_up') => {
    if (!reviewing) return;
    if (decision === 'confirmed' && projectForms.some(row => !row.package_name.trim())) {
      toast.error('请填写每个项目的套餐或项目名称');
      return;
    }
    if (decision === 'confirmed' && projectForms.some(row => ['active_paid', 'reactivated'].includes(row.status) && !row.paid_started_at)) {
      toast.error('付费合作中的项目必须填写第一笔有效收款日期');
      return;
    }
    setSaving(true);
    try {
      await client.apiCall.invoke({
        url: `/api/v1/management-decisions/classification-review/customers/${reviewing.customer_id}`,
        method: 'POST',
        data: {
          decision,
          note: reviewNote || null,
          projects: decision === 'confirmed' ? projectForms.map(row => ({
            ...row,
            paid_started_at: row.paid_started_at ? `${row.paid_started_at}T00:00:00Z` : null,
            stopped_at: row.stopped_at ? `${row.stopped_at}T00:00:00Z` : null,
          })) : [],
        },
        options: authOptions(),
      });
      toast.success(decision === 'confirmed' ? '客户分类与独立项目已确认' : '已标记为稍后核对');
      setReviewing(null);
      await loadData();
    } catch (error: any) {
      toast.error(errorMessage(error));
    } finally {
      setSaving(false);
    }
  };

  const openStatus = (project: Project) => {
    setStatusProject(project);
    setNextStatus(project.status);
    setStatusDate(today);
    setStatusReason('');
  };

  const saveStatus = async () => {
    if (!statusProject) return;
    setSaving(true);
    try {
      await client.apiCall.invoke({
        url: `/api/v1/management-decisions/engagements/${statusProject.id}/status`,
        method: 'PATCH',
        data: { status: nextStatus, effective_date: statusDate, reason_code: null, note: statusReason || null },
        options: authOptions(),
      });
      toast.success('项目状态已更新；客户整体合作状态未改变');
      setStatusProject(null);
      await loadData();
    } catch (error: any) {
      toast.error(errorMessage(error));
    } finally {
      setSaving(false);
    }
  };

  const summary = data?.summary;
  const pendingCount = summary?.review_counts?.pending || 0;
  const followUpCount = summary?.review_counts?.needs_follow_up || 0;
  const warningTotal = Object.values(summary?.warning_counts || {}).reduce((total, value) => total + value, 0);
  const economicsTotals = Object.entries(growth?.unit_economics.totals || {});
  const riskyHealth = (growth?.customer_health.items || []).filter(row => row.level !== 'healthy');
  const salesCapacitySummary = growth?.team_capacity.sales_lead_capacity || {};

  return (
    <div className="app-page space-y-5">
      <div className="app-page-title gap-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-blue-600">T24 Marketing · Management Decisions</p>
          <h1 className="mt-1 text-2xl font-bold text-slate-900">经营分类与项目</h1>
          <p className="mt-1 text-sm text-slate-500">逐位确认真实业务线；客户合作状态与代运营、OS、一次性项目分别管理。</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button asChild variant="outline"><Link to="/customer-lifecycle"><ArrowLeft className="mr-2 h-4 w-4" />客户生命周期</Link></Button>
          <Button onClick={() => void loadData()} disabled={loading}><RefreshCw className={`mr-2 h-4 w-4 ${loading ? 'animate-spin' : ''}`} />刷新数据</Button>
        </div>
      </div>

      <Card className="border-blue-200 bg-blue-50/50">
        <CardContent className="flex flex-wrap items-center justify-between gap-3 p-4">
          <div className="flex items-center gap-3"><ShieldCheck className="h-5 w-5 text-blue-600" /><div><p className="text-sm font-semibold text-slate-800">安全审核模式</p><p className="text-xs text-slate-500">确认项目不会改变客户“合作中/已停止”状态；原收款、订阅和生命周期记录保持不变。</p></div></div>
          <div className="flex flex-wrap items-end gap-2"><div><Label className="text-xs">统计开始</Label><Input type="date" min="2026-01-01" value={startDate} onChange={event => setStartDate(event.target.value)} className="mt-1 w-40 bg-white" /></div>{isAdmin && <div><Label className="text-xs">单人项目容量</Label><Input type="number" min={1} max={100} value={projectCapacityTarget} onChange={event => setProjectCapacityTarget(Math.max(1, Number(event.target.value) || 1))} className="mt-1 w-28 bg-white" /></div>}<Button variant="outline" onClick={() => void loadData()}>应用</Button></div>
        </CardContent>
      </Card>

      <Card className="border-slate-200">
        <CardContent className="flex flex-wrap gap-2 p-2">
          {[
            ['overview', '经营总览', BarChart3], ...(isAdmin ? [['insights', '利润·健康·产能', Gauge]] : []), ['projects', '项目客户明细', BriefcaseBusiness],
            ['exceptions', `数据质量中心 ${activeQualityCount || summary?.anomaly_count || 0}`, Database], ['history', `历史补录 ${pendingCount}`, Clock3],
          ].map(([value, label, Icon]: any[]) => <Button key={value} type="button" variant={section === value ? 'default' : 'ghost'} onClick={() => changeSection(value)}><Icon className="mr-2 h-4 w-4" />{label}</Button>)}
        </CardContent>
      </Card>

      {section === 'overview' && <>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-7">
          {[
            ['待补录客户', pendingCount, '仅限历史数据', Clock3, 'text-orange-600', 'bg-orange-50'],
            ['高优先异常', summary?.high_anomaly_count || 0, '需要老板确认', AlertTriangle, 'text-red-600', 'bg-red-50'],
            ['自动风险提醒', summary?.risk_reminder_count || 0, '只提醒，不自动停止', AlertTriangle, 'text-amber-600', 'bg-amber-50'],
            ['分类提示', warningTotal, '不会自动写入', ShieldCheck, 'text-blue-600', 'bg-blue-50'],
            ['已确认项目', summary?.project_count || 0, '从客户管理产生', BriefcaseBusiness, 'text-violet-600', 'bg-violet-50'],
            ['合作中项目', summary?.active_project_count || 0, '按项目口径统计', TrendingUp, 'text-emerald-600', 'bg-emerald-50'],
            ['多项目客户', summary?.multi_project_customers || 0, '交叉销售样本', Layers3, 'text-cyan-600', 'bg-cyan-50'],
          ].map(([label, value, hint, Icon, color, bg]: any[]) => <Card key={label} className="border-slate-200"><CardContent className="p-4"><div className={`flex h-9 w-9 items-center justify-center rounded-xl ${bg}`}><Icon className={`h-4 w-4 ${color}`} /></div><p className="mt-3 text-xs text-slate-500">{label}</p><p className="mt-1 text-xl font-bold text-slate-900">{value}</p><p className="mt-1 text-[11px] text-slate-400">{hint}</p></CardContent></Card>)}
        </div>
        <div className="grid gap-4 xl:grid-cols-2">
          <Card className="border-slate-200"><CardHeader><CardTitle className="text-base">各业务生命周期信号</CardTitle><p className="text-xs text-slate-500">项目样本不足时不输出虚假的增长结论。</p></CardHeader><CardContent className="grid gap-3 sm:grid-cols-2">{Object.entries(lineLabels).map(([code, label]) => { const metric = summary?.line_metrics?.[code]; return <div key={code} className="rounded-xl border border-slate-200 bg-slate-50 p-4"><div className="flex items-center justify-between"><p className="font-semibold">{label}</p><Badge variant="outline">{metric?.active_count || 0} 合作中</Badge></div><div className="mt-3 grid grid-cols-3 gap-2 text-center"><div><p className="text-lg font-bold">{metric?.project_count || 0}</p><p className="text-[11px] text-slate-400">项目</p></div><div><p className="text-lg font-bold">{metric?.average_months ?? '-'}</p><p className="text-[11px] text-slate-400">平均月数</p></div><div><p className="text-lg font-bold">{metric?.churn_rate == null ? '-' : `${Math.round(metric.churn_rate * 100)}%`}</p><p className="text-[11px] text-slate-400">项目流失</p></div></div><p className="mt-3 text-[11px] text-slate-400">有效时长样本 {metric?.duration_sample_count || 0} 个</p></div>; })}</CardContent></Card>
          <Card className="border-slate-200"><CardHeader><CardTitle className="text-base">老板决策建议</CardTitle><p className="text-xs text-slate-500">招聘和投入必须同时满足样本、留存与交付产能。</p></CardHeader><CardContent className="space-y-3">{(data?.recommendations || []).map((row, index) => <div key={`${row.title}-${index}`} className={`rounded-xl p-4 ${row.level === 'risk' ? 'bg-red-50 text-red-800' : row.level === 'growth' ? 'bg-emerald-50 text-emerald-800' : 'bg-blue-50 text-blue-800'}`}><p className="text-sm font-semibold">{row.title}</p><p className="mt-1 text-xs leading-5">{row.message}</p></div>)}<div className="rounded-xl border border-slate-200 p-4"><p className="text-sm font-semibold">多项目组合</p><div className="mt-2 space-y-2 text-xs">{Object.entries(summary?.multi_project_combinations || {}).map(([name, count]) => <div key={name} className="flex justify-between"><span>{name}</span><strong>{count} 位客户</strong></div>)}{Object.keys(summary?.multi_project_combinations || {}).length === 0 && <p className="text-slate-400">项目确认后显示交叉销售组合</p>}</div></div></CardContent></Card>
        </div>
      </>}

      {section === 'insights' && <div className="space-y-5">
        {!growth && !loading && <Card className="border-amber-200 bg-amber-50"><CardContent className="p-6 text-sm text-amber-800">当前账号没有老板经营分析权限，或数据尚未加载。</CardContent></Card>}
        {growth && <>
          <Card className="border-emerald-200 bg-emerald-50/30">
            <CardHeader><CardTitle className="flex items-center gap-2 text-base"><TrendingUp className="h-5 w-5 text-emerald-600" />管理口径月度人民币利润</CardTitle><p className="mt-1 text-xs text-slate-600">{growth.formal_monthly_profit.definition}</p><p className="text-[11px] leading-5 text-slate-500">{growth.formal_monthly_profit.accounting_note}</p></CardHeader>
              <CardContent className="overflow-x-auto"><table className="w-full min-w-[900px] text-sm"><thead><tr className="border-b bg-white/70 text-left text-xs text-slate-500"><th className="px-3 py-3">月份</th><th className="px-3 py-3">项目贡献</th><th className="px-3 py-3">公司支出</th><th className="px-3 py-3">USD/CNY 月均汇率</th><th className="px-3 py-3">汇率来源</th><th className="px-3 py-3">人民币利润</th><th className="px-3 py-3 text-right">操作</th></tr></thead><tbody>{growth.formal_monthly_profit.rows.map(row => { const draft = rateDrafts[row.year_month] || { rate: '', source: '当月平均汇率（手动核对）' }; return <tr key={row.year_month} className="border-b border-emerald-100"><td className="px-3 py-3 font-semibold">{row.year_month}</td><td className="px-3 py-3"><p>{money(row.project_contribution_usd, 'USD')}</p><p className="text-xs text-slate-400">{money(row.project_contribution_cny, 'CNY')}</p></td><td className="px-3 py-3"><p>运营 {money(row.company_expense_cny, 'CNY')}</p><p className="text-xs text-slate-400">工资 {money(row.payroll_cost_cny, 'CNY')}{row.payroll_source === 'paid_payroll' ? ' · 工资表' : row.payroll_source === 'company_expense' ? ' · 财务手工' : ''}</p>{row.company_expense_usd !== 0 && <p className="text-xs text-slate-400">另 {money(row.company_expense_usd, 'USD')}</p>}</td><td className="px-3 py-3"><Input type="number" min="0.1" max="20" step="0.0001" value={draft.rate} onChange={event => setRateDrafts(current => ({ ...current, [row.year_month]: { ...draft, rate: event.target.value } }))} className="w-24 bg-white" /></td><td className="px-3 py-3"><Input value={draft.source} onChange={event => setRateDrafts(current => ({ ...current, [row.year_month]: { ...draft, source: event.target.value } }))} className="w-44 bg-white" /></td><td className="px-3 py-3">{row.formal_profit_cny == null ? <Badge className="bg-amber-100 text-amber-700">待锁定汇率</Badge> : <><p className={`font-bold ${row.formal_profit_cny >= 0 ? 'text-emerald-700' : 'text-red-700'}`}>{money(row.formal_profit_cny, 'CNY')}</p><p className="text-[11px] text-slate-400">{row.status === 'cny_only' ? '本月无 USD 净额，无需汇率' : '汇率已锁定'}</p></>}</td><td className="px-3 py-3 text-right">{row.status === 'cny_only' && !draft.rate ? <span className="text-xs text-slate-400">无需操作</span> : <Button size="sm" variant={row.exchange_rate_status === 'locked' ? 'outline' : 'default'} disabled={rateSavingMonth === row.year_month} onClick={() => void saveExchangeRate(row.year_month)}>{rateSavingMonth === row.year_month ? '保存中…' : row.exchange_rate_status === 'locked' ? '更新并锁定' : '锁定汇率'}</Button>}</td></tr>; })}</tbody></table></CardContent>
          </Card>
          <Card className="border-slate-200">
            <CardHeader className="gap-2 lg:flex-row lg:items-start lg:justify-between"><div><CardTitle className="flex items-center gap-2 text-base"><WalletCards className="h-5 w-5 text-blue-600" />项目级真实利润与单位经济</CardTitle><p className="mt-1 text-xs text-slate-500">{growth.unit_economics.definition}</p></div><Badge variant="outline">{growth.period.start_date} 至 {growth.period.end_date}</Badge></CardHeader>
            <CardContent className="space-y-4">
              <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                {economicsTotals.map(([currency, value]) => <div key={currency} className="rounded-xl border border-slate-200 bg-slate-50 p-4"><div className="flex items-center justify-between"><p className="font-semibold">{currency} 可核算贡献利润</p><Badge className={value.contribution_profit >= 0 ? 'bg-emerald-100 text-emerald-700' : 'bg-red-100 text-red-700'}>{value.contribution_profit >= 0 ? '正贡献' : '负贡献'}</Badge></div><p className={`mt-3 text-2xl font-bold ${value.contribution_profit >= 0 ? 'text-emerald-700' : 'text-red-700'}`}>{money(value.contribution_profit, currency)}</p><div className="mt-3 grid grid-cols-2 gap-2 text-xs text-slate-500"><span>服务收入 {money(value.service_revenue, currency)}</span><span>投流差价 {money(value.ad_spread, currency)}</span><span>退款 {money(value.service_refunds, currency)}</span><span>客户成本 {money(value.customer_cost, currency)}</span></div></div>)}
                {economicsTotals.length === 0 && <div className="col-span-full rounded-xl border border-dashed p-6 text-center text-sm text-slate-400">当前期间暂无可核算项目收支</div>}
                <div className="rounded-xl border border-blue-200 bg-blue-50 p-4"><p className="font-semibold text-blue-900">数据可信度</p><div className="mt-3 space-y-2 text-xs text-blue-800"><p>直接关联项目：{growth.unit_economics.coverage.direct_projects}</p><p>单项目自动归属：{growth.unit_economics.coverage.inferred_projects}</p><p>尚无财务数据：{growth.unit_economics.coverage.projects_without_finance_data}</p></div></div>
              </div>
              <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-xs text-amber-800"><p className="font-semibold">核算护栏</p><p className="mt-1 leading-5">{growth.unit_economics.guardrails.join('；')}</p><div className="mt-2 flex flex-wrap gap-3">{Object.entries(growth.unit_economics.unallocated).flatMap(([name, currencies]) => Object.entries(currencies).filter(([, value]) => Number(value) !== 0).map(([currency, value]) => <span key={`${name}-${currency}`}>待分摊 {name}：{money(value, currency)}</span>))}</div></div>
              <div><p className="mb-2 text-sm font-semibold text-slate-800">业务线单位经济</p><div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">{growth.unit_economics.business_lines.map(row => <div key={`${row.business_line_code}-${row.currency}`} className="rounded-xl border border-slate-200 p-4"><div className="flex items-center justify-between"><p className="font-semibold">{row.business_line}</p><Badge variant="outline">{row.project_count} 项 · {row.currency}</Badge></div><p className={`mt-3 text-xl font-bold ${row.contribution_profit >= 0 ? 'text-emerald-700' : 'text-red-700'}`}>{money(row.contribution_profit, row.currency)}</p><div className="mt-2 space-y-1 text-xs text-slate-500"><p>单项目平均贡献 {money(row.average_project_contribution, row.currency)}</p><p>贡献利润率 {row.contribution_margin == null ? '-' : `${(row.contribution_margin * 100).toFixed(1)}%`}</p></div></div>)}</div></div>
              <div className="overflow-x-auto"><table className="w-full min-w-[1000px] text-sm"><thead><tr className="border-b bg-slate-50 text-left text-xs text-slate-500"><th className="px-3 py-3">客户/项目</th><th className="px-3 py-3">业务线</th><th className="px-3 py-3">服务收入</th><th className="px-3 py-3">投流差价</th><th className="px-3 py-3">退款及手续费</th><th className="px-3 py-3">成本及分润</th><th className="px-3 py-3">贡献利润</th><th className="px-3 py-3">可信度</th></tr></thead><tbody>{growth.unit_economics.projects.slice(0, 30).flatMap(project => project.metrics.map((metric, index) => { const currency = String(metric.currency); const profit = Number(metric.contribution_profit || 0); return <tr key={`${project.project_id}-${currency}`} className="border-b border-slate-100"><td className="px-3 py-3"><Link className="font-medium text-blue-700 hover:underline" to={buildReturnLink(`/customers?detail=${project.customer_id}`, currentDecisionPath(), 'management-decisions')}>{project.customer_name}</Link><p className="text-xs text-slate-400">{project.product_name}</p></td><td className="px-3 py-3">{project.business_line}</td><td className="px-3 py-3">{money(Number(metric.service_revenue), currency)}</td><td className="px-3 py-3">{money(Number(metric.ad_spread), currency)}</td><td className="px-3 py-3">{money(Number(metric.service_refunds) + Number(metric.stripe_fee_burden), currency)}</td><td className="px-3 py-3">{money(Number(metric.customer_cost) + Number(metric.channel_commission), currency)}</td><td className={`px-3 py-3 font-semibold ${profit >= 0 ? 'text-emerald-700' : 'text-red-700'}`}>{money(profit, currency)}<p className="text-[11px] font-normal text-slate-400">利润率 {metric.contribution_margin == null ? '-' : `${(Number(metric.contribution_margin) * 100).toFixed(1)}%`}</p></td><td className="px-3 py-3"><Badge variant="outline">{project.confidence === 'direct' ? '直接关联' : project.confidence === 'single_project_inferred' ? '单项目推断' : '待关联'}</Badge></td></tr>; }))}</tbody></table></div>
            </CardContent>
          </Card>

          <Card className="border-slate-200">
            <CardHeader className="gap-2 lg:flex-row lg:items-start lg:justify-between"><div><CardTitle className="flex items-center gap-2 text-base"><Activity className="h-5 w-5 text-orange-600" />客户健康度与流失预警</CardTitle><p className="mt-1 text-xs text-slate-500">收款、续费、退款、任务、交付和回访共同评分；每日自动更新，只提醒不自动停止。</p></div><Badge variant="outline">更新至 {growth.customer_health.updated_through}</Badge></CardHeader>
            <CardContent className="space-y-4">
              <div className="grid gap-3 sm:grid-cols-4">{[['healthy', '健康'], ['watch', '需关注'], ['risk', '有风险'], ['critical', '高风险']].map(([level, label]) => <div key={level} className="rounded-xl border border-slate-200 p-4"><Badge className={healthClasses[level]}>{label}</Badge><p className="mt-3 text-2xl font-bold">{growth.customer_health.summary[level] || 0}</p><p className="mt-1 text-xs text-slate-400">个项目</p></div>)}</div>
              <div className="grid gap-3 lg:grid-cols-2">{riskyHealth.slice(0, 20).map(row => <div key={row.project_id} className={`rounded-xl border p-4 ${row.level === 'critical' ? 'border-red-200 bg-red-50' : row.level === 'risk' ? 'border-orange-200 bg-orange-50' : 'border-amber-200 bg-amber-50'}`}><div className="flex items-start justify-between gap-3"><div><Link className="font-semibold text-slate-900 hover:text-blue-700" to={buildReturnLink(`/customers?detail=${row.customer_id}`, currentDecisionPath(), 'management-decisions')}>{row.customer_name}</Link><p className="mt-1 text-xs text-slate-500">{row.business_line} · {row.product_name || '项目'} · {row.owner_name || '负责人待分配'}</p></div><div className="text-right"><Badge className={healthClasses[row.level]}>{healthLabels[row.level]}</Badge><p className="mt-1 text-xl font-bold">{row.score}</p></div></div><div className="mt-3 space-y-1 text-xs text-slate-700">{row.reasons.slice(0, 3).map(reason => <p key={reason.code}>- {reason.message}</p>)}</div><p className="mt-3 rounded-lg bg-white/70 px-3 py-2 text-xs text-slate-600">下一步：{row.recommended_action}</p></div>)}{riskyHealth.length === 0 && <div className="col-span-full rounded-xl border border-dashed p-8 text-center text-sm text-emerald-600"><CheckCircle2 className="mx-auto mb-2 h-6 w-6" />当前没有需要关注的客户项目</div>}</div>
            </CardContent>
          </Card>

          <Card className="border-slate-200">
            <CardHeader><CardTitle className="flex items-center gap-2 text-base"><Users className="h-5 w-5 text-violet-600" />团队产能与招聘决策</CardTitle><p className="mt-1 text-xs text-slate-500">项目负载与逾期必须同时越线才建议招聘；销售招聘还要先看可复用线索池是否够用。</p></CardHeader>
            <CardContent className="space-y-4">
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">{[
                ['合作中项目', growth.team_capacity.summary.active_projects], ['未分配项目', growth.team_capacity.summary.unassigned_projects], ['达到预警线', growth.team_capacity.summary.near_or_over_capacity], ['任务逾期率', `${(growth.team_capacity.summary.overdue_rate * 100).toFixed(1)}%`], ['线索可用天数', Number(salesCapacitySummary.estimated_pool_days || 0).toFixed(1)],
              ].map(([label, value]) => <div key={String(label)} className="rounded-xl border border-slate-200 p-4"><p className="text-xs text-slate-500">{label}</p><p className="mt-2 text-2xl font-bold">{value}</p></div>)}</div>
              <div className="grid gap-3 lg:grid-cols-2">{growth.team_capacity.recommendations.map(row => <div key={row.title} className={`rounded-xl p-4 ${row.level === 'hire' ? 'bg-red-50 text-red-800' : row.level === 'hold' || row.level === 'process' ? 'bg-amber-50 text-amber-800' : 'bg-blue-50 text-blue-800'}`}><p className="font-semibold">{row.title}</p><p className="mt-1 text-xs leading-5">{row.message}</p></div>)}</div>
              <div className="overflow-x-auto"><table className="w-full min-w-[850px] text-sm"><thead><tr className="border-b bg-slate-50 text-left text-xs text-slate-500"><th className="px-3 py-3">员工</th><th className="px-3 py-3">在管项目</th><th className="px-3 py-3">容量使用</th><th className="px-3 py-3">协作任务</th><th className="px-3 py-3">交付任务</th><th className="px-3 py-3">判断</th></tr></thead><tbody>{growth.team_capacity.employees.map(row => <tr key={row.employee_id} className="border-b border-slate-100"><td className="px-3 py-3 font-medium">{row.employee_name}<p className="text-xs font-normal text-slate-400">{row.role}</p></td><td className="px-3 py-3">{row.active_projects} / {row.capacity_target}</td><td className="px-3 py-3"><div className="h-2 w-32 overflow-hidden rounded-full bg-slate-100"><div className={`h-full ${row.utilization >= 1 ? 'bg-red-500' : row.utilization >= .85 ? 'bg-amber-500' : 'bg-emerald-500'}`} style={{ width: `${Math.min(100, row.utilization * 100)}%` }} /></div><p className="mt-1 text-xs text-slate-400">{(row.utilization * 100).toFixed(0)}%</p></td><td className="px-3 py-3">{row.open_tasks} 待办<p className="text-xs text-red-500">{row.overdue_tasks} 逾期</p></td><td className="px-3 py-3">{row.open_delivery_tasks} 待办<p className="text-xs text-red-500">{row.overdue_delivery_tasks} 逾期</p></td><td className="px-3 py-3"><Badge className={row.capacity_level === 'overloaded' ? 'bg-red-100 text-red-700' : row.capacity_level === 'near_limit' ? 'bg-amber-100 text-amber-700' : 'bg-emerald-100 text-emerald-700'}>{row.capacity_level === 'overloaded' ? '超负荷' : row.capacity_level === 'near_limit' ? '接近上限' : '仍有余量'}</Badge></td></tr>)}</tbody></table></div>
            </CardContent>
          </Card>
        </>}
      </div>}

      {section === 'projects' && <Card className="border-slate-200">
        <CardHeader className="gap-3"><div><CardTitle className="text-base">项目客户明细</CardTitle><p className="mt-1 text-xs text-slate-500">日常项目维护从客户管理进入；本页用于筛选、观察和调整状态。</p></div><div className="flex flex-wrap gap-2"><div className="relative"><Search className="absolute left-3 top-2.5 h-4 w-4 text-slate-400" /><Input value={projectSearch} onChange={event => setProjectSearch(event.target.value)} placeholder="客户、编号、套餐或负责人" className="w-64 pl-9" /></div><select value={projectLineFilter} onChange={event => setProjectLineFilter(event.target.value)} className="h-10 rounded-md border px-3 text-sm"><option value="all">全部业务</option>{Object.entries(lineLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select><select value={projectStatusFilter} onChange={event => setProjectStatusFilter(event.target.value)} className="h-10 rounded-md border px-3 text-sm"><option value="all">全部状态</option>{Object.entries(projectStatusLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select><select value={projectIndustryFilter} onChange={event => setProjectIndustryFilter(event.target.value)} className="h-10 rounded-md border px-3 text-sm"><option value="all">全部行业</option>{industries.map(value => <option key={value} value={value}>{value}</option>)}</select></div></CardHeader>
        <CardContent className="overflow-x-auto"><table className="w-full min-w-[1050px] text-sm"><thead><tr className="border-b bg-slate-50 text-left text-xs text-slate-500"><th className="px-3 py-3">客户</th><th className="px-3 py-3">业务项目</th><th className="px-3 py-3">套餐/项目名称</th><th className="px-3 py-3">行业/负责人</th><th className="px-3 py-3">首次有效收款</th><th className="px-3 py-3">状态</th><th className="px-3 py-3">收费</th><th className="px-3 py-3 text-right">操作</th></tr></thead><tbody>{visibleProjects.map(project => <tr key={project.id} className="border-b border-slate-100"><td className="px-3 py-3 font-medium"><Link className="text-blue-700 hover:underline" to={buildReturnLink(`/customers?detail=${project.customer_id}`, currentDecisionPath(), 'management-decisions')}>{project.customer_name}</Link><p className="text-xs font-normal text-slate-400">{project.customer_code || '-'}</p></td><td className="px-3 py-3">{project.business_line.name}</td><td className="px-3 py-3">{project.package_name || project.product.name}</td><td className="px-3 py-3">{project.industry || '-'}<p className="text-xs text-slate-400">{project.sales_person || '销售待分配'}</p></td><td className="px-3 py-3">{dateValue(project.paid_started_at) || '待首笔收款'}</td><td className="px-3 py-3"><Badge className={projectStatusClasses[project.status] || 'bg-slate-100 text-slate-700'}>{projectStatusLabels[project.status] || project.status}</Badge></td><td className="px-3 py-3">{project.billing_cycle || '-'} · {project.currency}</td><td className="px-3 py-3 text-right"><Button size="sm" variant="outline" onClick={() => openStatus(project)} disabled={!isAdmin}>更改状态</Button></td></tr>)}</tbody></table>{!loading && visibleProjects.length === 0 && <div className="py-12 text-center text-sm text-slate-400">当前筛选下没有项目</div>}</CardContent>
      </Card>}

      {section === 'exceptions' && <div className="space-y-4">
        <Card className="border-blue-200 bg-blue-50/50">
          <CardContent className="flex flex-col gap-4 p-4 lg:flex-row lg:items-center lg:justify-between">
            <div className="flex items-start gap-3">
              <Database className="mt-0.5 h-5 w-5 text-blue-600" />
              <div>
                <p className="font-semibold text-slate-900">数据质量中心</p>
                <p className="mt-1 text-xs leading-5 text-slate-600">
                  每天北京时间 {String(automation?.schedule.hour ?? 8).padStart(2, '0')}:00 自动扫描；高优先和风险问题自动进入任务协作。只提醒、只建任务，不会自动停止客户或项目。
                </p>
                <p className="mt-1 text-xs text-slate-400">
                  {automation?.last_run?.completed_at ? `最近扫描：${new Date(automation.last_run.completed_at).toLocaleString('zh-CN', { hour12: false })}` : '尚未执行持久化扫描'}
                </p>
              </div>
            </div>
            <Button onClick={() => void runAutomationScan()} disabled={!isAdmin || scanLoading}>
              {scanLoading ? <RefreshCw className="mr-2 h-4 w-4 animate-spin" /> : <PlayCircle className="mr-2 h-4 w-4" />}
              {scanLoading ? '扫描中…' : '立即扫描'}
            </Button>
          </CardContent>
        </Card>

        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
          {[
            ['待处理', (automation?.summary.open || 0) + (automation?.summary.in_progress || 0), '仍需处理', 'text-amber-700', 'bg-amber-50'],
            ['高优先', automation?.summary.severity_counts.high || 0, '老板需要关注', 'text-red-700', 'bg-red-50'],
            ['风险提醒', automation?.summary.category_counts.risk || 0, '不自动停用', 'text-orange-700', 'bg-orange-50'],
            ['闭环任务', automation?.summary.open_task_count || 0, '任务协作处理中', 'text-violet-700', 'bg-violet-50'],
            ['已解决', automation?.summary.resolved || 0, '保留处理结果', 'text-emerald-700', 'bg-emerald-50'],
          ].map(([label, value, hint, color, bg]) => <Card key={String(label)} className="border-slate-200"><CardContent className="p-4"><div className={`inline-flex rounded-lg px-2 py-1 text-xs font-semibold ${color} ${bg}`}>{label}</div><p className="mt-3 text-2xl font-bold text-slate-900">{value}</p><p className="mt-1 text-xs text-slate-400">{hint}</p></CardContent></Card>)}
        </div>

        <Card className="border-slate-200">
          <CardHeader className="gap-3 lg:flex-row lg:items-center lg:justify-between">
            <div><CardTitle className="text-base">问题与任务闭环</CardTitle><p className="mt-1 text-xs text-slate-500">修正数据后问题会自动解决；完成任务必须填写处理结果。</p></div>
            <div className="flex flex-wrap gap-2">
              {isAdmin && visibleIssuesWithoutTask.length > 0 && <Button variant="outline" onClick={() => void createVisibleQualityTasks()} disabled={bulkTaskLoading}>{bulkTaskLoading ? <RefreshCw className="mr-2 h-4 w-4 animate-spin" /> : <ListChecks className="mr-2 h-4 w-4" />}为当前筛选生成任务 ({visibleIssuesWithoutTask.length})</Button>}
              <select value={qualityStatusFilter} onChange={event => changeQualityFilter('qualityStatus', event.target.value)} className="h-10 rounded-md border px-3 text-sm"><option value="active">待处理</option><option value="open">未开始</option><option value="in_progress">处理中</option><option value="resolved">已解决</option><option value="all">全部状态</option></select>
              <select value={qualityCategoryFilter} onChange={event => changeQualityFilter('qualityCategory', event.target.value)} className="h-10 rounded-md border px-3 text-sm"><option value="all">全部分类</option>{Object.entries(qualityCategoryLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select>
            </div>
          </CardHeader>
          <CardContent className="grid gap-3 lg:grid-cols-2">
            {visibleQualityIssues.map(row => <div key={row.id} className={`rounded-xl border p-4 ${row.status === 'resolved' ? 'border-emerald-200 bg-emerald-50/50' : row.severity === 'high' ? 'border-red-200 bg-red-50' : 'border-amber-200 bg-amber-50'}`}>
              <div className="flex items-start justify-between gap-3">
                <div><p className="font-semibold text-slate-900">{row.customer_name}</p><p className="mt-2 text-sm text-slate-700">{row.message}</p>{row.suggested_action && <p className="mt-2 text-xs text-slate-500">建议：{row.suggested_action}</p>}</div>
                <div className="flex shrink-0 flex-col items-end gap-1.5"><Badge variant="outline" className="bg-white/70 text-slate-600">{qualityCategoryLabels[row.category] || row.category}</Badge><Badge className={row.status === 'resolved' ? 'bg-emerald-100 text-emerald-700' : row.severity === 'high' ? 'bg-red-100 text-red-700' : 'bg-amber-100 text-amber-700'}>{row.status === 'resolved' ? '已解决' : row.status === 'in_progress' ? '处理中' : row.severity === 'high' ? '高优先' : '待完善'}</Badge></div>
              </div>
              {row.resolution_note && <div className="mt-3 rounded-lg bg-white/80 px-3 py-2 text-xs text-emerald-700">处理结果：{row.resolution_note}</div>}
              <div className="mt-4 flex flex-wrap gap-2">
                <Button asChild size="sm" variant="outline"><Link to={buildReturnLink(`/customers?detail=${row.customer_id}`, currentDecisionPath(), 'management-decisions')}>打开客户</Link></Button>
                {row.task ? <Button asChild size="sm" variant="outline"><Link to={buildReturnLink(`/tasks?task_id=${row.task.id}&view=system`, currentDecisionPath(), 'management-decisions')}>查看任务{row.task.assignee_name ? ` · ${row.task.assignee_name}` : ''}</Link></Button> : row.status !== 'resolved' && <Button size="sm" variant="outline" onClick={() => void createQualityTask(row.id)} disabled={!isAdmin}><ListChecks className="mr-1 h-3.5 w-3.5" />生成任务</Button>}
              </div>
            </div>)}
            {!loading && visibleQualityIssues.length === 0 && <div className="col-span-full py-12 text-center text-sm text-slate-400">{automation?.last_run ? <><CheckCircle2 className="mx-auto mb-2 h-6 w-6 text-emerald-500" />当前筛选下没有问题</> : '点击“立即扫描”建立首批数据质量记录'}</div>}
          </CardContent>
        </Card>
      </div>}

      {section === 'history' && <Card className="border-slate-200"><CardHeader className="gap-3 lg:flex-row lg:items-center lg:justify-between"><div><CardTitle className="text-base">历史客户一次性补录</CardTitle><p className="mt-1 text-xs text-slate-500">新客户已改为在客户管理首次录入；这里只处理历史资料。</p></div><div className="flex flex-wrap gap-2"><div className="relative"><Search className="absolute left-3 top-2.5 h-4 w-4 text-slate-400" /><Input value={search} onChange={event => setSearch(event.target.value)} placeholder="搜索客户名称或编号" className="w-64 pl-9" /></div><select value={reviewFilter} onChange={event => setReviewFilter(event.target.value)} className="h-10 rounded-md border px-3 text-sm"><option value="pending">待审核</option><option value="needs_follow_up">稍后核对</option><option value="confirmed">已确认</option><option value="all">全部</option></select></div></CardHeader><CardContent className="grid gap-3 lg:grid-cols-2">{visibleItems.map(item => <div key={item.customer_id} className="rounded-2xl border border-slate-200 p-4"><div className="flex items-start justify-between gap-3"><div><p className="font-semibold">{item.customer_name}</p><p className="mt-1 text-xs text-slate-400">{item.customer_code || `客户 #${item.customer_id}`} · {item.industry || '行业待补充'}</p></div><Badge className={item.review_status === 'confirmed' ? 'bg-emerald-100 text-emerald-700' : item.review_status === 'needs_follow_up' ? 'bg-amber-100 text-amber-700' : 'bg-orange-100 text-orange-700'}>{reviewLabels[item.review_status]}</Badge></div><div className="mt-3 flex flex-wrap gap-1.5">{item.suggestions.map(suggestion => <Badge key={suggestion.business_line} variant="outline">建议：{lineLabels[suggestion.business_line]}</Badge>)}{item.projects.map(project => <Badge key={project.id} className="bg-blue-100 text-blue-700">已建：{project.business_line.name}</Badge>)}</div>{item.warnings.length > 0 && <div className="mt-3 rounded-xl bg-orange-50 p-3 text-xs text-orange-700"><p className="font-semibold">{item.warnings.length} 项需要确认</p><p className="mt-1 line-clamp-2">{item.warnings.slice(0, 2).map(row => row.message).join('；')}</p></div>}<div className="mt-4 flex items-center justify-between"><p className="text-xs text-slate-400">客户状态：{item.customer_lifecycle?.status === 'active' ? '合作中' : item.customer_lifecycle?.status || '待确认'}</p><Button size="sm" variant={item.review_status === 'confirmed' ? 'outline' : 'default'} onClick={() => openReview(item)} disabled={!isAdmin}>{item.review_status === 'confirmed' ? '重新核对' : '开始审核'}</Button></div></div>)}{!loading && visibleItems.length === 0 && <div className="col-span-full py-12 text-center text-sm text-slate-400">当前筛选下没有历史客户</div>}</CardContent></Card>}

      <Dialog open={!!reviewing} onOpenChange={open => !open && setReviewing(null)}>
        <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-4xl"><DialogHeader><DialogTitle>{reviewing?.customer_name} · 分类与项目确认</DialogTitle></DialogHeader><div className="space-y-4"><div className="rounded-xl border border-blue-200 bg-blue-50 p-3 text-sm text-blue-800"><strong>客户整体状态保持不变：</strong>当前为 {reviewing?.customer_lifecycle?.status === 'active' ? '合作中' : reviewing?.customer_lifecycle?.status || '待确认'}。这里只确认该客户购买了哪些项目。</div>{reviewing?.warnings.map((warning, index) => <div key={`${warning.code}-${warning.source_id || index}`} className="rounded-lg bg-orange-50 px-3 py-2 text-xs text-orange-700">{warning.message}{warning.source_id ? `（${warning.scope} #${warning.source_id}）` : ''}</div>)}<div className="space-y-3">{projectForms.map((project, index) => <div key={`${project.engagement_id || 'new'}-${index}`} className="rounded-2xl border border-slate-200 p-4"><div className="mb-3 flex items-center justify-between"><p className="font-semibold">项目 {index + 1}</p><Button size="sm" variant="ghost" className="text-red-600" onClick={() => setProjectForms(rows => rows.filter((_row, rowIndex) => rowIndex !== index))} disabled={projectForms.length <= 1}>移除</Button></div><div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4"><div><Label>业务板块 *</Label><select value={project.business_line_code} onChange={event => updateProjectForm(index, { business_line_code: event.target.value })} className="mt-1 h-10 w-full rounded-md border border-slate-200 bg-white px-3 text-sm">{Object.entries(lineLabels).map(([code, label]) => <option key={code} value={code}>{label}</option>)}</select></div><div><Label>项目状态 *</Label><select value={project.status} onChange={event => updateProjectForm(index, { status: event.target.value })} className="mt-1 h-10 w-full rounded-md border border-slate-200 bg-white px-3 text-sm">{Object.entries(projectStatusLabels).map(([code, label]) => <option key={code} value={code}>{label}</option>)}</select></div><div><Label>开始日期 *</Label><Input type="date" value={project.paid_started_at} max={today} onChange={event => updateProjectForm(index, { paid_started_at: event.target.value })} className="mt-1" /></div><div><Label>结束日期</Label><Input type="date" value={project.stopped_at} max={today} onChange={event => updateProjectForm(index, { stopped_at: event.target.value })} className="mt-1" /></div><div><Label>收费周期</Label><select value={project.billing_cycle} onChange={event => updateProjectForm(index, { billing_cycle: event.target.value })} className="mt-1 h-10 w-full rounded-md border border-slate-200 bg-white px-3 text-sm"><option value="">待确认</option><option value="monthly">月付</option><option value="quarterly">季付</option><option value="annual">年付</option><option value="one_time">一次性</option></select></div><div><Label>收款方式</Label><select value={project.collection_method} onChange={event => updateProjectForm(index, { collection_method: event.target.value })} className="mt-1 h-10 w-full rounded-md border border-slate-200 bg-white px-3 text-sm">{Object.entries(collectionLabels).map(([code, label]) => <option key={code} value={code}>{label}</option>)}</select></div><div><Label>币种</Label><Input value={project.currency} maxLength={3} onChange={event => updateProjectForm(index, { currency: event.target.value.toUpperCase() })} className="mt-1" /></div><div><Label>产品名称</Label><Input value={project.product_name} onChange={event => updateProjectForm(index, { product_name: event.target.value })} className="mt-1" /></div></div><p className="mt-3 text-xs text-slate-400">关联收款 {project.source_payment_ids.length} 笔 · 关联订阅 {project.source_subscription_ids.length} 条</p></div>)}</div><Button variant="outline" onClick={() => setProjectForms(rows => [...rows, suggestionToForm({ business_line: 'managed_service', product_code: 'managed_service_legacy', product_name: '代运营历史套餐', currency: 'USD', source_payment_ids: [], source_subscription_ids: [], basis: [] })])}><Layers3 className="mr-2 h-4 w-4" />增加一个项目</Button><div><Label>审核备注</Label><Textarea value={reviewNote} onChange={event => setReviewNote(event.target.value)} rows={3} className="mt-1" placeholder="记录为什么这样分类，方便以后复盘" /></div></div><DialogFooter className="gap-2"><Button variant="outline" onClick={() => void saveReview('needs_follow_up')} disabled={saving}>资料不足，稍后核对</Button><Button onClick={() => void saveReview('confirmed')} disabled={saving}>{saving ? '保存中…' : '确认分类并建立项目'}</Button></DialogFooter></DialogContent>
      </Dialog>

      <Dialog open={!!statusProject} onOpenChange={open => !open && setStatusProject(null)}>
        <DialogContent className="sm:max-w-lg"><DialogHeader><DialogTitle>更改项目状态</DialogTitle></DialogHeader><div className="space-y-4"><div className="rounded-xl bg-slate-50 p-3 text-sm"><p className="font-semibold">{statusProject?.customer_name}</p><p className="mt-1 text-xs text-slate-500">{statusProject?.business_line.name} · 只更改项目，不更改客户整体合作状态</p></div><div><Label>项目状态</Label><select value={nextStatus} onChange={event => setNextStatus(event.target.value)} className="mt-1 h-10 w-full rounded-md border border-slate-200 bg-white px-3 text-sm">{Object.entries(projectStatusLabels).map(([code, label]) => <option key={code} value={code}>{label}</option>)}</select></div><div><Label>生效日期</Label><Input type="date" value={statusDate} max={today} onChange={event => setStatusDate(event.target.value)} className="mt-1" /></div><div><Label>原因与备注</Label><Textarea value={statusReason} onChange={event => setStatusReason(event.target.value)} rows={3} className="mt-1" /></div></div><DialogFooter><Button variant="outline" onClick={() => setStatusProject(null)}>取消</Button><Button onClick={() => void saveStatus()} disabled={saving}>{saving ? '保存中…' : '确认更新'}</Button></DialogFooter></DialogContent>
      </Dialog>
    </div>
  );
}
