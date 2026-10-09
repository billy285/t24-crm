import { useMemo, useRef, useState } from 'react';
import { Check, ChevronDown, ListFilter, Search } from 'lucide-react';
import { formatPhoneNumber, phoneSearchMatches } from '@/lib/phone-format';
import { readSalesWorkspaceQueueQuery, writeSalesWorkspaceQueueQuery, type SalesWorkspaceQueueScope } from '@/lib/sales-workspace-view-state';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle, SheetTrigger } from '@/components/ui/sheet';

type QueueTask = {
  task_id: number;
  task_status: string;
  lead: { id: number; business_name: string; phone: string; country?: string; city?: string; state?: string };
};
type Props = {
  tasks: QueueTask[];
  selectedTaskId?: number;
  filter: string;
  overdueCount: number;
  disabled: boolean;
  onFilterChange: (value: 'all' | 'unfinished' | 'overdue') => void;
  onSelect: (taskId: number) => void;
  workspaceScope?: SalesWorkspaceQueueScope;
  businessDay?: string;
};

export default function MobileSalesQueue({ tasks, selectedTaskId, filter, overdueCount, disabled, onFilterChange, onSelect, workspaceScope, businessDay = '' }: Props) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState(() => workspaceScope ? readSalesWorkspaceQueueQuery(workspaceScope, businessDay) : '');
  const updateQuery = (value: string) => {
    setQuery(value);
    if (workspaceScope) writeSalesWorkspaceQueueQuery(workspaceScope, businessDay, value);
  };
  const titleRef = useRef<HTMLHeadingElement>(null);
  const position = tasks.findIndex(task => task.task_id === selectedTaskId) + 1;
  const matches = useMemo(() => {
    const search = query.trim().toLocaleLowerCase();
    return !search ? tasks : tasks.filter(task =>
      [task.lead.business_name, task.lead.city, task.lead.state].filter(Boolean).join(' ').toLocaleLowerCase().includes(search)
      || phoneSearchMatches(task.lead.phone, query, task.lead.country));
  }, [query, tasks]);
  const filterLabel = ({ all: '全部', unfinished: '未完成', overdue: '逾期', callback: '待回访', interested: '有意向', appointment: '已预约' } as Record<string, string>)[filter] || '全部';

  return <Sheet open={open} onOpenChange={setOpen}>
    <SheetTrigger asChild><Button variant="outline" className="sw-phone-queue-trigger" disabled={disabled} aria-label="打开客户队列" data-selected-task-id={selectedTaskId || ''}><ListFilter size={17} /><span>客户队列</span><span className="sw-queue-position">{filterLabel} · {position || '—'} / {tasks.length}</span><ChevronDown size={16} /></Button></SheetTrigger>
    <SheetContent side="bottom" className="sales-center-ui sw-mobile-sheet sw-queue-sheet" onOpenAutoFocus={event => { event.preventDefault(); titleRef.current?.focus(); }}>
      <SheetHeader><SheetTitle ref={titleRef} tabIndex={-1}>客户队列</SheetTitle><SheetDescription className="sr-only">搜索姓名、电话或城市，选择客户不会保存或完成任务。</SheetDescription></SheetHeader>
      <div className="sw-queue-search"><Search size={17} aria-hidden="true" /><Input aria-label="搜索客户队列" placeholder="搜索客户、电话或城市" maxLength={200} className={query ? 'pr-16' : undefined} value={query} onChange={event => updateQuery(event.target.value)} />{query ? <Button type="button" variant="ghost" className="absolute inset-y-0 right-0 min-h-11 min-w-11 px-3" aria-label="清空队列搜索" onClick={() => updateQuery('')}>清空</Button> : null}</div>
      <nav className="sw-phone-queue-filters" aria-label="客户队列状态">{[{ value: 'all' as const, label: '全部' }, { value: 'unfinished' as const, label: '未完成' }, { value: 'overdue' as const, label: `逾期 ${overdueCount}` }].map(item => <button key={item.value} type="button" disabled={disabled} aria-pressed={filter === item.value} onClick={() => onFilterChange(item.value)}>{item.label}</button>)}</nav>
      <div className="sw-phone-queue-list" aria-label="可选客户">{matches.map(task => <button key={task.task_id} type="button" data-task-id={task.task_id} data-lead-id={task.lead.id} disabled={disabled} aria-pressed={selectedTaskId === task.task_id} onClick={() => { onSelect(task.task_id); setOpen(false); }}><span><strong>{task.lead.business_name}</strong><small>{[task.lead.city || task.lead.state, formatPhoneNumber(task.lead.phone, task.lead.country)].filter(Boolean).join(' · ')}</small></span>{selectedTaskId === task.task_id ? <Check size={18} aria-label="当前客户" /> : task.task_status === 'completed' ? <small>已记录</small> : null}</button>)}{!matches.length && <p className="sw-queue-empty">{query.trim() ? '没有匹配的客户' : '当前筛选暂无任务'}</p>}</div>
      <span className="sw-queue-total">共 {matches.length} 位</span>
    </SheetContent>
  </Sheet>;
}
