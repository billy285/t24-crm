import { useEffect, useRef, useState } from 'react';
import { invokeWithAuth } from '@/lib/tokenStore';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { NativeSelect } from '@/components/ui/native-select';
import './prospect-verification.css';
import { useUnsavedChanges } from '@/lib/use-unsaved-changes';

type Status = 'pending' | 'valid' | 'invalid_phone' | 'not_target' | 'closed';
type ChineseService = 'unknown' | 'yes' | 'no';
export type ProspectVerificationResponse = {
  entity_kind: 'pool' | 'lead'; entity_id: number;
  prospect_quality: { revision: number; status: Status; verified_at?: string; verified_by_name?: string; method?: string; notes?: string; corrected_fields: { chinese_service: ChineseService } };
  prospect_source: { source_url?: string; source_date?: string; source_label?: string; verification_type?: string };
  effective_fields: { business_name?: string; address?: string; contact_name?: string; chinese_service?: ChineseService };
  can_edit: boolean; read_only_reason?: string; contact_protection?: { can_contact: boolean; reason?: string };
  history: { revision: number; created_at: string; actor: { name?: string }; after: { status: Status; notes?: string } }[];
};
type Props = { entityKind: 'pool' | 'lead'; entityId: number; onSaved?: (data: ProspectVerificationResponse) => void; className?: string };
type Draft = { status: Status; method: 'call' | 'source_review'; notes: string; business_name: string; address: string; contact_name: string; chinese_service: ChineseService };
const labels: Record<Status,string> = { pending:'待核验', valid:'有效门店', invalid_phone:'号码无效', not_target:'非目标商家', closed:'已停业' };
const empty: Draft = { status:'pending', method:'call', notes:'', business_name:'', address:'', contact_name:'', chinese_service:'unknown' };
function errorText(error: any, fallback: string) { const detail=error?.response?.data?.detail ?? error?.data?.detail; return typeof detail==='string' ? detail : Array.isArray(detail) ? '核验资料格式有误，请检查必填字段。' : error?.response ? fallback : error?.message || fallback; }
const showDate = (value?: string) => value ? new Date(value).toLocaleString('zh-CN', { timeZone:'Asia/Shanghai', hour12:false }) : '尚未核验';

export default function ProspectVerification({ entityKind, entityId, onSaved, className='' }: Props) {
  const [data,setData] = useState<ProspectVerificationResponse | null>(null);
  const [draft,setDraft] = useState<Draft>(empty);
  const [open,setOpen] = useState(false);
  const [loading,setLoading] = useState(true);
  const [saving,setSaving] = useState(false);
  const [error,setError] = useState('');
  const [notice,setNotice] = useState('');
  const [conflict,setConflict] = useState(false);
  const [isDirty,setDirty] = useState(false);
  const draftGuard=useUnsavedChanges(isDirty);
  const alive = useRef(true);
  const submitting=useRef(false);
  const sequence = useRef(0);
  const dirty = useRef(false);
  const url = `/api/v1/prospect-verification/${entityKind}/${entityId}`;
  function accept(value: ProspectVerificationResponse, preserve=false) {
    if (value?.entity_kind !== entityKind || value?.entity_id !== entityId || !value.prospect_quality) throw new Error('核验返回资料不匹配，请刷新核对');
    setData(value);
    if (!preserve) {
      setDraft({ status:value.prospect_quality.status, method:'call', notes:'',
        business_name:value.effective_fields.business_name || '', address:value.effective_fields.address || '',
        contact_name:value.effective_fields.contact_name || '', chinese_service:value.effective_fields.chinese_service || 'unknown' });
      dirty.current = false;setDirty(false);draftGuard.markSaved();
    }
  }
  async function load(preserve=false) {
    const request=++sequence.current; setLoading(true); setError('');
    try {
      const response=await invokeWithAuth({url,method:'GET'});
      if (!alive.current || request!==sequence.current) return;
      accept(response.data,preserve);setConflict(false);
      if (preserve) setNotice('已读取最新记录并保留本次输入，请核对后再保存。');
    } catch (e: any) { if (alive.current && request===sequence.current) setError(errorText(e,'核验资料暂不可读取')); }
    finally { if (alive.current && request===sequence.current) setLoading(false); }
  }
  useEffect(()=>{ alive.current=true;setData(null);setDraft(empty);dirty.current=false;void load();return()=>{alive.current=false;sequence.current++;}; },[entityKind,entityId]);
  function update<K extends keyof Draft>(key: K,value: Draft[K]) { dirty.current=true;setDirty(true);setDraft(current=>({...current,[key]:value}));setNotice(''); }
  async function save() {
    if (!data?.can_edit || loading || saving || submitting.current || conflict) return;
    if (!draft.notes.trim()) {setError('请填写实际核验依据或待确认事项。');return;}
    const corrections: Record<string,string> = {chinese_service:draft.chinese_service};
    for (const key of ['business_name','address','contact_name'] as const) {
      const value=draft[key].trim();if(value && value !== (data.effective_fields[key] || '')) corrections[key]=value;
    }
    submitting.current=true;setSaving(true);setError('');setNotice('');
    try {
      const response=await invokeWithAuth({url,method:'PATCH',data:{expected_revision:data.prospect_quality.revision,status:draft.status,method:draft.method,notes:draft.notes.trim(),corrected_fields:corrections}});
      if (!alive.current) return;
      accept(response.data);setNotice('核验结果已保存，修改历史已保留。');onSaved?.(response.data);
    } catch(e:any) {
      if(!alive.current)return;
      setError(errorText(e,'保存未确认，请读取最新记录核对。'));
      if(e?.status===409 || e?.response?.status===409 || e?.data?.status===409 || /其他人|版本|更新|修订/.test(String(e?.response?.data?.detail ?? e?.data?.detail ?? '')))setConflict(true);
    } finally {submitting.current=false;if(alive.current)setSaving(false);}
  }
  const quality=data?.prospect_quality;
  const source=data?.prospect_source;
  return <section className={`prospect-verification ${className}`} aria-label="首拨核验">
    <div className="pv-heading"><div><strong>首拨核验</strong><Badge variant="outline">{quality ? labels[quality.status] : '读取中'}</Badge></div><Button type="button" size="sm" variant="ghost" onClick={()=>setOpen(value=>!value)} aria-expanded={open}>{open?'收起核验':'核验门店资料'}</Button></div>
    {source && <p className="pv-source">{source.verification_type==='recruitment_contact'?'招聘联系点 · 店名及地址待确认':source.verification_type==='public_business_profile'?'具名公开商家资料':'公开线索 · 主体待确认'}{source.source_date && ` · 来源日期 ${source.source_date}`}{source.source_url && /^https?:\/\//i.test(source.source_url) && <> · <a href={source.source_url} target="_blank" rel="noopener noreferrer">查看原始来源</a></>}</p>}
    {quality?.verified_at && <p className="pv-source">最近核验：{quality.verified_by_name || '员工'} · {showDate(quality.verified_at)}（北京时间）</p>}
    {error && <p className="pv-error" role="alert">{error}<Button type="button" size="sm" variant="ghost" disabled={loading || saving} onClick={()=>void load(dirty.current)}>读取最新记录</Button></p>}
    {notice && <p className="pv-notice" role="status">{notice}</p>}
    {open && <div className="pv-body">
      <p className="pv-help">记录门店与号码的真实情况；销售意向和通话结果另行保存。招聘广告日期不代表当前营业状态。</p>
      {data?.read_only_reason && <p className="pv-help">{data.read_only_reason}</p>}
      {data?.contact_protection?.can_contact===false && <p className="pv-help">{data.contact_protection.reason || '此商家已有联系保护，请先核对档案。'}</p>}
      <fieldset disabled={loading || saving || !data?.can_edit}>
        <div className="pv-fields"><label>核验结果<NativeSelect aria-label="首拨核验结果" value={draft.status} onChange={v=>update('status',v as Status)} options={Object.entries(labels).map(([value,label])=>({value,label}))}/></label>
        <label>核验方式<NativeSelect aria-label="首拨核验方式" value={draft.method} onChange={v=>update('method',v as Draft['method'])} options={[{value:'call',label:'实际电话核验'},{value:'source_review',label:'公开来源复核'}]}/></label>
        <label>实际店名<Input aria-label="核验实际店名" maxLength={200} value={draft.business_name} onChange={e=>update('business_name',e.target.value)}/></label>
        <label>联系人<Input aria-label="核验联系人" maxLength={200} value={draft.contact_name} onChange={e=>update('contact_name',e.target.value)}/></label>
        <label className="pv-wide">实际地址<Input aria-label="核验实际地址" maxLength={500} value={draft.address} onChange={e=>update('address',e.target.value)}/></label>
        <label>中文服务<NativeSelect aria-label="核验中文服务" value={draft.chinese_service} onChange={v=>update('chinese_service',v as ChineseService)} options={[{value:'unknown',label:'待确认'},{value:'yes',label:'已确认提供'},{value:'no',label:'已确认不提供'}]}/></label>
        <label className="pv-wide">核验依据 / 待确认事项 *<Textarea aria-label="首拨核验依据" maxLength={2000} value={draft.notes} onChange={e=>update('notes',e.target.value)} placeholder="填写实际确认的内容，未知事项保留待核验"/></label></div>
        <div className="pv-actions"><Button type="button" size="sm" onClick={()=>void save()} disabled={saving || loading || conflict}>{saving?'正在保存…':'保存核验'}</Button></div>
      </fieldset>
      {data?.history?.length>0 && <details className="pv-history"><summary>核验修改历史（{data.history.length}）</summary>{data.history.map(item=><article key={item.revision}><strong>第 {item.revision} 次 · {labels[item.after.status]} · {item.actor.name || '员工'}</strong><time>{showDate(item.created_at)}</time><p>{item.after.notes}</p></article>)}</details>}
    </div>}
  </section>;
}
