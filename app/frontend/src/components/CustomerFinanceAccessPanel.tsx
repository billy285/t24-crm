import { useEffect, useRef, useState } from 'react';
import { invokeWithAuth } from '@/lib/tokenStore';
import { useUnsavedChanges } from '@/lib/use-unsaved-changes';
import { customerFinanceLabels, type CustomerFinanceAccess } from '@/lib/customer-permissions';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { NativeSelect } from '@/components/ui/native-select';
import { toast } from 'sonner';
import './customer-access.css';

type Member = {employee_id:number;name:string;status:string;finance_access:CustomerFinanceAccess};
const descriptions:Record<CustomerFinanceAccess,string>={none:'不显示财务栏目',status:'仅收款笔数、日期和是否欠款，不含金额',receipts:'可查看该客户收款与退款金额，不含手续费、成本和利润',profit:'可查看该客户收款、成本与利润，仍不能修改账目'};
export default function CustomerFinanceAccessPanel({customer,open,onClose,onSaved}:{customer:any;open:boolean;onClose:()=>void;onSaved:()=>void|Promise<void>}) {
  const [rows,setRows]=useState<Member[]>([]),[baseline,setBaseline]=useState<Member[]>([]);
  const [loading,setLoading]=useState(false),[saving,setSaving]=useState(false),[error,setError]=useState(''),[confirmed,setConfirmed]=useState(false);
  const request=useRef(0);
  const changed=rows.filter(row=>row.finance_access!==baseline.find(item=>item.employee_id===row.employee_id)?.finance_access);
  const draft=useUnsavedChanges(open&&changed.length>0);
  const message=(err:any)=>err?.response?.data?.detail||err?.data?.detail||'财务授权未完成，请重试';
  useEffect(()=>{const id=++request.current;if(!open)return;setRows([]);setBaseline([]);setError('');setConfirmed(false);setLoading(true);invokeWithAuth({url:`/api/v1/entities/customers/${customer.id}/access`,method:'GET'}).then(response=>{if(id!==request.current)return;const members=(response.data?.members||[]).filter((row:any)=>row.role!=='super_admin');setRows(members);setBaseline(members);}).catch(err=>{if(id===request.current)setError(message(err));}).finally(()=>{if(id===request.current)setLoading(false);});return()=>{request.current++;};},[open,customer?.id]);
  const save=async()=>{if(!confirmed||!changed.length||saving)return;setSaving(true);try{for(const row of changed)await invokeWithAuth({url:`/api/v1/entities/customers/${customer.id}/access/${row.employee_id}/finance`,method:'PUT',data:{finance_access:row.finance_access}});draft.markSaved();toast.success('客户财务查看权限已保存');await onSaved();onClose();}catch(err){toast.error(message(err));setConfirmed(false);}finally{setSaving(false);}};
  const close=()=>{if(!saving&&(!changed.length||draft.confirmDiscard()))onClose();};
  return <Dialog open={open} onOpenChange={value=>{if(!value)close();}}><DialogContent className="customer-access-dialog"><DialogHeader><DialogTitle>财务单独授权</DialogTitle></DialogHeader><div className="customer-access-body"><strong className="text-sm">{customer?.business_name}</strong><p className="text-xs text-slate-500">仅对已邀请成员开放这位客户的财务。所有等级均为查看，不允许记账、改账或关账。</p>{error&&<p role="alert" className="text-sm text-red-700">{error}</p>}{loading?<p>正在读取…</p>:rows.length?<div className="customer-access-list">{rows.map(row=><article className="customer-access-member" key={row.employee_id}><div className="customer-access-member-head"><div><strong>{row.name}</strong><small>{descriptions[row.finance_access]}</small></div><NativeSelect aria-label={`${row.name}独立财务权限`} disabled={!['active','probation'].includes(row.status||'active')} value={row.finance_access} onChange={value=>{setConfirmed(false);setRows(items=>items.map(item=>item.employee_id===row.employee_id?{...item,finance_access:value as CustomerFinanceAccess}:item));}} options={Object.entries(customerFinanceLabels).map(([value,label])=>({value,label}))}/></div></article>)}</div>:<p className="py-6 text-center text-sm text-slate-500">暂无协作成员。请先从“协作成员”邀请员工。</p>}{changed.length>0&&<section className="customer-access-preview" aria-label="财务授权确认"><h3>本次变更</h3>{changed.map(row=><p key={row.employee_id} className="text-xs">{row.name}：{customerFinanceLabels[baseline.find(item=>item.employee_id===row.employee_id)?.finance_access||'none']} → {customerFinanceLabels[row.finance_access]}<br/>{descriptions[row.finance_access]}</p>)}<label className="flex items-center gap-2 text-xs"><input type="checkbox" aria-label="确认独立财务授权" checked={confirmed} onChange={event=>setConfirmed(event.target.checked)}/>确认以上财务可见范围</label></section>}</div><div className="customer-access-footer"><Button variant="outline" disabled={saving} onClick={close}>取消</Button><Button disabled={loading||saving||Boolean(error)||!confirmed||!changed.length} onClick={save}>{saving?'保存中…':'保存财务授权'}</Button></div></DialogContent></Dialog>;
}
