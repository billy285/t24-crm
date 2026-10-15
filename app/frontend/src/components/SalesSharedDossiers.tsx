import { useEffect, useRef, useState } from 'react';
import { RefreshCw, Search, Users } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { dossierApi, type SharedDossier } from '@/lib/sales-lead-dossier';
import { salesDate, salesError } from '@/lib/sales-intelligence';
import { useRole } from '@/lib/role-context';
import './sales-lead-dossier.css';

export default function SalesSharedDossiers({onOpen}:{onOpen:(id:number)=>void}) {
  const {employee} = useRole();
  const [items,setItems] = useState<SharedDossier[]>([]);
  const [error,setError] = useState('');
  const [loading,setLoading] = useState(false);
  const [query,setQuery] = useState('');
  const request = useRef(0);
  const load = async () => {
    const seq = ++request.current; setLoading(true); setError(''); setItems([]);
    try { const result = await dossierApi<{items:SharedDossier[];total:number}>('?shared_only=true'); if (seq === request.current) setItems(result.items || []); }
    catch(e) { if(seq === request.current) setError(salesError(e)); }
    finally { if(seq === request.current) setLoading(false); }
  };
  useEffect(() => { setQuery(''); void load(); return () => { request.current++; }; },[employee?.id]);
  const visible = items.filter(item => `${item.business_name} ${item.industry || ''} ${item.state || ''} ${item.owner_name || ''}`.toLowerCase().includes(query.trim().toLowerCase()));
  return <section className="sd-related-list" aria-label="受邀协作档案"><div className="sd-shared-heading"><div><h3 className="font-semibold flex items-center gap-2"><Users size={15}/>协作档案 <small className="font-normal text-slate-400">{items.length}</small></h3><p>老板邀请你查看或补充的商家，不进入你的拨打任务。</p></div><Button variant="outline" size="sm" disabled={loading} onClick={() => void load()}><RefreshCw size={13}/>刷新</Button></div><label className="flex items-center gap-2 mb-3"><Search size={15} className="text-slate-400"/><Input aria-label="搜索协作档案" placeholder="搜索商家、行业、州或负责人" value={query} onChange={event=>setQuery(event.target.value)}/></label>{error ? <div role="alert" className="sd-error">{error}<Button variant="ghost" size="sm" onClick={()=>void load()}>重试</Button></div> : loading ? <p className="sd-empty" role="status">正在读取受邀档案…</p> : !visible.length ? <p className="sd-empty">{query ? '没有符合搜索条件的协作档案。' : '暂无受邀档案，由老板邀请后会显示在这里。'}</p> : <div className="sd-shared-grid">{visible.map(item=><button type="button" className="sd-shared-card" key={item.id} onClick={()=>onOpen(item.lead_id || item.id)} aria-label={`打开协作档案：${item.business_name}`}><h3>{item.business_name}</h3><p>{item.industry || '待分类'} · {item.state || '地区待核实'}<span className="sd-tag ml-2">{item.access === 'collaborate' ? '协作补充' : '只读查看'}</span></p><p>主要负责人：{item.owner_name || item.owner || '待分配'}</p><small>最近联系 {salesDate(item.last_contact_at)}</small></button>)}</div>}</section>;
}
