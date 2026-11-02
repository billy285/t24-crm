import { useEffect, useRef, useState } from 'react';
import { AlertCircle, ArrowRight, CalendarClock, ChevronDown, Loader2, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { monthlyApi, monthlyPlatformLabels } from '@/lib/media-monthly-api';
import { mediaError, mediaUtcToLocal } from '@/lib/media-operations-api';
import { automationJobLabels, verifiedAutomationOverview, type AutomationOverview, type AutomationOverviewJob } from '@/lib/media-automation-api';
import './media-automation-panel.css';
import './media-ops-refinement.css';

type Props = { scope: string; isOwner: boolean; visible: boolean; refreshToken: number; onOpen: (job: AutomationOverviewJob) => void };
export default function MediaAutomationOverview(props: Props) {
  if (!props.isOwner || !props.visible) return null;
  return <OwnerAutomationOverview key={props.scope} {...props}/>;
}
function OwnerAutomationOverview({ scope, refreshToken, onOpen }: Props) {
  const current = useRef(scope); current.current = scope;
  const alive = useRef(true);
  const [data, setData] = useState<AutomationOverview | null>(null), [loading, setLoading] = useState(true), [error, setError] = useState(''), [refresh, setRefresh] = useState(0), [expanded, setExpanded] = useState(false);
  useEffect(() => {
    alive.current = true; let active = true; const controller = new AbortController(); setLoading(true); setData(null); setError('');
    void monthlyApi<AutomationOverview>('/automation/overview', 'GET', undefined, controller.signal).then(value => { const verified = verifiedAutomationOverview(value); if (active && !controller.signal.aborted && current.current === scope) { setData(verified); setExpanded(verified.attention_total > 0); } }).catch(cause => { if (active && !controller.signal.aborted && current.current === scope) setError(mediaError(cause, '自动准备总览暂时无法读取。')); }).finally(() => { if (active && !controller.signal.aborted && current.current === scope) setLoading(false); });
    return () => { active = false; alive.current = false; controller.abort(); };
  }, [scope, refreshToken, refresh]);
  if (loading) return <p className="ma-loading" role="status"><Loader2 className="animate-spin"/>正在核对草稿自动准备进度…</p>;
  if (error || !data) return <div className="ma-message warning" role="alert"><AlertCircle/><div><strong>自动准备进度待核对</strong><p>{error || '当前无法确认是否有准备异常。'}</p><Button variant="outline" onClick={() => setRefresh(value => value + 1)}>重新读取</Button></div></div>;
  const attention = data.attention_jobs;
  const attentionButton = (job: AutomationOverviewJob) => <button type="button" key={job.id} onClick={() => { if (alive.current && current.current === scope) onOpen(job); }}><span><b>{job.customer_name}</b><small>{monthlyPlatformLabels[job.platform]} · {job.month} · {automationJobLabels[job.status]}</small></span><ArrowRight size={16}/></button>;
  return <section className={`ma-overview ma-overview-compact${data.attention_total > 0 ? ' has-attention' : ''}`} aria-label="草稿自动准备总览"><button type="button" className="ma-overview-toggle" aria-expanded={expanded} aria-controls="ma-overview-details" onClick={() => setExpanded(value => !value)}><span><CalendarClock size={16}/><b>草稿自动准备</b><small>规则 {data.counts.enabled}/{data.counts.policies} · 已生成 {data.counts.generated} · 待核对 {data.attention_total}{!data.worker.enabled ? ' · 服务未启用' : ' · 生成后等待审核'}</small></span><ChevronDown size={16}/></button>{expanded && <div className="ma-overview-expanded" id="ma-overview-details"><header><div><span>已设置商家 · 草稿准备</span><h3><CalendarClock size={17}/>让下个月提前就绪</h3></div><Button variant="ghost" aria-label="刷新草稿自动准备总览" onClick={() => setRefresh(value => value + 1)}><RefreshCw size={15}/></Button></header><div className="ma-overview-metrics"><div><span>已开启规则</span><strong>{data.counts.enabled}<small> / {data.counts.policies}</small></strong></div><div><span>已生成草案</span><strong>{data.counts.generated}</strong></div><div className={data.counts.blocked + data.counts.unknown > 0 ? 'warning' : ''}><span>需核对 / 结果待确认</span><strong>{data.counts.blocked}<small> / {data.counts.unknown}</small></strong></div></div><p className="ma-caption">准备结果期间：{mediaUtcToLocal(data.period_start, 'Asia/Shanghai').slice(0, 10)} — {mediaUtcToLocal(data.period_end, 'Asia/Shanghai').slice(0, 10)}（北京时间）。规则在各商家“自动化设置”设置，生成后仍等待你的内容审核。</p>{!data.worker.enabled && <p className="ma-message"><CalendarClock size={15}/>自动准备服务尚未启用，已保存规则暂不后台执行。</p>}{data.attention_total > 0 && <div className="ma-overview-attention"><strong>先处理准备异常 · {data.attention_total}项</strong>{attention.slice(0, 4).map(attentionButton)}{attention.length > 4 && <details><summary>展开其余{attention.length - 4}项准备异常</summary>{attention.slice(4).map(attentionButton)}</details>}{data.attention_total > attention.length && <p className="ma-caption">本总览显示最近{attention.length}项准备异常；其余{data.attention_total - attention.length}项请从商家列表进入对应商家的“自动化设置”核对。</p>}</div>}</div>}</section>;
}
