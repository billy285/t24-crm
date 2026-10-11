import { ChevronRight, CreditCard, Landmark } from 'lucide-react';
import { formatPrivateAmount, privateSourceActionAvailability, privateStripeSnapshot, type PrivateWorkspaceData, type PrivateSource } from '@/lib/private-workspace-api';
import { currentBankCondition, privateBankAccountLabels, privateBankTime } from '@/lib/private-bank';
import './private-funds-overview.css';

interface Props {
  data: PrivateWorkspaceData | null;
  now?: number;
  busy?: boolean;
  compact?: boolean;
  onOpen: (view: 'funds' | 'stripe' | 'bofa_bank') => void;
}

function connectionLabel(source: PrivateSource | undefined, state: 'fresh' | 'stale' | 'unverified') {
  if (!source) return '接入状态待确认';
  if (privateSourceActionAvailability(source).pendingConfiguration) return '尚待配置';
  if (source.status === 'error') return '连接需检查';
  if (source.status === 'connecting') return '等待授权';
  if (source.status !== 'connected') return '尚未连接';
  return state === 'fresh' ? '已读取快照' : state === 'stale' ? '数据需更新' : '余额待同步';
}

/** Displays existing verified provider snapshots only; it never sums money or requests a report. */
export default function PrivateFundsOverview({ data, now = Date.now(), busy = false, compact = false, onOpen }: Props) {
  const stripe = data?.sources.find(source => source.id === 'stripe');
  const bank = data?.sources.find(source => source.id === 'bofa_bank');
  const stripeCondition = privateStripeSnapshot(stripe, now);
  const bankCondition = currentBankCondition(bank, now);
  const balances = stripeCondition.state === 'unverified' ? [] : (data?.balances || []).filter(balance => balance.source_id === 'stripe');
  const shownBalances = compact ? balances.slice(0, 2) : balances;
  const testMode = stripeCondition.mode === 'test';
  const accountLabel = typeof stripe?.metadata?.account_label === 'string' && !stripe.metadata.account_label.startsWith('acct_') ? stripe.metadata.account_label.split(/\s*[·|]\s*acct_/)[0].trim() || 'Stripe' : 'Stripe';

  return <div className={`pw-funds-overview${compact ? ' is-compact' : ''}`}>
    <section className="pw-funds-provider" aria-label="Stripe 缓存余额">
      <div className="pw-funds-heading"><h2><CreditCard aria-hidden="true" />{compact ? '私人资金' : accountLabel}</h2><span className={`pw-funds-state is-${stripeCondition.state}`}>{connectionLabel(stripe, stripeCondition.state)}</span></div>
      <p className="pw-funds-context">Stripe 当前余额{testMode ? ' · 测试数据' : ''}</p>
      {shownBalances.length ? <div className="pw-funds-currencies">{shownBalances.map(balance => <div className="pw-funds-currency" key={balance.currency}><span>{balance.currency}</span><dl><div><dt>可用</dt><dd>{formatPrivateAmount(balance.available_minor, balance.currency, 'stripe')}</dd></div><div><dt>待结算</dt><dd>{formatPrivateAmount(balance.pending_minor, balance.currency, 'stripe')}</dd></div></dl></div>)}</div> : <div className="pw-funds-missing"><strong>余额待确认</strong><p>{stripe?.status === 'connected' ? '同步并核对快照后显示。' : '完成连接后查看真实余额。'}</p></div>}
      {compact && balances.length > shownBalances.length && <p className="pw-funds-context">另有 {balances.length - shownBalances.length} 个币种，进入后分别查看。</p>}
      {stripeCondition.observedAt && <p className="pw-funds-time">快照 {privateBankTime(stripeCondition.observedAt)} · 北京时间</p>}
      <button type="button" className="pw-text-button" disabled={busy} onClick={() => onOpen(compact ? 'funds' : 'stripe')}>{compact ? '查看私人资金' : '查看收款、订阅与流水'}<ChevronRight aria-hidden="true" /></button>
    </section>
    {!compact && <section className="pw-funds-provider" aria-label="银行缓存余额">
      <div className="pw-funds-heading"><h2><Landmark aria-hidden="true" />Bank of America</h2><span className={`pw-funds-state is-${bankCondition.state}`}>{connectionLabel(bank, bankCondition.state)}</span></div>
      {bankCondition.environment === 'sandbox' && <p className="pw-funds-context pw-funds-test">银行测试数据 · 非真实余额</p>}
      {bankCondition.accounts.length ? <div className="pw-funds-bank-accounts">{bankCondition.accounts.map(account => {
        const labels = privateBankAccountLabels(account);
        return <div key={account.account_id} className="pw-funds-bank-account"><h3>{labels.title}</h3><span>{labels.kind}{account.mask ? ` · 尾号 ${account.mask}` : ''}</span><dl><div><dt>{labels.primaryLabel}</dt><dd>{labels.primaryAmount}</dd></div><div><dt>{labels.secondaryLabel}</dt><dd>{labels.secondaryAmount}</dd></div></dl></div>;
      })}</div> : <div className="pw-funds-missing"><strong>余额与流水待获取</strong><p>{bank?.status === 'connected' ? '等待有效银行快照。' : '完成配置与本人授权后显示。'}</p></div>}
      {bankCondition.observedAt && <p className="pw-funds-time">缓存读取 {privateBankTime(bankCondition.observedAt)} · 北京时间</p>}
      <button type="button" className="pw-text-button" disabled={busy} onClick={() => onOpen('bofa_bank')}>查看银行账户与流水<ChevronRight aria-hidden="true" /></button>
    </section>}
    {!compact && <p className="pw-funds-boundary">当前余额与期间收款分别查看，各账户和币种独立呈现。</p>}
  </div>;
}
