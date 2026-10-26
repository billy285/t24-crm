import { useEffect, useRef, useState } from 'react';
import { toast } from 'sonner';
import { CheckCircle2, ChevronDown, History, LockKeyhole, PencilLine, RefreshCw, ShieldCheck, UserRound, Users } from 'lucide-react';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { NativeSelect } from '@/components/ui/native-select';
import SalesLeadQuickEdit from '@/components/SalesLeadQuickEdit';
import SalesLeadDossierProgress from '@/components/SalesLeadDossierProgress';
import { formatPhoneNumber } from '@/lib/phone-format';
import { useRole } from '@/lib/role-context';
import { invokeWithAuth } from '@/lib/tokenStore';
import { salesDate, salesError } from '@/lib/sales-intelligence';
import { enrichmentFieldLabels, toEnrichmentUpdate, type EnrichmentUpdate } from '@/lib/sales-lead-enrichment';
import { dossierApi, type DossierSummary, type SalesDossier } from '@/lib/sales-lead-dossier';
import { dossierQualityHints } from '@/components/sales-dossier-quality';
import './sales-lead-dossier.css';

type Tab = 'overview' | 'contacts' | 'history' | 'ownership';
type SummaryDraft = Pick<DossierSummary, 'objections' | 'promises' | 'latest_conclusion'>;
const text = (value: unknown) => typeof value === 'string' && value.trim() ? value : '待补充';
const summaryDraft = (summary: DossierSummary): SummaryDraft => ({ objections: summary.objections || '', promises: summary.promises || '', latest_conclusion: summary.latest_conclusion || '' });
const safeUrl = (value: string | null | undefined) => value && /^https?:\/\//i.test(value) ? value : null;
const handoffText = (value: SalesDossier['handoffs'][number]) => [value.note || value.handoff_summary, ...Object.entries(value.summary || {}).filter(([key, item]) => ['need_summary', 'objections', 'promises', 'next_step', 'decision_maker', 'latest_conclusion', 'next_action_at'].includes(key) && item).map(([key,item]) => `${({ need_summary:'需求',objections:'顾虑',promises:'已承诺',next_step:'下一步',decision_maker:'决策人',latest_conclusion:'沟通结论',next_action_at:'下次联系' } as Record<string,string>)[key]}：${key === 'next_action_at' ? salesDate(String(item)) : item}`)].filter(Boolean).join('\n');

/** All invited access stays on dossier endpoints; it never widens the calling/customer scopes. */
export default function SalesLeadDossier({ leadId, onClose, onSaved }: { leadId: number | null; onClose: () => void; onSaved?: () => void }) {
  const { employee } = useRole();
  const [data, setData] = useState<SalesDossier | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [tab, setTab] = useState<Tab>('overview');
  const [historyTab, setHistoryTab] = useState<'contact' | 'changes'>('contact');
  const [profileDirty, setProfileDirty] = useState(false);
  const [summaryEditing, setSummaryEditing] = useState(false);
  const [form, setForm] = useState<SummaryDraft | null>(null);
  const [quickEditOpen, setQuickEditOpen] = useState(false);
  const [enrichmentDraft, setEnrichmentDraft] = useState<EnrichmentUpdate | null>(null);
  const [saving, setSaving] = useState('');
  const [actionError, setActionError] = useState('');
  const [discardConfirm, setDiscardConfirm] = useState(false);
  const [inviteId, setInviteId] = useState('');
  const [inviteAccess, setInviteAccess] = useState<'view' | 'collaborate'>('view');
  const [invitePreview, setInvitePreview] = useState(false);
  const [revokeId, setRevokeId] = useState<number | null>(null);
  const [transferOpen, setTransferOpen] = useState(false);
  const [transfer, setTransfer] = useState({ assigned_sales_id: '', reason: '', handoff_summary: '', confirm_protected_transfer: false });
  const [releaseOpen, setReleaseOpen] = useState(false);
  const [release, setRelease] = useState({ phone: '', reason: '', resume_lead: false });
  const requestId = useRef(0);
  const busyRef = useRef(false);
  const scopeKey = `${employee?.id || 'unknown'}:${leadId || 'none'}`;
  const currentScope = useRef(scopeKey);
  currentScope.current = scopeKey;
  const currentLead = useRef(leadId);
  currentLead.current = leadId;

  const load = async (id = leadId, reset = false) => {
    if (!id) return;
    const request = ++requestId.current;
    setLoading(true); setError('');
    if (reset) setData(null);
    try {
      const result = await dossierApi<SalesDossier>(`/${id}`);
      if (request !== requestId.current || currentLead.current !== id) return;
      if (result.insight.id !== id || result.enrichment.lead_id !== id) throw new Error('商家档案不一致，请重新读取');
      setData(result); setForm(summaryDraft(result.summary)); setEnrichmentDraft(null);
    } catch (e) {
      if (request === requestId.current && currentLead.current === id) { setError(salesError(e)); setData(null); }
    } finally { if (request === requestId.current) setLoading(false); }
  };
  useEffect(() => {
    requestId.current += 1; setData(null); setError(''); setActionError(''); setForm(null); setTab('overview');
    setSummaryEditing(false); setProfileDirty(false); setQuickEditOpen(false); setEnrichmentDraft(null); setDiscardConfirm(false);
    setInviteId(''); setInviteAccess('view'); setInvitePreview(false); setRevokeId(null); setTransferOpen(false); setReleaseOpen(false);
    setTransfer({ assigned_sales_id: '', reason: '', handoff_summary: '', confirm_protected_transfer: false });
    setRelease({ phone: '', reason: '', resume_lead: false });
    if (leadId) void load(leadId, true);
    return () => { requestId.current += 1; };
  }, [leadId, employee?.id]);

  const enrichmentDirty = Boolean(data && enrichmentDraft && JSON.stringify(enrichmentDraft) !== JSON.stringify(toEnrichmentUpdate(data.enrichment, 'manual')));
  const summaryDirty = Boolean(summaryEditing && data && form && JSON.stringify(form) !== JSON.stringify(summaryDraft(data.summary)));
  const close = () => { if (busyRef.current) return; if (enrichmentDirty || summaryDirty || profileDirty) { setDiscardConfirm(true); return; } onClose(); };
  async function mutate(key: string, action: () => Promise<unknown>, message: string) {
    if (!leadId || busyRef.current) return false;
    const id = leadId; const mutationScope = currentScope.current; busyRef.current = true; setSaving(key); setActionError('');
    try {
      await action();
      if (currentLead.current !== id || currentScope.current !== mutationScope) return false;
      toast.success(message);
      setSummaryEditing(false); setQuickEditOpen(false); setEnrichmentDraft(null);
      setInvitePreview(false); setInviteId(''); setRevokeId(null); setTransferOpen(false); setReleaseOpen(false);
      await load(id); onSaved?.(); return true;
    } catch (e) { if (currentLead.current === id && currentScope.current === mutationScope) setActionError(salesError(e)); return false; }
    finally { busyRef.current = false; if (currentLead.current === id && currentScope.current === mutationScope) setSaving(''); }
  }
  async function saveSummary() {
    if (!data || !form || !data.permissions.can_edit_summary) return;
    await mutate('summary', () => dossierApi(`/${data.insight.id}/summary`, 'PUT', { ...form, expected_revision: data.summary.revision }), '跟进摘要已保存');
  }
  const changeTab = (next: Tab) => { if (summaryDirty || enrichmentDirty || profileDirty) { setActionError('请先保存或取消当前修改，再切换档案视图。'); return; } if (!saving) { setTab(next); setActionError(''); } };
  const primary = data?.insight.owner || '待分配';
  const enrichment = data?.enrichment;
  const pendingHandoff = data?.handoffs.find(item => !item.acknowledged_at && (!item.status || item.status === 'pending') && item.to_employee_id === employee?.id);
  const activeGrants = data?.grants.filter(grant => !grant.status || grant.status === 'active') || [];
  const activeInvite = data?.candidates.find(candidate => String(candidate.id) === inviteId);
  const grantAccess = data?.grants.find(grant => grant.employee_id === employee?.id && (!grant.status || grant.status === 'active'))?.access;
  const isInvited = grantAccess && !data?.permissions.can_edit_profile;
  const candidateOptions = data?.candidates.filter(candidate => candidate.id !== data.insight.owner_id).map(candidate => ({ value: String(candidate.id), label: candidate.name })) || [];
  const summaryFields = [ ['latest_conclusion', '最近沟通结论'], ['need_summary', '商家需求'], ['objections', '主要顾虑'], ['promises', '已承诺事项'], ['decision_maker', '参与人／决策人'], ['next_step', '下一步'] ] as const;
  const qualityHints = data ? dossierQualityHints(data) : [];

  return <>
    <Dialog open={leadId !== null} onOpenChange={open => { if (!open) close(); }}>
      <DialogContent className="sales-center-ui sales-dossier-dialog" onInteractOutside={event => { if (saving || quickEditOpen) event.preventDefault(); }} onEscapeKeyDown={event => { if (quickEditOpen || saving) event.preventDefault(); }}>
        <DialogHeader className="sd-header"><span className="sd-eyebrow">销售中心 · 商家档案</span><DialogTitle className="sd-title">{data?.enrichment.business_name || '商家档案'}</DialogTitle><DialogDescription className="sr-only">查看最新商家资料、累计沟通、交接与协作权限。</DialogDescription>{data && <div className="sd-meta"><span>{enrichment?.industry || '待分类'} · {[enrichment?.city, enrichment?.state].filter(Boolean).join(', ') || '地区待核实'}</span><span>档案 #{data.insight.id}{data.original?.id ? ` · 采集 #${data.original.id}` : ''}</span><span className={`sd-verification ${enrichment?.verification === 'confirmed' ? 'is-confirmed' : ''}`}>{enrichment?.verification === 'confirmed' ? '资料已核实' : '资料待核实'}</span>{isInvited && <span><LockKeyhole size={12}/>{grantAccess === 'collaborate' ? '受邀协作' : '受邀查看'}</span>}</div>}</DialogHeader>
        <div className="sd-body" aria-busy={loading || Boolean(saving)}>
          {discardConfirm && <div className="sd-confirm" role="alert">有尚未保存的资料，关闭后将放弃这些修改。<div className="sd-actions"><Button size="sm" variant="outline" onClick={() => setDiscardConfirm(false)}>继续编辑</Button><Button size="sm" onClick={() => { setDiscardConfirm(false); onClose(); }}>放弃修改并关闭</Button></div></div>}
          {error ? <div className="sd-error" role="alert">{error}<Button variant="ghost" size="sm" onClick={() => void load()}>重新读取</Button></div> : !data ? <p className="sd-empty" role="status">正在汇总最新资料与累计记录…</p> : <>
            {pendingHandoff && data.permissions.can_ack && <section className="sd-ack" aria-label="待确认交接"><h3>请先阅读交接内容</h3><p>{handoffText(pendingHandoff) || '请核对累计记录与联系安排。'}</p><p className="sd-handoff-reason">转交原因：{pendingHandoff.reason || '未填写'}</p><Button size="sm" disabled={Boolean(saving)} onClick={() => void mutate('ack', () => dossierApi(`/${data.insight.id}/handoffs/${pendingHandoff.id}/ack`, 'POST', {}), '已确认接收交接')}><CheckCircle2 size={14}/>已阅读，确认接收</Button></section>}
            <div className="sd-snapshot" aria-label="跟进概况"><div className="sd-primary-owner"><span className="sd-label">主要负责人</span><strong><UserRound size={14}/>{primary}</strong></div><div><span className="sd-label">最近联系 · 北京时间</span><strong>{salesDate(data.insight.last_contact_at)}</strong><small className="sd-source-label">来源：跟进档案的最近联系时间</small></div><div><span className="sd-label">约定下次联系 · 北京时间</span><strong>{data.summary.next_action_at || data.insight.next_follow_up_at ? salesDate(data.summary.next_action_at || data.insight.next_follow_up_at) : '尚未约定'}</strong><small className="sd-source-label">沿用原有跟进安排</small></div></div>
            <div className={`sd-protection ${data.protection.can_contact ? '' : 'is-blocked'}`} role="status">{data.protection.can_contact ? <ShieldCheck size={15}/> : <LockKeyhole size={15}/>}<div>{data.protection.reason || (data.protection.can_contact ? '由主要负责人安排联系，协作人员先与负责人协调。' : '当前暂停联系，请核对保护状态。')}{data.protection.cooldown_until && <span> · 至 {salesDate(data.protection.cooldown_until)}</span>}</div></div>
            <nav className="sd-tabs" aria-label="商家档案视图">{([['overview','概览'],['contacts','联系人'],['history','累计记录'],['ownership','归属与协作']] as const).map(([value,label]) => <button key={value} type="button" aria-pressed={tab === value} onClick={() => changeTab(value)}>{label}</button>)}</nav>
            {actionError && <div className="sd-error" role="alert">{actionError}<span className="block">输入已保留。若资料已被其他人修改，请核对后重新读取。</span></div>}
            {tab === 'overview' && <>
              <div className="sd-section-heading"><h3>跟进接力</h3><div className="sd-heading-tools">{data.permissions.can_edit && <Button size="sm" variant="outline" disabled={Boolean(saving) || summaryDirty || profileDirty} onClick={() => { setActionError(''); setQuickEditOpen(true); }}><PencilLine size={13}/>补充资料</Button>}{data.permissions.can_edit_summary && !summaryEditing && <Button size="sm" variant="outline" disabled={Boolean(saving) || profileDirty} onClick={() => setSummaryEditing(true)}>更新摘要</Button>}<Button size="sm" variant="ghost" disabled={Boolean(saving) || summaryDirty || enrichmentDirty || profileDirty} aria-label="重新读取商家档案" onClick={() => void load()}><RefreshCw size={13}/></Button></div></div>
              {qualityHints.length > 0 && <section className="sd-quality" aria-label="资料补充提示"><div className="sd-quality-items">{qualityHints.map(hint => <span key={hint.key} className={`sd-quality-hint is-${hint.kind}`} title={hint.detail}>{hint.label}</span>)}</div><p>{data.permissions.can_edit ? '联系人、号码和意向可点“补充资料”；下一步与联系时间沿用现有商机及跟进安排。' : '请由主要负责人补充；当前仅按已有授权查看或协作。'}联系保护保持不变。</p></section>}
              {summaryEditing && form ? <><fieldset disabled={Boolean(saving)} className="sd-form">{summaryFields.filter(([key]) => ['latest_conclusion','objections','promises'].includes(key)).map(([key,label]) => <label key={key} className={key === 'latest_conclusion' ? 'sd-wide' : ''}>{label}<Textarea aria-label={`摘要：${label}`} value={form[key as keyof SummaryDraft]} rows={2} maxLength={4000} onChange={event => setForm({ ...form, [key]: event.target.value })} placeholder="仅记录已确认的信息，未知可留空"/></label>)}<p className="sd-inline-note sd-wide">需求以最新补充资料为准，决策人与下一步沿用商机档案，约定联系时间沿用现有跟进安排。</p></fieldset><div className="sd-actions"><Button size="sm" variant="outline" disabled={Boolean(saving)} onClick={() => { setForm(summaryDraft(data.summary)); setSummaryEditing(false); setActionError(''); }}>取消摘要修改</Button><Button size="sm" disabled={Boolean(saving)} onClick={() => void saveSummary()}>{saving === 'summary' ? '保存中…' : '保存跟进摘要'}</Button></div></> : <><section className="sd-follow-through" aria-label="当前沟通结论与下一步"><div><span className="sd-label">最近沟通结论</span><p>{data.summary.latest_conclusion.trim() ? data.summary.latest_conclusion : '尚未记录沟通结论'}</p><small className="sd-source-label">来源：跟进摘要{data.summary.updated_at ? ` · ${data.summary.updated_by_name || '操作人员'}于 ${salesDate(data.summary.updated_at)} 更新` : ''}</small></div><div className="sd-next-step"><span className="sd-label">下一步</span><p>{data.summary.next_step.trim() ? data.summary.next_step : '尚未填写下一步'}</p><small className="sd-source-label">来源：商机档案 · 由主要负责人安排</small></div></section><dl className="sd-facts">{summaryFields.filter(([key]) => !['latest_conclusion', 'next_step'].includes(key)).map(([key,label]) => <div key={key}><dt>{label}</dt><dd className={!data.summary[key] ? 'sd-muted' : ''}>{text(data.summary[key])}</dd></div>)}</dl></>}
              <section className="sd-section"><h3>最新商家资料</h3><dl className="sd-facts"><div><dt>门店电话</dt><dd>{formatPhoneNumber(enrichment?.store_phone, enrichment?.country)}</dd></div><div><dt>适合联系时间</dt><dd>{text(enrichment?.best_contact_time)}</dd></div><div className="sd-wide"><dt>完整地址</dt><dd>{text([enrichment?.address, enrichment?.city, enrichment?.state, enrichment?.country].filter(Boolean).join(', '))}</dd></div><div className="sd-wide"><dt>商家网站</dt><dd>{safeUrl(enrichment?.website) ? <a className="sd-safe-link" target="_blank" rel="noopener noreferrer" href={safeUrl(enrichment?.website)!}>{enrichment?.website}</a> : text(enrichment?.website)}</dd></div></dl>{enrichment?.updated_at && <p className="sd-inline-note">{enrichment.updated_by_name || '操作人员'} · {salesDate(enrichment.updated_at)} 更新资料</p>}</section>
              {data.permissions.can_edit_profile && <details className="sd-progress"><summary><ChevronDown size={13}/>商机阶段与主管复核</summary><SalesLeadDossierProgress key={`${data.insight.id}:${data.insight.revision}`} data={data.insight} canonicalNeed={data.summary.need_summary} onDirtyChange={setProfileDirty} onSaved={() => { void load(); onSaved?.(); }}/></details>}
              {data.original && <details className="sd-original"><summary><ChevronDown size={13}/>原始采集资料 · 保留来源</summary><dl className="sd-facts">{[['采集商家名称',data.original.business_name],['采集联系人',data.original.contact_name],['原始电话',data.original.phone],['原始行业',data.original.industry],['完整地址',[data.original.address,data.original.city,data.original.state].filter(Boolean).join(', ')],['资料来源',data.original.data_source],['采集时间',salesDate(data.original.collected_at)],['流转状态',data.original.pool_status === 'converted' ? '已转入销售跟进' : data.original.pool_status]].map(([label,value]) => <div key={label}><dt>{label}</dt><dd>{text(value)}</dd></div>)}{data.original.isolation_reason && data.original.pool_status !== 'converted' && <div className="sd-wide"><dt>隔离原因</dt><dd>{data.original.isolation_reason}</dd></div>}</dl><p className="sd-inline-note">原始采集记录保留，日常跟进以上方最新资料为准。</p></details>}
            </>}
            {tab === 'contacts' && <><div className="sd-section-heading"><h3>联系人与意向</h3>{data.permissions.can_edit && <Button size="sm" variant="outline" disabled={Boolean(saving)} onClick={() => setQuickEditOpen(true)}><PencilLine size={13}/>补充联系人与资料</Button>}</div><div className="sd-contacts">{enrichment?.contacts.map(contact => <article className="sd-contact" key={contact.id}><h4>{contact.name || '姓名待核实'}<small>{contact.role || '身份待核实'}</small>{contact.id === enrichment.preferred_contact_id && <span className="sd-tag">首选联系</span>}</h4><p>{contact.phone ? formatPhoneNumber(contact.phone, enrichment.country) : '电话待补充'}</p>{contact.email && <p>{contact.email}</p>}{contact.wechat && <p>微信：{contact.wechat}</p>}<div className="sd-contact-footer">{contact.verification === 'confirmed' ? '已核实' : '待核实'}</div></article>)}</div>{!enrichment?.contacts.length && <p className="sd-empty">还没有联系人，可在沟通时逐步补充老板、经理或前台信息。</p>}<section className="sd-section"><h3>意向产品</h3><p className="sd-summary-main">{enrichment?.interest_product_ids.length ? enrichment.interest_product_ids.map(id => data.catalog?.find(product => product.id === id)?.name || `产品 #${id}`).join('、') : '尚未明确'}</p><h3>已确认需求</h3><p className="sd-summary-main">{text(enrichment?.need_summary)}</p></section></>}
            {tab === 'history' && <><div className="sd-stats"><span><b>{data.insight.calls}</b>真实拨打</span><span><b>{data.insight.connected}</b>官方接通</span><span><b>{data.insight.records}</b>跟进记录</span><span><b>{data.insight.decision_conversations}</b>决策人沟通</span></div><div className="sd-timeline-tabs" aria-label="累计记录类型"><button type="button" aria-pressed={historyTab === 'contact'} onClick={() => setHistoryTab('contact')}>沟通与商机变化</button><button type="button" aria-pressed={historyTab === 'changes'} onClick={() => setHistoryTab('changes')}>资料与摘要变更</button></div>{historyTab === 'contact' ? <div className="sd-timeline">{data.insight.timeline.map(item => <article key={item.id}><span className="sd-timeline-dot"/><div><div className="sd-event-title"><b>{item.details?.after?.stage_label || item.label} · {item.salesperson || '未记录员工'}</b><time>{salesDate(item.at)} · 北京时间</time></div><small>{item.source === 'manual' ? '手工跟进 · 未关联官方通话' : item.source === 'review' ? '档案变更 · 保留依据' : `官方通话 #${item.official_ordinal || '—'} · ${item.connected ? '接通' : '未接通'}`}</small>{item.notes && <p>{item.notes}</p>}{item.details?.after?.evidence && <p>{item.details.after.evidence}</p>}{item.details?.need_summary && <p>需求：{item.details.need_summary}</p>}{item.details?.next_step && <p>下一步：{item.details.next_step}</p>}{item.next_follow_up_at && <p>约定联系：{salesDate(item.next_follow_up_at)}</p>}</div></article>)}{!data.insight.timeline.length && <p className="sd-empty">尚无累计沟通记录，首次联系后会开始积累。</p>}</div> : <DossierChanges data={data}/> }<p className="sd-inline-note">累计记录保留原操作人。真实拨打以官方会话去重，手工记录不推算电话次数。</p></>}
            {tab === 'ownership' && <>
              <div className="sd-section-heading"><h3>主要负责人</h3>{data.permissions.can_transfer && <Button size="sm" variant="outline" disabled={Boolean(saving)} onClick={() => setTransferOpen(!transferOpen)}>转交并填写交接</Button>}</div><div className="sd-person-row"><div><b><UserRound size={13} className="inline mr-1"/>{primary}</b><p>统一安排联系与下一步，协作权限不会改变负责人。</p></div><span>主要负责人</span></div>
              {transferOpen && data.permissions.can_transfer && <section className="sd-transfer" aria-label="商家交接"><h3>转交商家</h3><fieldset className="sd-form" disabled={Boolean(saving)}><label>接收销售<NativeSelect aria-label="接收销售" value={transfer.assigned_sales_id} options={[{ value:'',label:'选择接收销售' },...candidateOptions]} onChange={value => setTransfer({ ...transfer, assigned_sales_id:value })}/></label><label>转交原因<Input aria-label="转交原因" maxLength={1000} value={transfer.reason} onChange={event => setTransfer({ ...transfer, reason:event.target.value })}/></label><label className="sd-wide">交接说明<Textarea aria-label="交接说明" maxLength={2000} rows={4} placeholder="目前情况、需求与顾虑、已承诺事项、下一步安排" value={transfer.handoff_summary} onChange={event => setTransfer({ ...transfer, handoff_summary:event.target.value })}/></label><label className="sd-wide"><span className="flex items-start gap-2"><input type="checkbox" checked={transfer.confirm_protected_transfer} onChange={event => setTransfer({ ...transfer, confirm_protected_transfer:event.target.checked })}/>已核对当前跟进保护与约定时间，确认交接。禁联或黑名单仍保留。</span></label></fieldset><div className="sd-actions"><Button variant="outline" size="sm" disabled={Boolean(saving)} onClick={() => setTransferOpen(false)}>取消转交</Button><Button size="sm" disabled={Boolean(saving) || !transfer.assigned_sales_id || transfer.reason.trim().length < 3 || transfer.handoff_summary.trim().length < 3 || !transfer.confirm_protected_transfer} onClick={() => void mutate('transfer', () => invokeWithAuth({ url:`/api/v1/sales-leads/${data.insight.id}/recovery/reassign`,method:'POST',data:{ ...transfer,assigned_sales_id:Number(transfer.assigned_sales_id),expected_owner_id:data.insight.owner_id ?? null } }), '商家已转交，等待接收确认')}>确认转交</Button></div></section>}
              <section className="sd-section"><div className="sd-section-heading"><h3><Users size={14} className="inline mr-1"/>受邀人员</h3>{data.permissions.can_invite && <span className="sd-muted">仅老板可邀请或撤销</span>}</div>{activeGrants.length ? activeGrants.map(grant => <div className="sd-person-row" key={grant.employee_id}><div><b>{grant.employee_name || `员工 #${grant.employee_id}`}</b><p>{grant.employee_active === false ? '账号停用或角色已变更，当前邀请不生效' : grant.access === 'collaborate' ? '可补充资料与摘要' : '仅查看资料与累计记录'}</p></div><div className="sd-grant-actions"><span className="sd-tag">{grant.access === 'collaborate' ? '协作' : '只读'}</span>{data.permissions.can_invite && <Button type="button" size="sm" variant="ghost" disabled={Boolean(saving)} onClick={() => setRevokeId(grant.employee_id)}>撤销邀请</Button>}</div></div>) : <p className="sd-empty">尚未邀请其他人员。</p>}{revokeId !== null && <div className="sd-confirm" role="alert">撤销后，此人将失去本次邀请授予的档案访问。其既有操作记录继续保留。<div className="sd-actions"><Button variant="outline" size="sm" disabled={Boolean(saving)} onClick={() => setRevokeId(null)}>保留邀请</Button><Button size="sm" disabled={Boolean(saving)} onClick={() => void mutate('revoke', () => dossierApi(`/${data.insight.id}/invites/${revokeId}?expected_revision=${data.grants.find(grant => grant.employee_id === revokeId)?.revision ?? 0}`, 'DELETE'), '邀请已撤销')}>确认撤销</Button></div></div>}
              {data.permissions.can_invite && <><fieldset className="sd-form mt-3" disabled={Boolean(saving)}><label>邀请销售<NativeSelect aria-label="邀请销售" value={inviteId} options={[{value:'',label:'选择销售'},...candidateOptions]} onChange={value => { setInviteId(value); setInvitePreview(false); }}/></label><label>授予权限<NativeSelect aria-label="邀请权限" value={inviteAccess} options={[{value:'view',label:'只读查看'},{value:'collaborate',label:'协作补充'}]} onChange={value => { setInviteAccess(value === 'collaborate' ? 'collaborate' : 'view'); setInvitePreview(false); }}/></label></fieldset><div className="sd-actions"><Button size="sm" variant="outline" disabled={!inviteId || Boolean(saving)} onClick={() => setInvitePreview(true)}>预览权限</Button></div>{invitePreview && activeInvite && <div className="sd-preview" aria-label="邀请权限预览"><h4>{activeInvite.name} · {inviteAccess === 'collaborate' ? '协作补充' : '只读查看'}</h4><ul><li>可查看本商家最新资料、联系人、跟进摘要、累计沟通和交接记录。</li>{inviteAccess === 'collaborate' && <li>可补充商家资料、联系人和跟进摘要，修改保留操作人。</li>}<li>不授予拨号、抢单、转派、成交或分润归属修改权限。</li><li>不开放公司财务、客户中心权限或私人空间。</li></ul><div className="sd-actions"><Button size="sm" variant="outline" disabled={Boolean(saving)} onClick={() => setInvitePreview(false)}>返回调整</Button><Button size="sm" disabled={Boolean(saving)} onClick={() => void mutate('invite', () => dossierApi(`/${data.insight.id}/invites`, 'POST', {employee_id:Number(inviteId),access:inviteAccess,expected_revision:data.grants.find(grant => grant.employee_id === Number(inviteId))?.revision ?? 0}), '邀请权限已保存')}>确认邀请</Button></div></div>}</>}
              {!data.permissions.can_invite && <p className="sd-inline-note">协作人员由老板邀请，不能自行增加其他人员。</p>}</section>
              <section className="sd-section"><h3>交接记录</h3><div className="sd-timeline mt-3">{data.handoffs.map(item => <article key={item.id}><span className="sd-timeline-dot"/><div><div className="sd-event-title"><b>{item.from_name || item.from_sales_name || '待分配'} → {item.to_name || item.to_sales_name || '待分配'}</b><time>{salesDate(item.created_at)}</time></div><p>{handoffText(item)}</p><p className="sd-handoff-reason">{item.reason}</p><small>{item.acknowledged_at ? `${item.acknowledged_by_name || '接收人'} 已确认 · ${salesDate(item.acknowledged_at)}` : '待接收确认'}</small></div></article>)}{!data.handoffs.length && <p className="sd-empty">暂无新交接记录，历史转派保留在下方。</p>}</div><details className="sd-original"><summary><History size={13}/>历史负责人和贡献</summary><div className="mt-3">{data.insight.contributors.map(person => <div className="sd-person-row" key={person.employee_id}><div><b>{person.name || `员工 ${person.employee_id}`}</b><p>官方拨打 {person.calls} · 跟进记录 {person.records} · 有意向／预约 {person.positive}</p></div></div>)}</div><div className="sd-timeline mt-3">{data.insight.assignments.map(item => <article key={item.id}><span className="sd-timeline-dot"/><div><div className="sd-event-title"><b>{item.from || '待分配'} → {item.to || '待分配'}</b><time>{salesDate(item.at)}</time></div><p>{item.reason}</p></div></article>)}</div></details></section>
              {data.permissions.can_release_protection && !data.protection.can_contact && <section className="sd-section"><Button type="button" size="sm" variant="outline" onClick={() => { setReleaseOpen(!releaseOpen); setRelease({phone:enrichment?.store_phone || '',reason:'',resume_lead:false}); }}>核实后解除联系保护</Button>{releaseOpen && <div className="sd-transfer"><p className="sd-warning">仅在已核实商家重新同意联系时处理。指定号码的保护解除会保留操作记录，换负责人本身不会解除禁联。</p><fieldset className="sd-form" disabled={Boolean(saving)}><label>已核实的号码<Input aria-label="解除保护的号码" value={release.phone} onChange={event => setRelease({...release,phone:event.target.value})}/></label><label>重新允许联系的依据<Input aria-label="解除保护的依据" maxLength={1000} value={release.reason} onChange={event => setRelease({...release,reason:event.target.value})}/></label><label className="sd-wide"><span className="flex items-start gap-2"><input type="checkbox" checked={release.resume_lead} onChange={event => setRelease({...release,resume_lead:event.target.checked})}/>同时恢复本档案联系；其他受保护号码仍须分别核实。</span></label></fieldset><div className="sd-actions"><Button size="sm" variant="outline" onClick={() => setReleaseOpen(false)}>取消</Button><Button size="sm" disabled={Boolean(saving) || release.reason.trim().length < 3 || !release.phone.trim()} onClick={() => void mutate('release', () => invokeWithAuth({url:`/api/v1/sales-leads/${data.insight.id}/contact-protection/release`,method:'POST',data:release}), '已保存联系保护核实结果')}>确认解除指定号码保护</Button></div></div>}</section>}
              <p className="sd-inline-note">主要负责人、历史贡献、成交及分润归属分别管理。本页邀请与交接不修改客户中心权限。</p>
            </>}
          </>}
        </div>
      </DialogContent>
    </Dialog>
    {data && <SalesLeadQuickEdit open={quickEditOpen} onOpenChange={setQuickEditOpen} leadId={data.insight.id} value={{...data.enrichment,can_edit:data.permissions.can_edit}} draft={enrichmentDraft} onDraftChange={setEnrichmentDraft} canEdit={data.permissions.can_edit} saving={saving === 'enrichment'} loading={loading} error={quickEditOpen ? actionError : ''} catalog={data.catalog || []} onSave={async draft => {
      if (!data.permissions.can_edit) return false;
      return mutate('enrichment', () => dossierApi(`/${data.insight.id}/enrichment`, 'PUT', {...draft,source:'manual'}), '最新商家资料已保存');
    }} draftNotice={enrichmentDirty ? '修改仅保留在当前档案，保存后所有获准人员看到同一份资料。' : '补充资料保留操作人，不改变通话结果或归属。'}/>}
  </>;
}

function DossierChanges({data}:{data:SalesDossier}) {
  type Change = {id:number|string;actor_name?:string;created_at:string;kind?:string;changed_fields?:string[];before?:Record<string,unknown>;after?:Record<string,unknown>};
  const changes = (data as SalesDossier & {changes?:Change[]}).changes || (data.enrichment_history || []).map(item => ({...item,kind:'enrichment'}));
  const labels:Record<string,string> = {...enrichmentFieldLabels,latest_conclusion:'最近沟通结论',objections:'主要顾虑',promises:'已承诺事项'};
  const valueText = (key:string,value:unknown):string => {
    if (value == null || value === '') return '未填写';
    if (key === 'contacts' && Array.isArray(value)) return value.map(contact => [contact.name,contact.role,contact.phone,contact.email,contact.wechat].filter(Boolean).join(' · ')).join('；') || '无联系人';
    if (key === 'interest_product_ids' && Array.isArray(value)) return value.map(id=>data.catalog?.find(product=>product.id===id)?.name || `产品 #${id}`).join('、') || '未选择';
    if (key === 'verification') return value === 'confirmed' ? '已核实' : '待核实';
    return typeof value === 'string' || typeof value === 'number' ? String(value) : '已更新';
  };
  return <div className="sd-timeline">{changes.map(item => <article key={item.id}><span className="sd-timeline-dot"/><div><div className="sd-event-title"><b>{item.actor_name || '操作人员'} · {item.kind === 'summary' ? '更新跟进摘要' : '补充商家资料'}</b><time>{salesDate(item.created_at)}</time></div><p>{(item.changed_fields || []).map(key=>labels[key] || key).join('、') || '资料已更新'}</p><details className="sd-change-detail"><summary>查看修改前后</summary><dl>{(item.changed_fields || []).filter(key=>key!=='preferred_contact_id').map(key=><div key={key}><dt>{labels[key] || key}</dt><dd><small>修改前</small>{valueText(key,item.before?.[key])}</dd><dd><small>修改后</small>{valueText(key,item.after?.[key])}</dd></div>)}</dl></details></div></article>)}{!changes.length && <p className="sd-empty">暂无资料或摘要修改记录。</p>}</div>;
}
