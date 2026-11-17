import { useEffect, useRef, useState, type FormEvent } from 'react';
import { useQuery } from '@tanstack/react-query';
import { MoreHorizontal, Search } from 'lucide-react';
import { toast } from 'sonner';
import SalesWorkbenchDial from '@/components/SalesWorkbenchDial';
import { getCustomerDialValidation } from '@/lib/phone-dial';
import { Button } from '@/components/ui/button';
import {
  CrmFormDialogBody, CrmFormDialogContent, CrmFormDialogFooter, CrmFormDialogHeader,
  Dialog, DialogDescription, DialogTitle,
} from '@/components/ui/dialog';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { NativeSelect } from '@/components/ui/native-select';
import { Textarea } from '@/components/ui/textarea';
import { formatBusinessDateTimeInput, parseBusinessDateTimeInput } from '@/lib/business-date';
import { formatPhoneNumber } from '@/lib/phone-format';
import { salesHandoffError } from '@/lib/sales-deal-handoff';
import { invokeWithAuth } from '@/lib/tokenStore';
import { useUnsavedChanges } from '@/lib/use-unsaved-changes';
import './sales-closing-queue.css';

const stages = {
  pending: '待接手', working: '踢单中', won: '已成交', lost: '已结束',
} as const;
const filterStages = [
  { value: 'active', label: '待推进' }, { value: 'pending', label: stages.pending },
  { value: 'working', label: stages.working }, { value: 'won', label: stages.won },
  { value: 'lost', label: stages.lost }, { value: 'all', label: '全部阶段' },
];
type ClosingItem = {
  lead_id: number;
  business_name: string;
  phone?: string | null;
  country?: string | null;
  stage: keyof typeof stages;
  source_sales_name?: string | null;
  closer_id?: number | null;
  closer_name?: string | null;
  interest_note?: string | null;
  note?: string | null;
  next_follow_up_at?: string | null;
  revision: number;
  can_contact: boolean;
  contact_reason?: string | null;
};
type Queue = {
  items: ClosingItem[];
  total: number;
  sources: { id: number; name: string }[];
};
type Change = { action: 'claim' | 'follow_up' | 'lost' | 'take_over'; note?: string; next_follow_up_at?: string };
type Editor = { item: ClosingItem; action: 'follow_up' | 'lost' | 'take_over'; note: string; due: string };
const api = '/api/v1/sales-leads/closing-queue';
const pageSize = 20;

export default function SalesClosingQueue({ employeeId, isOwner, scope, refreshVersion, onOpenDossier, onOpenDeal }: {
  employeeId: number;
  isOwner: boolean;
  scope: string;
  refreshVersion: number;
  onOpenDossier: (leadId: number) => void;
  onOpenDeal: (leadId: number) => void;
}) {
  const [stage, setStage] = useState('active');
  const [source, setSource] = useState('');
  const [search, setSearch] = useState('');
  const [searchInput, setSearchInput] = useState('');
  const [page, setPage] = useState(1);
  const [editor, setEditor] = useState<Editor | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);
  const saving = useRef(false);
  const [editError, setEditError] = useState('');
  const [sources, setSources] = useState<Queue['sources']>([]);
  const guard = useUnsavedChanges(Boolean(editor && (editor.note.length || editor.due !== formatBusinessDateTimeInput(editor.item.next_follow_up_at))));
  const queue = useQuery({
    queryKey: ['sales-closing-queue', employeeId, scope, stage, source, search, page, refreshVersion],
    queryFn: async () => {
      const params = new URLSearchParams({ stage, page: String(page), page_size: String(pageSize) });
      if (source) params.set('source_sales_id', source);
      if (search) params.set('search', search);
      const response = await invokeWithAuth({ url: `${api}?${params}`, method: 'GET' });
      return response.data as Queue;
    },
    retry: false,
    gcTime: 0,
    refetchInterval: editor || busyId ? false : 30_000,
    refetchOnWindowFocus: !editor && !busyId,
  });
  const pages = Math.max(1, Math.ceil((queue.data?.total || 0) / pageSize));
  useEffect(() => {
    if (!queue.data || queue.isError) return;
    setSources(queue.data.sources);
    if (page > pages) setPage(pages);
  }, [queue.data, queue.isError, page, pages]);
  useEffect(() => {
    const value = searchInput.trim();
    if (value === search) return;
    const timer = window.setTimeout(() => { setSearch(value); setPage(1); }, 250);
    return () => window.clearTimeout(timer);
  }, [searchInput, search]);

  async function prepareDial(item: ClosingItem, phone: string) {
    const response = await invokeWithAuth({ url: `${api}/${item.lead_id}/dial-target?revision=${item.revision}`, method: 'GET' });
    const target = response.data;
    const confirmed = getCustomerDialValidation(target?.phone || '', target?.country).e164;
    if (target?.lead_id !== item.lead_id || target?.revision !== item.revision || confirmed !== phone) {
      throw new Error('商家或号码已变化，请刷新名单后重试');
    }
  }
  function openEditor(item: ClosingItem, action: Editor['action']) {
    setEditError('');
    setEditor({ item, action, note: '', due: formatBusinessDateTimeInput(item.next_follow_up_at) });
  }
  function closeEditor() {
    if (!saving.current && guard.confirmDiscard()) setEditor(null);
  }
  async function change(item: ClosingItem, update: Change) {
    if (saving.current) return;
    saving.current = true;
    setBusyId(item.lead_id);
    setEditError('');
    try {
      await invokeWithAuth({ url: `${api}/${item.lead_id}`, method: 'POST', data: { ...update, revision: item.revision } });
      guard.markSaved();
      setEditor(null);
      toast.success(update.action === 'claim' || update.action === 'take_over' ? '已接手这家商家' : update.action === 'lost' ? '已结束本次踢单' : '已保存踢单进展');
    } catch (problem) {
      const message = salesHandoffError(problem, '操作未完成，请核对最新状态后重试');
      if (update.action === 'claim') toast.error(message);
      else setEditError(message);
    } finally {
      // Re-read even after a network error: the server may already have committed.
      await queue.refetch();
      saving.current = false;
      setBusyId(null);
    }
  }
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!editor || !editor.note.trim() || saving.current) return;
    try {
      await change(editor.item, {
        action: editor.action,
        note: editor.note.trim(),
        ...(editor.action === 'follow_up' ? { next_follow_up_at: parseBusinessDateTimeInput(editor.due) } : {}),
      });
    } catch (problem) { setEditError(salesHandoffError(problem, '请核对填写内容')); }
  }
  const filtered = Boolean(source || search || stage !== 'active');
  const currentItem = editor && !queue.isError ? queue.data?.items.find(item => item.lead_id === editor.item.lead_id) : undefined;
  const canResumeEditor = !!editor && !!currentItem?.can_contact && currentItem.stage === 'working' &&
    (editor.action === 'take_over' ? isOwner && currentItem.closer_id !== employeeId : currentItem.closer_id === employeeId);
  const currentRevision = canResumeEditor && currentItem.revision === editor.item.revision;
  const staleEditor = editor && !currentRevision;
  const changingScope = searchInput.trim() !== search;
  return <section className="sales-closing-queue" aria-label="意向踢单名单">
    <div className="scq-controls">
      <div className="scq-search">
        <Search size={16} aria-hidden="true" />
        <Input type="search" aria-label="搜索踢单商家或电话" placeholder="搜索商家或电话" value={searchInput} maxLength={200} onChange={event => setSearchInput(event.target.value)} />
      </div>
      <NativeSelect aria-label="来源销售" value={source} options={[{ value: '', label: '全部来源销售' }, ...sources.map(item => ({ value: String(item.id), label: item.name }))]} onChange={value => { setSource(value); setPage(1); }}/>
      <NativeSelect aria-label="踢单阶段" value={stage} options={filterStages} onChange={value => { setStage(value); setPage(1); }}/>
    </div>
    <p className="scq-count" role="status">{scope}{queue.data && !queue.isError && !changingScope ? ` · ${queue.data.total} 家商家` : ''}</p>
    {queue.isError ? <div className="scq-message" role="alert">踢单名单暂时无法读取。<Button variant="outline" size="sm" onClick={() => void queue.refetch()}>重新加载</Button></div>
      : queue.isPending || changingScope ? <p className="scq-message" role="status">正在读取踢单名单…</p>
      : !queue.data.items.length ? <p className="scq-message">{filtered ? '当前筛选下没有商家。' : '暂无待推进的商家。销售保存「有意向」或「已预约」后会出现在这里。'}</p>
      : <ul className="scq-list">{queue.data.items.map(item => {
        const mine = item.stage === 'working' && item.closer_id === employeeId && item.can_contact;
        const active = item.stage === 'pending' || item.stage === 'working';
        const date = active ? formatBusinessDateTimeInput(item.next_follow_up_at) : '';
        const overdue = date && Date.parse(parseBusinessDateTimeInput(date)) < Date.now();
        return <li key={item.lead_id}>
          <div className="scq-identity">
            <button type="button" className="scq-merchant" onClick={() => onOpenDossier(item.lead_id)}>{item.business_name}</button>
            <span className="scq-state" data-stage={item.stage}>{stages[item.stage]}</span>
            <p className="scq-attribution">来源销售 {item.source_sales_name || '待确认'}{item.closer_name && <span>踢单人 {item.closer_name}</span>}</p>
            {item.phone && item.can_contact && <p className="scq-phone">{formatPhoneNumber(item.phone, item.country || undefined)}</p>}
          </div>
          <div className="scq-progress">
            {item.interest_note && <p><span>销售备注</span>{item.interest_note}</p>}
            {item.note && <p><span>{item.stage === 'lost' ? '结束原因' : '踢单进展'}</span>{item.note}</p>}
            {active && <p className={overdue ? 'scq-overdue' : ''}><span>下次跟进</span>{date ? `${overdue ? '逾期 · ' : ''}${date.replace('T', ' ')}（北京时间）` : '待安排'}</p>}
            {active && !item.can_contact && <p>{item.contact_reason || '已停止联系'}</p>}
          </div>
          <div className="scq-actions">
            {item.stage === 'pending' && item.can_contact && <Button type="button" size="sm" disabled={busyId !== null} onClick={() => void change(item, { action: 'claim' })}>我来接手</Button>}
            {isOwner && item.stage === 'working' && !mine && item.can_contact && <Button type="button" variant="outline" size="sm" disabled={busyId !== null} onClick={() => openEditor(item, 'take_over')}>接手踢单</Button>}
            {mine && <>
              <Button type="button" size="sm" disabled={busyId !== null} onClick={() => openEditor(item, 'follow_up')}>记录进展</Button>
              {item.phone && <SalesWorkbenchDial key={item.revision} phone={item.phone} country={item.country} disabled={busyId !== null} onPrepare={phone => prepareDial(item, phone)} onLaunched={() => {}}/>}
              <DropdownMenu>
                <DropdownMenuTrigger asChild><Button aria-label={`更多踢单操作：${item.business_name}`} type="button" size="sm" variant="ghost" disabled={busyId !== null}><MoreHorizontal size={16}/></Button></DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuItem onSelect={() => onOpenDeal(item.lead_id)}>登记成交</DropdownMenuItem>
                  <DropdownMenuItem onSelect={() => openEditor(item, 'lost')}>结束踢单</DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </>}
            {item.stage === 'won' && <Button type="button" size="sm" variant="outline" onClick={() => onOpenDeal(item.lead_id)}>查看成交</Button>}
          </div>
        </li>;
      })}</ul>}
    {queue.data && !queue.isError && pages > 1 && <nav className="scq-pagination" aria-label="踢单名单分页">
      <Button type="button" variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>上一页</Button>
      <span>{page} / {pages}</span>
      <Button type="button" variant="outline" size="sm" disabled={page >= pages} onClick={() => setPage(page + 1)}>下一页</Button>
    </nav>}
    <Dialog open={!!editor} onOpenChange={open => { if (!open) closeEditor(); }}>
      {editor && <CrmFormDialogContent className="max-w-lg" aria-describedby="scq-editor-context">
        <CrmFormDialogHeader>
          <DialogTitle>{editor.action === 'take_over' ? '接手踢单' : editor.action === 'lost' ? '结束踢单' : '记录踢单进展'}</DialogTitle>
          <DialogDescription id="scq-editor-context">{editor.item.business_name} · {editor.action === 'take_over' && editor.item.closer_name && `当前踢单人 ${editor.item.closer_name} · `}来源销售 {editor.item.source_sales_name || '待确认'}</DialogDescription>
        </CrmFormDialogHeader>
        <CrmFormDialogBody>
          <form id="scq-editor" onSubmit={submit} className="scq-form">
            <Label htmlFor="scq-note">{editor.action === 'take_over' ? '接手原因' : editor.action === 'lost' ? '结束原因' : '本次进展与下一步'}</Label>
            <Textarea id="scq-note" required maxLength={2000} value={editor.note} disabled={busyId !== null} onChange={event => setEditor({ ...editor, note: event.target.value })}/>
            {editor.action === 'follow_up' && <>
              <Label htmlFor="scq-next">下次跟进时间（北京时间）</Label>
              <Input id="scq-next" type="datetime-local" required value={editor.due} disabled={busyId !== null} onChange={event => setEditor({ ...editor, due: event.target.value })}/>
            </>}
            {editError && <p role="alert">{editError}</p>}
            {staleEditor && <div role="status">这条记录的状态已变化。{canResumeEditor && currentItem
              ? <Button type="button" variant="outline" size="sm" onClick={() => { setEditor({ ...editor, item: currentItem }); setEditError(''); }}>使用最新记录继续</Button>
              : '请返回名单核对。'}</div>}
          </form>
        </CrmFormDialogBody>
        <CrmFormDialogFooter>
          <Button type="button" variant="outline" disabled={busyId !== null} onClick={closeEditor}>取消</Button>
          <Button type="submit" form="scq-editor" disabled={busyId !== null || !currentRevision || !editor.note.trim() || (editor.action === 'follow_up' && !editor.due)}>{busyId !== null ? '保存中…' : editor.action === 'take_over' ? '确认接手' : editor.action === 'lost' ? '确认结束' : '保存进展'}</Button>
        </CrmFormDialogFooter>
      </CrmFormDialogContent>}
    </Dialog>
  </section>;
}
