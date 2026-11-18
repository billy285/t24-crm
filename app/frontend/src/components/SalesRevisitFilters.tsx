import { useState } from 'react';
import { Search, SlidersHorizontal, Star } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { NativeSelect } from '@/components/ui/native-select';
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { SalesLabelFilter } from '@/components/SalesLabels';
import { salesLabelText, type SalesLabel } from '@/lib/sales-labels';
import { useIsMobile } from '@/hooks/use-mobile';

export const revisitGroups = [
  { value: '', label: '全部已拨' }, { value: 'follow_up', label: '待回访' },
  { value: 'interested', label: '有意向' }, { value: 'appointment', label: '已预约' },
  { value: 'no_answer', label: '未接通' },
];
const dueRanges = [
  { value: '', label: '全部时间' }, { value: 'today', label: '今天' }, { value: 'overdue', label: '逾期' },
];
const contactRules = [
  { value: '', label: '全部联系规则' }, { value: 'contactable', label: '允许联系' },
  { value: 'do_not_contact', label: '禁止再联系' }, { value: 'blacklisted', label: '黑名单' },
];

type Choice = {value: string; label: string};
export type NoteOption = {id: string; label: string};
type Props = {
  mine: boolean; revisit: boolean; setScope: (revisit: boolean) => void;
  search: string; setSearch: (value: string) => void;
  group: string; setGroup: (value: string) => void;
  due: string; setDue: (value: string) => void;
  star: boolean; setStar: (value: boolean) => void;
  note: string; setNote: (value: string) => void; noteOptions: NoteOption[];
  status: string; setStatus: (value: string) => void; statuses: Choice[];
  contact: string; setContact: (value: string) => void;
  label: string; setLabel: (value: string) => void; labels: SalesLabel[];
  priority: boolean; setPriority: (value: boolean) => void;
  clear: () => void;
};

export default function SalesRevisitFilters(p: Props) {
  const mobile = useIsMobile();
  const [more, setMore] = useState(false);
  const groupName = p.mine ? '我的已拨商家' : '已拨商家';
  const noteName = p.noteOptions.find(row => row.id === p.note)?.label;
  const label = p.labels.find(row => String(row.id) === p.label);
  const extraNames = [
    p.revisit && p.note && (noteName || '已选沟通备注'),
    !p.revisit && p.status && p.statuses.find(item => item.value === p.status)?.label,
    !p.revisit && p.contact && contactRules.find(item => item.value === p.contact)?.label,
    p.label && (label ? salesLabelText(label) : '已选商家标签'), p.priority && '团队重点',
  ].filter(Boolean);
  const clearable = Boolean(extraNames.length || p.due || p.group || p.search || p.star);
  const settingsName = p.revisit ? '更多条件' : '筛选';
  const noteChoices = p.noteOptions.map(row => ({value: row.id, label: row.label}));
  if (p.note && !noteName) noteChoices.push({value:p.note, label:'已选沟通备注'});
  const extra = <div className="rv-extra-grid">
    {p.revisit ? <label><span>上次沟通备注</span><NativeSelect aria-label="上次沟通备注" value={p.note}
      options={[{value:'', label:'全部备注'}, ...noteChoices]} onChange={p.setNote}/></label> : <>
      <label><span>线索状态</span><NativeSelect aria-label="线索状态" value={p.status} options={[{value:'',label:'全部状态'}, ...p.statuses]} onChange={p.setStatus}/></label>
      <label><span>联系规则</span><NativeSelect aria-label="联系规则" value={p.contact} options={contactRules} onChange={p.setContact}/></label>
    </>}
    <label><span>商家标签</span><SalesLabelFilter value={p.label} labels={p.labels} onChange={p.setLabel}/></label>
    <label className="rv-priority"><input type="checkbox" checked={p.priority} onChange={e => p.setPriority(e.target.checked)}/>只看团队重点</label>
  </div>;
  return <div className="sl-review-toolbar">
    <div className="rv-top">
      <div role="group" aria-label="名单范围" className="rv-scope">
        <button type="button" aria-pressed={p.revisit} onClick={() => p.setScope(true)}>{groupName}</button>
        <button type="button" aria-pressed={!p.revisit} onClick={() => p.setScope(false)}>全部线索</button>
      </div>
      <div className="rv-search"><Search size={16} aria-hidden="true"/><Input aria-label="搜索销售线索" placeholder="搜索商家、联系人、电话或城市" value={p.search} onChange={e => p.setSearch(e.target.value)}/></div>
    </div>
    {p.revisit && <div role="group" aria-label="沟通分类" className="rv-groups">
      {revisitGroups.map(item => <button key={item.value} type="button" aria-pressed={item.value===p.group} onClick={() => p.setGroup(item.value)}>{item.label}</button>)}
    </div>}
    <div className="rv-filter-row">
      <label className="rv-due"><span>回访时间<small>北京时间</small></span><NativeSelect value={p.due} aria-label="回访时间" onChange={p.setDue} options={dueRanges}/></label>
      <Button className="rv-star" type="button" size="sm" variant="ghost" aria-pressed={p.star} onClick={() => p.setStar(!p.star)}><Star size={15} fill={p.star?'currentColor':'none'}/>只看星标</Button>
      <Button type="button" className="rv-more" size="sm" variant="outline" aria-controls="sales-lead-extra-filters" aria-expanded={more}
        onClick={() => setMore(!more)}><SlidersHorizontal size={15}/>{settingsName}{extraNames.length ? ' · '+extraNames.length : ''}</Button>
    </div>
    {more && !mobile && <div id="sales-lead-extra-filters">{extra}</div>}
    {mobile && <Sheet open={more} onOpenChange={setMore}><SheetContent id="sales-lead-extra-filters" side="bottom" className="sales-center-ui rv-filter-sheet">
      <SheetHeader><SheetTitle>{p.revisit ? '已拨商家筛选' : '筛选联系进展'}</SheetTitle><SheetDescription className="sr-only">筛选条件即时生效</SheetDescription></SheetHeader>
      {extra}<Button onClick={() => setMore(false)}>返回列表</Button></SheetContent></Sheet>}
    {clearable && <div className="rv-filter-summary"><span>{[
      p.group && revisitGroups.find(item=>item.value===p.group)?.label,
      p.due && dueRanges.find(item=>item.value===p.due)?.label, p.star && '我的星标',
      ...extraNames, p.search && '“'+p.search+'”',
    ].filter(Boolean).join(' · ')}</span><button type="button" onClick={p.clear}>清空筛选</button></div>}
  </div>;
}
