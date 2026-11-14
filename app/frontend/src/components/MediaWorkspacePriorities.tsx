import { AlertCircle, ArrowRight, CheckCircle2, Image } from 'lucide-react';
import { Button } from './ui/button';
import { mediaUtcToLocal } from '@/lib/media-operations-api';
import type { WorkspaceMerchant, WorkspaceProjection, WorkspaceQueueAction, WorkspaceStatusFilter } from '@/lib/media-workspace-api';

type Props = { data: WorkspaceProjection | null; isOwner: boolean; onFilter: (value: WorkspaceStatusFilter) => void; onView: (value: 'review' | 'reports') => void; onMerchant: (merchant: WorkspaceMerchant, action?: WorkspaceQueueAction) => void };
function workspacePriorityData(data: WorkspaceProjection | null) {
  if (!data) return null;
  const portfolio = data.portfolio, complete = data.sources_complete === true && portfolio?.sources_complete === true;
  const merchants = [...portfolio?.exceptions || []].sort((left, right) => {
    const score = (value: WorkspaceMerchant) => (value.issues || []).reduce((n, issue) => n + (issue.severity === 'high' ? 100 : issue.severity === 'medium' ? 10 : 1), 0);
    return score(right) - score(left) || left.id - right.id;
  }).slice(0, 4);
  return { complete, review: portfolio?.summary.review ?? null, attention: portfolio?.summary.attention ?? null, exceptions: data.summary.blocked + data.summary.unknown, merchants, matches: portfolio?.filtered_merchants, allMerchants: portfolio?.summary.merchants };
}
function workspacePriorityCount(value: number | null, complete: boolean): string { return value === null ? '待核对' : !complete && value === 0 ? '待核对' : `${value}${complete ? '' : '+'}`; }
export default function MediaWorkspacePriorities({ data, isOwner, onFilter, onView, onMerchant }: Props) {
  const value = workspacePriorityData(data);
  if (!value) return <p className="mwr-priority-unavailable" role="status"><AlertCircle size={16}/>当前待办尚未完整读取，请重新核对范围。</p>;
  const metrics = [
    { label: '待审核商家', count: value.review, unit: '家', open: () => onFilter('review') },
    { label: '需处理商家', count: value.attention, unit: '家', open: () => onFilter('attention'), attention: true },
    { label: '执行异常／待确认', count: value.exceptions, unit: '条', open: () => onView('reports'), attention: true },
  ];
  return <section className="mwr-priorities" aria-label={isOwner ? '老板优先待办' : '我的运营优先待办'}>
    <header>
      <h2>{isOwner ? '优先待办' : '我的运营待办'}</h2>
      <button type="button" onClick={() => onFilter('attention')}>查看运营清单<ArrowRight size={15}/></button>
    </header>
    {!value.complete && <p className="mwr-partial" role="status"><AlertCircle size={15}/>部分来源待核对，当前仅显示已读取的数量。</p>}
    <div className="mwr-priority-metrics">
      {metrics.map(({ label, count, unit, attention, open }) => (
        <button key={label} type="button" className={attention && count ? 'attention' : undefined} onClick={open}>
          <span>{label}</span>
          <strong>{workspacePriorityCount(count, value.complete)}{count !== null && (value.complete || count > 0) && <small>{unit}</small>}</strong>
        </button>
      ))}
    </div>
    <div className="mwr-priority-list">
      {value.merchants.length > 0 ? value.merchants.map(merchant => {
        const action = merchant.work_queue?.next_action;
        const allowed = action?.kind === 'monthly' && !isOwner ? undefined : action || undefined;
        const missing = merchant.work_queue?.checks.find(check => check.state === 'missing');
        return <article key={merchant.id}>
          <div>
            <button className="mwr-merchant-name" type="button" onClick={() => onMerchant(merchant)}>{merchant.name}</button>
            <p>
              {merchant.issues?.slice(0, 2).map(issue => <span key={issue.code} className={`mw-issue ${issue.severity}`}>{issue.label}</span>)}
              {missing && <span className="mw-issue medium">{missing.label}</span>}
            </p>
          </div>
          <span className="mwr-operator">{merchant.primary_operator_name || (merchant.assignment_state === 'unassigned' ? '主要运营待分配' : '按原协作范围处理')}</span>
          <Button variant="outline" onClick={() => onMerchant(merchant, allowed)}>{allowed?.kind === 'materials' ? '补齐素材' : '去处理'}<ArrowRight size={14}/></Button>
        </article>;
      }) : <div className="mwr-priority-empty">
        {value.complete ? <CheckCircle2 size={18}/> : <AlertCircle size={18}/>}
        <span>{value.complete ? '当前已保存记录中没有需优先处理的商家。' : '待办来源尚未完整，进入运营清单继续核对。'}</span>
        <button type="button" onClick={() => onFilter('all')}>查看商家<ArrowRight size={14}/></button>
      </div>}
    </div>
    <footer className="mwr-priority-tools">
      <button type="button" onClick={() => onFilter('all')}><Image size={15}/>逐家检查菜单与配图</button>
      <details>
        <summary>统计范围</summary>
        <p>待审核和需处理按授权商家计数。执行异常按当前筛选的记录条数统计。</p>
        {value.matches !== undefined && value.allMerchants !== undefined && <p>清单显示 {workspacePriorityCount(value.matches, value.complete)} / {workspacePriorityCount(value.allMerchants, value.complete)} 家。</p>}
        {data?.observed_at && <p>本地更新于 {mediaUtcToLocal(data.observed_at, 'Asia/Shanghai').replace('T', ' ')}（北京时间）。</p>}
      </details>
    </footer>
  </section>;
}
