import { useEffect, useRef, useState } from 'react';
import { RefreshCw } from 'lucide-react';
import { googleBusinessApi, verifiedGbpStatus, type GbpStatus } from '@/lib/google-business-api';
import { mediaError } from '@/lib/media-operations-api';
import { Button } from '@/components/ui/button';

export default function MediaPlatformCapabilities({ scope }: { scope: string }) {
  const [data,setData]=useState<GbpStatus|null>(null),[error,setError]=useState(''),[loading,setLoading]=useState(false);
  const currentScope=useRef(scope);currentScope.current=scope;const sequence=useRef(0);
  const load=async()=>{const seq=++sequence.current,identity=scope;setLoading(true);setError('');try{const value=verifiedGbpStatus(await googleBusinessApi<GbpStatus>('/status'));if(seq===sequence.current&&currentScope.current===identity)setData(value);}catch(cause){if(seq===sequence.current&&currentScope.current===identity){setData(null);setError(mediaError(cause,'Google 接入状态暂时无法读取。'));}}finally{if(seq===sequence.current&&currentScope.current===identity)setLoading(false);}};
  useEffect(()=>{setData(null);void load();return()=>{sequence.current++;};},[scope]);
  const active=data?.bindings.filter(binding=>binding.active).length||0;
  const googleLabel=loading?'正在核对':error?'读取失败':!data?.enabled||!data?.configured?'尚未开通':active?`已授权 · ${active} 家门店`:data.connections.some(row=>row.active&&!row.needs_reconnect)?'已授权 · 待绑定门店':data.is_owner?'等待本人授权':'尚未开放门店权限';
  return <details className="mo-platform-capabilities"><summary><strong>平台能力</strong><span>Google：{googleLabel}</span><span>Facebook / Instagram：人工任务</span><small>查看说明</small></summary><div className="mo-platform-grid"><div><strong>Google 商家</strong><span>{googleLabel}</span><small>{error||'图文、优惠与活动按已审核内容执行；仍受门店授权和图片要求限制。'}</small><Button variant="ghost" size="sm" aria-label="刷新 Google 接入状态" disabled={loading} onClick={()=>void load()}><RefreshCw size={13}/></Button></div><div><strong>Facebook / Instagram</strong><span>人工任务 · 尚未接入发布</span><small>可准备内容、审核及保存真实发布凭证。没有 API 连接或自动发布承诺。</small></div><div><strong>视频素材</strong><span>准备与人工预检</span><small>可进入团队素材库；Google 视频 API 发布待专项验证。</small></div></div></details>;
}
