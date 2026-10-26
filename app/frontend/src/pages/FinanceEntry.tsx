import { useCallback, useEffect, useRef, useState, type ComponentProps } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { ArrowUpRight, CheckCircle2, ChevronLeft, ChevronRight, Download, FilePenLine, LockKeyhole, Paperclip, Plus, RefreshCw, Trash2 } from 'lucide-react';
import { useRole } from '@/lib/role-context';
import { useHardNavigationBlock, useUnsavedChanges } from '@/lib/use-unsaved-changes';
import { financeEntryApi, financeEntryError, financeEntryErrorStatus, financeEntryRequestId, financeEntryStatusLabels, editableFinanceEntry, uploadFinanceEntryAttachment, downloadFinanceEntryAttachment, type FinanceEntryAttachment, type FinanceEntryAttachments, type FinanceEntryCustomer, type FinanceEntryDraft, type FinanceEntryKind, type FinanceEntryList, type FinanceEntryStatus } from '@/lib/finance-entry-api';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { NativeSelect } from '@/components/ui/native-select';
import { Dialog, DialogTitle, CrmFormDialogContent, CrmFormDialogHeader, CrmFormDialogBody, CrmFormDialogFooter } from '@/components/ui/dialog';
import './finance-entry.css';

type EntryForm = {
  customer_id: string; currency: string; product_name: string; income_type: string; amount_due: string; amount_paid: string;
  management_amount: string; ads_recharge_amount: string; payment_date: string; payment_method: string;
  billing_cycle: string; coverage_start: string; coverage_end: string; has_invoice: boolean; transaction_reference: string;
  notes: string; evidence_reference: string; expense_type: string; amount: string; expense_date: string;
  expense_month: string; expense_category: string; category: string; category_name: string;
};
const blankForm = (): EntryForm => ({ customer_id: '', currency: 'USD', product_name: '', income_type: 'management_fee', amount_due: '', amount_paid: '', management_amount: '', ads_recharge_amount: '', payment_date: '', payment_method: 'check', billing_cycle: '', coverage_start: '', coverage_end: '', has_invoice: false, transaction_reference: '', notes: '', evidence_reference: '', expense_type: 'other', amount: '', expense_date: '', expense_month: '', expense_category: '', category: 'other_company', category_name: '' });
const kindLabels: Record<FinanceEntryKind, string> = { manual_receipt: '手动收款', customer_expense: '客户支出', company_expense: '公司支出' };
const companyCategoryOptions = [{value:'internet',label:'网络费'},{value:'phone',label:'电话费'},{value:'rent',label:'租金'},{value:'software',label:'软件订阅'},{value:'ai_tools',label:'AI 工具'},{value:'cloud_services',label:'云服务'},{value:'operations_tools',label:'运营工具'},{value:'recruitment',label:'招聘'},{value:'travel',label:'差旅'},{value:'other_company',label:'其他公司支出'}];
const statuses: FinanceEntryStatus[] = ['draft', 'submitted', 'returned', 'posted', 'voided'];
const valueText = (value: unknown) => typeof value === 'string' || typeof value === 'number' ? String(value) : '';
const dateLabel = (value?: string | null) => value ? value.slice(0, 16).replace('T', ' ') : '未填写';
const money = (amount: unknown, currency: unknown) => {
  const number = Number(amount);
  if (!Number.isFinite(number)) return '金额待填写';
  try { return new Intl.NumberFormat('zh-CN', { style: 'currency', currency: valueText(currency) || 'USD' }).format(number); }
  catch { return `${valueText(currency)} ${number.toFixed(2)}`; }
};
function verifiedDraft(value: FinanceEntryDraft, expectedId?: number) {
  if (!value || !Number.isSafeInteger(value.id) || value.id < 1 || expectedId && value.id !== expectedId || !Number.isSafeInteger(value.revision) || !statuses.includes(value.status) || !['manual_receipt', 'customer_expense', 'company_expense'].includes(value.kind) || !value.payload || typeof value.payload !== 'object') throw new Error('登记返回内容尚未核对，请重新读取。');
  return value;
}
function formFromDraft(item: FinanceEntryDraft): EntryForm {
  const form = blankForm();
  for (const key of Object.keys(form) as Array<keyof EntryForm>) {
    if (key === 'customer_id') form.customer_id = item.customer_id == null ? '' : String(item.customer_id);
    else if (key === 'has_invoice') form.has_invoice = item.payload.has_invoice === true;
    else if (item.payload[key] != null) form[key] = valueText(item.payload[key]);
  }
  return form;
}
function payloadFromForm(form: EntryForm, kind: FinanceEntryKind) {
  const amount = (value: string) => value.trim() === '' ? null : Number(value);
  const common = { currency: kind === 'manual_receipt' ? 'USD' : form.currency, notes: form.notes.trim(), evidence_reference: form.evidence_reference.trim() };
  if (kind === 'manual_receipt') return { ...common, income_type: form.income_type, product_name: form.product_name.trim(), amount_due: amount(form.amount_due), amount_paid: amount(form.amount_paid), ...(form.management_amount !== '' ? { management_amount: amount(form.management_amount) } : {}), ...(form.ads_recharge_amount !== '' ? { ads_recharge_amount: amount(form.ads_recharge_amount) } : {}), payment_date: form.payment_date || null, payment_method: form.payment_method, billing_cycle: form.billing_cycle || null, coverage_start: form.coverage_start || null, coverage_end: form.coverage_end || null, has_invoice: form.has_invoice, transaction_reference: form.transaction_reference.trim() };
  if (kind === 'customer_expense') return { ...common, expense_type: form.expense_type, ...(form.expense_category.trim() ? { expense_category: form.expense_category.trim() } : {}), amount: amount(form.amount), expense_date: form.expense_date || null, expense_month: form.expense_month || null };
  return { ...common, category: form.category, category_name: form.category_name.trim() || companyCategoryOptions.find(option=>option.value===form.category)?.label || form.category, amount: amount(form.amount), expense_date: form.expense_date || null, expense_month: form.expense_month || null };
}

function EntrySelect({ options, value, ...props }: ComponentProps<typeof NativeSelect>) {
  const shown = options.some(option => option.value === value) ? options : [{ value, label: value || '未填写' }, ...options];
  return <NativeSelect {...props} value={value} options={shown}/>;
}

export default function FinanceEntry() {
  const { employee, systemRole, hasPermission, canAccess } = useRole();
  const owner = systemRole === 'super_admin';
  const registrar = systemRole === 'finance';
  const allowed = owner || registrar;
  const scope = `${employee?.id || ''}:${systemRole || ''}`;
  const [resolvedScope, setResolvedScope] = useState(scope);
  const canCreate = registrar && hasPermission('finance_draft_create');
  const canEdit = registrar && hasPermission('finance_draft_edit');
  const canSubmit = registrar && hasPermission('finance_draft_submit');
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const statusParam = params.get('status') || (owner ? 'submitted' : 'draft');
  const status = statuses.includes(statusParam as FinanceEntryStatus) ? statusParam : 'all';
  const page = Math.max(1, Number(params.get('page')) || 1);
  const limit = 20;
  const [list, setList] = useState<FinanceEntryList | null>(null);
  const [listLoading, setListLoading] = useState(false);
  const [listError, setListError] = useState('');
  const [editorOpen, setEditorOpen] = useState(false);
  const [item, setItem] = useState<FinanceEntryDraft | null>(null);
  const [kind, setKind] = useState<FinanceEntryKind>('manual_receipt');
  const [form, setForm] = useState<EntryForm>(blankForm);
  const [options, setOptions] = useState<FinanceEntryCustomer[]>([]);
  const [optionsReady, setOptionsReady] = useState(false);
  const [attachments, setAttachments] = useState<FinanceEntryAttachment[]>([]);
  const [attachmentsLoading, setAttachmentsLoading] = useState(false);
  const [attachmentsError, setAttachmentsError] = useState('');
  const [attachmentsReady, setAttachmentsReady] = useState(false);
  const [removeAttachmentId, setRemoveAttachmentId] = useState<number | null>(null);
  const [optionsError, setOptionsError] = useState('');
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState('');
  const [mutationError, setMutationError] = useState('');
  const [busy, setBusy] = useState('');
  const [leaveChoice, setLeaveChoice] = useState(false);
  const [ownerAction, setOwnerAction] = useState<'return' | 'post' | null>(null);
  const [reason, setReason] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  const [unknownResult, setUnknownResult] = useState(false);
  const [unknownPost, setUnknownPost] = useState(false);
  const listSequence = useRef(0), detailSequence = useRef(0), optionSequence = useRef(0), attachmentSequence = useRef(0);
  const busyRef = useRef(false);
  const activeDraftId = useRef<number | null>(null);
  const initialForm = useRef(JSON.stringify(blankForm()));
  const creationKey = useRef('');
  const attempt = useRef<{ key: string; request_id: string } | null>(null);
  const currentScope = useRef(scope); currentScope.current = scope;
  const writable = registrar && canEdit && (!item || editableFinanceEntry(item)) && !unknownResult;
  const dirty = editorOpen && ((writable && JSON.stringify(form) !== initialForm.current) || Boolean(ownerAction === 'return' && reason.trim()));
  const draftGuard = useUnsavedChanges(dirty);
  const navigationHold = useHardNavigationBlock(busy === 'post' || unknownPost);

  const loadList = useCallback(async (clear = false) => {
    if (!allowed) return;
    const request = ++listSequence.current, identity = scope;
    if (clear) setList(null);
    setListLoading(true); setListError('');
    try {
      const query = new URLSearchParams({ skip: String((page - 1) * limit), limit: String(limit) });
      if (status !== 'all') query.set('status', status);
      const result = await financeEntryApi<FinanceEntryList>(`?${query}`);
      if (request !== listSequence.current || currentScope.current !== identity) return;
      if (!Array.isArray(result?.items) || !Number.isSafeInteger(result.total)) throw new Error('登记列表返回不完整');
      result.items.forEach(row => { verifiedDraft(row); if (registrar && row.created_by_id !== Number(employee?.id)) throw new Error('登记范围不一致'); });
      setList(result);
    } catch (error) { if (request === listSequence.current && currentScope.current === identity) { if ([401,403,404].includes(financeEntryErrorStatus(error) || 0)) { setList(null); setItem(null); setAttachments([]); setDetailError('当前登记或客户授权已不可用，请重新读取。'); } setListError(financeEntryError(error)); } }
    finally { if (request === listSequence.current && currentScope.current === identity) setListLoading(false); }
  }, [allowed, scope, page, status]);

  useEffect(() => { void loadList(true); return () => { listSequence.current++; }; }, [loadList]);
  useEffect(() => {
    detailSequence.current++; optionSequence.current++; attachmentSequence.current++;
    setEditorOpen(false); setItem(null); setForm(blankForm()); setOptions([]); setOptionsReady(false); setAttachments([]); setAttachmentsReady(false); setAttachmentsError(''); setRemoveAttachmentId(null);
    setMutationError(''); setDetailError(''); setOwnerAction(null); setReason(''); setConfirmed(false); setUnknownResult(false); setUnknownPost(false);
    busyRef.current = false; setBusy(''); activeDraftId.current = null; attempt.current = null; navigationHold.release(); setResolvedScope(scope);
    return () => { detailSequence.current++; optionSequence.current++; attachmentSequence.current++; };
  }, [scope]);

  const hideDeniedDetail = (error: unknown) => {
    if (![401,403,404].includes(financeEntryErrorStatus(error) || 0)) return;
    setItem(null); setAttachments([]); setAttachmentsReady(false); setList(null); setListError('登记授权已变化，请重新读取列表。'); setDetailError('当前登记或客户授权已不可用，请重新读取。');
  };
  const loadOptions = async () => {
    if (!registrar) return;
    const request = ++optionSequence.current, identity = scope;
    setOptionsReady(false); setOptionsError(''); setOptions([]);
    try {
      const result = await financeEntryApi<{ items: FinanceEntryCustomer[] }>('/customer-options');
      if (request !== optionSequence.current || currentScope.current !== identity) return;
      if (!Array.isArray(result?.items)) throw new Error('客户选项返回不完整');
      setOptions(result.items); setOptionsReady(true);
    } catch (error) { if (request === optionSequence.current && currentScope.current === identity) { hideDeniedDetail(error); setOptionsError(financeEntryError(error, '授权客户暂时无法读取，请重试。')); } }
  };
  const loadAttachments = async (id: number, expectedRevision?: number) => {
    const request = ++attachmentSequence.current, identity = scope;
    setAttachmentsLoading(true); setAttachmentsError(''); setAttachmentsReady(false);
    try {
      const result = await financeEntryApi<FinanceEntryAttachments>(`/${id}/attachments`);
      if (request !== attachmentSequence.current || currentScope.current !== identity) return;
      if (!Array.isArray(result?.items) || !Number.isSafeInteger(result.draft_revision)) throw new Error('凭据列表返回不完整');
      if (expectedRevision !== undefined && result.draft_revision !== expectedRevision) { setUnknownResult(true); setMutationError('登记版本已变化，请重新读取当前登记后再处理凭据。'); setAttachmentsError('登记版本已变化，请重新读取当前登记后再处理凭据。'); return; }
      setAttachments(result.items); setAttachmentsReady(true);
    } catch (error) { if (request === attachmentSequence.current && currentScope.current === identity) { hideDeniedDetail(error); setAttachmentsError(financeEntryError(error, '私有凭据暂时无法读取，请重试。')); } }
    finally { if (request === attachmentSequence.current && currentScope.current === identity) setAttachmentsLoading(false); }
  };
  const openExisting = async (id: number, afterAttachment = false) => {
    if (busyRef.current && !afterAttachment) return;
    const request = ++detailSequence.current, identity = scope, recoveringUnknown = unknownResult;
    activeDraftId.current = id;
    setAttachments([]); setAttachmentsReady(false); setAttachmentsError(''); setRemoveAttachmentId(null); setEditorOpen(true); setDetailLoading(true); setDetailError(''); setItem(null); setMutationError(''); setOwnerAction(null); setReason(''); setConfirmed(false); setLeaveChoice(false);
    try {
      const result = verifiedDraft(await financeEntryApi<FinanceEntryDraft>(`/${id}`), id);
      if (registrar && result.created_by_id !== Number(employee?.id)) throw new Error('登记范围不一致');
      if (request !== detailSequence.current || currentScope.current !== identity) return;
      const nextForm = formFromDraft(result);
      setItem(result); setKind(result.kind); setForm(nextForm); initialForm.current = JSON.stringify(nextForm);
      setUnknownResult(false); setUnknownPost(false); navigationHold.release();
      if (recoveringUnknown) void loadList();
      void loadAttachments(id, result.revision);
      if (registrar && editableFinanceEntry(result)) void loadOptions();
    } catch (error) { if (request === detailSequence.current && currentScope.current === identity) setDetailError(financeEntryError(error)); }
    finally { if (request === detailSequence.current && currentScope.current === identity) setDetailLoading(false); }
  };
  const openNew = () => {
    if (!canCreate || busyRef.current) return;
    detailSequence.current++; attachmentSequence.current++; activeDraftId.current = null; setItem(null); setKind('manual_receipt'); const next = blankForm(); setForm(next); initialForm.current = JSON.stringify(next);
    creationKey.current = financeEntryRequestId(); attempt.current = null; setDetailLoading(false); setDetailError(''); setMutationError(''); setLeaveChoice(false); setOwnerAction(null); setUnknownResult(false); setAttachments([]); setAttachmentsReady(true); setAttachmentsError(''); setRemoveAttachmentId(null); setEditorOpen(true); void loadOptions();
  };
  const closeEditor = () => {
    if (busyRef.current || unknownPost) return;
    if (dirty) { setLeaveChoice(true); return; }
    setEditorOpen(false); setItem(null); activeDraftId.current = null; detailSequence.current++; optionSequence.current++; attachmentSequence.current++;
  };
  const validateForm = () => {
    if (kind !== 'company_expense' && (!optionsReady || !options.some(option => option.id === Number(form.customer_id)))) return '请选择当前仍授权的客户。';
    for (const field of kind === 'manual_receipt' ? ['amount_due', 'amount_paid', 'management_amount', 'ads_recharge_amount'] as const : ['amount'] as const) { if (form[field] && (!Number.isFinite(Number(form[field])) || Number(form[field]) < 0)) return '金额须为有效的非负数字。'; }
    return '';
  };
  const saveDraft = async (closeAfter = false): Promise<FinanceEntryDraft | null> => {
    if (!writable || busyRef.current || !canEdit) return null;
    const problem = validateForm(); if (problem) { setMutationError(problem); return null; }
    const identity = scope, previous = item; busyRef.current = true; setBusy('save'); setMutationError('');
    try {
      const payload = payloadFromForm(form, kind);
      const result = verifiedDraft(previous
        ? await financeEntryApi<FinanceEntryDraft>(`/${previous.id}`, 'PUT', { expected_revision: previous.revision, payload })
        : await financeEntryApi<FinanceEntryDraft>('', 'POST', { client_request_id: creationKey.current, kind, customer_id: kind === 'company_expense' ? null : Number(form.customer_id), payload }), previous?.id);
      if (currentScope.current !== identity) return null;
      if (result.kind !== kind || registrar && result.created_by_id !== Number(employee?.id) || result.customer_id !== (kind === 'company_expense' ? null : Number(form.customer_id))) throw new Error('保存的客户信息尚未核对');
      activeDraftId.current = result.id; setItem(result); const next = formFromDraft(result); setForm(next); initialForm.current = JSON.stringify(next); draftGuard.markSaved(); setLeaveChoice(false);
      if (closeAfter) setEditorOpen(false); else void loadAttachments(result.id, result.revision);
      void loadList(); return result;
    } catch (error) { if (currentScope.current === identity) { hideDeniedDetail(error); setMutationError(financeEntryError(error, '草稿保存结果尚未确认。请保留输入，重试保存或重新读取。')); } return null; }
    finally { if (currentScope.current === identity) { busyRef.current = false; setBusy(''); } }
  };
  const validateSubmission = () => {
    const keys: Array<keyof EntryForm> = kind === 'manual_receipt' ? ['income_type', 'product_name', 'amount_due', 'amount_paid', 'payment_date', ...(form.income_type === 'management_ads_mixed' ? ['management_amount', 'ads_recharge_amount'] as const : [])] : ['amount', 'expense_date', kind === 'company_expense' ? 'category' : 'expense_type'];
    if (keys.some(key => !String(form[key]).trim())) return '请先补齐必填的金额、类型和日期，再保存草稿后提交。';
    if (form.evidence_reference.trim().length < 3 && (!attachmentsReady || !attachments.length)) return '请填写至少 3 个字的凭据说明，或添加并读取有效私有附件后提交。';
    return '';
  };
  const uploadAttachment = async (file: File) => {
    if (!item || !writable || dirty || busyRef.current) return;
    if (file.size > 4 * 1024 * 1024 || !['application/pdf', 'image/jpeg', 'image/png', 'image/webp'].includes(file.type)) { setAttachmentsError('请使用 4MB 以内的 PDF、JPEG、PNG 或 WebP 文件。'); return; }
    const current = item, identity = scope; busyRef.current = true; setBusy('upload'); setAttachmentsError('');
    try {
      const result = await uploadFinanceEntryAttachment(current.id, current.revision, file);
      if (currentScope.current !== identity) return;
      if (!Number.isSafeInteger(result?.draft_revision) || !result.item?.id) throw new Error('凭据保存结果尚未确认');
      await openExisting(current.id, true);
    } catch (error) { if (currentScope.current === identity) { hideDeniedDetail(error); setAttachmentsError(financeEntryError(error, '凭据上传结果尚未确认，请重新读取登记与凭据列表后再处理。')); } }
    finally { if (currentScope.current === identity) { busyRef.current = false; setBusy(''); } }
  };
  const removeAttachment = async () => {
    if (!item || !removeAttachmentId || !writable || dirty || busyRef.current) return;
    const current = item, identity = scope; busyRef.current = true; setBusy('remove-attachment'); setAttachmentsError('');
    try {
      await financeEntryApi(`/${current.id}/attachments/${removeAttachmentId}?expected_revision=${current.revision}`, 'DELETE');
      if (currentScope.current !== identity) return;
      await openExisting(current.id, true);
    } catch (error) { if (currentScope.current === identity) { hideDeniedDetail(error); setAttachmentsError(financeEntryError(error, '凭据移除结果尚未确认，请重新读取后再继续。')); } }
    finally { if (currentScope.current === identity) { busyRef.current = false; setBusy(''); } }
  };
  const downloadAttachment = async (attachment: FinanceEntryAttachment) => {
    if (!item || busyRef.current) return;
    const current = item, identity = scope; busyRef.current = true; setBusy(`download-${attachment.id}`); setAttachmentsError('');
    try {
      const blob = await downloadFinanceEntryAttachment(current.id, attachment);
      if (currentScope.current !== identity) return;
      const url = URL.createObjectURL(blob), link = document.createElement('a');
      link.href = url; link.download = attachment.filename.replace(/[\/\\\x00-\x1f]/g, '_').slice(0, 160) || '财务凭据'; document.body.appendChild(link); link.click(); link.remove(); window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (error) { if (currentScope.current === identity) { hideDeniedDetail(error); setAttachmentsError(financeEntryError(error, '凭据下载失败，请重试。')); } }
    finally { if (currentScope.current === identity) { busyRef.current = false; setBusy(''); } }
  };
  const transition = async (action: 'submit' | 'return' | 'post') => {
    if (!item || busyRef.current || unknownResult || action === 'submit' && (!registrar || !canSubmit || !editableFinanceEntry(item) || dirty) || action !== 'submit' && (!owner || item.status !== 'submitted') || action === 'return' && reason.trim().length < 3 || action === 'post' && !confirmed) return;
    if (action === 'submit') { const problem = validateSubmission(); if (problem) { setMutationError(problem); return; } }
    const current = item, identity = scope, key = `${action}:${item.id}:${item.revision}`;
    if (attempt.current?.key !== key) attempt.current = { key, request_id: financeEntryRequestId() };
    busyRef.current = true; setBusy(action); setMutationError('');
    if (action === 'post') navigationHold.lock();
    try {
      const result = verifiedDraft(await financeEntryApi<FinanceEntryDraft>(`/${current.id}/${action}`, 'POST', { expected_revision: current.revision, request_id: attempt.current.request_id, ...(action === 'return' ? { reason: reason.trim() } : {}) }), current.id);
      if (currentScope.current !== identity) return;
      if (result.kind !== current.kind || result.customer_id !== current.customer_id || registrar && result.created_by_id !== Number(employee?.id)) throw new Error('登记返回范围尚未核对');
      setItem(result); setOwnerAction(null); setReason(''); setConfirmed(false); setUnknownResult(false); setUnknownPost(false); navigationHold.release(); attempt.current = null; draftGuard.markSaved(); void loadList();
    } catch (error) {
      if (currentScope.current !== identity) return;
      hideDeniedDetail(error);
      const status = financeEntryErrorStatus(error);
      const uncertain = !status || status >= 500;
      if (uncertain) { setUnknownResult(true); if (action === 'post') setUnknownPost(true); }
      if (action === 'post' && !uncertain) navigationHold.release();
      setMutationError(financeEntryError(error, action === 'post' ? '入账结果尚未确认，请重新读取，避免重复处理。' : '提交结果尚未确认，请重新读取后再继续。'));
    } finally { if (currentScope.current === identity) { busyRef.current = false; setBusy(''); } }
  };
  const changeStatus = (next: string, nextPage = 1) => { const query = new URLSearchParams(params); query.set('status', next); query.set('page', String(nextPage)); setParams(query); };
  const rowAmount = (row: FinanceEntryDraft) => row.payload[row.kind === 'manual_receipt' ? 'amount_paid' : 'amount'] == null ? '金额待填写' : money(row.payload[row.kind === 'manual_receipt' ? 'amount_paid' : 'amount'], row.payload.currency || 'USD');
  const patch = <K extends keyof EntryForm>(key: K, value: EntryForm[K]) => setForm(current => ({ ...current, [key]: value }));
  if (resolvedScope !== scope) return <div className="fe-page fe-empty" role="status">正在切换账号范围…</div>;
  if (!allowed) return <div className="fe-page fe-denied" role="alert"><LockKeyhole/><h1>当前账号没有财务登记权限</h1><p>请联系老板确认岗位与客户授权。</p></div>;
  const statusTabs = owner ? ['submitted', 'returned', 'posted', 'all'] : ['draft', 'submitted', 'returned', 'posted', 'all'];
  const readOnly = !writable || owner;

  return <div className="fe-page app-page">
    <header className="fe-header"><div><p className="fe-eyebrow">{owner ? '老板核对 · 公司正式账保持独立' : '财务登记 · 仅本人提交'}</p><h1>财务登记台</h1><p>{owner ? '核对登记与凭据，由你决定退回或确认入账。' : '先保存草稿，填写凭据后提交；正式入账由老板确认。'}</p></div><div className="fe-header-actions"><Button variant="outline" disabled={listLoading} onClick={() => void loadList()}><RefreshCw size={14} className={listLoading ? 'animate-spin' : ''}/>刷新</Button>{canCreate && <Button onClick={openNew}><Plus size={15}/>新建登记</Button>}</div></header>
    <div className="fe-scope" role="note"><LockKeyhole size={14}/><span>{owner ? '这里显示员工登记，不会自动入账。' : '仅显示本人草稿及当前仍获授权的客户。'} 不开放公司利润、工资、分润或私人空间。</span></div>
    <nav className="fe-tabs" aria-label="登记状态">{statusTabs.map(value => <button key={value} type="button" aria-current={status === value ? 'page' : undefined} onClick={() => changeStatus(value)}>{value === 'all' ? '全部登记' : financeEntryStatusLabels[value as FinanceEntryStatus]}</button>)}</nav>
    {listError && <div className="fe-notice is-error" role="alert"><p>{listError}{list ? ' 以下保留上次读取的记录，状态可能已变化。' : ''}</p><Button variant="outline" onClick={() => void loadList()} disabled={listLoading}>重新读取</Button></div>}
    <section className="fe-list" aria-label="登记记录" aria-busy={listLoading}>
      <div className="fe-list-heading"><h2>{owner && status === 'submitted' ? '等待你核对' : '登记记录'}</h2><span>{list ? `共 ${list.total} 条` : listLoading ? '正在读取…' : '尚未读取'}</span></div>
      {!list && listLoading ? <div className="fe-empty" role="status">正在读取登记记录…</div> : list && list.items.length === 0 && !listError ? <div className="fe-empty"><FilePenLine size={24}/><h3>当前状态暂无登记</h3><p>{canCreate ? '可以先建立草稿，稍后补齐后再提交。' : '员工提交后会出现在待核对列表。'}</p>{canCreate && <Button variant="outline" onClick={openNew}>新建登记</Button>}</div> : <div className="fe-records">{list?.items.map(row => <article className="fe-record" key={row.id}><div className="fe-record-title"><span className={`fe-status is-${row.status}`}>{financeEntryStatusLabels[row.status]}</span><h3>{row.kind === 'company_expense' ? '公司支出' : row.customer_name || `客户 #${row.customer_id}`}</h3><p>{kindLabels[row.kind]} · #{row.id}{owner ? ` · ${row.created_by_name || '登记员'}` : ''}</p>{row.status === 'returned' && row.return_reason && <p className="fe-return-reason">退回原因：{row.return_reason}</p>}</div><div className="fe-record-value"><small>登记金额</small><strong>{rowAmount(row)}</strong><span>{valueText(row.payload[row.kind === 'manual_receipt' ? 'payment_date' : 'expense_date']).slice(0, 10) || '日期待填写'}</span></div><Button variant="outline" onClick={() => void openExisting(row.id)}>{row.status === 'submitted' && owner ? '核对登记' : editableFinanceEntry(row) && registrar ? '继续填写' : '查看详情'}<ChevronRight size={14}/></Button></article>)}</div>}
      {list && list.total > 0 && <footer className="fe-pagination"><span>第 {page} / {Math.max(1, Math.ceil(list.total / limit))} 页 · 每页 {limit} 条</span><div><Button variant="outline" disabled={page <= 1 || listLoading} onClick={() => changeStatus(status, page - 1)}><ChevronLeft size={14}/>上一页</Button><Button variant="outline" disabled={page * limit >= list.total || listLoading} onClick={() => changeStatus(status, page + 1)}>下一页<ChevronRight size={14}/></Button></div></footer>}
    </section>
    <Dialog open={editorOpen} onOpenChange={open => { if (!open) closeEditor(); }}><CrmFormDialogContent className="fe-dialog max-w-2xl" onInteractOutside={event => { if (busy || dirty || unknownPost) { event.preventDefault(); if (dirty) setLeaveChoice(true); } }} onEscapeKeyDown={event => { if (busy || unknownPost) event.preventDefault(); }}><CrmFormDialogHeader><p className="fe-eyebrow">{item ? `登记 #${item.id} · ${financeEntryStatusLabels[item.status]}` : activeDraftId.current ? `登记 #${activeDraftId.current} · ${detailLoading ? '读取中' : '结果待确认'}` : '新建草稿 · 尚未提交'}</p><DialogTitle>{owner ? '核对财务登记' : item && !editableFinanceEntry(item) ? '查看登记' : '填写财务登记'}</DialogTitle><p className="fe-context">{!item && activeDraftId.current ? '正在核实该登记的最新状态' : kind === 'company_expense' ? '公司支出草稿 · 不开放公司原账簿' : item?.customer_name || '仅可选择老板已授权的客户'}{item && owner ? ` · 登记人 ${item.created_by_name || '未记录'}` : ''}</p></CrmFormDialogHeader><CrmFormDialogBody>
      {detailLoading ? <p className="fe-empty" role="status">正在读取登记详情…</p> : detailError ? <div className="fe-notice is-error" role="alert"><p>{detailError}</p><p>当前未显示旧登记内容，可按原登记编号重新读取。</p>{activeDraftId.current && <Button variant="outline" disabled={Boolean(busy)} onClick={() => void openExisting(activeDraftId.current!)}>重新读取当前登记</Button>}</div> : <>
      {leaveChoice && <div className="fe-notice" role="alert"><p>还有未保存的修改。保存到服务器草稿后，可稍后继续。</p><div className="fe-inline-actions"><Button variant="outline" onClick={() => setLeaveChoice(false)}>继续编辑</Button>{writable && <Button disabled={Boolean(busy)} onClick={() => void saveDraft(true)}>保存草稿并关闭</Button>}<Button variant="ghost" disabled={Boolean(busy) || unknownPost} onClick={() => { draftGuard.markSaved(); setLeaveChoice(false); setEditorOpen(false); }}>放弃本次修改</Button></div></div>}
      {mutationError && <div className="fe-notice is-error" role="alert"><p>{mutationError}</p>{activeDraftId.current && <Button variant="outline" disabled={Boolean(busy)} onClick={() => void openExisting(activeDraftId.current!)}>重新读取当前登记</Button>}</div>}
      {unknownResult && <p className="fe-notice" role="status">本次操作结果待确认，暂不能编辑或重复提交。请重新读取当前登记。</p>}
      {item?.return_reason && <div className="fe-notice is-returned"><strong>老板退回说明</strong><p>{item.return_reason}</p></div>}
      {item && !editableFinanceEntry(item) && <p className="fe-readonly"><LockKeyhole size={13}/>{item.status === 'submitted' ? '已提交，登记内容已锁定，等待老板核对。' : item.status === 'posted' ? '老板已确认入账，本登记不可修改。' : '本登记已作废，不再处理。'}</p>}
      {!readOnly && kind !== 'company_expense' && optionsError && <div className="fe-notice is-error" role="alert"><p>{optionsError}</p><Button variant="outline" onClick={() => void loadOptions()}>重新读取授权客户</Button></div>}
      {!readOnly && kind !== 'company_expense' && optionsReady && !options.length && <div className="fe-notice" role="status">暂无可登记客户。请老板先邀请你，并开放基础信息与收款明细查看权限。</div>}
      <fieldset className="fe-form" disabled={readOnly || Boolean(busy) || detailLoading}>
        <label className="fe-wide">登记类型<EntrySelect aria-label="登记类型" disabled={Boolean(item)} value={kind} onChange={value => setKind(value as FinanceEntryKind)} options={Object.entries(kindLabels).map(([value,label])=>({value,label}))}/></label>
        {kind !== 'company_expense' && <label className="fe-wide">客户 *{readOnly || item ? <Input aria-label="登记客户" value={item?.customer_name || ''} readOnly/> : <EntrySelect aria-label="登记客户" value={form.customer_id} onChange={value => patch('customer_id',value)} disabled={!optionsReady} options={[{value:'',label:optionsReady?'选择授权客户':'正在读取授权客户…'},...options.map(option=>({value:String(option.id),label:`${option.business_name}${option.customer_code?` · ${option.customer_code}`:''}`}))]}/>}</label>}
        {kind === 'manual_receipt' ? <>
          <label className="fe-wide">服务 / 收款用途<Input aria-label="登记用途" maxLength={240} value={form.product_name} onChange={event=>patch('product_name',event.target.value)} placeholder="填写实际服务或产品名称"/></label>
          <label className="fe-wide">收入类型 *<EntrySelect aria-label="收入类型" value={form.income_type} onChange={value=>patch('income_type',value)} options={[{value:'management_fee',label:'管理费'},{value:'ads_fee',label:'投流费'},{value:'management_ads_mixed',label:'管理费 + 投流费（分别填写）'},{value:'website_fee',label:'网站费'},{value:'other_income',label:'其他收入'}]}/></label>
          <label>应收金额 · USD *<Input aria-label="应收金额" type="number" min="0" step="0.01" inputMode="decimal" value={form.amount_due} onChange={event=>patch('amount_due',event.target.value)}/></label>
          <label>实际收款 · USD *<Input aria-label="实际收款" type="number" min="0" step="0.01" inputMode="decimal" value={form.amount_paid} onChange={event=>patch('amount_paid',event.target.value)}/></label>
          {(form.income_type === 'management_ads_mixed' || form.management_amount !== '' || form.ads_recharge_amount !== '') && <><label>其中管理费 · USD<Input aria-label="其中管理费" type="number" min="0" step="0.01" value={form.management_amount} onChange={event=>patch('management_amount',event.target.value)}/></label><label>其中投流费 · USD<Input aria-label="其中投流费" type="number" min="0" step="0.01" value={form.ads_recharge_amount} onChange={event=>patch('ads_recharge_amount',event.target.value)}/></label></>}
          <label>实际收款日期 *<Input aria-label="实际收款日期" type="date" value={form.payment_date.slice(0,10)} onChange={event=>patch('payment_date',event.target.value)}/></label>
          <label>收款方式<EntrySelect aria-label="收款方式" value={form.payment_method} onChange={value=>patch('payment_method',value)} options={[{value:'check',label:'支票'},{value:'zelle',label:'Zelle'},{value:'apple_cash',label:'Apple Cash'},{value:'venmo',label:'Venmo'},{value:'wire',label:'电汇'},{value:'cash',label:'现金'},{value:'credit_card',label:'信用卡（人工核对）'},{value:'other',label:'其他'}]}/></label>
          <p className="fe-form-note fe-wide">仅登记手动收款。Stripe 自动扣款继续走原对账流程；欠款、扣点及净额由系统按原规则处理。</p>
          <details className="fe-wide fe-optional"><summary>服务周期与凭据编号（选填）</summary><div className="fe-form">
            <label>服务周期<EntrySelect aria-label="服务周期" value={form.billing_cycle} onChange={value=>patch('billing_cycle',value)} options={[{value:'',label:'未填写'},{value:'monthly',label:'月付'},{value:'quarterly',label:'季付'},{value:'semi_annual',label:'半年付'},{value:'annual',label:'年付'},{value:'one_time',label:'一次性'}]}/></label>
            <label>收款参考编号<Input aria-label="收款参考编号" maxLength={240} value={form.transaction_reference} onChange={event=>patch('transaction_reference',event.target.value)}/></label>
            <label>覆盖开始日期<Input aria-label="覆盖开始日期" type="date" value={form.coverage_start.slice(0,10)} onChange={event=>patch('coverage_start',event.target.value)}/></label>
            <label>覆盖结束日期<Input aria-label="覆盖结束日期" type="date" value={form.coverage_end.slice(0,10)} onChange={event=>patch('coverage_end',event.target.value)}/></label>
            <label className="fe-confirm fe-wide"><input type="checkbox" checked={form.has_invoice} onChange={event=>patch('has_invoice',event.target.checked)}/><span>已核对发票</span></label>
          </div></details>
        </> : <>
          {kind === 'customer_expense' ? <label className="fe-wide">费用类型 *<EntrySelect aria-label="客户费用类型" value={form.expense_type} onChange={value=>patch('expense_type',value)} options={[{value:'website_fee',label:'网站费用'},{value:'domain_fee',label:'域名费用'},{value:'hosting_fee',label:'托管费用'},{value:'design_fee',label:'设计费用'},{value:'other',label:'其他客户支出'}]}/></label> : <><label>公司支出分类 *<EntrySelect aria-label="公司支出分类" value={form.category} onChange={value=>setForm(current=>({...current,category:value,category_name:companyCategoryOptions.find(option=>option.value===value)?.label||value}))} options={companyCategoryOptions}/></label><label>分类名称<Input aria-label="公司支出分类名称" value={form.category_name || companyCategoryOptions.find(option=>option.value===form.category)?.label || form.category} readOnly/><small>用途或支出明细请填在补充备注。</small></label></>}
          {kind === 'customer_expense' && form.expense_category && <label className="fe-wide">已登记费用子分类<Input aria-label="已登记费用子分类" value={form.expense_category} readOnly/></label>}
          <label>支出金额 *<Input aria-label="支出金额" type="number" min="0" step="0.01" inputMode="decimal" value={form.amount} onChange={event=>patch('amount',event.target.value)}/></label>
          <label>支出币种<EntrySelect aria-label="支出币种" value={form.currency} onChange={value=>patch('currency',value)} options={[{value:'USD',label:'USD 美元'},{value:'CNY',label:'CNY 人民币'}]}/></label>
          <label>实际支出日期 *<Input aria-label="实际支出日期" type="date" value={form.expense_date.slice(0,10)} onChange={event=>patch('expense_date',event.target.value)}/></label>
          <label>费用归属月份<Input aria-label="费用归属月份" type="month" value={form.expense_month} onChange={event=>patch('expense_month',event.target.value)}/></label>
          {kind === 'company_expense' && <p className="fe-form-note fe-wide">仅填写本次支出草稿。不会开放公司的支出账簿、工资或利润。</p>}
        </>}
        <label className="fe-wide">凭据说明 / 编号<Textarea aria-label="凭据说明" rows={3} maxLength={1000} value={form.evidence_reference} onChange={event=>patch('evidence_reference',event.target.value)} placeholder="记录支票号、转账参考号或可核对的真实依据"/><small>提交时须有至少 3 个字的凭据说明，或已保存的有效私有附件。</small></label>
        <label className="fe-wide">补充备注<Textarea aria-label="登记备注" rows={3} maxLength={3000} value={form.notes} onChange={event=>patch('notes',event.target.value)}/></label>
      </fieldset>
      <section className="fe-attachments" aria-label="私有凭据附件"><div className="fe-list-heading"><h3><Paperclip size={14}/>私有凭据</h3>{item && <Button variant="ghost" size="sm" disabled={Boolean(busy)||attachmentsLoading} onClick={()=>void loadAttachments(item.id, item.revision)}>重新读取</Button>}</div><p className="fe-form-note">PDF、JPEG、PNG、WebP，每件最多 4MB；每份登记累计最多 12 件、10MB。凭据通过当前账号验证后读取，不提供公开链接。</p>{!item ? <p className="fe-notice">先保存草稿，再添加私有凭据。保存后关闭页面，草稿仍会保留。</p> : <>
        {attachmentsError && <div className="fe-notice is-error" role="alert">{attachmentsError}</div>}
        {attachmentsLoading ? <p role="status" className="fe-form-note">正在读取私有凭据…</p> : attachmentsReady && !attachments.length && !attachmentsError ? <p className="fe-form-note">尚未添加附件，可添加文件或填写上方凭据说明。</p> : null}
        {attachments.map(attachment=><article className="fe-attachment-row" key={attachment.id}><div><strong>{attachment.filename}</strong><small>{(attachment.byte_size/1024).toFixed(1)} KB · {dateLabel(attachment.created_at)}</small></div><div><Button variant="outline" size="sm" disabled={Boolean(busy)} aria-label={`下载凭据：${attachment.filename}`} onClick={()=>void downloadAttachment(attachment)}><Download size={13}/>下载</Button>{writable&&<Button variant="ghost" size="sm" disabled={Boolean(busy)||dirty} aria-label={`移除凭据：${attachment.filename}`} onClick={()=>setRemoveAttachmentId(attachment.id)}><Trash2 size={13}/></Button>}</div></article>)}
        {removeAttachmentId && <div className="fe-notice" role="alert"><p>移除此凭据后，本次登记将不再使用它作为有效附件；历史证据仍按系统规则保留。</p><div className="fe-inline-actions"><Button variant="outline" disabled={Boolean(busy)} onClick={()=>setRemoveAttachmentId(null)}>保留凭据</Button><Button disabled={Boolean(busy)||dirty} onClick={()=>void removeAttachment()}>确认移除</Button></div></div>}
        {writable && <><label className={`fe-upload ${busy||dirty?'is-disabled':''}`}><Paperclip size={14}/>添加私有凭据<input type="file" aria-label="添加私有凭据" accept="application/pdf,image/jpeg,image/png,image/webp" disabled={Boolean(busy)||dirty} onChange={event=>{const file=event.target.files?.[0];event.target.value='';if(file)void uploadAttachment(file);}}/></label>{dirty&&<p className="fe-form-note">请先保存当前修改，再添加或移除凭据。</p>}</>}
      </>}</section>
      {owner && item?.status === 'submitted' && <section className="fe-owner-review" aria-label="老板核对操作"><h3>核对后决定</h3><p>登记不会自行成为正式账。确认入账前，请核对客户、实收/支出、日期、方式与凭据。</p>{ownerAction === 'return' ? <><label>退回原因 *<Textarea aria-label="退回原因" value={reason} maxLength={1000} onChange={event => setReason(event.target.value)} placeholder="告诉登记员需要补充或修正什么"/></label><div className="fe-inline-actions"><Button variant="outline" disabled={Boolean(busy)} onClick={()=>{setOwnerAction(null);setReason('');}}>取消退回</Button><Button disabled={Boolean(busy)||reason.trim().length<3||unknownResult} onClick={()=>void transition('return')}>确认退回</Button></div></> : ownerAction === 'post' ? <><label className="fe-confirm"><input type="checkbox" checked={confirmed} disabled={Boolean(busy)} onChange={event=>setConfirmed(event.target.checked)}/><span>我已核对真实收支与凭据，确认按公司现有规则入账。</span></label><div className="fe-inline-actions"><Button variant="outline" disabled={Boolean(busy)||unknownPost} onClick={()=>{setOwnerAction(null);setConfirmed(false);}}>继续核对</Button><Button disabled={!confirmed||Boolean(busy)||unknownResult} onClick={()=>void transition('post')}>{busy==='post'?'正在确认…':'确认入账'}</Button></div></> : <div className="fe-inline-actions"><Button variant="outline" disabled={Boolean(busy)||unknownResult} onClick={()=>setOwnerAction('return')}>退回补充</Button><Button disabled={Boolean(busy)||unknownResult} onClick={()=>setOwnerAction('post')}>已核对，准备入账</Button></div>}</section>}
      {owner && item?.status === 'posted' && canAccess('/finance') && <Button variant="outline" onClick={()=>navigate(`/finance?tab=${item.kind==='manual_receipt'?'income':item.kind==='company_expense'?'company_expense':'customer_expense'}${item.customer_id ? `&customer_id=${item.customer_id}` : ''}`)}>查看原财务账本<ArrowUpRight size={14}/></Button>}
      </>}
    </CrmFormDialogBody><CrmFormDialogFooter><Button variant="outline" disabled={Boolean(busy)||unknownPost} onClick={closeEditor}>关闭</Button>{!detailLoading&&!detailError&&writable&&<><Button variant="outline" disabled={Boolean(busy)||(kind!=='company_expense'&&!optionsReady)} onClick={()=>void saveDraft()}>{busy==='save'?'保存中…':'保存草稿'}</Button>{item&&canSubmit&&<Button disabled={Boolean(busy)||dirty||unknownResult} onClick={()=>void transition('submit')}>{busy==='submit'?'提交中…':'提交老板核对'}</Button>}</>}{item?.status==='posted'&&<span className="fe-posted-label"><CheckCircle2 size={14}/>已入账</span>}</CrmFormDialogFooter></CrmFormDialogContent></Dialog>
  </div>;
}
