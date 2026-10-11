import { useState } from 'react';
import { ArrowUpRight, ChevronRight, Landmark, LoaderCircle, RefreshCw } from 'lucide-react';
import { privateSourceActionAvailability, verifiedPrivateSourceUrl, type PrivateItem, type PrivateSource } from '@/lib/private-workspace-api';
import { currentBankCondition, privateBankAccountLabels, privateBankRecord, privateBankRecords, privateBankTime } from '@/lib/private-bank';
import './private-bank.css';

export interface PrivateBankDashboardProps {
  source?: PrivateSource;
  items: PrivateItem[];
  total: number;
  loading: boolean;
  error?: string;
  busy?: boolean;
  syncing?: boolean;
  now?: number;
  onSelect: (item: PrivateItem) => void;
  onConnect: () => void;
  onRefresh: () => void;
  onSync?: () => void;
}

export default function PrivateBankDashboard({ source, items, total, loading, error = '', busy = false, syncing = false, now = Date.now(), onSelect, onConnect, onRefresh, onSync }: PrivateBankDashboardProps) {
  const [tab, setTab] = useState<'posted' | 'pending'>('posted');
  const condition = currentBankCondition(source, now);
  const records = privateBankRecords(items, source, now);
  const filtered = records.filter(item => item.status === tab);
  const connected = source?.status === 'connected';
  const actions = source ? privateSourceActionAvailability(source) : null;
  const pendingConfiguration = actions?.pendingConfiguration ?? true;
  const canOpenConnection = Boolean(actions?.canConnect || connected && actions?.canDisconnect);
  const openConnection = () => { if (!busy && canOpenConnection) onConnect(); };
  const sourceStatus = !source ? '接入状态待确认' : pendingConfiguration ? '接入配置尚未完成' : connected ? '已安全连接 · 只读' : source.status === 'connecting' ? '等待银行授权' : source.status === 'error' ? '连接需要检查' : '尚未连接银行';
  const connectLabel = connected ? '管理接入' : !source ? '状态待确认' : pendingConfiguration ? '待完成配置' : source.status === 'connecting' ? '继续授权' : '安全连接';
  return <div className="pw-bank-dashboard">
    {condition.environment === 'sandbox' && <div className="pw-bank-sandbox" role="status"><strong>银行测试数据</strong><span>Sandbox · 非真实余额与流水</span></div>}
    <header className="pw-bank-source"><div><Landmark aria-hidden="true" /><div><strong>{source?.metadata?.bank_institution_name || 'Bank of America'}</strong><span>{sourceStatus}</span></div></div><button type="button" className="pw-button" disabled={busy || !canOpenConnection} aria-busy={busy || undefined} onClick={openConnection}>{connectLabel}</button></header>
    <section className="pw-bank-balances" aria-label="银行账户缓存余额"><div className="pw-bank-section-heading"><h2>{condition.label}</h2>{condition.observedAt && <time dateTime={condition.observedAt}>读取 {privateBankTime(condition.observedAt)}</time>}</div>{condition.accounts.length ? <div className="pw-bank-account-grid">{condition.accounts.map(account => {
      const labels = privateBankAccountLabels(account);
      return <article className="pw-bank-account" key={account.account_id}><div className="pw-bank-account-heading"><div><strong>{labels.title}</strong><span>{labels.kind}{account.mask ? ` · 尾号 ${account.mask}` : ''}</span></div><small>{labels.currency}</small></div><div className="pw-bank-account-primary"><span>{labels.primaryLabel}</span><strong>{labels.primaryAmount}</strong></div><div className="pw-bank-account-secondary"><span>{labels.secondaryLabel}</span><strong>{labels.secondaryAmount}</strong></div>{labels.limit && <div className="pw-bank-account-secondary"><span>信用额度</span><strong>{labels.limit}</strong></div>}<details className="pw-bank-account-update"><summary>余额来源与时间<ChevronRight aria-hidden="true" /></summary><p>银行缓存余额，非实时查询</p><p>银行更新：{privateBankTime(account.balance_updated_at)}</p><p>工作空间读取：{privateBankTime(condition.observedAt)}（北京时间）</p></details></article>;
    })}</div> : <div className="pw-bank-empty"><Landmark aria-hidden="true" /><h3>{!source ? '银行接入状态待确认' : pendingConfiguration ? '银行接入尚待配置' : condition.state === 'unverified' ? '授权并同步后查看银行数据' : '来源尚未提供账户余额'}</h3><p>{pendingConfiguration ? source ? '配置完成后，才能安全授权并读取真实账户数据。' : '重新读取来源状态后继续。' : '账户、币种与金额确认后分别显示。'}</p>{actions?.canConnect && <button type="button" className="pw-button pw-button-primary" disabled={busy} aria-busy={busy || undefined} onClick={openConnection}>连接 Bank of America</button>}</div>}</section>
    {source?.error && <p className="pw-bank-source-error" role="status">{source.error}</p>}
    <section className="pw-bank-transactions" aria-label="银行流水"><div className="pw-bank-section-heading"><h2>银行流水</h2>{condition.state === 'stale' && <span className="pw-bank-stale-label">上次同步 · 需更新</span>}{actions?.canSync && onSync && <button type="button" className="pw-text-button" disabled={busy} onClick={() => { if (!busy) onSync(); }}><RefreshCw aria-hidden="true" />{syncing ? '正在同步…' : '同步'}</button>}</div><div className="pw-bank-tabs" aria-label="银行流水状态">{(['posted', 'pending'] as const).map(status => <button key={status} type="button" aria-pressed={status === tab} onClick={() => setTab(status)}>{status === 'posted' ? '已入账' : '待入账'}<small>{loading || condition.state === 'unverified' || !condition.transactionsComplete && !records.some(item => item.status === status) ? '—' : records.filter(item => item.status === status).length}</small></button>)}</div>
      {condition.state !== 'unverified' && !condition.transactionsComplete && <p className="pw-bank-preparing" role="status">{condition.transactionUpdateStatus === 'INITIAL_UPDATE_COMPLETE' ? '近期流水已就绪，历史流水仍在准备。' : '银行流水正在准备，尚未返回完整数据。'}</p>}
      {loading ? <div className="pw-bank-loading" role="status"><LoaderCircle aria-hidden="true" />正在读取流水…</div> : error ? <div className="pw-bank-loading pw-bank-load-error" role="alert"><p>{error}</p><button type="button" className="pw-button" disabled={busy} onClick={onRefresh}>重新读取</button></div> : filtered.length ? <div className="pw-bank-records">{filtered.map(item => {
        const record = privateBankRecord(item, source, now);
        return <button type="button" key={item.id} className="pw-bank-record" onClick={() => onSelect(item)}><span className="pw-bank-record-copy"><strong>{item.title}</strong><span>{record.date || '日期待提供'}{record.account?.mask ? ` · 尾号 ${record.account.mask}` : ''}</span></span><span className={`pw-bank-record-money is-${record.direction}`}><strong>{record.amountPrefix}{record.amount}</strong><small>{record.directionLabel}</small></span><ChevronRight aria-hidden="true" /></button>;
      })}</div> : <div className="pw-bank-quiet-empty">{condition.state === 'unverified' ? pendingConfiguration ? '接入配置完成并授权同步后查看流水。' : '连接并同步后查看流水。' : condition.transactionsComplete ? `当前同步记录中没有${tab === 'posted' ? '已入账' : '待入账'}流水。` : `尚无可查看的${tab === 'posted' ? '已入账' : '待入账'}流水，请等待来源更新。`}</div>}
      {!loading && !error && records.length > 0 && <p className="pw-bank-list-count">当前查看 {records.length} 条同步流水{total > records.length ? ` · 来源列表共 ${total} 条` : ''}</p>}
    </section>
    <details className="pw-bank-coverage"><summary>数据范围与来源<ChevronRight aria-hidden="true" /></summary><p>各账户和币种分别查看；转入、转出表示银行资金变动，不直接归为经营收入或支出。</p><p>待入账金额可能更新；被替代或移除的流水不再显示。</p><p>余额来自银行缓存，流水来自授权连接；此页面只读，不写入 CRM 财务。</p>{condition.bankUpdatedAt && <p>来源更新：{privateBankTime(condition.bankUpdatedAt)}（北京时间）</p>}</details>
  </div>;
}

export function PrivateBankDetail({ item, source, now = Date.now() }: { item: PrivateItem; source?: PrivateSource; now?: number }) {
  const record = privateBankRecord(item, source, now);
  const link = verifiedPrivateSourceUrl('bofa_bank', item.source_url);
  return <div className="pw-bank-detail">{record.mode === 'sandbox' && <div className="pw-bank-sandbox" role="status"><strong>银行测试数据</strong><span>非真实资金变动</span></div>}<section className={`pw-bank-detail-amount is-${record.direction}`}><span>{record.current ? `${record.stateLabel} · ${record.directionLabel}` : '记录来源待重新核对'}</span><strong>{record.current ? `${record.amountPrefix}${record.amount}` : '待提供'}</strong>{record.needsUpdate && <small>上次同步记录 · 需更新</small>}</section><dl className="pw-bank-detail-fields"><div><dt>账户</dt><dd>{record.account ? `${record.account.name}${record.account.mask ? ` · 尾号 ${record.account.mask}` : ''}` : '待核对'}</dd></div><div><dt>银行日期</dt><dd>{record.date || '待提供'}</dd></div><div><dt>来源状态</dt><dd>{record.current ? record.stateLabel : '待核对'}</dd></div></dl>{item.status === 'pending' && <p className="pw-bank-detail-note">待入账金额与记录可能更新，以银行最终流水为准。</p>}<details className="pw-bank-detail-evidence"><summary>来源依据<ChevronRight aria-hidden="true" /></summary><dl><div><dt>工作空间读取</dt><dd>{privateBankTime(record.observedAt)}（北京时间）</dd></div><div><dt>记录参考</dt><dd>{typeof item.evidence.bank_transaction_id === 'string' ? item.evidence.bank_transaction_id : '待提供'}</dd></div>{item.summary && <div><dt>来源说明</dt><dd>{item.summary}</dd></div>}<div><dt>财务关系</dt><dd>独立个人查看，不写入 CRM 账目</dd></div></dl></details>{link && <a className="pw-button" href={link} target="_blank" rel="noopener noreferrer">打开 Bank of America<ArrowUpRight aria-hidden="true" /></a>}</div>;
}
