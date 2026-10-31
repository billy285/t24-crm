import { useEffect, useRef, useState } from 'react';
import { AlertCircle, CheckCircle2, ChevronRight, ClipboardCheck, Clock3, Loader2, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { gbpActionLabels, type GbpAction, type GbpBinding } from '@/lib/google-business-api';
import { gpmScheduleLabels } from '@/lib/google-management-api';
import { imageRequestScope } from '@/lib/media-publication-images';
import { mediaError, mediaUtcToLocal } from '@/lib/media-operations-api';
import { readGoogleReadiness, type GbpReadiness } from '@/lib/google-readiness';
import './google-readiness.css';

type Props = { binding: GbpBinding; scope: string; taskId?: number; onReadiness?: (value: GbpReadiness | null) => void; onOpenAction?: (action: GbpAction) => void };
export default function GoogleReadinessChecklist({ binding, scope, taskId, onReadiness, onOpenAction }: Props) {
  const identity = `${scope}:${binding.id}:${binding.customer_id}:${binding.revision}:${taskId || ''}`;
  const fence = useRef(imageRequestScope(identity)); fence.current.update(identity);
  const seq = useRef(0), listener = useRef(onReadiness); listener.current = onReadiness;
  const [state, setState] = useState<{ identity: string; value: GbpReadiness } | null>(null);
  const [loading, setLoading] = useState(true), [error, setError] = useState('');
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    fence.current.activate(); const current = fence.current.capture(), request = ++seq.current;
    setState(null); setLoading(true); setError(''); listener.current?.(null);
    void readGoogleReadiness(binding, taskId).then(value => {
      if (!current() || request !== seq.current) return;
      setState({ identity, value }); listener.current?.(value);
    }).catch(cause => { if (current() && request === seq.current) setError(mediaError(cause, cause instanceof Error ? cause.message : '暂时无法核对开工条件。')); })
      .finally(() => { if (current() && request === seq.current) setLoading(false); });
    return () => { fence.current.invalidate(); seq.current++; };
  }, [identity, retry]);
  const value = state?.identity === identity ? state.value : null;
  const issues = value?.checks.filter(row => row.status !== 'passed').length || 0;
  const format = (date: string, timezone: string) => mediaUtcToLocal(date, timezone).replace('T', ' ') || '时间待核对';
  return <section className="gpr-checklist" aria-label={taskId ? '本任务发布前检查' : '当前门店开工检查'}>
    <header><div><ClipboardCheck aria-hidden="true"/><strong>{taskId ? '本任务发布前检查' : '开工检查'}</strong>{value && <span className={issues ? 'gpr-count warning' : 'gpr-count'}>{issues ? `${issues} 项待处理` : '当前条件已核对'}</span>}</div><Button variant="ghost" size="sm" disabled={loading} onClick={() => setRetry(value => value + 1)} aria-label="重新核对开工条件"><RefreshCw size={15} className={loading ? 'animate-spin' : ''}/></Button></header>
    {loading || !value && !error ? <p className="gpr-note" role="status"><Loader2 size={15} className="animate-spin"/>正在核对当前门店与任务条件…</p> : error ? <p className="gpr-note warning" role="alert"><AlertCircle size={15}/>{error}</p> : value && <>
      <details open={issues > 0 || undefined}><summary>查看门店、负责人、素材和发布准备情况<ChevronRight size={14}/></summary><ul>{value.checks.map(check => <li key={check.key} className={`gpr-${check.status}`}>{check.status === 'passed' ? <CheckCircle2 size={15}/> : check.status === 'blocked' ? <AlertCircle size={15}/> : <Clock3 size={15}/>}<div><strong>{check.label}<span>{{ passed: '已核对', pending: '待准备', blocked: '需处理' }[check.status]}</span></strong><p>{check.message}</p></div></li>)}</ul></details>
      {value.task && <p className="gpr-note"><Clock3 size={14}/>任务截止：{format(value.task.due_at, value.task.timezone)} · {value.task.timezone}。这是准备完成目标，不是 Google 自动发布时间。</p>}
      {value.active_schedule ? <p className="gpr-note">最近 Google 排期：{format(value.active_schedule.planned_at, value.active_schedule.timezone)} · {gpmScheduleLabels[value.active_schedule.status]}。{value.active_schedule.message}</p> : taskId && <p className="gpr-note">尚未安排 Google 自动发布时间。核对内容后，可即时确认发布或另外明确排期。</p>}
      {value.active_action && <div className="gpr-action"><div><strong>最近 Google 操作：{gbpActionLabels[value.active_action.status]}</strong><p>{value.active_action.message}</p></div>{onOpenAction && <Button size="sm" variant="outline" onClick={() => onOpenAction(value.active_action!)}>查看结果<ChevronRight size={14}/></Button>}</div>}
      <p className="gpr-note">{value.image_delivery.notice} 图片投递设置作用于此连接所属老板账号。此检查只读取 CRM 当前状态，不会回复、发帖或创建排期。</p>
    </>}
  </section>;
}
