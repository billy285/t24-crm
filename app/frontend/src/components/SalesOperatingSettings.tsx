import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Plus, Save } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { NativeSelect } from "@/components/ui/native-select";
import { businessDateKey } from "@/lib/business-date";
import {
  salesApi,
  salesError,
  type OperatingConfig,
  type Stage,
} from "@/lib/sales-intelligence";
type SettingData = {
  config: OperatingConfig;
  defaults: OperatingConfig;
  version: number;
  can_publish: boolean;
  history: {
    id: number;
    effective_month: string;
    by: string;
    reason: string;
    config: OperatingConfig;
  }[];
};
type Preview = {
  total: number;
  changed: number;
  items: {
    id: number;
    name: string;
    before: string;
    after: string;
    reason: string[];
  }[];
  weights_before: Record<string, number>;
  weights_after: Record<string, number>;
};
const milestones = [
  ["none", "一般阶段"],
  ["qualified", "需求已确认"],
  ["scheduled", "预约已确认"],
  ["demo", "演示／方案沟通已完成"],
  ["quoted", "报价已审批"],
  ["decision", "等待决策"],
  ["won", "成交确认"],
  ["handoff", "交接完成"],
  ["lost", "失单"],
  ["nurture", "暂缓培育"],
].map(([value, label]) => ({ value, label }));
const weightLabels: Record<string, string> = {
  results: "成交结果",
  pipeline: "商机推进",
  execution: "真实拨打",
  quality: "记录质量",
};
export default function SalesOperatingSettings({
  onPublished,
}: {
  onPublished: () => void;
}) {
  const [data, setData] = useState<SettingData | null>(null);
  const [config, setConfig] = useState<OperatingConfig | null>(null);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  const [month, setMonth] = useState(businessDateKey().slice(0, 7));
  const [reason, setReason] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [busy, setBusy] = useState(false);
  const [section, setSection] = useState("rules");
  useEffect(() => {
    let live = true;
    salesApi<SettingData>("/settings")
      .then((d) => {
        if (live) {
          setData(d);
          setConfig(structuredClone(d.config));
          setError("");
        }
      })
      .catch((e) => {
        if (live) setError(salesError(e));
      });
    return () => {
      live = false;
    };
  }, [revision]);
  function change(next: OperatingConfig) {
    setConfig(next);
    setPreview(null);
  }
  async function inspect() {
    if (!config) return;
    setBusy(true);
    try {
      setPreview(await salesApi<Preview>("/settings/preview", "POST", config));
    } catch (e) {
      toast.error(salesError(e));
    } finally {
      setBusy(false);
    }
  }
  async function publish() {
    if (!config || !preview || busy) return;
    setBusy(true);
    try {
      await salesApi("/settings", "POST", {
        config,
        effective_month: month,
        reason,
      });
      toast.success("销售规则已发布");
      setPreview(null);
      setRevision((x) => x + 1);
      onPublished();
    } catch (e) {
      toast.error(salesError(e));
    } finally {
      setBusy(false);
    }
  }
  if (error)
    return (
      <div className="si-error" role="alert">
        {error}
        <Button onClick={() => setRevision((x) => x + 1)}>重试</Button>
      </div>
    );
  if (!config || !data) return <p className="si-empty">正在读取销售配置…</p>;
  const editStage = (pIndex: number, sIndex: number, x: Partial<Stage>) =>
    change({
      ...config,
      pipelines: config.pipelines.map((p, pi) =>
        pi === pIndex
          ? {
              ...p,
              stages: p.stages.map((s, si) =>
                si === sIndex ? { ...s, ...x } : s,
              ),
            }
          : p,
      ),
    });
  return (
    <section className="si-panel si-settings">
      <div className="si-panel-head">
        <h3>销售设置</h3>
        <span>
          {data.version ? `生效版本 #${data.version}` : "使用系统默认模板"}
        </span>
      </div>
      <p className="si-evidence-note">
        规则按月份生效，同月已发布版本不可覆盖。历史档案保留当时阶段及依据，绩效仅作管理参考。
      </p>
      <nav className="si-tabs" aria-label="销售配置分类">
        {[
          ["rules", "潜力与绩效"],
          ["pipelines", "流程与字段"],
          ["history", "版本记录"],
        ].map(([k, v]) => (
          <button
            key={k}
            aria-pressed={section === k}
            onClick={() => setSection(k)}
          >
            {v}
          </button>
        ))}
      </nav>
      {section === "rules" && (
        <fieldset disabled={!data.can_publish || busy} className="si-form">
          <h4>潜力分类与联系窗口</h4>
          <div className="si-form-grid">
            {[
              ["repeated_rejection_count", "拒绝／暂缓复核次数"],
              ["unconnected_attempts", "多次未接通提示次数"],
              ["interest_stale_days", "意向保持优先的天数"],
              ["default_contact_start", "当地建议联系开始小时"],
              ["default_contact_end", "当地建议联系结束小时"],
            ].map(([key, label]) => (
              <label key={key}>
                {label}
                <Input
                  type="number"
                  value={config[key as keyof OperatingConfig] as number}
                  onChange={(e) =>
                    change({ ...config, [key]: Number(e.target.value) })
                  }
                />
              </label>
            ))}
          </div>
          <h4>全流程销售参考权重</h4>
          <div className="si-form-grid">
            {Object.entries(config.weights).map(([key, v]) => (
              <label key={key}>
                {weightLabels[key]} %
                <Input
                  type="number"
                  min="0"
                  max="100"
                  value={v}
                  onChange={(e) =>
                    change({
                      ...config,
                      weights: {
                        ...config.weights,
                        [key]: Number(e.target.value),
                      },
                    })
                  }
                />
              </label>
            ))}
          </div>
          <p className="si-evidence-note">
            当前合计 {Object.values(config.weights).reduce((a, b) => a + b, 0)}
            %。开发岗位将成交权重计入商机；成交岗位将拨打权重计入成交。具体目标按员工和月份设置。
          </p>
        </fieldset>
      )}
      {section === "pipelines" && (
        <fieldset disabled={!data.can_publish || busy} className="si-form">
          {config.pipelines.map((p, pi) => (
            <section className="si-pipeline-editor" key={p.key}>
              <label>
                流程名称
                <Input
                  value={p.label}
                  onChange={(e) =>
                    change({
                      ...config,
                      pipelines: config.pipelines.map((x, i) =>
                        i === pi ? { ...x, label: e.target.value } : x,
                      ),
                    })
                  }
                />
              </label>
              {p.stages.map((s, si) => (
                <div className="si-stage-editor" key={s.key}>
                  <label>
                    阶段名称
                    <Input
                      value={s.label}
                      onChange={(e) =>
                        editStage(pi, si, { label: e.target.value })
                      }
                    />
                  </label>
                  <label>
                    业务含义
                    <NativeSelect
                      value={s.milestone}
                      onChange={(v) => editStage(pi, si, { milestone: v })}
                      options={milestones}
                    />
                  </label>
                  <label>
                    停留提醒（天）
                    <Input
                      type="number"
                      min="1"
                      max="180"
                      value={s.stale_days}
                      onChange={(e) =>
                        editStage(pi, si, {
                          stale_days: Number(e.target.value),
                        })
                      }
                    />
                  </label>
                  <label className="si-stage-evidence">
                    推进条件
                    <Input
                      value={s.evidence}
                      onChange={(e) =>
                        editStage(pi, si, { evidence: e.target.value })
                      }
                    />
                  </label>
                  <Button
                    variant="ghost"
                    disabled={p.stages.length <= 2}
                    onClick={() =>
                      change({
                        ...config,
                        pipelines: config.pipelines.map((x, i) =>
                          i === pi
                            ? {
                                ...x,
                                stages: x.stages.filter((_, n) => n !== si),
                              }
                            : x,
                        ),
                      })
                    }
                  >
                    移除阶段
                  </Button>
                </div>
              ))}
              <Button
                variant="outline"
                disabled={p.stages.length >= 15}
                onClick={() =>
                  change({
                    ...config,
                    pipelines: config.pipelines.map((x, i) =>
                      i === pi
                        ? {
                            ...x,
                            stages: [
                              ...x.stages,
                              {
                                key: `stage_${Date.now()}`,
                                label: "新阶段",
                                evidence: "记录客户确认的事实和下一步",
                                milestone: "none",
                                stale_days: 7,
                              },
                            ],
                          }
                        : x,
                    ),
                  })
                }
              >
                <Plus size={14} />
                增加阶段
              </Button>
            </section>
          ))}
          <Button
            variant="outline"
            disabled={config.pipelines.length >= 8}
            onClick={() =>
              change({
                ...config,
                pipelines: [
                  ...config.pipelines,
                  {
                    ...structuredClone(data.defaults.pipelines[0]),
                    key: `flow_${Date.now()}`,
                    label: "新销售流程",
                  },
                ],
              })
            }
          >
            增加销售流程
          </Button>
          <h4>商家自定义字段</h4>
          {config.custom_fields.map((f, fi) => (
            <div className="si-field-editor" key={f.key}>
              <label>
                字段名称
                <Input
                  value={f.label}
                  onChange={(e) =>
                    change({
                      ...config,
                      custom_fields: config.custom_fields.map((x, i) =>
                        i === fi ? { ...x, label: e.target.value } : x,
                      ),
                    })
                  }
                />
              </label>
              <label>
                在哪个阶段必填
                <NativeSelect
                  value={f.required_milestones[0] || ""}
                  onChange={(v) =>
                    change({
                      ...config,
                      custom_fields: config.custom_fields.map((x, i) =>
                        i === fi
                          ? { ...x, required_milestones: v ? [v] : [] }
                          : x,
                      ),
                    })
                  }
                  options={[{ value: "", label: "选填" }, ...milestones]}
                />
              </label>
              <Button
                variant="ghost"
                onClick={() =>
                  change({
                    ...config,
                    custom_fields: config.custom_fields.filter(
                      (_, i) => i !== fi,
                    ),
                  })
                }
              >
                移除字段
              </Button>
            </div>
          ))}
          <Button
            variant="outline"
            disabled={config.custom_fields.length >= 12}
            onClick={() =>
              change({
                ...config,
                custom_fields: [
                  ...config.custom_fields,
                  {
                    key: `field_${Date.now()}`,
                    label: "新字段",
                    required_milestones: [],
                  },
                ],
              })
            }
          >
            增加字段
          </Button>
        </fieldset>
      )}
      {section === "history" && (
        <div className="si-version-list">
          {data.history.map((h) => (
            <article key={h.id}>
              <div>
                <b>
                  {h.effective_month} 生效 · #{h.id}
                </b>
                <p>
                  {h.reason} · {h.by}
                </p>
              </div>
              {data.can_publish && (
                <Button
                  variant="outline"
                  onClick={() => {
                    change(structuredClone(h.config));
                    setSection("rules");
                  }}
                >
                  以此版本为新模板
                </Button>
              )}
            </article>
          ))}
          {!data.history.length && (
            <p className="si-empty">尚未发布自定义版本，当前使用系统模板。</p>
          )}
        </div>
      )}
      {data.can_publish && section !== "history" && (
        <div className="si-publish">
          <div className="si-form-grid">
            <label>
              生效月份
              <Input
                type="month"
                min={businessDateKey().slice(0, 7)}
                value={month}
                onChange={(e) => setMonth(e.target.value)}
              />
            </label>
            <label>
              发布原因
              <Input
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                placeholder="说明调整目的"
              />
            </label>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button
              variant="outline"
              disabled={busy}
              onClick={() => change(structuredClone(data.defaults))}
            >
              恢复默认模板到编辑区
            </Button>
            <Button
              variant="outline"
              disabled={busy}
              onClick={() => void inspect()}
            >
              预览分类影响
            </Button>
            <Button
              disabled={busy || !preview || reason.trim().length < 3}
              onClick={() => void publish()}
            >
              <Save size={15} />
              发布版本
            </Button>
          </div>
          {preview && (
            <div className="si-preview">
              <b>
                当前可见 {preview.total} 家商家中，{preview.changed}{" "}
                家分类或判断依据将变化
              </b>
              <p>
                权重：
                {Object.entries(preview.weights_before)
                  .map(
                    ([k, v]) =>
                      `${weightLabels[k]} ${v}→${preview.weights_after[k]}`,
                  )
                  .join(" · ")}
              </p>
              {preview.items.map((i) => (
                <p key={i.id}>
                  {i.name}：{i.before} → {i.after} · {i.reason.join("；")}
                </p>
              ))}
            </div>
          )}
        </div>
      )}
      {!data.can_publish && (
        <p className="si-evidence-note">
          主管可查看规则，并在团队目标页面配置本人团队；全局规则由管理员发布。
        </p>
      )}
    </section>
  );
}
