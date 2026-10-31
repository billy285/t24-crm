import { invokeWithAuth } from './tokenStore';
import type { MediaTask, MediaStatus } from './media-operations-api';

export type MediaContentPlan = {id:number;customer_id:number;customer_name:string;title:string;brief:string;created_at:string;items:MediaTask[]};
export type PlanningCalendar = {items:MediaTask[];total:number;skip:number;limit:number;from:string;to:string};
export type PlanningSummary = {status:Record<MediaStatus,number>;overdue:number;completed_in_period:number;is_owner:boolean;
  platforms:({platform:string}&Record<MediaStatus,number>)[];
  operators:({id:number;name:string}&Record<MediaStatus,number>)[];
  provider_totals: null | {post_succeeded:number;reply_succeeded:number;accepted:number;pending:number;unknown:number;rejected:number;failed:number;legacy_time_fallback:number}};
export async function mediaPlanningApi<T>(path:string,method:'GET'|'POST'='GET',data?:unknown):Promise<T>{
  const response=await invokeWithAuth({url:`/api/v1/media-planning${path}`,method,...(data===undefined?{}:{data})});
  return response.data as T;
}
export function planningMonthRange(month:string):{start:string;end:string;days:number;leading:number}{
  if(!/^\d{4}-\d{2}$/.test(month))throw new Error('请选择完整月份。');
  const year=Number(month.slice(0,4)),m=Number(month.slice(5));
  if(year<2000||year>2100||m<1||m>12)throw new Error('请选择有效月份。');
  const next=new Date(Date.UTC(year,m,1)),end=`${next.getUTCFullYear()}-${String(next.getUTCMonth()+1).padStart(2,'0')}-01T00:00:00+08:00`;
  return {start:`${month}-01T00:00:00+08:00`,end,days:new Date(Date.UTC(year,m,0)).getUTCDate(),leading:(new Date(Date.UTC(year,m-1,1)).getUTCDay()+6)%7};
}
export function planningDateKey(instant:string):string{
  const date=new Date(instant);return Number.isFinite(date.getTime())?new Date(date.getTime()+8*3600000).toISOString().slice(0,10):'';
}
