import { invokeWithAuth } from "@/lib/tokenStore";
export const potentialOptions = [
  { value: "priority", label: "优先推进" },
  { value: "nurture", label: "持续培育" },
  { value: "unknown", label: "待判断" },
  { value: "low_fit", label: "低匹配" },
  { value: "blocked", label: "禁止联系" },
  { value: "won", label: "已转客户" },
];
export const outcomeLabels: Record<string, string> = {
  no_answer: "未接通",
  callback: "待回访",
  interested: "有意向",
  appointment: "已预约",
  not_interested: "无意向",
  not_now: "暂时不需要",
  existing_provider: "已有服务商",
  do_not_contact: "禁止再联系",
};
export type ContactDetails = {
  reached_person: string;
  rejection_reason: string;
  need_summary: string;
  next_step: string;
};
export const emptyContact: ContactDetails = {
  reached_person: "unknown",
  rejection_reason: "",
  need_summary: "",
  next_step: "",
};
export type Stage = {
  key: string;
  label: string;
  evidence: string;
  milestone: string;
  stale_days: number;
};
export type OperatingConfig = {
  pipelines: { key: string; label: string; stages: Stage[] }[];
  custom_fields: {
    key: string;
    label: string;
    required_milestones: string[];
  }[];
  weights: Record<string, number>;
  repeated_rejection_count: number;
  unconnected_attempts: number;
  interest_stale_days: number;
  default_contact_start: number;
  default_contact_end: number;
};
export type Profile = {
  pipeline_key?: string;
  stage_key?: string;
  stage_label?: string;
  stage_entered_at?: string;
  milestone?: string;
  evidence?: string;
  next_step?: string;
  next_step_date?: string;
  need_summary?: string;
  decision_maker?: string;
  timezone?: string;
  custom_fields?: Record<string, string>;
  potential_override?: string;
  override_reason?: string;
};
export type TimelineItem = {
  id: string;
  activity_id?: number;
  kind: string;
  at: string;
  outcome?: string;
  label: string;
  notes?: string;
  salesperson?: string;
  source: string;
  official_ordinal?: number;
  connected?: boolean | null;
  duration_seconds?: number;
  next_follow_up_at?: string;
  details?: Partial<ContactDetails> & { after?: Profile; before?: Profile };
};
export type LeadInsight = {
  id: number;
  business_name: string;
  phone: string;
  country?: string;
  owner: string;
  owner_id?: number;
  source: string;
  industry: string;
  city?: string;
  state?: string;
  merchant_pool_id?: number;
  converted_customer_id?: number;
  potential: string;
  potential_label: string;
  rationale: string[];
  status: string;
  calls: number;
  connected: number;
  not_connected: number;
  pending_calls: number;
  manual_records: number;
  records: number;
  linked_records: number;
  decision_conversations: number;
  outcomes: Record<string, number>;
  rejection_reasons: Record<string, number>;
  connected_rejections: number;
  connected_without_result: number;
  all_connected_rejected: boolean;
  first_interest_at?: string;
  first_interest_record_number?: number;
  first_interest_call_number?: number;
  days_to_interest?: number;
  first_appointment_at?: string;
  last_contact_at?: string;
  last_synced_at?: string;
  next_follow_up_at?: string;
  overdue: boolean;
  no_next_step: boolean;
  turned_positive: boolean;
  profile: Profile;
  revision: number;
  timeline: TimelineItem[];
  contributors: {
    employee_id: number;
    name: string;
    records: number;
    positive: number;
    calls: number;
  }[];
  assignments: {
    id: number;
    from?: string;
    to?: string;
    reason?: string;
    at: string;
  }[];
  config: OperatingConfig;
  can_review: boolean;
};
export async function salesApi<T>(
  path: string,
  method: "GET" | "POST" | "PUT" | "DELETE" | "PATCH" = "GET",
  data?: unknown,
): Promise<T> {
  const r = await invokeWithAuth({
    url: `/api/v1/sales-intelligence${path}`,
    method,
    data,
  });
  return r.data as T;
}
export function salesError(error: unknown): string {
  const e = error as {
    response?: { data?: { detail?: unknown } };
    message?: string;
  };
  const detail = e.response?.data?.detail;
  return typeof detail === "string"
    ? detail
    : Array.isArray(detail)
      ? detail.map((x) => x.msg || "输入有误").join("；")
      : e.message || "加载失败，请重试";
}
export function salesDate(value?: string | null) {
  if (!value) return "—";
  const d = new Date(
    /Z$|[+-]\d\d:\d\d$/.test(value)
      ? value
      : value.length === 10
        ? value + "T00:00:00+08:00"
        : value + "Z",
  );
  return Number.isNaN(d.valueOf())
    ? value
    : d.toLocaleString("zh-CN", {
        timeZone: "Asia/Shanghai",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
      });
}
