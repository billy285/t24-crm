import { useEffect, useRef, useState } from 'react';
import { Download, FolderOpen, Loader2, LockKeyhole, RefreshCw, Upload } from 'lucide-react';
import { invokeWithAuth } from '@/lib/tokenStore';
import { client } from '@/lib/api';
import { customerPermissions, type CustomerEffectivePermissions } from '@/lib/customer-permissions';
import { confirmDiscardAllChanges, useHardNavigationBlock, useUnsavedChanges } from '@/lib/use-unsaved-changes';
import { mediaError, mediaErrorStatus, type MediaCustomer } from '@/lib/media-operations-api';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { NativeSelect } from '@/components/ui/native-select';
import './media-team-materials.css';

type TeamMaterial = { id: number; customer_id: number; title: string; material_type: string; visibility: string; source_type?: string; file_name?: string; file_url?: string; file_path?: string; approval_status?: string; copyright_status?: string; content_type?: string };
const validLink = (value: string) => { try { const url = new URL(value); return url.protocol === 'https:' && !url.username && !url.password ? url.href : null; } catch { return null; } };
const materialAccess = (item: TeamMaterial): 'private_file' | 'external_link' | 'record_only' => item.file_path?.trim() ? 'private_file' : validLink(item.file_url || '') ? 'external_link' : 'record_only';

export default function MediaTeamMaterials({ customers, initialCustomerId, onChanged, loading, error, onRetry }: { customers: MediaCustomer[]; initialCustomerId?: number; onChanged: () => void; loading: boolean; error: string; onRetry: () => void }) {
  const [selected, setSelected] = useState(initialCustomerId ? String(initialCustomerId) : '');
  const customer = customers.find(row=>String(row.id)===selected);
  return <section className="mo-team-materials" aria-label="客户团队素材"><header><div><h2><FolderOpen size={18}/>客户团队素材</h2><p>复用客户素材库；这里只处理团队素材，老板和财务私密素材不进入运营内容。</p></div><NativeSelect aria-label="素材所属客户" value={customer ? selected : ''} onChange={value=>{if(confirmDiscardAllChanges())setSelected(value);}} disabled={loading} options={[{value:'',label:loading?'正在读取授权客户…':'选择已授权客户'},...customers.map(row=>({value:String(row.id),label:row.name}))]}/></header>{error&&<div className="mtm-notice" role="alert">{error}<Button variant="outline" disabled={loading} onClick={onRetry}>重新读取授权客户</Button></div>}{loading&&!customers.length?<p className="mtm-empty" role="status">正在读取授权客户…</p>:customer ? <TeamMaterialContents key={customer.id} customer={customer} onChanged={onChanged}/> : <div className="mtm-empty"><FolderOpen size={22}/><p>先选择客户，再查看图片、视频和发布资料。</p></div>}</section>;
}

function TeamMaterialContents({ customer, onChanged }: { customer: MediaCustomer; onChanged: () => void }) {
  const [permission, setPermission] = useState<CustomerEffectivePermissions | null>(null);
  const [permissionLoading, setPermissionLoading] = useState(true), [permissionError, setPermissionError] = useState('');
  const permissionSequence = useRef(0);
  const canRead = permission?.modules.materials.read === true, canWrite = permission?.modules.materials.write === true;
  const [items, setItems] = useState<TeamMaterial[] | null>(null);
  const [loading, setLoading] = useState(false), [error, setError] = useState('');
  const [kind, setKind] = useState('image'), [mode, setMode] = useState<'upload'|'link'>('upload');
  const [title, setTitle] = useState(''), [notes, setNotes] = useState(''), [url, setUrl] = useState('');
  const [file, setFile] = useState<File | null>(null), [busy, setBusy] = useState(false), [notice, setNotice] = useState('');
  const [unknown, setUnknown] = useState(false), [checked, setChecked] = useState(false);
  const request = useRef(0), alive = useRef(true), busyRef = useRef(false);
  const fileInput = useRef<HTMLInputElement | null>(null);
  const dirty = Boolean(title.trim() || notes.trim() || url.trim() || file);
  const guard = useUnsavedChanges(dirty), hold = useHardNavigationBlock(busy || unknown);
  const loadPermission = async () => {
    const seq=++permissionSequence.current;setPermission(null);setItems(null);setPermissionLoading(true);setPermissionError('');
    try { const response=await client.entities.customers.query({query:{id:customer.id},limit:1});if(!alive.current||seq!==permissionSequence.current)return;const value=response.data?.items?.[0];if(value&&value.id!==customer.id)throw new Error('客户授权范围返回不一致');setPermission(customerPermissions(value)); }
    catch(cause){if(alive.current&&seq===permissionSequence.current)setPermissionError(mediaError(cause,'客户素材授权暂时无法核对，请重试。'));}
    finally{if(alive.current&&seq===permissionSequence.current)setPermissionLoading(false);}
  };
  useEffect(()=>{alive.current=true;void loadPermission();return()=>{alive.current=false;request.current++;permissionSequence.current++;};},[customer.id]);
  const load = async () => {
    if (!canRead) return;
    const sequence = ++request.current; setLoading(true); setError(''); setChecked(false);
    try {
      const response = await invokeWithAuth({url:'/api/v1/entities/customer_materials',method:'GET',data:{query:JSON.stringify({customer_id:customer.id,visibility:'team'}),sort:'-created_at',limit:200}});
      if (!alive.current || sequence!==request.current) return;
      if (!Array.isArray(response.data?.items)) throw new Error('素材列表返回不完整');
      setItems(response.data.items.filter((item:TeamMaterial)=>item.customer_id===customer.id&&item.visibility==='team'));
    } catch (cause) { if (alive.current && sequence===request.current) { if ([401,403,404].includes(mediaErrorStatus(cause)||0)) setItems(null); setError(mediaError(cause,'团队素材暂时无法读取，请重试。')); } }
    finally { if (alive.current&&sequence===request.current) setLoading(false); }
  };
  useEffect(()=>{ alive.current=true; if(canRead)void load();else setItems(null);return()=>{alive.current=false;request.current++;}; },[customer.id,canRead]);
  const save = async () => {
    if (!canWrite||busyRef.current||unknown) return;
    if (!title.trim() || mode==='upload'&&!file || mode==='link'&&!validLink(url.trim())) { setError('请填写素材名称，并选择文件或填写有效 HTTPS 链接。');return; }
    busyRef.current=true;setBusy(true);setError('');setNotice('');hold.lock();
    try {
      let response;
      if(mode==='upload'){
        const body=new FormData();body.append('customer_id',String(customer.id));body.append('title',title.trim());body.append('material_type',kind);body.append('platform','general');body.append('usage_status','unused');body.append('approval_status','pending');body.append('visibility','team');body.append('copyright_status','unknown');body.append('notes',notes.trim());body.append('file',file!);
        response=await invokeWithAuth({url:'/api/v1/entities/customer_materials/upload',method:'POST',data:body,options:{headers:{'Content-Type':'multipart/form-data'}}});
      }else response=await invokeWithAuth({url:'/api/v1/entities/customer_materials',method:'POST',data:{customer_id:customer.id,title:title.trim(),material_type:kind,platform:'general',source_type:'external_link',file_url:url.trim(),usage_status:'unused',approval_status:'pending',visibility:'team',copyright_status:'unknown',notes:notes.trim()}});
      if(!alive.current)return;
      if(response.data?.customer_id!==customer.id||response.data?.visibility!=='team')throw new Error('素材保存返回范围待确认');
      setTitle('');setNotes('');setUrl('');setFile(null);if(fileInput.current)fileInput.current.value='';guard.markSaved();setNotice('团队素材已保存，仍需核对版权、内容与发布要求。');hold.release();void load();onChanged();
    }catch(cause){if(!alive.current)return;const code=mediaErrorStatus(cause);if(!code||[408,429].includes(code)||code>=500){setUnknown(true);setError('保存结果待确认。请先重新读取素材列表，核对是否已保存；不要重复上传。');}else{hold.release();setError(mediaError(cause,'素材尚未保存，请核对后重试。'));}}
    finally{if(alive.current){busyRef.current=false;setBusy(false);}}
  };
  const download = async (item:TeamMaterial) => {
    if(!canRead||item.customer_id!==customer.id||item.visibility!=='team'||busyRef.current)return;
    const access=materialAccess(item);
    if(access==='record_only'){setError('这份素材只有资料记录，尚无可下载文件或安全链接。');return;}
    if(access==='external_link') { window.open(validLink(item.file_url||'')!,'_blank','noopener,noreferrer');return; }
    busyRef.current=true;setBusy(true);setError('');
    try{const response=await invokeWithAuth({url:`/api/v1/entities/customer_materials/${item.id}/download`,method:'GET',options:{responseType:'blob'}});if(!alive.current)return;if(!(response.data instanceof Blob))throw new Error('素材文件返回不完整');const link=URL.createObjectURL(response.data),anchor=document.createElement('a');anchor.href=link;anchor.download=(item.file_name||item.title||'团队素材').replace(/[\\/\u0000-\u001f]/g,'_');document.body.appendChild(anchor);anchor.click();anchor.remove();window.setTimeout(()=>URL.revokeObjectURL(link),1000);}catch(cause){if(alive.current)setError(mediaError(cause,'素材下载失败，请重新核对授权。'));}finally{if(alive.current){busyRef.current=false;setBusy(false);}}
  };
  if(permissionLoading)return <div className="mtm-empty" role="status"><Loader2 className="animate-spin"/><p>正在核对该客户的素材授权…</p></div>;
  if(permissionError)return <div className="mtm-notice" role="alert">{permissionError}<Button variant="outline" onClick={()=>void loadPermission()}>重新核对素材授权</Button></div>;
  if(!canRead)return <div className="mtm-empty"><LockKeyhole size={22}/><p>此客户尚未开放素材查看。客户交付权限不等于素材库权限，请由老板单独授权。</p></div>;
  return <><div className="mtm-toolbar"><span>{items ? `${items.length} 份团队素材（最多读取最新 200 份）`:'资料尚未读取'}</span><Button variant="outline" disabled={loading||busy} onClick={()=>void load()}><RefreshCw size={14} className={loading?'animate-spin':''}/>刷新素材</Button></div>{error&&<div className="mtm-notice" role="alert">{error}</div>}{notice&&<p className="mtm-notice" role="status">{notice}</p>}{unknown&&<div className="mtm-notice"><p>先点击刷新核对当前客户的最新素材，确认后才可继续添加。</p><label><input type="checkbox" disabled={loading||Boolean(error)||!items} checked={checked} onChange={event=>setChecked(event.target.checked)}/>我已核对列表，确认不会重复保存</label><Button variant="outline" disabled={!checked||loading||Boolean(error)} onClick={()=>{setUnknown(false);setChecked(false);setError('');hold.release();}}>继续处理</Button></div>}{loading&&!items?<p className="mtm-empty" role="status"><Loader2 className="animate-spin"/>正在读取团队素材…</p>:items?.length?<div className="mtm-list">{items.map(item=><article key={item.id}><div><strong>{item.title||item.file_name||`素材 #${item.id}`}</strong><span>{item.material_type==='video'?'视频 · 仅素材准备':item.material_type==='image'?'图片':item.material_type} · {item.approval_status==='approved'?'已审核':'待审核'}</span><small>{materialAccess(item)==='private_file'?'私有文件 · 授权后下载':materialAccess(item)==='external_link'?'外部素材链接 · 不代表可自动发布':'仅素材资料 · 尚无文件或链接'}</small></div>{materialAccess(item)!=='record_only'&&<Button variant="outline" onClick={()=>void download(item)} disabled={busy}><Download size={14}/>{materialAccess(item)==='external_link'?'查看链接':'下载'}</Button>}</article>)}</div>:items&&!error?<p className="mtm-empty">还没有团队素材。{canWrite?'可在下方添加，保存后再关联运营任务。':''}</p>:null}{canWrite&&<details className="mtm-create"><summary><Upload size={14}/>添加团队素材</summary><div className="mtm-form"><NativeSelect aria-label="素材录入方式" disabled={busy||unknown} value={mode} onChange={value=>setMode(value as 'upload'|'link')} options={[{value:'upload',label:'上传私有文件'},{value:'link',label:'添加素材链接'}]}/><label>素材名称<Input aria-label="团队素材名称" disabled={busy||unknown} maxLength={200} value={title} onChange={event=>setTitle(event.target.value)}/></label><NativeSelect aria-label="团队素材类型" disabled={busy||unknown} value={kind} onChange={setKind} options={[{value:'image',label:'图片'},{value:'video',label:'视频（仅准备）'},{value:'document',label:'文档'},{value:'screenshot',label:'截图'}]}/>{mode==='upload'?<label>选择文件<input aria-label="选择团队素材文件" type="file" ref={fileInput} disabled={busy||unknown} onChange={event=>setFile(event.target.files?.[0]||null)}/>{file&&<small>{file.name}</small>}</label>:<label>素材链接<Input aria-label="团队素材链接" type="url" placeholder="https://…" disabled={busy||unknown} maxLength={2000} value={url} onChange={event=>setUrl(event.target.value)}/></label>}<label>素材说明<Textarea aria-label="团队素材说明" disabled={busy||unknown} rows={2} value={notes} onChange={event=>setNotes(event.target.value)}/></label><p>保存范围固定为团队，版权和审核状态为待核对。私有上传不会自动变成平台可抓取图片；Google 视频发布仍待专项验证。</p><Button disabled={busy||unknown} onClick={()=>void save()}>{busy?'正在保存…':'保存团队素材'}</Button></div></details>}</>;
}
