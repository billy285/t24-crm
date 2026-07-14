import { useEffect, useMemo, useState } from 'react';
import { Copy, Download, Lock, Plus, Trash2, Unlock } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { toast } from 'sonner';

type PayrollStatus = 'draft' | 'confirmed' | 'paid';
type PayrollRow = {
  id: string; name: string; alipay: string; entryDate: string; department: string;
  baseSalary: number; fixedPerformance: number; commission: number; allowance: number;
  attendance: number; actualAttendance: number; absenceDeduction: number; fullAttendanceDeduction: number; performanceDeduction: number; otherDeduction: number; notes: string;
};
type PayrollSheet = { month: string; status: PayrollStatus; rows: PayrollRow[]; updatedAt: string };

const storageKey = 't24-payroll-sheets-v1';
const blankRow = (): PayrollRow => ({ id: crypto.randomUUID(), name: '', alipay: '', entryDate: '', department: '', baseSalary: 0, fixedPerformance: 0, commission: 0, allowance: 0, attendance: 0, actualAttendance: 0, absenceDeduction: 0, fullAttendanceDeduction: 0, performanceDeduction: 0, otherDeduction: 0, notes: '' });
const money = (value: number) => Number(value || 0).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const num = (value: string) => Math.max(0, Number(value) || 0);
const statusLabels: Record<PayrollStatus, string> = { draft: '草稿', confirmed: '已确认', paid: '已发放' };

export default function Payroll() {
  const currentMonth = new Date().toISOString().slice(0, 7);
  const [sheets, setSheets] = useState<PayrollSheet[]>([]);
  const [month, setMonth] = useState(currentMonth);
  const [editing, setEditing] = useState<PayrollRow | null>(null);
  const [status, setStatus] = useState<PayrollStatus>('draft');

  useEffect(() => {
    try { setSheets(JSON.parse(localStorage.getItem(storageKey) || '[]')); } catch { setSheets([]); }
  }, []);
  const sheet = sheets.find(item => item.month === month);
  const rows = sheet?.rows || [];
  const locked = status === 'paid';
  const saveSheet = (nextRows: PayrollRow[], nextStatus = status) => {
    const next = sheets.filter(item => item.month !== month).concat({ month, status: nextStatus, rows: nextRows, updatedAt: new Date().toISOString() }).sort((a, b) => b.month.localeCompare(a.month));
    setSheets(next); localStorage.setItem(storageKey, JSON.stringify(next)); setStatus(nextStatus);
  };
  useEffect(() => { setStatus(sheet?.status || 'draft'); setEditing(null); }, [month, sheet?.status]);
  const totals = useMemo(() => rows.reduce((sum, row) => {
    const gross = row.baseSalary + row.fixedPerformance;
    const additions = row.commission + row.allowance;
    const deductions = row.absenceDeduction + row.fullAttendanceDeduction + row.performanceDeduction + row.otherDeduction;
    return { gross: sum.gross + gross, additions: sum.additions + additions, deductions: sum.deductions + deductions, net: sum.net + gross + additions - deductions };
  }, { gross: 0, additions: 0, deductions: 0, net: 0 }), [rows]);

  const copyPrevious = () => {
    const previous = sheets.filter(item => item.month < month).sort((a, b) => b.month.localeCompare(a.month))[0];
    if (!previous) return toast.error('没有可复制的上月工资表');
    saveSheet(previous.rows.map(row => ({ ...row, id: crypto.randomUUID(), commission: 0, allowance: 0, absenceDeduction: 0, fullAttendanceDeduction: 0, performanceDeduction: 0, otherDeduction: 0 })), 'draft');
    toast.success('已复制上一期员工名单和基础工资');
  };
  const exportCsv = () => {
    const header = ['序号', '姓名', '部门', '基本工资', '固定绩效', '工资总额', '提成奖励', '补贴', '应发合计', '应扣合计', '实发工资', '状态'];
    const lines = rows.map((row, index) => { const gross = row.baseSalary + row.fixedPerformance; const add = row.commission + row.allowance; const deduction = row.absenceDeduction + row.fullAttendanceDeduction + row.performanceDeduction + row.otherDeduction; return [index + 1, row.name, row.department, row.baseSalary, row.fixedPerformance, gross, row.commission, row.allowance, add, deduction, gross + add - deduction, statusLabels[status]].join(','); });
    const blob = new Blob([`\ufeff${header.join(',')}\n${lines.join('\n')}`], { type: 'text/csv;charset=utf-8' }); const url = URL.createObjectURL(blob); const link = document.createElement('a'); link.href = url; link.download = `工资表_${month}.csv`; link.click(); URL.revokeObjectURL(url);
  };
  const saveRow = () => { if (!editing?.name.trim()) return toast.error('请填写员工姓名'); saveSheet(rows.some(row => row.id === editing.id) ? rows.map(row => row.id === editing.id ? editing : row) : [...rows, editing]); setEditing(null); toast.success('工资明细已保存'); };
  const field = (label: string, key: keyof PayrollRow, numeric = true) => <div><Label className="text-xs text-slate-500">{label}</Label><Input className="mt-1 h-8" type={numeric ? 'number' : 'text'} value={String(editing?.[key] ?? '')} onChange={e => setEditing(prev => prev ? { ...prev, [key]: numeric ? num(e.target.value) : e.target.value } : prev)} /></div>;

  return <div className="app-page space-y-5">
    <div className="app-page-title flex-col sm:flex-row items-start sm:items-center">
      <div><p className="text-xs font-medium uppercase tracking-[0.16em] text-blue-600">T24 Marketing · Payroll</p><h1 className="mt-1 text-2xl font-bold text-slate-900">工资表明细</h1><p className="mt-1 text-sm text-slate-500">独立填写和计算，不与客户、员工或财务数据联动</p></div>
      <div className="flex flex-wrap gap-2"><Button variant="outline" size="sm" onClick={copyPrevious}><Copy className="mr-1 h-4 w-4" />复制上月</Button><Button variant="outline" size="sm" onClick={exportCsv} disabled={!rows.length}><Download className="mr-1 h-4 w-4" />导出 CSV</Button></div>
    </div>
    <Card><CardContent className="flex flex-wrap items-end gap-4 p-4"><div><Label>工资月份</Label><Input type="month" value={month} onChange={e => setMonth(e.target.value)} className="mt-1 w-44" /></div><div><Label>当前状态</Label><div className="mt-2"><Badge className={status === 'paid' ? 'bg-emerald-100 text-emerald-700' : status === 'confirmed' ? 'bg-blue-100 text-blue-700' : 'bg-slate-100 text-slate-600'}>{statusLabels[status]}</Badge></div></div><div className="ml-auto flex gap-2">{status === 'draft' && <Button variant="outline" onClick={() => { saveSheet(rows, 'confirmed'); toast.success('工资表已确认'); }} disabled={!rows.length}><Lock className="mr-1 h-4 w-4" />确认工资表</Button>}{status === 'confirmed' && <Button onClick={() => { saveSheet(rows, 'paid'); toast.success('工资表已标记为发放'); }}><Lock className="mr-1 h-4 w-4" />标记已发放</Button>}{status === 'paid' && <Button variant="outline" onClick={() => { saveSheet(rows, 'confirmed'); toast.success('已重新打开工资表'); }}><Unlock className="mr-1 h-4 w-4" />重新打开</Button>}</div></CardContent></Card>
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">{[['工资总额', totals.gross], ['应发项目', totals.additions], ['应扣项目', totals.deductions], ['实发工资', totals.net]].map(([label, value], index) => <Card key={String(label)}><CardContent className="p-4"><p className="text-xs text-slate-500">{label}</p><p className={`mt-1 text-xl font-bold ${index === 3 ? 'text-emerald-600' : 'text-slate-800'}`}>{money(Number(value))}</p></CardContent></Card>)}</div>
    <Card><CardContent className="p-4"><div className="mb-4 flex items-center justify-between"><div><h2 className="font-semibold text-slate-800">员工工资明细</h2><p className="mt-1 text-xs text-slate-500">共 {rows.length} 人，发放后默认锁定，避免误改</p></div><Button onClick={() => setEditing(blankRow())} disabled={locked} className="bg-blue-600 hover:bg-blue-700"><Plus className="mr-1 h-4 w-4" />新增员工</Button></div>{rows.length === 0 ? <div className="app-empty">本月暂无工资明细，点击“新增员工”开始填写</div> : <div className="app-table-wrap"><table className="w-full text-sm"><thead><tr className="border-b bg-slate-50 text-left text-slate-500"><th className="px-3 py-3">序号</th><th className="px-3 py-3">姓名</th><th className="px-3 py-3">部门</th><th className="px-3 py-3">工资总额</th><th className="px-3 py-3">应发合计</th><th className="px-3 py-3">应扣合计</th><th className="px-3 py-3">实发工资</th><th className="px-3 py-3">操作</th></tr></thead><tbody>{rows.map((row, index) => { const gross = row.baseSalary + row.fixedPerformance; const add = row.commission + row.allowance; const deduction = row.absenceDeduction + row.fullAttendanceDeduction + row.performanceDeduction + row.otherDeduction; return <tr key={row.id} className="border-b border-slate-100"><td className="px-3 py-3">{index + 1}</td><td className="px-3 py-3 font-medium">{row.name}</td><td className="px-3 py-3">{row.department || '-'}</td><td className="px-3 py-3">{money(gross)}</td><td className="px-3 py-3 text-blue-600">{money(add)}</td><td className="px-3 py-3 text-red-600">{money(deduction)}</td><td className="px-3 py-3 font-semibold text-emerald-600">{money(gross + add - deduction)}</td><td className="px-3 py-3"><div className="flex gap-1"><Button size="sm" variant="outline" onClick={() => setEditing({ ...row })} disabled={locked}>编辑</Button><Button size="sm" variant="ghost" onClick={() => { if (!locked) { saveSheet(rows.filter(item => item.id !== row.id)); toast.success('已删除'); } }} disabled={locked}><Trash2 className="h-4 w-4 text-red-500" /></Button></div></td></tr>; })}</tbody></table></div>}</CardContent></Card>
    {editing && <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4"><Card className="max-h-[90vh] w-full max-w-3xl overflow-auto"><CardContent className="p-5"><div className="mb-4 flex items-center justify-between"><h2 className="text-lg font-semibold">{rows.some(row => row.id === editing.id) ? '编辑工资明细' : '新增工资明细'}</h2><Button variant="ghost" onClick={() => setEditing(null)}>关闭</Button></div><div className="grid grid-cols-2 gap-3 sm:grid-cols-4">{field('姓名 *', 'name', false)}{field('支付宝账号', 'alipay', false)}{field('入职时间', 'entryDate', false)}{field('部门', 'department', false)}{field('基本工资', 'baseSalary')}{field('固定绩效', 'fixedPerformance')}{field('提成奖励', 'commission')}{field('补贴', 'allowance')}{field('应出勤', 'attendance')}{field('实际出勤', 'actualAttendance')}{field('缺勤扣款', 'absenceDeduction')}{field('全勤扣除', 'fullAttendanceDeduction')}{field('绩效扣除', 'performanceDeduction')}{field('其他扣款', 'otherDeduction')}{field('备注', 'notes', false)}</div><div className="mt-5 flex justify-end gap-2"><Button variant="outline" onClick={() => setEditing(null)}>取消</Button><Button onClick={saveRow} className="bg-blue-600 hover:bg-blue-700">保存明细</Button></div></CardContent></Card></div>}
  </div>;
}
