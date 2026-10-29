// These loaders contain code only. Never add API requests, account data, or
// permissions to this cache. Public/auth/private routes intentionally stay out.
const crmRouteImporters = {
  '/': () => import('../pages/Dashboard'),
  '/customers': () => import('../pages/Customers'),
  '/sales': () => import('../pages/Sales'),
  '/deals': () => import('../pages/Deals'),
  '/finance': () => import('../pages/Finance'),
  '/finance-entry': () => import('../pages/FinanceEntry'),
  '/rmb-profit': () => import('../pages/RmbProfitEstimate'),
  '/tasks': () => import('../pages/Tasks'),
  '/employees': () => import('../pages/Employees'),
  '/settings': () => import('../pages/Settings'),
  '/permissions': () => import('../pages/Permissions'),
  '/service-board': () => import('../pages/ServiceBoard'),
  '/callbacks': () => import('../pages/Callbacks'),
  '/payroll': () => import('../pages/Payroll'),
  '/sales-leads': () => import('../pages/SalesLeads'),
  '/merchant-pool': () => import('../pages/MerchantPool'),
  '/sales-workbench': () => import('../pages/SalesWorkbench'),
  '/operations-workbench': () => import('../pages/OperationsWorkbench'),
  '/media-ops': () => import('../pages/MediaOperations'),
  '/sales-knowledge': () => import('../pages/SalesKnowledge'),
  '/settings/deduction': () => import('../pages/MonthlyDeduction'),
  '/customer-lifecycle': () => import('../pages/CustomerLifecycle'),
  '/management-decisions': () => import('../pages/ManagementDecisions'),
  '/commissions': () => import('../pages/Commissions'),
  '/partner-portal': () => import('../pages/PartnerPortal'),
  '/company-roadmap': () => import('../pages/CompanyRoadmap'),
} as const;

export type CrmModuleRoute = keyof typeof crmRouteImporters;
type CrmRouteModule<Route extends CrmModuleRoute> = Awaited<ReturnType<(typeof crmRouteImporters)[Route]>>;
const moduleRequests = new Map<CrmModuleRoute, Promise<unknown>>();

export function loadCrmRoute<Route extends CrmModuleRoute>(route: Route): Promise<CrmRouteModule<Route>> {
  const cached = moduleRequests.get(route);
  if (cached) return cached as Promise<CrmRouteModule<Route>>;
  const importer = crmRouteImporters[route] as () => Promise<CrmRouteModule<Route>>;
  const pending = Promise.resolve().then(importer);
  moduleRequests.set(route, pending);
  void pending.catch(() => {
    // A failed speculative load must not poison the later navigation attempt.
    if (moduleRequests.get(route) === pending) moduleRequests.delete(route);
  });
  return pending;
}

export function getPrefetchCrmRoute(href: string, baseHref: string, canAccess: (path: string) => boolean): CrmModuleRoute | null {
  if (!href.trim() || href.trim().startsWith('#')) return null;
  try {
    const base = new URL(baseHref);
    const url = new URL(href, base);
    if (!['http:', 'https:'].includes(url.protocol) || url.origin !== base.origin) return null;
    if (!Object.prototype.hasOwnProperty.call(crmRouteImporters, url.pathname)) return null;
    return canAccess(url.pathname) ? url.pathname as CrmModuleRoute : null;
  } catch {
    return null;
  }
}

export function prefetchCrmRoute(href: string, baseHref: string, canAccess: (path: string) => boolean): Promise<void> {
  const route = getPrefetchCrmRoute(href, baseHref, canAccess);
  if (!route) return Promise.resolve();
  // Prefetching never blocks or reports a navigation failure. The click can retry.
  return loadCrmRoute(route).then(() => undefined, () => undefined);
}
