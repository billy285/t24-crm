import { useEffect, useMemo, useState } from 'react';
import { Copy, Download, History, Lock, Plus, Trash2, Unlock, WalletCards } from 'lucide-react';
import { toast } from 'sonner';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { NativeSelect } from '@/components/ui/native-select';
import { Textarea } from '@/components/ui/textarea';
import { invokeWithAuth } from '@/lib/tokenStore';
import { useRole } from '@/lib/role-context';

type PayrollStatus = 'draft' | 'confirmed' | 'paid';
type PaymentStatus = 'pending' | 'partial' | 'paid' | 'failed' | 'returned' | 'supplemental';
type Employee = { id: number; name: string; employee_code?: string; department?: string; hire_date?: string };
type PayrollItem = {
  id?: number; employee_id?: number; employee_name: string; employee_code?: string; department?: string; hire_date?: string;
  payment_method: string; payment_account?: string; payment_account_masked?: string;
  base_salary: number; fixed_performance: number; commission: number; bonus: number; allowance: number; reimbursement: number;
  absence_deduction: number; performance_deduction: number; salary_advance_deduction: number; other_deduction: number;
  payment_status: PaymentStatus; payment_date?: string; payment_reference?: string; receipt_url?: string; notes?: string;
  gross_amount?: number; deduction_amount?: number; net_amount?: number;
};
type PayrollData = { sheet: { id: number; month: string; status: PayrollStatus; currency: string; reopen_reason?: string }; items: PayrollItem[]; totals: { gross: number; deductions: number; net: number } };
type AuditLog = { id: number; action: string; actor_name?: string; actor_role: string; reason?: string; created_at: string };

const blankItem = (): PayrollItem => ({ employee_name: '', payment_method: 'alipay', base_salary: 0, fixed_performance: 0, commission: 0, bonus: 0, allowance: 0, reimbursement: 0, absence_deduction: 0, performance_deduction: 0, salary_advance_deduction: 0, other_deduction: 0, payment_status: 'pending' });
const money = (value = 0) => `¥${Number(value || 0).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const statusLabels: Record<PayrollStatus, string> = { draft: '草稿录入', confirmed: '管理员已确认', paid: '已发放锁定' };
const paymentLabels: Record<PaymentStatus, string> = { pending: '待发放', partial: '部分发放', paid: '已发放', failed: '发放失败', returned: '已退回', supplemental: '待补发' };
const methodLabels: Record<string, string> = { alipay: '支付宝', bank_card: '国内银行卡', wechat: '微信', cash: '现金', other: '其他' };
const auditLabels: Record<string, string> = { legacy_import: '旧数据迁移', item_created: '新增明细', item_updated: '修改明细', item_deleted: '删除明细', confirm: '管理员确认', mark_paid: '整表发放完成', reopen: '重新打开' };

export default function Payroll() {
  const { role, isAdmin } = useRole();
  const currentMonth = new Date().toISOString().slice(0, 7);
  const [month, setMonth] = useState(currentMonth);
  const [data, setData] = useState<PayrollData | null>(null);
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [editing, setEditing] = useState<PayrollItem | null>(null);
  const [audit, setAudit] = useState<AuditLog[]>([]);
  const [showAudit, setShowAudit] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const canAdmin = isAdmin || role === 'super_admin';

  const load = async () => {
    setLoading(true);
    try {
      const [sheetRes, employeeRes] = await Promise.all([
        invokeWithAuth({ url: `/api/v1/payroll?month=${month}`, method: 'GET' }),
        invokeWithAuth({ url: '/api/v1/payroll/employees', method: 'GET' }),
      ]);
      setData(sheetRes.data); setEmployees(employeeRes.data || []);
    } catch (error: any) { toast.error(error?.data?.detail || error?.message || '工资表读取失败'); }
    finally { setLoading(false); }
  };
  useEffect(() => { void load(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [month]);

  const rows = data?.items || [];
  const locked = data?.sheet.status === 'paid';
  const totals = data?.totals || { gross: 0, deductions: 0, net: 0 };
  const additions = useMemo(() => rows.reduce((sum, row) => sum + row.commission + row.bonus + row.allowance + row.reimbursement, 0), [rows]);

  const saveItem = async () => {
    if (!editing?.employee_name.trim()) return toast.error('请选择员工或填写员工姓名');
    setSaving(true);
    try {
      const id = editing.id;
      await invokeWithAuth({ url: id ? `/api/v1/payroll/${month}/items/${id}` : `/api/v1/payroll/${month}/items`, method: id ? 'PUT' : 'POST', data: editing });
      toast.success('工资明细已保存并记录操作日志'); setEditing(null); await load();
    } catch (error: any) { toast.error(error?.data?.detail || error?.message || '保存失败'); }
    finally { setSaving(false); }
  };
  const removeItem = async (item: PayrollItem) => {
    if (!item.id || !window.confirm(`确认删除 ${item.employee_name} 的本月工资明细？`)) return;
    try { await invokeWithAuth({ url: `/api/v1/payroll/${month}/items/${item.id}`, method: 'DELETE' }); toast.success('已删除'); await load(); }
    catch (error: any) { toast.error(error?.data?.detail || error?.message || '删除失败'); }
  };
  const transition = async (action: 'confirm' | 'mark_paid' | 'reopen') => {
    let reason: string | null = null;
    if (action === 'reopen') { reason = window.prompt('请输入重新打开并修改已发放工资表的原因：'); if (!reason?.trim()) return; }
    try { await invokeWithAuth({ url: `/api/v1/payroll/${month}/transition`, method: 'POST', data: { action, reason } }); toast.success('工资表状态已更新'); await load(); }
    catch (error: any) { toast.error(error?.data?.detail || error?.message || '状态更新失败'); }
  };
  const copyPrevious = async () => {
    const date = new Date(`${month}-01T00:00:00`); date.setMonth(date.getMonth() - 1);
    const previousMonth = date.toISOString().slice(0, 7);
    try {
      const response = await invokeWithAuth({ url: `/api/v1/payroll?month=${previousMonth}`, method: 'GET' });
      const previous: PayrollItem[] = response.data?.items || [];
      if (!previous.length) return toast.error('上月没有可复制的工资明细');
      for (const row of previous) {
        const payload = { ...row, id: undefined, payment_account: undefined, commission: 0, bonus: 0, allowance: 0, reimbursement: 0, absence_deduction: 0, performance_deduction: 0, salary_advance_deduction: 0, other_deduction: 0, payment_status: 'pending', payment_date: undefined, payment_reference: undefined, receipt_url: undefined };
        await invokeWithAuth({ url: `/api/v1/payroll/${month}/items`, method: 'POST', data: payload });
      }
      toast.success('已复制上月人员和固定工资，动态项目已清零'); await load();
    } catch (error: any) { toast.error(error?.data?.detail || error?.message || '复制失败，请检查本月是否已有相同员工'); }
  };
  const showAuditLog = async () => {
    try { const response = await invokeWithAuth({ url: `/api/v1/payroll/${month}/audit`, method: 'GET' }); setAudit(response.data || []); setShowAudit(true); }
    catch { toast.error('操作日志读取失败'); }
  };
  const exportCsv = () => {
    const header = ['员工编号', '姓名', '部门', '基本工资', '固定绩效', '提成', '奖金', '补贴', '报销', '扣款', '实发', '发放方式', '发放状态', '发放日期', '流水号'];
    const lines = rows.map(row => [row.employee_code || '', row.employee_name, row.department || '', row.base_salary, row.fixed_performance, row.commission, row.bonus, row.allowance, row.reimbursement, row.deduction_amount, row.net_amount, methodLabels[row.payment_method], paymentLabels[row.payment_status], row.payment_date || '', row.payment_reference || ''].map(v => `"${String(v ?? '').replaceAll('"', '""')}"`).join(','));
    const blob = new Blob([`\ufeff${header.join(',')}\n${lines.join('\n')}`], { type: 'text/csv;charset=utf-8' }); const url = URL.createObjectURL(blob); const link = document.createElement('a'); link.href = url; link.download = `工资表_${month}.csv`; link.click(); URL.revokeObjectURL(url);
  };
  const chooseEmployee = (id: string) => {
    const employee = employees.find(item => item.id === Number(id));
    setEditing(current => current ? { ...current, employee_id: employee?.id, employee_name: employee?.name || '', employee_code: employee?.employee_code, department: employee?.department, hire_date: employee?.hire_date } : current);
  };
  const field = (label: string, key: keyof PayrollItem, type = 'number') => <div><Label className="text-xs text-slate-500">{label}</Label><Input className="mt-1" type={type} value={String(editing?.[key] ?? '')} onChange={e => setEditing(current => current ? { ...current, [key]: type === 'number' ? Math.max(0, Number(e.target.value) || 0) : e.target.value } : current)} /></div>;

  if (loading && !data) return <div className="app-page"><div className="app-loading">正在读取工资表...</div></div>;
  return <div className="app-page space-y-5">
    <div className="app-page-title flex-col items-start sm:flex-row sm:items-center">
      <div><p className="text-xs font-medium uppercase tracking-[0.16em] text-blue-600">T24 Marketing · Payroll</p><h1 className="mt-1 text-2xl font-bold text-slate-900">工资表明细</h1><p className="mt-1 text-sm text-slate-500">国内员工 · CNY · 独立核算，不自动进入财务管理或经营利润</p></div>
      <div className="flex flex-wrap gap-2"><Button variant="outline" size="sm" onClick={showAuditLog}><History className="mr-1 h-4 w-4" />操作日志</Button><Button variant="outline" size="sm" onClick={exportCsv} disabled={!rows.length}><Download className="mr-1 h-4 w-4" />导出 CSV</Button></div>
    </div>
    <Card className="border-blue-100 bg-blue-50/40"><CardContent className="flex flex-wrap items-end gap-4 p-4"><div><Label>工资月份</Label><Input type="month" value={month} onChange={e => setMonth(e.target.value)} className="mt-1 w-44 bg-white" /></div><div><Label>流程状态</Label><div className="mt-2"><Badge className={data?.sheet.status === 'paid' ? 'bg-emerald-100 text-emerald-700' : data?.sheet.status === 'confirmed' ? 'bg-blue-100 text-blue-700' : 'bg-slate-100 text-slate-700'}>{data ? statusLabels[data.sheet.status] : '-'}</Badge></div></div><p className="text-xs text-slate-500">录入：财务/管理员 · 确认：管理员 · 发放：财务/管理员</p><div className="ml-auto flex flex-wrap gap-2"><Button variant="outline" onClick={copyPrevious} disabled={locked || rows.length > 0}><Copy className="mr-1 h-4 w-4" />复制上月</Button>{data?.sheet.status === 'draft' && canAdmin && <Button onClick={() => transition('confirm')} disabled={!rows.length}><Lock className="mr-1 h-4 w-4" />确认工资表</Button>}{data?.sheet.status === 'confirmed' && <Button onClick={() => transition('mark_paid')}><WalletCards className="mr-1 h-4 w-4" />整表发放完成</Button>}{data?.sheet.status === 'paid' && canAdmin && <Button variant="outline" onClick={() => transition('reopen')}><Unlock className="mr-1 h-4 w-4" />带原因重新打开</Button>}</div></CardContent></Card>
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">{[['应发工资', totals.gross], ['动态应发', additions], ['应扣项目', totals.deductions], ['实发工资', totals.net]].map(([label, value], index) => <Card key={String(label)}><CardContent className="p-4"><p className="text-xs text-slate-500">{label}</p><p className={`mt-1 text-xl font-bold ${index === 3 ? 'text-emerald-600' : index === 2 ? 'text-rose-600' : 'text-slate-800'}`}>{money(Number(value))}</p></CardContent></Card>)}</div>
    <Card><CardContent className="p-4"><div className="mb-4 flex items-center justify-between"><div><h2 className="font-semibold text-slate-800">员工工资明细</h2><p className="mt-1 text-xs text-slate-500">账号仅显示末四位；发放完成后整表锁定，修改会留下审计记录</p></div><Button onClick={() => setEditing(blankItem())} disabled={locked}><Plus className="mr-1 h-4 w-4" />新增员工</Button></div>{!rows.length ? <div className="app-empty">本月暂无工资明细</div> : <div className="app-table-wrap"><table className="w-full min-w-[1040px] text-sm"><thead><tr className="border-b bg-slate-50 text-left text-xs text-slate-500"><th className="px-3 py-3">员工</th><th className="px-3 py-3">应发</th><th className="px-3 py-3">应扣</th><th className="px-3 py-3">实发</th><th className="px-3 py-3">发放账户</th><th className="px-3 py-3">发放状态</th><th className="px-3 py-3">凭证</th><th className="px-3 py-3">操作</th></tr></thead><tbody>{rows.map(row => <tr key={row.id} className="border-b border-slate-100"><td className="px-3 py-3"><p className="font-medium text-slate-900">{row.employee_name}</p><p className="text-xs text-slate-500">{row.employee_code || '无编号'} · {row.department || '未设置部门'}</p></td><td className="px-3 py-3">{money(row.gross_amount)}</td><td className="px-3 py-3 text-rose-600">{money(row.deduction_amount)}</td><td className="px-3 py-3 font-semibold text-emerald-600">{money(row.net_amount)}</td><td className="px-3 py-3"><p>{methodLabels[row.payment_method] || row.payment_method}</p><p className="text-xs text-slate-500">{row.payment_account_masked || '未填写'}</p></td><td className="px-3 py-3"><Badge variant="outline">{paymentLabels[row.payment_status]}</Badge><p className="mt-1 text-xs text-slate-500">{row.payment_date || '-'}</p></td><td className="px-3 py-3 text-xs">{row.payment_reference || '-'}</td><td className="px-3 py-3"><div className="flex gap-1"><Button size="sm" variant="outline" onClick={() => setEditing({ ...row, payment_account: '' })} disabled={locked}>编辑</Button><Button size="sm" variant="ghost" onClick={() => removeItem(row)} disabled={data?.sheet.status !== 'draft'}><Trash2 className="h-4 w-4 text-rose-500" /></Button></div></td></tr>)}</tbody></table></div>}</CardContent></Card>
    {editing && <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/45 p-4"><Card className="max-h-[92vh] w-full max-w-4xl overflow-auto"><CardContent className="p-5"><div className="mb-4 flex items-start justify-between"><div><h2 className="text-lg font-semibold">{editing.id ? '编辑工资明细' : '新增工资明细'}</h2><p className="text-xs text-slate-500">选择员工后自动带出编号、部门和入职日期</p></div><Button variant="ghost" onClick={() => setEditing(null)}>关闭</Button></div><div className="grid grid-cols-2 gap-3 md:grid-cols-4"><div className="col-span-2"><Label className="text-xs text-slate-500">关联员工 *</Label><NativeSelect className="mt-1" value={String(editing.employee_id || '')} onChange={chooseEmployee} options={[{ value: '', label: '手动填写 / 选择员工' }, ...employees.map(employee => ({ value: String(employee.id), label: `${employee.employee_code ? `${employee.employee_code} · ` : ''}${employee.name} · ${employee.department || '未分部门'}` }))]} /></div>{field('姓名 *', 'employee_name', 'text')}{field('员工编号', 'employee_code', 'text')}{field('部门', 'department', 'text')}{field('入职日期', 'hire_date', 'date')}<div><Label className="text-xs text-slate-500">发放方式</Label><NativeSelect className="mt-1" value={editing.payment_method} onChange={value => setEditing(current => current ? { ...current, payment_method: value } : current)} options={Object.entries(methodLabels).map(([value, label]) => ({ value, label }))} /></div>{field(editing.payment_account_masked ? `发放账号（留空保留 ${editing.payment_account_masked}）` : '发放账号', 'payment_account', 'text')}{field('基本工资', 'base_salary')}{field('固定绩效', 'fixed_performance')}{field('提成', 'commission')}{field('奖金', 'bonus')}{field('补贴', 'allowance')}{field('报销', 'reimbursement')}{field('缺勤扣款', 'absence_deduction')}{field('绩效扣款', 'performance_deduction')}{field('借支扣款', 'salary_advance_deduction')}{field('其他扣款', 'other_deduction')}<div><Label className="text-xs text-slate-500">发放状态</Label><NativeSelect className="mt-1" value={editing.payment_status} onChange={value => setEditing(current => current ? { ...current, payment_status: value as PaymentStatus } : current)} options={Object.entries(paymentLabels).map(([value, label]) => ({ value, label }))} /></div>{field('发放日期', 'payment_date', 'date')}{field('交易流水号 / 参考号', 'payment_reference', 'text')}{field('凭证链接', 'receipt_url', 'url')}</div><div className="mt-3"><Label className="text-xs text-slate-500">备注</Label><Textarea className="mt-1" value={editing.notes || ''} onChange={e => setEditing(current => current ? { ...current, notes: e.target.value } : current)} /></div><div className="mt-5 flex justify-end gap-2"><Button variant="outline" onClick={() => setEditing(null)}>取消</Button><Button onClick={saveItem} disabled={saving}>{saving ? '保存中...' : '保存明细'}</Button></div></CardContent></Card></div>}
    {showAudit && <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/45 p-4"><Card className="max-h-[85vh] w-full max-w-2xl overflow-auto"><CardContent className="p-5"><div className="mb-4 flex items-center justify-between"><div><h2 className="text-lg font-semibold">{month} 操作日志</h2><p className="text-xs text-slate-500">确认、发放、重新打开与明细修改均留痕</p></div><Button variant="ghost" onClick={() => setShowAudit(false)}>关闭</Button></div><div className="space-y-2">{audit.map(log => <div key={log.id} className="rounded-lg border p-3"><div className="flex justify-between"><p className="font-medium">{auditLabels[log.action] || log.action}</p><p className="text-xs text-slate-500">{String(log.created_at).slice(0, 16).replace('T', ' ')}</p></div><p className="mt-1 text-xs text-slate-600">{log.actor_name || '系统'} · {log.actor_role}{log.reason ? ` · 原因：${log.reason}` : ''}</p></div>)}{!audit.length && <div className="app-empty">暂无操作日志</div>}</div></CardContent></Card></div>}
  </div>;
}
