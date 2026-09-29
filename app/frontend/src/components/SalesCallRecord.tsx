import { useState } from 'react';
import { ArrowRight, CalendarCheck2, CheckCircle2, Clock3, MessageCircle, PencilLine, PhoneMissed, RefreshCw } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { NativeSelect } from '@/components/ui/native-select';
import { Textarea } from '@/components/ui/textarea';

export type SalesCallValues = { outcome: string; notes: string; nextFollowUpAt: string };
type ProviderCall = { sync_status: string; connected?: boolean; duration_seconds?: number };
type Props = {
  draftKey: string;
  saving: boolean;
  disabledReason?: string;
  providerCall: ProviderCall | null;
  options: { value: string; label: string }[];
  suggestedFollowUp: (outcome: string) => string;
  onSave: (values: SalesCallValues) => Promise<boolean>;
};

const resultIcons = [PhoneMissed, Clock3, MessageCircle, CalendarCheck2];

function readDraft(key: string, options: Props['options']): SalesCallValues {
  const empty = { outcome: '', notes: '', nextFollowUpAt: '' };
  try {
    const draft = JSON.parse(sessionStorage.getItem(key) || 'null');
    if (!draft || Date.now() - draft.updatedAt > 24 * 60 * 60 * 1000) return empty;
    return {
      outcome: options.some(item => item.value === draft.values?.outcome) ? draft.values.outcome : '',
      notes: typeof draft.values?.notes === 'string' ? draft.values.notes : '',
      nextFollowUpAt: typeof draft.values?.nextFollowUpAt === 'string' ? draft.values.nextFollowUpAt : '',
    };
  } catch { return empty; }
}

// Mount with a key containing the authenticated employee, viewed salesperson,
// workday and task. Drafts never cross those scopes or write business records.
export default function SalesCallRecord({ draftKey, saving, disabledReason, providerCall, options, suggestedFollowUp, onSave }: Props) {
  const [values, setValues] = useState(() => readDraft(draftKey, options));
  const [draftAvailable, setDraftAvailable] = useState(true);
  const [validation, setValidation] = useState('');
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
    nextFollowUpAt: ['not_interested', 'do_not_contact', 'not_now', 'existing_provider'].includes(outcome)
      ? '' : values.nextFollowUpAt || suggestedFollowUp(outcome),
  });
  const submit = async () => {
    if (saving || disabledReason) return;
    if (!values.outcome) { setValidation('请选择本次通话的真实结果。'); return; }
    if (requiresNotes && !values.notes.trim()) { setValidation('请写清沟通原因与下一步。'); return; }
    if (requiresFollowUp && !values.nextFollowUpAt) { setValidation('请设置下次跟进时间。'); return; }
    if (await onSave(values)) {
      try { sessionStorage.removeItem(draftKey); } catch { /* The saved business record is authoritative. */ }
      setValues({ outcome: '', notes: '', nextFollowUpAt: '' });
    }
  };

  return (
    <section className="sc-panel sc-record" aria-label="通话结果记录">
      <div className="sc-panel-heading"><h3>通话结果</h3><span>{dirty ? '待保存' : '等待记录'}</span></div>
      {providerCall && providerCall.sync_status !== 'waiting' && (
        <div className={`sc-provider-note ${providerCall.sync_status === 'verified' ? 'is-verified' : ''}`}>
          {providerCall.sync_status === 'verified' ? <CheckCircle2 size={15} /> : <RefreshCw size={15} />}
          <span>{providerCall.sync_status === 'verified'
            ? `RingCentral 已验证${providerCall.connected ? '接通' : '未接通'} · ${Math.floor((providerCall.duration_seconds || 0) / 60)}:${String((providerCall.duration_seconds || 0) % 60).padStart(2, '0')}`
            : providerCall.connected ? 'RingCentral 已回传接通状态，时长待核验' : '已收到 RingCentral 事件，等待通话记录核验'}</span>
        </div>
      )}
      <fieldset disabled={saving || Boolean(disabledReason)} className="sc-record-fields">
        <div className="sc-outcomes" aria-label="选择通话结果">
          {options.slice(0, 4).map((option, index) => {
            const Icon = resultIcons[index];
            return <button key={option.value} type="button" aria-pressed={values.outcome === option.value} onClick={() => changeOutcome(option.value)}><Icon size={17} />{option.label}</button>;
          })}
        </div>
        <div className="sc-other-result"><label><span className="sr-only">其他通话结果</span><NativeSelect value={options.slice(4).some(item => item.value === values.outcome) ? values.outcome : ''} onChange={value => value && changeOutcome(value)} options={[{ value: '', label: '其他结果…' }, ...options.slice(4)]} /></label></div>
        <div className="sc-record-inputs">
          <div><Label htmlFor="sc-call-notes">沟通要点 {requiresNotes && <span className="sc-required">*</span>}</Label><Textarea id="sc-call-notes" value={values.notes} onChange={event => update({ notes: event.target.value })} placeholder="记录商家的需求、顾虑，以及约定的下一步…" rows={4} /></div>
          {!hidesFollowUp && <div><Label htmlFor="sc-followup-time">下次跟进 {requiresFollowUp && <span className="sc-required">*</span>}</Label><Input id="sc-followup-time" type="datetime-local" value={values.nextFollowUpAt} onChange={event => update({ nextFollowUpAt: event.target.value })} /><p className="sc-field-hint">北京时间 · 可按商家约定调整</p></div>}
        </div>
      </fieldset>
      {disabledReason && <p className="sc-record-message">{disabledReason}</p>}
      {validation && <p className="sc-validation" role="alert">{validation}</p>}
      <div className="sc-record-footer"><span><PencilLine size={13} />{!draftAvailable ? '草稿无法暂存，请及时保存' : dirty ? '草稿已暂存，保存后计入执行' : '保存结果后计入今日执行'}</span><Button type="button" onClick={() => void submit()} disabled={saving || Boolean(disabledReason)}>{saving ? '正在保存…' : '保存并进入下一位'}<ArrowRight size={15} /></Button></div>
    </section>
  );
}
