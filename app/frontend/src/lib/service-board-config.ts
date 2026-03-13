// ==================== 服务进度看板配置 ====================

// 服务类型
export const serviceTypeLabels: Record<string, string> = {
  social_media: '新媒体代运营',
  website: '网站建设',
  ordering_system: '线上点餐系统',
  ads: '广告代投',
  seo: 'SEO优化',
  other: '其他',
};

// 新媒体代运营阶段
export const socialMediaStages: Record<string, string> = {
  deal_handover: '已成交待交接',
  group_created: '已建服务群',
  collecting_materials: '资料收集中',
  account_setup: '账号整理中',
  content_prep: '内容准备中',
  normal_ops: '正常运营中',
  data_optimization: '数据优化中',
  pending_renewal: '待续费',
  paused: '已暂停',
  ended: '已结束',
};

// 网站建设 / 点餐系统阶段
export const websiteStages: Record<string, string> = {
  deal_handover: '已成交待交接',
  collecting_info: '资料收集中',
  menu_input: '菜单录入中',
  page_design: '页面设计中',
  backend_config: '后台配置中',
  testing: '测试中',
  live: '已上线',
  maintenance: '维护中',
  pending_renewal: '待续费',
  ended: '已结束',
};

// 通用阶段（广告代投、SEO、其他）
export const generalStages: Record<string, string> = {
  deal_handover: '已成交待交接',
  collecting_info: '资料收集中',
  account_setup: '账号整理中',
  content_prep: '内容准备中',
  executing: '服务执行中',
  normal_ops: '正常维护中',
  pending_renewal: '待续费',
  paused: '暂停服务',
  ended: '服务结束',
};

// 获取对应服务类型的阶段列表
export function getStagesForType(serviceType: string): Record<string, string> {
  switch (serviceType) {
    case 'social_media': return socialMediaStages;
    case 'website':
    case 'ordering_system': return websiteStages;
    default: return generalStages;
  }
}

// 所有阶段合并（用于看板视图）
export const allStageLabels: Record<string, string> = {
  ...generalStages,
  ...socialMediaStages,
  ...websiteStages,
};

// 阶段对应进度百分比（新媒体代运营）
export const socialMediaStageProgress: Record<string, number> = {
  deal_handover: 10,
  group_created: 15,
  collecting_materials: 20,
  account_setup: 40,
  content_prep: 60,
  normal_ops: 80,
  data_optimization: 90,
  pending_renewal: 100,
  paused: -1,
  ended: -1,
};

// 阶段对应进度百分比（网站/点餐系统）
export const websiteStageProgress: Record<string, number> = {
  deal_handover: 10,
  collecting_info: 20,
  menu_input: 35,
  page_design: 50,
  backend_config: 65,
  testing: 80,
  live: 90,
  maintenance: 100,
  pending_renewal: 100,
  ended: -1,
};

// 阶段对应进度百分比（通用）
export const generalStageProgress: Record<string, number> = {
  deal_handover: 10,
  collecting_info: 20,
  account_setup: 35,
  content_prep: 50,
  executing: 70,
  normal_ops: 100,
  pending_renewal: 100,
  paused: -1,
  ended: -1,
};

// 获取阶段对应的默认进度（-1 表示特殊状态，不自动更新进度）
export function getDefaultProgress(serviceType: string, stage: string): number {
  let map: Record<string, number>;
  switch (serviceType) {
    case 'social_media': map = socialMediaStageProgress; break;
    case 'website':
    case 'ordering_system': map = websiteStageProgress; break;
    default: map = generalStageProgress; break;
  }
  const val = map[stage];
  if (val === undefined) return -1; // stage not found in this type
  return val;
}

// 检查阶段是否属于指定服务类型
export function isStageValidForType(serviceType: string, stage: string): boolean {
  const stages = getStagesForType(serviceType);
  return stage in stages;
}

// 获取服务类型的第一个阶段
export function getFirstStageForType(serviceType: string): string {
  const stages = getStagesForType(serviceType);
  return Object.keys(stages)[0] || 'deal_handover';
}

// 通用阶段进度映射（兼容旧数据）
export const stageProgressMap: Record<string, number> = {
  ...generalStageProgress,
  ...websiteStageProgress,
  ...socialMediaStageProgress,
};

// 看板视图分栏阶段（简化分组）
export const kanbanColumns: { key: string; label: string; stages: string[] }[] = [
  { key: 'not_started', label: '待开始', stages: ['not_started', 'deal_handover'] },
  { key: 'collecting', label: '资料收集', stages: ['group_created', 'collecting_info', 'collecting_materials', 'service_confirmed'] },
  { key: 'building', label: '建设中', stages: ['account_setup', 'account_opened', 'menu_input', 'content_prep', 'page_design', 'backend_config'] },
  { key: 'executing', label: '执行中', stages: ['content_publishing', 'testing', 'executing', 'live', 'data_optimization'] },
  { key: 'active', label: '正常运营', stages: ['normal_ops', 'maintenance', 'renewed'] },
  { key: 'attention', label: '需关注', stages: ['pending_renewal', 'paused', 'ended'] },
];

// 问题状态
export const issueStatusLabels: Record<string, string> = {
  none: '无问题',
  waiting_client: '等待客户回复',
  waiting_material: '等待客户提供资料',
  account_issue: '账号异常',
  permission_issue: '权限异常',
  platform_review: '平台审核中',
  internal_pending: '内部待处理',
  overdue: '已逾期未解决',
};

export const issueStatusColors: Record<string, string> = {
  none: 'bg-green-100 text-green-700',
  waiting_client: 'bg-amber-100 text-amber-700',
  waiting_material: 'bg-orange-100 text-orange-700',
  account_issue: 'bg-red-100 text-red-700',
  permission_issue: 'bg-red-100 text-red-700',
  platform_review: 'bg-blue-100 text-blue-700',
  internal_pending: 'bg-purple-100 text-purple-700',
  overdue: 'bg-red-200 text-red-800',
};

// 任务状态
export const taskStatusLabels: Record<string, string> = {
  pending: '待处理',
  in_progress: '进行中',
  completed: '已完成',
  delayed: '已延期',
  waiting_client: '等待客户提供资料',
  cancelled: '已取消',
};

export const taskStatusColors: Record<string, string> = {
  pending: 'bg-slate-100 text-slate-600',
  in_progress: 'bg-blue-100 text-blue-700',
  completed: 'bg-green-100 text-green-700',
  delayed: 'bg-red-100 text-red-700',
  waiting_client: 'bg-amber-100 text-amber-700',
  cancelled: 'bg-gray-100 text-gray-500',
};

// 任务优先级
export const priorityLabels: Record<string, string> = {
  high: '高',
  medium: '中',
  low: '低',
};

export const priorityColors: Record<string, string> = {
  high: 'bg-red-100 text-red-700',
  medium: 'bg-amber-100 text-amber-700',
  low: 'bg-slate-100 text-slate-600',
};

// 任务类型
export const taskTypeLabels: Record<string, string> = {
  setup_group: '建立服务群',
  collect_info: '收集店铺资料',
  collect_images: '收集图片素材',
  collect_logo: '收集Logo',
  confirm_service: '确认服务内容',
  open_facebook: '开通Facebook',
  open_instagram: '开通Instagram',
  bind_google: '绑定Google Business',
  update_info: '更新商家资料',
  publish_content: '发布内容',
  reply_comments: '评论回复',
  submit_report: '提交周报/月报',
  collect_menu: '收集菜单',
  collect_price: '收集价格',
  input_menu: '录入菜单',
  page_design: '页面设计',
  backend_setup: '后台设置',
  stripe_config: 'Stripe配置',
  test_order: '测试订单',
  go_live: '正式上线',
  other: '其他',
};

// 行业标签（与Customers一致）
export const industryLabels: Record<string, string> = {
  restaurant: '餐厅',
  nail: '美甲',
  massage: '按摩',
  beauty: '美容',
  barber: '理发店',
  spa: 'SPA',
  supermarket: '超市',
  other: '其他',
};

// 国家显示名称映射
export const countryDisplayLabels: Record<string, string> = {
  US: '美国',
  CA: '加拿大',
  GB: '英国',
  AU: '澳大利亚',
};

// 快捷标签定义
export type QuickFilter = 'all' | 'today_pending' | 'overdue' | 'has_issue' | 'waiting_client' | 'expiring_soon' | 'updated_this_week' | 'long_no_update';

export const quickFilterLabels: Record<QuickFilter, string> = {
  all: '全部服务客户',
  today_pending: '今日待处理',
  overdue: '已逾期',
  has_issue: '有问题卡点',
  waiting_client: '等待客户资料',
  expiring_soon: '即将到期',
  updated_this_week: '本周有更新',
  long_no_update: '长期未更新',
};