import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  Clock3,
  History,
  Landmark,
  LockKeyhole,
  Pencil,
  Plus,
  RefreshCw,
  Rocket,
  Settings2,
  ShieldCheck,
  Target,
  TrendingUp,
  UnlockKeyhole,
  WalletCards,
} from 'lucide-react';
import { toast } from 'sonner';
import { Link } from 'react-router-dom';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { NativeSelect } from '@/components/ui/native-select';
import { Progress } from '@/components/ui/progress';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Textarea } from '@/components/ui/textarea';
import { useRole } from '@/lib/role-context';
import { invokeWithAuth } from '@/lib/tokenStore';

type Account = {
  id: number;
  name: string;
  account_type: string;
  currency: 'USD' | 'CNY';
  masked_identifier?: string | null;
  is_active: boolean;
  sort_order: number;
  notes?: string | null;
};

type Restriction = {
  id?: number;
  category: string;
  category_label?: string;
  description: string;
  currency: 'USD' | 'CNY';
  amount: number;
  rate_to_cny?: number;
  amount_cny?: number;
  source_ref?: string | null;
  notes?: string | null;
  is_suggestion?: boolean;
};

type Balance = {
  id?: number;
  account_id: number;
  account_name?: string;
  account_type?: string;
  masked_identifier?: string | null;
  currency?: 'USD' | 'CNY';
  balance: number;
  rate_to_cny?: number;
  balance_cny?: number;
};

type CashPeriod = {
  id: number;
  year_month: string;
  snapshot_date: string;
  status: 'draft' | 'locked';
  usd_cny_rate: number;
  notes?: string | null;
  locked_at?: string | null;
  locked_by?: string | null;
  reopen_reason?: string | null;
  balances: Balance[];
  restrictions: Restriction[];
  totals: { account_balance_cny: number; restricted_cny: number; free_cash_cny: number };
};

type Overview = {
  settings: {
    configured: boolean;
    target_start_date: string;
    target_end_date: string;
    five_year_profit_target_cny: number;
    monthly_fixed_expense_cny: number;
    cash_reserve_months: number;
    cash_safety_target_cny: number;
    default_usd_cny_rate: number;
    current_focus: string;
  };
  accounts: Account[];
  cash_period: CashPeriod | null;
  cash_history: Array<{
    year_month: string;
    snapshot_date: string;
    status: string;
    account_balance_cny: number;
    restricted_cny: number;
    free_cash_cny: number;
  }>;
  restriction_categories: Array<{ value: string; label: string }>;
  restriction_suggestions: Restriction[];
  unrecorded_suggestion_cny: number;
  cash_health: {
    has_baseline: boolean;
    as_of_month: string | null;
    snapshot_status: 'locked' | null;
    snapshot_age_days: number | null;
    is_stale: boolean;
    free_cash_cny: number | null;
    safety_target_cny: number;
    gap_to_safety_cny: number | null;
    runway_months: number | null;
    level: 'unknown' | 'stale' | 'danger' | 'warning' | 'safe';
    projections: Array<{ days: number; free_cash_cny: number; based_on: string }>;
    projection_reason: string | null;
  };
  goal: {
    target_cny: number;
    recognized_profit_cny: number;
    progress_ratio: number;
    remaining_cny: number;
    remaining_months: number;
    required_average_monthly_profit_cny: number;
    ready_months: number;
    total_months: number;
    has_profit_data: boolean;
    is_complete_data: boolean;
    expected_profit_to_date_cny: number;
    pace_gap_cny: number;
    pace_status: 'ahead' | 'on_track' | 'behind' | 'data_incomplete';
  };
  operating_signals: {
    three_month_average_profit_cny: number | null;
    profit_sample_months: number;
    active_managed_service_projects: number;
    active_os_projects: number;
    paid_os_projects: number;
    paid_restaurant_os_projects: number;
    paid_beauty_os_projects: number;
    leading_os_code: 'restaurant_os' | 'beauty_os';
    leading_os_name: string;
    high_risk_project_count: number;
    health_project_count: number;
    high_risk_ratio: number;
    active_employee_count: number;
    team_capacity: {
      active_projects: number;
      unassigned_projects: number;
      near_or_over_capacity: number;
      overdue_rate: number;
      hiring_level: 'hire' | 'process' | 'stable' | string;
      hiring_title: string;
      hiring_message: string;
    };
  };
  milestones: Array<{ key: string; label: string; status: 'completed' | 'current' | 'pending'; target: string }>;
  recommendation: {
    key: string;
    level: 'critical' | 'warning' | 'growth';
    title: string;
    why: string;
    action: string;
    decision?: {
      status: string;
      decision_note?: string | null;
      next_review_date?: string | null;
      task_id?: number | null;
      decided_at?: string | null;
      decided_by_name?: string | null;
    } | null;
  };
  definitions: { free_cash: string; profit_vs_cash: string; data_boundary: string };
};

type SettingsForm = {
  target_start_date: string;
  target_end_date: string;
  five_year_profit_target_cny: string;
  monthly_fixed_expense_cny: string;
  cash_reserve_months: string;
  default_usd_cny_rate: string;
  current_focus: string;
};

type AccountForm = {
  id?: number;
  name: string;
  account_type: string;
  currency: 'USD' | 'CNY';
  masked_identifier: string;
  is_active: boolean;
  sort_order: string;
  notes: string;
};

const today = new Date();
const currentMonth = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}`;
const localDate = `${currentMonth}-${String(today.getDate()).padStart(2, '0')}`;

const cny = (value: number | null | undefined) => value == null
  ? '待确认'
  : `${Number(value) < 0 ? '-' : ''}¥${Math.abs(Number(value)).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

const money = (value: number, currency: string) => currency === 'USD'
  ? `$${Number(value || 0).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
  : cny(value);

const errorMessage = (error: any, fallback: string) => (
  error?.data?.detail || error?.response?.data?.detail || error?.message || fallback
);

const recommendationTone = {
  critical: 'border-rose-200 bg-rose-50',
  warning: 'border-amber-200 bg-amber-50',
  growth: 'border-blue-200 bg-blue-50',
};

const cashHealthLabels = {
  unknown: '待建立底账',
  stale: '快照已过期',
  danger: '现金风险',
  warning: '低于安全线',
  safe: '达到安全线',
};

const paceLabels = {
  ahead: '领先计划',
  on_track: '基本按计划',
  behind: '落后计划',
  data_incomplete: '数据未完整',
};

const decisionStatusLabels: Record<string, string> = {
  accepted: '已采纳',
  deferred: '已暂缓',
  rejected: '不采纳',
  completed: '已完成',
};

export default function CompanyRoadmap() {
  const { isAdmin } = useRole();
  const [overview, setOverview] = useState<Overview | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [selectedMonth, setSelectedMonth] = useState(currentMonth);
  const [snapshotDate, setSnapshotDate] = useState(localDate);
  const [rate, setRate] = useState('6.7');
  const [periodNotes, setPeriodNotes] = useState('');
  const [balances, setBalances] = useState<Record<number, string>>({});
  const [restrictions, setRestrictions] = useState<Restriction[]>([]);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settingsForm, setSettingsForm] = useState<SettingsForm | null>(null);
  const [accountOpen, setAccountOpen] = useState(false);
  const [accountForm, setAccountForm] = useState<AccountForm>({
    name: '', account_type: 'bank', currency: 'CNY', masked_identifier: '', is_active: true, sort_order: '0', notes: '',
  });
  const accountNameRef = useRef<HTMLInputElement | null>(null);
  const [restrictionOpen, setRestrictionOpen] = useState(false);
  const [restrictionDraft, setRestrictionDraft] = useState<Restriction>({
    category: 'tax_reserve', description: '', currency: 'CNY', amount: 0, notes: '',
  });
  const [reopenOpen, setReopenOpen] = useState(false);
  const [reopenReason, setReopenReason] = useState('');
  const [decisionOpen, setDecisionOpen] = useState(false);
  const [decisionStatus, setDecisionStatus] = useState<'accepted' | 'deferred' | 'rejected' | 'completed'>('accepted');
  const [decisionNote, setDecisionNote] = useState('');
  const [nextReviewDate, setNextReviewDate] = useState('');
  const [createTask, setCreateTask] = useState(true);
  const [auditOpen, setAuditOpen] = useState(false);
  const [auditRows, setAuditRows] = useState<Array<{ id: number; action: string; actor_name: string; actor_role: string; reason?: string | null; created_at: string }>>([]);

  const hydrateEditor = useCallback((data: Overview) => {
    const period = data.cash_period;
    if (period) {
      setSnapshotDate(period.snapshot_date);
      setRate(String(period.usd_cny_rate));
      setPeriodNotes(period.notes || '');
      setBalances(Object.fromEntries(period.balances.map(row => [row.account_id, String(row.balance)])));
      setRestrictions(period.restrictions);
    } else {
      const sameMonthDate = selectedMonth === currentMonth ? localDate : `${selectedMonth}-01`;
      setSnapshotDate(sameMonthDate);
      setRate(String(data.settings.default_usd_cny_rate));
      setPeriodNotes('');
      setBalances({});
      setRestrictions([]);
    }
  }, [selectedMonth]);

  const loadOverview = useCallback(async (month = selectedMonth) => {
    setLoading(true);
    try {
      const response = await invokeWithAuth({
        url: `/api/v1/company-roadmap/overview?month=${encodeURIComponent(month)}`,
        method: 'GET',
      });
      const data = response.data as Overview;
      setOverview(data);
      hydrateEditor(data);
    } catch (error) {
      toast.error(errorMessage(error, '公司战略数据读取失败'));
    } finally {
      setLoading(false);
    }
  }, [hydrateEditor, selectedMonth]);

  useEffect(() => {
    void loadOverview();
  }, [loadOverview]);

  const editorAccounts = useMemo(() => {
    const periodAccountIds = new Set((overview?.cash_period?.balances || []).map(row => row.account_id));
    return overview?.accounts.filter(row => row.is_active || periodAccountIds.has(row.id)) || [];
  }, [overview?.accounts, overview?.cash_period?.balances]);
  const periodLocked = overview?.cash_period?.status === 'locked';
  const futureMonthSelected = selectedMonth > currentMonth;
  const numericRate = Number(rate) || 0;
  const draftAccountTotal = useMemo(() => editorAccounts.reduce((sum, account) => {
    const value = Number(balances[account.id] || 0);
    return sum + value * (account.currency === 'USD' ? numericRate : 1);
  }, 0), [editorAccounts, balances, numericRate]);
  const draftRestrictedTotal = useMemo(() => restrictions.reduce((sum, row) => {
    return sum + Number(row.amount || 0) * (row.currency === 'USD' ? numericRate : 1);
  }, 0), [numericRate, restrictions]);
  const draftFreeCash = draftAccountTotal - draftRestrictedTotal;

  const openSettings = () => {
    if (!overview) return;
    const settings = overview.settings;
    setSettingsForm({
      target_start_date: settings.target_start_date,
      target_end_date: settings.target_end_date,
      five_year_profit_target_cny: String(settings.five_year_profit_target_cny),
      monthly_fixed_expense_cny: String(settings.monthly_fixed_expense_cny),
      cash_reserve_months: String(settings.cash_reserve_months),
      default_usd_cny_rate: String(settings.default_usd_cny_rate),
      current_focus: settings.current_focus || '',
    });
    setSettingsOpen(true);
  };

  const saveSettings = async () => {
    if (!settingsForm) return;
    setSaving(true);
    try {
      await invokeWithAuth({
        url: '/api/v1/company-roadmap/settings',
        method: 'PUT',
        data: {
          ...settingsForm,
          five_year_profit_target_cny: Number(settingsForm.five_year_profit_target_cny),
          monthly_fixed_expense_cny: Number(settingsForm.monthly_fixed_expense_cny),
          cash_reserve_months: Number(settingsForm.cash_reserve_months),
          default_usd_cny_rate: Number(settingsForm.default_usd_cny_rate),
        },
      });
      toast.success('公司目标与现金安全参数已保存');
      setSettingsOpen(false);
      await loadOverview();
    } catch (error) {
      toast.error(errorMessage(error, '目标设置保存失败'));
    } finally {
      setSaving(false);
    }
  };

  const openNewAccount = () => {
    setAccountForm({ name: '', account_type: 'bank', currency: 'CNY', masked_identifier: '', is_active: true, sort_order: '0', notes: '' });
    setAccountOpen(true);
  };

  useEffect(() => {
    if (!accountOpen) return;
    const frame = window.requestAnimationFrame(() => accountNameRef.current?.focus());
    return () => window.cancelAnimationFrame(frame);
  }, [accountOpen]);

  const openEditAccount = (account: Account) => {
    setAccountForm({
      id: account.id,
      name: account.name,
      account_type: account.account_type,
      currency: account.currency,
      masked_identifier: account.masked_identifier || '',
      is_active: account.is_active,
      sort_order: String(account.sort_order),
      notes: account.notes || '',
    });
    setAccountOpen(true);
  };

  const saveAccount = async () => {
    if (!accountForm.name.trim()) {
      toast.error('请输入账户名称');
      return;
    }
    setSaving(true);
    try {
      await invokeWithAuth({
        url: accountForm.id ? `/api/v1/company-roadmap/cash-accounts/${accountForm.id}` : '/api/v1/company-roadmap/cash-accounts',
        method: accountForm.id ? 'PUT' : 'POST',
        data: { ...accountForm, name: accountForm.name.trim(), sort_order: Number(accountForm.sort_order || 0) },
      });
      toast.success(accountForm.id ? '账户已更新' : '账户已新增');
      setAccountOpen(false);
      await loadOverview();
    } catch (error) {
      toast.error(errorMessage(error, '账户保存失败'));
    } finally {
      setSaving(false);
    }
  };

  const addSuggestion = (suggestion: Restriction) => {
    if (suggestion.source_ref && restrictions.some(row => row.source_ref === suggestion.source_ref)) {
      toast.info('这项系统建议已经加入');
      return;
    }
    setRestrictions(current => [...current, { ...suggestion }]);
  };

  const addAllSuggestions = () => {
    const currentRefs = new Set(restrictions.map(row => row.source_ref).filter(Boolean));
    const additions = (overview?.restriction_suggestions || []).filter(row => !row.source_ref || !currentRefs.has(row.source_ref));
    setRestrictions(current => [...current, ...additions]);
    if (additions.length) toast.success(`已加入 ${additions.length} 项，保存前仍可核对或移除`);
  };

  const saveRestriction = () => {
    if (!restrictionDraft.description.trim() || Number(restrictionDraft.amount) <= 0) {
      toast.error('请填写受限资金说明和金额');
      return;
    }
    setRestrictions(current => [...current, { ...restrictionDraft, description: restrictionDraft.description.trim() }]);
    setRestrictionOpen(false);
    setRestrictionDraft({ category: 'tax_reserve', description: '', currency: 'CNY', amount: 0, notes: '' });
  };

  const saveCashPeriod = async () => {
    if (!editorAccounts.length) {
      toast.error('请先新增至少一个公司现金账户');
      return;
    }
    if (!snapshotDate || snapshotDate.slice(0, 7) !== selectedMonth) {
      toast.error('快照日期必须属于所选月份');
      return;
    }
    if (!Number.isFinite(numericRate) || numericRate <= 0.1 || numericRate >= 20) {
      toast.error('请输入正确的 USD/CNY 汇率');
      return;
    }
    setSaving(true);
    try {
      await invokeWithAuth({
        url: `/api/v1/company-roadmap/cash-periods/${selectedMonth}`,
        method: 'PUT',
        data: {
          snapshot_date: snapshotDate,
          usd_cny_rate: numericRate,
          notes: periodNotes || null,
          balances: editorAccounts.map(account => ({ account_id: account.id, balance: Number(balances[account.id] || 0) })),
          restrictions: restrictions.map(row => ({
            category: row.category,
            description: row.description,
            currency: row.currency,
            amount: Number(row.amount),
            source_ref: row.source_ref || null,
            notes: row.notes || null,
          })),
        },
      });
      toast.success('现金快照草稿已保存；锁定后才会进入经营决策');
      await loadOverview();
    } catch (error) {
      toast.error(errorMessage(error, '现金快照保存失败'));
    } finally {
      setSaving(false);
    }
  };

  const transitionCashPeriod = async (action: 'lock' | 'reopen', reason?: string) => {
    setSaving(true);
    try {
      await invokeWithAuth({
        url: `/api/v1/company-roadmap/cash-periods/${selectedMonth}/transition`,
        method: 'POST',
        data: { action, reason: reason || null },
      });
      toast.success(action === 'lock' ? '现金快照已确认并锁定' : '现金快照已重新打开');
      setReopenOpen(false);
      setReopenReason('');
      await loadOverview();
    } catch (error) {
      toast.error(errorMessage(error, '现金快照状态更新失败'));
    } finally {
      setSaving(false);
    }
  };

  const openAudit = async () => {
    if (!overview?.cash_period) return;
    try {
      const response = await invokeWithAuth({
        url: `/api/v1/company-roadmap/cash-periods/${selectedMonth}/audit`,
        method: 'GET',
      });
      setAuditRows(response.data || []);
      setAuditOpen(true);
    } catch (error) {
      toast.error(errorMessage(error, '操作记录读取失败'));
    }
  };

  const saveDecision = async () => {
    if (!overview) return;
    setSaving(true);
    try {
      await invokeWithAuth({
        url: `/api/v1/company-roadmap/recommendations/${overview.recommendation.key}/decision`,
        method: 'POST',
        data: {
          status: decisionStatus,
          decision_note: decisionNote || null,
          next_review_date: nextReviewDate || null,
          create_task: createTask,
        },
      });
      toast.success('经营决策已记录');
      setDecisionOpen(false);
      await loadOverview();
    } catch (error) {
      toast.error(errorMessage(error, '经营决策保存失败'));
    } finally {
      setSaving(false);
    }
  };

  if (loading && !overview) {
    return <div className="app-loading">正在生成公司战略与现金安全视图...</div>;
  }

  if (!overview) {
    return <div className="app-page"><Card><CardContent className="p-10 text-center"><p className="text-slate-600">公司战略数据暂时无法读取。</p><Button className="mt-4" onClick={() => void loadOverview()}><RefreshCw className="mr-2 h-4 w-4" />重新加载</Button></CardContent></Card></div>;
  }

  const progressPercent = Math.min(100, Math.max(0, overview.goal.progress_ratio * 100));
  const recommendation = overview.recommendation;
  const cashLevel = overview.cash_health.level;
  const teamCapacity = overview.operating_signals.team_capacity || {
    active_projects: 0,
    unassigned_projects: 0,
    near_or_over_capacity: 0,
    overdue_rate: 0,
    hiring_level: 'stable',
    hiring_title: '团队产能数据正在更新',
    hiring_message: '刷新后仍未出现时，请检查后端是否已同步到最新版本。',
  };

  return (
    <div className="app-page space-y-5">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-blue-600">T24 Marketing · Company Roadmap</p>
          <h1 className="mt-1 text-2xl font-bold text-slate-900">公司战略与里程碑</h1>
          <p className="mt-1 text-sm text-slate-500">把利润、现金、客户健康和团队产能收成一条路线：当前只做最重要的一件事。</p>
        </div>
        <div className="flex flex-wrap gap-2">
          {isAdmin ? <Button variant="outline" onClick={openSettings}><Settings2 className="mr-2 h-4 w-4" />目标设置</Button> : null}
          <Button variant="outline" onClick={() => void loadOverview()} disabled={loading}><RefreshCw className={`mr-2 h-4 w-4 ${loading ? 'animate-spin' : ''}`} />刷新</Button>
        </div>
      </div>

      {!overview.settings.configured ? <div className="flex flex-col gap-3 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900 sm:flex-row sm:items-center sm:justify-between"><div><p className="font-semibold">当前显示的是系统默认规划参数，尚未由老板正式确认</p><p className="mt-1 text-xs leading-5 text-amber-700">默认目标为 2026–2030 年累计净利润 2,000 万元、现金安全线为 6 个月固定支出。确认前只用于规划提示。</p></div>{isAdmin ? <Button size="sm" variant="outline" onClick={openSettings}>现在确认目标</Button> : null}</div> : null}

      <Card className="overflow-hidden border-slate-800 bg-[#0f1b34] text-white">
        <CardContent className="p-5 lg:p-6">
          <div className="grid gap-6 xl:grid-cols-[1.35fr_0.65fr]">
            <div>
              <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.15em] text-cyan-300"><Target className="h-4 w-4" />五年累计净利润目标</div>
              <div className="mt-3 flex flex-wrap items-end gap-x-5 gap-y-2">
                <p className="text-3xl font-semibold tracking-tight">{cny(overview.goal.target_cny)}</p>
                <p className="pb-1 text-sm text-slate-300">当前可核算 {cny(overview.goal.recognized_profit_cny)} · 完成 {progressPercent.toFixed(2)}%</p>
              </div>
              <Progress value={progressPercent} className="mt-4 h-2 bg-white/10 [&>div]:bg-cyan-400" />
              <div className="mt-4 grid gap-2 sm:grid-cols-3">
                <div className="rounded-xl border border-white/10 bg-white/[0.05] p-3"><p className="text-xs text-slate-400">剩余目标</p><p className="mt-1 text-lg font-semibold">{cny(overview.goal.remaining_cny)}</p></div>
                <div className="rounded-xl border border-white/10 bg-white/[0.05] p-3"><p className="text-xs text-slate-400">剩余时间</p><p className="mt-1 text-lg font-semibold">{overview.goal.remaining_months} 个月</p></div>
                <div className="rounded-xl border border-white/10 bg-white/[0.05] p-3"><p className="text-xs text-slate-400">所需月均净利润</p><p className="mt-1 text-lg font-semibold">{cny(overview.goal.required_average_monthly_profit_cny)}</p></div>
              </div>
              <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-slate-300"><Badge className={overview.goal.pace_status === 'ahead' ? 'bg-emerald-200 text-emerald-900' : overview.goal.pace_status === 'behind' ? 'bg-rose-200 text-rose-900' : overview.goal.pace_status === 'data_incomplete' ? 'bg-amber-200 text-amber-900' : 'bg-blue-200 text-blue-900'}>{paceLabels[overview.goal.pace_status]}</Badge><span>按时间计划应累计 {cny(overview.goal.expected_profit_to_date_cny)} · 当前差额 {overview.goal.pace_gap_cny >= 0 ? '+' : ''}{cny(overview.goal.pace_gap_cny)}</span></div>
              {overview.settings.current_focus ? <p className="mt-3 rounded-lg border border-white/10 bg-white/[0.04] px-3 py-2 text-xs leading-5 text-slate-300">老板设定的经营焦点：{overview.settings.current_focus}</p> : null}
            </div>
            <div className={`rounded-2xl border p-4 ${cashLevel === 'safe' ? 'border-emerald-400/30 bg-emerald-400/10' : cashLevel === 'unknown' ? 'border-slate-400/30 bg-white/[0.04]' : 'border-amber-300/30 bg-amber-300/10'}`}>
              <div className="flex items-center justify-between"><span className="text-sm font-medium text-slate-200">公司可用现金</span><Badge className={cashLevel === 'safe' ? 'bg-emerald-200 text-emerald-900' : cashLevel === 'unknown' ? 'bg-slate-200 text-slate-800' : 'bg-amber-200 text-amber-900'}>{cashHealthLabels[cashLevel]}</Badge></div>
              <p className="mt-3 text-3xl font-semibold">{cny(overview.cash_health.free_cash_cny)}</p>
              <p className="mt-2 text-xs leading-5 text-slate-300">{overview.cash_health.as_of_month ? `${overview.cash_health.as_of_month} 已确认快照 · ` : ''}安全目标 {cny(overview.cash_health.safety_target_cny)} · 可支撑 {overview.cash_health.runway_months == null ? '待确认' : `${overview.cash_health.runway_months} 个月`}</p>
              {overview.cash_health.is_stale ? <p className="mt-2 rounded-lg bg-amber-300/15 px-3 py-2 text-xs text-amber-100">该现金快照距今 {overview.cash_health.snapshot_age_days} 天，只能参考，请先更新本月余额。</p> : null}
              <Button className="mt-4 w-full bg-white text-slate-900 hover:bg-slate-100" onClick={() => document.getElementById('cash-ledger')?.scrollIntoView({ behavior: 'smooth' })}><WalletCards className="mr-2 h-4 w-4" />核对现金底账</Button>
            </div>
          </div>
          {!overview.goal.is_complete_data ? <div className="mt-4 rounded-lg border border-amber-300/20 bg-amber-300/10 px-3 py-2 text-xs text-amber-100">{overview.goal.has_profit_data ? `当前只有 ${overview.goal.ready_months}/${overview.goal.total_months} 个已完成月份具备可核算利润；缺失汇率的月份不会被当作 0 元利润。` : '尚无已完成月份的正式利润数据，当前进度和差额只用于提示数据准备，不能据此判断经营表现。'}</div> : null}
        </CardContent>
      </Card>

      <Card className={recommendationTone[recommendation.level]}>
        <CardContent className="p-5">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
            <div className="max-w-4xl">
              <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.14em] text-slate-500"><Rocket className="h-4 w-4" />当前唯一经营重点</div>
              <h2 className="mt-2 text-xl font-bold text-slate-900">{recommendation.title}</h2>
              <p className="mt-2 text-sm leading-6 text-slate-700">判断：{recommendation.why}</p>
              <p className="mt-2 rounded-lg bg-white/70 px-3 py-2 text-sm font-medium text-slate-800">下一步：{recommendation.action}</p>
              {recommendation.decision ? <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-slate-500"><span>老板决定：{decisionStatusLabels[recommendation.decision.status] || recommendation.decision.status} · {recommendation.decision.decision_note || '未填写说明'}</span>{recommendation.decision.task_id ? <Button asChild size="sm" variant="link" className="h-auto p-0 text-xs"><Link to={`/tasks?task_id=${recommendation.decision.task_id}`}>打开执行任务 #{recommendation.decision.task_id}<ArrowRight className="ml-1 h-3 w-3" /></Link></Button> : null}</div> : null}
            </div>
            {isAdmin ? <Button onClick={() => {
              setDecisionStatus('accepted');
              setDecisionNote(recommendation.decision?.decision_note || '');
              setNextReviewDate(recommendation.decision?.next_review_date || '');
              setCreateTask(true);
              setDecisionOpen(true);
            }}>处理这项建议<ArrowRight className="ml-2 h-4 w-4" /></Button> : null}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3"><CardTitle className="text-base">阶段路线图</CardTitle><p className="mt-1 text-xs text-slate-500">未达到前一阶段时，后面的投入默认不启动。</p></CardHeader>
        <CardContent>
          <div className="grid gap-3 md:grid-cols-5">
            {overview.milestones.map((item, index) => <div key={item.key} className={`relative rounded-xl border p-4 ${item.status === 'completed' ? 'border-emerald-200 bg-emerald-50' : item.status === 'current' ? 'border-blue-300 bg-blue-50 ring-2 ring-blue-100' : 'border-slate-200 bg-slate-50'}`}>
              <div className="flex items-center justify-between"><span className="text-xs font-semibold text-slate-400">阶段 {index + 1}</span>{item.status === 'completed' ? <CheckCircle2 className="h-5 w-5 text-emerald-600" /> : item.status === 'current' ? <Clock3 className="h-5 w-5 text-blue-600" /> : <span className="h-5 w-5 rounded-full border-2 border-slate-300" />}</div>
              <p className="mt-3 font-semibold text-slate-900">{item.label}</p>
              <p className="mt-2 text-xs leading-5 text-slate-500">{item.target}</p>
            </div>)}
          </div>
        </CardContent>
      </Card>

      <Tabs defaultValue="cash" id="cash-ledger" className="scroll-mt-4">
        <TabsList className="grid h-auto w-full grid-cols-2 sm:w-[420px]"><TabsTrigger value="cash">现金底账</TabsTrigger><TabsTrigger value="signals">经营信号</TabsTrigger></TabsList>
        <TabsContent value="cash" className="mt-4 space-y-4">
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <Card><CardContent className="p-4"><p className="text-sm text-slate-500">账户总余额</p><p className="mt-2 text-2xl font-bold text-slate-900">{cny(periodLocked ? overview.cash_period?.totals.account_balance_cny : draftAccountTotal)}</p><p className="mt-1 text-xs text-slate-400">所有账户按本期汇率折算</p></CardContent></Card>
            <Card><CardContent className="p-4"><p className="text-sm text-slate-500">受限资金</p><p className="mt-2 text-2xl font-bold text-amber-700">{cny(periodLocked ? overview.cash_period?.totals.restricted_cny : draftRestrictedTotal)}</p><p className="mt-1 text-xs text-slate-400">客户资金与已确认待付款</p></CardContent></Card>
            <Card className="border-emerald-200 bg-emerald-50/40"><CardContent className="p-4"><p className="text-sm text-slate-500">真正可用现金</p><p className={`mt-2 text-2xl font-bold ${(periodLocked ? overview.cash_period?.totals.free_cash_cny || 0 : draftFreeCash) >= 0 ? 'text-emerald-700' : 'text-rose-700'}`}>{cny(periodLocked ? overview.cash_period?.totals.free_cash_cny : draftFreeCash)}</p><p className="mt-1 text-xs text-slate-500">余额减去受限资金</p></CardContent></Card>
            <Card><CardContent className="p-4"><p className="text-sm text-slate-500">安全线差额</p><p className="mt-2 text-2xl font-bold text-blue-700">{cny(Math.max(overview.cash_health.safety_target_cny - (periodLocked ? overview.cash_period?.totals.free_cash_cny || 0 : draftFreeCash), 0))}</p><p className="mt-1 text-xs text-slate-400">目标 {overview.settings.cash_reserve_months} 个月固定支出</p></CardContent></Card>
          </div>

          <Card>
            <CardHeader className="pb-3">
              <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
                <div><CardTitle className="flex items-center gap-2 text-base"><Landmark className="h-5 w-5 text-blue-600" />月度现金快照</CardTitle><p className="mt-1 text-xs text-slate-500">只录账户余额和受限资金，不重复录收入或支出。</p></div>
                <div className="flex flex-wrap items-center gap-2">
                  <Input type="month" value={selectedMonth} onChange={event => setSelectedMonth(event.target.value)} className="w-[160px]" />
                  {overview.cash_period ? <Badge className={periodLocked ? 'bg-violet-100 text-violet-700' : 'bg-amber-100 text-amber-700'}>{periodLocked ? '已确认锁定' : '草稿待确认'}</Badge> : <Badge variant="outline">尚未建立</Badge>}
                  {overview.cash_period ? <Button size="sm" variant="outline" onClick={() => void openAudit()}><History className="mr-1 h-4 w-4" />记录</Button> : null}
                </div>
              </div>
            </CardHeader>
            <CardContent className="space-y-5">
              <div className="grid gap-3 lg:grid-cols-3">
                <div><Label htmlFor="cash-snapshot-date">余额核对日期</Label><Input id="cash-snapshot-date" className="mt-1" type="date" value={snapshotDate} onChange={event => setSnapshotDate(event.target.value)} disabled={periodLocked} /></div>
                <div><Label htmlFor="cash-rate">USD/CNY 核对汇率</Label><Input id="cash-rate" className="mt-1" type="number" min="0.1" max="20" step="0.0001" value={rate} onChange={event => setRate(event.target.value)} disabled={periodLocked} /></div>
                <div><Label htmlFor="cash-notes">本期说明</Label><Input id="cash-notes" className="mt-1" value={periodNotes} onChange={event => setPeriodNotes(event.target.value)} disabled={periodLocked} placeholder="例如：银行余额已与 8 月 12 日对账" /></div>
              </div>
              {futureMonthSelected ? <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">未来月份只可查看，不允许提前建立现金快照。请切换到本月或历史月份。</div> : null}

              <div>
                <div className="mb-3 flex items-center justify-between"><div><h3 className="font-semibold text-slate-900">公司账户余额</h3><p className="mt-1 text-xs text-slate-500">只保存脱敏账户名称和末位，不保存完整银行卡号。</p></div><Button size="sm" variant="outline" onClick={openNewAccount} disabled={periodLocked || futureMonthSelected}><Plus className="mr-1 h-4 w-4" />新增账户</Button></div>
                {accountOpen ? <div className="mb-4 rounded-2xl border border-blue-200 bg-blue-50/50 p-4 shadow-sm sm:p-5">
                  <div className="mb-4 flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                    <div><h4 className="font-semibold text-slate-900">{accountForm.id ? '编辑现金账户' : '新增现金账户'}</h4><p className="mt-1 text-xs leading-5 text-slate-500">账户建立后，再在下方填写本月核对余额。不要录完整银行卡号、登录信息或密码。</p></div>
                    <Button size="sm" variant="ghost" onClick={() => setAccountOpen(false)}>取消</Button>
                  </div>
                  <div className="grid gap-4 sm:grid-cols-2">
                    <div className="sm:col-span-2"><Label htmlFor="cash-account-name">账户名称 *</Label><Input ref={accountNameRef} id="cash-account-name" className="mt-1 bg-white" value={accountForm.name} onChange={event => setAccountForm(current => ({ ...current, name: event.target.value }))} placeholder="例如：美国公司运营账户" /></div>
                    <div><Label>账户类型</Label><NativeSelect className="mt-1" value={accountForm.account_type} onChange={value => setAccountForm(current => ({ ...current, account_type: value }))} options={[{ value: 'bank', label: '银行账户' }, { value: 'payment_platform', label: '支付平台' }, { value: 'cash', label: '现金' }, { value: 'other', label: '其他' }]} /></div>
                    <div><Label>币种</Label><NativeSelect className="mt-1" value={accountForm.currency} onChange={value => setAccountForm(current => ({ ...current, currency: value as 'USD' | 'CNY' }))} options={[{ value: 'CNY', label: 'CNY' }, { value: 'USD', label: 'USD' }]} /></div>
                    <div><Label htmlFor="cash-account-mask">脱敏末位/简称</Label><Input id="cash-account-mask" className="mt-1 bg-white" value={accountForm.masked_identifier} onChange={event => setAccountForm(current => ({ ...current, masked_identifier: event.target.value }))} placeholder="例如：•••• 2850" /></div>
                    <div><Label htmlFor="cash-account-order">显示顺序</Label><Input id="cash-account-order" className="mt-1 bg-white" type="number" min="0" value={accountForm.sort_order} onChange={event => setAccountForm(current => ({ ...current, sort_order: event.target.value }))} /></div>
                    <div className="sm:col-span-2"><Label htmlFor="cash-account-notes">备注</Label><Input id="cash-account-notes" className="mt-1 bg-white" value={accountForm.notes} onChange={event => setAccountForm(current => ({ ...current, notes: event.target.value }))} placeholder="可选，例如账户用途或核对负责人" /></div>
                    {accountForm.id ? <label className="sm:col-span-2 flex items-center gap-2 text-sm text-slate-700"><input type="checkbox" checked={accountForm.is_active} onChange={event => setAccountForm(current => ({ ...current, is_active: event.target.checked }))} />继续用于后续现金快照</label> : null}
                  </div>
                  <div className="mt-4 flex flex-col-reverse gap-2 border-t border-blue-100 pt-4 sm:flex-row sm:justify-end"><Button variant="outline" onClick={() => setAccountOpen(false)}>取消</Button><Button onClick={() => void saveAccount()} disabled={saving}>{saving ? '保存中…' : '保存账户'}</Button></div>
                </div> : null}
                {editorAccounts.length ? <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">{editorAccounts.map(account => <div key={account.id} className="rounded-xl border border-slate-200 p-4">
                  <div className="flex items-start justify-between gap-3"><div><p className="font-medium text-slate-900">{account.name}</p><p className="mt-1 text-xs text-slate-400">{account.currency} · {account.masked_identifier || '未填写末位'}</p></div><button type="button" aria-label={`编辑 ${account.name}`} onClick={() => openEditAccount(account)} disabled={periodLocked} className="text-slate-400 hover:text-blue-600 disabled:opacity-40"><Pencil className="h-4 w-4" /></button></div>
                  <div className="mt-3 flex items-center gap-2"><span className="text-sm font-medium text-slate-500">{account.currency === 'USD' ? '$' : '¥'}</span><Input type="number" min="0" step="0.01" value={balances[account.id] || ''} onChange={event => setBalances(current => ({ ...current, [account.id]: event.target.value }))} disabled={periodLocked} placeholder="0.00" /></div>
                  {account.currency === 'USD' ? <p className="mt-2 text-xs text-slate-400">折合 {cny(Number(balances[account.id] || 0) * numericRate)}</p> : null}
                </div>)}</div> : <div className="rounded-xl border border-dashed p-8 text-center"><Landmark className="mx-auto h-7 w-7 text-slate-300" /><p className="mt-2 text-sm text-slate-500">先新增公司人民币或美元账户，再录入真实余额。</p><Button className="mt-3" size="sm" onClick={openNewAccount}><Plus className="mr-1 h-4 w-4" />新增第一个账户</Button></div>}
              </div>

              <div>
                <div className="mb-3 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between"><div><h3 className="font-semibold text-slate-900">受限资金</h3><p className="mt-1 text-xs text-slate-500">这些钱在账户里，但不能当作公司可自由使用的钱。</p></div><Button size="sm" variant="outline" onClick={() => setRestrictionOpen(true)} disabled={periodLocked || futureMonthSelected}><Plus className="mr-1 h-4 w-4" />手动新增</Button></div>
                {!periodLocked && overview.restriction_suggestions.length ? <div className="mb-3 rounded-xl border border-blue-200 bg-blue-50 p-4">
                  <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between"><div><p className="font-medium text-blue-900">系统找到 {overview.restriction_suggestions.length} 项可核对的受限资金</p><p className="mt-1 text-xs text-blue-700">合计约 {cny(overview.unrecorded_suggestion_cny)}。系统不会自动记账，加入后仍需你核对。</p></div><Button size="sm" onClick={addAllSuggestions}>全部加入待核对</Button></div>
                  <div className="mt-3 grid gap-2 md:grid-cols-2">{overview.restriction_suggestions.map(row => <button type="button" key={row.source_ref || row.description} onClick={() => addSuggestion(row)} className="flex items-center justify-between rounded-lg bg-white px-3 py-2 text-left text-sm text-blue-800 hover:bg-blue-100"><span>{row.category_label}</span><span className="font-semibold">{money(row.amount, row.currency)} <Plus className="ml-1 inline h-3.5 w-3.5" /></span></button>)}</div>
                </div> : null}
                {restrictions.length ? <div className="overflow-x-auto rounded-xl border"><table className="w-full min-w-[760px] text-sm"><thead className="bg-slate-50 text-left text-xs text-slate-500"><tr><th className="px-4 py-3">类别</th><th className="px-4 py-3">说明</th><th className="px-4 py-3">原币金额</th><th className="px-4 py-3">折合人民币</th><th className="px-4 py-3 text-right">操作</th></tr></thead><tbody>{restrictions.map((row, index) => <tr key={`${row.source_ref || row.description}-${index}`} className="border-t border-slate-100"><td className="px-4 py-3">{row.category_label || overview.restriction_categories.find(item => item.value === row.category)?.label || row.category}</td><td className="px-4 py-3"><p className="font-medium text-slate-800">{row.description}</p>{row.source_ref?.startsWith('system:') ? <p className="mt-1 text-xs text-blue-500">系统建议，已加入待核对</p> : null}</td><td className="px-4 py-3">{money(row.amount, row.currency)}</td><td className="px-4 py-3">{cny(Number(row.amount || 0) * (row.currency === 'USD' ? numericRate : 1))}</td><td className="px-4 py-3 text-right"><Button size="sm" variant="ghost" disabled={periodLocked} onClick={() => setRestrictions(current => current.filter((_, itemIndex) => itemIndex !== index))}>移除</Button></td></tr>)}</tbody></table></div> : <div className="rounded-xl border border-dashed p-6 text-center text-sm text-slate-400">当前没有受限资金。请确认客户投流款、待退款、待发工资、待付分润和税务预留是否确实为 0。</div>}
              </div>

              <div className="flex flex-col gap-3 border-t pt-4 sm:flex-row sm:items-center sm:justify-between">
                <p className="text-xs leading-5 text-slate-500">{overview.definitions.data_boundary}</p>
                <div className="flex gap-2">
                  {periodLocked ? isAdmin ? <Button variant="outline" onClick={() => setReopenOpen(true)}><UnlockKeyhole className="mr-2 h-4 w-4" />重新打开</Button> : null : <>
                    <Button variant="outline" onClick={() => void saveCashPeriod()} disabled={saving || futureMonthSelected}>保存草稿</Button>
                    {overview.cash_period ? <Button onClick={() => void transitionCashPeriod('lock')} disabled={saving || futureMonthSelected || overview.restriction_suggestions.length > 0}><LockKeyhole className="mr-2 h-4 w-4" />确认并锁定</Button> : null}
                  </>}
                </div>
              </div>
              {!periodLocked && overview.cash_period && overview.restriction_suggestions.length > 0 ? <p className="text-right text-xs text-amber-700">还有系统建议未加入，完成核对后才能锁定。</p> : null}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="signals" className="mt-4 space-y-4">
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <Card><CardContent className="p-4"><p className="text-sm text-slate-500">近 3 月平均净利润</p><p className="mt-2 text-2xl font-bold text-emerald-700">{cny(overview.operating_signals.three_month_average_profit_cny)}</p><p className="mt-1 text-xs text-slate-400">有效样本 {overview.operating_signals.profit_sample_months} 个月</p></CardContent></Card>
            <Card><CardContent className="p-4"><p className="text-sm text-slate-500">在合作代运营项目</p><p className="mt-2 text-2xl font-bold text-blue-700">{overview.operating_signals.active_managed_service_projects}</p><p className="mt-1 text-xs text-slate-400">当前主要现金引擎</p></CardContent></Card>
            <Card><CardContent className="p-4"><p className="text-sm text-slate-500">付费 OS 项目</p><p className="mt-2 text-2xl font-bold text-violet-700">{overview.operating_signals.paid_os_projects}</p><p className="mt-1 text-xs text-slate-400">餐饮 {overview.operating_signals.paid_restaurant_os_projects ?? 0} · 美业 {overview.operating_signals.paid_beauty_os_projects ?? 0}</p><p className="mt-1 text-xs font-medium text-violet-600">阶段门槛按单一产品最高值判断，不合并凑数</p></CardContent></Card>
            <Card><CardContent className="p-4"><p className="text-sm text-slate-500">高风险项目占比</p><p className={`mt-2 text-2xl font-bold ${overview.operating_signals.high_risk_ratio >= 0.2 ? 'text-rose-700' : 'text-emerald-700'}`}>{(overview.operating_signals.high_risk_ratio * 100).toFixed(1)}%</p><p className="mt-1 text-xs text-slate-400">{overview.operating_signals.high_risk_project_count}/{overview.operating_signals.health_project_count} 个项目</p></CardContent></Card>
          </div>
          <Card><CardHeader className="pb-3"><CardTitle className="text-base">团队产能与招聘门</CardTitle><p className="mt-1 text-xs text-slate-500">系统只提出招聘验证，不会因为客户数量增加就自动建议扩编。</p></CardHeader><CardContent><div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4"><div className="rounded-xl bg-slate-50 p-4"><p className="text-xs text-slate-500">在职/试用员工</p><p className="mt-2 text-xl font-bold text-slate-900">{overview.operating_signals.active_employee_count ?? 0}</p></div><div className="rounded-xl bg-slate-50 p-4"><p className="text-xs text-slate-500">合作中项目</p><p className="mt-2 text-xl font-bold text-slate-900">{teamCapacity.active_projects}</p><p className="mt-1 text-xs text-slate-400">未分配 {teamCapacity.unassigned_projects}</p></div><div className="rounded-xl bg-slate-50 p-4"><p className="text-xs text-slate-500">达到产能预警线</p><p className={`mt-2 text-xl font-bold ${teamCapacity.near_or_over_capacity ? 'text-amber-700' : 'text-emerald-700'}`}>{teamCapacity.near_or_over_capacity} 人</p></div><div className="rounded-xl bg-slate-50 p-4"><p className="text-xs text-slate-500">任务逾期率</p><p className={`mt-2 text-xl font-bold ${teamCapacity.overdue_rate >= 0.15 ? 'text-rose-700' : 'text-emerald-700'}`}>{(teamCapacity.overdue_rate * 100).toFixed(1)}%</p></div></div><div className={`mt-3 rounded-xl p-4 ${teamCapacity.hiring_level === 'hire' ? 'bg-rose-50 text-rose-800' : teamCapacity.hiring_level === 'process' ? 'bg-amber-50 text-amber-800' : 'bg-blue-50 text-blue-800'}`}><p className="font-semibold">{teamCapacity.hiring_title}</p><p className="mt-1 text-xs leading-5">{teamCapacity.hiring_message}</p></div></CardContent></Card>
          {overview.cash_history.length ? <Card><CardHeader className="pb-3"><CardTitle className="text-base">现金快照趋势</CardTitle><p className="mt-1 text-xs text-slate-500">最多保留最近 24 个月，草稿与已确认分开显示。</p></CardHeader><CardContent><div className="overflow-x-auto rounded-xl border"><table className="w-full min-w-[680px] text-sm"><thead className="bg-slate-50 text-left text-xs text-slate-500"><tr><th className="px-4 py-3">月份</th><th className="px-4 py-3">状态</th><th className="px-4 py-3 text-right">账户余额</th><th className="px-4 py-3 text-right">受限资金</th><th className="px-4 py-3 text-right">可用现金</th></tr></thead><tbody>{overview.cash_history.map(row => <tr key={row.year_month} className="border-t border-slate-100"><td className="px-4 py-3 font-medium text-slate-800">{row.year_month}</td><td className="px-4 py-3"><Badge className={row.status === 'locked' ? 'bg-violet-100 text-violet-700' : 'bg-amber-100 text-amber-700'}>{row.status === 'locked' ? '已确认' : '草稿'}</Badge></td><td className="px-4 py-3 text-right">{cny(row.account_balance_cny)}</td><td className="px-4 py-3 text-right text-amber-700">{cny(row.restricted_cny)}</td><td className={`px-4 py-3 text-right font-semibold ${row.free_cash_cny >= 0 ? 'text-emerald-700' : 'text-rose-700'}`}>{cny(row.free_cash_cny)}</td></tr>)}</tbody></table></div></CardContent></Card> : null}
          <Card><CardHeader className="pb-3"><CardTitle className="text-base">30 / 60 / 90 天现金推演</CardTitle><p className="mt-1 text-xs text-slate-500">只用于经营预估，不是银行余额承诺。</p></CardHeader><CardContent>{overview.cash_health.projections.length ? <div className="grid gap-3 md:grid-cols-3">{overview.cash_health.projections.map(row => <div key={row.days} className="rounded-xl border p-4"><p className="text-xs text-slate-500">{row.days} 天后</p><p className={`mt-2 text-xl font-bold ${row.free_cash_cny >= overview.cash_health.safety_target_cny ? 'text-emerald-700' : row.free_cash_cny >= 0 ? 'text-amber-700' : 'text-rose-700'}`}>{cny(row.free_cash_cny)}</p><p className="mt-2 text-xs leading-5 text-slate-400">{row.based_on}</p></div>)}</div> : <div className="rounded-xl border border-dashed p-8 text-center text-sm text-slate-400">暂不生成，避免用不完整数据误导决策。{overview.cash_health.projection_reason ? <span className="mt-2 block">{overview.cash_health.projection_reason}</span> : null}</div>}</CardContent></Card>
          <Card><CardContent className="p-5"><div className="grid gap-4 lg:grid-cols-3"><div className="rounded-xl bg-blue-50 p-4"><ShieldCheck className="h-5 w-5 text-blue-600" /><p className="mt-3 font-semibold text-blue-900">可用现金口径</p><p className="mt-2 text-xs leading-5 text-blue-700">{overview.definitions.free_cash}</p></div><div className="rounded-xl bg-emerald-50 p-4"><TrendingUp className="h-5 w-5 text-emerald-600" /><p className="mt-3 font-semibold text-emerald-900">利润与现金不混用</p><p className="mt-2 text-xs leading-5 text-emerald-700">{overview.definitions.profit_vs_cash}</p></div><div className="rounded-xl bg-amber-50 p-4"><AlertTriangle className="h-5 w-5 text-amber-600" /><p className="mt-3 font-semibold text-amber-900">老板确认边界</p><p className="mt-2 text-xs leading-5 text-amber-700">{overview.definitions.data_boundary}</p></div></div></CardContent></Card>
        </TabsContent>
      </Tabs>

      <Dialog open={settingsOpen} onOpenChange={setSettingsOpen}>
        <DialogContent className="max-w-2xl"><DialogHeader><DialogTitle>公司目标与现金安全参数</DialogTitle></DialogHeader>{settingsForm ? <div className="grid gap-4 py-2 sm:grid-cols-2">
          <div><Label>目标开始日期</Label><Input className="mt-1" type="date" value={settingsForm.target_start_date} onChange={event => setSettingsForm(current => current ? { ...current, target_start_date: event.target.value } : current)} /></div>
          <div><Label>目标结束日期</Label><Input className="mt-1" type="date" value={settingsForm.target_end_date} onChange={event => setSettingsForm(current => current ? { ...current, target_end_date: event.target.value } : current)} /></div>
          <div><Label>累计净利润目标（CNY）</Label><Input className="mt-1" type="number" min="1" value={settingsForm.five_year_profit_target_cny} onChange={event => setSettingsForm(current => current ? { ...current, five_year_profit_target_cny: event.target.value } : current)} /></div>
          <div><Label>月固定支出基线（CNY）</Label><Input className="mt-1" type="number" min="1" value={settingsForm.monthly_fixed_expense_cny} onChange={event => setSettingsForm(current => current ? { ...current, monthly_fixed_expense_cny: event.target.value } : current)} /></div>
          <div><Label>现金安全月数</Label><Input className="mt-1" type="number" min="1" max="36" value={settingsForm.cash_reserve_months} onChange={event => setSettingsForm(current => current ? { ...current, cash_reserve_months: event.target.value } : current)} /></div>
          <div><Label>缺失月份默认预估汇率</Label><Input className="mt-1" type="number" min="0.1" max="20" step="0.0001" value={settingsForm.default_usd_cny_rate} onChange={event => setSettingsForm(current => current ? { ...current, default_usd_cny_rate: event.target.value } : current)} /></div>
          <div className="sm:col-span-2"><Label>当前经营焦点</Label><Input className="mt-1" value={settingsForm.current_focus} onChange={event => setSettingsForm(current => current ? { ...current, current_focus: event.target.value } : current)} /></div>
          <p className="sm:col-span-2 rounded-lg bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-800">月固定支出用于安全线和现金跑道，不会自动写入财务支出。正式利润仍沿用现有财务数据。</p>
        </div> : null}<DialogFooter><Button variant="outline" onClick={() => setSettingsOpen(false)}>取消</Button><Button onClick={() => void saveSettings()} disabled={saving}>保存设置</Button></DialogFooter></DialogContent>
      </Dialog>

      <Dialog open={restrictionOpen} onOpenChange={setRestrictionOpen}>
        <DialogContent><DialogHeader><DialogTitle>新增受限资金</DialogTitle></DialogHeader><div className="grid gap-4 py-2 sm:grid-cols-2">
          <div><Label>类别</Label><NativeSelect className="mt-1" value={restrictionDraft.category} onChange={value => setRestrictionDraft(current => ({ ...current, category: value }))} options={overview.restriction_categories} /></div>
          <div><Label>币种</Label><NativeSelect className="mt-1" value={restrictionDraft.currency} onChange={value => setRestrictionDraft(current => ({ ...current, currency: value as 'USD' | 'CNY' }))} options={[{ value: 'CNY', label: 'CNY' }, { value: 'USD', label: 'USD' }]} /></div>
          <div className="sm:col-span-2"><Label>说明 *</Label><Input className="mt-1" value={restrictionDraft.description} onChange={event => setRestrictionDraft(current => ({ ...current, description: event.target.value }))} placeholder="例如：2026 年企业所得税预留" /></div>
          <div><Label>金额 *</Label><Input className="mt-1" type="number" min="0.01" step="0.01" value={restrictionDraft.amount || ''} onChange={event => setRestrictionDraft(current => ({ ...current, amount: Number(event.target.value) }))} /></div>
          <div><Label>折合人民币</Label><Input className="mt-1" disabled value={cny(Number(restrictionDraft.amount || 0) * (restrictionDraft.currency === 'USD' ? numericRate : 1))} /></div>
          <div className="sm:col-span-2"><Label>备注</Label><Input className="mt-1" value={restrictionDraft.notes || ''} onChange={event => setRestrictionDraft(current => ({ ...current, notes: event.target.value }))} /></div>
        </div><DialogFooter><Button variant="outline" onClick={() => setRestrictionOpen(false)}>取消</Button><Button onClick={saveRestriction}>加入待核对</Button></DialogFooter></DialogContent>
      </Dialog>

      <Dialog open={reopenOpen} onOpenChange={setReopenOpen}>
        <DialogContent><DialogHeader><DialogTitle>重新打开已确认快照</DialogTitle></DialogHeader><div className="py-2"><Label>修改原因 *</Label><Textarea className="mt-1" value={reopenReason} onChange={event => setReopenReason(event.target.value)} placeholder="说明为什么需要修改已确认的账户余额或受限资金" /></div><DialogFooter><Button variant="outline" onClick={() => setReopenOpen(false)}>取消</Button><Button onClick={() => void transitionCashPeriod('reopen', reopenReason)} disabled={saving || !reopenReason.trim()}>确认重新打开</Button></DialogFooter></DialogContent>
      </Dialog>

      <Dialog open={decisionOpen} onOpenChange={setDecisionOpen}>
        <DialogContent className="max-w-xl"><DialogHeader><DialogTitle>记录老板经营决策</DialogTitle></DialogHeader><div className="space-y-4 py-2">
          <div className="rounded-xl bg-slate-50 p-4"><p className="font-semibold text-slate-900">{recommendation.title}</p><p className="mt-2 text-xs leading-5 text-slate-600">{recommendation.action}</p></div>
          <div><Label>决定</Label><NativeSelect className="mt-1" value={decisionStatus} onChange={value => setDecisionStatus(value as typeof decisionStatus)} options={[{ value: 'accepted', label: '采纳并执行' }, { value: 'deferred', label: '暂缓' }, { value: 'rejected', label: '不采纳' }, { value: 'completed', label: '已完成' }]} /></div>
          <div><Label>决定说明{decisionStatus === 'deferred' || decisionStatus === 'rejected' ? ' *' : ''}</Label><Textarea className="mt-1" value={decisionNote} onChange={event => setDecisionNote(event.target.value)} placeholder="为什么这样决定，后续复盘时可追溯" /></div>
          <div><Label>下次复盘日期</Label><Input className="mt-1" type="date" value={nextReviewDate} onChange={event => setNextReviewDate(event.target.value)} /></div>
          {decisionStatus === 'accepted' ? <label className="flex items-center gap-2 text-sm text-slate-700"><input type="checkbox" checked={createTask} onChange={event => setCreateTask(event.target.checked)} />同时生成一条任务，进入任务协作闭环</label> : null}
        </div><DialogFooter><Button variant="outline" onClick={() => setDecisionOpen(false)}>取消</Button><Button onClick={() => void saveDecision()} disabled={saving}>保存决定</Button></DialogFooter></DialogContent>
      </Dialog>

      <Dialog open={auditOpen} onOpenChange={setAuditOpen}>
        <DialogContent className="max-w-xl"><DialogHeader><DialogTitle>{selectedMonth} 现金快照操作记录</DialogTitle></DialogHeader><div className="max-h-[55vh] space-y-2 overflow-y-auto py-2">{auditRows.map(row => <div key={row.id} className="rounded-xl border p-3"><div className="flex items-center justify-between"><p className="font-medium text-slate-900">{row.action === 'saved' ? '保存草稿' : row.action === 'lock' ? '确认锁定' : row.action === 'reopen' ? '重新打开' : row.action}</p><span className="text-xs text-slate-400">{new Date(row.created_at).toLocaleString('zh-CN', { hour12: false })}</span></div><p className="mt-1 text-xs text-slate-500">{row.actor_name} · {row.actor_role}</p>{row.reason ? <p className="mt-2 rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-600">{row.reason}</p> : null}</div>)}{!auditRows.length ? <p className="py-8 text-center text-sm text-slate-400">暂无操作记录</p> : null}</div></DialogContent>
      </Dialog>
    </div>
  );
}
