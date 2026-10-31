import { useEffect, useRef, useState } from 'react';
import { RefreshCw } from 'lucide-react';
import { googleBusinessApi, verifiedGbpStatus, type GbpStatus } from '@/lib/google-business-api';
import { mediaError } from '@/lib/media-operations-api';
import { Button } from '@/components/ui/button';
import { metaBusinessApi, metaRequestScope, verifiedMetaStatus, type MetaStatus } from '@/lib/meta-business-api';

export default function MediaPlatformCapabilities({ scope, isOwner = false, metaRefreshKey = 0, onOpenMeta }: { scope: string; isOwner?: boolean; metaRefreshKey?: number; onOpenMeta?: () => void }) {
  const [data,setData]=useState<GbpStatus|null>(null),[error,setError]=useState(''),[loading,setLoading]=useState(false);
  const currentScope=useRef(scope);currentScope.current=scope;const sequence=useRef(0);
  const load=async()=>{const seq=++sequence.current,identity=scope;setLoading(true);setError('');try{const value=verifiedGbpStatus(await googleBusinessApi<GbpStatus>('/status'));if(seq===sequence.current&&currentScope.current===identity)setData(value);}catch(cause){if(seq===sequence.current&&currentScope.current===identity){setData(null);setError(mediaError(cause,'Google 接入状态暂时无法读取。'));}}finally{if(seq===sequence.current&&currentScope.current===identity)setLoading(false);}};
  useEffect(()=>{setData(null);void load();return()=>{sequence.current++;};},[scope]);
  const metaIdentity=`${scope}:${isOwner?'owner':'staff'}`,metaFence=useRef(metaRequestScope(metaIdentity));metaFence.current.update(metaIdentity);
  const [meta,setMeta]=useState<{identity:string;value:MetaStatus}|null>(null),[metaError,setMetaError]=useState(''),[metaLoading,setMetaLoading]=useState(false);
  useEffect(()=>{metaFence.current.activate();setMeta(null);setMetaError('');setMetaLoading(isOwner);const current=metaFence.current.capture();if(isOwner){void metaBusinessApi<MetaStatus>('/status').then(verifiedMetaStatus).then(value=>{if(current())setMeta({identity:metaIdentity,value});}).catch(()=>{if(current())setMetaError('Meta连接状态暂时无法读取');}).finally(()=>{if(current())setMetaLoading(false);});}return()=>{metaFence.current.invalidate();};},[metaIdentity,isOwner,metaRefreshKey]);
  const metaValue=meta?.identity===metaIdentity?meta.value:null;
  const metaLabel=!isOwner?'连接阶段仅老板管理':metaLoading?'正在核对':metaError?'读取失败':!metaValue?'尚未读取':!metaValue.is_owner?'尚未开放管理':!metaValue.enabled||!metaValue.configured?'接入配置待完成':metaValue.bindings.some(row=>row.active)?`已连接 · ${metaValue.bindings.filter(row=>row.active).length} 个客户账号`:metaValue.connections.some(row=>row.active&&!row.needs_reconnect)?'已授权 · 待绑定客户':'等待本人授权';
  const active=data?.bindings.filter(binding=>binding.active).length||0;
  const googleLabel=loading?'正在核对':error?'读取失败':!data?.enabled||!data?.configured?'尚未开通':active?`已授权 · ${active} 家门店`:data.connections.some(row=>row.active&&!row.needs_reconnect)?'已授权 · 待绑定门店':data.is_owner?'等待本人授权':'尚未开放门店权限';
  return <details className="mo-platform-capabilities"><summary><strong>平台能力</strong><span>Google：{googleLabel}</span><span>Facebook / Instagram：{metaLabel} · 人工交付</span><small>查看说明</small></summary><div className="mo-platform-grid"><div><strong>Google 商家</strong><span>{googleLabel}</span><small>{error||'图文、优惠与活动按已审核内容执行；仍受门店授权和图片要求限制。'}</small><Button variant="ghost" size="sm" aria-label="刷新 Google 接入状态" disabled={loading} onClick={()=>void load()}><RefreshCw size={13}/></Button></div><div><strong>Facebook / Instagram</strong><span>{metaLabel}</span><small>当前仅连接与客户绑定；发帖、评论回复和员工操作尚未接入。现有任务继续人工交付。</small>{isOwner&&onOpenMeta&&<Button className="mo-meta-entry" variant="ghost" size="sm" onClick={onOpenMeta}>管理 Meta 连接</Button>}</div><div><strong>视频素材</strong><span>准备与人工预检</span><small>可进入团队素材库；Google 视频 API 发布待专项验证。</small></div></div></details>;
}
