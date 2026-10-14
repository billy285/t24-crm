import { useEffect, useRef, useState } from 'react';
import { Check, ChevronDown, History, Plus, Save, Trash2, UserRound } from 'lucide-react';
import { Sheet, SheetContent, SheetDescription, SheetTitle } from '@/components/ui/sheet';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { NativeSelect } from '@/components/ui/native-select';
import { useIsMobile } from '@/hooks/use-mobile';
import { formatPhoneNumber, parsePhoneNumber } from '@/lib/phone-format';
import {
  createEnrichmentContact, enrichmentDraftSignature, enrichmentFieldLabels, enrichmentWarningText,
  normalizeEnrichmentUpdate, removeEnrichmentContact, toEnrichmentUpdate, validateEnrichmentUpdate,
  type EnrichmentContact, type EnrichmentHistoryEntry, type EnrichmentProduct,
  type EnrichmentResponse, type EnrichmentUpdate,
} from '@/lib/sales-lead-enrichment';
import './sales-lead-enrichment.css';

export type SalesLeadQuickEditProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  leadId: number | null;
  value: EnrichmentResponse | null;
  draft: EnrichmentUpdate | null;
  onDraftChange: (value: EnrichmentUpdate) => void;
  onSave: (value: EnrichmentUpdate) => void | boolean | Promise<void | boolean>;
  saving: boolean;
  loading: boolean;
  error?: string | null;
  catalog: EnrichmentProduct[];
  history?: EnrichmentHistoryEntry[] | null;
  onLoadHistory?: () => void | Promise<unknown>;
  historyLoading?: boolean;
  historyError?: string | null;
  canEdit?: boolean;
  readOnlyReason?: string | null;
  onReload?: () => void;
  draftNotice?: string;
};

const verificationOptions = [{ value: 'pending', label: '待确认' }, { value: 'confirmed', label: '已确认' }];
const dateText = (date: string | null | undefined) => {
  if (!date) return '';
  const parsed = new Date(date);
  return Number.isNaN(parsed.getTime()) ? '时间待确认' : parsed.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
};

function historyValue(key: string, value: unknown, catalog: EnrichmentProduct[]): string {
  if (value == null || value === '') return '未填写';
  if (key === 'verification') return value === 'confirmed' ? '已确认' : '待确认';
  if (key === 'contacts' && Array.isArray(value)) return value.length ? value.map(contact => [contact.name, contact.role, contact.phone, contact.email, contact.wechat].filter(item => typeof item === 'string' && item).join(' · ')).join('；') : '无联系人';
  if (key === 'interest_product_ids' && Array.isArray(value)) return value.map(id => catalog.find(product => product.id === id)?.name || `产品 #${id}`).join('、') || '未选择';
  return typeof value === 'string' || typeof value === 'number' ? String(value) : '已更新';
}

function PhoneHint({ value, country }: { value: string | null; country: string | null }) {
  if (!value?.trim()) return null;
  const parsed = parsePhoneNumber(value, country);
  return <span className={`sle-phone-hint ${parsed.isValid ? '' : 'sle-phone-pending'}`}>{parsed.isValid ? formatPhoneNumber(value, country) : '号码待核对，可先保留为待确认'}</span>;
}

/** Controlled draft: closing, failures and history inspection never clear parent input. */
export default function SalesLeadQuickEdit({
  open, onOpenChange, leadId, value, draft, onDraftChange, onSave, saving, loading, error,
  catalog, history, onLoadHistory, historyLoading = false, historyError, canEdit = true, readOnlyReason,
  onReload, draftNotice,
}: SalesLeadQuickEditProps) {
  const mobile = useIsMobile();
  const [tab, setTab] = useState<'edit' | 'history'>('edit');
  const [validation, setValidation] = useState<string[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [confirmReload, setConfirmReload] = useState(false);
  const submitLock = useRef(false);
  useEffect(() => { setTab('edit'); setValidation([]); setConfirmReload(false); }, [leadId]);
  const ready = value !== null && value.lead_id === leadId;
  const form = ready ? draft || toEnrichmentUpdate(value) : null;
  const editable = ready && canEdit && value.can_edit;
  const busy = saving || submitting;
  const readonlyMessage = readOnlyReason || value?.read_only_reason || '当前账号不能编辑这位商家的资料。';
  const dirty = Boolean(form && value && enrichmentDraftSignature(form) !== enrichmentDraftSignature(toEnrichmentUpdate(value, form.source)));
  const warning = enrichmentWarningText(value?.warnings || []);
  const update = (changes: Partial<EnrichmentUpdate>) => {
    if (!form || !editable || busy || loading) return;
    setValidation([]); setConfirmReload(false);
    onDraftChange({ ...form, ...changes });
  };
  const updateContact = (id: string, changes: Partial<EnrichmentContact>) => {
    if (!form) return;
    update({ contacts: form.contacts.map(contact => contact.id === id ? { ...contact, ...changes } : contact) });
  };
  const addContact = () => {
    if (!form || form.contacts.length >= 20) return;
    const contact = createEnrichmentContact();
    update({ contacts: [...form.contacts, contact] });
  };
  const save = async () => {
    if (!form || !editable || loading || busy || submitLock.current) return;
    const problems = validateEnrichmentUpdate(form);
    setValidation(problems);
    if (problems.length) return;
    submitLock.current = true; setSubmitting(true);
    try {
      const result = await onSave(normalizeEnrichmentUpdate(form));
      if (result === false) setValidation(['保存未完成，输入已保留，请核对提示后重试。']);
    } catch { setValidation(['保存未完成，输入已保留，请稍后重试。']); }
    finally { submitLock.current = false; setSubmitting(false); }
  };
  const showHistory = () => {
    setTab('history');
    if (!historyLoading) void onLoadHistory?.();
  };
  const close = () => { if (!busy) onOpenChange(false); };

  return <Sheet open={open} onOpenChange={next => { if (!busy) onOpenChange(next); }}>
    <SheetContent side={mobile ? 'bottom' : 'right'} className="sales-lead-quick-edit" overlayClassName="sle-overlay">
      <header className="sle-header">
        <div><span className="sle-eyebrow">商家资料</span><SheetTitle>快捷补全</SheetTitle></div>
        <SheetDescription>边沟通边记录，保存后留在当前商家。</SheetDescription>
        <nav className="sle-tabs" aria-label="资料面板视图">
          <button type="button" aria-pressed={tab === 'edit'} onClick={() => setTab('edit')}><UserRound size={14}/>资料</button>
          {onLoadHistory && <button type="button" aria-pressed={tab === 'history'} onClick={showHistory}><History size={14}/>修改历史</button>}
          <span role="status">{busy ? '正在保存…' : dirty ? '有未保存修改' : ready ? '已读取最新资料' : ''}</span>
        </nav>
      </header>
      <div className="sle-body" aria-busy={loading || busy}>
        {error && <div className="sle-message sle-error" role="alert">{error}{onReload && <button type="button" disabled={busy} onClick={() => setConfirmReload(true)}>重新读取资料（放弃未保存修改）</button>}</div>}
        {confirmReload && <div className="sle-message sle-reload" role="alert"><span>重新读取会替换本商家尚未保存的资料。</span><div><Button type="button" variant="outline" size="sm" onClick={() => setConfirmReload(false)}>保留修改</Button><Button type="button" size="sm" disabled={busy} onClick={() => { setConfirmReload(false); setValidation([]); onReload?.(); }}>确认重新读取</Button></div></div>}
        {loading ? <p className="sle-empty" role="status">正在读取商家资料…</p> : !form ? <p className="sle-empty">暂时无法读取资料，请重试。</p> : tab === 'history' ? <section className="sle-history" aria-label="资料修改历史">
          {historyLoading ? <p role="status">正在读取修改历史…</p> : historyError ? <p role="alert">{historyError}<Button variant="ghost" type="button" onClick={() => void onLoadHistory?.()}>重试</Button></p> : history?.length ? history.map(item => <details key={item.id}>
            <summary><div><strong>{item.actor_name || '操作人员'}</strong><span>{dateText(item.created_at)} · {item.source === 'call' ? '通话补全' : '手动补全'}</span></div><span>版本 {item.revision}<ChevronDown size={14}/></span></summary>
            <p>{item.changed_fields.map(key => enrichmentFieldLabels[key]).filter(Boolean).join('、') || '商家资料'}已更新</p>
            {item.changed_fields.filter(key => key in enrichmentFieldLabels && key !== 'preferred_contact_id').map(key => <div className="sle-history-change" key={key}><strong>{enrichmentFieldLabels[key]}</strong><span><small>修改前</small>{historyValue(key, item.before?.[key as keyof EnrichmentResponse], catalog)}</span><span><small>修改后</small>{historyValue(key, item.after?.[key as keyof EnrichmentResponse], catalog)}</span></div>)}
          </details>) : <p className="sle-empty">暂无资料修改记录。</p>}
        </section> : <>
          {!editable && <div className="sle-message" role="status">{readonlyMessage}</div>}
          {warning && <div className="sle-message sle-warning" role="status">{warning}</div>}
          <fieldset disabled={!editable || busy} className="sle-fields">
            <section className="sle-section"><h3>商家信息</h3><div className="sle-grid">
              <label className="sle-wide">商家名称 <span>*</span><Input aria-label="商家名称" maxLength={200} value={form.business_name} onChange={event => update({ business_name: event.target.value, verification: 'pending' })} placeholder="门店 / 商家名称"/></label>
              <label className="sle-wide">门店号码 <span>*</span><Input aria-label="门店号码" type="tel" inputMode="tel" maxLength={64} value={form.store_phone} onChange={event => update({ store_phone: event.target.value, verification: 'pending' })} placeholder="+1 (888) 888 8888"/><PhoneHint value={form.store_phone} country={form.country}/></label>
            </div></section>
            <section className="sle-section"><div className="sle-section-heading"><h3>联系人 <span>{form.contacts.length}</span></h3><Button type="button" variant="ghost" size="sm" disabled={!editable || busy || form.contacts.length >= 20} onClick={addContact}><Plus size={14}/>添加联系人</Button></div>
              {form.contacts.length === 0 ? <p className="sle-muted">可记录老板、经理或店员，之后选择首选联系人。</p> : <div className="sle-contacts">{form.contacts.map((contact, index) => <article key={contact.id} className="sle-contact" aria-label={`联系人 ${index + 1}`}>
                <div className="sle-contact-heading"><label><input type="radio" name={`sle-preferred-${leadId}`} aria-label={`首选联系人 ${index + 1}`} checked={form.preferred_contact_id === contact.id} onChange={() => update({ preferred_contact_id: contact.id })}/><span>{form.preferred_contact_id === contact.id ? '首选联系' : `联系人 ${index + 1}`}</span></label><button type="button" className="sle-icon-button" aria-label={`移除联系人 ${index + 1}`} onClick={() => update(removeEnrichmentContact(form, contact.id))}><Trash2 size={15}/></button></div>
                <div className="sle-grid"><label>姓名<Input aria-label={`联系人 ${index + 1} 姓名`} maxLength={120} value={contact.name || ''} onChange={event => updateContact(contact.id, { name: event.target.value, verification: 'pending' })}/></label><label>身份 / 职位<Input aria-label={`联系人 ${index + 1} 身份`} maxLength={80} value={contact.role || ''} onChange={event => updateContact(contact.id, { role: event.target.value, verification: 'pending' })} placeholder="老板 / 经理 / 店员"/></label><label className="sle-wide">手机 / 联系电话<Input aria-label={`联系人 ${index + 1} 电话`} type="tel" inputMode="tel" maxLength={64} value={contact.phone || ''} onChange={event => updateContact(contact.id, { phone: event.target.value, verification: 'pending' })} placeholder="带国家码的号码"/><PhoneHint value={contact.phone} country={form.country}/></label></div>
                <div className="sle-contact-bottom"><details><summary>邮箱、微信</summary><div className="sle-grid"><label>邮箱<Input aria-label={`联系人 ${index + 1} 邮箱`} type="email" maxLength={254} value={contact.email || ''} onChange={event => updateContact(contact.id, { email: event.target.value, verification: 'pending' })}/></label><label>微信<Input aria-label={`联系人 ${index + 1} 微信`} maxLength={120} value={contact.wechat || ''} onChange={event => updateContact(contact.id, { wechat: event.target.value, verification: 'pending' })}/></label></div></details><NativeSelect aria-label={`联系人 ${index + 1} 核实状态`} value={contact.verification} options={verificationOptions} onChange={next => updateContact(contact.id, { verification: next === 'confirmed' ? 'confirmed' : 'pending' })}/></div>
              </article>)}</div>}
              {form.preferred_contact_id && <button type="button" className="sle-text-button" onClick={() => update({ preferred_contact_id: null })}>取消首选，默认联系门店</button>}
            </section>
            <section className="sle-section"><h3>意向与需求</h3><div className="sle-product-options" role="group" aria-label="意向产品多选">{catalog.map(product => <label key={product.id} data-selected={form.interest_product_ids.includes(product.id)}><input type="checkbox" aria-label={`意向产品 ${product.name}`} checked={form.interest_product_ids.includes(product.id)} onChange={event => update({ interest_product_ids: event.target.checked ? [...new Set([...form.interest_product_ids, product.id])] : form.interest_product_ids.filter(id => id !== product.id) })}/>{form.interest_product_ids.includes(product.id) && <Check size={12}/>}<span>{product.name}</span></label>)}{form.interest_product_ids.filter(id => !catalog.some(product => product.id === id)).map(id => <label key={id} data-selected="true"><input type="checkbox" aria-label={`移除目录外产品 ${id}`} checked onChange={() => update({ interest_product_ids: form.interest_product_ids.filter(selected => selected !== id) })}/><span>目录外产品 #{id}</span></label>)}</div>{!catalog.length && <p className="sle-muted">产品目录暂无可选项，已选产品会保留。</p>}<label className="sle-need-label">真实需求<Textarea aria-label="真实需求" rows={3} maxLength={4000} value={form.need_summary || ''} onChange={event => update({ need_summary: event.target.value })} placeholder="想解决什么、预算范围、约定的下一步…"/></label></section>
            <details className="sle-more"><summary>更多资料 <span>地址、网站与联系时间</span><ChevronDown size={15}/></summary><div className="sle-grid">
              {([['industry', '行业'], ['country', '国家 / 地区'], ['city', '城市'], ['state', '州 / 省'], ['address', '街道地址'], ['website', '网站'], ['best_contact_time', '适合联系时间']] as const).map(([key, label]) => <label key={key} className={['address', 'website', 'best_contact_time'].includes(key) ? 'sle-wide' : ''}>{label}<Input aria-label={label} maxLength={key === 'website' ? 1000 : key === 'address' ? 500 : key === 'best_contact_time' ? 300 : key === 'country' ? 80 : 120} value={form[key] || ''} onChange={event => update({ [key]: event.target.value, ...(key === 'country' ? { verification: 'pending' } : {}) })} placeholder={key === 'country' ? '例如 US / CN' : key === 'best_contact_time' ? '例如商家当地周二 14:00–16:00' : undefined}/></label>)}
            </div></details>
            <section className="sle-source-grid"><label>资料来源<NativeSelect aria-label="资料来源" value={form.source} options={[{ value: 'call', label: '本次通话' }, { value: 'manual', label: '手动补全' }]} onChange={source => update({ source: source === 'manual' ? 'manual' : 'call' })}/></label><label>商家资料状态<NativeSelect aria-label="商家资料核实状态" value={form.verification} options={verificationOptions} onChange={next => update({ verification: next === 'confirmed' ? 'confirmed' : 'pending' })}/></label></section>
          </fieldset>
          {value?.updated_at && <p className="sle-muted sle-updated">{value.updated_by_name || '操作人员'} · {dateText(value.updated_at)} 更新</p>}
          {validation.length > 0 && <ul className="sle-message sle-error" role="alert">{validation.map(message => <li key={message}>{message}</li>)}</ul>}
        </>}
      </div>
      <footer className="sle-footer"><p role="status">{draftNotice || (dirty ? '关闭面板可保留本次输入，尚未写入系统。' : '资料保存与沟通结果分别记录。')}</p><div><Button variant="outline" type="button" disabled={busy} onClick={close}>{dirty ? '暂存并关闭' : '关闭'}</Button>{tab === 'history' ? <Button type="button" variant="outline" onClick={() => setTab('edit')}>返回资料</Button> : <Button type="button" disabled={!editable || busy || loading || !form} onClick={() => void save()}><Save size={15}/>{busy ? '保存中…' : '保存资料，继续沟通'}</Button>}</div></footer>
    </SheetContent>
  </Sheet>;
}
