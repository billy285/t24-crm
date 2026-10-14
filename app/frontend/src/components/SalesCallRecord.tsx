import { useEffect, useId, useRef, useState } from 'react';
import { toast } from 'sonner';
import SalesFollowUpQuick from '@/components/SalesFollowUpQuick';
import { emptyContact, type ContactDetails } from '@/lib/sales-intelligence';
import { ArrowRight, BookOpen } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { NativeSelect } from '@/components/ui/native-select';
import { Textarea } from '@/components/ui/textarea';
import { emptySalesCallValues, hasSalesCallDraft, readSalesCallDraft, removeSalesCallDraft, writeSalesCallDraft, type DraftPersistence, type SalesCallDraft } from '@/lib/sales-call-draft';

export type SalesCallValues = { outcome: string; notes: string; nextFollowUpAt: string; contactDetails?: ContactDetails };
type ProviderCall = { sync_status: string; connected?: boolean; duration_seconds?: number };
type Props = {
  draftKey: string | null;
  legacyDraftKey?: string;
  saving: boolean;
  disabledReason?: string;
  providerCall: ProviderCall | null;
  options: { value: string; label: string }[];
  suggestedFollowUp: (outcome: string) => string;
  onSave: (values: SalesCallValues) => Promise<boolean>;
  onOpenKnowledge?: () => void;
  submitLabel?: string;
  timezone?: string;
};

const noteTemplates = [
  { label: '本次未接通', text: '本次未接通。' },
  { label: '前台／老板不在', text: '前台接听，老板不在。' },
  { label: '英文沟通', text: '对方讲英文，暂未能有效沟通。' },
  { label: '老板有兴趣／忙', text: '老板有兴趣，目前比较忙。' },
  { label: '先看资料', text: '希望先看资料，关注：____。' },
  { label: '已有服务商', text: '已有服务商，补充：____。' },
  { label: '暂时不需要', text: '暂时不需要，原因：____。' },
  { label: '要求不再联系', text: '对方明确要求不再联系。' },
];

// The mounting key scopes drafts to employee, salesperson, lead, workday and task.
// A draft never writes a business record.
export default function SalesCallRecord({ draftKey, legacyDraftKey, saving, disabledReason, providerCall, options, suggestedFollowUp, onSave, onOpenKnowledge, submitLabel = '保存并下一位', timezone }: Props) {
  const [initialDraft] = useState<SalesCallDraft>(() => disabledReason ? { values: emptySalesCallValues(), restored: false, persistence: 'session' as DraftPersistence } : readSalesCallDraft(draftKey, options, legacyDraftKey));
  const [values, setValues] = useState(initialDraft.values);
  const [persistence, setPersistence] = useState(initialDraft.persistence);
  const [restored, setRestored] = useState(initialDraft.restored);
  const [draftInvalid, setDraftInvalid] = useState(initialDraft.invalid || false);
  const [validation, setValidation] = useState('');
  const submitting = useRef(false);
  const notesRef = useRef<HTMLTextAreaElement>(null);
  const fieldId = useId();
  const requiresNotes = ['interested', 'appointment', 'do_not_contact'].includes(values.outcome);
  const requiresFollowUp = ['callback', 'interested', 'appointment'].includes(values.outcome);
  const hidesFollowUp = ['not_interested', 'do_not_contact', 'not_now', 'existing_provider'].includes(values.outcome);
  const dirty = hasSalesCallDraft(values);
  useEffect(() => {
    if (!dirty || persistence === 'session') return;
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ''; };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [dirty, persistence]);

  const update = (changes: Partial<SalesCallValues>) => {
    const next = { ...values, ...changes };
    setValues(next);
    setValidation('');
    setRestored(false);
    setDraftInvalid(false);
    setPersistence(writeSalesCallDraft(draftKey, next));
  };
  const insertNoteTemplate = (text: string) => {
    if (saving || disabledReason || submitting.current) return;
    const notes = values.notes
      ? `${values.notes}${values.notes.endsWith('\n') ? '' : '\n'}${text}`
      : text;
    if (notes.length > 10000) {
      toast.warning('插入后会超出字数上限，请先删减沟通记录');
      return;
    }
    update({ notes });
    requestAnimationFrame(() => {
      notesRef.current?.focus();
      notesRef.current?.setSelectionRange(notes.length, notes.length);
    });
  };
  const discard = () => {
    if (saving || disabledReason || !(dirty || draftInvalid) || !window.confirm('确定丢弃这位商家的本地草稿？尚未保存的记录会被清空。')) return;
    const removed = removeSalesCallDraft(draftKey, legacyDraftKey);
    setValues(emptySalesCallValues());
    setRestored(false);
    setDraftInvalid(false);
    setValidation(removed ? '' : '草稿已从本页清空，浏览器暂存无法清除，刷新可能恢复。');
  };
  const changeOutcome = (outcome: string) => update({
    outcome,
    contactDetails: outcome === 'no_answer' ? { ...emptyContact } : values.contactDetails,
    nextFollowUpAt: ['not_interested', 'do_not_contact', 'not_now', 'existing_provider'].includes(outcome)
      ? '' : values.nextFollowUpAt || suggestedFollowUp(outcome),
  });
  const submit = async () => {
    if (saving || disabledReason || submitting.current) return;
    if (!values.outcome) { setValidation('请选择本次结果'); return; }
    if (requiresNotes && !values.notes.trim()) { setValidation('请写清沟通原因与下一步'); return; }
    if (requiresFollowUp && !values.nextFollowUpAt) { setValidation('请设置下次跟进时间'); return; }
    submitting.current = true;
    try {
      if (await onSave(values)) {
        if (!removeSalesCallDraft(draftKey, legacyDraftKey)) toast.warning('记录已保存；浏览器暂存无法清除，刷新可能恢复旧草稿，请勿重复提交');
        setValues(emptySalesCallValues());
        setRestored(false);
        setDraftInvalid(false);
      } else { setValidation('保存失败，记录已保留，请重试'); }
    } catch { setValidation('保存失败，记录已保留，请重试'); }
    finally { submitting.current = false; }
  };

  return <section className="sc-panel sc-record sw-record" aria-label="通话结果记录">
    {providerCall && providerCall.sync_status !== 'waiting' && <div className="sw-provider-status" role="status">{providerCall.sync_status === 'verified'
      ? `官方${providerCall.connected ? '接通' : '未接通'} · ${Math.floor((providerCall.duration_seconds || 0) / 60)}:${String((providerCall.duration_seconds || 0) % 60).padStart(2, '0')}`
      : '通话已回传 · 待核验'}</div>}
    <fieldset disabled={saving || Boolean(disabledReason)} className="sc-record-fields">
      <div className="sw-note-heading"><Label htmlFor={`${fieldId}-notes`}>沟通记录{requiresNotes && <span className="sc-required"> *</span>}</Label><div className="sw-draft-tools"><span role="status" title="仅保存在当前浏览器页签，明确保存后才写入联系记录">{dirty ? persistence === 'memory' ? '本次页面保留' : restored ? '已恢复草稿' : '草稿已暂存' : ''}</span>{(dirty || draftInvalid) && <Button type="button" variant="ghost" onClick={discard}>丢弃草稿</Button>}</div></div>
      <div className="sw-note-templates" role="group" aria-label="快捷备注模板"><p>快捷备注<span>点击追加</span></p><div>{noteTemplates.map(template => <button key={template.text} type="button" aria-label={`插入模板：${template.text}`} title={template.text} onClick={() => insertNoteTemplate(template.text)}>{template.label}</button>)}</div></div>
      <Textarea ref={notesRef} id={`${fieldId}-notes`} aria-label="沟通记录" maxLength={10000} value={values.notes} onChange={event => update({ notes: event.target.value })} placeholder="记下客户的需求、顾虑和约定的下一步…" rows={5} className="sw-notes" />
      <div className="sw-result-heading">本次结果</div>
      <div className="sw-result-row">
        <div className="sc-outcomes sw-outcomes-expanded" role="group" aria-label="选择通话结果">{options.map(option => {
          const labelParts = option.label.match(/^(.+?)（(.+)）$/);
          return <button key={option.value} type="button" aria-label={option.label} aria-pressed={values.outcome === option.value} onClick={() => changeOutcome(option.value)}>{labelParts ? <><span>{labelParts[1]}</span><small>{labelParts[2]}</small></> : option.label}</button>;
        })}</div>
      </div>
      {Boolean(values.outcome) && !hidesFollowUp && <div className="sw-followup"><Label htmlFor={`${fieldId}-followup`}>下次跟进<span> · 北京时间{requiresFollowUp ? ' *' : ''}</span></Label><Input id={`${fieldId}-followup`} type="datetime-local" value={values.nextFollowUpAt} onChange={event => update({ nextFollowUpAt: event.target.value })} /><SalesFollowUpQuick value={values.nextFollowUpAt} timezone={timezone} onChange={nextFollowUpAt => update({ nextFollowUpAt })} /></div>}
      {values.outcome && values.outcome !== 'no_answer' && <details className="si-contact-extra"><summary>更多信息</summary><div className="si-form-grid"><label>沟通对象<NativeSelect value={values.contactDetails?.reached_person || 'unknown'} onChange={reached_person => update({ contactDetails: { ...emptyContact, ...values.contactDetails, reached_person } })} options={[{ value: 'unknown', label: '尚未确认' }, { value: 'gatekeeper', label: '前台／其他人员' }, { value: 'decision_maker', label: '老板／决策人' }]} /></label><label>拒绝／暂缓原因<Input maxLength={2000} value={values.contactDetails?.rejection_reason || ''} onChange={event => update({ contactDetails: { ...emptyContact, ...values.contactDetails, rejection_reason: event.target.value } })} /></label><label>真实需求<Input maxLength={2000} value={values.contactDetails?.need_summary || ''} onChange={event => update({ contactDetails: { ...emptyContact, ...values.contactDetails, need_summary: event.target.value } })} /></label><label>下一步<Input maxLength={2000} value={values.contactDetails?.next_step || ''} onChange={event => update({ contactDetails: { ...emptyContact, ...values.contactDetails, next_step: event.target.value } })} /></label></div></details>}
    </fieldset>
    {disabledReason && <p className="sc-record-message">{disabledReason}</p>}
    {validation && <p className="sc-validation" role="alert">{validation}</p>}
    {draftInvalid && <p className="sc-validation" role="alert">暂存草稿无法读取，原草稿尚未删除。</p>}
    {persistence === 'memory' && dirty && <p className="sc-validation" role="alert">浏览器暂存不可用，刷新会丢失本页草稿。请先保存。</p>}
    <div className="sc-record-footer">{onOpenKnowledge ? <Button type="button" variant="ghost" onClick={onOpenKnowledge} className="sw-knowledge-trigger"><BookOpen size={15} />话术</Button> : <span>保存后计入跟进历史</span>}<Button type="button" onClick={() => void submit()} disabled={saving || Boolean(disabledReason)}>{saving ? '正在保存…' : submitLabel}<ArrowRight size={15} /></Button></div>
  </section>;
}
