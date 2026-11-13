import { useCallback, useEffect, useId, useRef, useState, type MutableRefObject } from 'react';
import { ArrowRight, CheckCircle2, RefreshCw, Upload } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { CrmFormDialogBody, CrmFormDialogContent, CrmFormDialogFooter, CrmFormDialogHeader, Dialog, DialogTitle } from '@/components/ui/dialog';
import { useRole } from '@/lib/role-context';
import { AUTH_SESSION_EPOCH_KEY, AUTH_SESSION_INVALIDATED_EVENT, getAuthSessionEpoch } from '@/lib/auth-storage';
import { autoPostingTime } from '@/lib/stripe-auto-posting';
import { stripeReconciliationApi as api, stripeReconciliationError } from '@/lib/stripe-history-reconciliation';
import { BANK_CSV_MAX_BYTES, BankRequestGuard, bankColumnsError, bankMatchConfirmReady, bankMatchReady, bankMoney, bankPayoutExclusionNotice, bankPayoutEligible, decodeBankCsv, readBankInspection, readBankMatchPreview, readBankOverview, readBankPayoutPage, readBankStatement, type BankColumns, type BankInspection, type BankMatch, type BankMatchPreview, type BankOverview, type BankPayout, type BankStatementPreview } from '@/lib/stripe-bank-reconciliation';
import './stripe-bank-reconciliation.css';

type LiveScope = MutableRefObject<{ key: string; allowed: boolean }>;
type Operation = 'overview' | 'payouts' | 'file' | 'statement' | 'match' | 'confirm' | 'void';
const emptyColumns: BankColumns = { account_label: '', currency: 'USD', date_format: 'ymd', date_column: '', amount_column: '', description_column: '', reference_column: '' };
const statusCode = (failure: any) => Number(failure?.response?.status || failure?.data?.status || failure?.status);

/** Local matches load on entry; Stripe is read only after an explicit owner action. */
export default function StripeBankReconciliation() {
  const { role, employee } = useRole();
  const [sessionRevision, setSessionRevision] = useState(0);
  const session = getAuthSessionEpoch();
  const allowed = role === 'super_admin' && Boolean(employee?.id);
  const scope = `${employee?.id || ''}:${role}:${session}:${sessionRevision}`;
  const liveScope = useRef({ key: scope, allowed }); liveScope.current = { key: scope, allowed };
  useEffect(() => {
    const invalidate = () => { liveScope.current = { key: '', allowed: false }; setSessionRevision(value => value + 1); };
    const storage = (event: StorageEvent) => { if (event.key === AUTH_SESSION_EPOCH_KEY) invalidate(); };
    window.addEventListener(AUTH_SESSION_INVALIDATED_EVENT, invalidate); window.addEventListener('storage', storage);
    return () => { window.removeEventListener(AUTH_SESSION_INVALIDATED_EVENT, invalidate); window.removeEventListener('storage', storage); };
  }, []);
  return allowed ? <BankWorkspace key={scope} scope={scope} session={session} liveScope={liveScope} /> : null;
}

function BankWorkspace({ scope, session, liveScope }: { scope: string; session: string; liveScope: LiveScope }) {
  const guard = useRef(new BankRequestGuard()), inFlight = useRef<object | null>(null), operationBlocked = useRef(false);
  const [overview, setOverview] = useState<BankOverview | null>(null), [overviewError, setOverviewError] = useState(false);
  const [busy, setBusy] = useState<Operation | null>(null), [error, setError] = useState(''), [message, setMessage] = useState('');
  const [uncertain, setUncertain] = useState(false), [denied, setDenied] = useState(false);
  const [payouts, setPayouts] = useState<BankPayout[]>([]), [payoutFresh, setPayoutFresh] = useState(false), [payoutMore, setPayoutMore] = useState(false), [cursor, setCursor] = useState<string | null>(null);
  const [excludedNoncreditCount, setExcludedNoncreditCount] = useState<number | undefined>(undefined);
  const [csv, setCsv] = useState(''), [fileName, setFileName] = useState(''), [inspection, setInspection] = useState<BankInspection | null>(null), [columns, setColumns] = useState<BankColumns>({ ...emptyColumns });
  const [statement, setStatement] = useState<BankStatementPreview | null>(null), [rowIndex, setRowIndex] = useState(0), [payoutId, setPayoutId] = useState('');
  const [preview, setPreview] = useState<BankMatchPreview | null>(null), [verified, setVerified] = useState(false), [note, setNote] = useState('');
  const [voidTarget, setVoidTarget] = useState<BankMatch | null>(null), [voidVerified, setVoidVerified] = useState(false), [voidNote, setVoidNote] = useState('');
  const fileId = useId();
  const clearConfirmation = () => { setPreview(null); setVerified(false); setNote(''); };
  const clearWorkflow = useCallback(() => { setPayouts([]); setExcludedNoncreditCount(undefined); setPayoutFresh(false); setPayoutMore(false); setCursor(null); setCsv(''); setFileName(''); setInspection(null); setColumns({ ...emptyColumns }); setStatement(null); setRowIndex(0); setPayoutId(''); setPreview(null); setVerified(false); setNote(''); setVoidTarget(null); setVoidVerified(false); setVoidNote(''); }, []);
  const execute = useCallback(async (kind: Operation, action: (current: () => boolean) => Promise<void>, mutation = false) => {
    if (inFlight.current || !liveScope.current.allowed || liveScope.current.key !== scope || getAuthSessionEpoch() !== session || (operationBlocked.current && kind !== 'overview')) return;
    const request = guard.current.begin(scope, session);
    const current = () => liveScope.current.allowed && guard.current.current(request, liveScope.current.key, getAuthSessionEpoch());
    inFlight.current = request; setBusy(kind); setError(''); setMessage('');
    try { await action(current); }
    catch (failure) {
      if (!current()) return;
      const code = statusCode(failure);
      if ([401, 403, 404].includes(code)) { setOverview(null); clearWorkflow(); operationBlocked.current = true; setDenied(true); }
      if (kind === 'overview') setOverviewError(true);
      if (kind === 'payouts' || kind === 'match') setPayoutFresh(false);
      setVerified(false); setVoidVerified(false);
      if (mutation) { operationBlocked.current = true; setUncertain(true); setPreview(null); setVoidTarget(null); }
      const fallback = !code && failure instanceof Error ? failure.message : code === 503 && ['payouts', 'match', 'confirm'].includes(kind) ? 'Stripe 只读核对尚未就绪，请核对只读权限或连接后重试。' : '银行核对资料暂不可用，请重新读取。';
      setError(stripeReconciliationError(failure, fallback));
    } finally { if (inFlight.current === request) { inFlight.current = null; if (current()) setBusy(null); } }
  }, [scope, session, liveScope, clearWorkflow]);
  const loadOverview = useCallback(() => execute('overview', async current => {
    const data = readBankOverview(await api('/bank/overview'));
    if (!current()) return;
    setOverview(data); setOverviewError(false); setDenied(false); operationBlocked.current = false; setUncertain(false); clearWorkflow();
  }), [execute, clearWorkflow]);
  const initialLoad = useRef(loadOverview);
  useEffect(() => { void initialLoad.current(); return () => { guard.current.invalidate(); inFlight.current = null; }; }, []); // The keyed workspace reads local records once; no provider polling.
  const loadPayouts = (append = false) => {
    if (!overview || overviewError || denied || uncertain || (append && (!payoutFresh || !cursor))) return;
    void execute('payouts', async current => {
      const page = readBankPayoutPage(await api(`/bank/payouts${append ? `?starting_after=${encodeURIComponent(cursor!)}` : ''}`));
      if (!current()) return;
      setPayouts(previous => append ? [...previous, ...page.items.filter(item => !previous.some(old => old.id === item.id))] : page.items);
      setExcludedNoncreditCount(Object.prototype.hasOwnProperty.call(page, 'excluded_noncredit_count') ? page.excluded_noncredit_count : undefined);
      setPayoutFresh(true); setPayoutMore(page.has_more); setCursor(page.next_cursor || null); if (!append) { setPayoutId(''); clearConfirmation(); }
    });
  };
  const inspectFile = (file?: File) => {
    if (!file || !overview || overviewError || denied || uncertain) return;
    setCsv(''); setFileName(''); setInspection(null); setStatement(null); setRowIndex(0); clearConfirmation();
    void execute('file', async current => {
      if (file.size > BANK_CSV_MAX_BYTES) throw new Error('请上传不超过 1 MB 的 UTF-8 CSV 公司银行流水。');
      const text = decodeBankCsv(file.name, await file.arrayBuffer());
      if (!current()) return;
      const result = readBankInspection(await api('/bank/statements/inspect', 'POST', { csv_text: text }));
      if (!current()) return;
      setCsv(text); setFileName(file.name); setInspection(result); setColumns(previous => ({ ...emptyColumns, account_label: previous.account_label }));
    });
  };
  const updateColumns = (patch: Partial<BankColumns>) => { setColumns(previous => ({ ...previous, ...patch })); setStatement(null); setRowIndex(0); clearConfirmation(); };
  const columnError = inspection ? bankColumnsError(columns, inspection.headers) : '';
  const previewStatement = () => {
    if (!inspection || !csv || columnError || denied || uncertain) return;
    void execute('statement', async current => {
      const result = readBankStatement(await api('/bank/statements/preview', 'POST', { csv_text: csv, ...columns, account_label: columns.account_label.trim(), reference_column: columns.reference_column || undefined }));
      if (!current()) return;
      setStatement(result); setRowIndex(0); clearConfirmation();
    });
  };
  const selectedRow = statement?.rows.find(row => row.row_index === rowIndex), selectedPayout = payouts.find(item => item.id === payoutId);
  const matchingReady = !denied && !uncertain && payoutFresh && bankMatchReady(statement, selectedRow, selectedPayout);
  const previewMatch = () => {
    if (!matchingReady || !statement) return;
    clearConfirmation();
    void execute('match', async current => {
      const result = readBankMatchPreview(await api('/bank/matches/preview', 'POST', { statement_token: statement.token, row_index: rowIndex, payout_id: payoutId }));
      if (!current()) return;
      if (result.payout.id !== payoutId || result.bank_row.row_index !== rowIndex || result.account_label !== statement.account_label) throw new Error('匹配预览与所选来源不一致，请重新读取。');
      setPreview(result);
    });
  };
  const confirm = () => {
    if (!preview || denied || uncertain || !payoutFresh || !bankMatchConfirmReady(preview, verified, note)) return;
    void execute('confirm', async current => {
      const result = await api<{ item: BankMatch; ledger_writes: false }>('/bank/matches/confirm', 'POST', { token: preview.token, owner_verified: true, note: note.trim() });
      if (!current()) return;
      if (result?.ledger_writes !== false) throw new Error('匹配确认结果需重新读取。');
      readBankOverview({ items: [result.item], total: 1, currency: 'USD', bank_connection: 'statement_upload', provider_writes: false, ledger_writes: false });
      setOverview(previous => previous ? { ...previous, items: [result.item, ...previous.items.filter(item => item.id !== result.item.id)], total: previous.total + (previous.items.some(item => item.id === result.item.id) ? 0 : 1) } : null);
      clearWorkflow(); setMessage('已保存老板人工流水匹配证据；没有新增收入、改动收款或佣金。');
    }, true);
  };
  const voidMatch = () => {
    if (!voidTarget || !voidVerified || voidNote.trim().length < 3 || voidNote.trim().length > 1000 || overviewError || denied || uncertain) return;
    void execute('void', async current => {
      const result = await api<{ id: number; status: string; ledger_writes: false }>(`/bank/matches/${voidTarget.id}/void`, 'POST', { owner_verified: true, note: voidNote.trim() });
      if (!current()) return;
      if (result?.id !== voidTarget.id || result.status !== 'voided' || result.ledger_writes !== false) throw new Error('撤回结果需重新读取。');
      setOverview(previous => previous ? { ...previous, items: previous.items.filter(item => item.id !== voidTarget.id), total: Math.max(previous.total - 1, 0) } : null);
      setVoidTarget(null); setVoidVerified(false); setVoidNote(''); setMessage('人工匹配已撤回并保留操作记录；原收入与收款没有改动。');
    }, true);
  };
  const exclusionNotice = payoutFresh ? bankPayoutExclusionNotice(excludedNoncreditCount) : null;
  const locked = Boolean(busy) || denied || uncertain || !overview || overviewError;
  const selectColumn = (key: 'date_column' | 'amount_column' | 'description_column' | 'reference_column', label: string, optional = false) => <label>{label}<select aria-label={label} value={columns[key] || ''} onChange={event => updateColumns({ [key]: event.target.value })}><option value="">{optional ? '不使用独立编号列' : '请选择列'}</option>{inspection?.headers.map(header => <option key={header} value={header}>{header}</option>)}</select></label>;
  return <section className="sbk-page" aria-label="公司银行流水核对" aria-busy={Boolean(busy)}>
    <div className="shr-section-title"><div><h3>银行到账核验</h3><p>上传公司美元银行流水，与 Stripe 自动结算逐笔核对。平台 paid 状态不等于银行流水已匹配。</p></div><Button size="sm" variant="outline" disabled={Boolean(busy)} onClick={() => void loadOverview()}><RefreshCw size={14} className={busy === 'overview' ? 'animate-spin' : ''} />{uncertain ? '核对处理结果' : '读取匹配记录'}</Button></div>
    {error && <p className="shr-error" role="alert">{error}{overviewError && overview && ' 以下为上次读取结果，撤回已暂停。'}{uncertain && ' 上次处理结果尚未确认，请先重新读取匹配记录，勿重复提交。'}</p>}
    {message && <p className="shr-success" role="status"><CheckCircle2 size={16} />{message}</p>}
    {denied && <p className="shr-warning">当前访问未就绪，已清除本页敏感资料。请核对老板账号与 Stripe 只读权限后重新读取。</p>}
    <div className="sbk-workflow">
      <section className="shr-panel sbk-step"><div className="sbk-step-title"><span>1</span><h4>上传公司流水</h4></div><p className="shr-note">仅支持 UTF-8 CSV、1 MB 内、最多 1000 行。入账用正数，支出用负数；首期仅美元。仅本页临时读取，不写入浏览器存储。</p>
        <label className={`sbk-file${locked ? ' sbk-disabled' : ''}`} htmlFor={fileId}><Upload size={16} /><span>选择 CSV 公司流水</span><input id={fileId} aria-label="上传公司银行流水 CSV" type="file" accept=".csv,text/csv" disabled={locked} onChange={event => { const file = event.currentTarget.files?.[0]; event.currentTarget.value = ''; inspectFile(file); }} /></label>
        {fileName && <p className="sbk-file-name">{fileName} · {inspection?.row_count ?? '—'} 行</p>}
        {inspection && <fieldset disabled={locked} className="sbk-columns"><label>公司账户标记<Input aria-label="公司账户标记" value={columns.account_label} maxLength={80} placeholder="如 公司运营账户·尾号1234" onChange={event => updateColumns({ account_label: event.target.value })} /></label>
          <details open={!statement}><summary>确认流水列与日期格式</summary><div className="sbk-column-grid"><label>日期格式<select aria-label="流水日期格式" value={columns.date_format} onChange={event => updateColumns({ date_format: event.target.value as 'ymd' | 'mdy' })}><option value="ymd">年-月-日 · 2026-11-13</option><option value="mdy">月/日/年 · 11/13/2026</option></select></label>{selectColumn('date_column', '日期列')}{selectColumn('amount_column', '美元金额列')}{selectColumn('description_column', '摘要列')}{selectColumn('reference_column', '流水编号列（可选）', true)}</div><details className="sbk-sample"><summary>查看前 {inspection.sample.length} 行样例</summary><div className="sbk-table-scroll"><table><thead><tr>{inspection.headers.map(header => <th key={header}>{header}</th>)}</tr></thead><tbody>{inspection.sample.map((row, index) => <tr key={index}>{row.map((cell, column) => <td key={column}>{cell}</td>)}</tr>)}</tbody></table></div></details></details>
          {columnError && <p className="shr-note">{columnError}</p>}<Button size="sm" variant="outline" disabled={Boolean(columnError)} onClick={previewStatement}>{busy === 'statement' ? '正在解析…' : '预览入账行，不记账'}</Button>
        </fieldset>}
      </section>
      <section className="shr-panel sbk-step"><div className="sbk-step-title"><span>2</span><h4>读取 Stripe 结算</h4></div><p className="shr-note">点击后只读 Stripe 结算；仅 paid、自动转入银行的美元结算可核对。不会发起付款或改 Stripe。</p><Button size="sm" variant="outline" disabled={locked} onClick={() => loadPayouts()}>{busy === 'payouts' ? '正在读取…' : '从 Stripe 读取结算'}</Button>
        {exclusionNotice && <p className="shr-note" role="note">{exclusionNotice}</p>}
        {!payoutFresh && payouts.length > 0 && <p className="shr-warning">以下为上次结果，请重新读取 Stripe 后再预览匹配。</p>}
        {payouts.length > 0 ? <div className="sbk-options" role="group" aria-label="选择 Stripe 结算">{payouts.map(item => <label key={item.id} className="sbk-option"><input type="radio" name={`${fileId}-payout`} aria-label={`选择结算 ${item.id}`} value={item.id} checked={payoutId === item.id} disabled={locked || !payoutFresh || !bankPayoutEligible(item)} onChange={() => { setPayoutId(item.id); clearConfirmation(); }} /><span><strong>{bankMoney(item.amount_minor)}</strong><small>{item.arrival_date} · {item.status}{!bankPayoutEligible(item) && ' · 暂不可核对'}</small><small>{item.id}</small></span></label>)}</div> : payoutFresh && <p className="shr-note">本次读取页暂无可核对的美元入账结算；不能据此判断银行到账情况。</p>}
        {payoutMore && <Button size="sm" variant="ghost" disabled={locked || !payoutFresh} onClick={() => loadPayouts(true)}>继续读取下一页</Button>}
      </section>
    </div>
    {statement && <section className="shr-panel sbk-match"><div className="sbk-step-title"><span>3</span><h4>选择银行入账并预览匹配</h4></div><p className="shr-note">{statement.account_label} · 已解析 {statement.rows.length} 笔正数入账。重复且无法区分的行须补银行流水编号。每次仅核对一笔，不按相同金额自动配对。</p>
      <div className="sbk-options" role="group" aria-label="选择银行入账行">{statement.rows.map(row => <label key={row.row_index} className="sbk-option"><input type="radio" name={`${fileId}-bank-row`} aria-label={`选择银行流水第 ${row.row_index} 行`} checked={rowIndex === row.row_index} disabled={locked || row.ambiguous} onChange={() => { setRowIndex(row.row_index); clearConfirmation(); }} /><span><strong>{bankMoney(row.amount_minor)} · {row.date}</strong><small>{row.description || '摘要未填写'}</small><small>第 {row.row_index} 行{row.reference && ` · ${row.reference}`}{row.ambiguous && ' · 重复行，需补流水编号后重新上传'}</small></span></label>)}</div>
      {selectedRow && selectedPayout && selectedRow.amount_minor !== selectedPayout.amount_minor && <p className="shr-warning">所选入账与结算金额不同，请重新选择；不会自动调整金额。</p>}
      <Button disabled={locked || !matchingReady} onClick={previewMatch}>{busy === 'match' ? '正在核对结算交易…' : '预览这一笔匹配'}<ArrowRight size={14} /></Button>
    </section>}
    {preview && <section className="shr-panel sbk-confirm" aria-label="银行匹配确认"><h4>预览通过，等待老板确认</h4><dl><div><dt>公司银行流水</dt><dd>{preview.account_label} · {preview.bank_row.date} · {bankMoney(preview.bank_row.amount_minor)}<small>{preview.bank_row.description} · {preview.bank_row.reference || '无独立流水编号'}</small></dd></div><div><dt>Stripe 结算依据</dt><dd>{preview.payout.id} · {bankMoney(preview.payout.amount_minor)}<small>已核验 {preview.transaction_count} 条结算交易 · paid</small></dd></div></dl><p className="shr-note">保存的是老板人工流水匹配证据。不会生成收入、改动原收款、税费或佣金；完整性仍取决于上传的公司流水范围。</p>
      <fieldset disabled={locked}><label>核对说明<Textarea aria-label="银行匹配核对说明" value={note} maxLength={1000} onChange={event => { setNote(event.target.value); setVerified(false); }} placeholder="说明公司账户、流水编号及结算核对依据" /></label><label className="sbk-owner-check"><input type="checkbox" checked={verified} onChange={event => setVerified(event.target.checked)} /><span>我已核对公司银行原始流水与这笔 Stripe 结算，确认仅保存人工匹配证据，不新增收入。</span></label><Button disabled={!payoutFresh || !bankMatchConfirmReady(preview, verified, note)} onClick={confirm}>{busy === 'confirm' ? '正在核对保存…' : '确认流水匹配'}</Button></fieldset>
    </section>}
    <details className="shr-panel sbk-records"><summary>已保存的人工匹配 <strong>{overview ? overview.total : '—'}</strong><small>仅当前有效证据，非全部银行余额</small></summary>{overview?.items.length ? <div className="sbk-record-list">{overview.items.map(item => <article key={item.id}><div><strong>{bankMoney(item.amount_minor)} · {item.account_label}</strong><p>{item.bank_date} · {item.payout_id}</p><p>人工流水已匹配 · {item.confirmed_by || '老板'} · {autoPostingTime(item.confirmed_at)}（北京时间）</p>{item.bank_reference && <p>流水编号 {item.bank_reference}</p>}<details><summary>查看依据与已关联公司账</summary><p>{item.note}</p><p>{item.payment_ids.length ? `已关联收款 ${item.payment_ids.map(id => `#${id}`).join('、')}` : '尚无可直接关联的公司收款记录；本次没有新增收入。'}</p></details></div><Button size="sm" variant="outline" disabled={locked || overviewError} onClick={() => { setVoidTarget(item); setVoidVerified(false); setVoidNote(''); }}>撤回匹配</Button></article>)}</div> : <p className="shr-note">{overview ? '当前没有有效的人工流水匹配；不能据此判断尚未到账。' : busy === 'overview' ? '正在读取本地匹配记录…' : '匹配记录待读取，不能当作零笔。'}</p>}{overview && overview.total > overview.items.length && <p className="shr-note">当前展示最近 {overview.items.length} 条，共 {overview.total} 条有效匹配。</p>}</details>
    <Dialog open={Boolean(voidTarget)} onOpenChange={open => { if (!open && !busy) setVoidTarget(null); }}><CrmFormDialogContent className="financial-workspace-form shr-dialog sbk-void-dialog" aria-describedby={undefined}><CrmFormDialogHeader><DialogTitle>撤回人工匹配</DialogTitle></CrmFormDialogHeader><CrmFormDialogBody><p>{voidTarget?.account_label} · {bankMoney(voidTarget?.amount_minor)} · {voidTarget?.payout_id}</p><p className="shr-note">撤回仅取消这笔人工匹配并保留留痕；不会退款、删除公司收入或改动佣金。</p><label>撤回原因<Textarea aria-label="撤回银行匹配原因" value={voidNote} maxLength={1000} disabled={Boolean(busy)} onChange={event => { setVoidNote(event.target.value); setVoidVerified(false); }} /></label><label className="sbk-owner-check"><input type="checkbox" checked={voidVerified} disabled={Boolean(busy)} onChange={event => setVoidVerified(event.target.checked)} /><span>我确认撤回此匹配证据，并保留原收款及审计记录。</span></label></CrmFormDialogBody><CrmFormDialogFooter><Button variant="outline" disabled={Boolean(busy)} onClick={() => setVoidTarget(null)}>暂不撤回</Button><Button disabled={locked || !voidVerified || voidNote.trim().length < 3 || overviewError} onClick={voidMatch}>确认撤回</Button></CrmFormDialogFooter></CrmFormDialogContent></Dialog>
  </section>;
}
