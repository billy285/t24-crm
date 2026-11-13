/** Display only records already authorized by the caller. Never infer links from names. */
export type CustomerCooperationRecord = Record<string, any>;
export type CustomerCooperationRow = {
  key: string;
  title: string;
  source: 'project' | 'legacy_subscription' | 'legacy_deal';
  statusLabel: string;
  statusKind: 'pending' | 'active' | 'paused' | 'ended' | 'unknown';
  unlinked: boolean;
  projectId?: number;
  ownerId?: number;
  salesOwnerId?: number;
  renewalOwner?: string;
  periodConflict?: boolean;
  startDate?: string;
  endDate?: string;
  subscriptionIds: number[];
  dealIds: number[];
  project?: CustomerCooperationRecord;
  subscription?: CustomerCooperationRecord;
  deal?: CustomerCooperationRecord;
};

function id(value: unknown): number | undefined {
  if (typeof value !== 'number' && typeof value !== 'string') return undefined;
  if (typeof value === 'string' && !/^[1-9]\d*$/.test(value)) return undefined;
  const number = Number(value);
  return Number.isSafeInteger(number) && number > 0 ? number : undefined;
}

function text(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim() ? value.trim() : undefined;
}

const projectStatuses = new Map<string, [string, CustomerCooperationRow['statusKind']]>([
  ['pending_setup', ['待开通', 'pending']], ['trial', ['试用中', 'active']],
  ['active_paid', ['付费服务中', 'active']], ['at_risk', ['服务中 · 需关注', 'active']],
  ['active', ['服务中', 'active']],
  ['reactivated', ['已恢复合作', 'active']], ['paused', ['已暂停', 'paused']],
  ['pending_stop', ['待停止', 'pending']], ['stopped', ['已停止', 'ended']],
  ['completed', ['已完成', 'ended']],
]);
const subscriptionStatuses = new Map<string, [string, CustomerCooperationRow['statusKind']]>([
  ['pending', ['待生效', 'pending']], ['active', ['服务中', 'active']],
  ['trial', ['试用中', 'active']], ['active_paid', ['付费服务中', 'active']],
  ['reactivated', ['已恢复合作', 'active']], ['expiring_soon', ['即将到期', 'active']],
  ['renewal_pending', ['续费待确认', 'pending']], ['paused', ['已暂停', 'paused']],
  ['expired', ['已到期', 'ended']], ['lost', ['已流失', 'ended']],
  ['stopped', ['已停止', 'ended']], ['renewed', ['已续费（历史记录）', 'ended']],
  ['upgraded', ['已升级（历史记录）', 'ended']], ['completed', ['已完成', 'ended']],
]);

function status(value: unknown, mapping: typeof projectStatuses): Pick<CustomerCooperationRow, 'statusLabel' | 'statusKind'> {
  const raw = text(value);
  const match = raw ? mapping.get(raw) : undefined;
  return { statusLabel: match?.[0] || (raw ? `状态待核对：${raw}` : '状态未记录'), statusKind: match?.[1] || 'unknown' };
}

function subscriptionPriority(subscription: CustomerCooperationRecord) {
  const value = subscription.computed_status ?? subscription.status;
  if (['active', 'active_paid', 'trial', 'reactivated', 'expiring_soon'].includes(value)) return 0;
  if (value === 'renewal_pending') return 1;
  if (value === 'pending') return 2;
  if (value === 'paused') return 3;
  if (['expired', 'lost', 'stopped', 'renewed', 'upgraded', 'completed'].includes(value)) return 5;
  return 4;
}

function records(input: unknown, customerId: number, scopedProjects = false): CustomerCooperationRecord[] {
  if (!Array.isArray(input)) return [];
  const seen = new Set<number>();
  return input.filter((item): item is CustomerCooperationRecord => {
    if (!item || typeof item !== 'object' || Array.isArray(item)) return false;
    // /customers/:id/projects omits customer_id: the caller has already verified that scoped response.
    if (!(scopedProjects && !Object.prototype.hasOwnProperty.call(item, 'customer_id')) && id(item.customer_id) !== customerId) return false;
    const recordId = id(item.id);
    if (!recordId || seen.has(recordId)) return false;
    seen.add(recordId);
    return true;
  });
}

export function buildCustomerCooperationRows({ customerId, projects, subscriptions, deals }: {
  customerId: number | string;
  projects?: readonly CustomerCooperationRecord[] | null;
  subscriptions?: readonly CustomerCooperationRecord[] | null;
  deals?: readonly CustomerCooperationRecord[] | null;
}): CustomerCooperationRow[] {
  const customer = id(customerId);
  if (!customer) return [];
  const projectRows = records(projects, customer, true);
  const subscriptionRows = records(subscriptions, customer);
  const dealRows = records(deals, customer);
  const rows = new Map<string, CustomerCooperationRow>();
  const projectById = new Map(projectRows.map(project => [id(project.id)!, project]));
  const dealById = new Map(dealRows.map(deal => [id(deal.id)!, deal]));
  const dealTargets = new Map<number, Set<number>>();
  for (const subscription of subscriptionRows) {
    const projectId = id(subscription.engagement_id), dealId = id(subscription.deal_id);
    if (projectId && projectById.has(projectId) && dealId && dealById.has(dealId)) {
      const targets = dealTargets.get(dealId) || new Set<number>();
      targets.add(projectId); dealTargets.set(dealId, targets);
    }
  }
  for (const project of projectRows) {
    const projectId = id(project.id)!;
    rows.set(`project:${projectId}`, {
      key: `project:${projectId}`, source: 'project', projectId, project,
      title: text(project.package_name) || text(project.product_name) || text(project.product?.name) || text(project.business_line_name) || text(project.business_line?.name) || `合作项目 #${projectId}`,
      ...status(project.status, projectStatuses), unlinked: false,
      ownerId: id(project.owner_employee_id), salesOwnerId: id(project.sales_employee_id),
      startDate: text(project.start_date),
      endDate: text(project.end_date), subscriptionIds: [], dealIds: [],
    });
  }
  const resolvedDealProjects = new Map<number, number>();
  for (const deal of dealRows) {
    const dealId = id(deal.id)!, explicitProject = id(deal.engagement_id);
    if (explicitProject) {
      if (projectById.has(explicitProject)) resolvedDealProjects.set(dealId, explicitProject);
    } else {
      const targets = dealTargets.get(dealId);
      if (targets?.size === 1) resolvedDealProjects.set(dealId, [...targets][0]);
    }
  }
  for (const subscription of subscriptionRows) {
    const subscriptionId = id(subscription.id)!, explicitProject = id(subscription.engagement_id);
    const linkedDeal = dealById.get(id(subscription.deal_id) || 0);
    const dealProject = linkedDeal ? resolvedDealProjects.get(id(linkedDeal.id)!) : undefined;
    // A conflicting or inaccessible explicit project never falls through to another project.
    const projectId = explicitProject ? (projectById.has(explicitProject) ? explicitProject : undefined) : dealProject;
    const compatibleDeal = linkedDeal && (!explicitProject || !id(linkedDeal.engagement_id) || id(linkedDeal.engagement_id) === explicitProject);
    const key = projectId ? `project:${projectId}` : compatibleDeal && !dealProject ? `legacy_deal:${id(linkedDeal.id)}` : `legacy_subscription:${subscriptionId}`;
    let row = rows.get(key);
    if (!row) {
      row = {
        key, source: 'legacy_subscription', title: text(subscription.package_name) || `历史服务 #${subscriptionId}`,
        ...status(subscription.computed_status ?? subscription.status, subscriptionStatuses),
        unlinked: true, subscriptionIds: [], dealIds: [],
      };
      rows.set(key, row);
    }
    row.subscriptionIds.push(subscriptionId);
  }
  for (const deal of dealRows) {
    const dealId = id(deal.id)!, projectId = resolvedDealProjects.get(dealId);
    const key = projectId ? `project:${projectId}` : `legacy_deal:${dealId}`;
    let row = rows.get(key);
    if (!row) {
      row = {
        key, source: 'legacy_deal', title: text(deal.package_name) || text(deal.product_type) || `历史成交 #${dealId}`,
        statusLabel: '合作状态待核对', statusKind: 'unknown', unlinked: true, subscriptionIds: [], dealIds: [],
      };
      rows.set(key, row);
    }
    row.dealIds.push(dealId);
  }
  const subscriptionById = new Map(subscriptionRows.map(subscription => [id(subscription.id)!, subscription]));
  for (const row of rows.values()) {
    const linkedSubscriptions = row.subscriptionIds.map(subscriptionId => subscriptionById.get(subscriptionId)!);
    const priority = Math.min(...linkedSubscriptions.map(subscriptionPriority));
    const currentSubscriptions = linkedSubscriptions.filter(subscription => subscriptionPriority(subscription) === priority);
    const currentSubscription = currentSubscriptions[0];
    const linkedDeals = row.dealIds.map(dealId => dealById.get(dealId)!);
    const currentDeal = linkedDeals.find(deal => id(deal.id) === id(currentSubscription?.deal_id)) || linkedDeals[0];
    row.subscription = currentSubscription;
    row.deal = currentDeal;
    row.salesOwnerId ||= id(currentDeal?.sales_employee_id);
    const periods = new Set(currentSubscriptions.map(subscription => JSON.stringify([text(subscription.start_date), text(subscription.end_date), text(subscription.renewal_person)])));
    row.periodConflict = periods.size > 1;
    if (!row.periodConflict) {
      row.renewalOwner = text(currentSubscription?.renewal_person);
      row.startDate ||= text(currentSubscription?.start_date) || text(currentDeal?.service_start_date);
      row.endDate ||= text(currentSubscription?.end_date) || text(currentDeal?.service_end_date);
    }
    if (row.source === 'legacy_subscription' && currentSubscription) {
      Object.assign(row, status(currentSubscription.computed_status ?? currentSubscription.status, subscriptionStatuses));
      if (new Set(currentSubscriptions.map(subscription => status(subscription.computed_status ?? subscription.status, subscriptionStatuses).statusLabel)).size > 1) {
        row.statusLabel = '服务状态不一致 · 待核对'; row.statusKind = 'unknown';
      }
    }
  }
  return [...rows.values()];
}

/** A shell or contacts-only grant must not reveal the basic-profile contact. */
export function getCustomerPrimaryContact(customer: CustomerCooperationRecord | null | undefined, basicReadable = true): { name: string; phone: string; email: string } | null {
  if (!basicReadable || !customer || typeof customer !== 'object') return null;
  const name = text(customer.contact_name) || '', phone = text(customer.phone) || '';
  if (!name && !phone) return null;
  return { name, phone, email: text(customer.email) || '' };
}
