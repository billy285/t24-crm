import { useEffect, useState } from "react";
import { toast } from "sonner";
import { CheckCircle2, Plus, Target } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { NativeSelect } from "@/components/ui/native-select";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useRole } from "@/lib/role-context";
import { businessDateKey } from "@/lib/business-date";
import { salesApi, salesError, salesDate } from "@/lib/sales-intelligence";
import { invokeWithAuth } from "@/lib/tokenStore";
type TargetValues = {
  role_template: string;
  calls: number;
  qualified: number;
  demos: number;
  wins: number;
  reason: string;
};
type TeamRow = {
  employee_id: number;
  name: string;
  calls: number;
  connected: number;
  records: number;
  qualified: number;
  demos: number;
  wins: number;
  quality: number | null;
  quality_sample: number;
  score: number | null;
  breakdown: Record<string, number>;
  weights: Record<string, number>;
  target: TargetValues | null;
  target_revision: number;
};
type Team = {
  month: string;
  items: TeamRow[];
  rules_version: number;
  notice: string;
  target_history: {
    id: number;
    employee_id: number;
    revision: number;
    at: string;
    values: TargetValues;
  }[];
};
type Coach = {
  id: number;
  employee_id: number;
  employee: string;
  lead_id?: number;
  action: string;
  due_date: string;
  status: string;
  revision: number;
  completion_note?: string;
};
const weightLabels: Record<string, string> = {
  results: "成交结果",
  pipeline: "商机推进",
  execution: "真实拨打",
  quality: "记录质量",
};

type DailyTeamRow = {
  id: number;
  name: string;
  quota: number | null;
  completed: number | null;
  remaining: number | null;
};
type DailyTeamSummary = {
  rows: DailyTeamRow[];
  connected: number | null;
  overdue: number | null;
  stalled: number | null;
  unassigned: number | null;
  incomplete: boolean;
};
const dailyCount = (value: unknown) => typeof value === "number" && Number.isFinite(value) && value >= 0 ? value : null;

/** Daily task progress is read from existing batches; opening this view never prepares tasks. */
export function SalesTeamToday({ employees, targetDate, onOpenWorkbench }: {
  employees: { id: number; name: string }[];
  targetDate: string;
  onOpenWorkbench: (employeeId: number) => void;
}) {
  const [summary, setSummary] = useState<DailyTeamSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    let live = true;
    setSummary(null);
    setLoading(true);
    const read = async () => {
      const rows: DailyTeamRow[] = employees.map(employee => ({ ...employee, quota: null, completed: null, remaining: null }));
      let cursor = 0;
      const readRows = async () => {
        while (live && cursor < employees.length) {
          const index = cursor++;
          const employee = employees[index];
          try {
            const params = new URLSearchParams({ target_date: targetDate, sales_employee_id: String(employee.id) });
            const response = await invokeWithAuth({ url: `/api/v1/sales-leads/workbench/today?${params}`, method: "GET" });
            const data = response.data;
            if (Number(data?.salesperson?.id) === employee.id && (!data.target_date || data.target_date === targetDate)) {
              rows[index] = { ...employee, quota: dailyCount(data.quota), completed: dailyCount(data.completed_count), remaining: dailyCount(data.remaining_count) };
            }
          } catch { /* An unreadable row stays unknown rather than becoming zero. */ }
        }
      };
      const requests = [
        invokeWithAuth({ url: `/api/v1/sales-leads/dashboard/management?target_date=${targetDate}`, method: "GET" }),
        invokeWithAuth({ url: "/api/v1/merchant-pool/stats", method: "GET" }),
        targetDate === businessDateKey() ? invokeWithAuth({ url: "/api/v1/sales-leads/dashboard/call-report?days=1", method: "GET" }) : Promise.resolve(null),
      ];
      const [results] = await Promise.all([
        Promise.allSettled(requests),
        Promise.all(Array.from({ length: Math.min(4, employees.length) }, () => readRows())),
      ]);
      if (!live) return;
      const management = results[0].status === "fulfilled" ? results[0].value?.data : null;
      const pool = results[1].status === "fulfilled" ? results[1].value?.data : null;
      const report = results[2].status === "fulfilled" ? results[2].value?.data : null;
      const reportCurrent = targetDate === businessDateKey() && report?.source?.status === "verified"
        && report?.period?.start_date === targetDate && report?.period?.end_date === targetDate;
      const dateMatches = management?.target_date === targetDate;
      const overdue = dateMatches ? dailyCount(management?.owner_attention?.overdue_followups) : null;
      const stalled = dateMatches ? dailyCount(management?.owner_attention?.high_intent_stale) : null;
      const unassigned = dailyCount(pool?.pending);
      const connected = reportCurrent ? dailyCount(report?.summary?.connected) : null;
      setSummary({ rows, connected, overdue, stalled, unassigned, incomplete: rows.some(row => row.completed === null || row.quota === null || row.remaining === null) || overdue === null || stalled === null || unassigned === null });
      setLoading(false);
    };
    void read();
    return () => { live = false; };
  }, [employees, targetDate, reload]);

  const value = (count: number | null | undefined) => loading ? "—" : count === null || count === undefined ? "待确认" : count;
  const dateLabel = targetDate === businessDateKey() ? "今日" : "当日";
  const recorded = summary && summary.rows.every(row => row.completed !== null) ? summary.rows.reduce((total, row) => total + (row.completed as number), 0) : null;
  const taskRows = summary?.rows || employees.map(employee => ({ ...employee, quota: null, completed: null, remaining: null }));
  const openProgress = (signal?: "overdue") => window.location.assign(`/sales-leads?view=intelligence&panel=leads${signal ? `&signal=${signal}` : ""}`);
  return <div className="sw-team-today" aria-label="团队今日任务">
    <section className="sw-team-summary" aria-label="团队任务概况">
      <div><span>{dateLabel}已记录</span><strong>{value(recorded)}</strong></div>
      <div title="仅显示所选日期为今天、且已核验的 RingCentral 官方通话记录"><span>官方接通</span><strong>{value(summary?.connected)}</strong></div>
      <div><span>逾期回访</span><strong className={summary?.overdue ? "sw-count-attention" : undefined}>{value(summary?.overdue)}</strong></div>
    </section>
    {summary?.incomplete && <div className="sw-team-error" role="alert"><span>部分任务数据暂不可用</span><Button variant="outline" onClick={() => setReload(current => current + 1)}>重新读取</Button></div>}
    <section className="sw-team-panel" aria-label="团队需要处理">
      <h2>需要处理</h2>
      <div className="sw-team-actions">
        <div title="当前未分配商家，不随任务日期变化"><div><span>待分配商家</span><strong>{value(summary?.unassigned)}</strong></div><Button disabled={loading || summary?.unassigned === null} onClick={() => window.location.assign("/merchant-pool")}>分配商家</Button></div>
        <div><div><span>逾期回访</span><strong className={summary?.overdue ? "sw-count-attention" : undefined}>{value(summary?.overdue)}</strong></div><Button variant="outline" title="查看当前线索" disabled={loading || summary?.overdue === null} onClick={() => openProgress("overdue")}>查看</Button></div>
        <div><div><span>商机待跟进</span><strong>{value(summary?.stalled)}</strong></div><Button variant="outline" title="查看当前商机" disabled={loading || summary?.stalled === null} onClick={() => openProgress()}>查看</Button></div>
      </div>
    </section>
    <section className="sw-team-panel sw-team-progress" aria-label="团队进度">
      <h2>团队进度</h2>
      <div className="sw-team-table-scroll"><table><thead><tr><th>销售</th><th>{dateLabel}目标</th><th>已记录</th><th>待处理</th><th>操作</th></tr></thead><tbody>
        {taskRows.map(row => <tr key={row.id}>
          <td><span className="sw-team-person"><span className="sw-team-avatar" aria-hidden="true">{row.name.slice(0, 1)}</span><strong>{row.name}</strong></span></td>
          <td>{value(row.quota)}</td>
          <td><div className="sw-team-completion"><span>{value(row.completed)}</span>{row.completed !== null && row.quota !== null && row.quota > 0 && <div role="progressbar" aria-label={`${row.name}任务进度`} aria-valuemin={0} aria-valuemax={row.quota} aria-valuenow={row.completed}><span style={{ width: `${Math.min(100, row.completed / row.quota * 100)}%` }} /></div>}</div></td>
          <td>{value(row.remaining)}</td>
          <td><Button variant="outline" onClick={() => onOpenWorkbench(row.id)} aria-label={`查看任务：${row.name}`}>查看任务</Button></td>
        </tr>)}
      </tbody></table></div>
      <div className="sw-team-mobile-list" role="list" aria-label="销售任务进度">
        {taskRows.map(row => <div className="sw-team-mobile-row" role="listitem" key={row.id}>
          <div><span className="sw-team-person"><strong>{row.name}</strong></span><Button variant="outline" onClick={() => onOpenWorkbench(row.id)} aria-label={`查看任务：${row.name}`}>查看任务</Button></div>
          <dl><div><dt>{dateLabel}目标</dt><dd>{value(row.quota)}</dd></div><div><dt>已记录</dt><dd>{value(row.completed)}</dd></div><div><dt>待处理</dt><dd>{value(row.remaining)}</dd></div></dl>
        </div>)}
      </div>
      {!employees.length && <p className="sw-team-empty">暂无可用销售人员</p>}
      {employees.length > 0 && <p className="sw-team-total">{employees.length} 位销售</p>}
    </section>
  </div>;
}

export default function SalesTeamPerformance({
  onOpenLead,
  refreshKey,
}: {
  onOpenLead: (id: number) => void;
  refreshKey: number;
}) {
  const [evidence, setEvidence] = useState<{
    name: string;
    items: {
      lead_id: number | null;
      name: string;
      at: string;
      detail: string;
    }[];
  } | null>(null);
  const [evidenceLoading, setEvidenceLoading] = useState(false);
  const [evidenceError, setEvidenceError] = useState("");
  async function inspect(r: TeamRow, metric: string, label: string) {
    setEvidence({ name: `${r.name} · ${month} · ${label}`, items: [] });
    setEvidenceLoading(true);
    setEvidenceError("");
    try {
      const result = await salesApi<{
        items: {
          lead_id: number | null;
          name: string;
          at: string;
          detail: string;
        }[];
      }>(
        `/team?month=${month}&evidence_employee=${r.employee_id}&metric=${metric}`,
      );
      setEvidence((current) =>
        current ? { ...current, items: result.items } : null,
      );
    } catch (e) {
      setEvidenceError(salesError(e));
    } finally {
      setEvidenceLoading(false);
    }
  }
  const { role, isAdmin } = useRole();
  const canManage = isAdmin || role === "sales_manager";
  const [month, setMonth] = useState(businessDateKey().slice(0, 7));
  const [data, setData] = useState<Team | null>(null);
  const [coaching, setCoaching] = useState<Coach[]>([]);
  const [error, setError] = useState("");
  const [reload, setReload] = useState(0);
  const [editing, setEditing] = useState<TeamRow | null>(null);
  const [form, setForm] = useState<TargetValues>({
    role_template: "full_cycle",
    calls: 0,
    qualified: 0,
    demos: 0,
    wins: 0,
    reason: "",
  });
  const [saving, setSaving] = useState(false);
  const [coachOpen, setCoachOpen] = useState(false);
  const [coachEmployee, setCoachEmployee] = useState("");
  const [coachAction, setCoachAction] = useState("");
  const [coachDate, setCoachDate] = useState(businessDateKey());
  const [completing, setCompleting] = useState<Coach | null>(null);
  const [completionNote, setCompletionNote] = useState("");
  useEffect(() => {
    let live = true;
    setData(null);
    setError("");
    Promise.all([
      salesApi<Team>(`/team?month=${month}`),
      salesApi<Coach[]>("/coaching"),
    ])
      .then(([t, c]) => {
        if (live) {
          setData(t);
          setCoaching(c);
        }
      })
      .catch((e) => {
        if (live) setError(salesError(e));
      });
    return () => {
      live = false;
    };
  }, [month, reload, refreshKey]);
  async function saveTarget() {
    if (!editing || saving) return;
    setSaving(true);
    try {
      await salesApi("/targets", "POST", {
        ...form,
        employee_id: editing.employee_id,
        month,
        previous_revision: editing.target_revision,
      });
      toast.success("月度目标已保存");
      setEditing(null);
      setReload((x) => x + 1);
    } catch (e) {
      toast.error(salesError(e));
    } finally {
      setSaving(false);
    }
  }
  async function saveCoach() {
    setSaving(true);
    try {
      await salesApi("/coaching", "POST", {
        employee_id: Number(coachEmployee),
        action: coachAction,
        due_date: coachDate,
      });
      toast.success("辅导行动已创建");
      setCoachOpen(false);
      setCoachAction("");
      setReload((x) => x + 1);
    } catch (e) {
      toast.error(salesError(e));
    } finally {
      setSaving(false);
    }
  }
  async function finishCoach() {
    if (!completing) return;
    setSaving(true);
    try {
      await salesApi(`/coaching/${completing.id}`, "PUT", {
        revision: completing.revision,
        completion_note: completionNote,
      });
      toast.success("复查记录已保存");
      setCompleting(null);
      setCompletionNote("");
      setReload((x) => x + 1);
    } catch (e) {
      toast.error(salesError(e));
    } finally {
      setSaving(false);
    }
  }
  return (
    <div className="space-y-5">
      <section className="si-panel">
        <div className="si-panel-head">
          <h3>
            <Target size={16} />
            月度目标与绩效参考
          </h3>
          <label className="si-inline-label">
            考核月份
            <Input
              type="month"
              value={month}
              onChange={(e) => e.target.value && setMonth(e.target.value)}
            />
          </label>
        </div>
        {error ? (
          <div className="si-error" role="alert">
            {error}
            <Button onClick={() => setReload((x) => x + 1)}>重试</Button>
          </div>
        ) : !data ? (
          <p className="si-empty">正在加载团队目标与真实记录…</p>
        ) : (
          <>
            <p className="si-evidence-note">{data.notice}</p>
            <div className="si-table-wrap">
              <table className="si-table">
                <thead>
                  <tr>
                    <th>销售</th>
                    <th>真实拨打／目标</th>
                    <th>有效商机／目标</th>
                    <th>完成演示／目标</th>
                    <th>确认成交／目标</th>
                    <th>记录完整度</th>
                    <th>参考得分</th>
                    {canManage && <th>管理</th>}
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((r) => (
                    <tr key={r.employee_id}>
                      <td>
                        <b>{r.name}</b>
                        <small>
                          {r.target?.role_template === "development"
                            ? "开发岗位"
                            : r.target?.role_template === "closer"
                              ? "成交岗位"
                              : "全流程销售"}
                        </small>
                      </td>
                      <td>
                        <button
                          className="si-link"
                          disabled={evidenceLoading}
                          onClick={() => void inspect(r, "calls", "真实拨打")}
                        >
                          {r.calls} / {r.target?.calls ?? "未设"}
                        </button>
                        <small>{r.connected} 次官方接通</small>
                      </td>
                      <td>
                        <button
                          className="si-link"
                          disabled={evidenceLoading}
                          onClick={() =>
                            void inspect(r, "qualified", "有效商机")
                          }
                        >
                          {r.qualified} / {r.target?.qualified ?? "未设"}
                        </button>
                      </td>
                      <td>
                        <button
                          className="si-link"
                          disabled={evidenceLoading}
                          onClick={() => void inspect(r, "demos", "完成演示")}
                        >
                          {r.demos} / {r.target?.demos ?? "未设"}
                        </button>
                      </td>
                      <td>
                        <button
                          className="si-link"
                          disabled={evidenceLoading}
                          onClick={() => void inspect(r, "wins", "确认成交")}
                        >
                          {r.wins} / {r.target?.wins ?? "未设"}
                        </button>
                      </td>
                      <td>
                        <button
                          className="si-link"
                          disabled={evidenceLoading}
                          onClick={() =>
                            void inspect(r, "quality", "记录完整度")
                          }
                        >
                          {r.quality === null ? "—" : `${r.quality}%`}
                        </button>
                        <small>{r.quality_sample} 条有效结果样本</small>
                      </td>
                      <td>
                        <b>
                          {r.score === null ? "暂不评分" : `${r.score} / 100`}
                        </b>
                        <small>
                          {r.score === null
                            ? "需配置目标、足够样本及通话依据"
                            : Object.entries(r.breakdown)
                                .map(([k, v]) => `${weightLabels[k]} ${v}`)
                                .join(" · ")}
                        </small>
                      </td>
                      {canManage && (
                        <td>
                          <Button
                            size="sm"
                            variant="outline"
                            disabled={month < businessDateKey().slice(0, 7)}
                            onClick={() => {
                              setEditing(r);
                              setForm(
                                r.target
                                  ? { ...r.target, reason: "" }
                                  : {
                                      role_template: "full_cycle",
                                      calls: 0,
                                      qualified: 0,
                                      demos: 0,
                                      wins: 0,
                                      reason: "",
                                    },
                              );
                            }}
                          >
                            设置目标
                          </Button>
                        </td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {!data.items.length && (
              <p className="si-empty">当前范围没有销售员工。</p>
            )}
            <details className="si-details">
              <summary>目标版本记录 · 当前月份</summary>
              {data.target_history.map((h) => (
                <p key={h.id}>
                  员工 #{h.employee_id} · 第 {h.revision} 版 · {h.values.reason}{" "}
                  · 拨打 {h.values.calls} / 商机 {h.values.qualified} / 演示{" "}
                  {h.values.demos} / 成交 {h.values.wins}
                </p>
              ))}
              {!data.target_history.length && <p>尚未配置本月目标。</p>}
            </details>
          </>
        )}
      </section>
      <section className="si-panel">
        <div className="si-panel-head">
          <h3>辅导与复查行动</h3>
          {canManage && (
            <Button variant="outline" onClick={() => setCoachOpen(true)}>
              <Plus size={15} />
              安排辅导
            </Button>
          )}
        </div>
        <div className="si-coaching-list">
          {coaching.map((c) => (
            <article key={c.id}>
              <div>
                <b>
                  {c.employee} · {c.action}
                </b>
                <small>
                  复查日期 {c.due_date} ·{" "}
                  {c.status === "done" ? "已完成" : "待复查"}
                </small>
                {c.completion_note && <p>{c.completion_note}</p>}
              </div>
              <div>
                {c.lead_id && (
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => onOpenLead(c.lead_id!)}
                  >
                    商家档案
                  </Button>
                )}
                {c.status === "open" && (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => {
                      setCompleting(c);
                      setCompletionNote("");
                    }}
                  >
                    记录复查
                  </Button>
                )}
                {c.status === "done" && (
                  <CheckCircle2 size={18} className="text-emerald-600" />
                )}
              </div>
            </article>
          ))}
          {!coaching.length && (
            <p className="si-empty">
              尚无辅导行动。围绕具体问题安排一个改进动作和复查日期。
            </p>
          )}
        </div>
      </section>
      <Dialog
        open={!!evidence}
        onOpenChange={(open) => !open && setEvidence(null)}
      >
        <DialogContent className="sales-center-ui max-h-[85dvh] max-w-3xl overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{evidence?.name}</DialogTitle>
          </DialogHeader>
          {evidenceError ? (
            <p role="alert" className="si-error">
              {evidenceError}
            </p>
          ) : evidenceLoading ? (
            <p className="si-empty">正在读取指标依据…</p>
          ) : (
            <div className="si-timeline">
              {evidence?.items.map((item, i) => (
                <article key={i}>
                  <div>
                    <b>{item.name}</b>
                    <small>{salesDate(item.at)}</small>
                    <p>{item.detail}</p>
                    {item.lead_id && (
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => {
                          setEvidence(null);
                          onOpenLead(item.lead_id!);
                        }}
                      >
                        查看累计档案
                      </Button>
                    )}
                  </div>
                </article>
              ))}
              {!evidence?.items.length && (
                <p className="si-empty">该月份尚无此项记录。</p>
              )}
            </div>
          )}
        </DialogContent>
      </Dialog>
      <Dialog open={!!editing} onOpenChange={(o) => !o && setEditing(null)}>
        <DialogContent className="sales-center-ui">
          <DialogHeader>
            <DialogTitle>
              {editing?.name} · {month} 目标
            </DialogTitle>
          </DialogHeader>
          <div className="si-form">
            <label>
              岗位模板
              <NativeSelect
                value={form.role_template}
                onChange={(v) => setForm((f) => ({ ...f, role_template: v }))}
                options={[
                  { value: "full_cycle", label: "全流程销售" },
                  { value: "development", label: "开发岗位：成交权重转入商机" },
                  { value: "closer", label: "成交岗位：拨打权重转入成交" },
                ]}
              />
            </label>
            <div className="si-form-grid">
              {[
                ["calls", "真实拨打目标"],
                ["qualified", "有效商机目标"],
                ["demos", "实际演示目标"],
                ["wins", "确认成交目标"],
              ].map(([key, label]) => (
                <label key={key}>
                  {label}
                  <Input
                    type="number"
                    min="1"
                    value={form[key as keyof TargetValues]}
                    onChange={(e) =>
                      setForm((f) => ({ ...f, [key]: Number(e.target.value) }))
                    }
                  />
                </label>
              ))}
            </div>
            <label>
              设置／调整原因
              <Textarea
                value={form.reason}
                onChange={(e) =>
                  setForm((f) => ({ ...f, reason: e.target.value }))
                }
              />
            </label>
            <Button disabled={saving} onClick={() => void saveTarget()}>
              保存目标版本
            </Button>
          </div>
        </DialogContent>
      </Dialog>
      <Dialog open={coachOpen} onOpenChange={setCoachOpen}>
        <DialogContent className="sales-center-ui">
          <DialogHeader>
            <DialogTitle>安排辅导</DialogTitle>
          </DialogHeader>
          <div className="si-form">
            <label>
              销售员工
              <NativeSelect
                value={coachEmployee}
                onChange={setCoachEmployee}
                options={[
                  { value: "", label: "选择销售" },
                  ...(data?.items || []).map((x) => ({
                    value: String(x.employee_id),
                    label: x.name,
                  })),
                ]}
              />
            </label>
            <label>
              具体改进动作
              <Textarea
                value={coachAction}
                onChange={(e) => setCoachAction(e.target.value)}
                placeholder="例如：复盘本周三次演示，明确每次沟通的下一步"
              />
            </label>
            <label>
              复查日期
              <Input
                type="date"
                value={coachDate}
                onChange={(e) => setCoachDate(e.target.value)}
              />
            </label>
            <Button
              disabled={saving || !coachEmployee}
              onClick={() => void saveCoach()}
            >
              创建辅导行动
            </Button>
          </div>
        </DialogContent>
      </Dialog>
      <Dialog
        open={!!completing}
        onOpenChange={(o) => !o && setCompleting(null)}
      >
        <DialogContent className="sales-center-ui">
          <DialogHeader>
            <DialogTitle>记录复查结果</DialogTitle>
          </DialogHeader>
          <p>{completing?.action}</p>
          <Textarea
            aria-label="复查结果"
            value={completionNote}
            onChange={(e) => setCompletionNote(e.target.value)}
            placeholder="完成了什么，有什么变化，后续还需要什么帮助"
          />
          <Button disabled={saving} onClick={() => void finishCoach()}>
            保存复查结果
          </Button>
        </DialogContent>
      </Dialog>
    </div>
  );
}
