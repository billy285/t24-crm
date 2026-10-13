import { useEffect, useMemo, useRef, useState } from 'react';
import { invokeWithAuth } from '@/lib/tokenStore';
import { useUnsavedChanges } from '@/lib/use-unsaved-changes';
import { customerAccessLabels, customerFinanceLabels, customerModuleLabels, type CustomerAccessLevel, type CustomerEffectivePermissions, type CustomerFinanceAccess, type CustomerModule } from '@/lib/customer-permissions';
import { systemRoleLabels, type SystemRole } from '@/lib/permissions';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { NativeSelect } from '@/components/ui/native-select';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { toast } from 'sonner';
import { Eye, History, ShieldCheck } from 'lucide-react';
import './customer-access.css';

type AccessEmployee = { id?: number; employee_id?: number; name: string; role: string; email?: string; status?: string };
export type CustomerAccessMember = AccessEmployee & {
  employee_id: number; access_level: CustomerAccessLevel; scopes: Record<CustomerModule, CustomerAccessLevel>;
  finance_access: CustomerFinanceAccess; can_delete: boolean; can_export: boolean; can_reassign: boolean;
  effective_permissions?: CustomerEffectivePermissions; explicit: boolean;
};
type AccessHistory = { id: number; actor_name: string; created_at: string; before: unknown; after: unknown };
const api = '/api/v1/entities/customers';
const inactive = (row: AccessEmployee) => !['active','probation'].includes(row.status || 'active');
const modules = Object.keys(customerModuleLabels) as CustomerModule[];
const levels = Object.entries(customerAccessLabels).map(([value, label]) => ({ value, label }));
const financeLevels = Object.entries(customerFinanceLabels).map(([value, label]) => ({ value, label }));
const errorText = (error: any) => typeof error?.data?.detail === 'string' ? error.data.detail : typeof error?.response?.data?.detail === 'string' ? error.response.data.detail : error?.message || '操作未完成，请重试';

export function accessMemberPayload(row: CustomerAccessMember) {
  return { employee_id: row.employee_id, access_level: row.access_level, scopes: row.scopes, finance_access: row.finance_access, can_delete: row.can_delete, can_export: row.can_export, can_reassign: row.can_reassign };
}
function freshMember(employee: AccessEmployee): CustomerAccessMember {
  return { ...employee, employee_id: Number(employee.employee_id || employee.id), access_level: 'none', scopes: { basic: 'none', followups: 'none', delivery: 'none', materials: 'none' }, finance_access: 'none', can_delete: false, can_export: false, can_reassign: false, explicit: false };
}
function changeLevel(row: CustomerAccessMember, level: CustomerAccessLevel): CustomerAccessMember {
  const hasScope = modules.some(key => row.scopes[key] !== 'none');
  return { ...row, explicit: true, access_level: level,
    scopes: Object.fromEntries(modules.map(key => [key, level === 'none' ? 'none' : hasScope ? row.scopes[key] === 'none' ? 'none' : level : level])) as CustomerAccessMember['scopes'],
    ...(level !== 'read_write' ? {can_delete: false, can_reassign: false} : {}),
    ...(level === 'none' ? {finance_access: 'none' as const, can_delete: false, can_export: false, can_reassign: false} : {}),
  };
}
function EffectiveView({ permission }: { permission?: CustomerEffectivePermissions }) {
  if (!permission) return <p className="text-xs text-slate-500">尚未取得实际权限</p>;
  return <div className="customer-access-effective"><div><Badge variant="outline">{customerAccessLabels[permission.access_level] || '不可见'}</Badge><span>财务：{customerFinanceLabels[permission.finance_access] || '不开放'}</span></div><div>{modules.map(key => <span key={key}>{customerModuleLabels[key]}：{permission.modules?.[key]?.write ? '可编辑' : permission.modules?.[key]?.read ? '只读' : '不可见'}</span>)}</div><p>来源：{permission.sources?.map(item => item.label).join('、') || '未授权'}</p><p>独立操作：{[['业务记录删除', permission.can_delete], ['导出', permission.can_export], ['转负责人', permission.can_reassign], ['再授权', permission.can_manage_access], ['密码', permission.reveal_secrets]].filter(([, allowed]) => allowed).map(([label]) => label).join('、') || '均未开放'}</p></div>;
}

export default function CustomerAccessPanel({ customer, customerIds = [], open, onClose, onSaved }: { customer: any; customerIds?: number[]; open: boolean; onClose: () => void; onSaved: () => void | Promise<void> }) {
  const bulk = customerIds.length > 0;
  const [members, setMembers] = useState<CustomerAccessMember[]>([]);
  const [baseline, setBaseline] = useState<CustomerAccessMember[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [search, setSearch] = useState('');
  const [expanded, setExpanded] = useState<number | null>(null);
  const [preview, setPreview] = useState<{name: string; permission: CustomerEffectivePermissions} | null>(null);
  const [previewing, setPreviewing] = useState<number | null>(null);
  const [history, setHistory] = useState<AccessHistory[] | null>(null);
  const [historyLoading, setHistoryLoading] = useState(false);
  const requestId = useRef(0);
  const previewId = useRef(0);
  const targetId = Number(customer?.id || 0);
  const targetKey = bulk ? customerIds.join(',') : String(targetId);
  const changed = useMemo(() => members.filter(row => row.explicit && JSON.stringify(accessMemberPayload(row)) !== JSON.stringify(baseline.find(item => item.employee_id === row.employee_id && item.explicit) ? accessMemberPayload(baseline.find(item => item.employee_id === row.employee_id)!) : null)), [members, baseline]);
  const draft = useUnsavedChanges(open && changed.length > 0);
  useEffect(() => {
    const sequence = ++requestId.current;
    if (!open) return;
    setLoading(true); setError(''); setMembers([]); setBaseline([]); setSearch(''); setPreview(null); setPreviewing(null); setHistory(null); setExpanded(null);
    const request = bulk ? invokeWithAuth({url: '/api/v1/entities/employees/directory', method: 'GET', data: {limit: 1000}}) : invokeWithAuth({url: `${api}/${targetId}/access`, method: 'GET'});
    request.then(response => {
      if (sequence !== requestId.current) return;
      const supplied = response.data?.members || [];
      const employees: AccessEmployee[] = bulk ? response.data?.items || [] : response.data?.eligible_employees || [];
      const byId = new Map<number, CustomerAccessMember>();
      employees.filter(item => !['super_admin', 'sales_partner'].includes(item.role) && ['active', 'probation'].includes(item.status || 'active')).forEach(item => byId.set(Number(item.employee_id || item.id), freshMember(item)));
      supplied.forEach((item: CustomerAccessMember) => {
        const effective = item.effective_permissions;
        const inherited = !item.explicit && effective ? {
          scopes: Object.fromEntries(modules.map(key => [key, effective.modules?.[key]?.write ? 'read_write' : effective.modules?.[key]?.read ? 'read_only' : 'none'])),
          finance_access: effective.finance_access, can_delete: effective.can_delete, can_export: effective.can_export, can_reassign: effective.can_reassign,
        } : {};
        byId.set(item.employee_id, {...freshMember(item), ...item, scopes: {...freshMember(item).scopes, ...item.scopes}, ...inherited} as CustomerAccessMember);
      });
      const rows = [...byId.values()].sort((a, b) => Number(b.access_level !== 'none') - Number(a.access_level !== 'none') || a.name.localeCompare(b.name, 'zh'));
      setMembers(rows); setBaseline(rows);
    }).catch(err => { if (sequence === requestId.current) setError(errorText(err)); }).finally(() => { if (sequence === requestId.current) setLoading(false); });
    return () => { requestId.current++; };
  }, [open, targetKey]);
  const update = (id: number, updater: (row: CustomerAccessMember) => CustomerAccessMember) => { previewId.current++; setPreview(null); setPreviewing(null); setMembers(rows => rows.map(row => row.employee_id === id ? updater(row) : row)); };
  const showPreview = async (row: CustomerAccessMember) => {
    const sequence = requestId.current;
    const previewSequence = ++previewId.current;
    const id = bulk ? customerIds[0] : targetId;
    setPreviewing(row.employee_id); setPreview(null);
    try { const response = await invokeWithAuth({url: `${api}/${id}/access/preview`, method: 'POST', data: accessMemberPayload(row)}); if (sequence === requestId.current && previewSequence === previewId.current) setPreview({name: row.name, permission: response.data.effective_permissions}); }
    catch (err) { toast.error(errorText(err)); }
    finally { if (sequence === requestId.current && previewSequence === previewId.current) setPreviewing(null); }
  };
  const loadHistory = async () => {
    if (history) { setHistory(null); return; }
    const sequence = requestId.current; setHistoryLoading(true);
    try { const response = await invokeWithAuth({url: `${api}/${targetId}/access/history`, method: 'GET'}); if (sequence === requestId.current) setHistory(response.data?.items || []); }
    catch (err) { toast.error(errorText(err)); }
    finally { if (sequence === requestId.current) setHistoryLoading(false); }
  };
  const save = async () => {
    if (saving || loading || error || !changed.length) return;
    setSaving(true);
    try {
      const payload = (bulk ? changed : members.filter(row => row.explicit && row.role !== 'super_admin')).map(accessMemberPayload);
      await invokeWithAuth({url: bulk ? `${api}/access/bulk-update` : `${api}/${targetId}/access`, method: bulk ? 'POST' : 'PUT', data: bulk ? {customer_ids: customerIds, operation: 'upsert', members: payload} : {members: payload}});
      draft.markSaved(); toast.success('客户访问权限已保存'); await onSaved(); onClose();
    } catch (err) { toast.error(errorText(err)); }
    finally { setSaving(false); }
  };
  const visible = members.filter(row => !search || [row.name, row.email, systemRoleLabels[row.role as SystemRole]].some(value => value?.toLowerCase().includes(search.toLowerCase())));
  return <Dialog open={open} onOpenChange={value => { if (!value && !saving && (!changed.length || draft.confirmDiscard())) onClose(); }}><DialogContent className="customer-access-dialog"><DialogHeader><DialogTitle>{bulk ? `批量设置 ${customerIds.length} 位客户的访问权限` : '客户访问权限'}</DialogTitle></DialogHeader><div className="customer-access-body"><div className="customer-access-intro"><strong>{bulk ? '仅更新本次调整的员工' : customer?.business_name}</strong><span><ShieldCheck size={14} />仅老板可调整</span></div><p className="text-xs text-slate-500">资料协作与财务独立授权。设为“不可见”会覆盖已有继承权限。</p><div className="flex gap-2"><Input aria-label="搜索访问权限员工" value={search} onChange={e => setSearch(e.target.value)} placeholder="搜索员工姓名、角色或邮箱" />{!bulk && <Button variant="outline" aria-label="权限变更记录" disabled={historyLoading || loading} onClick={loadHistory}><History size={16} /></Button>}</div>{error && <p role="alert" className="text-sm text-red-700">{error}</p>}{loading ? <p className="py-8 text-center text-slate-500">正在核对实际权限…</p> : <div className="customer-access-list">{visible.map(row => <article key={row.employee_id} className="customer-access-member"><div className="customer-access-member-head"><div className="min-w-0"><strong>{row.name}</strong><small>{systemRoleLabels[row.role as SystemRole] || row.role} · {inactive(row) ? '账号已停用' : row.role === 'super_admin' ? '老板完整权限' : row.explicit ? '老板单独授权' : '角色或负责人规则'}</small></div><NativeSelect aria-label={`${row.name}访问权限`} disabled={row.role === 'super_admin'} value={row.access_level} onChange={value => update(row.employee_id, item => changeLevel(item, value as CustomerAccessLevel))} options={inactive(row) ? levels.filter(item => item.value === row.access_level || item.value === 'none') : levels} /><Button size="sm" variant="ghost" aria-expanded={expanded === row.employee_id} onClick={() => setExpanded(expanded === row.employee_id ? null : row.employee_id)}>范围</Button></div>{expanded === row.employee_id && <div className="customer-access-scope"><div className="customer-access-module-grid">{modules.map(key => <label key={key}><span>{customerModuleLabels[key]}</span><NativeSelect aria-label={`${row.name}${customerModuleLabels[key]}`} disabled={row.role === 'super_admin' || inactive(row) || row.access_level === 'none'} value={row.scopes[key]} onChange={value => update(row.employee_id, item => ({...item, explicit:true, scopes:{...item.scopes, [key]:value}, access_level: value === 'read_write' ? 'read_write' : item.access_level}))} options={levels} /></label>)}</div><label className="customer-access-finance"><span>财务可见范围</span><NativeSelect aria-label={`${row.name}财务权限`} disabled={row.role === 'super_admin' || inactive(row) || row.access_level === 'none'} value={row.finance_access} onChange={value => update(row.employee_id, item => ({...item, explicit: true, finance_access: value as CustomerFinanceAccess}))} options={financeLevels} /></label><p className="text-xs text-slate-500">收款状态不含金额；收款明细不含手续费、成本和利润。财务查看不授予记账操作。</p><details><summary className="cursor-pointer text-xs text-slate-500">独立操作权限</summary><p className="mt-2 text-xs text-slate-500">业务记录删除只适用于获准编辑的记录；整位客户仅老板可删除。</p><div className="mt-2 flex flex-wrap gap-4">{([['can_export','导出'],['can_delete','业务记录删除'],['can_reassign','转负责人']] as const).map(([key,label]) => <label key={key} className="flex items-center gap-2 text-sm"><input type="checkbox" aria-label={`${row.name}${label}`} disabled={row.role === 'super_admin' || inactive(row) || row.access_level === 'none' || (key !== 'can_export' && row.access_level !== 'read_write')} checked={row[key]} onChange={e => update(row.employee_id, item => ({...item, explicit: true, [key]: e.target.checked}))} />{label}</label>)}</div></details><div className="border-t border-dashed border-slate-200 pt-3"><p className="mb-2 text-xs font-medium text-slate-700">当前实际权限</p><EffectiveView permission={row.effective_permissions} /></div><Button variant="outline" size="sm" disabled={previewing !== null || row.role === 'super_admin'} onClick={() => void showPreview(row)}><Eye className="mr-1 h-4 w-4" />{previewing === row.employee_id ? '核对中…' : '预览员工效果'}</Button></div>}</article>)}{!visible.length && !error && <p className="py-8 text-center text-sm text-slate-500">没有匹配的员工</p>}</div>}{preview && <section className="customer-access-preview" aria-label="员工效果预览"><h3>{preview.name} · 保存后的可见范围</h3><EffectiveView permission={preview.permission} /><p className="text-xs text-slate-500">仅模拟权限；没有切换账号或展示该员工的真实数据。{bulk ? '此处以所选第一位客户核对，其他客户按相同明确授权更新。' : ''}</p></section>}{history && <section className="customer-access-history" aria-label="权限变更记录"><h3>权限变更记录</h3>{history.map(item => <details key={item.id}><summary>{item.actor_name || '老板'} · {item.created_at?.slice(0,16).replace('T',' ')}</summary><div className="grid gap-2 sm:grid-cols-2">{[['变更前',item.before],['变更后',item.after]].map(([label,value]) => <div key={String(label)}><strong>{String(label)}</strong><HistoryMembers value={value} /></div>)}</div></details>)}{!history.length && <p className="text-xs text-slate-500">暂无权限调整记录</p>}</section>}{changed.length > 0 && <p className="customer-access-change" role="status">待保存 {changed.length} 位：{changed.map(row => `${row.name} ${customerAccessLabels[row.access_level]} · 财务${customerFinanceLabels[row.finance_access]}`).join('；')}</p>}</div><div className="customer-access-footer"><Button variant="outline" disabled={saving} onClick={() => { if (!changed.length || draft.confirmDiscard()) onClose(); }}>取消</Button><Button disabled={loading || saving || Boolean(error) || !changed.length} onClick={save}>{saving ? '保存中…' : '保存访问权限'}</Button></div></DialogContent></Dialog>;
}

function HistoryMembers({value}: {value: any}) {
  const rows = Array.isArray(value) ? value : value?.members || [];
  return <div className="space-y-1 text-xs text-slate-500">{rows.map((row: any, index: number) => <div key={index}><p>{row.name || `员工 #${row.employee_id}`} · {customerAccessLabels[row.access_level as CustomerAccessLevel] || '继承'} · 财务{customerFinanceLabels[row.finance_access as CustomerFinanceAccess] || '不开放'}</p><p>{modules.map(key => `${customerModuleLabels[key]} ${customerAccessLabels[row.scopes?.[key] as CustomerAccessLevel] || '继承'}`).join(' · ')}</p><p>独立操作：{[['导出', row.can_export],['业务记录删除', row.can_delete],['转负责人', row.can_reassign]].filter(([,allowed]) => allowed).map(([label]) => label).join('、') || '无'}</p></div>)}{!rows.length && <p>无单独授权</p>}</div>;
}
