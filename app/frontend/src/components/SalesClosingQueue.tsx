import { useEffect, useRef, useState, type FormEvent } from 'react';
import { useQuery } from '@tanstack/react-query';
import { MoreHorizontal, Search } from 'lucide-react';
import { toast } from 'sonner';
import SalesWorkbenchDial from '@/components/SalesWorkbenchDial';
import SalesLeadMarkers from '@/components/SalesLeadMarkers';
import { SalesLabelBadges, SalesLabelEditor, SalesLabelFilter } from '@/components/SalesLabels';
import { useSalesLabels, type SalesLabel } from '@/lib/sales-labels';
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
  pending: '待接手', working: '踢单中', nurturing: '暂缓跟进', won: '已成交', lost: '已结束',
} as const;
const filterStages = [
  { value: 'active', label: '待推进' }, { value: 'pending', label: stages.pending },
  { value: 'today', label: '今日跟进' }, { value: 'overdue', label: '已逾期' },
  { value: 'working', label: stages.working }, { value: 'nurturing', label: stages.nurturing },
  { value: 'won', label: stages.won },
  { value: 'lost', label: stages.lost }, { value: 'all', label: '全部阶段' },
];
const reasons = {
  price: '价格或预算', product_fit: '功能不符', renewed_provider: '续签其他服务商',
  not_interested: '明确无意向', no_response: '多次未联系上', do_not_contact: '明确要求不再联系', other: '其他',
} as const;
type LossReason = keyof typeof reasons;
const editorCopy = {
  follow_up: { title: '记录踢单进展', note: '本次进展与下一步', date: '下次跟进时间（北京时间）', submit: '保存进展' },
  pause: { title: '暂缓跟进', note: '暂缓原因与下次联系计划', date: '重新提醒时间（北京时间）', submit: '暂缓并设置提醒' },
  lost: { title: '结束踢单', note: '结束说明', date: '', submit: '确认结束' },
  take_over: { title: '接手踢单', note: '接手原因', date: '', submit: '确认接手' },
  delegate: { title: '转给主管跟进', note: '交接说明', date: '', submit: '确认转交' },
} as const;
const successCopy = {
  claim: '已接手这家商家', take_over: '已接手这家商家', follow_up: '已保存踢单进展',
  delegate: '已转给主管，保留当前跟进安排',
  pause: '已暂缓跟进，到期会出现在跟进列表', resume: '已恢复跟进', lost: '已结束本次踢单',
} as const;
type ClosingItem = {
  lead_id: number;
  business_name: string;
  phone?: string | null;
  starred?: boolean;
  priority?: boolean;
  sales_labels?: SalesLabel[];
  country?: string | null;
  stage: keyof typeof stages;
  source_sales_name?: string | null;
  closer_id?: number | null;
  closer_name?: string | null;
  interest_note?: string | null;
  note?: string | null;
  handoff_note?: string | null;
  loss_reason?: LossReason | null;
  next_follow_up_at?: string | null;
  revision: number;
  can_contact: boolean;
  contact_reason?: string | null;
};
type Queue = {
  items: ClosingItem[];
  total: number;
  sources: { id: number; name: string }[];
  attention?: Record<string, number>;
};
type Change = { action: keyof typeof successCopy; note?: string; next_follow_up_at?: string; loss_reason?: LossReason; manager_id?: number };
type Editor = { item: ClosingItem; action: keyof typeof editorCopy; note: string; due: string;
  lossReason: LossReason | ''; manager: string };
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
  const [industry, setIndustry] = useState('');
  const [label, setLabel] = useState('');
  const [providerConfirmed, setProviderConfirmed] = useState(false);
  const [onlyMine, setOnlyMine] = useState(false);
  const [starred, setStarred] = useState(false);
  const [priority, setPriority] = useState(false);
  const [search, setSearch] = useState('');
  const [searchInput, setSearchInput] = useState('');
  const [page, setPage] = useState(1);
  const [editor, setEditor] = useState<Editor | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);
  const saving = useRef(false);
  const [editError, setEditError] = useState('');
  const [sources, setSources] = useState<Queue['sources']>([]);
  const [labelEditor, setLabelEditor] = useState<number | null>(null);
  const labels = useSalesLabels().data || [];
  const canConfirmProvider = labels.some(item => String(item.id) === label && item.kind === 'provider');
  const confirmedFilter = canConfirmProvider && providerConfirmed;
  const guard = useUnsavedChanges(Boolean(editor && (editor.note.length || editor.lossReason || editor.manager || editor.due !== formatBusinessDateTimeInput(editor.item.next_follow_up_at))));
  const delegationTarget = isOwner && editor?.action === 'delegate' ? editor.item : null;
  const managers = useQuery({
    queryKey: ['sales-closing-managers', employeeId, delegationTarget?.lead_id, delegationTarget?.revision],
    enabled: !!delegationTarget,
    gcTime: 0,
    retry: false,
    queryFn: async () => (await invokeWithAuth({
      url: `${api}/${delegationTarget?.lead_id}/managers`, method: 'GET',
    })).data as {id: number; name: string}[],
  });
  const queue = useQuery({
    queryKey: ['sales-closing-queue', employeeId, scope, stage, source, industry, label,
      confirmedFilter, onlyMine, starred, priority, search, page, refreshVersion],
    queryFn: async () => {
      const params = new URLSearchParams({ stage, page: String(page), page_size: String(pageSize) });
      if (source) params.set('source_sales_id', source);
      if (industry) params.set('industry', industry);
      if (label) params.set('label_id', label);
      if (confirmedFilter) params.set('provider_confirmed', 'true');
      if (onlyMine) params.set('mine', 'true');
      if (starred) params.set('starred', 'true');
      if (priority) params.set('priority', 'true');
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
    setEditor({ item, action, note: '', due: formatBusinessDateTimeInput(item.next_follow_up_at), lossReason: '', manager: '' });
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
      toast.success(successCopy[update.action]);
    } catch (problem) {
      const message = salesHandoffError(problem, '操作未完成，请核对最新状态后重试');
      if (update.action === 'claim' || update.action === 'resume') toast.error(message);
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
    if (editor.action === 'delegate' && !managers.data?.some(manager => String(manager.id) === editor.manager)) return;
    try {
      await change(editor.item, {
        action: editor.action,
        note: editor.note.trim(),
        ...(editorCopy[editor.action].date ? { next_follow_up_at: parseBusinessDateTimeInput(editor.due) } : {}),
        ...(editor.lossReason ? { loss_reason: editor.lossReason } : {}),
        ...(editor.manager ? { manager_id: Number(editor.manager) } : {}),
      });
    } catch (problem) { setEditError(salesHandoffError(problem, '请核对填写内容')); }
  }
  const filtered = Boolean(source || industry || label || onlyMine || starred || priority || search || stage !== 'active');
  const currentItem = editor && !queue.isError ? queue.data?.items.find(item => item.lead_id === editor.item.lead_id) : undefined;
  const canResumeEditor = !!editor && !!currentItem?.can_contact &&
    (currentItem.stage === 'working' || (currentItem.stage === 'nurturing' && ['take_over', 'delegate', 'lost'].includes(editor.action))) &&
    (editor.action === 'delegate' ? isOwner : editor.action === 'take_over' ?
      isOwner && currentItem.closer_id !== employeeId : currentItem.closer_id === employeeId);
  const currentRevision = canResumeEditor && currentItem.revision === editor.item.revision;
  const staleEditor = editor && !currentRevision;
  const changingScope = searchInput.trim() !== search;
  const copy = editor ? editorCopy[editor.action] : null;
  function selectStage(value: string) {
    setStage(value);
    setPage(1);
  }
  return <section className="sales-closing-queue" aria-label="意向踢单名单">
    <div className="scq-fast-filters" role="group" aria-label="跟进快捷筛选">
      {filterStages.slice(0, 4).map(option => <Button key={option.value} type="button" size="sm"
        variant={stage === option.value ? 'default' : 'outline'} aria-pressed={stage === option.value}
        onClick={() => selectStage(option.value)}>{option.label}
        {!!queue.data?.attention?.[option.value] && <span aria-label={`${queue.data.attention[option.value]} 家`}>
          {queue.data.attention[option.value]}
        </span>}
      </Button>)}
    </div>
    <div className="scq-controls">
      <div className="scq-search">
        <Search size={16} aria-hidden="true" />
        <Input type="search" aria-label="搜索踢单商家或电话" placeholder="搜索商家或电话" value={searchInput} maxLength={200} onChange={event => setSearchInput(event.target.value)} />
      </div>
      <NativeSelect aria-label="来源销售" value={source} options={[{ value: '', label: '全部来源销售' }, ...sources.map(item => ({ value: String(item.id), label: item.name }))]} onChange={value => { setSource(value); setPage(1); }}/>
      <NativeSelect aria-label="踢单阶段" value={stage} options={filterStages} onChange={selectStage}/>
    </div>
    <div className="scq-filter-panel">
      <Button type="button" size="sm" variant={starred ? 'default' : 'outline'} aria-pressed={starred}
        onClick={() => { setStarred(!starred); setPage(1); }}>只看星标</Button>
      <Button type="button" size="sm" variant={onlyMine ? 'default' : 'outline'} aria-pressed={onlyMine}
        onClick={() => { setOnlyMine(!onlyMine); setPage(1); }}>我的跟进</Button>
      <details>
        <summary>{industry || label || priority ? '更多筛选 · 已启用' : '更多筛选'}</summary>
        <div className="scq-extra-filters">
          <NativeSelect aria-label="筛选行业" value={industry} options={[
            { value: '', label: '全部行业' }, { value: '餐厅', label: '餐厅' }, { value: '美业', label: '美业' },
          ]} onChange={value => { setIndustry(value); setPage(1); }}/>
          <SalesLabelFilter value={label} labels={labels} onChange={value => { setLabel(value); setProviderConfirmed(false); setPage(1); }}/>
          {canConfirmProvider && <label><input type="checkbox" checked={providerConfirmed}
            onChange={event => { setProviderConfirmed(event.target.checked); setPage(1); }}/> 只看已确认在用</label>}
          <label><input type="checkbox" checked={priority} onChange={event => { setPriority(event.target.checked); setPage(1); }}/> 只看团队重点</label>
        </div>
      </details>
    </div>
    <p className="scq-count" role="status">{scope}{queue.data && !queue.isError && !changingScope ? ` · ${queue.data.total} 家商家` : ''}</p>
    {queue.isError ? <div className="scq-message" role="alert">踢单名单暂时无法读取。<Button variant="outline" size="sm" onClick={() => void queue.refetch()}>重新加载</Button></div>
      : queue.isPending || changingScope ? <p className="scq-message" role="status">正在读取踢单名单…</p>
      : !queue.data.items.length ? <p className="scq-message">{filtered ? '当前筛选下没有商家。' : '暂无待推进的商家。销售保存「有意向」或「已预约」后会出现在这里。'}</p>
      : <ul className="scq-list">{queue.data.items.map(item => {
        const active = ['pending', 'working', 'nurturing'].includes(item.stage);
        const ownedByMe = item.closer_id === employeeId && item.can_contact;
        const mine = item.stage === 'working' && ownedByMe;
        const deferred = item.stage === 'nurturing';
        const date = active ? formatBusinessDateTimeInput(item.next_follow_up_at) : '';
        const overdue = date && Date.parse(parseBusinessDateTimeInput(date)) < Date.now();
        return <li key={item.lead_id}>
          <div className="scq-identity">
            <button type="button" className="scq-merchant" onClick={() => onOpenDossier(item.lead_id)}>{item.business_name}</button>
            <span className="scq-state" data-stage={item.stage}>{stages[item.stage]}</span>
            <SalesLeadMarkers leadId={item.lead_id} starred={item.starred} priority={item.priority} canManage
              onChanged={() => void queue.refetch()}/>
            <p className="scq-attribution">来源销售 {item.source_sales_name || '待确认'}{item.closer_name && <span>踢单人 {item.closer_name}</span>}</p>
            {item.phone && item.can_contact && <p className="scq-phone">{formatPhoneNumber(item.phone, item.country || undefined)}</p>}
            <SalesLabelBadges labels={item.sales_labels || []}/>
          </div>
          <div className="scq-progress">
            {item.interest_note && <p><span>销售备注</span>{item.interest_note}</p>}
            {item.handoff_note && <p><span>交接说明</span>{item.handoff_note}</p>}
            {item.loss_reason && <p><span>未成交原因</span>{reasons[item.loss_reason]}</p>}
            {item.note && <p><span>{item.stage === 'lost' ? '结束说明' : deferred ? '暂缓计划' : '踢单进展'}</span>{item.note}</p>}
            {active && <p className={overdue ? 'scq-overdue' : ''}><span>{deferred ? '重新提醒' : '下次跟进'}</span>{date ? `${overdue ? '逾期 · ' : ''}${date.replace('T', ' ')}（北京时间）` : '待安排'}</p>}
            {active && !item.can_contact && <p>{item.contact_reason || '已停止联系'}</p>}
          </div>
          <div className="scq-actions">
            {item.stage === 'pending' && item.can_contact && <Button type="button" size="sm" disabled={busyId !== null} onClick={() => void change(item, { action: 'claim' })}>{isOwner ? '我来跟进' : '我来接手'}</Button>}
            {isOwner && (item.stage === 'working' || deferred) && !ownedByMe && item.can_contact && <Button type="button" variant="outline" size="sm" disabled={busyId !== null} onClick={() => openEditor(item, 'take_over')}>接手踢单</Button>}
            {deferred && ownedByMe && <Button type="button" size="sm" disabled={busyId !== null}
              onClick={() => void change(item, { action: 'resume' })}>恢复跟进</Button>}
            {mine && <>
              <Button type="button" size="sm" disabled={busyId !== null} onClick={() => openEditor(item, 'follow_up')}>记录进展</Button>
              {item.phone && <SalesWorkbenchDial key={item.revision} phone={item.phone} country={item.country} disabled={busyId !== null} onPrepare={phone => prepareDial(item, phone)} onLaunched={() => {}}/>}
            </>}
            <DropdownMenu>
              <DropdownMenuTrigger asChild><Button aria-label={`更多踢单操作：${item.business_name}`} type="button" size="sm" variant="ghost" disabled={busyId !== null}><MoreHorizontal size={16}/></Button></DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem onSelect={() => onOpenDossier(item.lead_id)}>查看档案和历史</DropdownMenuItem>
                <DropdownMenuItem onSelect={() => setLabelEditor(item.lead_id)}>编辑标签</DropdownMenuItem>
                {isOwner && item.can_contact && (item.stage === 'working' || deferred) &&
                  <DropdownMenuItem onSelect={() => openEditor(item, 'delegate')}>转给主管跟进</DropdownMenuItem>}
                {mine && <DropdownMenuItem onSelect={() => onOpenDeal(item.lead_id)}>登记成交</DropdownMenuItem>}
                {mine && <DropdownMenuItem onSelect={() => openEditor(item, 'pause')}>暂缓跟进</DropdownMenuItem>}
                {(mine || (deferred && ownedByMe)) && <DropdownMenuItem onSelect={() => openEditor(item, 'lost')}>结束踢单</DropdownMenuItem>}
              </DropdownMenuContent>
            </DropdownMenu>
            {item.stage === 'won' && <Button type="button" size="sm" variant="outline" onClick={() => onOpenDeal(item.lead_id)}>查看成交</Button>}
          </div>
        </li>;
      })}</ul>}
    {queue.data && !queue.isError && pages > 1 && <nav className="scq-pagination" aria-label="踢单名单分页">
      <Button type="button" variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>上一页</Button>
      <span>{page} / {pages}</span>
      <Button type="button" variant="outline" size="sm" disabled={page >= pages} onClick={() => setPage(page + 1)}>下一页</Button>
    </nav>}
    {labelEditor !== null && <SalesLabelEditor leadId={labelEditor} onSaved={() => void queue.refetch()}
      onClose={() => setLabelEditor(null)}/>}
    <Dialog open={!!editor} onOpenChange={open => { if (!open) closeEditor(); }}>
      {editor && copy && <CrmFormDialogContent className="max-w-lg" aria-describedby="scq-editor-context">
        <CrmFormDialogHeader>
          <DialogTitle>{copy.title}</DialogTitle>
          <DialogDescription id="scq-editor-context">{editor.item.business_name} · {['take_over', 'delegate'].includes(editor.action) && editor.item.closer_name && `当前踢单人 ${editor.item.closer_name} · `}来源销售 {editor.item.source_sales_name || '待确认'}</DialogDescription>
        </CrmFormDialogHeader>
        <CrmFormDialogBody>
          <form id="scq-editor" onSubmit={submit} className="scq-form">
            {['take_over', 'delegate'].includes(editor.action) && editor.item.note && <p className="scq-last-progress">上次进展：{editor.item.note}</p>}
            {editor.action === 'delegate' && <>
              {managers.isPending ? <p role="status">正在查找可接手的主管…</p> :
                managers.isError ? <p role="alert">无法读取主管名单。<Button type="button" size="sm" variant="outline" onClick={() => void managers.refetch()}>重试</Button></p> :
                managers.data?.length ? <>
                  <NativeSelect aria-label="接手主管" value={editor.manager} disabled={busyId !== null}
                    options={[{ value: '', label: '选择接手主管' },
                      ...managers.data.map(manager => ({ value: String(manager.id), label: manager.name }))]}
                    onChange={value => setEditor({ ...editor, manager: value })}/>
                  <p className="scq-last-progress">保留现有跟进计划{editor.due ? ` · ${editor.due.replace('T', ' ')}（北京时间）` : ''}</p>
                </> : <p role="status">暂无拥有这家商家管理权限的在职主管。</p>}
            </>}
            {editor.action === 'lost' && <>
              <NativeSelect aria-label="未成交原因" value={editor.lossReason} options={[
                { value: '', label: '请选择未成交原因' },
                ...Object.entries(reasons).map(([value, label]) => ({ value, label })),
              ]} onChange={value => setEditor({ ...editor, lossReason: value as LossReason | '' })}/>
              {editor.lossReason === 'do_not_contact' && <p role="status">保存后，公司将停止联系这个商家和已记录的号码。</p>}
            </>}
            <Label htmlFor="scq-note">{copy.note}</Label>
            <Textarea id="scq-note" required maxLength={2000} value={editor.note} disabled={busyId !== null} onChange={event => setEditor({ ...editor, note: event.target.value })}/>
            {copy.date && <>
              <Label htmlFor="scq-next">{copy.date}</Label>
              <Input id="scq-next" type="datetime-local" required value={editor.due} disabled={busyId !== null} onChange={event => setEditor({ ...editor, due: event.target.value })}/>
            </>}
            {editError && <p role="alert">{editError}</p>}
            {staleEditor && <div role="status">这条记录的状态已变化。{canResumeEditor && currentItem
              ? <Button type="button" variant="outline" size="sm" onClick={() => {
                setEditor({ ...editor, item: currentItem, manager: '',
                  due: copy.date ? editor.due : formatBusinessDateTimeInput(currentItem.next_follow_up_at) });
                setEditError('');
              }}>使用最新记录继续</Button>
              : '请返回名单核对。'}</div>}
          </form>
        </CrmFormDialogBody>
        <CrmFormDialogFooter>
          <Button type="button" variant="outline" disabled={busyId !== null} onClick={closeEditor}>取消</Button>
          <Button type="submit" form="scq-editor" disabled={busyId !== null || !currentRevision || !editor.note.trim() ||
            (Boolean(copy.date) && !editor.due) || (editor.action === 'lost' && !editor.lossReason) ||
            (editor.action === 'delegate' && !managers.data?.some(manager => String(manager.id) === editor.manager))}>{busyId !== null ? '保存中…' : copy.submit}</Button>
        </CrmFormDialogFooter>
      </CrmFormDialogContent>}
    </Dialog>
  </section>;
}
