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
import { useIsMobile } from '@/hooks/use-mobile';
import { defaultSalesQuickNotes, type SalesQuickNoteTemplate } from '@/lib/sales-quick-notes';
import { callNoteLimit, primaryCallOutcome, toggleCallOutcome, toggleQuickNote, trackEditedNotes, type SelectedQuickNote } from '@/lib/sales-call-selection';
import { emptySalesCallValues, hasSalesCallDraft, readSalesCallDraft, removeSalesCallDraft, writeSalesCallDraft, type DraftPersistence, type SalesCallDraft } from '@/lib/sales-call-draft';

export type SalesCallValues = { outcome: string; outcomes?: string[]; quickNotes?: SelectedQuickNote[]; submissionId?: string; notes: string; nextFollowUpAt: string; contactDetails?: ContactDetails };
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
  supplemental?: boolean;
  timezone?: string;
  noteTemplates?: SalesQuickNoteTemplate[];
  merchantIndustry?: 'restaurant' | 'beauty' | 'other';
  onManageNoteTemplates?: () => void;
};

// The mounting key scopes drafts to employee, salesperson, lead, workday and task.
// A draft never writes a business record.
export default function SalesCallRecord({ draftKey, legacyDraftKey, saving, disabledReason, providerCall, options, suggestedFollowUp, onSave, onOpenKnowledge, submitLabel = '保存并下一位', supplemental = false, timezone, noteTemplates = defaultSalesQuickNotes, merchantIndustry = 'other', onManageNoteTemplates }: Props) {
  const [initialDraft] = useState<SalesCallDraft>(() => disabledReason ? { values: emptySalesCallValues(), restored: false, persistence: 'session' as DraftPersistence } : readSalesCallDraft(draftKey, options, legacyDraftKey));
  const isMobile = useIsMobile();
  const [showMoreTemplates, setShowMoreTemplates] = useState(false);
  const [values, setValues] = useState(initialDraft.values);
  const [persistence, setPersistence] = useState(initialDraft.persistence);
  const [restored, setRestored] = useState(initialDraft.restored);
  const [draftInvalid, setDraftInvalid] = useState(initialDraft.invalid || false);
  const [validation, setValidation] = useState('');
  const submitting = useRef(false);
  const fieldId = useId();
  const requiresNotes = ['interested', 'appointment', 'do_not_contact'].includes(values.outcome);
  const requiresFollowUp = ['callback', 'interested', 'appointment'].includes(values.outcome);
  const hidesFollowUp = ['not_interested', 'do_not_contact', 'not_now', 'existing_provider'].includes(values.outcome);
  const outcomes = values.outcomes ?? (values.outcome ? [values.outcome] : []);
  const selectedNotes = values.quickNotes ?? [];
  const templates = noteTemplates.filter(template => {
    if (!template.enabled || (template.industry !== 'all' && template.industry !== merchantIndustry)) return false;
    // The unmodified stock note duplicates the visible workflow choice.
    // A renamed or rewritten owner template remains an independent note.
    const stock = defaultSalesQuickNotes.find(item => item.id === template.id);
    const covered = ['no_answer', 'existing_provider', 'not_now'].includes(template.id) &&
      options.some(item => item.value === template.id) && stock?.label === template.label && stock.text === template.text &&
      !template.remind_do_not_contact;
    return !covered;
  });
  const choices = [
    ...options.slice(0, 4).map(option => ({ kind: 'result' as const, option })),
    ...templates.slice(0, 4).map(option => ({ kind: 'note' as const, option })),
    ...options.slice(4).map(option => ({ kind: 'result' as const, option })),
    ...templates.slice(4).map(option => ({ kind: 'note' as const, option })),
  ];
  const orphanNotes = selectedNotes.filter(note => !templates.some(template => template.id === note.id));
  const compactChoice = (index: number) => index < (isMobile ? 8 : 12);
  const hiddenCount = choices.filter((choice, index) => !compactChoice(index) && !(choice.kind === 'result'
    ? outcomes.includes(choice.option.value) : selectedNotes.some(note => note.id === choice.option.id))).length;
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
  const changeNote = (template: Pick<SalesQuickNoteTemplate, 'id' | 'label' | 'text'>, remind = false) => {
    if (saving || disabledReason || submitting.current) return;
    const next = toggleQuickNote(values.notes, selectedNotes, template, remind);
    if (next.quickNotes.length > 60) {
      toast.warning('同一条沟通最多选择 60 个快捷备注');
      return;
    }
    if (next.notes.length > callNoteLimit && next.quickNotes.length > selectedNotes.length) {
      toast.warning(`沟通内容最多 ${callNoteLimit} 字，请先删减后再选择备注`);
      return;
    }
    update(next);
  };
  const discard = () => {
    if (saving || disabledReason || !(dirty || draftInvalid) || !window.confirm('确定丢弃这位商家的本地草稿？尚未保存的记录会被清空。')) return;
    const removed = removeSalesCallDraft(draftKey, legacyDraftKey);
    setValues(emptySalesCallValues());
    setRestored(false);
    setDraftInvalid(false);
    setValidation(removed ? '' : '草稿已从本页清空，浏览器暂存无法清除，刷新可能恢复。');
  };
  const changeOutcome = (value: string) => {
    const next = toggleCallOutcome(outcomes, value);
    const outcome = primaryCallOutcome(next);
    update({ outcome, outcomes: next,
      contactDetails: outcome === 'no_answer' ? { ...emptyContact } : values.contactDetails,
      nextFollowUpAt: !outcome || ['not_interested', 'do_not_contact', 'not_now', 'existing_provider'].includes(outcome)
        ? '' : values.nextFollowUpAt || suggestedFollowUp(outcome),
    });
  };
  const submit = async () => {
    if (saving || disabledReason || submitting.current) return;
    if (!values.outcome && !selectedNotes.length) { setValidation('请选择本次结果或一项快捷备注'); return; }
    if (!values.outcome && selectedNotes.some(note => note.remindDoNotContact || templates.some(template => template.id === note.id && template.remind_do_not_contact))) {
      setValidation('请明确选择本次结果。商家要求停止联系时，请选择「禁止再联系」');
      return;
    }
    if (values.notes.length > callNoteLimit) { setValidation(`沟通内容最多 ${callNoteLimit} 字，请删减后保存`); return; }
    if (requiresNotes && !values.notes.trim()) { setValidation('请写清沟通原因与下一步'); return; }
    if (requiresFollowUp && !values.nextFollowUpAt) { setValidation('请设置下次跟进时间'); return; }
    submitting.current = true;
    try {
      let draft = values;
      if (supplemental && !draft.submissionId) {
        draft = { ...draft, submissionId: crypto.randomUUID() };
        setValues(draft);
        setPersistence(writeSalesCallDraft(draftKey, draft));
      }
      if (await onSave({ ...draft, outcome: draft.outcome || 'recorded', outcomes })) {
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
      <div className="sw-note-heading"><strong id={`${fieldId}-choices`}>本次沟通 <small>可多选</small></strong>
        <div className="sw-draft-tools"><span role="status">{dirty ? persistence === 'memory' ? '本次页面保留' : restored ? '已恢复草稿' : '草稿已暂存' : ''}</span>
          {(dirty || draftInvalid) && <Button type="button" variant="ghost" onClick={discard}>丢弃草稿</Button>}
          {onManageNoteTemplates && <Button type="button" variant="ghost" onClick={onManageNoteTemplates}>管理快捷备注</Button>}
        </div>
      </div>
      <div className="sw-call-choices" role="group" aria-labelledby={`${fieldId}-choices`}>
        {choices.map((choice, index) => {
          if (choice.kind === 'result') {
            const { value, label } = choice.option;
            const selected = outcomes.includes(value);
            if (!showMoreTemplates && !compactChoice(index) && !selected) return null;
            const shortLabel = label.split('（')[0];
            return <button key={`result-${value}`} type="button" aria-label={label} aria-pressed={selected}
              disabled={values.outcome === 'do_not_contact' && !selected}
              onClick={() => changeOutcome(value)} title={label}>{shortLabel}</button>;
          }
          const template = choice.option;
          const selected = selectedNotes.find(item => item.id === template.id);
          if (!showMoreTemplates && !compactChoice(index) && !selected) return null;
          const label = selected?.label || template.label;
          const duplicatesResult = options.some(option => option.label.split('（')[0] === label);
          return <button key={`note-${template.id}`} type="button" aria-label={`备注：${selected?.label || template.label}`}
            aria-pressed={Boolean(selected)} title={selected?.text || template.text}
            onClick={() => changeNote(template, template.remind_do_not_contact)}>{duplicatesResult ? `备注 · ${label}` : label}</button>;
        })}
        {orphanNotes.map(note => <button key={`saved-${note.id}`} type="button" aria-label={`备注：${note.label}`}
          aria-pressed="true" title={note.text} onClick={() => changeNote(note)}>{note.label}</button>)}
      </div>
      {(hiddenCount > 0 || showMoreTemplates) && <button type="button" className="sw-call-more"
        aria-expanded={showMoreTemplates} onClick={() => setShowMoreTemplates(current => !current)}>
        {showMoreTemplates ? '收起选项' : `更多选项（${hiddenCount}）`}
      </button>}
      {values.outcome && (outcomes.length > 1 || ['not_now','existing_provider','do_not_contact'].includes(values.outcome)) &&
        <small className="sw-call-routing" role="status">{values.outcome === 'do_not_contact' ? '保存后将停止联系这家商家。' :
          `按「${options.find(option => option.value === values.outcome)?.label}」安排下一步`}</small>}
      {selectedNotes.some(note => note.remindDoNotContact) && values.outcome !== 'do_not_contact' &&
        <p className="sw-note-result-reminder" role="status">商家明确要求停止联系时，请选择「禁止再联系」并保存。</p>}
      <Label className="sw-call-notes-label" htmlFor={`${fieldId}-notes`}>沟通内容{requiresNotes && <span className="sc-required"> *</span>}</Label>
      <Textarea id={`${fieldId}-notes`} aria-label="沟通记录" maxLength={callNoteLimit} value={values.notes}
        onChange={event => update({ notes: event.target.value, quickNotes: trackEditedNotes(values.notes, event.target.value, selectedNotes) })}
        placeholder="补充客户的需求、顾虑或约定…" rows={3} className="sw-notes" />
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
