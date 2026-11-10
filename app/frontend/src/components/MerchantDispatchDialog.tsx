import { useEffect, useRef, useState } from 'react';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { invokeWithAuth } from '@/lib/tokenStore';
import { useRole } from '@/lib/role-context';

type Assignment = { merchant_id: number; business_name: string; sales_employee_id: number; salesperson: string; timezone_group: string; queue_reason: string; completeness: number; quality_status: string };
type Plan = {
  target_date: string; plan_sha256: string; assigned_count: number; unassigned_count: number; policy: string;
  assignments: Assignment[];
  unassigned: { merchant_id: number; business_name: string; reason: string }[];
  employees: { sales_employee_id: number; salesperson: string; quota: number; today_tasks: number; existing_pending_load: number; reserved_existing: number; remaining: number; assigned_count: number; timezones: Record<string, number> }[];
};
const zones: Record<string, string> = { eastern: '东部', central: '中部', mountain: '山区', pacific: '西部', hawaii: '夏威夷', alaska: '阿拉斯加', unknown: '时区待确认' };

export default function MerchantDispatchDialog({ open, onOpenChange, merchantIds, assignees, onAssigned }: {
  open: boolean; onOpenChange: (open: boolean) => void; merchantIds: number[];
  assignees: { id: number; name: string }[]; onAssigned: () => void;
}) {
  const { employee, role } = useRole();
  const authScope = `${employee?.id || ''}:${role}`;
  const owner = useRef<string | null>(authScope);
  owner.current = authScope;
  const [salesIds, setSalesIds] = useState<number[]>([]);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [busy, setBusy] = useState<'preview' | 'confirm' | null>(null);
  const [error, setError] = useState('');
  const flight = useRef<number | null>(null);
  const epoch = useRef(0);
  const selectionKey = [...merchantIds].sort((a, b) => a - b).join(',');
  const assigneeKey = assignees.map(item => item.id).sort((a, b) => a - b).join(',');
  useEffect(() => {
    epoch.current++; setPlan(null); setError('');
    setSalesIds([]); setBusy(null); flight.current = null;
  }, [open, selectionKey, assigneeKey, authScope]);
  useEffect(() => () => { epoch.current++; owner.current = null; flight.current = null; }, []);

  const request = async (action: 'preview' | 'confirm') => {
    if (flight.current || !merchantIds.length || merchantIds.length > 200 || !salesIds.length || (action === 'confirm' && !plan?.assigned_count)) return;
    setBusy(action); setError('');
    const current = ++epoch.current;
    flight.current = current;
    const active = () => current === epoch.current && owner.current === authScope;
    try {
      const result = await invokeWithAuth({ url: `/api/v1/sales-pool-dispatch/${action}`, method: 'POST',
        data: { merchant_ids: merchantIds, sales_ids: salesIds, ...(action === 'confirm' ? { plan_sha256: plan!.plan_sha256 } : {}) } });
      if (!active()) return;
      if (action === 'confirm') {
        onAssigned();
        if (active()) onOpenChange(false);
      } else setPlan(result.data as Plan);
    } catch (failure: any) {
      if (active()) { setError(String(failure?.response?.data?.detail || failure?.data?.detail || failure?.message || '处理结果暂未确认，请刷新商家池后重新预览。')); setPlan(null); }
    } finally {
      if (flight.current === current) flight.current = null;
      if (active()) setBusy(null);
    }
  };

  return <Dialog open={open} onOpenChange={value => { if (!flight.current) onOpenChange(value); }}>
    <DialogContent className="max-h-[90dvh] w-[calc(100vw-2rem)] min-w-0 max-w-[calc(100vw-2rem)] overflow-y-auto sm:max-w-4xl">
      <DialogHeader className="min-w-0 max-w-full break-words"><DialogTitle>按剩余容量均衡派单</DialogTitle><DialogDescription>仅处理本次选中的 {merchantIds.length} 条商家。先选择销售并预览，确认后才分配并创建今日任务；本操作不会拨号。</DialogDescription></DialogHeader>
      <div className="min-w-0 max-w-full space-y-4">
        <fieldset disabled={!!busy} className="min-w-0 max-w-full rounded-xl border p-3"><legend className="px-1 text-sm font-medium">选择接单销售</legend><div className="flex flex-wrap gap-3">{assignees.map(item => <label key={item.id} className="flex min-h-10 items-center gap-2 text-sm"><input type="checkbox" checked={salesIds.includes(item.id)} onChange={event => { setPlan(null); setError(''); setSalesIds(ids => event.target.checked ? [...ids, item.id] : ids.filter(id => id !== item.id)); }} />{item.name}</label>)}{!assignees.length && <p className="text-sm text-slate-500">当前没有可选择的销售。</p>}</div></fieldset>
        <p className="text-xs leading-5 text-slate-500">今日配额优先留给已存在任务及到期待处理线索，其余容量按待处理负载均衡分配。占位店名、待核验地址不计入资料完整度；待核验商家仍可安排首次核验。不固定每位销售负责一个时区。</p>
        {merchantIds.length > 200 && <p role="alert" className="text-sm text-rose-700">每次最多选择200条，请缩小本次选择。</p>}
        {error && <p role="alert" className="rounded-lg bg-rose-50 p-3 text-sm text-rose-700">{error}</p>}
        <Button variant="outline" disabled={!!busy || !salesIds.length || !merchantIds.length || merchantIds.length > 200} onClick={() => void request('preview')}>{busy === 'preview' ? '正在核对剩余容量…' : '生成派单预览'}</Button>
        {plan && <div className="min-w-0 max-w-full space-y-3">
          <p className="rounded-lg bg-blue-50 p-3 text-sm text-blue-900">{plan.target_date}（北京时间）：本次安排 {plan.assigned_count} 条，保留待安排 {plan.unassigned_count} 条。确认时将重新核对权限、核验状态、配额和商家信息；有变化则整批停止。</p>
          <div className="min-w-0 max-w-full overflow-x-auto"><table className="w-full min-w-[640px] text-left text-sm"><thead><tr className="border-b"><th className="p-2">销售</th><th>今日配额</th><th>已有任务 / 保留</th><th>待处理负载</th><th>本次 / 余量</th><th>本次时区</th></tr></thead><tbody>{plan.employees.map(item => <tr key={item.sales_employee_id} className="border-b"><td className="p-2 font-medium">{item.salesperson}</td><td>{item.quota}</td><td>{item.today_tasks} / {item.reserved_existing}</td><td>{item.existing_pending_load}</td><td>{item.assigned_count} / {Math.max(0, item.remaining - item.assigned_count)}</td><td>{Object.entries(item.timezones).map(([zone, count]) => `${zones[zone] || zone} ${count}`).join('、') || '—'}</td></tr>)}</tbody></table></div>
          <details className="min-w-0 max-w-full rounded-lg border p-3"><summary className="cursor-pointer text-sm font-medium">逐条查看 {plan.assigned_count} 条安排</summary><ul className="mt-2 max-h-64 space-y-2 overflow-y-auto break-words text-xs">{plan.assignments.map(item => <li key={item.merchant_id}><strong>{item.business_name}</strong> → {item.salesperson} · {zones[item.timezone_group] || item.timezone_group} · {item.queue_reason} · 资料字段 {item.completeness}/5（真实性仍按核验状态）</li>)}</ul></details>
          {!!plan.unassigned.length && <details open className="min-w-0 max-w-full rounded-lg border border-amber-200 bg-amber-50 p-3"><summary className="cursor-pointer text-sm font-medium">留待安排的 {plan.unassigned_count} 条及原因</summary><ul className="mt-2 max-h-48 space-y-2 overflow-y-auto break-words text-xs">{plan.unassigned.map(item => <li key={item.merchant_id}>{item.business_name}：{item.reason}</li>)}</ul></details>}
        </div>}
        <div className="flex min-w-0 max-w-full flex-col gap-2 sm:flex-row sm:justify-end"><Button className="w-full min-w-0 whitespace-normal sm:w-auto" variant="outline" disabled={!!busy} onClick={() => onOpenChange(false)}>取消</Button><Button className="h-auto min-h-10 w-full min-w-0 max-w-full whitespace-normal break-words py-2 sm:w-auto" disabled={!!busy || !plan?.assigned_count} onClick={() => void request('confirm')}>{busy === 'confirm' ? '正在分配今日任务…' : `确认分配${plan?.assigned_count || 0}条并创建今日任务`}</Button></div>
      </div>
    </DialogContent>
  </Dialog>;
}
