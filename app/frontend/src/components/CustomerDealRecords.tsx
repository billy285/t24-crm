import { customerPermissions } from '@/lib/customer-permissions';
type Props={customer:any;deals:any[];classify:(name:string)=>{currentLabel:string;historicalLabel?:string;changed?:boolean};productLabels:Record<string,string>;cycleLabels:Record<string,string>};
/** A deal invitation is operational visibility; amounts require independent finance. */
export default function CustomerDealRecords({customer,deals,classify,productLabels,cycleLabels}:Props) {
  const permission=customerPermissions(customer);
  if(!permission.modules.deals.read)return null;
  const showFinance=['receipts','profit'].includes(permission.finance_access);
  return <div className="space-y-3">{deals.map(deal=>{const label=classify(deal.package_name);return <div key={deal.id} className="rounded-lg bg-slate-50 p-3"><div className="mb-2 flex items-center justify-between gap-2"><span className="text-sm font-medium">{label.currentLabel}</span>{showFinance&&deal.deal_amount!=null&&<span className="font-bold text-green-600">{deal.currency||'USD'} {deal.deal_amount}</span>}</div>{label.changed&&<p className="mb-2 text-xs text-slate-400">历史成交原名：{label.historicalLabel}</p>}<div className="grid grid-cols-2 gap-1 text-xs text-slate-500"><span>产品：{productLabels[deal.product_type]||deal.product_type||'-'}</span><span>周期：{cycleLabels[deal.billing_cycle]||deal.billing_cycle||'-'}</span><span>成交日：{deal.deal_date?.slice(0,10)||'-'}</span><span>销售：{deal.sales_name||'-'}</span>{showFinance&&typeof deal.is_paid==='boolean'&&<span>付款：{deal.is_paid?'已付':'未付'}</span>}<span>交接：{deal.is_handed_over?'已交接':'待交接'}</span></div></div>;})}</div>;
}
