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
import { Eye, History, ShieldCheck, UserPlus } from 'lucide-react';
import './customer-access.css';

type AccessEmployee = { id?: number; employee_id?: number; name: string; role: string; email?: string; status?: string };
export type CustomerAccessMember = AccessEmployee & {
  employee_id: number; access_level: CustomerAccessLevel; scopes: Record<CustomerModule, CustomerAccessLevel>;
  finance_access: CustomerFinanceAccess; can_delete: boolean; can_export: boolean; can_reassign: boolean;
  effective_permissions?: CustomerEffectivePermissions; explicit: boolean; invitation_status?: string; invited_by_name?: string;
  customer_ids?: number[];
  batch_requested?: boolean;
};
type AccessHistory = { id: number; actor_name: string; created_at: string; before: unknown; after: unknown };
type Preview = { customerId: number; name: string; permission: CustomerEffectivePermissions };
const api = '/api/v1/entities/customers';
const modules = Object.keys(customerModuleLabels) as CustomerModule[];
const inactive = (row: AccessEmployee) => !['active','probation'].includes(row.status || 'active');
const errorText = (error: any) => typeof error?.data?.detail === 'string' ? error.data.detail : typeof error?.response?.data?.detail === 'string' ? error.response.data.detail : error?.message || '操作未完成，请重试';
const emptyScopes = () => Object.fromEntries(modules.map(key => [key,'none'])) as Record<CustomerModule, CustomerAccessLevel>;
export function invitationScopes(template = 'basic_deals'): Record<CustomerModule, CustomerAccessLevel> {
  const scopes = emptyScopes();
  const selected = template === 'delivery' ? ['basic','delivery','materials'] : template === 'sales' ? ['basic','contacts','followups','opportunities','deals'] : ['basic','deals'];
  selected.forEach(key => { scopes[key as CustomerModule] = 'read_only'; });
  return scopes;
}
/** Ordinary collaboration never sends an existing or legacy financial grant. */
export function accessMemberPayload(row: CustomerAccessMember) {
  return { employee_id: row.employee_id, access_level: row.access_level, scopes: row.scopes, finance_access: 'none', can_delete: row.can_delete, can_export: row.can_export, can_reassign: row.can_reassign };
}
function freshMember(employee: AccessEmployee, template = 'basic_deals'): CustomerAccessMember {
  return { ...employee, employee_id: Number(employee.employee_id || employee.id), access_level:'read_only', scopes:invitationScopes(template), finance_access:'none', can_delete:false, can_export:false, can_reassign:false, explicit:true, invitation_status:'active' };
}
function normalizedMember(row: CustomerAccessMember): CustomerAccessMember {
  return {...freshMember(row), ...row, scopes:{...emptyScopes(), ...row.scopes}};
}
function scopeSummary(row: CustomerAccessMember) {
  return row.access_level === 'none' ? '将撤销全部协作及财务查看' : modules.filter(key => row.scopes[key] !== 'none').map(key => `${customerModuleLabels[key]}${row.scopes[key] === 'read_write' ? '·编辑' : '·只读'}`).join('、') || '未选择栏目';
}
function EffectiveView({ permission }: { permission?: CustomerEffectivePermissions }) {
  if (!permission) return <p className="text-xs text-slate-500">尚未取得权限预览</p>;
  const visible = modules.filter(key => permission.modules?.[key]?.read);
  return <div className="customer-access-effective"><div><Badge variant="outline">{customerAccessLabels[permission.access_level] || '不可见'}</Badge><span>财务：{customerFinanceLabels[permission.finance_access] || '不开放'}</span></div><div>{visible.length ? visible.map(key => <span key={key}>{customerModuleLabels[key]} · {permission.modules[key].write ? '可编辑' : '只读'}</span>) : <span>无可见栏目</span>}</div><p>{permission.sources?.map(item => item.label).join('、')}</p><p>独立操作：{[['业务记录删除',permission.can_delete],['导出',permission.can_export],['转负责人',permission.can_reassign]].filter(([,allowed]) => allowed).map(([label]) => label).join('、') || '均未开放'}</p></div>;
}

export default function CustomerAccessPanel({customer,customerIds=[],open,onClose,onSaved}: {customer:any;customerIds?:number[];open:boolean;onClose:()=>void;onSaved:()=>void|Promise<void>}) {
  const bulk = customerIds.length > 0;
  const ids = bulk ? customerIds : [Number(customer?.id || 0)];
  const targetKey = ids.join(',');
  const [members,setMembers] = useState<CustomerAccessMember[]>([]);
  const [baseline,setBaseline] = useState<CustomerAccessMember[]>([]);
  const [candidates,setCandidates] = useState<AccessEmployee[]>([]);
  const [legacy,setLegacy] = useState<CustomerAccessMember[]>([]);
  const [owner,setOwner] = useState<AccessEmployee|null>(null);
  const [loading,setLoading] = useState(false);
  const [saving,setSaving] = useState(false);
  const [error,setError] = useState('');
  const [picker,setPicker] = useState(false);
  const [search,setSearch] = useState('');
  const [chosen,setChosen] = useState<number[]>([]);
  const [legacyChosen,setLegacyChosen] = useState<number[]>([]);
  const [template,setTemplate] = useState('basic_deals');
  const [expanded,setExpanded] = useState<number|null>(null);
  const [preview,setPreview] = useState<Preview[]|null>(null);
  const [previewing,setPreviewing] = useState(false);
  const [previewSignature,setPreviewSignature] = useState('');
  const [history,setHistory] = useState<AccessHistory[]|null>(null);
  const requestId = useRef(0), previewId = useRef(0);
  const bodyRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => { if (preview && bodyRef.current) bodyRef.current.scrollTop = 0; }, [preview]);
  const changed = useMemo(() => members.filter(row => row.batch_requested || JSON.stringify(accessMemberPayload(row)) !== JSON.stringify(baseline.find(item => item.employee_id === row.employee_id) ? accessMemberPayload(baseline.find(item => item.employee_id === row.employee_id)!) : null)), [members,baseline]);
  const signature = JSON.stringify(changed.map(accessMemberPayload));
  const draft = useUnsavedChanges(open && changed.length > 0);
  const invalidatePreview = () => { previewId.current++;setPreview(null);setPreviewSignature('');setPreviewing(false); };
  useEffect(() => {
    const seq=++requestId.current;if(!open)return;
    setLoading(true);setError('');setMembers([]);setBaseline([]);setLegacy([]);setCandidates([]);setOwner(null);setPicker(false);setChosen([]);setLegacyChosen([]);setExpanded(null);setPreview(null);setPreviewSignature('');setHistory(null);
    Promise.all(ids.map(id => invokeWithAuth({url:`${api}/${id}/access`,method:'GET'}))).then(responses => {
      if(seq!==requestId.current)return;
      const activeMap=new Map<number,CustomerAccessMember>(), legacyMap=new Map<number,CustomerAccessMember>(), employeeMap=new Map<number,AccessEmployee>();
      responses.forEach((response,index) => {
        (response.data?.eligible_employees || []).filter((item:AccessEmployee) => !['super_admin','sales_partner'].includes(item.role) && !inactive(item)).forEach((item:AccessEmployee) => employeeMap.set(Number(item.employee_id||item.id),item));
        (response.data?.members || []).filter((item:CustomerAccessMember) => item.role!=='super_admin').forEach((item:CustomerAccessMember) => { const previous=activeMap.get(item.employee_id);activeMap.set(item.employee_id,{...normalizedMember(item),customer_ids:[...(previous?.customer_ids||[]),ids[index]]}); });
        (response.data?.pending_legacy_members || []).forEach((item:CustomerAccessMember) => { const previous=legacyMap.get(item.employee_id);legacyMap.set(item.employee_id,{...normalizedMember(item),customer_ids:[...(previous?.customer_ids||[]),ids[index]]}); });
      });
      const rows=[...activeMap.values()];setMembers(rows);setBaseline(rows);setLegacy([...legacyMap.values()]);setCandidates([...employeeMap.values()]);setOwner(responses[0]?.data?.owner||null);
    }).catch(err=>{if(seq===requestId.current)setError(errorText(err));}).finally(()=>{if(seq===requestId.current)setLoading(false);});
    return()=>{requestId.current++;previewId.current++;};
  },[open,targetKey]);
  const update = (id:number,fn:(row:CustomerAccessMember)=>CustomerAccessMember) => {invalidatePreview();setMembers(rows=>rows.map(row=>row.employee_id===id?fn(row):row));};
  const stageInvitations = (people:AccessEmployee[], selectedTemplate:string) => {
    invalidatePreview();const rows=people.map(person=>({...freshMember(person,selectedTemplate),batch_requested:bulk}));
    setMembers(previous=>[...previous.filter(row=>!rows.some(next=>next.employee_id===row.employee_id)),...rows]);
    setPicker(false);setChosen([]);setSearch('');setLegacyChosen([]);if(rows.length===1)setExpanded(rows[0].employee_id);
  };
  const revoke = (id:number) => update(id,row=>({...row,access_level:'none',scopes:emptyScopes(),finance_access:'none',can_delete:false,can_export:false,can_reassign:false}));
  const updateScope = (id:number,key:CustomerModule,value:CustomerAccessLevel) => update(id,row=>{
    const scopes={...row.scopes,[key]:value};const editing=Object.values(scopes).includes('read_write');const visible=Object.values(scopes).some(item=>item!=='none');
    return {...row,scopes,access_level:editing?'read_write':visible?'read_only':'none',...(!editing?{can_delete:false,can_reassign:false}:{}),...(!visible?{can_export:false,finance_access:'none' as const}:{})};
  });
  const previewChanges = async () => {
    if(!changed.length||previewing)return;const seq=requestId.current,version=++previewId.current;setPreviewing(true);setPreview(null);
    try { const results:Preview[]=[];for(const id of ids)for(const row of changed){const response=await invokeWithAuth({url:`${api}/${id}/access/preview`,method:'POST',data:accessMemberPayload(row)});results.push({customerId:id,name:row.name,permission:response.data.effective_permissions});if(seq!==requestId.current||version!==previewId.current)return;}setPreview(results);setPreviewSignature(signature); }
    catch(err){toast.error(errorText(err));}finally{if(seq===requestId.current&&version===previewId.current)setPreviewing(false);}
  };
  const save = async () => {
    if(saving||!changed.length||previewSignature!==signature)return;setSaving(true);
    try {
      if(bulk){const invited=changed.filter(row=>row.access_level!=='none'),removed=changed.filter(row=>row.access_level==='none');
        if(invited.length)await invokeWithAuth({url:`${api}/access/bulk-update`,method:'POST',data:{customer_ids:ids,operation:'upsert',members:invited.map(accessMemberPayload)}});
        if(removed.length)await invokeWithAuth({url:`${api}/access/bulk-update`,method:'POST',data:{customer_ids:ids,operation:'remove',members:removed.map(accessMemberPayload)}});
      }else await invokeWithAuth({url:`${api}/${ids[0]}/access`,method:'PUT',data:{members:members.filter(row=>row.access_level!=='none').map(accessMemberPayload)}});
      draft.markSaved();toast.success('协作成员已保存');await onSaved();onClose();
    }catch(err){toast.error(errorText(err));invalidatePreview();}finally{setSaving(false);}
  };
  const loadHistory=async()=>{if(history){setHistory(null);return;}const seq=requestId.current;try{const response=await invokeWithAuth({url:`${api}/${ids[0]}/access/history`,method:'GET'});if(seq===requestId.current)setHistory(response.data?.items||[]);}catch(err){toast.error(errorText(err));}};
  const available=candidates.filter(item=>bulk||!members.some(row=>row.employee_id===Number(item.employee_id||item.id)&&row.access_level!=='none')).filter(item=>!search||[item.name,item.email,systemRoleLabels[item.role as SystemRole]].some(value=>value?.toLowerCase().includes(search.toLowerCase())));
  const pending=legacy.filter(row=>!members.some(item=>item.employee_id===row.employee_id && item.invitation_status==='active' && (item.batch_requested || !baseline.some(previous=>previous.employee_id===item.employee_id))));
  const close=()=>{if(!saving&&(!changed.length||draft.confirmDiscard()))onClose();};
  return <Dialog open={open} onOpenChange={value=>{if(!value)close();}}><DialogContent className="customer-access-dialog customer-access-collaboration-dialog"><DialogHeader className="customer-access-header"><DialogTitle>{bulk?`批量协作 · ${ids.length} 位客户`:'协作成员'}</DialogTitle></DialogHeader>
    <div className="customer-access-body" ref={bodyRef}>
      <div className="customer-access-intro"><strong>{bulk?'邀请或撤销所选客户的协作成员':customer?.business_name}</strong><span><ShieldCheck size={14}/>仅老板管理</span></div>
      {!preview && <>
      <div className="customer-access-owner"><ShieldCheck size={17}/><div><strong>{owner?.name||'老板'}</strong><small>完整访问 · 始终保留</small></div></div>
      <div className="customer-access-toolbar"><p>{members.filter(row=>row.access_level!=='none').length} 位协作成员{bulk?'（已邀请人员汇总）':''}</p><div><Button size="sm" variant="outline" disabled={loading||Boolean(error)} onClick={()=>{setPicker(!picker);setSearch('');setChosen([]);}}><UserPlus size={15} className="mr-1"/>邀请成员</Button>{!bulk&&<Button variant="ghost" size="sm" aria-label="权限变更记录" disabled={loading} onClick={loadHistory}><History size={16}/></Button>}</div></div>
      <p className="text-xs text-slate-500">默认仅共享基础信息和成交记录，均为只读。财务通过独立入口授权。</p>
      {error&&<p role="alert" className="text-sm text-red-700">{error}</p>}
      {picker&&<section className="customer-access-picker" aria-label="邀请员工选择器"><Input aria-label="搜索可邀请员工" value={search} onChange={event=>setSearch(event.target.value)} placeholder="搜索姓名、角色或邮箱"/><div className="customer-access-candidates">{available.map(item=>{const id=Number(item.employee_id||item.id);return <label key={id}><input type="checkbox" aria-label={`邀请${item.name}`} checked={chosen.includes(id)} onChange={event=>setChosen(rows=>event.target.checked?[...rows,id]:rows.filter(value=>value!==id))}/><span><strong>{item.name}</strong><small>{systemRoleLabels[item.role as SystemRole]||item.role}{item.email?` · ${item.email}`:''}</small></span></label>;})}{!available.length&&<p className="text-xs text-slate-500">没有可邀请的员工</p>}</div><div className="customer-access-picker-footer"><NativeSelect aria-label="邀请权限模板" value={template} onChange={setTemplate} options={[{value:'basic_deals',label:'基础 + 成交 · 只读'},{value:'delivery',label:'交付协作 · 只读'},{value:'sales',label:'销售协作 · 只读'}]}/><Button size="sm" disabled={!chosen.length} onClick={()=>stageInvitations(candidates.filter(item=>chosen.includes(Number(item.employee_id||item.id))),template)}>加入 {chosen.length} 人</Button></div></section>}
      {loading?<p className="py-8 text-center text-slate-500">正在读取协作成员…</p>:<div className="customer-access-list">{members.map(row=><article key={row.employee_id} className="customer-access-member"><div className="customer-access-member-head"><div><strong>{row.name}</strong><small>{inactive(row)?'账号已停用':row.access_level==='none'?'待撤销':baseline.some(item=>item.employee_id===row.employee_id)?row.batch_requested?'待统一邀请':'已邀请':'待邀请'}{bulk&&row.customer_ids?` · ${row.customer_ids.length}/${ids.length} 位客户已邀请`:''}</small><p className="customer-access-scope-summary">{scopeSummary(row)}</p></div><Button size="sm" variant="ghost" disabled={inactive(row)||row.access_level==='none'} aria-expanded={expanded===row.employee_id} onClick={()=>setExpanded(expanded===row.employee_id?null:row.employee_id)}>栏目</Button><Button size="sm" variant="ghost" disabled={row.access_level==='none'} className="text-slate-500" aria-label={`撤销${row.name}邀请`} onClick={()=>revoke(row.employee_id)}>撤销</Button></div>
        {expanded===row.employee_id&&row.access_level!=='none'&&<div className="customer-access-scope"><div className="customer-access-module-grid">{modules.map(key=><div key={key} className="customer-access-module"><label><input type="checkbox" aria-label={`${row.name}${customerModuleLabels[key]}可见`} disabled={inactive(row)} checked={row.scopes[key]!=='none'} onChange={event=>updateScope(row.employee_id,key,event.target.checked?'read_only':'none')}/><span>{customerModuleLabels[key]}</span></label><NativeSelect aria-label={`${row.name}${customerModuleLabels[key]}权限`} disabled={inactive(row)||row.scopes[key]==='none'} value={row.scopes[key]==='read_write'?'read_write':'read_only'} onChange={value=>updateScope(row.employee_id,key,value as CustomerAccessLevel)} options={['deals','renewals'].includes(key)?[{value:'read_only',label:'只读'}]:[{value:'read_only',label:'只读'},{value:'read_write',label:'可编辑'}]}/></div>)}</div><p className="text-xs text-slate-500">{bulk?'修改会统一应用于所选客户。':''}未勾选的栏目不会向成员显示。成交和续费的财务操作仍仅老板可执行。</p><details><summary className="cursor-pointer text-xs text-slate-500">独立操作权限</summary><div className="mt-2 flex flex-wrap gap-4">{([['can_export','导出'],['can_delete','业务记录删除'],['can_reassign','转负责人']] as const).map(([key,label])=><label key={key} className="flex items-center gap-2 text-xs"><input type="checkbox" aria-label={`${row.name}${label}`} disabled={inactive(row)||(key!=='can_export'&&row.access_level!=='read_write')} checked={row[key]} onChange={event=>update(row.employee_id,item=>({...item,[key]:event.target.checked}))}/>{label}</label>)}</div></details>{row.effective_permissions&&<details><summary className="cursor-pointer text-xs text-slate-500">当前实际权限</summary><EffectiveView permission={row.effective_permissions}/></details>}</div>}
      </article>)}{!members.length&&!error&&<p className="py-6 text-center text-sm text-slate-500">目前仅老板可见，点击“邀请成员”开始协作。</p>}</div>}
      {pending.length>0&&<details className="customer-access-legacy"><summary>旧授权待确认 <Badge variant="outline">{pending.length}</Badge></summary><p>以下旧授权尚未激活。确认后按“基础 + 成交只读”重新邀请，旧财务权限不会沿用。</p>{pending.map(row=><label key={row.employee_id}><input type="checkbox" aria-label={`确认旧授权${row.name}`} disabled={inactive(row)} checked={legacyChosen.includes(row.employee_id)} onChange={event=>setLegacyChosen(rows=>event.target.checked?[...rows,row.employee_id]:rows.filter(id=>id!==row.employee_id))}/><span>{row.name}<small>{inactive(row)?'账号已停用':`原财务：${customerFinanceLabels[row.finance_access]||'不开放'}`}</small></span></label>)}<Button variant="outline" size="sm" disabled={!legacyChosen.length} onClick={()=>stageInvitations(pending.filter(row=>legacyChosen.includes(row.employee_id)),'basic_deals')}>确认邀请 {legacyChosen.length} 人</Button></details>}
      </>}
      {preview&&<section className="customer-access-preview" aria-label="保存前权限预览"><h3>保存后的员工视角</h3>{preview.map(item=><div key={`${item.customerId}-${item.name}`}><strong className="text-xs">{item.name}{bulk?` · 客户 #${item.customerId}`:''}</strong><EffectiveView permission={item.permission}/></div>)}<p className="text-xs text-slate-500">仅模拟栏目与权限，没有切换账号或读取员工数据。</p></section>}
      {!preview&&history&&<section className="customer-access-history" aria-label="权限变更记录"><h3>变更记录</h3>{history.map(item=><details key={item.id}><summary>{item.actor_name||'老板'} · {item.created_at?.slice(0,16).replace('T',' ')}</summary><div className="grid gap-2 sm:grid-cols-2">{[['变更前',item.before],['变更后',item.after]].map(([label,value])=><div key={String(label)}><strong>{String(label)}</strong><HistoryMembers value={value}/></div>)}</div></details>)}{!history.length&&<p>暂无变更记录</p>}</section>}
      {changed.length>0&&<p className="customer-access-change" role="status">待保存 {changed.length} 位成员{bulk?` · ${ids.length} 位客户`:''}；撤销后将同时关闭该成员的客户财务查看。</p>}
    </div><div className="customer-access-footer">{preview?<Button variant="outline" disabled={saving} onClick={invalidatePreview}>返回调整</Button>:<Button variant="outline" disabled={saving} onClick={close}>取消</Button>}{previewSignature===signature&&preview?<Button disabled={saving||!changed.length} onClick={save}>{saving?'保存中…':'确认保存协作'}</Button>:<Button disabled={loading||Boolean(error)||!changed.length||previewing} onClick={previewChanges}><Eye size={15} className="mr-1"/>{previewing?'核对权限中…':'预览更改'}</Button>}</div>
  </DialogContent></Dialog>;
}
function HistoryMembers({value}:{value:any}) {
  const rows=Array.isArray(value)?value:value?.members||[];
  return <div className="space-y-1 text-xs text-slate-500">{rows.map((row:any,index:number)=><div key={index}><p>{row.name||`员工 #${row.employee_id}`} · {row.invitation_status==='revoked'||row.access_level==='none'?'已撤销':'邀请'} · 财务{customerFinanceLabels[row.finance_access as CustomerFinanceAccess]||'不开放'}</p><p>{modules.filter(key=>row.scopes?.[key]&&row.scopes[key]!=='none').map(key=>`${customerModuleLabels[key]} ${customerAccessLabels[row.scopes[key] as CustomerAccessLevel]}`).join(' · ')||'无可见栏目'}</p></div>)}{!rows.length&&<p>无协作成员</p>}</div>;
}
