import { useState, useEffect, useMemo, useRef, useCallback } from 'react';
import { client } from '../lib/api';
import { useRole } from '../lib/role-context';
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
  ChevronRight, Download, Copy, ArrowUpRight,
} from 'lucide-react';
import ConfirmDialog from '@/components/ConfirmDialog';
import ExportButton from '@/components/ExportButton';

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
  assignee_name: string;
  priority: string;
  status: string;
  due_date: string;
  completed_date: string;
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

// ==================== Helpers ====================
const todayStr = () => new Date().toISOString().slice(0, 10);
const isOverdue = (sp: ServiceProgress) => sp.service_end_date && sp.service_end_date < todayStr() && sp.service_stage !== 'ended';
const isExpiringSoon = (sp: ServiceProgress) => {
  if (!sp.service_end_date) return false;
  const end = new Date(sp.service_end_date);
  const now = new Date();
  const diff = (end.getTime() - now.getTime()) / (1000 * 60 * 60 * 24);
  return diff > 0 && diff <= 30;
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

const displayCountry = (code: string) => countryDisplayLabels[code] || code;

// Product type to service type mapping
const productToServiceType: Record<string, string> = {
  social_media: 'social_media',
  website: 'website',
  ordering_system: 'ordering_system',
  ads: 'ads',
  combo: 'other',
};

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

// ==================== Main Component ====================
export default function ServiceBoard() {
  const { role, employee, isAdmin, dataScope } = useRole();

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

  // Quick update work summary dialog
  const [showQuickUpdate, setShowQuickUpdate] = useState(false);
  const [quickUpdateSp, setQuickUpdateSp] = useState<ServiceProgress | null>(null);
  const [quickUpdateSummary, setQuickUpdateSummary] = useState('');
  const [savingQuickUpdate, setSavingQuickUpdate] = useState(false);

  const [deleteTarget, setDeleteTarget] = useState<{ type: 'progress' | 'task'; item: any } | null>(null);
  const [deleting, setDeleting] = useState(false);

  // ==================== Data Loading ====================
  useEffect(() => { loadData(); }, []);

  const loadData = async () => {
    try {
      const [pRes, tRes, cRes, eRes, sRes] = await Promise.all([
        client.entities.service_progresses.queryAll({ limit: 500, sort: '-last_update_time' }),
        client.entities.service_tasks.queryAll({ limit: 1000, sort: '-created_at' }),
        client.entities.customers.query({ limit: 500, sort: '-created_at' }),
        client.entities.employees.queryAll({ limit: 200, sort: 'name' }),
        client.entities.subscriptions.query({ limit: 500, sort: '-created_at' }),
      ]);
      let items = pRes?.data?.items || [];
      if (dataScope === 'self' && employee) {
        items = items.filter((p: ServiceProgress) =>
          p.ops_person === employee.name || p.sales_person === employee.name || p.design_person === employee.name
        );
      }
      setProgresses(items);
      setAllTasks(tRes?.data?.items || []);
      setAllCustomers(cRes?.data?.items || []);
      setAllEmployees(eRes?.data?.items || []);
      setAllSubscriptions(sRes?.data?.items || []);
    } catch (err) {
      console.error(err);
      toast.error('加载数据失败');
    } finally {
      setLoading(false);
    }
  };

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

  // ==================== Stats ====================
  const stats = useMemo(() => {
    const total = progresses.length;
    const active = progresses.filter(p => !['ended', 'paused'].includes(p.service_stage)).length;
    const withIssue = progresses.filter(p => hasIssue(p)).length;
    const overdueCount = progresses.filter(p => isOverdue(p)).length;
    const updatedWeek = progresses.filter(p => isUpdatedThisWeek(p)).length;
    const longNoUpd = progresses.filter(p => isLongNoUpdate(p)).length;
    const expiring = progresses.filter(p => isExpiringSoon(p)).length;

    const opsMap: Record<string, { total: number; pending: number; issues: number }> = {};
    progresses.forEach(p => {
      if (p.ops_person) {
        if (!opsMap[p.ops_person]) opsMap[p.ops_person] = { total: 0, pending: 0, issues: 0 };
        opsMap[p.ops_person].total++;
        if (hasIssue(p)) opsMap[p.ops_person].issues++;
      }
    });
    allTasks.forEach(t => {
      if (t.assignee_name && t.status !== 'completed' && t.status !== 'cancelled') {
        if (!opsMap[t.assignee_name]) opsMap[t.assignee_name] = { total: 0, pending: 0, issues: 0 };
        opsMap[t.assignee_name].pending++;
      }
    });

    return { total, active, withIssue, overdueCount, updatedWeek, longNoUpd, expiring, opsMap };
  }, [progresses, allTasks]);

  // ==================== Task stats per progress ====================
  const getTaskStats = useCallback((progressId: number) => {
    const tasks = allTasks.filter(t => t.service_progress_id === progressId);
    const total = tasks.length;
    const completed = tasks.filter(t => t.status === 'completed').length;
    const pending = tasks.filter(t => t.status === 'pending' || t.status === 'in_progress').length;
    const overdue = tasks.filter(t => t.status === 'delayed' || (t.due_date && t.due_date < todayStr() && t.status !== 'completed' && t.status !== 'cancelled')).length;
    const waitingClient = tasks.filter(t => t.status === 'waiting_client').length;
    return { total, completed, pending, overdue, waitingClient };
  }, [allTasks]);

  // ==================== Permissions ====================
  const canEdit = isAdmin || role === 'ops';
  const canCreate = isAdmin || role === 'ops';
  const canDelete = isAdmin;

  // ==================== Form Helpers ====================
  function emptyProgressForm() {
    return {
      customer_id: 0, customer_name: '', service_type: 'social_media', service_stage: 'deal_handover',
      progress_percent: 10, sales_person: '', ops_person: '', design_person: '', package_name: '',
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
      task_name: '', task_type: 'other', assignee_name: '', priority: 'medium',
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
      package_name: sp.package_name || '', industry: sp.industry || 'restaurant',
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
        await client.entities.service_progresses.update({ id: String(editingProgressId), data });
        toast.success('服务进度已更新');
        try {
          logOperation({ customerId: progressForm.customer_id, actionType: 'edit_customer', actionDetail: `更新服务进度: 阶段=${allStageLabels[effectiveStage] || effectiveStage}, 进度=${progressForm.progress_percent}%, 摘要=${progressForm.last_work_summary || '无'}`, operatorName: op });
        } catch { /* ignore log errors */ }
      } else {
        data.created_at = now;
        await client.entities.service_progresses.create({ data });
        toast.success('服务进度已创建');
        try {
          logOperation({ customerId: progressForm.customer_id, actionType: 'create_customer', actionDetail: `新增服务进度: ${progressForm.customer_name}, 类型=${serviceTypeLabels[progressForm.service_type]}, 阶段=${allStageLabels[effectiveStage]}`, operatorName: op });
        } catch { /* ignore log errors */ }
      }
      setShowProgressForm(false);
      await loadData();
      // Refresh detail view if we were editing the currently selected progress
      if (selectedProgress && editingProgressId === selectedProgress.id) {
        const refreshed = (await client.entities.service_progresses.get({ id: String(editingProgressId) }))?.data;
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
      await client.entities.service_progresses.update({
        id: String(sp.id),
        data: {
          service_stage: nextStage,
          progress_percent: defaultProg >= 0 ? defaultProg : sp.progress_percent,
          last_update_time: now,
          last_update_person: op,
        },
      });
      toast.success(`已推进到: ${allStageLabels[nextStage] || nextStage}`);
      logOperation({ customerId: sp.customer_id, actionType: 'edit_customer', actionDetail: `推进服务阶段: ${sp.customer_name} ${allStageLabels[sp.service_stage]} → ${allStageLabels[nextStage]}`, operatorName: op });
      await loadData();
      if (selectedProgress?.id === sp.id) {
        const refreshed = (await client.entities.service_progresses.get({ id: String(sp.id) }))?.data;
        if (refreshed) setSelectedProgress(refreshed);
      }
    } catch { toast.error('推进失败'); }
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
      await client.entities.service_progresses.update({
        id: String(quickUpdateSp.id),
        data: { last_work_summary: quickUpdateSummary, last_update_time: now, last_update_person: op },
      });
      toast.success('工作摘要已更新');
      setShowQuickUpdate(false);
      await loadData();
      if (selectedProgress?.id === quickUpdateSp.id) {
        const refreshed = (await client.entities.service_progresses.get({ id: String(quickUpdateSp.id) }))?.data;
        if (refreshed) setSelectedProgress(refreshed);
      }
    } catch { toast.error('更新失败'); }
    finally { setSavingQuickUpdate(false); }
  };

  // Quick toggle task status
  const handleQuickTaskStatus = async (task: ServiceTask, newStatus: string) => {
    try {
      const completedDate = newStatus === 'completed' ? todayStr() : null;
      await client.entities.service_tasks.update({
        id: String(task.id),
        data: { status: newStatus, completed_date: completedDate },
      });
      toast.success(`任务状态已更新为: ${taskStatusLabels[newStatus]}`);
      await loadData();
      if (selectedProgress) {
        const res = await client.entities.service_tasks.queryAll({ query: { service_progress_id: selectedProgress.id }, sort: 'created_at', limit: 100 });
        setDetailTasks(res?.data?.items || []);
      }
    } catch (err: unknown) {
      console.error('Quick task status error:', err);
      const msg = err instanceof Error ? err.message : (typeof err === 'object' && err !== null && 'data' in err ? JSON.stringify((err as Record<string, unknown>).data) : '未知错误');
      toast.error(`更新失败: ${msg}`);
    }
  };

  const openCreateTask = (sp: ServiceProgress) => {
    setTaskForm({ ...emptyTaskForm(), service_progress_id: sp.id, customer_id: sp.customer_id, customer_name: sp.customer_name });
    setEditingTaskId(null);
    setShowTaskForm(true);
  };

  const openEditTask = (t: ServiceTask) => {
    setTaskForm({
      service_progress_id: t.service_progress_id, customer_id: t.customer_id, customer_name: t.customer_name,
      task_name: t.task_name, task_type: t.task_type || 'other', assignee_name: t.assignee_name || '',
      priority: t.priority || 'medium', status: t.status, due_date: t.due_date?.slice(0, 10) || '', notes: t.notes || '',
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
        assignee_name: taskForm.assignee_name || null,
        priority: taskForm.priority || 'medium',
        status: taskForm.status || 'pending',
        due_date: taskForm.due_date || null,
        notes: taskForm.notes || null,
        completed_date: taskForm.status === 'completed' ? todayStr() : null,
      };
      if (editingTaskId) {
        await client.entities.service_tasks.update({ id: String(editingTaskId), data });
        toast.success('任务已更新');
      } else {
        data.created_at = now;
        await client.entities.service_tasks.create({ data });
        toast.success('任务已创建');
      }
      setShowTaskForm(false);
      await loadData();
      if (selectedProgress) {
        const res = await client.entities.service_tasks.queryAll({ query: { service_progress_id: selectedProgress.id }, sort: 'created_at', limit: 100 });
        setDetailTasks(res?.data?.items || []);
      }
    } catch (err: unknown) {
      console.error('Save task error:', err);
      const msg = err instanceof Error ? err.message : (typeof err === 'object' && err !== null && 'data' in err ? JSON.stringify((err as Record<string, unknown>).data) : '未知错误');
      toast.error(`保存失败: ${msg}`);
    } finally { setSavingTask(false); }
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      if (deleteTarget.type === 'progress') {
        // Also delete associated tasks
        const relatedTasks = allTasks.filter(t => t.service_progress_id === deleteTarget.item.id);
        for (const t of relatedTasks) {
          try { await client.entities.service_tasks.delete({ id: String(t.id) }); } catch { /* ignore */ }
        }
        await client.entities.service_progresses.delete({ id: String(deleteTarget.item.id) });
        toast.success('服务进度及关联任务已删除');
        if (selectedProgress?.id === deleteTarget.item.id) setSelectedProgress(null);
      } else {
        await client.entities.service_tasks.delete({ id: String(deleteTarget.item.id) });
        toast.success('任务已删除');
      }
      setDeleteTarget(null);
      await loadData();
      if (selectedProgress && deleteTarget.type === 'task') {
        const res = await client.entities.service_tasks.queryAll({ query: { service_progress_id: selectedProgress.id }, sort: 'created_at', limit: 100 });
        setDetailTasks(res?.data?.items || []);
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
      const res = await client.entities.service_tasks.queryAll({ query: { service_progress_id: sp.id }, sort: 'created_at', limit: 100 });
      setDetailTasks(res?.data?.items || []);
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

    return (
      <div
        className={`p-4 rounded-lg border cursor-pointer transition-all hover:shadow-md ${
          issue ? 'border-red-300 bg-red-50/50' : overdue ? 'border-amber-300 bg-amber-50/50' : expiring ? 'border-yellow-300 bg-yellow-50/50' : 'border-slate-200 bg-white'
        }`}
        onClick={() => openDetail(sp)}
      >
        <div className="flex items-start justify-between mb-2">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="font-semibold text-sm text-slate-800 truncate">{sp.customer_name}</span>
              <Badge className="text-[10px] bg-blue-100 text-blue-700">{serviceTypeLabels[sp.service_type] || sp.service_type}</Badge>
              {issue && <Badge className="text-[10px] bg-red-100 text-red-700 flex items-center gap-0.5"><AlertTriangle className="w-2.5 h-2.5" />卡点</Badge>}
              {overdue && <Badge className="text-[10px] bg-amber-100 text-amber-700">逾期</Badge>}
              {expiring && <Badge className="text-[10px] bg-yellow-100 text-yellow-700">即将到期</Badge>}
            </div>
            <p className="text-xs text-slate-500 mt-0.5">{sp.city}{sp.state ? `, ${sp.state}` : ''} · {industryLabels[sp.industry] || sp.industry}</p>
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

        <div className="flex items-center gap-3 text-xs border-t border-slate-100 pt-2">
          <span className="flex items-center gap-1 text-slate-500"><CheckCircle2 className="w-3 h-3 text-green-500" />{ts.completed}/{ts.total}</span>
          {ts.overdue > 0 && <span className="flex items-center gap-1 text-red-600"><XCircle className="w-3 h-3" />{ts.overdue}逾期</span>}
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
          </div>
        )}
      </div>
    );
  };

  // ==================== DETAIL VIEW ====================
  if (selectedProgress) {
    const sp = selectedProgress;
    const ts = getTaskStats(sp.id);
    const nextStage = getNextStage(sp.service_type, sp.service_stage);

    // Build richer timeline
    const timelineItems = [
      ...(sp.created_at ? [{ time: sp.created_at, label: '创建服务记录', type: 'info' as const }] : []),
      ...(sp.service_start_date ? [{ time: sp.service_start_date, label: '服务开始', type: 'info' as const }] : []),
      ...detailTasks.map(t => ({
        time: t.created_at,
        label: `创建任务: ${t.task_name} (${taskTypeLabels[t.task_type] || t.task_type})`,
        type: 'task' as const,
      })),
      ...detailTasks.filter(t => t.completed_date).map(t => ({ time: t.completed_date, label: `完成任务: ${t.task_name}`, type: 'done' as const })),
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
          {isOverdue(sp) && <Badge className="bg-amber-100 text-amber-700">已逾期</Badge>}
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
            <Button size="sm" onClick={() => { openCreateTask(sp); setDetailTab('tasks'); }} className="bg-blue-600 hover:bg-blue-700 text-white"><Plus className="w-3.5 h-3.5 mr-1" /> 新增任务</Button>
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
            <TabsTrigger value="tasks" className="text-xs">任务清单 ({detailTasks.length})</TabsTrigger>
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
                  <div className="flex justify-between"><span className="text-slate-500">到期日期</span><span className={isOverdue(sp) ? 'text-red-600 font-medium' : ''}>{sp.service_end_date?.slice(0, 10) || '-'}{isOverdue(sp) ? ' (已逾期)' : ''}</span></div>
                </div>
              </CardContent></Card>

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
              <div className="flex items-center justify-between mb-4">
                <span className="text-sm font-medium text-slate-600">服务任务清单</span>
                {canEdit && <Button size="sm" onClick={() => openCreateTask(sp)} className="bg-blue-600 hover:bg-blue-700"><Plus className="w-3.5 h-3.5 mr-1" /> 新增任务</Button>}
              </div>
              {detailTasks.length === 0 ? (
                <div className="text-center py-8">
                  <p className="text-sm text-slate-400 mb-3">暂无任务</p>
                  {canEdit && (
                    <Button size="sm" variant="outline" onClick={() => openCreateTask(sp)}>
                      <Plus className="w-3.5 h-3.5 mr-1" /> 创建第一个任务
                    </Button>
                  )}
                </div>
              ) : (
                <div className="space-y-2">
                  {detailTasks.map(t => {
                    const isTaskOverdue = t.due_date && t.due_date < todayStr() && t.status !== 'completed' && t.status !== 'cancelled';
                    return (
                      <div key={t.id} className={`p-3 rounded-lg border ${t.status === 'delayed' || isTaskOverdue ? 'border-red-200 bg-red-50/50' : t.status === 'completed' ? 'border-green-200 bg-green-50/30' : t.status === 'waiting_client' ? 'border-amber-200 bg-amber-50/30' : 'border-slate-200'} group`}>
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-2 flex-wrap flex-1">
                            <span className={`text-sm font-medium ${t.status === 'completed' ? 'line-through text-slate-400' : 'text-slate-700'}`}>{t.task_name}</span>
                            <Badge className={`text-[10px] ${taskStatusColors[t.status]}`}>{taskStatusLabels[t.status]}</Badge>
                            <Badge className={`text-[10px] ${priorityColors[t.priority]}`}>{priorityLabels[t.priority]}</Badge>
                          </div>
                          <div className="flex gap-1 shrink-0">
                            {/* Quick status buttons */}
                            {canEdit && t.status !== 'completed' && (
                              <Button size="sm" variant="ghost" className="h-6 px-1.5 text-green-600 hover:text-green-700 hover:bg-green-50" title="标记完成" onClick={() => handleQuickTaskStatus(t, 'completed')}>
                                <CheckCircle2 className="w-3.5 h-3.5" />
                              </Button>
                            )}
                            {canEdit && t.status === 'pending' && (
                              <Button size="sm" variant="ghost" className="h-6 px-1.5 text-blue-600 hover:text-blue-700 hover:bg-blue-50 text-[10px]" onClick={() => handleQuickTaskStatus(t, 'in_progress')}>
                                开始
                              </Button>
                            )}
                            {canEdit && t.status !== 'waiting_client' && t.status !== 'completed' && t.status !== 'cancelled' && (
                              <Button size="sm" variant="ghost" className="h-6 px-1.5 text-amber-600 hover:text-amber-700 hover:bg-amber-50 text-[10px]" onClick={() => handleQuickTaskStatus(t, 'waiting_client')}>
                                等客户
                              </Button>
                            )}
                            {canEdit && (
                              <Button size="sm" variant="ghost" className="h-6 w-6 p-0 opacity-0 group-hover:opacity-100 transition-opacity" onClick={() => openEditTask(t)}><Edit className="w-3 h-3" /></Button>
                            )}
                            {canDelete && (
                              <Button size="sm" variant="ghost" className="h-6 w-6 p-0 text-red-500 opacity-0 group-hover:opacity-100 transition-opacity" onClick={() => setDeleteTarget({ type: 'task', item: t })}><Trash2 className="w-3 h-3" /></Button>
                            )}
                          </div>
                        </div>
                        <div className="flex items-center gap-4 mt-1 text-xs text-slate-500">
                          <span>类型: {taskTypeLabels[t.task_type] || t.task_type}</span>
                          <span>负责: {t.assignee_name || '-'}</span>
                          {t.due_date && <span className={isTaskOverdue ? 'text-red-600 font-medium' : ''}>截止: {t.due_date.slice(0, 10)}{isTaskOverdue ? ' ⚠️' : ''}</span>}
                          {t.completed_date && <span className="text-green-600">完成: {t.completed_date.slice(0, 10)}</span>}
                        </div>
                        {t.notes && <p className="text-xs text-slate-400 mt-1">{t.notes}</p>}
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
      </div>
    );
  }

  // ==================== MAIN VIEW ====================
  if (loading) {
    return <div className="flex items-center justify-center py-12"><div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600" /></div>;
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
        <h2 className="text-xl font-semibold text-slate-800">客户服务进度看板</h2>
        <div className="flex gap-2 flex-wrap">
          <ExportButton
            data={exportData}
            columns={exportColumns}
            filename={`服务进度_${todayStr()}`}
            sheetName="服务进度"
          />
          <Button variant="outline" size="sm" onClick={() => setShowStats(!showStats)} className="gap-1.5"><BarChart3 className="w-4 h-4" /> {showStats ? '隐藏统计' : '显示统计'}</Button>
          <Button variant="outline" size="sm" onClick={loadData} className="gap-1.5"><RefreshCw className="w-4 h-4" /> 刷新</Button>
          {canCreate && <Button onClick={openCreateProgress} className="bg-blue-600 hover:bg-blue-700"><Plus className="w-4 h-4 mr-1" /> 新增服务</Button>}
        </div>
      </div>

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
                {data.pending > 0 && <Badge className="text-xs bg-amber-100 text-amber-700">{data.pending}待办</Badge>}
                {data.issues > 0 && <Badge className="text-xs bg-red-100 text-red-700">{data.issues}卡点</Badge>}
              </div>
            ))}
          </div>
        </CardContent></Card>
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
          ) : filtered.map(sp => <ProgressCard key={sp.id} sp={sp} />)}
        </div>
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
                          {isOverdue(sp) && <Clock className="w-3 h-3 text-amber-500" />}
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
                    <Badge className="bg-amber-100 text-amber-700 text-xs">{items.filter(i => isOverdue(i)).length} 逾期</Badge>
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