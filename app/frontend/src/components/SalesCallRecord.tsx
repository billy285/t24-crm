import { useId, useRef, useState } from 'react';
import { emptyContact, type ContactDetails } from '@/lib/sales-intelligence';
import { ArrowRight, BookOpen } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { NativeSelect } from '@/components/ui/native-select';
import { Textarea } from '@/components/ui/textarea';

export type SalesCallValues = { outcome: string; notes: string; nextFollowUpAt: string; contactDetails?: ContactDetails };
type ProviderCall = { sync_status: string; connected?: boolean; duration_seconds?: number };
type Props = {
  draftKey: string;
  saving: boolean;
  disabledReason?: string;
  providerCall: ProviderCall | null;
  options: { value: string; label: string }[];
  suggestedFollowUp: (outcome: string) => string;
  onSave: (values: SalesCallValues) => Promise<boolean>;
  onOpenKnowledge?: () => void;
  submitLabel?: string;
};

function readDraft(key: string, options: Props['options']): SalesCallValues {
  const empty = { outcome: '', notes: '', nextFollowUpAt: '' };
  try {
    const draft = JSON.parse(sessionStorage.getItem(key) || 'null');
    if (!draft || !Number.isFinite(draft.updatedAt) || Date.now() - draft.updatedAt > 24 * 60 * 60 * 1000) return empty;
    return {
      outcome: options.some(item => item.value === draft.values?.outcome) ? draft.values.outcome : '',
      notes: typeof draft.values?.notes === 'string' ? draft.values.notes : '',
      nextFollowUpAt: typeof draft.values?.nextFollowUpAt === 'string' ? draft.values.nextFollowUpAt : '',
      contactDetails: { ...emptyContact, ...draft.values?.contactDetails },
    };
  } catch { return empty; }
}

// The mounting key scopes drafts to employee, salesperson, workday and task.
// A draft never writes a business record.
export default function SalesCallRecord({ draftKey, saving, disabledReason, providerCall, options, suggestedFollowUp, onSave, onOpenKnowledge, submitLabel = '保存并下一位' }: Props) {
  const [values, setValues] = useState(() => readDraft(draftKey, options));
  const [draftAvailable, setDraftAvailable] = useState(true);
  const [validation, setValidation] = useState('');
  const submitting = useRef(false);
  const fieldId = useId();
  const requiresNotes = ['interested', 'appointment', 'do_not_contact'].includes(values.outcome);
  const requiresFollowUp = ['callback', 'interested', 'appointment'].includes(values.outcome);
  const hidesFollowUp = ['not_interested', 'do_not_contact', 'not_now', 'existing_provider'].includes(values.outcome);
  const dirty = Boolean(values.outcome || values.notes || values.nextFollowUpAt);

  const update = (changes: Partial<SalesCallValues>) => {
    const next = { ...values, ...changes };
    setValues(next);
    setValidation('');
    try { sessionStorage.setItem(draftKey, JSON.stringify({ updatedAt: Date.now(), values: next })); }
    catch { setDraftAvailable(false); }
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
        try { sessionStorage.removeItem(draftKey); } catch { /* The business record was saved. */ }
        setValues({ outcome: '', notes: '', nextFollowUpAt: '' });
      } else { setValidation('保存失败，记录已保留，请重试'); }
    } catch { setValidation('保存失败，记录已保留，请重试'); }
    finally { submitting.current = false; }
  };

  return <section className="sc-panel sc-record sw-record" aria-label="通话结果记录">
    {providerCall && providerCall.sync_status !== 'waiting' && <div className="sw-provider-status" role="status">{providerCall.sync_status === 'verified'
      ? `官方${providerCall.connected ? '接通' : '未接通'} · ${Math.floor((providerCall.duration_seconds || 0) / 60)}:${String((providerCall.duration_seconds || 0) % 60).padStart(2, '0')}`
      : '通话已回传 · 待核验'}</div>}
    <fieldset disabled={saving || Boolean(disabledReason)} className="sc-record-fields">
      <div className="sw-note-heading"><Label htmlFor={`${fieldId}-notes`}>沟通记录{requiresNotes && <span className="sc-required"> *</span>}</Label><span role="status">{!draftAvailable ? '草稿暂存不可用' : dirty ? '草稿' : ''}</span></div>
      <Textarea id={`${fieldId}-notes`} aria-label="沟通记录" value={values.notes} onChange={event => update({ notes: event.target.value })} placeholder="记下客户的需求、顾虑和约定的下一步…" rows={5} className="sw-notes" />
      <div className="sw-result-heading">本次结果</div>
      <div className="sw-result-row">
        <div className="sc-outcomes" aria-label="选择通话结果">{options.slice(0, 4).map(option => <button key={option.value} type="button" aria-pressed={values.outcome === option.value} onClick={() => changeOutcome(option.value)}>{option.label}</button>)}</div>
        <label className="sw-other-result"><span className="sr-only">其他通话结果</span><NativeSelect value={options.slice(4).some(item => item.value === values.outcome) ? values.outcome : ''} onChange={value => value && changeOutcome(value)} options={[{ value: '', label: '其他结果' }, ...options.slice(4)]} /></label>
      </div>
      {Boolean(values.outcome) && !hidesFollowUp && <div className="sw-followup"><Label htmlFor={`${fieldId}-followup`}>下次跟进<span> · 北京时间{requiresFollowUp ? ' *' : ''}</span></Label><Input id={`${fieldId}-followup`} type="datetime-local" value={values.nextFollowUpAt} onChange={event => update({ nextFollowUpAt: event.target.value })} /></div>}
      {values.outcome && values.outcome !== 'no_answer' && <details className="si-contact-extra"><summary>更多信息</summary><div className="si-form-grid"><label>沟通对象<NativeSelect value={values.contactDetails?.reached_person || 'unknown'} onChange={reached_person => update({ contactDetails: { ...emptyContact, ...values.contactDetails, reached_person } })} options={[{ value: 'unknown', label: '尚未确认' }, { value: 'gatekeeper', label: '前台／其他人员' }, { value: 'decision_maker', label: '老板／决策人' }]} /></label><label>拒绝／暂缓原因<Input value={values.contactDetails?.rejection_reason || ''} onChange={event => update({ contactDetails: { ...emptyContact, ...values.contactDetails, rejection_reason: event.target.value } })} /></label><label>真实需求<Input value={values.contactDetails?.need_summary || ''} onChange={event => update({ contactDetails: { ...emptyContact, ...values.contactDetails, need_summary: event.target.value } })} /></label><label>下一步<Input value={values.contactDetails?.next_step || ''} onChange={event => update({ contactDetails: { ...emptyContact, ...values.contactDetails, next_step: event.target.value } })} /></label></div></details>}
    </fieldset>
    {disabledReason && <p className="sc-record-message">{disabledReason}</p>}
    {validation && <p className="sc-validation" role="alert">{validation}</p>}
    {!draftAvailable && dirty && <p className="sc-validation" role="alert">草稿无法暂存，请保存后再离开。</p>}
    <div className="sc-record-footer">{onOpenKnowledge ? <Button type="button" variant="ghost" onClick={onOpenKnowledge} className="sw-knowledge-trigger"><BookOpen size={15} />话术</Button> : <span>保存后计入跟进历史</span>}<Button type="button" onClick={() => void submit()} disabled={saving || Boolean(disabledReason)}>{saving ? '正在保存…' : submitLabel}<ArrowRight size={15} /></Button></div>
  </section>;
}
