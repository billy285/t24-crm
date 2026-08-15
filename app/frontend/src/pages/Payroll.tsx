import { useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertTriangle, BarChart3, Building2, CalendarRange, Copy, Download, History, Lock, Plus,
  Search, Trash2, TrendingUp, Unlock, Users, WalletCards,
} from 'lucide-react';
import { toast } from 'sonner';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { NativeSelect } from '@/components/ui/native-select';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Textarea } from '@/components/ui/textarea';
import { invokeWithAuth } from '@/lib/tokenStore';
import { useRole } from '@/lib/role-context';

type PayrollStatus = 'draft' | 'confirmed' | 'paid';
type PaymentStatus = 'pending' | 'partial' | 'paid' | 'failed' | 'returned' | 'supplemental';
type PayrollView = 'processing' | 'analytics' | 'ledger';
type Employee = { id: number; name: string; employee_code?: string; department?: string; hire_date?: string };
type PayrollItem = {
  id?: number; employee_id?: number; employee_name: string; employee_code?: string; department?: string; hire_date?: string;
  payment_method: string; payment_account?: string; payment_account_masked?: string;
  base_salary: number; fixed_performance: number; commission: number; bonus: number; allowance: number; reimbursement: number;
  absence_deduction: number; performance_deduction: number; salary_advance_deduction: number; other_deduction: number;
  payment_status: PaymentStatus; payment_date?: string; payment_reference?: string; receipt_url?: string; notes?: string;
  gross_amount?: number; deduction_amount?: number; net_amount?: number;
};
type PayrollData = {
  sheet: { id: number; month: string; status: PayrollStatus; currency: string; reopen_reason?: string };
  items: PayrollItem[];
  totals: { gross: number; deductions: number; net: number };
};
type AuditLog = { id: number; action: string; actor_name?: string; actor_role: string; reason?: string; created_at: string };
type ReportBucket = {
  gross: number; fixed: number; variable: number; deductions: number; net: number;
  paid_amount: number; pending_amount: number; headcount: number;
};
type MonthlyReport = ReportBucket & { month: string; status: PayrollStatus | 'none' };
type DepartmentReport = ReportBucket & { department: string };
type EmployeeReport = {
  employee_id?: number; employee_code?: string; employee_name: string; department: string; months: number;
  base_salary: number; fixed_performance: number; commission: number; bonus: number; allowance: number; reimbursement: number;
  gross: number; deductions: number; net: number; paid_amount: number; pending_amount: number;
  latest_month: string; latest_payment_status: PaymentStatus;
};
type PayrollReport = {
  year: number; currency: string; independent_accounting: boolean; has_data: boolean;
  totals: ReportBucket & { active_months: number; average_monthly: number; average_per_employee: number; variable_ratio: number };
  monthly: MonthlyReport[];
  departments: DepartmentReport[];
  employees: EmployeeReport[];
  payment_statuses: { status: PaymentStatus; count: number; amount: number }[];
};

const blankItem = (): PayrollItem => ({
  employee_name: '', payment_method: 'alipay', base_salary: 0, fixed_performance: 0,
  commission: 0, bonus: 0, allowance: 0, reimbursement: 0, absence_deduction: 0,
  performance_deduction: 0, salary_advance_deduction: 0, other_deduction: 0,
  payment_status: 'pending',
});
const money = (value = 0) => `¥${Number(value || 0).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const statusLabels: Record<PayrollStatus | 'none', string> = { draft: '草稿录入', confirmed: '管理员已确认', paid: '已发放锁定', none: '未建立' };
const paymentLabels: Record<PaymentStatus, string> = { pending: '待发放', partial: '部分发放', paid: '已发放', failed: '发放失败', returned: '已退回', supplemental: '待补发' };
const methodLabels: Record<string, string> = { alipay: '支付宝', bank_card: '国内银行卡', wechat: '微信', cash: '现金', other: '其他' };
const auditLabels: Record<string, string> = { legacy_import: '旧数据迁移', item_created: '新增明细', item_updated: '修改明细', item_deleted: '删除明细', confirm: '管理员确认', bulk_mark_paid: '批量登记已发放', mark_paid: '整表发放完成', reopen: '重新打开' };
const beijingToday = () => new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai' }).format(new Date());

function errorMessage(error: any, fallback: string) {
  const detail = error?.data?.detail || error?.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  if (detail?.message) return String(detail.message);
  return error?.message || fallback;
}

function downloadCsv(filename: string, header: string[], rows: (string | number | undefined)[][]) {
  const lines = rows.map(row => row.map(value => `"${String(value ?? '').replaceAll('"', '""')}"`).join(','));
  const blob = new Blob([`\ufeff${header.join(',')}\n${lines.join('\n')}`], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

function MetricCard({ label, value, detail, tone = 'slate' }: { label: string; value: string; detail?: string; tone?: 'slate' | 'blue' | 'emerald' | 'rose' | 'amber' }) {
  const tones = { slate: 'text-slate-900', blue: 'text-blue-700', emerald: 'text-emerald-700', rose: 'text-rose-700', amber: 'text-amber-700' };
  return <Card><CardContent className="p-4"><p className="text-xs text-slate-500">{label}</p><p className={`mt-1 text-xl font-bold ${tones[tone]}`}>{value}</p>{detail && <p className="mt-1 text-xs text-slate-500">{detail}</p>}</CardContent></Card>;
}

export default function Payroll() {
  const { role, isAdmin } = useRole();
  const today = new Date();
  const currentMonth = today.toISOString().slice(0, 7);
  const currentYear = today.getFullYear();
  const [view, setView] = useState<PayrollView>('processing');
  const [month, setMonth] = useState(currentMonth);
  const [reportYear, setReportYear] = useState(currentYear);
  const [data, setData] = useState<PayrollData | null>(null);
  const [report, setReport] = useState<PayrollReport | null>(null);
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [editing, setEditing] = useState<PayrollItem | null>(null);
  const [audit, setAudit] = useState<AuditLog[]>([]);
  const [showAudit, setShowAudit] = useState(false);
  const [ledgerSearch, setLedgerSearch] = useState('');
  const [loading, setLoading] = useState(true);
  const [reportLoading, setReportLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [transitioning, setTransitioning] = useState(false);
  const [showMarkPaid, setShowMarkPaid] = useState(false);
  const [bulkPaymentDate, setBulkPaymentDate] = useState(beijingToday());
  const markPaidDialogRef = useRef<HTMLDivElement>(null);
  const canAdmin = isAdmin || role === 'super_admin';

  const load = async () => {
    setLoading(true);
    try {
      const [sheetRes, employeeRes] = await Promise.all([
        invokeWithAuth({ url: `/api/v1/payroll?month=${month}`, method: 'GET' }),
        invokeWithAuth({ url: '/api/v1/payroll/employees', method: 'GET' }),
      ]);
      setData(sheetRes.data);
      setEmployees(employeeRes.data || []);
    } catch (error: any) {
      toast.error(errorMessage(error, '工资表读取失败'));
    } finally {
      setLoading(false);
    }
  };

  const loadReport = async () => {
    setReportLoading(true);
    try {
      const response = await invokeWithAuth({ url: `/api/v1/payroll/reports?year=${reportYear}`, method: 'GET' });
      setReport(response.data);
    } catch (error: any) {
      setReport(null);
      toast.error(errorMessage(error, '工资报表读取失败'));
    } finally {
      setReportLoading(false);
    }
  };

  useEffect(() => { void load(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [month]);
  useEffect(() => { if (view !== 'processing') void loadReport(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [view, reportYear]);
  useEffect(() => {
    if (showMarkPaid && data?.sheet.status && data.sheet.status !== 'confirmed') setShowMarkPaid(false);
  }, [data?.sheet.status, showMarkPaid]);
  useEffect(() => {
    if (!showMarkPaid) return undefined;
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const focusFrame = window.requestAnimationFrame(() => markPaidDialogRef.current?.focus());
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !transitioning) setShowMarkPaid(false);
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      window.cancelAnimationFrame(focusFrame);
      document.removeEventListener('keydown', handleKeyDown);
      previousFocus?.focus();
    };
  }, [showMarkPaid, transitioning]);

  const rows = data?.items || [];
  const locked = data?.sheet.status === 'paid';
  const pendingRows = rows.filter(row => row.payment_status === 'pending');
  const blockingRows = rows.filter(row => !['pending', 'paid'].includes(row.payment_status));
  const totals = data?.totals || { gross: 0, deductions: 0, net: 0 };
  const additions = useMemo(() => rows.reduce((sum, row) => sum + row.commission + row.bonus + row.allowance + row.reimbursement, 0), [rows]);
  const reportMonths = useMemo(() => report?.monthly.filter(item => item.headcount > 0) || [], [report]);
  const maxMonthlyNet = Math.max(1, ...reportMonths.map(item => Math.max(0, item.net)));
  const filteredLedger = useMemo(() => {
    const keyword = ledgerSearch.trim().toLowerCase();
    if (!keyword) return report?.employees || [];
    return (report?.employees || []).filter(item => [item.employee_name, item.employee_code, item.department].some(value => String(value || '').toLowerCase().includes(keyword)));
  }, [ledgerSearch, report]);
  const reportAlerts = useMemo(() => {
    if (!report?.has_data) return [];
    const alerts: string[] = [];
    for (let index = 1; index < reportMonths.length; index += 1) {
      const previous = reportMonths[index - 1];
      const current = reportMonths[index];
      if (previous.net > 0) {
        const change = (current.net - previous.net) / previous.net * 100;
        if (Math.abs(change) >= 20) alerts.push(`${current.month} 人力成本较 ${previous.month} ${change > 0 ? '上升' : '下降'} ${Math.abs(change).toFixed(1)}%，建议核对人员、提成或奖金变化。`);
      }
      if (previous.headcount !== current.headcount) alerts.push(`${current.month} 工资人数由 ${previous.headcount} 人变为 ${current.headcount} 人，请确认入离职或漏录情况。`);
    }
    if (report.totals.pending_amount > 0) alerts.push(`本年度仍有 ${money(report.totals.pending_amount)} 未完成发放，请进入月度工资表核对。`);
    return alerts.slice(-4);
  }, [report, reportMonths]);

  const saveItem = async () => {
    if (!editing?.employee_name.trim()) return toast.error('请选择员工或填写员工姓名');
    setSaving(true);
    try {
      const id = editing.id;
      await invokeWithAuth({ url: id ? `/api/v1/payroll/${month}/items/${id}` : `/api/v1/payroll/${month}/items`, method: id ? 'PUT' : 'POST', data: editing });
      toast.success('工资明细已保存并记录操作日志');
      setEditing(null);
      await load();
    } catch (error: any) {
      toast.error(errorMessage(error, '保存失败'));
    } finally {
      setSaving(false);
    }
  };

  const removeItem = async (item: PayrollItem) => {
    if (!item.id || !window.confirm(`确认删除 ${item.employee_name} 的本月工资明细？`)) return;
    try {
      await invokeWithAuth({ url: `/api/v1/payroll/${month}/items/${item.id}`, method: 'DELETE' });
      toast.success('已删除');
      await load();
    } catch (error: any) {
      toast.error(errorMessage(error, '删除失败'));
    }
  };

  const transition = async (action: 'confirm' | 'mark_paid' | 'reopen', options?: { paymentDate?: string; confirmAllPending?: boolean }) => {
    if (transitioning) return;
    let reason: string | null = null;
    if (action === 'reopen') {
      reason = window.prompt('请输入重新打开并修改已发放工资表的原因：');
      if (!reason?.trim()) return;
    }
    setTransitioning(true);
    try {
      const response = await invokeWithAuth({
        url: `/api/v1/payroll/${month}/transition`,
        method: 'POST',
        data: {
          action,
          reason,
          payment_date: options?.paymentDate,
          confirm_all_pending: Boolean(options?.confirmAllPending),
        },
      });
      toast.success(response.data?.message || '工资表状态已更新');
      if (action === 'mark_paid') setShowMarkPaid(false);
      await load();
    } catch (error: any) {
      toast.error(errorMessage(error, '状态更新失败'));
      await load();
    } finally {
      setTransitioning(false);
    }
  };

  const copyPrevious = async () => {
    const date = new Date(`${month}-01T00:00:00`);
    date.setMonth(date.getMonth() - 1);
    const previousMonth = date.toISOString().slice(0, 7);
    try {
      const response = await invokeWithAuth({ url: `/api/v1/payroll?month=${previousMonth}`, method: 'GET' });
      const previous: PayrollItem[] = response.data?.items || [];
      if (!previous.length) return toast.error('上月没有可复制的工资明细');
      for (const row of previous) {
        const payload = { ...row, id: undefined, payment_account: undefined, commission: 0, bonus: 0, allowance: 0, reimbursement: 0, absence_deduction: 0, performance_deduction: 0, salary_advance_deduction: 0, other_deduction: 0, payment_status: 'pending', payment_date: undefined, payment_reference: undefined, receipt_url: undefined };
        await invokeWithAuth({ url: `/api/v1/payroll/${month}/items`, method: 'POST', data: payload });
      }
      toast.success('已复制上月人员和固定工资，动态项目已清零');
      await load();
    } catch (error: any) {
      toast.error(errorMessage(error, '复制失败，请检查本月是否已有相同员工'));
    }
  };

  const showAuditLog = async () => {
    try {
      const response = await invokeWithAuth({ url: `/api/v1/payroll/${month}/audit`, method: 'GET' });
      setAudit(response.data || []);
      setShowAudit(true);
    } catch {
      toast.error('操作日志读取失败');
    }
  };

  const exportMonthlyCsv = () => downloadCsv(
    `工资表_${month}.csv`,
    ['员工编号', '姓名', '部门', '基本工资', '固定绩效', '提成', '奖金', '补贴', '报销', '扣款', '实发', '发放方式', '发放状态', '发放日期', '流水号'],
    rows.map(row => [row.employee_code, row.employee_name, row.department, row.base_salary, row.fixed_performance, row.commission, row.bonus, row.allowance, row.reimbursement, row.deduction_amount, row.net_amount, methodLabels[row.payment_method], paymentLabels[row.payment_status], row.payment_date, row.payment_reference]),
  );

  const exportAnnualCsv = () => downloadCsv(
    `员工年度工资台账_${reportYear}.csv`,
    ['员工编号', '姓名', '部门', '有工资月份', '基本工资累计', '固定绩效累计', '提成', '奖金', '补贴', '报销', '应发', '扣款', '实发', '已发', '待发', '最近状态'],
    (report?.employees || []).map(item => [item.employee_code, item.employee_name, item.department, item.months, item.base_salary, item.fixed_performance, item.commission, item.bonus, item.allowance, item.reimbursement, item.gross, item.deductions, item.net, item.paid_amount, item.pending_amount, paymentLabels[item.latest_payment_status]]),
  );

  const chooseEmployee = (id: string) => {
    const employee = employees.find(item => item.id === Number(id));
    setEditing(current => current ? { ...current, employee_id: employee?.id, employee_name: employee?.name || '', employee_code: employee?.employee_code, department: employee?.department, hire_date: employee?.hire_date } : current);
  };

  const field = (label: string, key: keyof PayrollItem, type = 'number') => <div><Label className="text-xs text-slate-500">{label}</Label><Input className="mt-1" type={type} value={String(editing?.[key] ?? '')} onChange={event => setEditing(current => current ? { ...current, [key]: type === 'number' ? Math.max(0, Number(event.target.value) || 0) : event.target.value } : current)} /></div>;

  if (loading && !data) return <div className="app-page"><div className="app-loading">正在读取工资表...</div></div>;

  return <div className="app-page space-y-5">
    <div className="app-page-title flex-col items-start sm:flex-row sm:items-center">
      <div>
        <p className="text-xs font-medium uppercase tracking-[0.16em] text-blue-600">T24 Marketing · Payroll</p>
        <h1 className="mt-1 text-2xl font-bold text-slate-900">工资表与人力成本</h1>
        <p className="mt-1 text-sm text-slate-500">国内员工 · CNY · 独立核算，不自动进入财务管理或经营利润</p>
      </div>
      <div className="flex flex-wrap gap-2">
        {view === 'processing' && <Button variant="outline" size="sm" onClick={showAuditLog}><History className="mr-1 h-4 w-4" />操作日志</Button>}
        <Button variant="outline" size="sm" onClick={view === 'processing' ? exportMonthlyCsv : exportAnnualCsv} disabled={view === 'processing' ? !rows.length : !report?.employees.length}><Download className="mr-1 h-4 w-4" />{view === 'processing' ? '导出当月' : '导出年度台账'}</Button>
      </div>
    </div>

    <Tabs value={view} onValueChange={value => setView(value as PayrollView)}>
      <TabsList className="h-auto w-full justify-start gap-1 overflow-x-auto bg-slate-100 p-1 sm:w-auto">
        <TabsTrigger value="processing" className="gap-2"><WalletCards className="h-4 w-4" />工资处理</TabsTrigger>
        <TabsTrigger value="analytics" className="gap-2"><BarChart3 className="h-4 w-4" />报表分析</TabsTrigger>
        <TabsTrigger value="ledger" className="gap-2"><CalendarRange className="h-4 w-4" />年度台账</TabsTrigger>
      </TabsList>

      <TabsContent value="processing" className="mt-5 space-y-5">
        <Card className="border-blue-100 bg-blue-50/40">
          <CardContent className="flex flex-wrap items-end gap-4 p-4">
            <div><Label>工资月份</Label><Input type="month" value={month} onChange={event => setMonth(event.target.value)} className="mt-1 w-44 bg-white" /></div>
            <div><Label>流程状态</Label><div className="mt-2"><Badge className={data?.sheet.status === 'paid' ? 'bg-emerald-100 text-emerald-700' : data?.sheet.status === 'confirmed' ? 'bg-blue-100 text-blue-700' : 'bg-slate-100 text-slate-700'}>{data ? statusLabels[data.sheet.status] : '-'}</Badge></div></div>
            <p className="text-xs text-slate-500">录入：财务/管理员 · 确认：管理员 · 发放：财务/管理员</p>
            <div className="ml-auto flex flex-wrap gap-2">
              <Button variant="outline" onClick={copyPrevious} disabled={locked || rows.length > 0}><Copy className="mr-1 h-4 w-4" />复制上月</Button>
              {data?.sheet.status === 'draft' && canAdmin && <Button onClick={() => transition('confirm')} disabled={!rows.length || transitioning}><Lock className="mr-1 h-4 w-4" />{transitioning ? '处理中...' : '确认工资表'}</Button>}
              {data?.sheet.status === 'confirmed' && <Button onClick={() => { setBulkPaymentDate(beijingToday()); setShowMarkPaid(true); }} disabled={transitioning}><WalletCards className="mr-1 h-4 w-4" />{blockingRows.length ? `${blockingRows.length} 人需先处理` : pendingRows.length ? `登记 ${pendingRows.length} 人并锁定` : '完成并锁定整表'}</Button>}
              {data?.sheet.status === 'paid' && canAdmin && <Button variant="outline" onClick={() => transition('reopen')} disabled={transitioning}><Unlock className="mr-1 h-4 w-4" />{transitioning ? '处理中...' : '带原因重新打开'}</Button>}
            </div>
          </CardContent>
        </Card>

        {data?.sheet.status === 'confirmed' && (pendingRows.length > 0 || blockingRows.length > 0) && <div className={`rounded-xl border px-4 py-3 text-sm ${blockingRows.length ? 'border-rose-200 bg-rose-50 text-rose-800' : 'border-amber-200 bg-amber-50 text-amber-800'}`}>
          {blockingRows.length
            ? `当前有 ${blockingRows.length} 人处于部分发放、失败、退回或待补发状态，必须先逐条核对。`
            : `当前有 ${pendingRows.length} 人待登记发放。确认实际发放日期后，可一次完成登记并锁定整表。`}
        </div>}

        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <MetricCard label="应发工资" value={money(totals.gross)} />
          <MetricCard label="动态应发" value={money(additions)} tone="blue" />
          <MetricCard label="应扣项目" value={money(totals.deductions)} tone="rose" />
          <MetricCard label="实发工资" value={money(totals.net)} tone="emerald" />
        </div>

        <Card><CardContent className="p-4">
          <div className="mb-4 flex items-center justify-between">
            <div><h2 className="font-semibold text-slate-800">员工工资明细</h2><p className="mt-1 text-xs text-slate-500">账号仅显示末四位；发放完成后整表锁定，修改会留下审计记录</p></div>
            <Button onClick={() => setEditing(blankItem())} disabled={locked}><Plus className="mr-1 h-4 w-4" />新增员工</Button>
          </div>
          {!rows.length ? <div className="app-empty">本月暂无工资明细</div> : <div className="app-table-wrap"><table className="w-full min-w-[1040px] text-sm"><thead><tr className="border-b bg-slate-50 text-left text-xs text-slate-500"><th className="px-3 py-3">员工</th><th className="px-3 py-3">应发</th><th className="px-3 py-3">应扣</th><th className="px-3 py-3">实发</th><th className="px-3 py-3">发放账户</th><th className="px-3 py-3">发放状态</th><th className="px-3 py-3">凭证</th><th className="px-3 py-3">操作</th></tr></thead><tbody>{rows.map(row => <tr key={row.id} className="border-b border-slate-100"><td className="px-3 py-3"><p className="font-medium text-slate-900">{row.employee_name}</p><p className="text-xs text-slate-500">{row.employee_code || '无编号'} · {row.department || '未设置部门'}</p></td><td className="px-3 py-3">{money(row.gross_amount)}</td><td className="px-3 py-3 text-rose-600">{money(row.deduction_amount)}</td><td className="px-3 py-3 font-semibold text-emerald-600">{money(row.net_amount)}</td><td className="px-3 py-3"><p>{methodLabels[row.payment_method] || row.payment_method}</p><p className="text-xs text-slate-500">{row.payment_account_masked || '未填写'}</p></td><td className="px-3 py-3"><Badge variant="outline">{paymentLabels[row.payment_status]}</Badge><p className="mt-1 text-xs text-slate-500">{row.payment_date || '-'}</p></td><td className="px-3 py-3 text-xs">{row.payment_reference || '-'}</td><td className="px-3 py-3"><div className="flex gap-1"><Button size="sm" variant="outline" onClick={() => setEditing({ ...row, payment_account: '' })} disabled={locked}>编辑</Button><Button size="sm" variant="ghost" onClick={() => removeItem(row)} disabled={data?.sheet.status !== 'draft'}><Trash2 className="h-4 w-4 text-rose-500" /></Button></div></td></tr>)}</tbody></table></div>}
        </CardContent></Card>
      </TabsContent>

      <TabsContent value="analytics" className="mt-5 space-y-5">
        <Card className="border-indigo-100 bg-gradient-to-r from-indigo-50 via-white to-blue-50"><CardContent className="flex flex-wrap items-center gap-4 p-4"><div className="flex items-center gap-3"><TrendingUp className="h-8 w-8 text-indigo-600" /><div><p className="font-semibold text-slate-900">老板人力成本报表</p><p className="text-xs text-slate-500">只汇总工资表，不写入财务经营利润。</p></div></div><div className="ml-auto flex items-center gap-2"><Label>统计年度</Label><NativeSelect value={String(reportYear)} onChange={value => setReportYear(Number(value))} options={Array.from({ length: 5 }, (_, index) => currentYear - index).map(year => ({ value: String(year), label: `${year} 年` }))} className="w-32 bg-white" /></div></CardContent></Card>
        {reportLoading ? <div className="app-loading">正在生成工资报表...</div> : !report?.has_data ? <Card><CardContent className="p-10 text-center"><BarChart3 className="mx-auto h-10 w-10 text-slate-300" /><p className="mt-3 font-medium text-slate-700">{reportYear} 年暂无工资数据</p><p className="mt-1 text-sm text-slate-500">完成任意月份工资录入后，趋势、部门成本和发放状态会自动生成。</p></CardContent></Card> : <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
            <MetricCard label="年度实发工资" value={money(report.totals.net)} detail={`应发 ${money(report.totals.gross)} · 扣款 ${money(report.totals.deductions)}`} tone="emerald" />
            <MetricCard label="覆盖员工" value={`${report.totals.headcount} 人`} detail={`${report.totals.active_months} 个有工资月份`} tone="blue" />
            <MetricCard label="月均人力成本" value={money(report.totals.average_monthly)} detail="按有工资数据月份计算" />
            <MetricCard label="已发 / 待发" value={money(report.totals.paid_amount)} detail={`待处理 ${money(report.totals.pending_amount)}`} tone={report.totals.pending_amount > 0 ? 'amber' : 'emerald'} />
            <MetricCard label="浮动工资占比" value={`${report.totals.variable_ratio}%`} detail={`提成、奖金、补贴、报销 ${money(report.totals.variable)}`} tone="blue" />
          </div>

          {reportAlerts.length > 0 && <Card className="border-amber-200 bg-amber-50/60"><CardContent className="p-5"><div className="flex items-start gap-3"><AlertTriangle className="mt-0.5 h-5 w-5 text-amber-600" /><div><h2 className="font-semibold text-amber-900">需要老板关注</h2><div className="mt-2 space-y-1">{reportAlerts.map(alert => <p key={alert} className="text-sm text-amber-800">• {alert}</p>)}</div><p className="mt-2 text-xs text-amber-700">系统只提示变化，不自动调整工资或员工绩效。</p></div></div></CardContent></Card>}

          <Card><CardContent className="p-5"><div className="mb-4"><h2 className="font-semibold text-slate-900">月度工资趋势</h2><p className="mt-1 text-xs text-slate-500">观察团队人数与人力成本变化，不作为员工绩效排名。</p></div><div className="space-y-3">{reportMonths.map(item => <div key={item.month} className="grid grid-cols-[72px_1fr_auto] items-center gap-3"><p className="text-sm font-medium text-slate-700">{item.month.slice(5)}月</p><div className="h-8 overflow-hidden rounded-md bg-slate-100"><div className="flex h-full items-center rounded-md bg-gradient-to-r from-blue-500 to-indigo-500 px-3 text-xs font-medium text-white" style={{ width: `${Math.max(8, item.net / maxMonthlyNet * 100)}%` }}>{money(item.net)}</div></div><div className="w-28 text-right"><p className="text-xs text-slate-500">{item.headcount} 人</p><Badge variant="outline" className="mt-1">{statusLabels[item.status]}</Badge></div></div>)}</div></CardContent></Card>

          <div className="grid gap-5 xl:grid-cols-[1.4fr_1fr]">
            <Card><CardContent className="p-5"><div className="mb-4 flex items-center gap-2"><Building2 className="h-5 w-5 text-blue-600" /><div><h2 className="font-semibold text-slate-900">部门人力成本</h2><p className="text-xs text-slate-500">用于编制与预算判断，不做员工排名。</p></div></div><div className="app-table-wrap"><table className="w-full min-w-[680px] text-sm"><thead><tr className="border-b bg-slate-50 text-left text-xs text-slate-500"><th className="px-3 py-3">部门</th><th className="px-3 py-3">人数</th><th className="px-3 py-3">固定工资</th><th className="px-3 py-3">浮动工资</th><th className="px-3 py-3">扣款</th><th className="px-3 py-3">实发</th><th className="px-3 py-3">人均</th></tr></thead><tbody>{report.departments.map(item => <tr key={item.department} className="border-b border-slate-100"><td className="px-3 py-3 font-medium">{item.department}</td><td className="px-3 py-3">{item.headcount}</td><td className="px-3 py-3">{money(item.fixed)}</td><td className="px-3 py-3 text-blue-700">{money(item.variable)}</td><td className="px-3 py-3 text-rose-600">{money(item.deductions)}</td><td className="px-3 py-3 font-semibold text-emerald-700">{money(item.net)}</td><td className="px-3 py-3">{money(item.headcount ? item.net / item.headcount : 0)}</td></tr>)}</tbody></table></div></CardContent></Card>
            <Card><CardContent className="p-5"><div className="mb-4 flex items-center gap-2"><WalletCards className="h-5 w-5 text-emerald-600" /><div><h2 className="font-semibold text-slate-900">发放状态</h2><p className="text-xs text-slate-500">快速发现待发、退回或补发工资。</p></div></div><div className="space-y-3">{report.payment_statuses.map(item => <div key={item.status} className="flex items-center justify-between rounded-lg border p-3"><div><p className="font-medium text-slate-800">{paymentLabels[item.status]}</p><p className="text-xs text-slate-500">{item.count} 条工资明细</p></div><p className="font-semibold text-slate-900">{money(item.amount)}</p></div>)}</div></CardContent></Card>
          </div>

          <Card><CardContent className="p-5"><div className="mb-4"><h2 className="font-semibold text-slate-900">月度明细表</h2><p className="mt-1 text-xs text-slate-500">年度趋势的核对底表。</p></div><div className="app-table-wrap"><table className="w-full min-w-[900px] text-sm"><thead><tr className="border-b bg-slate-50 text-left text-xs text-slate-500"><th className="px-3 py-3">月份</th><th className="px-3 py-3">人数</th><th className="px-3 py-3">应发</th><th className="px-3 py-3">浮动</th><th className="px-3 py-3">扣款</th><th className="px-3 py-3">实发</th><th className="px-3 py-3">已发</th><th className="px-3 py-3">待发</th><th className="px-3 py-3">状态</th></tr></thead><tbody>{reportMonths.map(item => <tr key={item.month} className="border-b border-slate-100"><td className="px-3 py-3 font-medium">{item.month}</td><td className="px-3 py-3">{item.headcount}</td><td className="px-3 py-3">{money(item.gross)}</td><td className="px-3 py-3 text-blue-700">{money(item.variable)}</td><td className="px-3 py-3 text-rose-600">{money(item.deductions)}</td><td className="px-3 py-3 font-semibold">{money(item.net)}</td><td className="px-3 py-3 text-emerald-700">{money(item.paid_amount)}</td><td className="px-3 py-3 text-amber-700">{money(item.pending_amount)}</td><td className="px-3 py-3"><Badge variant="outline">{statusLabels[item.status]}</Badge></td></tr>)}</tbody></table></div></CardContent></Card>
        </>}
      </TabsContent>

      <TabsContent value="ledger" className="mt-5 space-y-5">
        <Card className="border-blue-100 bg-blue-50/40"><CardContent className="flex flex-wrap items-center gap-4 p-4"><div className="flex items-center gap-3"><Users className="h-8 w-8 text-blue-600" /><div><p className="font-semibold text-slate-900">员工年度工资台账</p><p className="text-xs text-slate-500">按员工汇总全年工资、提成、奖金、扣款与发放状态。</p></div></div><div className="ml-auto flex flex-wrap items-center gap-2"><NativeSelect value={String(reportYear)} onChange={value => setReportYear(Number(value))} options={Array.from({ length: 5 }, (_, index) => currentYear - index).map(year => ({ value: String(year), label: `${year} 年` }))} className="w-32 bg-white" /><div className="relative"><Search className="absolute left-3 top-2.5 h-4 w-4 text-slate-400" /><Input value={ledgerSearch} onChange={event => setLedgerSearch(event.target.value)} placeholder="搜索姓名、编号或部门" className="w-64 bg-white pl-9" /></div></div></CardContent></Card>
        {reportLoading ? <div className="app-loading">正在生成年度台账...</div> : !report?.has_data ? <Card><CardContent className="p-10 text-center"><CalendarRange className="mx-auto h-10 w-10 text-slate-300" /><p className="mt-3 font-medium text-slate-700">{reportYear} 年暂无员工工资台账</p><p className="mt-1 text-sm text-slate-500">工资录入后会自动按员工归集，无需重复填写。</p></CardContent></Card> : <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4"><MetricCard label="台账员工" value={`${report.totals.headcount} 人`} tone="blue" /><MetricCard label="员工年度人均" value={money(report.totals.average_per_employee)} /><MetricCard label="年度已发" value={money(report.totals.paid_amount)} tone="emerald" /><MetricCard label="仍需处理" value={money(report.totals.pending_amount)} tone={report.totals.pending_amount > 0 ? 'amber' : 'emerald'} /></div>
          <Card><CardContent className="p-5"><div className="mb-4"><h2 className="font-semibold text-slate-900">员工年度明细</h2><p className="mt-1 text-xs text-slate-500">显示累计金额，不展示完整收款账号；可导出年度台账核对。</p></div><div className="app-table-wrap"><table className="w-full min-w-[1120px] text-sm"><thead><tr className="border-b bg-slate-50 text-left text-xs text-slate-500"><th className="px-3 py-3">员工</th><th className="px-3 py-3">月份</th><th className="px-3 py-3">基本工资</th><th className="px-3 py-3">固定绩效</th><th className="px-3 py-3">提成</th><th className="px-3 py-3">奖金/补贴/报销</th><th className="px-3 py-3">扣款</th><th className="px-3 py-3">实发</th><th className="px-3 py-3">已发/待发</th><th className="px-3 py-3">最近状态</th></tr></thead><tbody>{filteredLedger.map(item => <tr key={`${item.employee_id || 'legacy'}-${item.employee_name}`} className="border-b border-slate-100"><td className="px-3 py-3"><p className="font-medium text-slate-900">{item.employee_name}</p><p className="text-xs text-slate-500">{item.employee_code || '无编号'} · {item.department}</p></td><td className="px-3 py-3">{item.months}</td><td className="px-3 py-3">{money(item.base_salary)}</td><td className="px-3 py-3">{money(item.fixed_performance)}</td><td className="px-3 py-3 text-blue-700">{money(item.commission)}</td><td className="px-3 py-3">{money(item.bonus + item.allowance + item.reimbursement)}</td><td className="px-3 py-3 text-rose-600">{money(item.deductions)}</td><td className="px-3 py-3 font-semibold text-emerald-700">{money(item.net)}</td><td className="px-3 py-3"><p className="text-emerald-700">{money(item.paid_amount)}</p><p className="text-xs text-amber-700">待 {money(item.pending_amount)}</p></td><td className="px-3 py-3"><Badge variant="outline">{paymentLabels[item.latest_payment_status]}</Badge><p className="mt-1 text-xs text-slate-500">{item.latest_month}</p></td></tr>)}{!filteredLedger.length && <tr><td colSpan={10} className="py-10 text-center text-slate-500">没有匹配的员工台账</td></tr>}</tbody></table></div></CardContent></Card>
        </>}
      </TabsContent>
    </Tabs>

    {editing && <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/45 p-4"><Card className="max-h-[92vh] w-full max-w-4xl overflow-auto"><CardContent className="p-5"><div className="mb-4 flex items-start justify-between"><div><h2 className="text-lg font-semibold">{editing.id ? '编辑工资明细' : '新增工资明细'}</h2><p className="text-xs text-slate-500">选择员工后自动带出编号、部门和入职日期</p></div><Button variant="ghost" onClick={() => setEditing(null)}>关闭</Button></div><div className="grid grid-cols-2 gap-3 md:grid-cols-4"><div className="col-span-2"><Label className="text-xs text-slate-500">关联员工 *</Label><NativeSelect className="mt-1" value={String(editing.employee_id || '')} onChange={chooseEmployee} options={[{ value: '', label: '手动填写 / 选择员工' }, ...employees.map(employee => ({ value: String(employee.id), label: `${employee.employee_code ? `${employee.employee_code} · ` : ''}${employee.name} · ${employee.department || '未分部门'}` }))]} /></div>{field('姓名 *', 'employee_name', 'text')}{field('员工编号', 'employee_code', 'text')}{field('部门', 'department', 'text')}{field('入职日期', 'hire_date', 'date')}<div><Label className="text-xs text-slate-500">发放方式</Label><NativeSelect className="mt-1" value={editing.payment_method} onChange={value => setEditing(current => current ? { ...current, payment_method: value } : current)} options={Object.entries(methodLabels).map(([value, label]) => ({ value, label }))} /></div>{field(editing.payment_account_masked ? `发放账号（留空保留 ${editing.payment_account_masked}）` : '发放账号', 'payment_account', 'text')}{field('基本工资', 'base_salary')}{field('固定绩效', 'fixed_performance')}{field('提成', 'commission')}{field('奖金', 'bonus')}{field('补贴', 'allowance')}{field('报销', 'reimbursement')}{field('缺勤扣款', 'absence_deduction')}{field('绩效扣款', 'performance_deduction')}{field('借支扣款', 'salary_advance_deduction')}{field('其他扣款', 'other_deduction')}<div><Label className="text-xs text-slate-500">发放状态</Label><NativeSelect className="mt-1" value={editing.payment_status} onChange={value => setEditing(current => current ? { ...current, payment_status: value as PaymentStatus } : current)} options={Object.entries(paymentLabels).map(([value, label]) => ({ value, label }))} /></div>{field('发放日期', 'payment_date', 'date')}{field('交易流水号 / 参考号', 'payment_reference', 'text')}{field('凭证链接', 'receipt_url', 'url')}</div><div className="mt-3"><Label className="text-xs text-slate-500">备注</Label><Textarea className="mt-1" value={editing.notes || ''} onChange={event => setEditing(current => current ? { ...current, notes: event.target.value } : current)} /></div><div className="mt-5 flex justify-end gap-2"><Button variant="outline" onClick={() => setEditing(null)}>取消</Button><Button onClick={saveItem} disabled={saving}>{saving ? '保存中...' : '保存明细'}</Button></div></CardContent></Card></div>}

    {showMarkPaid && <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/45 p-4">
      <Card ref={markPaidDialogRef} role="dialog" aria-modal="true" aria-labelledby="mark-paid-title" tabIndex={-1} className="max-h-[calc(100dvh-2rem)] w-full max-w-xl overflow-y-auto outline-none">
        <CardContent className="p-5">
          <div className="flex items-start justify-between gap-4">
            <div><h2 id="mark-paid-title" className="text-lg font-semibold text-slate-900">确认整表发放完成</h2><p className="mt-1 text-sm text-slate-500">{month} · 共 {rows.length} 人 · 实发 {money(totals.net)}</p></div>
            <Button variant="ghost" onClick={() => setShowMarkPaid(false)} disabled={transitioning}>关闭</Button>
          </div>

          {blockingRows.length > 0 ? <div className="mt-4 rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800">
            <p className="font-medium">暂时不能完成整表发放</p>
            <p className="mt-1">以下员工存在部分发放、失败、退回或待补发状态，请先逐条核对：</p>
            <div className="mt-3 flex flex-wrap gap-2">{blockingRows.map(row => <Badge key={row.id || row.employee_name} variant="outline" className="border-rose-200 bg-white text-rose-700">{row.employee_name} · {paymentLabels[row.payment_status]}</Badge>)}</div>
          </div> : <>
            <div className="mt-4 rounded-xl border border-blue-100 bg-blue-50 p-4 text-sm text-blue-900">
              {pendingRows.length > 0
                ? `确认后将把 ${pendingRows.length} 人从“待发放”登记为“已发放”，随后锁定整张工资表。`
                : '所有员工均已登记发放，确认后将锁定整张工资表。'}
            </div>
            <div className="mt-4"><Label htmlFor="bulk-payment-date">实际发放日期 *</Label><Input id="bulk-payment-date" type="date" value={bulkPaymentDate} onChange={event => setBulkPaymentDate(event.target.value)} className="mt-1" /></div>
            <p className="mt-3 text-xs leading-5 text-slate-500">该操作只更新独立工资台账并记录审计日志，不会自动写入财务管理或重复计算经营利润。锁定后如需修改，必须由管理员填写原因重新打开。</p>
          </>}

          <div className="mt-5 flex justify-end gap-2">
            <Button variant="outline" onClick={() => setShowMarkPaid(false)} disabled={transitioning}>取消</Button>
            {!blockingRows.length && <Button aria-label="确认发放并锁定" onClick={() => transition('mark_paid', { paymentDate: bulkPaymentDate, confirmAllPending: true })} disabled={transitioning || !bulkPaymentDate}><WalletCards className="mr-1 h-4 w-4" />{transitioning ? '正在登记并锁定...' : '确认发放并锁定'}</Button>}
          </div>
        </CardContent>
      </Card>
    </div>}

    {showAudit && <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/45 p-4"><Card className="max-h-[85vh] w-full max-w-2xl overflow-auto"><CardContent className="p-5"><div className="mb-4 flex items-center justify-between"><div><h2 className="text-lg font-semibold">{month} 操作日志</h2><p className="text-xs text-slate-500">确认、发放、重新打开与明细修改均留痕</p></div><Button variant="ghost" onClick={() => setShowAudit(false)}>关闭</Button></div><div className="space-y-2">{audit.map(log => <div key={log.id} className="rounded-lg border p-3"><div className="flex justify-between"><p className="font-medium">{auditLabels[log.action] || log.action}</p><p className="text-xs text-slate-500">{String(log.created_at).slice(0, 16).replace('T', ' ')}</p></div><p className="mt-1 text-xs text-slate-600">{log.actor_name || '系统'} · {log.actor_role}{log.reason ? ` · 原因：${log.reason}` : ''}</p></div>)}{!audit.length && <div className="app-empty">暂无操作日志</div>}</div></CardContent></Card></div>}
  </div>;
}
