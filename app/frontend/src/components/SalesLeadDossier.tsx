import { useEffect, useState } from "react";
import { toast } from "sonner";
import { ArrowUpRight, History, Phone, Save, UserRound } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { NativeSelect } from "@/components/ui/native-select";
import {
  salesApi,
  salesError,
  salesDate,
  potentialOptions,
  outcomeLabels,
  type LeadInsight,
  type Profile,
} from "@/lib/sales-intelligence";

export default function SalesLeadDossier({
  leadId,
  onClose,
  onSaved,
}: {
  leadId: number | null;
  onClose: () => void;
  onSaved?: () => void;
}) {
  const [data, setData] = useState<LeadInsight | null>(null);
  const [error, setError] = useState("");
  const [reload, setReload] = useState(0);
  const [tab, setTab] = useState("history");
  const [form, setForm] = useState<Profile>({});
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    if (!leadId) return;
    let live = true;
    setData(null);
    setError("");
    setTab("history");
    salesApi<LeadInsight>(`/leads/${leadId}`)
      .then((d) => {
        if (live) {
          setData(d);
          setForm(d.profile);
        }
      })
      .catch((e) => {
        if (live) setError(salesError(e));
      });
    return () => {
      live = false;
    };
  }, [leadId, reload]);
  const pipeline = data?.config.pipelines.find(
    (p) => p.key === form.pipeline_key,
  );
  const stage = pipeline?.stages.find((s) => s.key === form.stage_key);
  const update = (x: Partial<Profile>) => setForm((f) => ({ ...f, ...x }));
  async function save() {
    if (!data || saving) return;
    setSaving(true);
    try {
      await salesApi(`/leads/${data.id}`, "PUT", {
        revision: data.revision,
        pipeline_key: form.pipeline_key || "",
        stage_key: form.stage_key || "",
        evidence: form.evidence || "",
        next_step: form.next_step || "",
        next_step_date: form.next_step_date || null,
        need_summary: form.need_summary || "",
        decision_maker: form.decision_maker || "",
        timezone: form.timezone || "",
        custom_fields: Object.fromEntries(
          data.config.custom_fields.map((f) => [
            f.key,
            form.custom_fields?.[f.key] || "",
          ]),
        ),
        potential_override: form.potential_override || "",
        override_reason: form.override_reason || "",
      });
      toast.success("档案已保存，历史依据保留");
      setReload((x) => x + 1);
      onSaved?.();
    } catch (e) {
      toast.error(salesError(e));
    } finally {
      setSaving(false);
    }
  }
  const localHour = data?.profile.timezone
    ? Number(
        new Intl.DateTimeFormat("en-US", {
          timeZone: data.profile.timezone,
          hour: "numeric",
          hourCycle: "h23",
        }).format(new Date()),
      )
    : null;
  const localTime = data?.profile.timezone
    ? new Intl.DateTimeFormat("zh-CN", {
        timeZone: data.profile.timezone,
        weekday: "short",
        hour: "2-digit",
        minute: "2-digit",
        hourCycle: "h23",
      }).format(new Date())
    : "";
  return (
    <Dialog open={leadId !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sales-center-ui si-dossier max-h-[92dvh] max-w-5xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{data?.business_name || "累计联系档案"}</DialogTitle>
        </DialogHeader>
        {error ? (
          <div role="alert" className="si-error">
            {error}
            <Button variant="outline" onClick={() => setReload((x) => x + 1)}>
              重试
            </Button>
          </div>
        ) : !data ? (
          <p className="p-8 text-slate-500">
            正在汇总真实通话、跟进与归属历史…
          </p>
        ) : (
          <>
            <div className="si-dossier-meta">
              <span>
                <Phone size={14} />
                {data.phone}
              </span>
              <span>
                <UserRound size={14} />
                {data.owner}
              </span>
              <span>
                {data.source} · {data.industry}
              </span>
              {localTime && (
                <span>
                  商家当地 {localTime} · {data.profile.timezone}
                </span>
              )}
            </div>
            {localHour !== null && (
              <p className="si-evidence-note">
                建议联系窗口：商家当地 {data.config.default_contact_start}:00–
                {data.config.default_contact_end}:00 ·{" "}
                {localHour >= data.config.default_contact_start &&
                localHour < data.config.default_contact_end
                  ? "当前在建议窗口内"
                  : "当前在建议窗口外，优先按客户约定联系"}
              </p>
            )}
            <div className={`si-classification si-${data.potential}`}>
              <strong>{data.potential_label}</strong>
              <span>{data.rationale.join("；")}</span>
            </div>
            <div className="si-stat-grid">
              {[
                ["已同步真实拨打", data.calls],
                ["官方接通", data.connected],
                ["手工跟进未关联", data.manual_records],
                ["决策人有效沟通", data.decision_conversations],
              ].map(([label, value]) => (
                <div key={label}>
                  <span>{label}</span>
                  <strong>{value}</strong>
                </div>
              ))}
            </div>
            <div className="si-evidence-note">
              真实拨打按通话会话去重。历史手工记录不会推算成电话次数；决策人沟通需要明确记录身份与需求。
            </div>
            <nav className="si-tabs" aria-label="商家档案视图">
              {[
                ["history", "累计与变化"],
                ["progress", "商机与复核"],
                ["ownership", "负责人历史"],
              ].map(([key, label]) => (
                <button
                  key={key}
                  aria-pressed={tab === key}
                  onClick={() => setTab(key)}
                >
                  {label}
                </button>
              ))}
            </nav>
            {tab === "history" && (
              <>
                <div className="si-milestones">
                  <div>
                    <span>首次有意向</span>
                    <b>
                      {data.first_interest_at
                        ? salesDate(data.first_interest_at)
                        : "尚无记录"}
                    </b>
                    <small>
                      {data.first_interest_record_number
                        ? `第 ${data.first_interest_record_number} 条跟进记录`
                        : "等待真实结果"}
                      {data.first_interest_call_number
                        ? ` · 已同步通话中的第 ${data.first_interest_call_number} 次`
                        : " · 对应拨打序号未知"}
                    </small>
                  </div>
                  <div>
                    <span>培育周期</span>
                    <b>
                      {data.days_to_interest === null ||
                      data.days_to_interest === undefined
                        ? "—"
                        : `${data.days_to_interest} 天`}
                    </b>
                    <small>从系统内首次留存联系到有意向</small>
                  </div>
                  <div>
                    <span>接通后的拒绝／暂缓</span>
                    <b>
                      {data.connected_rejections} / {data.connected}
                    </b>
                    <small>
                      {data.connected_without_result} 次接通尚未关联结果
                    </small>
                  </div>
                </div>
                <div className="si-chips">
                  {Object.entries(data.outcomes).map(([k, v]) => (
                    <span key={k}>
                      {outcomeLabels[k] || k} <b>{v}</b>
                    </span>
                  ))}
                  {!data.records && <span>尚无销售结果记录</span>}
                </div>
                {Object.keys(data.rejection_reasons).length > 0 && (
                  <p className="si-evidence-note">
                    已记录原因：
                    {Object.entries(data.rejection_reasons)
                      .map(([k, v]) => `${k}（${v}）`)
                      .join(" · ")}
                  </p>
                )}
                <h3 className="si-section-title">
                  <History size={16} />
                  联系与态度时间线 <span>北京时间</span>
                </h3>
                <div className="si-timeline">
                  {data.timeline.map((item) => (
                    <article key={item.id}>
                      <div className="si-timeline-dot" />
                      <div>
                        <div className="si-timeline-title">
                          <b>
                            {item.details?.after?.stage_label || item.label}
                          </b>
                          <span>
                            {salesDate(item.at)} ·{" "}
                            {item.salesperson || "未记录员工"}
                          </span>
                        </div>
                        <small>
                          {item.source === "manual"
                            ? "手工跟进 · 未关联官方通话"
                            : item.source === "review"
                              ? "档案变更 · 有历史记录"
                              : `官方通话 #${item.official_ordinal} · ${item.connected ? "接通" : "未接通"}`}
                        </small>
                        {item.notes && <p>{item.notes}</p>}
                        {item.details?.after && (
                          <p>
                            {item.details.after.evidence}
                            {item.details.after.override_reason &&
                              `；潜力复核：${item.details.after.override_reason}`}
                          </p>
                        )}
                        {item.details?.reached_person && (
                          <p>
                            沟通对象：
                            {item.details.reached_person === "decision_maker"
                              ? "决策人"
                              : item.details.reached_person === "gatekeeper"
                                ? "前台／其他人员"
                                : "未确认"}
                            {item.details.rejection_reason &&
                              ` · 原因：${item.details.rejection_reason}`}
                          </p>
                        )}
                        {item.details?.need_summary && (
                          <p>需求：{item.details.need_summary}</p>
                        )}
                        {item.details?.next_step && (
                          <p>下一步：{item.details.next_step}</p>
                        )}
                      </div>
                    </article>
                  ))}
                  {!data.timeline.length && (
                    <p className="si-empty">
                      尚无留存联系记录。首次联系后开始累积。
                    </p>
                  )}
                </div>
              </>
            )}
            {tab === "progress" && (
              <div className="si-form">
                <div className="si-form-grid">
                  <label>
                    销售流程
                    <NativeSelect
                      value={form.pipeline_key || ""}
                      onChange={(value) =>
                        update({ pipeline_key: value, stage_key: "" })
                      }
                      options={[
                        { value: "", label: "选择流程" },
                        ...data.config.pipelines.map((p) => ({
                          value: p.key,
                          label: p.label,
                        })),
                      ]}
                    />
                  </label>
                  <label>
                    当前阶段
                    <NativeSelect
                      value={form.stage_key || ""}
                      onChange={(value) => update({ stage_key: value })}
                      options={[
                        { value: "", label: "选择阶段" },
                        ...(pipeline?.stages || []).map((s) => ({
                          value: s.key,
                          label: s.label,
                        })),
                      ]}
                    />
                  </label>
                </div>
                {stage && (
                  <p className="si-evidence-note">
                    推进条件：{stage.evidence} · 停留 {stage.stale_days}{" "}
                    天后提示主管
                  </p>
                )}
                <label>
                  推进／更新依据 *
                  <Textarea
                    value={form.evidence || ""}
                    onChange={(e) => update({ evidence: e.target.value })}
                    placeholder="写清客户确认了什么，或本次分类复核的事实依据"
                  />
                </label>
                <div className="si-form-grid">
                  <label>
                    客户真实需求
                    <Textarea
                      value={form.need_summary || ""}
                      onChange={(e) => update({ need_summary: e.target.value })}
                    />
                  </label>
                  <label>
                    参与人／决策人
                    <Input
                      value={form.decision_maker || ""}
                      onChange={(e) =>
                        update({ decision_maker: e.target.value })
                      }
                    />
                  </label>
                  <label>
                    下一步
                    <Input
                      value={form.next_step || ""}
                      onChange={(e) => update({ next_step: e.target.value })}
                    />
                  </label>
                  <label>
                    跟进截止日期（北京时间）
                    <Input
                      type="date"
                      value={form.next_step_date || ""}
                      onChange={(e) =>
                        update({ next_step_date: e.target.value })
                      }
                    />
                    <small>同步到拨打工作台，当日结束前跟进。</small>
                  </label>
                  <label>
                    商家时区
                    <NativeSelect
                      value={form.timezone || ""}
                      onChange={(v) => update({ timezone: v })}
                      options={[
                        { value: "", label: "尚未核实" },
                        ...[
                          "America/New_York",
                          "America/Chicago",
                          "America/Denver",
                          "America/Los_Angeles",
                          "America/Phoenix",
                          "Pacific/Honolulu",
                          "Asia/Shanghai",
                        ].map((v) => ({ value: v, label: v })),
                      ]}
                    />
                  </label>
                  {data.config.custom_fields.map((f) => (
                    <label key={f.key}>
                      {f.label}
                      {stage && f.required_milestones.includes(stage.milestone)
                        ? " *"
                        : ""}
                      <Input
                        value={form.custom_fields?.[f.key] || ""}
                        onChange={(e) =>
                          update({
                            custom_fields: {
                              ...form.custom_fields,
                              [f.key]: e.target.value,
                            },
                          })
                        }
                      />
                    </label>
                  ))}
                </div>
                {data.can_review && (
                  <div className="si-review">
                    <h4>主管潜力复核</h4>
                    <p>禁止联系与已转客户状态始终遵循既有业务规则。</p>
                    <label>
                      潜力复核分类
                      <NativeSelect
                        value={form.potential_override || ""}
                        onChange={(v) => update({ potential_override: v })}
                        options={[
                          { value: "", label: "按证据自动分类" },
                          ...potentialOptions.filter(
                            (x) => !["blocked", "won"].includes(x.value),
                          ),
                        ]}
                      />
                    </label>
                    {form.potential_override && (
                      <Textarea
                        aria-label="潜力复核依据"
                        placeholder="说明判断依据，保留到历史记录"
                        value={form.override_reason || ""}
                        onChange={(e) =>
                          update({ override_reason: e.target.value })
                        }
                      />
                    )}
                  </div>
                )}
                <Button disabled={saving} onClick={() => void save()}>
                  <Save size={15} />
                  {saving ? "保存中…" : "保存档案与历史"}
                </Button>
              </div>
            )}
            {tab === "ownership" && (
              <>
                <div className="si-table-wrap">
                  <table className="si-table">
                    <thead>
                      <tr>
                        <th>销售</th>
                        <th>官方拨打</th>
                        <th>跟进记录</th>
                        <th>有意向／预约记录</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.contributors.map((p) => (
                        <tr key={p.employee_id}>
                          <td>{p.name || `员工 ${p.employee_id}`}</td>
                          <td>{p.calls}</td>
                          <td>{p.records}</td>
                          <td>{p.positive}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div className="si-timeline">
                  {data.assignments.map((a) => (
                    <article key={a.id}>
                      <ArrowUpRight size={15} />
                      <div>
                        <b>
                          {a.from || "待分配"} → {a.to || "待分配"}
                        </b>
                        <p>{a.reason}</p>
                        <small>{salesDate(a.at)}</small>
                      </div>
                    </article>
                  ))}
                </div>
              </>
            )}
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
