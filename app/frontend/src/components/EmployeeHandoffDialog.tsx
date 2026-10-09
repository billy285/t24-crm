import { readCompleteCollection } from '@/lib/complete-collection';
import { useEffect, useRef, useState } from 'react';
import { invokeWithAuth } from '@/lib/tokenStore';
import { logOperation } from '@/lib/operation-log-helper';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { NativeSelect } from '@/components/ui/native-select';

type Group = { key: string; label: string; items: any[] };
const errorDetail = (error: any) => error?.data?.detail || error?.response?.data?.detail || error?.message || '读取失败，请重试';
const closed = (row: any) => ['completed', 'cancelled'].includes(row.status);

export async function readAllHandoffRows(entity: string, query?: Record<string, unknown>) {
  const response = await readCompleteCollection<any>(params => invokeWithAuth({ url: `/api/v1/entities/${entity}/all`, method: 'GET', data: { ...params, ...(query ? { query: JSON.stringify(query) } : {}) } }), 200);
  return response.data.items;
}

export default function EmployeeHandoffDialog({ source, employees, actor, onClose, onComplete }: {
  source: any; employees: any[]; actor: string; onClose: () => void; onComplete: () => void;
}) {
  const [groups, setGroups] = useState<Group[]>([]);
  const [targetId, setTargetId] = useState('');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [progress, setProgress] = useState('');
  const requestId = useRef(0);
  const inFlight = useRef(false);
  const read = async () => {
    const seq = ++requestId.current;
    setLoading(true); setError('');
    try {
      const [customers, tasks, serviceTasks, progresses] = await Promise.all(['customers', 'tasks', 'service_tasks', 'service_progresses'].map(entity => readAllHandoffRows(entity)));
      const projectResponse = await readCompleteCollection<any>(params => invokeWithAuth({ url: '/api/v1/management-decisions/engagements', method: 'GET', data: { page: Math.floor(params.skip / params.limit) + 1, page_size: params.limit } }), 100);
      const projects = projectResponse.data.items;
      if (seq !== requestId.current) return;
      setGroups([
        { key: 'customers', label: '客户', items: customers.filter(row => Number(row.sales_employee_id) === source.id || (row.sales_employee_id == null && row.sales_person === source.name)) },
        { key: 'tasks', label: '待办任务', items: tasks.filter(row => !closed(row) && (Number(row.assignee_id) === source.id || (row.assignee_id == null && row.assignee_name === source.name))) },
        { key: 'service_tasks', label: '交付任务', items: serviceTasks.filter(row => !closed(row) && row.assignee_name === source.name) },
        { key: 'service_progresses', label: '服务进度', items: progresses.filter(row => !['ended', 'stopped', 'completed', 'cancelled'].includes(row.service_stage) && ['sales_person', 'ops_person', 'design_person', 'issue_owner'].some(key => row[key] === source.name)) },
        { key: 'projects', label: '在办项目', items: projects.filter(row => !['stopped', 'completed'].includes(row.status) && [row.owner_employee_id, row.sales_employee_id].some(id => Number(id) === source.id)) },
      ]);
    } catch (err) { if (seq === requestId.current) setError(errorDetail(err)); }
    finally { if (seq === requestId.current) setLoading(false); }
  };
  useEffect(() => { void read(); return () => { requestId.current++; }; }, [source.id]);

  const transfer = async () => {
    const target = employees.find(row => String(row.id) === targetId);
    if (!target || inFlight.current || loading || error) return;
    inFlight.current = true; setBusy(true); setError('');
    let completed = 0;
    const total = groups.reduce((sum, group) => sum + group.items.length, 0);
    try {
      for (const group of groups) {
        if (group.key === 'projects') {
          if (group.items.length) {
            const response = await invokeWithAuth({ url: `/api/v1/entities/employees/${source.id}/handoff-projects`, method: 'POST', data: { target_employee_id: target.id } });
            completed += Number(response.data?.transferred_count || 0);
            if (Number(response.data?.remaining_count || 0)) throw new Error(`在办项目仍有 ${response.data.remaining_count} 个未交接，请重新核对清单`);
          }
        } else {
          for (const row of group.items) {
            const payload = group.key === 'customers' ? { sales_person: target.name, sales_employee_id: target.id }
              : group.key === 'tasks' ? { assignee_name: target.name, assignee_id: target.id }
                : group.key === 'service_tasks' ? { assignee_name: target.name }
                  : Object.fromEntries(['sales_person', 'ops_person', 'design_person', 'issue_owner'].filter(key => row[key] === source.name).map(key => [key, target.name]));
            await invokeWithAuth({ url: `/api/v1/entities/${group.key}/${row.id}`, method: 'PUT', data: { ...payload, ...(group.key !== 'service_tasks' ? { updated_at: new Date().toISOString() } : {}) } });
            completed++;
            setProgress(`已交接 ${completed} / ${total} 项 · ${group.label}`);
          }
        }
      }
      setProgress(`本次已完成 ${completed} 项交接。正在核对剩余归属…`);
      logOperation({ actionType: 'other', actionDetail: `业务交接: ${source.name} → ${target.name}，本次完成 ${completed} 项`, operatorName: actor });
      await read(); onComplete();
    } catch (err) {
      const detail = errorDetail(err);
      setProgress(`本次已完成 ${completed} 项，已保存的交接继续有效。`);
      await read();
      setError(`尚有事项未交接：${detail}。重新核对后只会转交仍归原员工的事项。`);
    } finally { inFlight.current = false; setBusy(false); }
  };
  const remaining = groups.reduce((sum, group) => sum + group.items.length, 0);
  return <Dialog open onOpenChange={open => { if (!open && !busy) onClose(); }}><DialogContent className="max-h-[90dvh] max-w-xl overflow-y-auto"><DialogHeader><DialogTitle>客户与业务交接</DialogTitle></DialogHeader>
    <p className="text-sm text-slate-600">{source.name} → 接收员工</p>
    <NativeSelect value={targetId} onChange={setTargetId} disabled={busy} options={[{ value: '', label: '选择接收员工' }, ...employees.filter(row => row.id !== source.id && ['active', 'probation'].includes(row.status)).map(row => ({ value: String(row.id), label: row.name }))]} />
    {loading ? <p role="status" className="py-4 text-sm text-slate-500">正在读取全部业务归属…</p> : <div className="space-y-2">{groups.map(group => <details key={group.key} className="rounded-xl border border-slate-200"><summary className="flex cursor-pointer justify-between p-3 text-sm font-medium"><span>{group.label}</span><span>{group.items.length} 项</span></summary><ul className="max-h-48 space-y-1 overflow-y-auto border-t p-3 text-xs text-slate-500">{group.items.map(row => <li key={row.id}>{row.business_name || row.customer_name || row.title || row.task_name || row.package_name || `#${row.id}`}</li>)}{!group.items.length && <li>已无原员工负责的事项</li>}</ul></details>)}</div>}
    {progress && <p role="status" className="rounded-xl bg-blue-50 p-3 text-sm text-blue-800">{progress}</p>}
    {error && <div role="alert" className="rounded-xl bg-amber-50 p-3 text-sm text-amber-800"><p>{error}</p><Button variant="outline" className="mt-2" disabled={busy} onClick={() => void read()}>重新核对清单</Button></div>}
    <p className="text-xs text-slate-500">仅转移原员工的业务归属，保留历史记录。五类事项全部交接后，再办理离职。</p>
    <div className="flex justify-end gap-2"><Button variant="outline" disabled={busy} onClick={onClose}>关闭</Button><Button disabled={busy || loading || Boolean(error) || !targetId || !remaining} onClick={() => void transfer()}>{busy ? '交接中…' : remaining ? `确认交接 ${remaining} 项` : '已全部交接'}</Button></div>
  </DialogContent></Dialog>;
}
