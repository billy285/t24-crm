import { TabsList, TabsTrigger } from '@/components/ui/tabs';
import { customerVisibleTabs } from '@/lib/customer-permissions';
/** Shared customers expose only the explicitly invited sections. */
export default function CustomerCollaborationTabs({customer}:{customer:any}) {
  return <TabsList aria-label="已邀请客户栏目" className="mb-3 flex h-auto w-full flex-wrap justify-start gap-1 bg-slate-100 p-1">{customerVisibleTabs(customer).map(item=><TabsTrigger key={item.value} value={item.value} className="min-h-10 text-sm md:min-h-8 md:text-xs">{item.label}</TabsTrigger>)}</TabsList>;
}
