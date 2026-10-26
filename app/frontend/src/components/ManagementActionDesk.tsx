import { useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { ArrowRight, CheckCircle2, Search } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { CrmFormDialogBody, CrmFormDialogContent, CrmFormDialogFooter, CrmFormDialogHeader, Dialog, DialogTitle } from '@/components/ui/dialog';
import { buildReturnLink } from '@/lib/navigation-state';

type Issue = {
  id: number; customer_id: number; customer_name: string; message: string; status: string;
  severity: string; category: string; suggested_action?: string; last_detected_at: string;
  resolution_note?: string;
  task?: { id: number; status: string; assignee_name?: string; due_date?: string; completion_result?: string };
};
type Review = {
  customer_id: number; customer_name: string; review_status: string; reviewed_at?: string;
  warnings: Array<{ code: string; message: string; scope: string; source_id?: number }>;
  suggestions: Array<{ business_line: string; product_name: string; basis: string[] }>;
};
type Signal = { code: string; severity: string; category?: string; customer_id: number; customer_name: string; project_id?: number; message: string; suggested_action?: string };
type Row<T> = { key: string; customerId: number; name: string; reason: string; owner: string; status: string; source: string; evidence: string[]; issue?: Issue; review?: T; task?: Issue['task']; relatedIssues?: Issue[] };
type InboxTab = 'tasks' | 'history' | 'issues' | 'signals';

export function managementSourceTime(value?: string) {
  if (!value) return '更新时间待确认';
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return '更新时间待确认';
  return date.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false });
}

export default function ManagementActionDesk<T extends Review>({ automation, items, anomalies, riskCount, warningCount, loadedAt, loading, isAdmin, isMobile, returnPath, onReview, onCreateTask, onHistory, onQuality }: {
  automation: { items: Issue[]; last_run?: { completed_at?: string; status: string } } | null;
  items: T[]; anomalies: Signal[]; riskCount: number; warningCount: number;
  loadedAt: string; loading: boolean; isAdmin: boolean; isMobile: boolean; returnPath: string;
  onReview: (item: T) => void; onCreateTask: (id: number) => Promise<void>; onHistory: () => void; onQuality: () => void;
}) {
  const [params, setParams] = useSearchParams();
  const requestedTab = params.get('inbox') || 'tasks';
  const tab: InboxTab = ['tasks', 'history', 'issues', 'signals'].includes(requestedTab) ? requestedTab as InboxTab : 'tasks';
  const query = params.get('inboxSearch') || '';
  const selectedKey = params.get('inboxItem');
  const setSelectedKey = (key: string | null) => { const next = new URLSearchParams(params); if (key) next.set('inboxItem', key); else next.delete('inboxItem'); setParams(next, { replace: true }); };
  const setQuery = (value: string) => { const next = new URLSearchParams(params); if (value) next.set('inboxSearch', value); else next.delete('inboxSearch'); next.delete('inboxItem'); setParams(next, { replace: true }); };
  const setTab = (value: InboxTab) => { const next = new URLSearchParams(params); next.set('inbox', value); next.delete('inboxSearch'); next.delete('inboxItem'); setParams(next, { replace: true }); };
  const [creating, setCreating] = useState(false);
  const activeIssues = (automation?.items || []).filter(item => item.status !== 'resolved');
  const pendingHistory = items.filter(item => ['pending', 'needs_follow_up'].includes(item.review_status));
  const taskGroups = new Map<number, Issue[]>();
  activeIssues.forEach(item => { if (item.task) taskGroups.set(item.task.id, [...(taskGroups.get(item.task.id) || []), item]); });
  const untaskedIssues = activeIssues.filter(item => !item.task);
  const scanAt = automation?.last_run?.completed_at;
  const scanDate = scanAt ? new Date(scanAt).getTime() : NaN;
  const scanStale = !Number.isFinite(scanDate) || Date.now() - scanDate > 48 * 60 * 60 * 1000 || automation?.last_run?.status !== 'completed';
  const rowSets: Record<InboxTab, Row<T>[]> = {
    tasks: Array.from(taskGroups.values()).map(group => {
      const issue = group[0];
      return { key: `task-${issue.task!.id}`, customerId: issue.customer_id, name: issue.customer_name,
        reason: group.map(row => row.message).join('；'), owner: issue.task!.assignee_name || '负责人待确认',
        status: issue.task!.status === 'completed' ? '任务已完成 · 问题待复核' : issue.task!.status === 'cancelled' ? '任务已取消 · 问题待复核' : issue.task!.status === 'in_progress' ? '处理中' : '待跟进',
        source: `已有任务 #${issue.task!.id}`, evidence: group.map(row => row.message), task: issue.task, issue, relatedIssues: group };
    }),
    issues: untaskedIssues.map(issue => ({ key: `issue-${issue.id}`, customerId: issue.customer_id, name: issue.customer_name,
      reason: issue.message, owner: '尚无任务', status: issue.severity === 'high' ? '高优先' : '待处理', source: `扫描问题 #${issue.id}`, evidence: [issue.message], issue })),
    history: pendingHistory.map(item => ({ key: `history-${item.customer_id}`, customerId: item.customer_id, name: item.customer_name,
      reason: item.warnings[0]?.message || item.suggestions.map(suggestion => suggestion.product_name).join(' / ') || '核对业务分类与首次有效收款',
      owner: '管理员核对', status: item.review_status === 'needs_follow_up' ? '稍后核对' : '待补录', source: '历史分类审核',
      evidence: [...item.warnings.map(row => row.message), ...item.suggestions.flatMap(row => row.basis)], review: item })),
    signals: [
      ...anomalies.map((signal, index) => ({ key: `signal-${signal.customer_id}-${signal.project_id || ''}-${signal.code}-${index}`, customerId: signal.customer_id, name: signal.customer_name,
        reason: signal.message, owner: signal.project_id ? `项目 #${signal.project_id}` : '客户层面', status: signal.severity === 'high' ? '高优先' : '提醒',
        source: signal.category === 'risk' ? '实时风险提醒' : '实时检查', evidence: [signal.message, ...(signal.suggested_action ? [`建议：${signal.suggested_action}`] : [])] })),
      ...items.filter(item => item.warnings.length > 0).map(item => ({ key: `classification-${item.customer_id}`, customerId: item.customer_id, name: item.customer_name,
        reason: item.warnings.map(row => row.message).join('；'), owner: `${item.warnings.length} 条提示`, status: '待核对依据',
        source: '分类提示', evidence: item.warnings.map(row => `${row.message}${row.source_id ? `（${row.scope} #${row.source_id}）` : ''}`), review: item })),
    ],
  };
  const rows = rowSets[tab].filter(row => !query.trim() || [row.name, row.reason, row.owner].join(' ').toLowerCase().includes(query.trim().toLowerCase()));
  const selected = rows.find(row => row.key === selectedKey);
  const selectedIndex = selected ? rows.indexOf(selected) : -1;
  const nextRow = selectedIndex >= 0 ? rows[selectedIndex + 1] : undefined;


  return <section className="mgt-action-desk" aria-label="经营待处理">
    <div className="mgt-board">
      <div className="mgt-board-head">
        <div className="mgt-inbox-tabs" aria-label="待处理来源">
          {([
            ['tasks', '已有任务', taskGroups.size], ['history', '历史补录', pendingHistory.length],
            ...(untaskedIssues.length ? [['issues', '待分配问题', untaskedIssues.length]] : []), ['signals', '其他信号', null],
          ] as Array<[InboxTab, string, number | null]>).map(([value, label, count]) => <button key={value} type="button" aria-pressed={tab === value} onClick={() => setTab(value)}>{label}{count !== null && <span>{!loadedAt ? '—' : count}</span>}</button>)}
        </div>
        <div className="mgt-search"><Search size={15} /><Input aria-label="搜索待处理客户或问题" placeholder="搜索客户或问题" value={query} onChange={event => setQuery(event.target.value)} /></div>
      </div>
      <div className="mgt-source-note">
        {['tasks', 'issues'].includes(tab) ? <><span>任务扫描：{managementSourceTime(scanAt)}</span>{scanStale && <span className="mgt-warning">状态需复核</span>}</> : <span>分类与风险读取：{managementSourceTime(loadedAt)}</span>}
        {tab === 'signals' && <span>风险 {loadedAt ? riskCount : '—'} 条 · 分类提示 {loadedAt ? warningCount : '—'} 条；同一客户可能有多条提示</span>}
        {tab === 'history' && <span>按客户计数 · 新客户从客户管理录入</span>}
      </div>
      {loading && !loadedAt ? <p className="mgt-empty" role="status">正在读取待处理事项…</p> : rows.map(row => <article key={row.key} className="mgt-action-row">
        <div className="mgt-row-main"><h3>{row.name}</h3><p>{row.reason}</p></div>
        <span className="mgt-row-owner">{row.owner}</span><span className="mgt-row-status">{row.status}</span>
        <Button size="sm" variant="outline" onClick={() => setSelectedKey(row.key)}>{row.review ? '核对' : '跟进'}<ArrowRight className="ml-1 h-3.5 w-3.5" /></Button>
      </article>)}
      {!loading && rows.length === 0 && <div className="mgt-empty"><CheckCircle2 size={19} />{!loadedAt ? '资料尚未读取成功，请刷新后重试' : query ? '没有匹配的客户或问题' : tab === 'tasks' ? '当前没有关联任务的待处理问题' : '当前来源没有待处理事项'}</div>}
      <div className="mgt-board-footer"><span>{loadedAt ? rows.length : '—'} {tab === 'tasks' ? '个任务' : tab === 'history' ? '位客户' : '组事项'}</span>{!isMobile && <Button size="sm" variant="ghost" onClick={tab === 'history' ? onHistory : onQuality}>{tab === 'history' ? '查看全部历史记录' : '查看扫描与处理记录'}</Button>}</div>
    </div>
    <Dialog open={Boolean(selected)} onOpenChange={open => { if (!open) setSelectedKey(null); }}>
      <CrmFormDialogContent className="mgt-action-detail sm:max-w-xl"><CrmFormDialogHeader><p className="mgt-detail-kicker">{selected?.source}</p><DialogTitle>{selected?.name}</DialogTitle></CrmFormDialogHeader>{selected && <><CrmFormDialogBody>
          <div className="mgt-detail-status"><span>{selected.status}</span><span>{selected.owner}</span></div>
          <div className="mgt-detail-evidence"><h4>处理依据</h4><ul>{selected.evidence.map((text, index) => <li key={index}>{text}</li>)}</ul></div>
          {selected.issue && <p className="mgt-source-note">最后检测：{managementSourceTime(selected.issue.last_detected_at)}{scanStale ? ' · 请先复核当前状态' : ''}</p>}
          {selected.issue?.suggested_action && <p className="mgt-next-action">下一步：{selected.issue.suggested_action}</p>}
          {!selected.issue && !selected.review && <p className="mgt-next-action">下一步：打开客户档案核对提示所指的项目、收款或服务状态；核对后刷新本页确认提醒是否消除。</p>}
          {selected.task && <p className="mgt-next-action">继续处理原任务 #{selected.task.id}，已有任务不会重复创建。</p>}
          {selected.review && <p className="mgt-next-action">先核对项目、首款和关联来源，保存前可查看具体影响。</p>}
          {isMobile && (selected.review || !selected.task) && <p className="mgt-source-note">手机可查看依据；分类写入与任务生成请在电脑端处理。</p>}
          </CrmFormDialogBody><CrmFormDialogFooter className="mgt-detail-actions">
            {selected.task ? <Button asChild><Link to={buildReturnLink(`/tasks?task_id=${selected.task.id}&view=system`, returnPath, 'management-decisions')}>查看已有任务</Link></Button> : selected.review ? <Button disabled={!isAdmin || isMobile} onClick={() => { const item = selected.review!; setSelectedKey(null); onReview(item); }}>核对分类与项目</Button> : selected.issue && !isMobile ? <Button disabled={!isAdmin || creating} onClick={async () => { setCreating(true); try { await onCreateTask(selected.issue!.id); } finally { setCreating(false); setSelectedKey(null); } }}>{creating ? '生成中…' : '生成处理任务'}</Button> : null}
            <Button asChild variant="outline"><Link to={buildReturnLink(`/customers?detail=${selected.customerId}`, returnPath, 'management-decisions')}>客户档案</Link></Button>
            <Button variant="ghost" disabled={!nextRow} onClick={() => setSelectedKey(nextRow!.key)}>下一项<ArrowRight className="ml-1 h-3.5 w-3.5" /></Button>
          </CrmFormDialogFooter></>}</CrmFormDialogContent>
    </Dialog>
  </section>;
}
