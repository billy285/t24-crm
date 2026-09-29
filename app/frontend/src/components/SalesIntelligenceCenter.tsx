import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import {
  ArrowRight,
  BarChart3,
  Bookmark,
  Filter,
  RefreshCw,
  Search,
  Settings2,
  Users,
  type LucideIcon,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { useRole } from "@/lib/role-context";
import {
  salesApi,
  salesError,
  salesDate,
  potentialOptions,
  type LeadInsight,
} from "@/lib/sales-intelligence";
import SalesLeadDossier from "./SalesLeadDossier";
import SalesOperatingSettings from "./SalesOperatingSettings";
import SalesTeamPerformance from "./SalesTeamPerformance";

type Overview = {
  total: number;
  counts: Record<string, number>;
  calls: number;
  connected: number;
  manual_records: number;
  pending_calls: number;
  rules_version: number;
  groups: {
    dimension: string;
    label: string;
    leads: number;
    calls: number;
    interested: number;
    converted: number;
    interest_rate: number;
  }[];
  alerts: {
    id: number;
    name: string;
    owner: string;
    reason: string;
    next_step?: string;
  }[];
  stages: Record<string, number>;
  sources: string[];
  industries: string[];
  coverage_notice: string;
};
type Facets = {
  owners: { value: string; label: string }[];
  sources: string[];
  industries: string[];
  stages: string[];
};
type View = { id: number; name: string; filters: Record<string, string> };
const emptyFilters = {
  search: "",
  potential: "",
  min_calls: "0",
  source: "",
  industry: "",
  owner: "",
  signal: "",
  stage: "",
  sort: "attention",
};
export default function SalesIntelligenceCenter() {
  const { role, isAdmin } = useRole();
  const manager = isAdmin || role === "sales_manager";
  const [panel, setPanel] = useState(() => {
    const requested = new URLSearchParams(window.location.search).get("panel");
    return requested &&
      ["leads", "team", ...(manager ? ["overview", "settings"] : [])].includes(
        requested,
      )
      ? requested
      : manager
        ? "overview"
        : "leads";
  });
  const [overview, setOverview] = useState<Overview | null>(null);
  const [items, setItems] = useState<LeadInsight[]>([]);
  const [filters, setFilters] = useState(emptyFilters);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [overviewError, setOverviewError] = useState("");
  const [views, setViews] = useState<View[]>([]);
  const [viewName, setViewName] = useState("");
  const [savingView, setSavingView] = useState(false);
  const [leadId, setLeadId] = useState<number | null>(null);
  const [revision, setRevision] = useState(0);
  const [facets, setFacets] = useState<Facets>({
    owners: [],
    sources: [],
    industries: [],
    stages: [],
  });
  const refresh = useCallback(() => setRevision((x) => x + 1), []);
  useEffect(() => {
    let live = true;
    if (manager) {
      salesApi<Overview>("/overview")
        .then((d) => {
          if (live) {
            setOverview(d);
            setOverviewError("");
          }
        })
        .catch((e) => {
          if (live) {
            setOverview(null);
            setOverviewError(salesError(e));
          }
        });
    }
    salesApi<View[]>("/views")
      .then((d) => {
        if (live) setViews(d);
      })
      .catch(() => {
        if (live) setViews([]);
      });
    return () => {
      live = false;
    };
  }, [manager, revision]);
  useEffect(() => {
    let live = true;
    setLoading(true);
    setError("");
    const t = window.setTimeout(() => {
      const p = new URLSearchParams({
        skip: String((page - 1) * 30),
        limit: "30",
      });
      Object.entries(filters).forEach(([k, v]) => {
        if (v) p.set(k, v);
      });
      salesApi<{ items: LeadInsight[]; total: number; facets: Facets }>(
        `/leads?${p}`,
      )
        .then((d) => {
          if (live) {
            setItems(d.items);
            setTotal(d.total);
            setFacets(d.facets);
          }
        })
        .catch((e) => {
          if (live) {
            setItems([]);
            setTotal(0);
            setError(salesError(e));
          }
        })
        .finally(() => {
          if (live) setLoading(false);
        });
    }, 200);
    return () => {
      live = false;
      window.clearTimeout(t);
    };
  }, [filters, page, revision]);
  const filter = (values: Partial<typeof emptyFilters>) => {
    setFilters((f) => ({ ...f, ...values }));
    setPage(1);
  };
  const drill = (values: Partial<typeof emptyFilters>) => {
    setFilters({ ...emptyFilters, ...values });
    setPage(1);
    setPanel("leads");
  };
  async function saveView() {
    if (!viewName.trim() || savingView) return;
    setSavingView(true);
    try {
      await salesApi("/views", "POST", { name: viewName.trim(), filters });
      toast.success("常用视图已保存到你的账号");
      setViewName("");
      refresh();
    } catch (e) {
      toast.error(salesError(e));
    } finally {
      setSavingView(false);
    }
  }
  const panels: [string, string, LucideIcon][] = manager
    ? [
        ["overview", "经营总览", BarChart3],
        ["leads", "商家潜力", Filter],
        ["team", "团队目标与辅导", Users],
        ["settings", "销售设置", Settings2],
      ]
    : [
        ["leads", "商家潜力", Filter],
        ["team", "我的目标与辅导", Users],
      ];
  return (
    <section className="si-center" aria-label="销售经营中心">
      <div className="si-center-header">
        <div>
          <p>SALES INTELLIGENCE</p>
          <h2>{manager ? "销售经营中心" : "我的商家与目标"}</h2>
          <span>从每一次联系，看清客户变化与下一步。</span>
        </div>
        <Button variant="outline" onClick={refresh}>
          <RefreshCw size={15} />
          刷新
        </Button>
      </div>
      <nav className="si-tabs" aria-label="销售经营中心视图">
        {panels.map(([id, label, Icon]) => (
          <button
            key={id}
            aria-pressed={panel === id}
            onClick={() => setPanel(id)}
          >
            <Icon size={15} />
            {label}
          </button>
        ))}
      </nav>
      {panel === "overview" && manager && (
        <>
          {overviewError ? (
            <div className="si-error" role="alert">
              {overviewError}
              <Button onClick={refresh}>重试</Button>
            </div>
          ) : !overview ? (
            <p className="si-empty">正在汇总团队证据…</p>
          ) : (
            <>
              <div className="si-stat-grid">
                {[
                  ["当前范围商家", overview.total, ""],
                  ["优先推进", overview.counts.priority || 0, "priority"],
                  ["持续培育", overview.counts.nurture || 0, "nurture"],
                  ["待判断", overview.counts.unknown || 0, "unknown"],
                ].map(([label, value, potential]) => (
                  <button
                    key={label}
                    onClick={() => drill({ potential: String(potential) })}
                  >
                    <span>{label}</span>
                    <strong>{value}</strong>
                    <small>
                      查看商家 <ArrowRight size={12} />
                    </small>
                  </button>
                ))}
              </div>
              <div className="si-fact-strip">
                <span>
                  已同步真实拨打 <b>{overview.calls}</b>
                </span>
                <span>
                  官方接通 <b>{overview.connected}</b>
                </span>
                <span>
                  未关联手工跟进 <b>{overview.manual_records}</b>
                </span>
                <span>
                  待核验通话事件 <b>{overview.pending_calls}</b>
                </span>
              </div>
              <div className="si-two-col">
                <section className="si-panel">
                  <div className="si-panel-head">
                    <h3>今天需要介入</h3>
                    <span>{overview.alerts.length} 项</span>
                  </div>
                  {overview.alerts.slice(0, 8).map((a) => (
                    <button
                      className="si-action-row"
                      key={a.id}
                      onClick={() => setLeadId(a.id)}
                    >
                      <div>
                        <b>{a.name}</b>
                        <small>
                          {a.owner} · {a.reason}
                        </small>
                      </div>
                      <ArrowRight size={15} />
                    </button>
                  ))}
                  {!overview.alerts.length && (
                    <p className="si-empty">当前没有逾期或商机停留提醒。</p>
                  )}
                  {overview.alerts.length > 8 && (
                    <Button
                      variant="ghost"
                      onClick={() => drill({ signal: "overdue" })}
                    >
                      查看逾期跟进
                    </Button>
                  )}
                </section>
                <section className="si-panel">
                  <div className="si-panel-head">
                    <h3>商机阶段分布</h3>
                    <span>当前存量</span>
                  </div>
                  {Object.entries(overview.stages).map(([stage, n]) => (
                    <div className="si-stage-row" key={stage}>
                      <button
                        className="si-link"
                        onClick={() => drill({ stage })}
                      >
                        {stage}
                      </button>
                      <div>
                        <i
                          style={{
                            width: `${Math.max(2, (n / Math.max(1, overview.total)) * 100)}%`,
                          }}
                        />
                      </div>
                      <b>{n}</b>
                    </div>
                  ))}
                  <p className="si-evidence-note">
                    商机推进需满足阶段条件。成交与交接沿用现有审核。
                  </p>
                </section>
              </div>
              <section className="si-panel">
                <div className="si-panel-head">
                  <h3>来源与行业质量</h3>
                  <span>点击分组查看商家</span>
                </div>
                <div className="si-table-wrap">
                  <table className="si-table">
                    <thead>
                      <tr>
                        <th>分组</th>
                        <th>商家样本</th>
                        <th>真实拨打</th>
                        <th>曾有意向</th>
                        <th>已转客户</th>
                        <th>历史意向比例</th>
                      </tr>
                    </thead>
                    <tbody>
                      {overview.groups.map((g) => (
                        <tr key={g.dimension + g.label}>
                          <td>
                            <button
                              className="si-link"
                              onClick={() => drill({ [g.dimension]: g.label })}
                            >
                              {g.dimension === "source" ? "来源" : "行业"} ·{" "}
                              {g.label}
                            </button>
                          </td>
                          <td>{g.leads}</td>
                          <td>{g.calls}</td>
                          <td>{g.interested}</td>
                          <td>{g.converted}</td>
                          <td>{g.interest_rate}%</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <p className="si-evidence-note">{overview.coverage_notice}</p>
              </section>
            </>
          )}
        </>
      )}
      {panel === "leads" && (
        <>
          <div className="si-panel si-filter-panel">
            <div className="si-filter-grid">
              <label>
                商家搜索
                <div className="si-search">
                  <Search size={15} />
                  <Input
                    aria-label="累计档案商家搜索"
                    value={filters.search}
                    onChange={(e) => filter({ search: e.target.value })}
                    placeholder="商家名称或电话"
                  />
                </div>
              </label>
              <label>
                潜力分类
                <NativeSelect
                  value={filters.potential}
                  onChange={(v) => filter({ potential: v })}
                  options={[
                    { value: "", label: "全部分类" },
                    ...potentialOptions,
                  ]}
                />
              </label>
              <label>
                联系信号
                <NativeSelect
                  value={filters.signal}
                  onChange={(v) => filter({ signal: v })}
                  options={[
                    { value: "", label: "全部联系信号" },
                    { value: "connected", label: "有官方接通记录" },
                    { value: "manual_records", label: "有未关联手工跟进" },
                    { value: "pending_calls", label: "有待核验通话" },
                    {
                      value: "all_rejected",
                      label: "已关联接通结果全部拒绝／暂缓",
                    },
                    { value: "unreached", label: "真实拨打仍未接通" },
                    { value: "turned_positive", label: "拒绝后转为有意向" },
                    { value: "overdue", label: "跟进逾期" },
                    { value: "no_next_step", label: "有意向缺少下一步" },
                  ]}
                />
              </label>
              <label>
                至少真实拨打次数
                <Input
                  type="number"
                  min="0"
                  value={filters.min_calls}
                  onChange={(e) => filter({ min_calls: e.target.value })}
                />
              </label>
              <label>
                资料来源
                <NativeSelect
                  value={filters.source}
                  onChange={(v) => filter({ source: v })}
                  options={[
                    { value: "", label: "全部来源" },
                    ...facets.sources.map((v) => ({ value: v, label: v })),
                  ]}
                />
              </label>
              <label>
                行业
                <NativeSelect
                  value={filters.industry}
                  onChange={(v) => filter({ industry: v })}
                  options={[
                    { value: "", label: "全部行业" },
                    ...facets.industries.map((v) => ({ value: v, label: v })),
                  ]}
                />
              </label>
              {manager && (
                <label>
                  负责人
                  <NativeSelect
                    value={filters.owner}
                    onChange={(v) => filter({ owner: v })}
                    options={[
                      { value: "", label: "全部负责人" },
                      ...facets.owners,
                    ]}
                  />
                </label>
              )}
              <label>
                商机阶段
                <NativeSelect
                  value={filters.stage}
                  onChange={(v) => filter({ stage: v })}
                  options={[
                    { value: "", label: "全部阶段" },
                    ...facets.stages.map((v) => ({ value: v, label: v })),
                  ]}
                />
              </label>
              <label>
                排序
                <NativeSelect
                  value={filters.sort}
                  onChange={(v) => filter({ sort: v })}
                  options={[
                    { value: "attention", label: "优先处理提醒" },
                    { value: "calls", label: "累计拨打最多" },
                    { value: "recent", label: "最近联系" },
                  ]}
                />
              </label>
              <Button
                variant="outline"
                onClick={() => {
                  setFilters(emptyFilters);
                  setPage(1);
                }}
              >
                清空筛选
              </Button>
            </div>
            <div className="si-saved-views">
              <Bookmark size={15} />
              {views.map((v) => (
                <button
                  key={v.id}
                  onClick={() => {
                    setFilters({ ...emptyFilters, ...v.filters });
                    setPage(1);
                  }}
                >
                  {v.name}
                </button>
              ))}
              <Input
                aria-label="常用视图名称"
                value={viewName}
                onChange={(e) => setViewName(e.target.value)}
                placeholder="为当前筛选命名"
                maxLength={60}
              />
              <Button
                variant="outline"
                disabled={!viewName.trim() || savingView}
                onClick={() => void saveView()}
              >
                保存个人视图
              </Button>
            </div>
          </div>
          <section className="si-panel">
            <div className="si-panel-head">
              <h3>商家累计联系档案</h3>
              <span>{loading ? "正在加载…" : `${total} 家商家`}</span>
            </div>
            <p className="si-evidence-note">
              拨打次数仅统计已同步的官方通话。未知历史不推算；首次意向序号以系统留存记录为准。
            </p>
            {error ? (
              <div className="si-error" role="alert">
                {error}
                <Button onClick={refresh}>重试</Button>
              </div>
            ) : (
              <div className="si-table-wrap">
                <table className="si-table">
                  <thead>
                    <tr>
                      <th>商家／负责人</th>
                      <th>潜力与依据</th>
                      <th>拨打／接通</th>
                      <th>手工未关联</th>
                      <th>首次有意向</th>
                      <th>下一步</th>
                      <th>档案</th>
                    </tr>
                  </thead>
                  <tbody>
                    {!loading &&
                      items.map((i) => (
                        <tr key={i.id}>
                          <td>
                            <b>{i.business_name}</b>
                            <small>
                              {i.owner} · {i.industry}
                            </small>
                          </td>
                          <td>
                            <span className={`si-badge si-${i.potential}`}>
                              {i.potential_label}
                            </span>
                            <small>{i.rationale[0]}</small>
                          </td>
                          <td>
                            <b>
                              {i.calls} / {i.connected}
                            </b>
                            <small>
                              {i.connected_rejections} 次接通拒绝／暂缓
                            </small>
                          </td>
                          <td>
                            {i.manual_records}
                            <small>共有 {i.records} 条跟进</small>
                          </td>
                          <td>
                            {i.first_interest_record_number
                              ? `第 ${i.first_interest_record_number} 条记录`
                              : "尚无记录"}
                            <small>
                              {i.first_interest_call_number
                                ? `已同步通话第 ${i.first_interest_call_number} 次`
                                : "对应拨打序号未知"}
                            </small>
                          </td>
                          <td>
                            <span className={i.overdue ? "text-rose-600" : ""}>
                              {salesDate(i.next_follow_up_at)}
                            </span>
                            <small>
                              {i.profile.next_step ||
                                i.profile.stage_label ||
                                "尚未建立商机"}
                            </small>
                          </td>
                          <td>
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() => setLeadId(i.id)}
                            >
                              查看档案
                            </Button>
                          </td>
                        </tr>
                      ))}
                  </tbody>
                </table>
                {loading && <p className="si-empty">正在汇总累计记录…</p>}
                {!loading && !items.length && (
                  <p className="si-empty">
                    没有符合当前条件的商家，可调整筛选。
                  </p>
                )}
              </div>
            )}
            <div className="si-pagination">
              <span>
                第 {page} / {Math.max(1, Math.ceil(total / 30))} 页
              </span>
              <Button
                size="sm"
                variant="outline"
                disabled={page <= 1 || loading}
                onClick={() => setPage((p) => p - 1)}
              >
                上一页
              </Button>
              <Button
                size="sm"
                variant="outline"
                disabled={page * 30 >= total || loading}
                onClick={() => setPage((p) => p + 1)}
              >
                下一页
              </Button>
            </div>
          </section>
        </>
      )}
      {panel === "team" && (
        <SalesTeamPerformance onOpenLead={setLeadId} refreshKey={revision} />
      )}
      {panel === "settings" && manager && (
        <SalesOperatingSettings onPublished={refresh} />
      )}
      <SalesLeadDossier
        leadId={leadId}
        onClose={() => setLeadId(null)}
        onSaved={refresh}
      />
    </section>
  );
}
