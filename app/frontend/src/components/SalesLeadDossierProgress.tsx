import { useEffect, useState } from 'react';
import { toast } from 'sonner';
import { Save } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { NativeSelect } from '@/components/ui/native-select';
import { salesApi, salesError, potentialOptions, type LeadInsight, type Profile } from '@/lib/sales-intelligence';

/** Existing sales-stage editing stays restricted to the original scoped actors. */
export default function SalesLeadDossierProgress({ data, onSaved, onDirtyChange, canonicalNeed }: { data: LeadInsight; onSaved: () => void; onDirtyChange: (dirty:boolean) => void; canonicalNeed: string }) {
 const [form, setForm] = useState<Profile>(data.profile);
 const [saving, setSaving] = useState(false);
 useEffect(() => { onDirtyChange(JSON.stringify(form) !== JSON.stringify(data.profile)); }, [form, data.profile, onDirtyChange]);
 useEffect(() => () => onDirtyChange(false), [onDirtyChange]);
 const pipeline = data.config.pipelines.find(p => p.key === form.pipeline_key);
 const stage = pipeline?.stages.find(s => s.key === form.stage_key);
 const update = (value: Partial<Profile>) => setForm(previous => ({ ...previous, ...value }));
 const save = async () => {
  if (saving) return;
  setSaving(true);
  try {
   await salesApi(`/leads/${data.id}`, 'PUT', { revision: data.revision, pipeline_key: form.pipeline_key || '', stage_key: form.stage_key || '', evidence: form.evidence || '', next_step: form.next_step || '', next_step_date: form.next_step_date || null, need_summary: form.need_summary || '', decision_maker: form.decision_maker || '', timezone: form.timezone || '', custom_fields: Object.fromEntries(data.config.custom_fields.map(f => [f.key, form.custom_fields?.[f.key] || ''])), potential_override: form.potential_override || '', override_reason: form.override_reason || '' });
   toast.success('商机复核已保存'); onSaved();
  } catch(error) { toast.error(salesError(error)); }
  finally { setSaving(false); }
 };
 return (
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
                      value={canonicalNeed || ""}
                      readOnly
                      aria-label="最新需求（只读）"
                    />
                    <small>请通过补充资料更新需求。</small>
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
                <div className="sd-actions"><Button disabled={saving} variant="outline" onClick={() => setForm(data.profile)}>取消商机修改</Button><Button disabled={saving} onClick={() => void save()}>
                  <Save size={15} />
                  {saving ? "保存中…" : "保存档案与历史"}
                </Button></div>
              </div>
);
}
