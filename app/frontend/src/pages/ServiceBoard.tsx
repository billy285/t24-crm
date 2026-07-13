import { useState, useEffect, useMemo, useRef, useCallback } from 'react';
import { invokeWithAuth } from '../lib/tokenStore';
import { useRole } from '../lib/role-context';
import { decorateEffectiveSubscriptions } from '../lib/subscription-utils';
import { getCountryLabel, getStateLabel } from '../lib/country-state-data';
import { logOperation } from '../lib/operation-log-helper';
import {
  serviceTypeLabels, allStageLabels, getStagesForType, getDefaultProgress,
  isStageValidForType, getFirstStageForType, kanbanColumns,
  issueStatusLabels, issueStatusColors, taskStatusLabels, taskStatusColors,
  priorityLabels, priorityColors, taskTypeLabels, industryLabels, countryDisplayLabels,
  quickFilterLabels, type QuickFilter,
} from '../lib/service-board-config';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Textarea } from '@/components/ui/textarea';
import { NativeSelect } from '@/components/ui/native-select';
import { toast } from 'sonner';
import {
  Search, Plus, Edit, Trash2, ArrowLeft, LayoutList, Kanban, Users,
  AlertTriangle, Clock, CheckCircle2, XCircle, BarChart3, Filter, RefreshCw, Info,
  ChevronRight, Copy, FileImage, Sparkles, ShieldCheck, ClipboardCheck,
} from 'lucide-react';
import ConfirmDialog from '@/components/ConfirmDialog';
import ExportButton from '@/components/ExportButton';
import { buildBusinessDicts, inferPackagePlatforms, platformLabels as configuredPlatformLabels } from '../lib/dict-config';
import { useAutoRefresh } from '../lib/use-auto-refresh';

// ==================== Types ====================
interface ServiceProgress {
  id: number;
  customer_id: number;
  customer_name: string;
  service_type: string;
  service_stage: string;
  progress_percent: number;
  sales_person: string;
  ops_person: string;
  design_person: string;
  package_name: string;
  package_platforms: string;
  industry: string;
  country: string;
  state: string;
  city: string;
  service_start_date: string;
  service_end_date: string;
  last_update_time: string;
  last_update_person: string;
  last_work_summary: string;
  issue_status: string;
  issue_description: string;
  issue_found_date: string;
  issue_owner: string;
  issue_resolved: boolean;
  issue_resolved_date: string;
  notes: string;
  created_at: string;
}

interface ServiceTask {
  id: number;
  service_progress_id: number;
  customer_id: number;
  customer_name: string;
  task_name: string;
  task_type: string;
  platform?: string;
  assignee_name: string;
  priority: string;
  status: string;
  due_date: string;
  completed_date: string;
  completed_at?: string;
  completed_by?: string;
  selected_copy_id?: number | null;
  selected_copy_title?: string | null;
  selected_material_id?: number | null;
  selected_material_title?: string | null;
  completion_quality?: string | null;
  completion_note?: string | null;
  notes: string;
  created_at: string;
}

interface CustomerRecord {
  id: number;
  customer_code: string;
  business_name: string;
  contact_name: string;
  phone: string;
  industry: string;
  country: string;
  state: string;
  city: string;
  sales_person: string;
  status: string;
  [key: string]: unknown;
}

interface EmployeeRecord {
  id: number;
  name: string;
  role: string;
  department: string;
  status: string;
  [key: string]: unknown;
}

interface SubscriptionRecord {
  id: number;
  customer_id: number;
  package_name: string;
  product_type: string;
  start_date: string;
  end_date: string;
  status: string;
  [key: string]: unknown;
}

interface CustomerAiCopyRecord {
  id: number;
  title: string;
  platform: string;
  content_type: string;
  content: string;
  status: string;
  updated_at?: string;
  created_at?: string;
}

interface CustomerMaterialRecord {
  id: number;
  title: string;
  material_type: string;
  platform: string;
  usage_status: string;
  approval_status: string;
  file_name?: string;
  file_url?: string;
  updated_at?: string;
  created_at?: string;
}

// ==================== Helpers ====================
const todayStr = () => new Date().toISOString().slice(0, 10);
const SERVICE_EXPIRY_WARNING_DAYS = 7;
const getServiceRemainingDays = (sp: Pick<ServiceProgress, 'service_end_date'>) => {
  if (!sp.service_end_date) return null;
  const end = new Date(sp.service_end_date);
  if (Number.isNaN(end.getTime())) return null;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return Math.ceil((end.getTime() - today.getTime()) / 86400000);
};
const isOverdue = (sp: ServiceProgress) => {
  const remainDays = getServiceRemainingDays(sp);
  return remainDays !== null && remainDays <= 0 && sp.service_stage !== 'ended';
};
const isExpiringSoon = (sp: ServiceProgress) => {
  const remainDays = getServiceRemainingDays(sp);
  return remainDays !== null && remainDays > 0 && remainDays <= SERVICE_EXPIRY_WARNING_DAYS;
};
const isUpdatedThisWeek = (sp: ServiceProgress) => {
  if (!sp.last_update_time) return false;
  const d = new Date(sp.last_update_time);
  const now = new Date();
  return (now.getTime() - d.getTime()) / (1000 * 60 * 60 * 24) <= 7;
};
const isLongNoUpdate = (sp: ServiceProgress) => {
  if (!sp.last_update_time) return true;
  const d = new Date(sp.last_update_time);
  const now = new Date();
  return (now.getTime() - d.getTime()) / (1000 * 60 * 60 * 24) > 14;
};
const hasIssue = (sp: ServiceProgress) => sp.issue_status !== 'none' && !sp.issue_resolved;
const isWaitingForClientMaterial = (sp: ServiceProgress) => (
  !sp.issue_resolved && ['waiting_client', 'waiting_material'].includes(sp.issue_status)
);

const displayCountry = (code: string) => countryDisplayLabels[code] || code;
const normalizeText = (value?: string | null) => (value || '').toLowerCase().replace(/\s+/g, '');
const parseMultiValue = (value?: string | null) => (value || '').split(',').map(item => item.trim()).filter(Boolean);
const getPackagePlatformContext = () => {
  const dicts = buildBusinessDicts();
  return {
    labels: dicts.customerPackages,
    platforms: dicts.customerPackagePlatforms,
  };
};
const getWeekStartStr = () => {
  const date = new Date();
  date.setHours(0, 0, 0, 0);
  const day = date.getDay() || 7;
  date.setDate(date.getDate() - day + 1);
  return date.toISOString().slice(0, 10);
};
const getWeekEndStr = () => {
  const date = new Date();
  date.setHours(0, 0, 0, 0);
  const day = date.getDay() || 7;
  date.setDate(date.getDate() - day + 7);
  return date.toISOString().slice(0, 10);
};
const getTaskDoneDate = (task: Pick<ServiceTask, 'completed_at' | 'completed_date'>) => (
  (task.completed_at || task.completed_date || '').slice(0, 10)
);
const isTaskCompletedThisWeek = (task: ServiceTask, weekStart = getWeekStartStr()) => (
  task.status === 'completed' && Boolean(getTaskDoneDate(task)) && getTaskDoneDate(task) >= weekStart
);
const isWeeklyReportTask = (task: ServiceTask) => {
  const text = normalizeText(`${task.task_type || ''}${task.task_name || ''}${task.notes || ''}${task.completion_note || ''}`);
  return task.task_type === 'submit_report' || text.includes('周报') || text.includes('总结') || text.includes('汇报') || text.includes('report');
};
const isOpenTaskThisWeek = (task: ServiceTask, weekStart = getWeekStartStr(), weekEnd = getWeekEndStr()) => {
  if (task.status === 'completed' || task.status === 'cancelled') return false;
  const dueDate = (task.due_date || '').slice(0, 10);
  return Boolean(dueDate) && dueDate >= weekStart && dueDate <= weekEnd;
};
const inferPlatformsFromProgress = (sp?: Pick<ServiceProgress, 'package_name' | 'package_platforms'> | null) => {
  const savedPlatforms = parseMultiValue(sp?.package_platforms);
  if (savedPlatforms.length > 0) return savedPlatforms;
  const context = getPackagePlatformContext();
  return inferPackagePlatforms(sp?.package_name, context.labels, context.platforms);
};

const getWeeklyTaskPlan = (sp: ServiceProgress, tasks: ServiceTask[]) => {
  const platforms = inferPlatformsFromProgress(sp);
  const weekStart = getWeekStartStr();
  const weekEnd = getWeekEndStr();
  const completedThisWeek = tasks.filter(task => task.service_progress_id === sp.id && isTaskCompletedThisWeek(task, weekStart));
  const openThisWeek = tasks.filter(task => task.service_progress_id === sp.id && isOpenTaskThisWeek(task, weekStart, weekEnd));
  const platformPlans = platforms.map(platform => {
    const completed = completedThisWeek.filter(task => task.platform === platform).length;
    const scheduled = openThisWeek.filter(task => task.platform === platform && !isWeeklyReportTask(task)).length;
    return {
      platform,
      completed,
      scheduled,
      target: WEEKLY_PLATFORM_UPDATE_TARGET,
      remainingToDo: Math.max(0, WEEKLY_PLATFORM_UPDATE_TARGET - completed),
      remainingToCreate: Math.max(0, WEEKLY_PLATFORM_UPDATE_TARGET - completed - scheduled),
    };
  });
  const reportCompleted = completedThisWeek.some(isWeeklyReportTask);
  const reportScheduled = openThisWeek.some(isWeeklyReportTask);
  return {
    platforms,
    platformPlans,
    reportCompleted,
    reportScheduled,
    reportRemainingToDo: reportCompleted ? 0 : 1,
    reportRemainingToCreate: reportCompleted || reportScheduled ? 0 : 1,
    totalRemainingToDo: platformPlans.reduce((sum, item) => sum + item.remainingToDo, 0) + (reportCompleted ? 0 : 1),
    totalRemainingToCreate: platformPlans.reduce((sum, item) => sum + item.remainingToCreate, 0) + (reportCompleted || reportScheduled ? 0 : 1),
  };
};
const getWeeklyPlatformProgress = (sp: ServiceProgress, tasks: ServiceTask[]) => {
  const platforms = inferPlatformsFromProgress(sp);
  const weekStart = getWeekStartStr();
  const relevantTasks = tasks.filter(task => task.service_progress_id === sp.id && isTaskCompletedThisWeek(task, weekStart));
  const counts = platforms.reduce<Record<string, number>>((acc, platform) => {
    acc[platform] = relevantTasks.filter(task => task.platform === platform).length;
    return acc;
  }, {});
  const platformTarget = platforms.length * WEEKLY_PLATFORM_UPDATE_TARGET;
  const platformDone = platforms.reduce((sum, platform) => sum + Math.min(counts[platform] || 0, WEEKLY_PLATFORM_UPDATE_TARGET), 0);
  const missingPlatforms = platforms.filter(platform => (counts[platform] || 0) < WEEKLY_PLATFORM_UPDATE_TARGET);
  const weeklyReportDone = relevantTasks.some(isWeeklyReportTask) ? 1 : 0;
  return {
    platforms,
    counts,
    platformTarget,
    platformDone,
    missingPlatforms,
    weeklyReportDone,
    weeklyReportTarget: platforms.length > 0 ? WEEKLY_REPORT_TARGET : 0,
  };
};

const onboardingStepRules: Array<{
  key: string;
  label: string;
  match: (task: ServiceTask) => boolean;
}> = [
  {
    key: 'group',
    label: '拉群建群',
    match: task => task.task_type === 'setup_group' || /服务群|拉群|建群/.test(task.task_name || ''),
  },
  {
    key: 'brief',
    label: '运营说明',
    match: task => task.task_type === 'confirm_service' || /运营说明|素材清单|服务内容/.test(task.task_name || ''),
  },
  {
    key: 'permission',
    label: '权限对接',
    match: task => ['bind_google', 'open_facebook', 'open_instagram'].includes(task.task_type || '') || /权限|账号/.test(task.task_name || ''),
  },
  {
    key: 'profile',
    label: '资料完善',
    match: task => task.task_type === 'update_info' || /基础信息|资料完善|主页资料|店铺资料/.test(task.task_name || ''),
  },
  {
    key: 'launch',
    label: '正式运营',
    match: task => task.task_type === 'publish_content' && /正式运营启动|运营启动/.test(task.task_name || ''),
  },
  {
    key: 'first_report',
    label: '首周汇报',
    match: task => task.task_type === 'submit_report' && /首周|总结|汇报/.test(task.task_name || ''),
  },
];

const getOnboardingProgress = (sp: ServiceProgress, tasks: ServiceTask[]) => {
  const progressTasks = tasks.filter(task => task.service_progress_id === sp.id);
  const steps = onboardingStepRules.map(rule => {
    const matchedTasks = progressTasks.filter(rule.match);
    const completedTask = matchedTasks.find(task => task.status === 'completed');
    const activeTask = matchedTasks.find(task => task.status !== 'completed' && task.status !== 'cancelled');
    return {
      key: rule.key,
      label: rule.label,
      task: completedTask || activeTask || null,
      status: completedTask ? 'completed' : activeTask ? activeTask.status : 'missing',
    };
  });
  const existingSteps = steps.filter(step => step.task);
  const total = existingSteps.length;
  const completed = existingSteps.filter(step => step.status === 'completed').length;
  const nextStep = steps.find(step => step.status !== 'completed' && step.task) || null;
  return { steps, total, completed, nextStep, isComplete: total > 0 && completed >= total };
};
const getErrorMessage = (err: unknown, fallback: string) => {
  if (err instanceof Error) return err.message;
  if (typeof err === 'object' && err !== null) {
    const anyErr = err as any;
    return anyErr?.data?.detail || anyErr?.response?.data?.detail || anyErr?.message || fallback;
  }
  return fallback;
};

type EntityQueryParams = {
  query?: Record<string, unknown>;
  sort?: string;
  skip?: number;
  limit?: number;
  fields?: string;
};

const buildEntityQueryData = (params: EntityQueryParams = {}) => {
  const data: Record<string, unknown> = {};
  if (params.query) data.query = JSON.stringify(params.query);
  if (params.sort) data.sort = params.sort;
  if (typeof params.skip === 'number') data.skip = params.skip;
  if (typeof params.limit === 'number') data.limit = params.limit;
  if (params.fields) data.fields = params.fields;
  return data;
};

const authedListEntity = async <T,>(entity: string, params: EntityQueryParams = {}): Promise<T[]> => {
  const res = await invokeWithAuth({
    url: `/api/v1/entities/${entity}/all`,
    method: 'GET',
    data: buildEntityQueryData(params),
  });
  return (res?.data?.items || []) as T[];
};

const authedGetEntity = async <T,>(entity: string, id: number | string): Promise<T | null> => {
  const res = await invokeWithAuth({
    url: `/api/v1/entities/${entity}/${id}`,
    method: 'GET',
  });
  return (res?.data || null) as T | null;
};

const authedCreateEntity = async <T,>(entity: string, data: Record<string, unknown>): Promise<T | null> => {
  const res = await invokeWithAuth({
    url: `/api/v1/entities/${entity}`,
    method: 'POST',
    data,
  });
  return (res?.data || null) as T | null;
};

const authedUpdateEntity = async <T,>(entity: string, id: number | string, data: Record<string, unknown>): Promise<T | null> => {
  const res = await invokeWithAuth({
    url: `/api/v1/entities/${entity}/${id}`,
    method: 'PUT',
    data,
  });
  return (res?.data || null) as T | null;
};

const authedDeleteEntity = async (entity: string, id: number | string) => {
  await invokeWithAuth({
    url: `/api/v1/entities/${entity}/${id}`,
    method: 'DELETE',
  });
};

// Product type to service type mapping
const productToServiceType: Record<string, string> = {
  social_media: 'social_media',
  website: 'website',
  ordering_system: 'ordering_system',
  ads: 'ads',
  combo: 'other',
};

const platformLabels: Record<string, string> = {
  general: '通用',
  ...configuredPlatformLabels,
  website: '网站',
  other: '其他',
};

const materialTypeLabels: Record<string, string> = {
  image: '图片',
  video: '视频',
  logo: 'Logo',
  menu: '菜单',
  screenshot: '截图',
  document: '文档',
  design: '设计稿',
  post: '发布素材',
  other: '其他',
};

const copyTypeLabels: Record<string, string> = {
  business_intro: '商家介绍',
  promotion: '活动推广',
  holiday: '节日营销',
  review_reply: '评论回复',
  weekly_update: '每周更新',
  package_promo: '套餐宣传',
};

const qualityLabels: Record<string, string> = {
  standard: '标准完成',
  low_quality: '低质量完成',
};

const qualityColors: Record<string, string> = {
  standard: 'bg-green-100 text-green-700',
  low_quality: 'bg-orange-100 text-orange-700',
};

const WEEKLY_PLATFORM_UPDATE_TARGET = 3;
const WEEKLY_REPORT_TARGET = 1;
const CONTENT_REFERENCE_REQUIRED_TASK_TYPES = new Set(['publish_content', 'reply_comments', 'submit_report']);
const PAGE_SIZE_OPTIONS = [20, 50, 100];

function paginateList<T>(items: T[], page: number, pageSize: number) {
  const totalPages = Math.max(1, Math.ceil(items.length / pageSize));
  const safePage = Math.min(Math.max(page, 1), totalPages);
  const start = (safePage - 1) * pageSize;
  return {
    items: items.slice(start, start + pageSize),
    page: safePage,
    totalPages,
    start: items.length === 0 ? 0 : start + 1,
    end: Math.min(start + pageSize, items.length),
  };
}

// Get next stage for a given service type and current stage
function getNextStage(serviceType: string, currentStage: string): string | null {
  const stages = getStagesForType(serviceType);
  const keys = Object.keys(stages);
  const idx = keys.indexOf(currentStage);
  if (idx >= 0 && idx < keys.length - 1) {
    return keys[idx + 1];
  }
  return null;
}

const requiresCompletionReference = (task?: Pick<ServiceTask, 'task_type'> | null) => (
  CONTENT_REFERENCE_REQUIRED_TASK_TYPES.has(task?.task_type || '')
);

// ==================== Main Component ====================
export default function ServiceBoard() {
  const { role, employee, isAdmin, dataScope, hasPermission } = useRole();

  // Core data
  const [progresses, setProgresses] = useState<ServiceProgress[]>([]);
  const [allTasks, setAllTasks] = useState<ServiceTask[]>([]);
  const [loading, setLoading] = useState(true);

  // Reference data for smart form
  const [allCustomers, setAllCustomers] = useState<CustomerRecord[]>([]);
  const [allEmployees, setAllEmployees] = useState<EmployeeRecord[]>([]);
  const [allSubscriptions, setAllSubscriptions] = useState<SubscriptionRecord[]>([]);

  // Views
  const [viewMode, setViewMode] = useState<'list' | 'kanban' | 'employee'>('list');
  const [quickFilter, setQuickFilter] = useState<QuickFilter>('all');
  const [search, setSearch] = useState('');
  const [showFilters, setShowFilters] = useState(false);
  const [filters, setFilters] = useState({ industry: 'all', service_type: 'all', service_stage: 'all', ops_person: '', sales_person: '', issue_status: 'all' });
  const [progressPage, setProgressPage] = useState(1);
  const [progressPageSize, setProgressPageSize] = useState(20);
  const [showStats, setShowStats] = useState(true);

  // Detail
  const [selectedProgress, setSelectedProgress] = useState<ServiceProgress | null>(null);
  const [detailTasks, setDetailTasks] = useState<ServiceTask[]>([]);
  const [detailTab, setDetailTab] = useState('overview');

  // Progress Form
  const [showProgressForm, setShowProgressForm] = useState(false);
  const [editingProgressId, setEditingProgressId] = useState<number | null>(null);
  const [progressForm, setProgressForm] = useState(emptyProgressForm());
  const [savingProgress, setSavingProgress] = useState(false);
  const [customerSearch, setCustomerSearch] = useState('');
  const [showCustomerDropdown, setShowCustomerDropdown] = useState(false);
  const [selectedCustomer, setSelectedCustomerState] = useState<CustomerRecord | null>(null);
  const customerDropdownRef = useRef<HTMLDivElement>(null);

  // Task Form
  const [showTaskForm, setShowTaskForm] = useState(false);
  const [editingTaskId, setEditingTaskId] = useState<number | null>(null);
  const [taskForm, setTaskForm] = useState(emptyTaskForm());
  const [savingTask, setSavingTask] = useState(false);
  const [generatingWeeklyTasks, setGeneratingWeeklyTasks] = useState(false);

  // Quick update work summary dialog
  const [showQuickUpdate, setShowQuickUpdate] = useState(false);
  const [quickUpdateSp, setQuickUpdateSp] = useState<ServiceProgress | null>(null);
  const [quickUpdateSummary, setQuickUpdateSummary] = useState('');
  const [savingQuickUpdate, setSavingQuickUpdate] = useState(false);

  // Complete task dialog with lightweight operations supervision
  const [completeTaskTarget, setCompleteTaskTarget] = useState<ServiceTask | null>(null);
  const [completionCopies, setCompletionCopies] = useState<CustomerAiCopyRecord[]>([]);
  const [completionMaterials, setCompletionMaterials] = useState<CustomerMaterialRecord[]>([]);
  const [completionForm, setCompletionForm] = useState({ platform: '', selected_copy_id: '', selected_material_id: '', completion_note: '' });
  const [loadingCompletionRefs, setLoadingCompletionRefs] = useState(false);
  const [savingCompletion, setSavingCompletion] = useState(false);
  const [savingTaskActionId, setSavingTaskActionId] = useState<number | null>(null);

  const [deleteTarget, setDeleteTarget] = useState<{ type: 'progress' | 'task'; item: any } | null>(null);
  const [deleting, setDeleting] = useState(false);

  // ==================== Data Loading ====================
  useEffect(() => { loadData(); }, []);

  const loadData = async () => {
    try {
      const [progressItems, taskItems, customerItems, employeeItems, subscriptionItems] = await Promise.all([
        authedListEntity<ServiceProgress>('service_progresses', { limit: 1000, sort: '-last_update_time' }),
        authedListEntity<ServiceTask>('service_tasks', { limit: 1000, sort: '-created_at' }),
        authedListEntity<CustomerRecord>('customers', { limit: 1000, sort: '-created_at' }),
        authedListEntity<EmployeeRecord>('employees', { limit: 200, sort: 'name' }),
        authedListEntity<SubscriptionRecord>('subscriptions', { limit: 1000, sort: '-created_at' }),
      ]);
      let items = progressItems;
      if (dataScope === 'self' && employee) {
        items = items.filter((p: ServiceProgress) =>
          p.ops_person === employee.name || p.sales_person === employee.name || p.design_person === employee.name
        );
      }
      setProgresses(items);
      setAllTasks(taskItems);
      setAllCustomers(customerItems);
      setAllEmployees(employeeItems);
      setAllSubscriptions(decorateEffectiveSubscriptions(subscriptionItems));
    } catch (err) {
      console.error(err);
      toast.error(getErrorMessage(err, '加载数据失败'));
    } finally {
      setLoading(false);
    }
  };

  useAutoRefresh(loadData, {
    intervalMs: 30000,
    enabled: !showProgressForm && !showTaskForm && !showQuickUpdate && !completeTaskTarget,
  });

  // ==================== Derived employee lists ====================
  const activeEmployees = useMemo(() => allEmployees.filter(e => e.status === 'active' || e.status === 'probation'), [allEmployees]);
  const opsEmployees = useMemo(() => activeEmployees.filter(e => e.role === 'ops' || e.department === 'operations' || e.role === 'admin' || e.role === 'super_admin'), [activeEmployees]);
  const designEmployees = useMemo(() => activeEmployees.filter(e => e.role === 'design' || e.department === 'design' || e.role === 'admin' || e.role === 'super_admin'), [activeEmployees]);
  const salesEmployees = useMemo(() => activeEmployees.filter(e => e.role === 'sales' || e.department === 'sales' || e.role === 'admin' || e.role === 'super_admin'), [activeEmployees]);

  // ==================== Customer search for smart form ====================
  const filteredCustomers = useMemo(() => {
    if (!customerSearch.trim()) return allCustomers.slice(0, 20);
    const q = customerSearch.toLowerCase().trim();
    return allCustomers.filter(c =>
      (c.business_name || '').toLowerCase().includes(q) ||
      (c.customer_code || '').toLowerCase().includes(q) ||
      (c.contact_name || '').toLowerCase().includes(q) ||
      (c.phone || '').includes(q) ||
      String(c.id).includes(q)
    ).slice(0, 20);
  }, [allCustomers, customerSearch]);

  // Close dropdown on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (customerDropdownRef.current && !customerDropdownRef.current.contains(e.target as Node)) {
        setShowCustomerDropdown(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  // ==================== Smart form: select customer and auto-populate ====================
  const handleSelectCustomer = (c: CustomerRecord) => {
    setSelectedCustomerState(c);
    setCustomerSearch(c.business_name);
    setShowCustomerDropdown(false);

    const activeSub = allSubscriptions.find(s => s.customer_id === c.id && (s.status === 'active' || s.status === 'expiring_soon'));
    const anySub = allSubscriptions.find(s => s.customer_id === c.id);
    const sub = activeSub || anySub;

    const serviceType = sub?.product_type ? (productToServiceType[sub.product_type] || 'other') : progressForm.service_type;
    const existingProgress = progresses.find(p => p.customer_id === c.id);
    const currentStageValid = isStageValidForType(serviceType, progressForm.service_stage);
    const newStage = currentStageValid ? progressForm.service_stage : getFirstStageForType(serviceType);
    const defaultProg = getDefaultProgress(serviceType, newStage);

    setProgressForm(prev => ({
      ...prev,
      customer_id: c.id,
      customer_name: c.business_name,
      industry: c.industry || prev.industry,
      country: c.country || prev.country,
      state: c.state || prev.state,
      city: c.city || prev.city,
      sales_person: c.sales_person || prev.sales_person,
      ops_person: existingProgress?.ops_person || prev.ops_person,
      design_person: existingProgress?.design_person || prev.design_person,
      package_name: sub?.package_name || prev.package_name,
      package_platforms: sub?.package_name
        ? inferPackagePlatforms(sub.package_name, getPackagePlatformContext().labels, getPackagePlatformContext().platforms).join(',')
        : prev.package_platforms,
      service_type: serviceType,
      service_stage: newStage,
      progress_percent: defaultProg >= 0 ? defaultProg : prev.progress_percent,
      service_start_date: sub?.start_date?.slice(0, 10) || prev.service_start_date,
      service_end_date: sub?.end_date?.slice(0, 10) || prev.service_end_date,
    }));
  };

  // ==================== Filtering ====================
  const filtered = useMemo(() => {
    return progresses.filter(sp => {
      if (quickFilter === 'today_pending') {
        const tasks = allTasks.filter(t => t.service_progress_id === sp.id && t.status !== 'completed' && t.status !== 'cancelled' && t.due_date && t.due_date <= todayStr());
        if (tasks.length === 0) return false;
      }
      if (quickFilter === 'overdue' && !isOverdue(sp)) return false;
      if (quickFilter === 'has_issue' && !hasIssue(sp)) return false;
      if (quickFilter === 'waiting_client' && sp.issue_status !== 'waiting_client' && sp.issue_status !== 'waiting_material') return false;
      if (quickFilter === 'expiring_soon' && !isExpiringSoon(sp)) return false;
      if (quickFilter === 'updated_this_week' && !isUpdatedThisWeek(sp)) return false;
      if (quickFilter === 'long_no_update' && !isLongNoUpdate(sp)) return false;

      if (search) {
        const q = search.toLowerCase();
        const match = [sp.customer_name, sp.sales_person, sp.ops_person, sp.design_person, sp.city, sp.package_name]
          .some(f => (f || '').toLowerCase().includes(q));
        if (!match) return false;
      }

      if (filters.industry !== 'all' && sp.industry !== filters.industry) return false;
      if (filters.service_type !== 'all' && sp.service_type !== filters.service_type) return false;
      if (filters.service_stage !== 'all' && sp.service_stage !== filters.service_stage) return false;
      if (filters.ops_person && !sp.ops_person?.toLowerCase().includes(filters.ops_person.toLowerCase())) return false;
      if (filters.sales_person && !sp.sales_person?.toLowerCase().includes(filters.sales_person.toLowerCase())) return false;
      if (filters.issue_status !== 'all' && sp.issue_status !== filters.issue_status) return false;

      return true;
    });
  }, [progresses, allTasks, quickFilter, search, filters]);

  const paginatedProgresses = useMemo(
    () => paginateList(filtered, progressPage, progressPageSize),
    [filtered, progressPage, progressPageSize],
  );

  useEffect(() => {
    setProgressPage(1);
  }, [search, quickFilter, filters, progressPageSize]);

  // ==================== Stats ====================
  const stats = useMemo(() => {
    const total = progresses.length;
    const active = progresses.filter(p => !['ended', 'paused'].includes(p.service_stage)).length;
    const withIssue = progresses.filter(p => hasIssue(p)).length;
    const overdueCount = progresses.filter(p => isOverdue(p)).length;
    const updatedWeek = progresses.filter(p => isUpdatedThisWeek(p)).length;
    const longNoUpd = progresses.filter(p => isLongNoUpdate(p)).length;
    const expiring = progresses.filter(p => isExpiringSoon(p)).length;
    const visibleProgressIds = new Set(progresses.map(p => p.id));
    const scopedTasks = allTasks.filter(t => !t.service_progress_id || visibleProgressIds.has(t.service_progress_id));
    const weeklyPlatformRows = progresses.map(p => getWeeklyPlatformProgress(p, scopedTasks));
    const weeklyPlatformTarget = weeklyPlatformRows.reduce((sum, item) => sum + item.platformTarget, 0);
    const weeklyPlatformDone = weeklyPlatformRows.reduce((sum, item) => sum + item.platformDone, 0);
    const weeklyMissingPlatforms = weeklyPlatformRows.reduce((sum, item) => sum + item.missingPlatforms.length, 0);
    const weeklyReportTarget = weeklyPlatformRows.reduce((sum, item) => sum + item.weeklyReportTarget, 0);
    const weeklyReportDone = weeklyPlatformRows.reduce((sum, item) => sum + item.weeklyReportDone, 0);
    const weeklyMissingReports = Math.max(0, weeklyReportTarget - weeklyReportDone);

    const taskTotal = scopedTasks.filter(t => t.status !== 'cancelled').length;
    const taskCompleted = scopedTasks.filter(t => t.status === 'completed').length;
    const taskPending = scopedTasks.filter(t => t.status !== 'completed' && t.status !== 'cancelled').length;
    const taskOverdue = scopedTasks.filter(t => t.due_date && t.due_date < todayStr() && t.status !== 'completed' && t.status !== 'cancelled').length;
    const lowQualityCompleted = scopedTasks.filter(t => t.status === 'completed' && t.completion_quality === 'low_quality').length;
    const completionRate = taskTotal > 0 ? Math.round((taskCompleted / taskTotal) * 100) : 100;
    const healthScore = Math.max(0, Math.min(100, completionRate - lowQualityCompleted * 4 - taskOverdue * 5 - longNoUpd * 3 - withIssue * 4 - weeklyMissingPlatforms * 2 - weeklyMissingReports * 3));

    const opsMap: Record<string, { total: number; pending: number; issues: number; completed: number; lowQuality: number }> = {};
    progresses.forEach(p => {
      if (p.ops_person) {
        if (!opsMap[p.ops_person]) opsMap[p.ops_person] = { total: 0, pending: 0, issues: 0, completed: 0, lowQuality: 0 };
        opsMap[p.ops_person].total++;
        if (hasIssue(p)) opsMap[p.ops_person].issues++;
      }
    });
    scopedTasks.forEach(t => {
      if (t.assignee_name) {
        if (!opsMap[t.assignee_name]) opsMap[t.assignee_name] = { total: 0, pending: 0, issues: 0, completed: 0, lowQuality: 0 };
      }
      if (t.assignee_name && t.status !== 'completed' && t.status !== 'cancelled') {
        opsMap[t.assignee_name].pending++;
      }
      if (t.assignee_name && t.status === 'completed') {
        opsMap[t.assignee_name].completed++;
        if (t.completion_quality === 'low_quality') opsMap[t.assignee_name].lowQuality++;
      }
    });

    return {
      total, active, withIssue, overdueCount, updatedWeek, longNoUpd, expiring,
      taskTotal, taskCompleted, taskPending, taskOverdue, lowQualityCompleted, completionRate, healthScore, opsMap,
      weeklyPlatformTarget, weeklyPlatformDone, weeklyMissingPlatforms, weeklyReportTarget, weeklyReportDone, weeklyMissingReports,
    };
  }, [progresses, allTasks]);

  const weeklyActionItems = useMemo(() => (
    progresses
      .filter(sp => !['ended', 'paused'].includes(sp.service_stage))
      .map(sp => ({ sp, plan: getWeeklyTaskPlan(sp, allTasks) }))
      .filter(item => item.plan.platforms.length > 0 && item.plan.totalRemainingToDo > 0)
      .sort((a, b) => b.plan.totalRemainingToDo - a.plan.totalRemainingToDo)
  ), [progresses, allTasks]);

  const filteredWeeklyActionItems = useMemo(() => {
    const visibleIds = new Set(filtered.map(sp => sp.id));
    return weeklyActionItems.filter(item => visibleIds.has(item.sp.id));
  }, [weeklyActionItems, filtered]);

  const selectedCompletionCopy = useMemo(
    () => completionCopies.find(item => String(item.id) === completionForm.selected_copy_id) || null,
    [completionCopies, completionForm.selected_copy_id],
  );

  const selectedCompletionMaterial = useMemo(
    () => completionMaterials.find(item => String(item.id) === completionForm.selected_material_id) || null,
    [completionMaterials, completionForm.selected_material_id],
  );

  const completionContractPlatforms = useMemo(() => {
    const progress = completeTaskTarget
      ? progresses.find(p => p.id === completeTaskTarget.service_progress_id) || selectedProgress
      : selectedProgress;
    return progress ? inferPlatformsFromProgress(progress) : [];
  }, [completeTaskTarget, progresses, selectedProgress]);

  // ==================== Task stats per progress ====================
  const getTaskStats = useCallback((progressId: number) => {
    const tasks = allTasks.filter(t => t.service_progress_id === progressId);
    const total = tasks.length;
    const completed = tasks.filter(t => t.status === 'completed').length;
    const pending = tasks.filter(t => t.status === 'pending' || t.status === 'in_progress').length;
    const overdue = tasks.filter(t => t.status === 'delayed' || (t.due_date && t.due_date < todayStr() && t.status !== 'completed' && t.status !== 'cancelled')).length;
    const waitingClient = tasks.filter(t => t.status === 'waiting_client').length;
    const lowQuality = tasks.filter(t => t.status === 'completed' && t.completion_quality === 'low_quality').length;
    return { total, completed, pending, overdue, waitingClient, lowQuality };
  }, [allTasks]);

  // ==================== Permissions ====================
  const currentRoleText = `${role || ''} ${employee?.role || ''} ${employee?.name || ''}`.toLowerCase();
  const isServiceAdmin = isAdmin || ['super_admin', 'admin', 'system_admin', 'administrator', '系统管理员', '超级管理员', '管理员'].some(label => currentRoleText.includes(label.toLowerCase()));
  const canEdit = isServiceAdmin || role === 'ops' || hasPermission('task_edit');
  const canCreate = isServiceAdmin || role === 'ops' || hasPermission('task_create');
  const canDelete = isServiceAdmin || hasPermission('task_delete');
  const canAddServiceTask = canCreate || canEdit;
  const canOperateTask = (task: ServiceTask) => {
    if (canEdit) return true;
    const operatorName = employee?.name || '';
    if (!operatorName) return false;
    const relatedProgress = progresses.find(item => item.id === task.service_progress_id);
    return task.assignee_name === operatorName || relatedProgress?.ops_person === operatorName;
  };

  // ==================== Form Helpers ====================
  function emptyProgressForm() {
    return {
      customer_id: 0, customer_name: '', service_type: 'social_media', service_stage: 'deal_handover',
      progress_percent: 10, sales_person: '', ops_person: '', design_person: '', package_name: '', package_platforms: '',
      industry: 'restaurant', country: 'US', state: 'CA', city: '',
      service_start_date: todayStr(), service_end_date: '', last_work_summary: '',
      issue_status: 'none', issue_description: '', issue_owner: '',
      issue_found_date: '', issue_resolved: false, issue_resolved_date: '',
      notes: '',
    };
  }

  function emptyTaskForm() {
    return {
      service_progress_id: 0, customer_id: 0, customer_name: '',
      task_name: '', task_type: 'other', platform: '', assignee_name: '', priority: 'medium',
      status: 'pending', due_date: '', notes: '',
    };
  }

  // ==================== CRUD Handlers ====================
  const openCreateProgress = () => {
    setProgressForm(emptyProgressForm());
    setEditingProgressId(null);
    setSelectedCustomerState(null);
    setCustomerSearch('');
    setShowProgressForm(true);
  };

  const openEditProgress = (sp: ServiceProgress) => {
    const cust = allCustomers.find(c => c.id === sp.customer_id) || null;
    setSelectedCustomerState(cust);
    setCustomerSearch(sp.customer_name);

    const stageValid = isStageValidForType(sp.service_type, sp.service_stage);
    const effectiveStage = stageValid ? sp.service_stage : sp.service_stage;

    setProgressForm({
      customer_id: sp.customer_id, customer_name: sp.customer_name, service_type: sp.service_type || 'social_media',
      service_stage: effectiveStage, progress_percent: sp.progress_percent,
      sales_person: sp.sales_person || '', ops_person: sp.ops_person || '', design_person: sp.design_person || '',
      package_name: sp.package_name || '', package_platforms: sp.package_platforms || '', industry: sp.industry || 'restaurant',
      country: sp.country || 'US', state: sp.state || '', city: sp.city || '',
      service_start_date: sp.service_start_date?.slice(0, 10) || '', service_end_date: sp.service_end_date?.slice(0, 10) || '',
      last_work_summary: sp.last_work_summary || '', issue_status: sp.issue_status || 'none',
      issue_description: sp.issue_description || '', issue_owner: sp.issue_owner || '',
      issue_found_date: sp.issue_found_date?.slice(0, 10) || '', issue_resolved: sp.issue_resolved || false,
      issue_resolved_date: sp.issue_resolved_date?.slice(0, 10) || '',
      notes: sp.notes || '',
    });
    setEditingProgressId(sp.id);
    setShowProgressForm(true);
  };

  const handleSaveProgress = async () => {
    if (!progressForm.customer_name.trim()) { toast.error('请先选择客户'); return; }
    if (!progressForm.customer_id) { toast.error('请从下拉列表中选择已有客户'); return; }
    if (progressForm.service_end_date && progressForm.service_start_date && progressForm.service_end_date < progressForm.service_start_date) {
      toast.error('到期日期不能早于开始日期'); return;
    }
    if (progressForm.progress_percent < 0 || progressForm.progress_percent > 100) {
      toast.error('进度百分比必须在 0-100 之间'); return;
    }
    setSavingProgress(true);
    try {
      const now = new Date().toISOString();
      const op = employee?.name || '管理员';

      const effectiveStage = isStageValidForType(progressForm.service_type, progressForm.service_stage)
        ? progressForm.service_stage
        : getFirstStageForType(progressForm.service_type);

      const data: Record<string, unknown> = {
        customer_id: progressForm.customer_id,
        customer_name: progressForm.customer_name,
        service_type: progressForm.service_type,
        service_stage: effectiveStage,
        progress_percent: progressForm.progress_percent,
        sales_person: progressForm.sales_person,
        ops_person: progressForm.ops_person,
        design_person: progressForm.design_person,
        package_name: progressForm.package_name,
        package_platforms: progressForm.package_platforms || inferPackagePlatforms(
          progressForm.package_name,
          getPackagePlatformContext().labels,
          getPackagePlatformContext().platforms,
        ).join(','),
        industry: progressForm.industry,
        country: progressForm.country,
        state: progressForm.state,
        city: progressForm.city,
        service_start_date: progressForm.service_start_date || null,
        service_end_date: progressForm.service_end_date || null,
        last_work_summary: progressForm.last_work_summary,
        notes: progressForm.notes,
        last_update_time: now,
        last_update_person: op,
      };

      if (progressForm.issue_status === 'none') {
        data.issue_status = 'none';
        data.issue_resolved = true;
        data.issue_description = '';
        data.issue_found_date = null;
        data.issue_resolved_date = null;
        data.issue_owner = '';
      } else {
        data.issue_status = progressForm.issue_status;
        data.issue_resolved = progressForm.issue_resolved;
        data.issue_description = progressForm.issue_description;
        data.issue_owner = progressForm.issue_owner;
        data.issue_found_date = progressForm.issue_found_date || todayStr();
        if (progressForm.issue_resolved && !progressForm.issue_resolved_date) {
          data.issue_resolved_date = todayStr();
        } else {
          data.issue_resolved_date = progressForm.issue_resolved_date || null;
        }
      }

      if (editingProgressId) {
        await authedUpdateEntity<ServiceProgress>('service_progresses', editingProgressId, data);
        toast.success('服务进度已更新');
        try {
          logOperation({ customerId: progressForm.customer_id, actionType: 'edit_customer', actionDetail: `更新服务进度: 阶段=${allStageLabels[effectiveStage] || effectiveStage}, 进度=${progressForm.progress_percent}%, 摘要=${progressForm.last_work_summary || '无'}`, operatorName: op });
        } catch { /* ignore log errors */ }
      } else {
        data.created_at = now;
        await authedCreateEntity<ServiceProgress>('service_progresses', data);
        toast.success('服务进度已创建');
        try {
          logOperation({ customerId: progressForm.customer_id, actionType: 'create_customer', actionDetail: `新增服务进度: ${progressForm.customer_name}, 类型=${serviceTypeLabels[progressForm.service_type]}, 阶段=${allStageLabels[effectiveStage]}`, operatorName: op });
        } catch { /* ignore log errors */ }
      }
      setShowProgressForm(false);
      await loadData();
      // Refresh detail view if we were editing the currently selected progress
      if (selectedProgress && editingProgressId === selectedProgress.id) {
        const refreshed = await authedGetEntity<ServiceProgress>('service_progresses', editingProgressId);
        if (refreshed) setSelectedProgress(refreshed);
      }
    } catch (err: unknown) {
      console.error('Save progress error:', err);
      const msg = err instanceof Error ? err.message : (typeof err === 'object' && err !== null && 'data' in err ? JSON.stringify((err as Record<string, unknown>).data) : '未知错误');
      toast.error(`保存失败: ${msg}`);
    } finally { setSavingProgress(false); }
  };

  // Quick advance to next stage
  const handleAdvanceStage = async (sp: ServiceProgress) => {
    const nextStage = getNextStage(sp.service_type, sp.service_stage);
    if (!nextStage) { toast.info('已经是最后一个阶段'); return; }
    const defaultProg = getDefaultProgress(sp.service_type, nextStage);
    try {
      const now = new Date().toISOString();
      const op = employee?.name || '管理员';
      await authedUpdateEntity<ServiceProgress>('service_progresses', sp.id, {
        service_stage: nextStage,
        progress_percent: defaultProg >= 0 ? defaultProg : sp.progress_percent,
        last_update_time: now,
        last_update_person: op,
      });
      toast.success(`已推进到: ${allStageLabels[nextStage] || nextStage}`);
      logOperation({ customerId: sp.customer_id, actionType: 'edit_customer', actionDetail: `推进服务阶段: ${sp.customer_name} ${allStageLabels[sp.service_stage]} → ${allStageLabels[nextStage]}`, operatorName: op });
      await loadData();
      if (selectedProgress?.id === sp.id) {
        const refreshed = await authedGetEntity<ServiceProgress>('service_progresses', sp.id);
        if (refreshed) setSelectedProgress(refreshed);
      }
    } catch (err) {
      console.error('Advance service stage error:', err);
      toast.error(getErrorMessage(err, '推进失败'));
    }
  };

  const handleClientMaterialReceived = async (sp: ServiceProgress) => {
    try {
      const now = new Date().toISOString();
      const op = employee?.name || '管理员';
      const nextStage = getNextStage(sp.service_type, sp.service_stage);
      const defaultProg = nextStage ? getDefaultProgress(sp.service_type, nextStage) : -1;
      const waitingTasks = allTasks.filter(task => task.service_progress_id === sp.id && task.status === 'waiting_client');

      await Promise.all(waitingTasks.map(task => authedUpdateEntity<ServiceTask>('service_tasks', task.id, {
        status: 'in_progress',
        completed_date: '',
      })));

      const data: Record<string, unknown> = {
        issue_status: 'none',
        issue_resolved: true,
        issue_description: '',
        issue_resolved_date: todayStr(),
        last_update_time: now,
        last_update_person: op,
        last_work_summary: waitingTasks.length > 0
          ? `客户资料已收到，${waitingTasks.length} 个等待客户的任务已恢复进行中`
          : '客户资料已收到，卡点已解除',
      };

      if (nextStage) {
        data.service_stage = nextStage;
        data.progress_percent = defaultProg >= 0 ? defaultProg : sp.progress_percent;
      }

      await authedUpdateEntity<ServiceProgress>('service_progresses', sp.id, data);
      toast.success(nextStage ? `资料已收到，已推进到：${allStageLabels[nextStage] || nextStage}` : '资料已收到，卡点已解除');
      await loadData();
      if (selectedProgress?.id === sp.id) {
        await refreshDetailTasks(sp.id);
        const refreshed = await authedGetEntity<ServiceProgress>('service_progresses', sp.id);
        if (refreshed) setSelectedProgress(refreshed);
      }
    } catch (err) {
      console.error('Resolve waiting material error:', err);
      toast.error(`推进失败: ${getErrorMessage(err, '未知错误')}`);
    }
  };

  // Quick update work summary
  const openQuickUpdate = (sp: ServiceProgress) => {
    setQuickUpdateSp(sp);
    setQuickUpdateSummary(sp.last_work_summary || '');
    setShowQuickUpdate(true);
  };

  const handleQuickUpdateSave = async () => {
    if (!quickUpdateSp) return;
    setSavingQuickUpdate(true);
    try {
      const now = new Date().toISOString();
      const op = employee?.name || '管理员';
      await authedUpdateEntity<ServiceProgress>('service_progresses', quickUpdateSp.id, {
        last_work_summary: quickUpdateSummary,
        last_update_time: now,
        last_update_person: op,
      });
      toast.success('工作摘要已更新');
      setShowQuickUpdate(false);
      await loadData();
      if (selectedProgress?.id === quickUpdateSp.id) {
        const refreshed = await authedGetEntity<ServiceProgress>('service_progresses', quickUpdateSp.id);
        if (refreshed) setSelectedProgress(refreshed);
      }
    } catch { toast.error('更新失败'); }
    finally { setSavingQuickUpdate(false); }
  };

  const refreshDetailTasks = async (progressId: number) => {
    const items = await authedListEntity<ServiceTask>('service_tasks', { query: { service_progress_id: progressId }, sort: 'created_at', limit: 100 });
    setDetailTasks(items);
    return items;
  };

  const refreshProgressDetail = async (progressId: number) => {
    const [progress] = await Promise.all([
      authedGetEntity<ServiceProgress>('service_progresses', progressId),
      refreshDetailTasks(progressId),
    ]);
    if (progress) setSelectedProgress(progress);
  };

  const openCompleteTask = async (task: ServiceTask) => {
    const progress = progresses.find(p => p.id === task.service_progress_id) || selectedProgress;
    const contractPlatforms = progress ? inferPlatformsFromProgress(progress) : [];
    setCompleteTaskTarget(task);
    setCompletionForm({ platform: task.platform || contractPlatforms[0] || '', selected_copy_id: '', selected_material_id: '', completion_note: '' });
    setCompletionCopies([]);
    setCompletionMaterials([]);
    setLoadingCompletionRefs(true);
    try {
      const [copyRes, materialRes] = await Promise.all([
        invokeWithAuth({
          url: '/api/v1/entities/customer_ai_copies',
          method: 'GET',
          data: { query: JSON.stringify({ customer_id: task.customer_id }), sort: '-updated_at', limit: 100 },
        }),
        invokeWithAuth({
          url: '/api/v1/entities/customer_materials',
          method: 'GET',
          data: { query: JSON.stringify({ customer_id: task.customer_id }), sort: '-updated_at', limit: 100 },
        }),
      ]);
      setCompletionCopies(copyRes?.data?.items || []);
      setCompletionMaterials(materialRes?.data?.items || []);
    } catch (err) {
      console.error('Load completion references error:', err);
      toast.error(getErrorMessage(err, '加载客户文案/素材失败'));
    } finally {
      setLoadingCompletionRefs(false);
    }
  };

  const handleCompleteTask = async () => {
    if (!completeTaskTarget) return;
    setSavingCompletion(true);
    try {
      const selectedCopyId = completionForm.selected_copy_id ? Number(completionForm.selected_copy_id) : null;
      const selectedMaterialId = completionForm.selected_material_id ? Number(completionForm.selected_material_id) : null;
      const platform = completionForm.platform || selectedCompletionMaterial?.platform || selectedCompletionCopy?.platform || null;
      const res = await invokeWithAuth({
        url: `/api/v1/entities/service_tasks/${completeTaskTarget.id}/complete`,
        method: 'POST',
        data: {
          platform,
          selected_copy_id: selectedCopyId,
          selected_material_id: selectedMaterialId,
          completion_note: completionForm.completion_note,
        },
      });
      const completedTask = res?.data as ServiceTask;
      const isLowQuality = completedTask?.completion_quality === 'low_quality';
      toast.success(isLowQuality ? '任务已完成，但系统标记为低质量完成' : '任务已完成，并已同步文案/素材使用记录');
      setCompleteTaskTarget(null);
      await loadData();
      if (selectedProgress) {
        await refreshProgressDetail(selectedProgress.id);
      }
    } catch (err) {
      console.error('Complete task error:', err);
      toast.error(getErrorMessage(err, '完成任务失败'));
    } finally {
      setSavingCompletion(false);
    }
  };

  const completeTaskDirectly = async (task: ServiceTask) => {
    setSavingTaskActionId(task.id);
    try {
      const res = await invokeWithAuth({
        url: `/api/v1/entities/service_tasks/${task.id}/complete`,
        method: 'POST',
        data: {
          platform: task.platform || null,
          selected_copy_id: null,
          selected_material_id: null,
          completion_note: '流程任务直接确认完成',
        },
      });
      const completedTask = res?.data as ServiceTask;
      toast.success(completedTask?.completion_quality === 'low_quality' ? '任务已完成，但系统标记为低质量完成' : '任务已完成');
      await loadData();
      if (selectedProgress) {
        await refreshProgressDetail(selectedProgress.id);
      }
    } catch (err) {
      console.error('Direct complete task error:', err);
      toast.error(getErrorMessage(err, '完成任务失败'));
    } finally {
      setSavingTaskActionId(null);
    }
  };

  // Quick toggle task status
  const handleQuickTaskStatus = async (task: ServiceTask, newStatus: string) => {
    if (newStatus === 'completed') {
      if (requiresCompletionReference(task)) {
        await openCompleteTask(task);
      } else {
        await completeTaskDirectly(task);
      }
      return;
    }
    try {
      setSavingTaskActionId(task.id);
      const completedDate = newStatus === 'completed' ? todayStr() : null;
      await authedUpdateEntity<ServiceTask>('service_tasks', task.id, {
        status: newStatus,
        completed_date: completedDate || '',
      });
      toast.success(`任务状态已更新为: ${taskStatusLabels[newStatus]}`);
      await loadData();
      if (selectedProgress) {
        await refreshProgressDetail(selectedProgress.id);
      }
    } catch (err: unknown) {
      console.error('Quick task status error:', err);
      toast.error(`更新失败: ${getErrorMessage(err, '未知错误')}`);
    } finally {
      setSavingTaskActionId(null);
    }
  };

  const openCreateTask = (sp: ServiceProgress) => {
    const platforms = inferPlatformsFromProgress(sp);
    setTaskForm({ ...emptyTaskForm(), service_progress_id: sp.id, customer_id: sp.customer_id, customer_name: sp.customer_name, platform: platforms[0] || '' });
    setEditingTaskId(null);
    setShowTaskForm(true);
  };

  const openCreateTaskSafely = (sp: ServiceProgress, event?: { preventDefault: () => void; stopPropagation: () => void }) => {
    event?.preventDefault();
    event?.stopPropagation();
    setDetailTab('tasks');
    openCreateTask(sp);
  };

  const openEditTask = (t: ServiceTask) => {
    setTaskForm({
      service_progress_id: t.service_progress_id, customer_id: t.customer_id, customer_name: t.customer_name,
      task_name: t.task_name, task_type: t.task_type || 'other', assignee_name: t.assignee_name || '',
      platform: t.platform || '', priority: t.priority || 'medium', status: t.status, due_date: t.due_date?.slice(0, 10) || '', notes: t.notes || '',
    });
    setEditingTaskId(t.id);
    setShowTaskForm(true);
  };

  const handleSaveTask = async () => {
    if (!taskForm.task_name.trim()) { toast.error('请填写任务名称'); return; }
    if (!taskForm.customer_id) { toast.error('任务缺少关联客户信息'); return; }
    setSavingTask(true);
    try {
      const now = new Date().toISOString();
      const data: Record<string, unknown> = {
        service_progress_id: taskForm.service_progress_id || null,
        customer_id: taskForm.customer_id,
        customer_name: taskForm.customer_name || '',
        task_name: taskForm.task_name.trim(),
        task_type: taskForm.task_type || 'other',
        platform: taskForm.platform || null,
        assignee_name: taskForm.assignee_name || null,
        priority: taskForm.priority || 'medium',
        status: taskForm.status || 'pending',
        due_date: taskForm.due_date || null,
        notes: taskForm.notes || null,
        completed_date: taskForm.status === 'completed' ? todayStr() : null,
      };
      if (editingTaskId) {
        await invokeWithAuth({
          url: `/api/v1/entities/service_tasks/${editingTaskId}`,
          method: 'PUT',
          data,
        });
        toast.success('任务已更新');
      } else {
        data.created_at = now;
        await invokeWithAuth({
          url: '/api/v1/entities/service_tasks',
          method: 'POST',
          data,
        });
        toast.success('任务已创建');
      }
      setShowTaskForm(false);
      await loadData();
      if (selectedProgress) {
        await refreshProgressDetail(selectedProgress.id);
      }
    } catch (err: unknown) {
      console.error('Save task error:', err);
      const msg = err instanceof Error ? err.message : (typeof err === 'object' && err !== null && 'data' in err ? JSON.stringify((err as Record<string, unknown>).data) : '未知错误');
      toast.error(`保存失败: ${msg}`);
    } finally { setSavingTask(false); }
  };

  const generateWeeklyTasksForProgresses = async (targets: ServiceProgress[]) => {
    const weekEnd = getWeekEndStr();
    const now = new Date().toISOString();
    let createdCount = 0;

    for (const sp of targets) {
      const plan = getWeeklyTaskPlan(sp, allTasks);
      if (plan.platforms.length === 0) continue;

      for (const platformPlan of plan.platformPlans) {
        for (let i = 0; i < platformPlan.remainingToCreate; i += 1) {
          const sequence = platformPlan.completed + platformPlan.scheduled + i + 1;
          await authedCreateEntity<ServiceTask>('service_tasks', {
            service_progress_id: sp.id,
            customer_id: sp.customer_id,
            customer_name: sp.customer_name,
            task_name: `${platformLabels[platformPlan.platform] || platformPlan.platform} 本周第 ${sequence} 次更新`,
            task_type: 'publish_content',
            platform: platformPlan.platform,
            assignee_name: sp.ops_person || null,
            priority: 'medium',
            status: 'pending',
            due_date: weekEnd,
            notes: '系统按套餐平台自动生成：合作平台每周更新 3 次。',
            created_at: now,
          });
          createdCount += 1;
        }
      }

      if (plan.reportRemainingToCreate > 0) {
        await authedCreateEntity<ServiceTask>('service_tasks', {
          service_progress_id: sp.id,
          customer_id: sp.customer_id,
          customer_name: sp.customer_name,
          task_name: '本周运营总结汇报',
          task_type: 'submit_report',
          platform: null,
          assignee_name: sp.ops_person || null,
          priority: 'medium',
          status: 'pending',
          due_date: weekEnd,
          notes: '系统自动生成：每个合作客户每周总结汇报 1 次。',
          created_at: now,
        });
        createdCount += 1;
      }
    }

    return createdCount;
  };

  const handleGenerateWeeklyTasks = async (targets?: ServiceProgress[]) => {
    const safeTargets = (targets || filteredWeeklyActionItems.map(item => item.sp))
      .filter(sp => getWeeklyTaskPlan(sp, allTasks).totalRemainingToCreate > 0);

    if (safeTargets.length === 0) {
      toast.info('本周任务已经排好了，无需重复生成');
      return;
    }

    setGeneratingWeeklyTasks(true);
    try {
      const createdCount = await generateWeeklyTasksForProgresses(safeTargets);
      if (createdCount > 0) {
        toast.success(`已生成 ${createdCount} 个本周运营任务`);
      } else {
        toast.info('没有需要新生成的任务');
      }
      await loadData();
      if (selectedProgress) {
        await refreshProgressDetail(selectedProgress.id);
      }
    } catch (err) {
      console.error('Generate weekly tasks error:', err);
      toast.error(getErrorMessage(err, '生成本周任务失败'));
    } finally {
      setGeneratingWeeklyTasks(false);
    }
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      if (deleteTarget.type === 'progress') {
        // Also delete associated tasks
        const relatedTasks = allTasks.filter(t => t.service_progress_id === deleteTarget.item.id);
        for (const t of relatedTasks) {
          try { await authedDeleteEntity('service_tasks', t.id); } catch { /* ignore */ }
        }
        await authedDeleteEntity('service_progresses', deleteTarget.item.id);
        toast.success('服务进度及关联任务已删除');
        if (selectedProgress?.id === deleteTarget.item.id) setSelectedProgress(null);
      } else {
        await authedDeleteEntity('service_tasks', deleteTarget.item.id);
        toast.success('任务已删除');
      }
      setDeleteTarget(null);
      await loadData();
      if (selectedProgress && deleteTarget.type === 'task') {
        await refreshProgressDetail(selectedProgress.id);
      }
    } catch (err: unknown) {
      console.error('Delete error:', err);
      const msg = err instanceof Error ? err.message : (typeof err === 'object' && err !== null && 'data' in err ? JSON.stringify((err as Record<string, unknown>).data) : '未知错误');
      toast.error(`删除失败: ${msg}`);
    } finally { setDeleting(false); }
  };

  const openDetail = async (sp: ServiceProgress) => {
    setSelectedProgress(sp);
    setDetailTab('overview');
    try {
      await refreshDetailTasks(sp.id);
    } catch { setDetailTasks([]); }
  };

  // ==================== Export data preparation ====================
  const exportData = useMemo(() => {
    return filtered.map(sp => {
      const ts = getTaskStats(sp.id);
      return {
        customer_name: sp.customer_name,
        service_type: serviceTypeLabels[sp.service_type] || sp.service_type,
        service_stage: allStageLabels[sp.service_stage] || sp.service_stage,
        progress_percent: `${sp.progress_percent}%`,
        sales_person: sp.sales_person || '-',
        ops_person: sp.ops_person || '-',
        design_person: sp.design_person || '-',
        package_name: sp.package_name || '-',
        industry: industryLabels[sp.industry] || sp.industry,
        city: sp.city || '-',
        state: sp.state || '-',
        country: displayCountry(sp.country),
        service_start_date: sp.service_start_date?.slice(0, 10) || '-',
        service_end_date: sp.service_end_date?.slice(0, 10) || '-',
        issue_status: issueStatusLabels[sp.issue_status] || sp.issue_status,
        issue_description: sp.issue_description || '-',
        last_update_time: sp.last_update_time?.slice(0, 16) || '-',
        last_update_person: sp.last_update_person || '-',
        last_work_summary: sp.last_work_summary || '-',
        tasks_total: ts.total,
        tasks_completed: ts.completed,
        tasks_pending: ts.pending,
        notes: sp.notes || '-',
      };
    });
  }, [filtered, getTaskStats]);

  const exportColumns = [
    { key: 'customer_name', label: '客户名称' },
    { key: 'service_type', label: '服务类型' },
    { key: 'service_stage', label: '服务阶段' },
    { key: 'progress_percent', label: '进度' },
    { key: 'sales_person', label: '销售' },
    { key: 'ops_person', label: '运营' },
    { key: 'design_person', label: '设计' },
    { key: 'package_name', label: '套餐' },
    { key: 'industry', label: '行业' },
    { key: 'city', label: '城市' },
    { key: 'state', label: '州' },
    { key: 'country', label: '国家' },
    { key: 'service_start_date', label: '开始日期' },
    { key: 'service_end_date', label: '到期日期' },
    { key: 'issue_status', label: '问题状态' },
    { key: 'issue_description', label: '问题描述' },
    { key: 'last_update_time', label: '最近更新' },
    { key: 'last_update_person', label: '更新人' },
    { key: 'last_work_summary', label: '工作摘要' },
    { key: 'tasks_total', label: '总任务' },
    { key: 'tasks_completed', label: '已完成' },
    { key: 'tasks_pending', label: '待处理' },
    { key: 'notes', label: '备注' },
  ];

  // ==================== Progress Card Component ====================
  const ProgressCard = ({ sp }: { sp: ServiceProgress }) => {
    const ts = getTaskStats(sp.id);
    const overdue = isOverdue(sp);
    const expiring = isExpiringSoon(sp);
    const issue = hasIssue(sp);
    const nextStage = getNextStage(sp.service_type, sp.service_stage);
    const remainDays = getServiceRemainingDays(sp);
    const weekly = getWeeklyPlatformProgress(sp, allTasks);
    const onboarding = getOnboardingProgress(sp, allTasks);

    return (
      <div
        className={`p-4 rounded-lg border cursor-pointer transition-all hover:shadow-md ${
          issue ? 'border-red-300 bg-red-50/50' : overdue ? 'border-red-300 bg-red-50/50' : expiring ? 'border-yellow-300 bg-yellow-50/50' : 'border-slate-200 bg-white'
        }`}
        onClick={() => openDetail(sp)}
      >
        <div className="flex items-start justify-between mb-2">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="font-semibold text-sm text-slate-800 truncate">{sp.customer_name}</span>
              <Badge className="text-[10px] bg-blue-100 text-blue-700">{serviceTypeLabels[sp.service_type] || sp.service_type}</Badge>
              {issue && <Badge className="text-[10px] bg-red-100 text-red-700 flex items-center gap-0.5"><AlertTriangle className="w-2.5 h-2.5" />卡点</Badge>}
              {overdue && <Badge className="text-[10px] bg-red-100 text-red-700">已逾期</Badge>}
              {expiring && <Badge className="text-[10px] bg-yellow-100 text-yellow-700">即将到期</Badge>}
            </div>
            <p className="text-xs text-slate-500 mt-0.5">{sp.city}{sp.state ? `, ${sp.state}` : ''} · {industryLabels[sp.industry] || sp.industry}</p>
            <p className={`text-xs mt-1 ${
              remainDays == null
                ? 'text-slate-400'
                : remainDays <= 0
                  ? 'text-red-600 font-medium'
                  : remainDays <= SERVICE_EXPIRY_WARNING_DAYS
                    ? 'text-yellow-700 font-medium'
                    : 'text-slate-500'
            }`}>
              {remainDays == null
                ? '到期剩余: -'
                : remainDays <= 0
                  ? `已逾期 ${Math.abs(remainDays)} 天`
                  : `剩余 ${remainDays} 天`}
            </p>
          </div>
          <div className="text-right shrink-0 ml-2">
            <div className="text-lg font-bold text-blue-600">{sp.progress_percent}%</div>
          </div>
        </div>

        <div className="w-full bg-slate-200 rounded-full h-1.5 mb-2">
          <div className={`h-1.5 rounded-full transition-all ${sp.progress_percent >= 100 ? 'bg-green-500' : sp.progress_percent >= 60 ? 'bg-blue-500' : sp.progress_percent >= 30 ? 'bg-amber-500' : 'bg-slate-400'}`} style={{ width: `${Math.min(sp.progress_percent, 100)}%` }} />
        </div>

        <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-slate-500 mb-2">
          <span>阶段: <span className="text-slate-700">{allStageLabels[sp.service_stage] || sp.service_stage}</span></span>
          <span>套餐: <span className="text-slate-700">{sp.package_name || '-'}</span></span>
          <span>运营: <span className="text-slate-700">{sp.ops_person || '-'}</span></span>
          <span>销售: <span className="text-slate-700">{sp.sales_person || '-'}</span></span>
        </div>

        {weekly.platforms.length > 0 && (
          <div className="mb-2 rounded-md bg-slate-50 border border-slate-100 p-2">
            <div className="flex items-center justify-between gap-2 text-xs">
              <span className="text-slate-500">本周平台更新</span>
              <span className={weekly.platformDone >= weekly.platformTarget ? 'text-green-600 font-medium' : 'text-orange-600 font-medium'}>
                {weekly.platformDone}/{weekly.platformTarget}
              </span>
            </div>
            <div className="flex flex-wrap gap-1 mt-1">
              {weekly.platforms.map(platform => (
                <Badge key={platform} className={`text-[10px] ${(weekly.counts[platform] || 0) >= WEEKLY_PLATFORM_UPDATE_TARGET ? 'bg-green-100 text-green-700' : 'bg-orange-100 text-orange-700'}`}>
                  {platformLabels[platform] || platform} {Math.min(weekly.counts[platform] || 0, WEEKLY_PLATFORM_UPDATE_TARGET)}/{WEEKLY_PLATFORM_UPDATE_TARGET}
                </Badge>
              ))}
              <Badge className={`text-[10px] ${weekly.weeklyReportDone >= weekly.weeklyReportTarget ? 'bg-indigo-100 text-indigo-700' : 'bg-orange-100 text-orange-700'}`}>
                周报 {weekly.weeklyReportDone}/{weekly.weeklyReportTarget}
              </Badge>
            </div>
          </div>
        )}

        {onboarding.total > 0 && !onboarding.isComplete && (
          <div className="mb-2 rounded-md bg-blue-50 border border-blue-100 p-2">
            <div className="flex items-center justify-between gap-2 text-xs">
              <span className="text-blue-700 font-medium">前期流程</span>
              <span className="text-blue-700">{onboarding.completed}/{onboarding.total}</span>
            </div>
            <div className="w-full bg-blue-100 rounded-full h-1.5 mt-1.5">
              <div className="h-1.5 rounded-full bg-blue-500 transition-all" style={{ width: `${onboarding.total > 0 ? Math.round((onboarding.completed / onboarding.total) * 100) : 0}%` }} />
            </div>
            {onboarding.nextStep && (
              <p className="text-[11px] text-blue-700 mt-1">下一步：{onboarding.nextStep.label}</p>
            )}
          </div>
        )}

        <div className="flex items-center gap-3 text-xs border-t border-slate-100 pt-2">
          <span className="flex items-center gap-1 text-slate-500"><CheckCircle2 className="w-3 h-3 text-green-500" />{ts.completed}/{ts.total}</span>
          {ts.overdue > 0 && <span className="flex items-center gap-1 text-red-600"><XCircle className="w-3 h-3" />{ts.overdue}逾期</span>}
          {ts.lowQuality > 0 && <span className="flex items-center gap-1 text-orange-600"><AlertTriangle className="w-3 h-3" />{ts.lowQuality}低质</span>}
          {ts.waitingClient > 0 && <span className="flex items-center gap-1 text-amber-600"><Clock className="w-3 h-3" />{ts.waitingClient}待客户</span>}
          <span className="ml-auto text-slate-400">{sp.last_update_time?.slice(0, 10) || '-'}</span>
        </div>

        {/* Quick actions row */}
        {canEdit && (
          <div className="flex items-center gap-1.5 mt-2 pt-2 border-t border-slate-100" onClick={e => e.stopPropagation()}>
            <Button size="sm" variant="ghost" className="h-6 px-2 text-xs text-slate-500 hover:text-blue-600" onClick={() => openEditProgress(sp)}>
              <Edit className="w-3 h-3 mr-1" /> 编辑
            </Button>
            <Button size="sm" variant="ghost" className="h-6 px-2 text-xs text-slate-500 hover:text-blue-600" onClick={() => openQuickUpdate(sp)}>
              <Copy className="w-3 h-3 mr-1" /> 更新摘要
            </Button>
            {nextStage && (
              <Button size="sm" variant="ghost" className="h-6 px-2 text-xs text-slate-500 hover:text-green-600" onClick={() => handleAdvanceStage(sp)}>
                <ChevronRight className="w-3 h-3 mr-1" /> 推进阶段
              </Button>
            )}
            {canDelete && (
              <Button size="sm" variant="ghost" className="h-6 px-2 text-xs text-slate-500 hover:text-red-600 ml-auto" onClick={() => setDeleteTarget({ type: 'progress', item: sp })}>
                <Trash2 className="w-3 h-3" />
              </Button>
            )}
          </div>
        )}

        {issue && (
          <div className="mt-2 p-2 bg-red-50 border border-red-200 rounded text-xs text-red-700">
            <span className="font-medium">{issueStatusLabels[sp.issue_status]}</span>: {sp.issue_description || '无描述'}
            {canEdit && isWaitingForClientMaterial(sp) && (
              <Button
                size="sm"
                variant="outline"
                className="mt-2 h-7 w-full border-emerald-200 bg-emerald-50 text-emerald-700 hover:bg-emerald-100"
                onClick={e => {
                  e.stopPropagation();
                  void handleClientMaterialReceived(sp);
                }}
              >
                资料已收到并继续推进
              </Button>
            )}
          </div>
        )}
      </div>
    );
  };

  const renderTaskActionDialogs = () => (
    <>
      <ConfirmDialog
        open={!!deleteTarget}
        onOpenChange={v => { if (!v) setDeleteTarget(null); }}
        title={deleteTarget?.type === 'progress' ? '确认删除服务进度' : '确认删除任务'}
        description={
          deleteTarget?.type === 'progress'
            ? `确定要删除「${deleteTarget?.item?.customer_name}」的服务进度记录吗？关联的所有任务也将被删除。此操作不可撤销。`
            : `确定要删除任务「${deleteTarget?.item?.task_name}」吗？此操作不可撤销。`
        }
        onConfirm={handleDelete}
        loading={deleting}
      />

      <Dialog open={!!completeTaskTarget} onOpenChange={v => { if (!v) setCompleteTaskTarget(null); }}>
        <DialogContent className="max-w-xl max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>完成任务 - {completeTaskTarget?.task_name}</DialogTitle>
          </DialogHeader>
          {loadingCompletionRefs ? (
            <div className="py-8 text-center">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600 mx-auto mb-3" />
              <p className="text-sm text-slate-500">正在加载该客户的文案和素材...</p>
            </div>
          ) : (
            <div className="space-y-4">
              <div className="rounded-lg border border-blue-100 bg-blue-50 p-3 text-sm text-blue-800 flex gap-2">
                <ClipboardCheck className="w-4 h-4 shrink-0 mt-0.5" />
                <span>
                  {requiresCompletionReference(completeTaskTarget)
                    ? '内容发布、评论回复、周报类任务建议选择实际使用的文案或素材；如果都不选也可以完成，但系统会标记为低质量完成。'
                    : '流程类任务可以直接确认完成；如果有相关文案或素材，也可以顺手选择，方便后续追踪。'}
                </span>
              </div>

              <div>
                <Label>本次完成平台</Label>
                <NativeSelect
                  value={completionForm.platform}
                  onChange={v => setCompletionForm({ ...completionForm, platform: v })}
                  options={[
                    { value: '', label: '不限定平台 / 周总结汇报' },
                    ...Array.from(new Set([...completionContractPlatforms, ...Object.keys(platformLabels).filter(key => key !== 'general')])).map(platform => ({
                      value: platform,
                      label: completionContractPlatforms.includes(platform)
                        ? `${platformLabels[platform] || platform}（套餐合作平台）`
                        : platformLabels[platform] || platform,
                    })),
                  ]}
                />
                <p className="text-xs text-slate-400 mt-1">平台更新任务需要选择对应平台；周总结汇报可以选择“不限定平台”。</p>
              </div>

              <div className="grid md:grid-cols-2 gap-4">
                <div>
                  <Label className="flex items-center gap-1.5"><Sparkles className="w-3.5 h-3.5 text-blue-500" /> 使用文案</Label>
                  <NativeSelect
                    value={completionForm.selected_copy_id}
                    onChange={v => {
                      const nextCopy = completionCopies.find(item => String(item.id) === v);
                      setCompletionForm({
                        ...completionForm,
                        selected_copy_id: v,
                        platform: completionForm.platform || (nextCopy?.platform && nextCopy.platform !== 'general' ? nextCopy.platform : ''),
                      });
                    }}
                    options={[
                      { value: '', label: completionCopies.length ? '不选择文案' : '暂无可选文案' },
                      ...completionCopies.map(item => ({
                        value: String(item.id),
                        label: `${item.title || `文案 #${item.id}`} · ${platformLabels[item.platform] || item.platform} · ${copyTypeLabels[item.content_type] || item.content_type}`,
                      })),
                    ]}
                  />
                  {selectedCompletionCopy && (
                    <div className="mt-2 rounded-md bg-slate-50 border border-slate-100 p-2 text-xs text-slate-600 max-h-28 overflow-y-auto">
                      <p className="font-medium text-slate-700 mb-1">{selectedCompletionCopy.title}</p>
                      <p className="whitespace-pre-wrap line-clamp-4">{selectedCompletionCopy.content}</p>
                    </div>
                  )}
                </div>

                <div>
                  <Label className="flex items-center gap-1.5"><FileImage className="w-3.5 h-3.5 text-emerald-500" /> 使用素材</Label>
                  <NativeSelect
                    value={completionForm.selected_material_id}
                    onChange={v => {
                      const nextMaterial = completionMaterials.find(item => String(item.id) === v);
                      setCompletionForm({
                        ...completionForm,
                        selected_material_id: v,
                        platform: completionForm.platform || (nextMaterial?.platform && nextMaterial.platform !== 'general' ? nextMaterial.platform : ''),
                      });
                    }}
                    options={[
                      { value: '', label: completionMaterials.length ? '不选择素材' : '暂无可选素材' },
                      ...completionMaterials.map(item => ({
                        value: String(item.id),
                        label: `${item.title || item.file_name || `素材 #${item.id}`} · ${platformLabels[item.platform] || item.platform || '通用'} · ${materialTypeLabels[item.material_type] || item.material_type}`,
                      })),
                    ]}
                  />
                  {selectedCompletionMaterial && (
                    <div className="mt-2 rounded-md bg-slate-50 border border-slate-100 p-2 text-xs text-slate-600">
                      <p className="font-medium text-slate-700 mb-1">{selectedCompletionMaterial.title}</p>
                      <div className="flex flex-wrap gap-1">
                        <Badge className="text-[10px] bg-emerald-100 text-emerald-700">{materialTypeLabels[selectedCompletionMaterial.material_type] || selectedCompletionMaterial.material_type}</Badge>
                        <Badge className="text-[10px] bg-blue-100 text-blue-700">{platformLabels[selectedCompletionMaterial.platform] || selectedCompletionMaterial.platform || '通用'}</Badge>
                        <Badge className="text-[10px] bg-slate-100 text-slate-700">{selectedCompletionMaterial.usage_status || '未使用'}</Badge>
                      </div>
                      {selectedCompletionMaterial.file_url && <p className="mt-1 truncate text-blue-600">{selectedCompletionMaterial.file_url}</p>}
                    </div>
                  )}
                </div>
              </div>

              <div>
                <Label>完成说明</Label>
                <Textarea
                  value={completionForm.completion_note}
                  onChange={e => setCompletionForm({ ...completionForm, completion_note: e.target.value })}
                  rows={3}
                  placeholder="例如：已用菜单图生成本周 Google 商家更新文案，等待客户确认图片。"
                />
              </div>

              {requiresCompletionReference(completeTaskTarget) && !completionForm.selected_copy_id && !completionForm.selected_material_id && (
                <div className="rounded-lg border border-orange-200 bg-orange-50 p-3 text-xs text-orange-800 flex gap-2">
                  <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
                  <span>当前没有选择文案或素材，保存后会计入“低质量完成”。如果客户确实没有素材，可以在完成说明里写清楚原因。</span>
                </div>
              )}

              {completeTaskTarget?.task_type === 'publish_content' && !completionForm.platform && (
                <div className="rounded-lg border border-indigo-200 bg-indigo-50 p-3 text-xs text-indigo-800 flex gap-2">
                  <Info className="w-4 h-4 shrink-0 mt-0.5" />
                  <span>当前没有选择平台，这次完成不会计入平台每周 3 次更新；如果这是周总结汇报，可以保持不限定平台。</span>
                </div>
              )}
            </div>
          )}
          <div className="flex justify-end gap-2 mt-4">
            <Button variant="outline" onClick={() => setCompleteTaskTarget(null)}>取消</Button>
            <Button onClick={handleCompleteTask} disabled={savingCompletion || loadingCompletionRefs} className="bg-green-600 hover:bg-green-700">
              {savingCompletion ? '保存中...' : '确认完成'}
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      <Dialog open={showTaskForm} onOpenChange={setShowTaskForm}>
        <DialogContent className="max-w-lg max-h-[85vh] overflow-y-auto">
          <DialogHeader><DialogTitle>{editingTaskId ? '编辑任务' : '新增任务'} - {taskForm.customer_name}</DialogTitle></DialogHeader>
          <div className="space-y-4">
            <div><Label>任务名称 *</Label><Input value={taskForm.task_name} onChange={e => setTaskForm({ ...taskForm, task_name: e.target.value })} placeholder="例如：收集菜单图片" /></div>
            <div className="grid grid-cols-2 gap-4">
              <div><Label>任务类型</Label><NativeSelect value={taskForm.task_type} onChange={v => setTaskForm({ ...taskForm, task_type: v })} options={Object.entries(taskTypeLabels).map(([k, v]) => ({ value: k, label: v }))} /></div>
              <div>
                <Label>平台</Label>
                <NativeSelect
                  value={taskForm.platform}
                  onChange={v => setTaskForm({ ...taskForm, platform: v })}
                  options={[
                    { value: '', label: '不限定平台 / 周总结汇报' },
                    ...Object.entries(platformLabels)
                      .filter(([key]) => key !== 'general')
                      .map(([value, label]) => ({ value, label })),
                  ]}
                />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <Label>负责人</Label>
                <NativeSelect
                  value={taskForm.assignee_name}
                  onChange={v => setTaskForm({ ...taskForm, assignee_name: v })}
                  options={[
                    { value: '', label: '请选择' },
                    ...activeEmployees.map(e => ({ value: e.name, label: `${e.name} (${e.role})` })),
                    ...(taskForm.assignee_name && !activeEmployees.find(e => e.name === taskForm.assignee_name) ? [{ value: taskForm.assignee_name, label: `${taskForm.assignee_name} (当前)` }] : []),
                  ]}
                />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div><Label>优先级</Label><NativeSelect value={taskForm.priority} onChange={v => setTaskForm({ ...taskForm, priority: v })} options={Object.entries(priorityLabels).map(([k, v]) => ({ value: k, label: v }))} /></div>
              <div><Label>状态</Label><NativeSelect value={taskForm.status} onChange={v => setTaskForm({ ...taskForm, status: v })} options={Object.entries(taskStatusLabels).map(([k, v]) => ({ value: k, label: v }))} /></div>
            </div>
            <div><Label>截止日期</Label><Input type="date" value={taskForm.due_date} onChange={e => setTaskForm({ ...taskForm, due_date: e.target.value })} /></div>
            <div><Label>备注</Label><Textarea value={taskForm.notes} onChange={e => setTaskForm({ ...taskForm, notes: e.target.value })} rows={2} placeholder="补充说明..." /></div>
          </div>
          <div className="flex justify-end gap-2 mt-4">
            <Button variant="outline" onClick={() => setShowTaskForm(false)}>取消</Button>
            <Button onClick={handleSaveTask} disabled={savingTask} className="bg-blue-600 hover:bg-blue-700">{savingTask ? '保存中...' : '保存'}</Button>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );

  const ProgressPaginationFooter = () => {
    if (filtered.length === 0) return null;
    return (
      <div className="mt-4 flex flex-col gap-3 rounded-lg border border-slate-200 bg-white p-3 text-sm text-slate-600 sm:flex-row sm:items-center sm:justify-between">
        <div>
          显示第 {paginatedProgresses.start}-{paginatedProgresses.end} 条，共 {filtered.length} 条
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-500">每页</span>
          <NativeSelect
            value={String(progressPageSize)}
            onChange={value => setProgressPageSize(Number(value))}
            options={PAGE_SIZE_OPTIONS.map(size => ({ value: String(size), label: `${size} 条` }))}
            className="h-9 w-24 text-sm"
          />
          <Button
            variant="outline"
            size="sm"
            disabled={paginatedProgresses.page <= 1}
            onClick={() => setProgressPage(page => Math.max(1, page - 1))}
          >
            上一页
          </Button>
          <span className="min-w-16 text-center text-xs text-slate-500">
            {paginatedProgresses.page} / {paginatedProgresses.totalPages}
          </span>
          <Button
            variant="outline"
            size="sm"
            disabled={paginatedProgresses.page >= paginatedProgresses.totalPages}
            onClick={() => setProgressPage(page => Math.min(paginatedProgresses.totalPages, page + 1))}
          >
            下一页
          </Button>
        </div>
      </div>
    );
  };

  // ==================== DETAIL VIEW ====================
  if (selectedProgress) {
    const sp = selectedProgress;
    const ts = getTaskStats(sp.id);
    const nextStage = getNextStage(sp.service_type, sp.service_stage);
    const weekly = getWeeklyPlatformProgress(sp, allTasks);
    const weeklyTaskPlan = getWeeklyTaskPlan(sp, allTasks);
    const onboarding = getOnboardingProgress(sp, detailTasks);
    const activeDetailTasks = detailTasks.filter(task => task.status !== 'completed');
    const completedDetailTasks = detailTasks.filter(task => task.status === 'completed');

    // Build richer timeline
    const timelineItems = [
      ...(sp.created_at ? [{ time: sp.created_at, label: '创建服务记录', type: 'info' as const }] : []),
      ...(sp.service_start_date ? [{ time: sp.service_start_date, label: '服务开始', type: 'info' as const }] : []),
      ...detailTasks.map(t => ({
        time: t.created_at,
        label: `创建任务: ${t.task_name} (${taskTypeLabels[t.task_type] || t.task_type})`,
        type: 'task' as const,
      })),
      ...detailTasks.filter(t => t.completed_date || t.completed_at).map(t => {
        const refs = [
          t.selected_copy_title ? `文案「${t.selected_copy_title}」` : '',
          t.selected_material_title ? `素材「${t.selected_material_title}」` : '',
          t.completion_quality === 'low_quality' ? '低质量完成' : '',
        ].filter(Boolean);
        return {
          time: t.completed_at || t.completed_date || '',
          label: `完成任务: ${t.task_name}${refs.length ? `（${refs.join('，')}）` : ''}`,
          type: t.completion_quality === 'low_quality' ? 'issue' as const : 'done' as const,
        };
      }),
      ...(sp.issue_found_date && sp.issue_status !== 'none' ? [{ time: sp.issue_found_date, label: `发现问题: ${issueStatusLabels[sp.issue_status]} - ${sp.issue_description || '无描述'}`, type: 'issue' as const }] : []),
      ...(sp.issue_resolved && sp.issue_resolved_date ? [{ time: sp.issue_resolved_date, label: '问题已解决', type: 'done' as const }] : []),
      ...(sp.last_update_time ? [{ time: sp.last_update_time, label: `最近更新: ${sp.last_work_summary || '无描述'} (${sp.last_update_person || '-'})`, type: 'update' as const }] : []),
      ...(sp.service_end_date ? [{ time: sp.service_end_date, label: '服务到期', type: isOverdue(sp) ? 'issue' as const : 'info' as const }] : []),
    ].sort((a, b) => a.time.localeCompare(b.time));

    return (
      <div className="space-y-4">
        <div className="flex items-center gap-3 flex-wrap">
          <Button variant="ghost" size="sm" onClick={() => setSelectedProgress(null)}><ArrowLeft className="w-4 h-4 mr-1" /> 返回看板</Button>
          <h2 className="text-lg font-semibold">{sp.customer_name}</h2>
          <Badge className="bg-blue-100 text-blue-700">{serviceTypeLabels[sp.service_type]}</Badge>
          <Badge className={issueStatusColors[sp.issue_status]}>{issueStatusLabels[sp.issue_status]}</Badge>
          {isOverdue(sp) && <Badge className="bg-red-100 text-red-700">已逾期</Badge>}
          {isExpiringSoon(sp) && <Badge className="bg-yellow-100 text-yellow-700">即将到期</Badge>}
        </div>

        {/* Quick action bar */}
        {canEdit && (
          <div className="flex gap-2 flex-wrap">
            <Button size="sm" variant="outline" onClick={() => openEditProgress(sp)}><Edit className="w-3.5 h-3.5 mr-1" /> 编辑进度</Button>
            <Button size="sm" variant="outline" onClick={() => openQuickUpdate(sp)}><Copy className="w-3.5 h-3.5 mr-1" /> 更新摘要</Button>
            {nextStage && (
              <Button size="sm" variant="outline" className="text-green-600 hover:text-green-700 hover:bg-green-50" onClick={() => handleAdvanceStage(sp)}>
                <ChevronRight className="w-3.5 h-3.5 mr-1" /> 推进到: {allStageLabels[nextStage]}
              </Button>
            )}
            {isWaitingForClientMaterial(sp) && (
              <Button size="sm" variant="outline" className="text-emerald-700 border-emerald-200 bg-emerald-50 hover:bg-emerald-100" onClick={() => handleClientMaterialReceived(sp)}>
                <CheckCircle2 className="w-3.5 h-3.5 mr-1" /> 资料已收到并继续
              </Button>
            )}
            {weeklyTaskPlan.totalRemainingToCreate > 0 && (
              <Button size="sm" variant="outline" className="text-emerald-600 hover:text-emerald-700 hover:bg-emerald-50" onClick={() => handleGenerateWeeklyTasks([sp])} disabled={generatingWeeklyTasks}>
                <ClipboardCheck className="w-3.5 h-3.5 mr-1" /> 生成本周任务 ({weeklyTaskPlan.totalRemainingToCreate})
              </Button>
            )}
            {canCreate && (
              <Button size="sm" onClick={() => { openCreateTask(sp); setDetailTab('tasks'); }} className="bg-blue-600 hover:bg-blue-700 text-white"><Plus className="w-3.5 h-3.5 mr-1" /> 新增任务</Button>
            )}
            {canDelete && (
              <Button size="sm" variant="outline" className="text-red-600 hover:text-red-700 hover:bg-red-50 ml-auto" onClick={() => setDeleteTarget({ type: 'progress', item: sp })}>
                <Trash2 className="w-3.5 h-3.5 mr-1" /> 删除
              </Button>
            )}
          </div>
        )}

        <Tabs value={detailTab} onValueChange={setDetailTab} className="w-full">
          <TabsList className="bg-slate-100 flex-wrap h-auto gap-1 p-1">
            <TabsTrigger value="overview" className="text-xs">服务概览</TabsTrigger>
            <TabsTrigger value="tasks" className="text-xs gap-1.5">
              <span>任务清单 ({activeDetailTasks.length})</span>
              <span className="rounded-full bg-green-100 px-1.5 py-0.5 text-[10px] font-medium text-green-700">
                已完成 {completedDetailTasks.length}
              </span>
            </TabsTrigger>
            <TabsTrigger value="timeline" className="text-xs">时间线 ({timelineItems.length})</TabsTrigger>
          </TabsList>

          <TabsContent value="overview">
            <div className="grid md:grid-cols-2 gap-4">
              <Card className="border-slate-200"><CardContent className="p-5">
                <h3 className="text-sm font-semibold text-slate-700 mb-3">服务信息</h3>
                <div className="space-y-2 text-sm">
                  <div className="flex justify-between"><span className="text-slate-500">当前阶段</span><span className="font-medium">{allStageLabels[sp.service_stage] || sp.service_stage}</span></div>
                  <div className="flex justify-between"><span className="text-slate-500">进度</span>
                    <div className="flex items-center gap-2">
                      <div className="w-24 bg-slate-200 rounded-full h-2"><div className={`h-2 rounded-full ${sp.progress_percent >= 100 ? 'bg-green-500' : 'bg-blue-500'}`} style={{ width: `${Math.min(sp.progress_percent, 100)}%` }} /></div>
                      <span className="font-bold text-blue-600">{sp.progress_percent}%</span>
                    </div>
                  </div>
                  <div className="flex justify-between"><span className="text-slate-500">服务类型</span><span>{serviceTypeLabels[sp.service_type]}</span></div>
                  <div className="flex justify-between"><span className="text-slate-500">套餐</span><span>{sp.package_name || '-'}</span></div>
                  <div className="flex justify-between"><span className="text-slate-500">行业</span><span>{industryLabels[sp.industry] || sp.industry}</span></div>
                  <div className="flex justify-between"><span className="text-slate-500">地区</span><span>{[sp.city, sp.state ? getStateLabel(sp.country, sp.state) : '', displayCountry(sp.country)].filter(Boolean).join(', ')}</span></div>
                  <div className="flex justify-between"><span className="text-slate-500">开始日期</span><span>{sp.service_start_date?.slice(0, 10) || '-'}</span></div>
                  <div className="flex justify-between">
                    <span className="text-slate-500">到期日期</span>
                    <span className={
                      isOverdue(sp)
                        ? 'text-red-600 font-medium'
                        : isExpiringSoon(sp)
                          ? 'text-yellow-700 font-medium'
                          : ''
                    }>
                      {sp.service_end_date?.slice(0, 10) || '-'}
                      {(() => {
                        const remainDays = getServiceRemainingDays(sp);
                        if (remainDays == null) return '';
                        if (remainDays <= 0) return ` (已逾期 ${Math.abs(remainDays)} 天)`;
                        if (remainDays <= SERVICE_EXPIRY_WARNING_DAYS) return ` (剩余 ${remainDays} 天)`;
                        return '';
                      })()}
                    </span>
                  </div>
                </div>
              </CardContent></Card>

              {weekly.platforms.length > 0 && (
                <Card className="border-slate-200"><CardContent className="p-5">
                  <h3 className="text-sm font-semibold text-slate-700 mb-3">合作平台本周达标</h3>
                  <div className="space-y-2">
                    {weekly.platforms.map(platform => {
                      const done = Math.min(weekly.counts[platform] || 0, WEEKLY_PLATFORM_UPDATE_TARGET);
                      const ok = done >= WEEKLY_PLATFORM_UPDATE_TARGET;
                      return (
                        <div key={platform} className="flex items-center justify-between text-sm">
                          <span className="text-slate-600">{platformLabels[platform] || platform}</span>
                          <Badge className={ok ? 'bg-green-100 text-green-700' : 'bg-orange-100 text-orange-700'}>
                            {done}/{WEEKLY_PLATFORM_UPDATE_TARGET} 次
                          </Badge>
                        </div>
                      );
                    })}
                    <div className="flex items-center justify-between text-sm pt-2 border-t border-slate-100">
                      <span className="text-slate-600">周总结汇报</span>
                      <Badge className={weekly.weeklyReportDone >= weekly.weeklyReportTarget ? 'bg-indigo-100 text-indigo-700' : 'bg-orange-100 text-orange-700'}>
                        {weekly.weeklyReportDone}/{weekly.weeklyReportTarget} 次
                      </Badge>
                    </div>
                  </div>
                  <p className="text-xs text-slate-400 mt-3">规则：合作平台每个平台每周更新 3 次，客户每周总结汇报 1 次。</p>
                </CardContent></Card>
              )}

              {onboarding.total > 0 && (
                <Card className="border-blue-100 bg-blue-50/40"><CardContent className="p-5">
                  <div className="flex items-center justify-between gap-3 mb-3">
                    <h3 className="text-sm font-semibold text-blue-800">前期运营流程</h3>
                    <Badge className={onboarding.isComplete ? 'bg-green-100 text-green-700' : 'bg-blue-100 text-blue-700'}>
                      {onboarding.completed}/{onboarding.total} 完成
                    </Badge>
                  </div>
                  <div className="space-y-2">
                    {onboarding.steps.filter(step => step.task).map(step => (
                      <div key={step.key} className="flex items-start gap-2 text-sm">
                        {step.status === 'completed' ? (
                          <CheckCircle2 className="w-4 h-4 text-green-600 mt-0.5 shrink-0" />
                        ) : (
                          <Clock className="w-4 h-4 text-blue-600 mt-0.5 shrink-0" />
                        )}
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center justify-between gap-2">
                            <span className="font-medium text-slate-700">{step.label}</span>
                            <Badge className={step.status === 'completed' ? 'bg-green-100 text-green-700' : 'bg-slate-100 text-slate-600'}>
                              {taskStatusLabels[step.status] || '待处理'}
                            </Badge>
                          </div>
                          <p className="text-xs text-slate-500 truncate">{step.task?.task_name}</p>
                        </div>
                      </div>
                    ))}
                  </div>
                  {onboarding.nextStep && (
                    <p className="text-xs text-blue-700 mt-3">建议下一步优先处理：{onboarding.nextStep.label}</p>
                  )}
                </CardContent></Card>
              )}

              <Card className="border-slate-200"><CardContent className="p-5">
                <h3 className="text-sm font-semibold text-slate-700 mb-3">负责人 & 最近更新</h3>
                <div className="space-y-2 text-sm">
                  <div className="flex justify-between"><span className="text-slate-500">销售负责人</span><span>{sp.sales_person || '-'}</span></div>
                  <div className="flex justify-between"><span className="text-slate-500">运营负责人</span><span>{sp.ops_person || '-'}</span></div>
                  <div className="flex justify-between"><span className="text-slate-500">设计负责人</span><span>{sp.design_person || '-'}</span></div>
                  <div className="flex justify-between"><span className="text-slate-500">最近更新人</span><span>{sp.last_update_person || '-'}</span></div>
                  <div className="flex justify-between"><span className="text-slate-500">最近更新时间</span><span>{sp.last_update_time?.slice(0, 16) || '-'}</span></div>
                </div>
                {sp.last_work_summary && (
                  <div className="mt-3 p-2 bg-slate-50 rounded text-xs text-slate-600">
                    <span className="font-medium">最近工作:</span> {sp.last_work_summary}
                  </div>
                )}
              </CardContent></Card>

              <Card className={`border-slate-200 ${hasIssue(sp) ? 'border-red-300' : ''}`}><CardContent className="p-5">
                <h3 className="text-sm font-semibold text-slate-700 mb-3">问题卡点</h3>
                {hasIssue(sp) ? (
                  <div className="space-y-2 text-sm">
                    <div className="flex justify-between"><span className="text-slate-500">问题状态</span><Badge className={issueStatusColors[sp.issue_status]}>{issueStatusLabels[sp.issue_status]}</Badge></div>
                    <div className="flex justify-between"><span className="text-slate-500">发现时间</span><span>{sp.issue_found_date || '-'}</span></div>
                    <div className="flex justify-between"><span className="text-slate-500">负责人</span><span>{sp.issue_owner || '-'}</span></div>
                    {sp.issue_description && <div className="p-2 bg-red-50 rounded text-xs text-red-700">{sp.issue_description}</div>}
                    {canEdit && isWaitingForClientMaterial(sp) && (
                      <Button
                        size="sm"
                        variant="outline"
                        className="w-full border-emerald-200 bg-emerald-50 text-emerald-700 hover:bg-emerald-100"
                        onClick={() => handleClientMaterialReceived(sp)}
                      >
                        <CheckCircle2 className="w-3.5 h-3.5 mr-1" /> 客户资料已收到，解除卡点并推进
                      </Button>
                    )}
                  </div>
                ) : (
                  <p className="text-sm text-green-600 flex items-center gap-1"><CheckCircle2 className="w-4 h-4" /> 当前无问题</p>
                )}
              </CardContent></Card>

              <Card className="border-slate-200"><CardContent className="p-5">
                <h3 className="text-sm font-semibold text-slate-700 mb-3">任务概况</h3>
                <div className="grid grid-cols-2 gap-3">
                  <div className="text-center p-2 bg-slate-50 rounded"><div className="text-lg font-bold text-slate-700">{ts.total}</div><div className="text-xs text-slate-500">总任务</div></div>
                  <div className="text-center p-2 bg-green-50 rounded"><div className="text-lg font-bold text-green-600">{ts.completed}</div><div className="text-xs text-slate-500">已完成</div></div>
                  <div className="text-center p-2 bg-red-50 rounded"><div className="text-lg font-bold text-red-600">{ts.overdue}</div><div className="text-xs text-slate-500">逾期</div></div>
                  <div className="text-center p-2 bg-amber-50 rounded"><div className="text-lg font-bold text-amber-600">{ts.waitingClient}</div><div className="text-xs text-slate-500">待客户</div></div>
                  <div className="text-center p-2 bg-orange-50 rounded col-span-2"><div className="text-lg font-bold text-orange-600">{ts.lowQuality}</div><div className="text-xs text-slate-500">低质量完成</div></div>
                </div>
                {ts.total > 0 && (
                  <div className="mt-3">
                    <div className="w-full bg-slate-200 rounded-full h-2">
                      <div className="h-2 rounded-full bg-green-500 transition-all" style={{ width: `${ts.total > 0 ? (ts.completed / ts.total * 100) : 0}%` }} />
                    </div>
                    <p className="text-xs text-slate-500 mt-1 text-center">任务完成率: {ts.total > 0 ? Math.round(ts.completed / ts.total * 100) : 0}%</p>
                  </div>
                )}
              </CardContent></Card>
            </div>
            {sp.notes && <Card className="border-slate-200"><CardContent className="p-4 text-sm text-slate-600"><span className="font-medium">备注:</span> {sp.notes}</CardContent></Card>}
          </TabsContent>

          <TabsContent value="tasks">
            <Card className="border-slate-200"><CardContent className="p-5">
              <div className="mb-4 flex items-center justify-between gap-3">
                <span className="text-sm font-medium text-slate-600">服务任务清单</span>
                {canAddServiceTask && (
                  <button
                    type="button"
                    onPointerDown={e => openCreateTaskSafely(sp, e)}
                    onClick={e => openCreateTaskSafely(sp, e)}
                    className="relative z-20 inline-flex h-9 shrink-0 items-center justify-center rounded-md bg-blue-600 px-4 text-sm font-medium text-white shadow-sm hover:bg-blue-700 active:bg-blue-800"
                  >
                    <Plus className="w-3.5 h-3.5 mr-1" /> 新增任务
                  </button>
                )}
              </div>
              {activeDetailTasks.length === 0 && completedDetailTasks.length === 0 ? (
                <div className="text-center py-8">
                  <p className="text-sm text-slate-400 mb-3">暂无任务</p>
                  {canAddServiceTask && (
                    <button
                      type="button"
                      onPointerDown={e => openCreateTaskSafely(sp, e)}
                      onClick={e => openCreateTaskSafely(sp, e)}
                      className="relative z-20 inline-flex h-9 items-center justify-center rounded-md border border-slate-200 bg-white px-4 text-sm font-medium text-slate-700 hover:bg-slate-50"
                    >
                      <Plus className="w-3.5 h-3.5 mr-1" /> 创建第一个任务
                    </button>
                  )}
                </div>
              ) : (
                <div className="space-y-2">
                  {activeDetailTasks.length > 0 && (
                    <div className="flex items-center justify-between rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-500">
                      <span className="font-medium text-slate-600">待处理任务</span>
                      <Badge className="bg-blue-100 text-blue-700">{activeDetailTasks.length} 个</Badge>
                    </div>
                  )}
                  {activeDetailTasks.length === 0 && completedDetailTasks.length > 0 && (
                    <div className="rounded-lg border border-green-100 bg-green-50 px-3 py-3 text-sm text-green-700">
                      当前没有待处理任务，已完成任务在下方查看。
                    </div>
                  )}
                  {[
                    ...activeDetailTasks.map(task => ({ task, showCompletedHeader: false })),
                    ...completedDetailTasks.map((task, index) => ({ task, showCompletedHeader: index === 0 })),
                  ].map(({ task: t, showCompletedHeader }) => {
                    const isTaskOverdue = t.due_date && t.due_date < todayStr() && t.status !== 'completed' && t.status !== 'cancelled';
                    const canTaskOperate = canOperateTask(t);
                    const isTaskActionSaving = savingTaskActionId === t.id;
                    return (
                      <div key={`${showCompletedHeader ? 'completed' : 'active'}-${t.id}`} className="space-y-2">
                        {showCompletedHeader && (
                          <div className="mt-4 flex items-center justify-between rounded-lg bg-green-50 px-3 py-2 text-xs text-green-700">
                            <span className="font-medium">已完成任务</span>
                            <Badge className="bg-green-100 text-green-700">{completedDetailTasks.length} 个</Badge>
                          </div>
                        )}
                        <div className={`p-3 rounded-lg border ${t.status === 'delayed' || isTaskOverdue ? 'border-red-200 bg-red-50/50' : t.status === 'completed' ? 'border-green-200 bg-green-50/30' : t.status === 'waiting_client' ? 'border-amber-200 bg-amber-50/30' : 'border-slate-200'} group`}>
                          <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-start">
                          <div className="min-w-0">
                            <div className="flex min-w-0 flex-1 items-center gap-2 flex-wrap">
                              <span className={`text-sm font-medium ${t.status === 'completed' ? 'line-through text-slate-400' : 'text-slate-700'}`}>{t.task_name}</span>
                              <Badge className={`text-[10px] ${taskStatusColors[t.status]}`}>{taskStatusLabels[t.status]}</Badge>
                              {t.platform && <Badge className="text-[10px] bg-blue-100 text-blue-700">{platformLabels[t.platform] || t.platform}</Badge>}
                              {t.status === 'completed' && t.completion_quality && (
                                <Badge className={`text-[10px] ${qualityColors[t.completion_quality] || 'bg-slate-100 text-slate-600'}`}>
                                  {qualityLabels[t.completion_quality] || t.completion_quality}
                                </Badge>
                              )}
                              <Badge className={`text-[10px] ${priorityColors[t.priority]}`}>{priorityLabels[t.priority]}</Badge>
                            </div>
                            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 mt-1 text-xs text-slate-500">
                              <span>类型: {taskTypeLabels[t.task_type] || t.task_type}</span>
                              <span>负责: {t.assignee_name || '-'}</span>
                              {t.due_date && <span className={isTaskOverdue ? 'text-red-600 font-medium' : ''}>截止: {t.due_date.slice(0, 10)}{isTaskOverdue ? ' ⚠️' : ''}</span>}
                              {t.completed_date && <span className="text-green-600">完成: {t.completed_date.slice(0, 10)} · {t.completed_by || '-'}</span>}
                            </div>
                            {t.status === 'completed' && (t.selected_copy_title || t.selected_material_title || t.completion_note) && (
                              <div className="mt-2 grid gap-1 text-xs text-slate-500">
                                {t.selected_copy_title && <span className="flex items-center gap-1"><Sparkles className="w-3 h-3 text-blue-500" /> 文案: {t.selected_copy_title}</span>}
                                {t.selected_material_title && <span className="flex items-center gap-1"><FileImage className="w-3 h-3 text-emerald-500" /> 素材: {t.selected_material_title}</span>}
                                {t.completion_note && <span className="flex items-center gap-1"><ClipboardCheck className="w-3 h-3 text-slate-400" /> 说明: {t.completion_note}</span>}
                              </div>
                            )}
                            {t.notes && <p className="text-xs text-slate-400 mt-1">{t.notes}</p>}
                          </div>
                          <div className="relative z-20 flex flex-wrap items-center justify-start gap-2 lg:w-[260px] lg:justify-end">
                            {t.status === 'completed' && (
                              <span className="inline-flex h-8 items-center justify-center rounded-md border border-green-200 bg-green-50 px-3 text-xs font-medium text-green-700">
                                <CheckCircle2 className="w-3.5 h-3.5 mr-1" /> 已完成
                              </span>
                            )}
                            {canTaskOperate && t.status !== 'completed' && t.status !== 'cancelled' && (
                              <button
                                type="button"
                                className="inline-flex h-8 items-center justify-center rounded-md border border-green-200 bg-green-50 px-3 text-xs font-medium text-green-700 hover:bg-green-100 disabled:opacity-50"
                                title="标记完成"
                                onPointerDown={e => {
                                  e.preventDefault();
                                  e.stopPropagation();
                                  void handleQuickTaskStatus(t, 'completed');
                                }}
                                onClick={e => {
                                  e.preventDefault();
                                  e.stopPropagation();
                                }}
                                disabled={isTaskActionSaving}
                              >
                                <CheckCircle2 className="w-3.5 h-3.5 mr-1" /> {isTaskActionSaving ? '处理中' : '完成'}
                              </button>
                            )}
                            {canTaskOperate && t.status === 'pending' && (
                              <button
                                type="button"
                                className="inline-flex h-8 items-center justify-center rounded-md border border-blue-200 bg-blue-50 px-3 text-xs font-medium text-blue-700 hover:bg-blue-100 disabled:opacity-50"
                                onPointerDown={e => {
                                  e.preventDefault();
                                  e.stopPropagation();
                                  void handleQuickTaskStatus(t, 'in_progress');
                                }}
                                onClick={e => {
                                  e.preventDefault();
                                  e.stopPropagation();
                                }}
                                disabled={isTaskActionSaving}
                              >
                                开始
                              </button>
                            )}
                            {canTaskOperate && t.status === 'waiting_client' && (
                              <button
                                type="button"
                                className="inline-flex h-8 items-center justify-center rounded-md border border-emerald-200 bg-emerald-50 px-3 text-xs font-medium text-emerald-700 hover:bg-emerald-100 disabled:opacity-50"
                                onPointerDown={e => {
                                  e.preventDefault();
                                  e.stopPropagation();
                                  void handleQuickTaskStatus(t, 'in_progress');
                                }}
                                onClick={e => {
                                  e.preventDefault();
                                  e.stopPropagation();
                                }}
                                disabled={isTaskActionSaving}
                              >
                                {isTaskActionSaving ? '处理中' : '资料已收到'}
                              </button>
                            )}
                            {canTaskOperate && t.status !== 'waiting_client' && t.status !== 'completed' && t.status !== 'cancelled' && (
                              <button
                                type="button"
                                className="inline-flex h-8 items-center justify-center rounded-md border border-amber-200 bg-amber-50 px-3 text-xs font-medium text-amber-700 hover:bg-amber-100 disabled:opacity-50"
                                onPointerDown={e => {
                                  e.preventDefault();
                                  e.stopPropagation();
                                  void handleQuickTaskStatus(t, 'waiting_client');
                                }}
                                onClick={e => {
                                  e.preventDefault();
                                  e.stopPropagation();
                                }}
                                disabled={isTaskActionSaving}
                              >
                                等客户
                              </button>
                            )}
                            {canEdit && (
                              <button
                                type="button"
                                className="inline-flex h-8 items-center justify-center rounded-md border border-slate-200 bg-white px-3 text-xs font-medium text-slate-700 hover:bg-slate-50"
                                onPointerDown={e => {
                                  e.preventDefault();
                                  e.stopPropagation();
                                  openEditTask(t);
                                }}
                                onClick={e => {
                                  e.preventDefault();
                                  e.stopPropagation();
                                }}
                              >
                                <Edit className="w-3.5 h-3.5 mr-1" /> 编辑
                              </button>
                            )}
                            {canDelete && (
                              <button
                                type="button"
                                className="inline-flex h-8 items-center justify-center rounded-md border border-red-200 bg-white px-3 text-xs font-medium text-red-600 hover:bg-red-50"
                                onPointerDown={e => {
                                  e.preventDefault();
                                  e.stopPropagation();
                                  setDeleteTarget({ type: 'task', item: t });
                                }}
                                onClick={e => {
                                  e.preventDefault();
                                  e.stopPropagation();
                                }}
                              >
                                <Trash2 className="w-3.5 h-3.5 mr-1" /> 删除
                              </button>
                            )}
                          </div>
                        </div>
                      </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </CardContent></Card>
          </TabsContent>

          <TabsContent value="timeline">
            <Card className="border-slate-200"><CardContent className="p-5">
              <h3 className="text-sm font-semibold text-slate-700 mb-4">服务时间线</h3>
              {timelineItems.length === 0 ? (
                <p className="text-sm text-slate-400 text-center py-4">暂无时间线记录</p>
              ) : (
                <div className="space-y-0">
                  {timelineItems.map((item, i) => (
                    <div key={i} className="flex gap-3 pb-4">
                      <div className="flex flex-col items-center">
                        <div className={`w-3 h-3 rounded-full shrink-0 ${
                          item.type === 'done' ? 'bg-green-500' :
                          item.type === 'update' ? 'bg-blue-500' :
                          item.type === 'issue' ? 'bg-red-500' :
                          item.type === 'task' ? 'bg-purple-400' :
                          'bg-slate-400'
                        }`} />
                        {i < timelineItems.length - 1 && <div className="w-px flex-1 bg-slate-200" />}
                      </div>
                      <div className="pb-2">
                        <p className="text-xs text-slate-400">{item.time.slice(0, 16)}</p>
                        <p className={`text-sm ${item.type === 'issue' ? 'text-red-700' : 'text-slate-700'}`}>{item.label}</p>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </CardContent></Card>
          </TabsContent>
        </Tabs>
        {renderTaskActionDialogs()}
      </div>
    );
  }

  // ==================== MAIN VIEW ====================
  if (loading) {
    return <div className="flex items-center justify-center py-12"><div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600" /></div>;
  }

  return (
    <div className="app-page space-y-5">
      {/* Header */}
      <div className="app-page-title flex-col sm:flex-row items-start sm:items-center">
        <div>
          <p className="text-xs font-medium uppercase tracking-[0.16em] text-blue-600">T24 Marketing · Delivery</p>
          <h2 className="mt-1 text-2xl font-bold text-slate-900">客户服务进度看板</h2>
          <p className="mt-1 text-sm text-slate-500">明确当前阶段、负责人和下一步动作，完成后自动归档查看</p>
        </div>
        <div className="flex gap-2 flex-wrap">
          <ExportButton
            data={exportData}
            columns={exportColumns}
            filename={`服务进度_${todayStr()}`}
            sheetName="服务进度"
          />
          <Button variant="outline" size="sm" onClick={() => setShowStats(!showStats)} className="gap-1.5"><BarChart3 className="w-4 h-4" /> {showStats ? '隐藏统计' : '显示统计'}</Button>
          <Button variant="outline" size="sm" onClick={loadData} className="gap-1.5"><RefreshCw className="w-4 h-4" /> 刷新</Button>
          {canCreate && <Button onClick={openCreateProgress} className="bg-blue-600 hover:bg-blue-700"><Plus className="w-4 h-4 mr-1" /> 手动新增服务</Button>}
        </div>
      </div>

      {canCreate && (
        <Card className="border-emerald-100 bg-emerald-50/70">
          <CardContent className="p-3">
            <div className="flex flex-col gap-2 text-sm text-emerald-800 md:flex-row md:items-center md:justify-between">
              <div className="flex items-start gap-2">
                <Info className="mt-0.5 h-4 w-4 shrink-0" />
                <p>
                  服务看板现在不会因为新增客户或补录历史成交自动生成。新客户需要交付时，请在成交管理打开“生成服务看板”开关，或在成交列表点击“看板”；旧客户补录可以保持关闭。
                </p>
              </div>
              <Button size="sm" variant="outline" className="border-emerald-200 bg-white text-emerald-700 hover:bg-emerald-100" onClick={() => { window.location.href = '/deals'; }}>
                去成交管理生成
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {showStats && (isAdmin || role === 'ops') && (
        <Card className="border-blue-100 bg-gradient-to-r from-blue-50 via-white to-emerald-50">
          <CardContent className="p-4">
            <div className="flex flex-col lg:flex-row lg:items-center gap-4">
              <div className="flex items-center gap-3 min-w-[210px]">
                <div className={`w-12 h-12 rounded-2xl flex items-center justify-center ${stats.healthScore >= 85 ? 'bg-green-100 text-green-700' : stats.healthScore >= 70 ? 'bg-amber-100 text-amber-700' : 'bg-red-100 text-red-700'}`}>
                  <ShieldCheck className="w-6 h-6" />
                </div>
                <div>
                  <p className="text-xs text-slate-500">运营健康分</p>
                  <div className="flex items-end gap-1">
                    <span className={`text-3xl font-bold ${stats.healthScore >= 85 ? 'text-green-700' : stats.healthScore >= 70 ? 'text-amber-700' : 'text-red-700'}`}>{stats.healthScore}</span>
                    <span className="text-xs text-slate-400 mb-1">/100</span>
                  </div>
                </div>
              </div>
              <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3 flex-1">
                <div className="bg-white/80 border border-slate-100 rounded-xl p-3">
                  <p className="text-xs text-slate-500">任务完成率</p>
                  <p className="text-lg font-semibold text-slate-800">{stats.completionRate}%</p>
                  <p className="text-[11px] text-slate-400">{stats.taskCompleted}/{stats.taskTotal} 已完成</p>
                </div>
                <div className="bg-white/80 border border-slate-100 rounded-xl p-3">
                  <p className="text-xs text-slate-500">本周平台更新</p>
                  <p className="text-lg font-semibold text-emerald-700">{stats.weeklyPlatformDone}/{stats.weeklyPlatformTarget}</p>
                  <p className="text-[11px] text-slate-400">每平台每周 3 次</p>
                </div>
                <div className="bg-white/80 border border-slate-100 rounded-xl p-3">
                  <p className="text-xs text-slate-500">周总结汇报</p>
                  <p className="text-lg font-semibold text-indigo-700">{stats.weeklyReportDone}/{stats.weeklyReportTarget}</p>
                  <p className="text-[11px] text-slate-400">每客户每周 1 次</p>
                </div>
                <div className="bg-white/80 border border-slate-100 rounded-xl p-3">
                  <p className="text-xs text-slate-500">当前待办</p>
                  <p className="text-lg font-semibold text-blue-700">{stats.taskPending}</p>
                  <p className="text-[11px] text-slate-400">需要继续处理</p>
                </div>
                <div className="bg-white/80 border border-slate-100 rounded-xl p-3">
                  <p className="text-xs text-slate-500">低质量完成</p>
                  <p className="text-lg font-semibold text-orange-700">{stats.lowQualityCompleted}</p>
                  <p className="text-[11px] text-slate-400">未选择文案/素材</p>
                </div>
                <div className="bg-white/80 border border-slate-100 rounded-xl p-3">
                  <p className="text-xs text-slate-500">逾期任务</p>
                  <p className="text-lg font-semibold text-red-700">{stats.taskOverdue}</p>
                  <p className="text-[11px] text-slate-400">需要优先处理</p>
                </div>
              </div>
            </div>
            {(stats.lowQualityCompleted > 0 || stats.taskOverdue > 0 || stats.longNoUpd > 0 || stats.weeklyMissingPlatforms > 0 || stats.weeklyMissingReports > 0) && (
              <div className="mt-3 flex items-start gap-2 text-xs text-slate-600 bg-white/70 border border-amber-100 rounded-lg p-2">
                <AlertTriangle className="w-4 h-4 text-amber-600 shrink-0 mt-0.5" />
                <span>
                  建议优先检查：
                  {stats.taskOverdue > 0 ? ` ${stats.taskOverdue} 个逾期任务` : ''}
                  {stats.lowQualityCompleted > 0 ? ` ${stats.lowQualityCompleted} 个低质量完成` : ''}
                  {stats.weeklyMissingPlatforms > 0 ? ` ${stats.weeklyMissingPlatforms} 个平台本周更新未达标` : ''}
                  {stats.weeklyMissingReports > 0 ? ` ${stats.weeklyMissingReports} 个客户本周总结未完成` : ''}
                  {stats.longNoUpd > 0 ? ` ${stats.longNoUpd} 个长期未更新客户` : ''}
                  。运营完成任务时选择对应文案或素材，系统会自动降低风险。
                </span>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Stats Panel */}
      {showStats && (isAdmin || role === 'ops') && (
        <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-3">
          {[
            { label: '服务中', value: stats.active, color: 'text-blue-600', bg: 'bg-blue-50' },
            { label: '有卡点', value: stats.withIssue, color: 'text-red-600', bg: 'bg-red-50' },
            { label: '已逾期', value: stats.overdueCount, color: 'text-amber-600', bg: 'bg-amber-50' },
            { label: '即将到期', value: stats.expiring, color: 'text-yellow-600', bg: 'bg-yellow-50' },
            { label: '本周更新', value: stats.updatedWeek, color: 'text-green-600', bg: 'bg-green-50' },
            { label: '长期未更新', value: stats.longNoUpd, color: 'text-slate-600', bg: 'bg-slate-50' },
            { label: '客户总数', value: stats.total, color: 'text-purple-600', bg: 'bg-purple-50' },
          ].map(s => (
            <div key={s.label} className={`${s.bg} rounded-lg p-3 text-center`}>
              <div className={`text-xl font-bold ${s.color}`}>{s.value}</div>
              <div className="text-xs text-slate-500">{s.label}</div>
            </div>
          ))}
        </div>
      )}

      {/* Ops workload */}
      {showStats && isAdmin && Object.keys(stats.opsMap).length > 0 && (
        <Card className="border-slate-200"><CardContent className="p-4">
          <h3 className="text-sm font-semibold text-slate-700 mb-2">运营工作量</h3>
          <div className="flex flex-wrap gap-4">
            {Object.entries(stats.opsMap).map(([name, data]) => (
              <div key={name} className="flex items-center gap-2 text-sm">
                <span className="font-medium text-slate-700">{name}</span>
                <Badge variant="secondary" className="text-xs">{data.total}客户</Badge>
                {data.completed > 0 && <Badge className="text-xs bg-green-100 text-green-700">{data.completed}完成</Badge>}
                {data.pending > 0 && <Badge className="text-xs bg-amber-100 text-amber-700">{data.pending}待办</Badge>}
                {data.lowQuality > 0 && <Badge className="text-xs bg-orange-100 text-orange-700">{data.lowQuality}低质量</Badge>}
                {data.issues > 0 && <Badge className="text-xs bg-red-100 text-red-700">{data.issues}卡点</Badge>}
              </div>
            ))}
          </div>
        </CardContent></Card>
      )}

      {showStats && (isAdmin || role === 'ops') && (
        <Card className="border-slate-200">
          <CardContent className="p-4">
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-3 mb-3">
              <div>
                <h3 className="text-sm font-semibold text-slate-700">本周待完成清单</h3>
                <p className="text-xs text-slate-400 mt-0.5">按套餐自动计算：合作平台每周更新 3 次，客户每周总结汇报 1 次。</p>
              </div>
              {canCreate && (
                <Button
                  size="sm"
                  onClick={() => handleGenerateWeeklyTasks()}
                  disabled={generatingWeeklyTasks || filteredWeeklyActionItems.every(item => item.plan.totalRemainingToCreate === 0)}
                  className="bg-emerald-600 hover:bg-emerald-700 text-white"
                >
                  <ClipboardCheck className="w-3.5 h-3.5 mr-1" />
                  {generatingWeeklyTasks ? '生成中...' : '一键生成本周任务'}
                </Button>
              )}
            </div>

            {filteredWeeklyActionItems.length === 0 ? (
              <div className="rounded-lg bg-green-50 border border-green-100 p-3 text-sm text-green-700 flex items-center gap-2">
                <CheckCircle2 className="w-4 h-4" />
                当前筛选范围内，本周运营目标都已达标或没有平台套餐客户。
              </div>
            ) : (
              <div className="space-y-2">
                {filteredWeeklyActionItems.slice(0, 8).map(({ sp, plan }) => {
                  const createCount = plan.totalRemainingToCreate;
                  return (
                    <div key={sp.id} className="rounded-lg border border-slate-100 bg-slate-50/70 p-3">
                      <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-2">
                        <div className="min-w-0">
                          <div className="flex items-center gap-2 flex-wrap">
                            <button className="font-medium text-sm text-blue-700 hover:underline" onClick={() => openDetail(sp)}>
                              {sp.customer_name}
                            </button>
                            <Badge variant="secondary" className="text-[10px]">{sp.ops_person || '未分配运营'}</Badge>
                            <Badge className="text-[10px] bg-slate-100 text-slate-700">{sp.package_name || '未填写套餐'}</Badge>
                          </div>
                          <div className="flex flex-wrap gap-1 mt-2">
                            {plan.platformPlans.filter(item => item.remainingToDo > 0).map(item => (
                              <Badge key={item.platform} className={`text-[10px] ${item.remainingToCreate > 0 ? 'bg-orange-100 text-orange-700' : 'bg-blue-100 text-blue-700'}`}>
                                {platformLabels[item.platform] || item.platform} 还差 {item.remainingToDo} 次{item.scheduled > 0 ? `，已排 ${item.scheduled}` : ''}
                              </Badge>
                            ))}
                            {plan.reportRemainingToDo > 0 && (
                              <Badge className={`text-[10px] ${plan.reportRemainingToCreate > 0 ? 'bg-orange-100 text-orange-700' : 'bg-blue-100 text-blue-700'}`}>
                                周总结未完成{plan.reportScheduled ? '，已排' : ''}
                              </Badge>
                            )}
                          </div>
                        </div>
                        {canCreate && (
                          <Button
                            size="sm"
                            variant={createCount > 0 ? 'default' : 'outline'}
                            disabled={generatingWeeklyTasks || createCount === 0}
                            onClick={() => handleGenerateWeeklyTasks([sp])}
                            className={createCount > 0 ? 'bg-blue-600 hover:bg-blue-700 text-white' : ''}
                          >
                            {createCount > 0 ? `生成 ${createCount} 个任务` : '已排任务'}
                          </Button>
                        )}
                      </div>
                    </div>
                  );
                })}
                {filteredWeeklyActionItems.length > 8 && (
                  <p className="text-xs text-slate-400 text-center pt-1">还有 {filteredWeeklyActionItems.length - 8} 个客户未展示，可通过筛选负责人或客户名称查看。</p>
                )}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Quick Filters */}
      <div className="flex gap-2 flex-wrap">
        {(Object.entries(quickFilterLabels) as [QuickFilter, string][]).map(([k, v]) => (
          <Button key={k} variant={quickFilter === k ? 'default' : 'outline'} size="sm"
            className={`h-7 text-xs ${quickFilter === k ? 'bg-blue-600 hover:bg-blue-700 text-white' : ''}`}
            onClick={() => setQuickFilter(quickFilter === k ? 'all' : k)}
          >{v}
            {k === 'has_issue' && stats.withIssue > 0 && <span className="ml-1 text-[10px]">({stats.withIssue})</span>}
            {k === 'overdue' && stats.overdueCount > 0 && <span className="ml-1 text-[10px]">({stats.overdueCount})</span>}
            {k === 'long_no_update' && stats.longNoUpd > 0 && <span className="ml-1 text-[10px]">({stats.longNoUpd})</span>}
          </Button>
        ))}
      </div>

      {/* Search & Filters */}
      <Card className="border-slate-200"><CardContent className="p-3 space-y-3">
        <div className="flex flex-col sm:flex-row gap-3">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
            <Input placeholder="搜索客户名称、负责人..." value={search} onChange={e => setSearch(e.target.value)} className="pl-9" />
          </div>
          <div className="flex gap-2">
            <div className="flex border border-slate-200 rounded-md overflow-hidden">
              <button className={`px-3 py-2 text-xs flex items-center gap-1 ${viewMode === 'list' ? 'bg-blue-600 text-white' : 'bg-white text-slate-600 hover:bg-slate-50'}`} onClick={() => setViewMode('list')}><LayoutList className="w-3.5 h-3.5" /> 列表</button>
              <button className={`px-3 py-2 text-xs flex items-center gap-1 ${viewMode === 'kanban' ? 'bg-blue-600 text-white' : 'bg-white text-slate-600 hover:bg-slate-50'}`} onClick={() => setViewMode('kanban')}><Kanban className="w-3.5 h-3.5" /> 看板</button>
              <button className={`px-3 py-2 text-xs flex items-center gap-1 ${viewMode === 'employee' ? 'bg-blue-600 text-white' : 'bg-white text-slate-600 hover:bg-slate-50'}`} onClick={() => setViewMode('employee')}><Users className="w-3.5 h-3.5" /> 员工</button>
            </div>
            <Button variant={showFilters ? 'default' : 'outline'} size="sm" className={`h-10 gap-1.5 ${showFilters ? 'bg-blue-600 hover:bg-blue-700 text-white' : ''}`} onClick={() => setShowFilters(!showFilters)}>
              <Filter className="w-4 h-4" /> 筛选
            </Button>
          </div>
        </div>
        {showFilters && (
          <div className="border-t border-slate-200 pt-3">
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
              <div><label className="text-xs text-slate-500 mb-1 block">行业</label><NativeSelect value={filters.industry} onChange={v => setFilters({ ...filters, industry: v })} options={[{ value: 'all', label: '全部' }, ...Object.entries(industryLabels).map(([k, v]) => ({ value: k, label: v }))]} /></div>
              <div><label className="text-xs text-slate-500 mb-1 block">服务类型</label><NativeSelect value={filters.service_type} onChange={v => setFilters({ ...filters, service_type: v })} options={[{ value: 'all', label: '全部' }, ...Object.entries(serviceTypeLabels).map(([k, v]) => ({ value: k, label: v }))]} /></div>
              <div><label className="text-xs text-slate-500 mb-1 block">服务阶段</label><NativeSelect value={filters.service_stage} onChange={v => setFilters({ ...filters, service_stage: v })} options={[{ value: 'all', label: '全部' }, ...Object.entries(allStageLabels).map(([k, v]) => ({ value: k, label: v }))]} /></div>
              <div><label className="text-xs text-slate-500 mb-1 block">运营负责人</label><Input placeholder="运营" value={filters.ops_person} onChange={e => setFilters({ ...filters, ops_person: e.target.value })} className="h-9 text-sm" /></div>
              <div><label className="text-xs text-slate-500 mb-1 block">销售负责人</label><Input placeholder="销售" value={filters.sales_person} onChange={e => setFilters({ ...filters, sales_person: e.target.value })} className="h-9 text-sm" /></div>
              <div><label className="text-xs text-slate-500 mb-1 block">问题状态</label><NativeSelect value={filters.issue_status} onChange={v => setFilters({ ...filters, issue_status: v })} options={[{ value: 'all', label: '全部' }, ...Object.entries(issueStatusLabels).map(([k, v]) => ({ value: k, label: v }))]} /></div>
            </div>
            <div className="flex justify-end mt-2">
              <Button size="sm" variant="ghost" className="text-xs text-slate-500" onClick={() => setFilters({ industry: 'all', service_type: 'all', service_stage: 'all', ops_person: '', sales_person: '', issue_status: 'all' })}>
                重置筛选
              </Button>
            </div>
          </div>
        )}
      </CardContent></Card>

      <div className="text-xs text-slate-500">共 {filtered.length} 条{filtered.length !== progresses.length ? ` (筛选自 ${progresses.length} 条)` : ''}</div>

      {/* LIST VIEW */}
      {viewMode === 'list' && (
        <>
          <div className="grid md:grid-cols-2 xl:grid-cols-3 gap-4">
            {filtered.length === 0 ? (
              <div className="col-span-full text-center text-slate-400 py-12">
                <p className="mb-3">暂无匹配的服务记录</p>
                {canCreate && (
                  <Button variant="outline" onClick={openCreateProgress}>
                    <Plus className="w-4 h-4 mr-1" /> 新增第一条服务记录
                  </Button>
                )}
              </div>
            ) : paginatedProgresses.items.map(sp => <ProgressCard key={sp.id} sp={sp} />)}
          </div>
          <ProgressPaginationFooter />
        </>
      )}

      {/* KANBAN VIEW */}
      {viewMode === 'kanban' && (
        <div className="flex gap-4 overflow-x-auto pb-4">
          {kanbanColumns.map(col => {
            const items = filtered.filter(sp => col.stages.includes(sp.service_stage));
            return (
              <div key={col.key} className="min-w-[280px] max-w-[320px] flex-shrink-0">
                <div className="bg-slate-100 rounded-t-lg px-3 py-2 flex items-center justify-between">
                  <span className="text-sm font-semibold text-slate-700">{col.label}</span>
                  <Badge variant="secondary" className="text-xs">{items.length}</Badge>
                </div>
                <div className="bg-slate-50 rounded-b-lg p-2 space-y-2 min-h-[200px]">
                  {items.length === 0 ? (
                    <p className="text-xs text-slate-400 text-center py-8">暂无</p>
                  ) : items.map(sp => {
                    const nextStage = getNextStage(sp.service_type, sp.service_stage);
                    return (
                      <div key={sp.id} className={`p-3 bg-white rounded-lg border cursor-pointer hover:shadow-sm transition-shadow ${hasIssue(sp) ? 'border-red-300' : 'border-slate-200'}`} onClick={() => openDetail(sp)}>
                        <div className="flex items-center justify-between mb-1">
                          <span className="text-sm font-medium text-slate-800 truncate">{sp.customer_name}</span>
                          <span className="text-xs font-bold text-blue-600">{sp.progress_percent}%</span>
                        </div>
                        <div className="w-full bg-slate-200 rounded-full h-1 mb-1.5">
                          <div className={`h-1 rounded-full ${sp.progress_percent >= 100 ? 'bg-green-500' : 'bg-blue-500'}`} style={{ width: `${Math.min(sp.progress_percent, 100)}%` }} />
                        </div>
                        <div className="flex items-center gap-2 text-xs text-slate-500">
                          <span>{sp.ops_person || '-'}</span>
                          {hasIssue(sp) && <AlertTriangle className="w-3 h-3 text-red-500" />}
                          {isOverdue(sp) && <Clock className="w-3 h-3 text-red-500" />}
                        </div>
                        {/* Kanban quick actions */}
                        {canEdit && (
                          <div className="flex gap-1 mt-1.5 pt-1.5 border-t border-slate-100" onClick={e => e.stopPropagation()}>
                            <Button size="sm" variant="ghost" className="h-5 px-1.5 text-[10px] text-slate-400 hover:text-blue-600" onClick={() => openEditProgress(sp)}>编辑</Button>
                            {nextStage && (
                              <Button size="sm" variant="ghost" className="h-5 px-1.5 text-[10px] text-slate-400 hover:text-green-600" onClick={() => handleAdvanceStage(sp)}>
                                → {allStageLabels[nextStage]?.slice(0, 4)}
                              </Button>
                            )}
                            <Button size="sm" variant="ghost" className="h-5 px-1.5 text-[10px] text-slate-400 hover:text-blue-600" onClick={() => openQuickUpdate(sp)}>摘要</Button>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* EMPLOYEE VIEW */}
      {viewMode === 'employee' && (() => {
        const opsGroups: Record<string, ServiceProgress[]> = {};
        filtered.forEach(sp => {
          const key = sp.ops_person || '未分配';
          if (!opsGroups[key]) opsGroups[key] = [];
          opsGroups[key].push(sp);
        });
        return (
          <div className="space-y-6">
            {Object.entries(opsGroups).map(([opsName, items]) => {
              const opsStats = stats.opsMap[opsName];
              return (
                <div key={opsName}>
                  <div className="flex items-center gap-3 mb-3">
                    <h3 className="text-sm font-semibold text-slate-700">{opsName}</h3>
                    <Badge variant="secondary">{items.length} 客户</Badge>
                    <Badge className="bg-red-100 text-red-700 text-xs">{items.filter(i => hasIssue(i)).length} 卡点</Badge>
                    <Badge className="bg-red-100 text-red-700 text-xs">{items.filter(i => isOverdue(i)).length} 逾期</Badge>
                    {opsStats && opsStats.pending > 0 && <Badge className="bg-blue-100 text-blue-700 text-xs">{opsStats.pending} 待办任务</Badge>}
                  </div>
                  <div className="grid md:grid-cols-2 xl:grid-cols-3 gap-3">
                    {items.map(sp => <ProgressCard key={sp.id} sp={sp} />)}
                  </div>
                </div>
              );
            })}
            {Object.keys(opsGroups).length === 0 && <p className="text-center text-slate-400 py-12">暂无数据</p>}
          </div>
        );
      })()}

      {/* ==================== DIALOGS ==================== */}
      <ConfirmDialog open={!!deleteTarget} onOpenChange={v => { if (!v) setDeleteTarget(null); }} title={deleteTarget?.type === 'progress' ? '确认删除服务进度' : '确认删除任务'} description={deleteTarget?.type === 'progress' ? `确定要删除「${deleteTarget?.item?.customer_name}」的服务进度记录吗？关联的所有任务也将被删除。此操作不可撤销。` : `确定要删除任务「${deleteTarget?.item?.task_name}」吗？此操作不可撤销。`} onConfirm={handleDelete} loading={deleting} />

      {/* Quick Update Work Summary Dialog */}
      <Dialog open={showQuickUpdate} onOpenChange={v => { if (!v) setShowQuickUpdate(false); }}>
        <DialogContent className="max-w-md">
          <DialogHeader><DialogTitle>更新工作摘要 - {quickUpdateSp?.customer_name}</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <div>
              <Label>最近工作摘要</Label>
              <Textarea
                value={quickUpdateSummary}
                onChange={e => setQuickUpdateSummary(e.target.value)}
                rows={4}
                placeholder="例如：本周已完成 Facebook 内容更新和 Google Business 图片上传"
              />
            </div>
          </div>
          <div className="flex justify-end gap-2 mt-4">
            <Button variant="outline" onClick={() => setShowQuickUpdate(false)}>取消</Button>
            <Button onClick={handleQuickUpdateSave} disabled={savingQuickUpdate} className="bg-blue-600 hover:bg-blue-700">{savingQuickUpdate ? '保存中...' : '保存'}</Button>
          </div>
        </DialogContent>
      </Dialog>

      {/* Complete Task Dialog */}
      <Dialog open={!!completeTaskTarget} onOpenChange={v => { if (!v) setCompleteTaskTarget(null); }}>
        <DialogContent className="max-w-xl max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>完成任务 - {completeTaskTarget?.task_name}</DialogTitle>
          </DialogHeader>
          {loadingCompletionRefs ? (
            <div className="py-8 text-center">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600 mx-auto mb-3" />
              <p className="text-sm text-slate-500">正在加载该客户的文案和素材...</p>
            </div>
          ) : (
            <div className="space-y-4">
              <div className="rounded-lg border border-blue-100 bg-blue-50 p-3 text-sm text-blue-800 flex gap-2">
                <ClipboardCheck className="w-4 h-4 shrink-0 mt-0.5" />
                <span>
                  {requiresCompletionReference(completeTaskTarget)
                    ? '内容发布、评论回复、周报类任务建议选择实际使用的文案或素材；如果都不选也可以完成，但系统会标记为低质量完成。'
                    : '流程类任务可以直接确认完成；如果有相关文案或素材，也可以顺手选择，方便后续追踪。'}
                </span>
              </div>

              <div>
                <Label>本次完成平台</Label>
                <NativeSelect
                  value={completionForm.platform}
                  onChange={v => setCompletionForm({ ...completionForm, platform: v })}
                  options={[
                    { value: '', label: '不限定平台 / 周总结汇报' },
                    ...Array.from(new Set([...completionContractPlatforms, ...Object.keys(platformLabels).filter(key => key !== 'general')])).map(platform => ({
                      value: platform,
                      label: completionContractPlatforms.includes(platform)
                        ? `${platformLabels[platform] || platform}（套餐合作平台）`
                        : platformLabels[platform] || platform,
                    })),
                  ]}
                />
                <p className="text-xs text-slate-400 mt-1">平台更新任务需要选择对应平台；周总结汇报可以选择“不限定平台”。</p>
              </div>

              <div className="grid md:grid-cols-2 gap-4">
                <div>
                  <Label className="flex items-center gap-1.5"><Sparkles className="w-3.5 h-3.5 text-blue-500" /> 使用文案</Label>
                  <NativeSelect
                    value={completionForm.selected_copy_id}
                    onChange={v => {
                      const nextCopy = completionCopies.find(item => String(item.id) === v);
                      setCompletionForm({
                        ...completionForm,
                        selected_copy_id: v,
                        platform: completionForm.platform || (nextCopy?.platform && nextCopy.platform !== 'general' ? nextCopy.platform : ''),
                      });
                    }}
                    options={[
                      { value: '', label: completionCopies.length ? '不选择文案' : '暂无可选文案' },
                      ...completionCopies.map(item => ({
                        value: String(item.id),
                        label: `${item.title || `文案 #${item.id}`} · ${platformLabels[item.platform] || item.platform} · ${copyTypeLabels[item.content_type] || item.content_type}`,
                      })),
                    ]}
                  />
                  {selectedCompletionCopy && (
                    <div className="mt-2 rounded-md bg-slate-50 border border-slate-100 p-2 text-xs text-slate-600 max-h-28 overflow-y-auto">
                      <p className="font-medium text-slate-700 mb-1">{selectedCompletionCopy.title}</p>
                      <p className="whitespace-pre-wrap line-clamp-4">{selectedCompletionCopy.content}</p>
                    </div>
                  )}
                </div>

                <div>
                  <Label className="flex items-center gap-1.5"><FileImage className="w-3.5 h-3.5 text-emerald-500" /> 使用素材</Label>
                  <NativeSelect
                    value={completionForm.selected_material_id}
                    onChange={v => {
                      const nextMaterial = completionMaterials.find(item => String(item.id) === v);
                      setCompletionForm({
                        ...completionForm,
                        selected_material_id: v,
                        platform: completionForm.platform || (nextMaterial?.platform && nextMaterial.platform !== 'general' ? nextMaterial.platform : ''),
                      });
                    }}
                    options={[
                      { value: '', label: completionMaterials.length ? '不选择素材' : '暂无可选素材' },
                      ...completionMaterials.map(item => ({
                        value: String(item.id),
                        label: `${item.title || item.file_name || `素材 #${item.id}`} · ${platformLabels[item.platform] || item.platform || '通用'} · ${materialTypeLabels[item.material_type] || item.material_type}`,
                      })),
                    ]}
                  />
                  {selectedCompletionMaterial && (
                    <div className="mt-2 rounded-md bg-slate-50 border border-slate-100 p-2 text-xs text-slate-600">
                      <p className="font-medium text-slate-700 mb-1">{selectedCompletionMaterial.title}</p>
                      <div className="flex flex-wrap gap-1">
                        <Badge className="text-[10px] bg-emerald-100 text-emerald-700">{materialTypeLabels[selectedCompletionMaterial.material_type] || selectedCompletionMaterial.material_type}</Badge>
                        <Badge className="text-[10px] bg-blue-100 text-blue-700">{platformLabels[selectedCompletionMaterial.platform] || selectedCompletionMaterial.platform || '通用'}</Badge>
                        <Badge className="text-[10px] bg-slate-100 text-slate-700">{selectedCompletionMaterial.usage_status || '未使用'}</Badge>
                      </div>
                      {selectedCompletionMaterial.file_url && <p className="mt-1 truncate text-blue-600">{selectedCompletionMaterial.file_url}</p>}
                    </div>
                  )}
                </div>
              </div>

              <div>
                <Label>完成说明</Label>
                <Textarea
                  value={completionForm.completion_note}
                  onChange={e => setCompletionForm({ ...completionForm, completion_note: e.target.value })}
                  rows={3}
                  placeholder="例如：已用菜单图生成本周 Google 商家更新文案，等待客户确认图片。"
                />
              </div>

              {requiresCompletionReference(completeTaskTarget) && !completionForm.selected_copy_id && !completionForm.selected_material_id && (
                <div className="rounded-lg border border-orange-200 bg-orange-50 p-3 text-xs text-orange-800 flex gap-2">
                  <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
                  <span>当前没有选择文案或素材，保存后会计入“低质量完成”。如果客户确实没有素材，可以在完成说明里写清楚原因。</span>
                </div>
              )}

              {completeTaskTarget?.task_type === 'publish_content' && !completionForm.platform && (
                <div className="rounded-lg border border-indigo-200 bg-indigo-50 p-3 text-xs text-indigo-800 flex gap-2">
                  <Info className="w-4 h-4 shrink-0 mt-0.5" />
                  <span>当前没有选择平台，这次完成不会计入平台每周 3 次更新；如果这是周总结汇报，可以保持不限定平台。</span>
                </div>
              )}
            </div>
          )}
          <div className="flex justify-end gap-2 mt-4">
            <Button variant="outline" onClick={() => setCompleteTaskTarget(null)}>取消</Button>
            <Button onClick={handleCompleteTask} disabled={savingCompletion || loadingCompletionRefs} className="bg-green-600 hover:bg-green-700">
              {savingCompletion ? '保存中...' : '确认完成'}
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      {/* ==================== SMART Progress Form Dialog ==================== */}
      <Dialog open={showProgressForm} onOpenChange={setShowProgressForm}>
        <DialogContent className="max-w-2xl max-h-[85vh] overflow-y-auto">
          <DialogHeader><DialogTitle>{editingProgressId ? '编辑服务进度' : '新增服务进度'}</DialogTitle></DialogHeader>

          {/* Section 1: Customer Selection */}
          <div className="space-y-4">
            <div className="bg-blue-50 border border-blue-200 rounded-lg p-3">
              <h4 className="text-sm font-semibold text-blue-800 mb-2 flex items-center gap-1.5"><Search className="w-4 h-4" /> 选择客户</h4>
              <div className="relative" ref={customerDropdownRef}>
                <Input
                  placeholder="搜索客户名称、编号、联系人、电话..."
                  value={customerSearch}
                  onChange={e => {
                    setCustomerSearch(e.target.value);
                    setShowCustomerDropdown(true);
                    if (!e.target.value.trim()) {
                      setSelectedCustomerState(null);
                      setProgressForm(prev => ({ ...prev, customer_id: 0, customer_name: '' }));
                    }
                  }}
                  onFocus={() => setShowCustomerDropdown(true)}
                  className="bg-white"
                />
                {showCustomerDropdown && filteredCustomers.length > 0 && (
                  <div className="absolute z-50 top-full left-0 right-0 mt-1 bg-white border border-slate-200 rounded-lg shadow-lg max-h-60 overflow-y-auto">
                    {filteredCustomers.map(c => (
                      <div
                        key={c.id}
                        className={`px-3 py-2.5 hover:bg-blue-50 cursor-pointer border-b border-slate-100 last:border-0 ${selectedCustomer?.id === c.id ? 'bg-blue-50' : ''}`}
                        onClick={() => handleSelectCustomer(c)}
                      >
                        <div className="flex items-center justify-between">
                          <span className="font-medium text-sm text-slate-800">{c.business_name}</span>
                          <span className="text-xs text-slate-400 font-mono">{c.customer_code || `#${c.id}`}</span>
                        </div>
                        <div className="flex items-center gap-3 text-xs text-slate-500 mt-0.5">
                          <span>{displayCountry(c.country)}{c.state ? ` · ${c.state}` : ''}{c.city ? ` · ${c.city}` : ''}</span>
                          <span>{industryLabels[c.industry] || c.industry}</span>
                          {c.sales_person && <span>销售: {c.sales_person}</span>}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
                {showCustomerDropdown && customerSearch.trim() && filteredCustomers.length === 0 && (
                  <div className="absolute z-50 top-full left-0 right-0 mt-1 bg-white border border-slate-200 rounded-lg shadow-lg p-4 text-center text-sm text-slate-400">
                    未找到匹配的客户
                  </div>
                )}
              </div>
            </div>

            {/* Section 2: Auto-populated customer info (read-only) */}
            {selectedCustomer && (
              <div className="bg-slate-50 border border-slate-200 rounded-lg p-3">
                <h4 className="text-sm font-semibold text-slate-600 mb-2 flex items-center gap-1.5"><Info className="w-4 h-4" /> 客户档案信息（自动带出）</h4>
                <div className="grid grid-cols-2 sm:grid-cols-3 gap-x-4 gap-y-2 text-sm">
                  <div><span className="text-slate-400 text-xs">客户ID</span><p className="text-slate-700 font-mono">{progressForm.customer_id}</p></div>
                  <div><span className="text-slate-400 text-xs">行业</span><p className="text-slate-700">{industryLabels[progressForm.industry] || progressForm.industry}</p></div>
                  <div><span className="text-slate-400 text-xs">国家</span><p className="text-slate-700">{displayCountry(progressForm.country)}</p></div>
                  <div><span className="text-slate-400 text-xs">州/省</span><p className="text-slate-700">{progressForm.state ? getStateLabel(progressForm.country, progressForm.state) : '-'}</p></div>
                  <div><span className="text-slate-400 text-xs">城市</span><p className="text-slate-700">{progressForm.city || <span className="text-amber-500 text-xs">⚠ 客户档案缺少城市信息</span>}</p></div>
                  <div><span className="text-slate-400 text-xs">套餐名称</span><p className="text-slate-700">{progressForm.package_name || '-'}</p></div>
                  <div><span className="text-slate-400 text-xs">服务开始日期</span><p className="text-slate-700">{progressForm.service_start_date || '-'}</p></div>
                  <div><span className="text-slate-400 text-xs">服务到期日期</span><p className="text-slate-700">{progressForm.service_end_date || '-'}</p></div>
                </div>
              </div>
            )}

            {/* Section 3: Service-specific editable fields */}
            <div className="border border-slate-200 rounded-lg p-3 space-y-3">
              <h4 className="text-sm font-semibold text-slate-600">本次服务进度信息</h4>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <Label>服务类型</Label>
                  <NativeSelect
                    value={progressForm.service_type}
                    onChange={v => {
                      const currentStageValid = isStageValidForType(v, progressForm.service_stage);
                      const newStage = currentStageValid ? progressForm.service_stage : getFirstStageForType(v);
                      const defaultProg = getDefaultProgress(v, newStage);
                      setProgressForm({
                        ...progressForm,
                        service_type: v,
                        service_stage: newStage,
                        progress_percent: defaultProg >= 0 ? defaultProg : progressForm.progress_percent,
                      });
                    }}
                    options={Object.entries(serviceTypeLabels).map(([k, v]) => ({ value: k, label: v }))}
                  />
                </div>
                <div>
                  <Label>服务阶段</Label>
                  <NativeSelect
                    value={progressForm.service_stage}
                    onChange={v => {
                      const defaultProg = getDefaultProgress(progressForm.service_type, v);
                      setProgressForm({
                        ...progressForm,
                        service_stage: v,
                        progress_percent: defaultProg >= 0 ? defaultProg : progressForm.progress_percent,
                      });
                    }}
                    options={(() => {
                      const stages = getStagesForType(progressForm.service_type);
                      const opts = Object.entries(stages).map(([k, v]) => ({ value: k, label: v }));
                      if (progressForm.service_stage && !stages[progressForm.service_stage]) {
                        const legacyLabel = allStageLabels[progressForm.service_stage] || progressForm.service_stage;
                        opts.unshift({ value: progressForm.service_stage, label: `${legacyLabel} (旧阶段)` });
                      }
                      return opts;
                    })()}
                  />
                </div>
                <div>
                  <Label>进度百分比 ({progressForm.progress_percent}%)</Label>
                  <div className="flex items-center gap-2">
                    <Input
                      type="number"
                      min={0}
                      max={100}
                      value={progressForm.progress_percent}
                      onChange={e => {
                        const val = Math.max(0, Math.min(100, Number(e.target.value) || 0));
                        setProgressForm({ ...progressForm, progress_percent: val });
                      }}
                      className="w-20"
                    />
                    <div className="flex-1 bg-slate-200 rounded-full h-2">
                      <div className={`h-2 rounded-full transition-all ${progressForm.progress_percent >= 100 ? 'bg-green-500' : progressForm.progress_percent >= 60 ? 'bg-blue-500' : 'bg-amber-500'}`} style={{ width: `${Math.min(progressForm.progress_percent, 100)}%` }} />
                    </div>
                  </div>
                </div>
                <div>
                  <Label>销售负责人</Label>
                  <NativeSelect
                    value={progressForm.sales_person}
                    onChange={v => setProgressForm({ ...progressForm, sales_person: v })}
                    options={[
                      { value: '', label: '请选择销售' },
                      ...salesEmployees.map(e => ({ value: e.name, label: e.name })),
                      ...(progressForm.sales_person && !salesEmployees.find(e => e.name === progressForm.sales_person) ? [{ value: progressForm.sales_person, label: `${progressForm.sales_person} (当前)` }] : []),
                    ]}
                  />
                </div>
                <div>
                  <Label>运营负责人</Label>
                  <NativeSelect
                    value={progressForm.ops_person}
                    onChange={v => setProgressForm({ ...progressForm, ops_person: v })}
                    options={[
                      { value: '', label: '请选择运营' },
                      ...opsEmployees.map(e => ({ value: e.name, label: e.name })),
                      ...(progressForm.ops_person && !opsEmployees.find(e => e.name === progressForm.ops_person) ? [{ value: progressForm.ops_person, label: `${progressForm.ops_person} (当前)` }] : []),
                    ]}
                  />
                </div>
                <div>
                  <Label>设计负责人</Label>
                  <NativeSelect
                    value={progressForm.design_person}
                    onChange={v => setProgressForm({ ...progressForm, design_person: v })}
                    options={[
                      { value: '', label: '请选择设计' },
                      ...designEmployees.map(e => ({ value: e.name, label: e.name })),
                      ...(progressForm.design_person && !designEmployees.find(e => e.name === progressForm.design_person) ? [{ value: progressForm.design_person, label: `${progressForm.design_person} (当前)` }] : []),
                    ]}
                  />
                </div>
                <div>
                  <Label>服务开始日期</Label>
                  <Input type="date" value={progressForm.service_start_date} onChange={e => setProgressForm({ ...progressForm, service_start_date: e.target.value })} className={!isAdmin ? 'bg-slate-50' : ''} readOnly={!isAdmin && !!progressForm.service_start_date} />
                </div>
                <div>
                  <Label>服务到期日期</Label>
                  <Input type="date" value={progressForm.service_end_date} onChange={e => setProgressForm({ ...progressForm, service_end_date: e.target.value })} />
                </div>
              </div>
            </div>

            {/* Section 4: Issue status */}
            <div className="border border-slate-200 rounded-lg p-3 space-y-3">
              <h4 className="text-sm font-semibold text-slate-600">问题卡点</h4>
              <div>
                <Label>问题状态</Label>
                <NativeSelect
                  value={progressForm.issue_status}
                  onChange={v => setProgressForm({ ...progressForm, issue_status: v, issue_found_date: v !== 'none' && !progressForm.issue_found_date ? todayStr() : progressForm.issue_found_date })}
                  options={Object.entries(issueStatusLabels).map(([k, v]) => ({ value: k, label: v }))}
                />
              </div>
              {progressForm.issue_status !== 'none' && (
                <div className="grid grid-cols-2 gap-4">
                  <div className="col-span-2"><Label>问题描述</Label><Textarea value={progressForm.issue_description} onChange={e => setProgressForm({ ...progressForm, issue_description: e.target.value })} rows={2} placeholder="描述具体问题..." /></div>
                  <div><Label>问题开始时间</Label><Input type="date" value={progressForm.issue_found_date} onChange={e => setProgressForm({ ...progressForm, issue_found_date: e.target.value })} /></div>
                  <div>
                    <Label>问题负责人</Label>
                    <NativeSelect
                      value={progressForm.issue_owner}
                      onChange={v => setProgressForm({ ...progressForm, issue_owner: v })}
                      options={[
                        { value: '', label: '请选择' },
                        ...activeEmployees.map(e => ({ value: e.name, label: e.name })),
                      ]}
                    />
                  </div>
                  <div className="flex items-center gap-3">
                    <label className="flex items-center gap-2 text-sm cursor-pointer">
                      <input type="checkbox" checked={progressForm.issue_resolved} onChange={e => setProgressForm({ ...progressForm, issue_resolved: e.target.checked, issue_resolved_date: e.target.checked ? todayStr() : '' })} className="rounded" />
                      已解决
                    </label>
                  </div>
                  {progressForm.issue_resolved && (
                    <div><Label>解决时间</Label><Input type="date" value={progressForm.issue_resolved_date} onChange={e => setProgressForm({ ...progressForm, issue_resolved_date: e.target.value })} /></div>
                  )}
                </div>
              )}
            </div>

            {/* Section 5: Work summary */}
            <div className="border border-slate-200 rounded-lg p-3 space-y-3">
              <h4 className="text-sm font-semibold text-slate-600">工作记录</h4>
              <div><Label>最近工作摘要</Label><Textarea value={progressForm.last_work_summary} onChange={e => setProgressForm({ ...progressForm, last_work_summary: e.target.value })} rows={3} placeholder="例如：本周已完成 Facebook 内容更新和 Google Business 图片上传" /></div>
              <div><Label>备注</Label><Textarea value={progressForm.notes} onChange={e => setProgressForm({ ...progressForm, notes: e.target.value })} rows={2} /></div>
            </div>
          </div>

          <div className="flex justify-end gap-2 mt-4">
            <Button variant="outline" onClick={() => setShowProgressForm(false)}>取消</Button>
            <Button onClick={handleSaveProgress} disabled={savingProgress} className="bg-blue-600 hover:bg-blue-700">{savingProgress ? '保存中...' : '保存'}</Button>
          </div>
        </DialogContent>
      </Dialog>

      {/* Task Form Dialog */}
      <Dialog open={showTaskForm} onOpenChange={setShowTaskForm}>
        <DialogContent className="max-w-lg max-h-[85vh] overflow-y-auto">
          <DialogHeader><DialogTitle>{editingTaskId ? '编辑任务' : '新增任务'} - {taskForm.customer_name}</DialogTitle></DialogHeader>
          <div className="space-y-4">
            <div><Label>任务名称 *</Label><Input value={taskForm.task_name} onChange={e => setTaskForm({ ...taskForm, task_name: e.target.value })} placeholder="例如：收集菜单图片" /></div>
            <div className="grid grid-cols-2 gap-4">
              <div><Label>任务类型</Label><NativeSelect value={taskForm.task_type} onChange={v => setTaskForm({ ...taskForm, task_type: v })} options={Object.entries(taskTypeLabels).map(([k, v]) => ({ value: k, label: v }))} /></div>
              <div>
                <Label>平台</Label>
                <NativeSelect
                  value={taskForm.platform}
                  onChange={v => setTaskForm({ ...taskForm, platform: v })}
                  options={[
                    { value: '', label: '不限定平台 / 周总结汇报' },
                    ...Object.entries(platformLabels)
                      .filter(([key]) => key !== 'general')
                      .map(([value, label]) => ({ value, label })),
                  ]}
                />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <Label>负责人</Label>
                <NativeSelect
                  value={taskForm.assignee_name}
                  onChange={v => setTaskForm({ ...taskForm, assignee_name: v })}
                  options={[
                    { value: '', label: '请选择' },
                    ...activeEmployees.map(e => ({ value: e.name, label: `${e.name} (${e.role})` })),
                    ...(taskForm.assignee_name && !activeEmployees.find(e => e.name === taskForm.assignee_name) ? [{ value: taskForm.assignee_name, label: `${taskForm.assignee_name} (当前)` }] : []),
                  ]}
                />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div><Label>优先级</Label><NativeSelect value={taskForm.priority} onChange={v => setTaskForm({ ...taskForm, priority: v })} options={Object.entries(priorityLabels).map(([k, v]) => ({ value: k, label: v }))} /></div>
              <div><Label>状态</Label><NativeSelect value={taskForm.status} onChange={v => setTaskForm({ ...taskForm, status: v })} options={Object.entries(taskStatusLabels).map(([k, v]) => ({ value: k, label: v }))} /></div>
            </div>
            <div><Label>截止日期</Label><Input type="date" value={taskForm.due_date} onChange={e => setTaskForm({ ...taskForm, due_date: e.target.value })} /></div>
            <div><Label>备注</Label><Textarea value={taskForm.notes} onChange={e => setTaskForm({ ...taskForm, notes: e.target.value })} rows={2} placeholder="补充说明..." /></div>
          </div>
          <div className="flex justify-end gap-2 mt-4">
            <Button variant="outline" onClick={() => setShowTaskForm(false)}>取消</Button>
            <Button onClick={handleSaveTask} disabled={savingTask} className="bg-blue-600 hover:bg-blue-700">{savingTask ? '保存中...' : '保存'}</Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
