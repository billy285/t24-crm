import { lazy, Suspense, type ReactNode } from 'react';
import { Toaster } from '@/components/ui/sonner';
import { TooltipProvider } from '@/components/ui/tooltip';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { createBrowserRouter, createRoutesFromElements, RouterProvider, Outlet, Route, useRouteError } from 'react-router-dom';
import { RoleProvider } from './lib/role-context';
import Layout from './components/Layout';
import PageLoadState from './components/PageLoadState';
import AppErrorBoundary from './components/AppErrorBoundary';
import UnsavedNavigationGuard from './components/UnsavedNavigationGuard';
import AppVersionNotice from './components/AppVersionNotice';
import { loadCrmRoute } from './components/crm-route-modules';

const AuthCallback = lazy(() => import('./pages/AuthCallback'));
const AuthError = lazy(() => import('./pages/AuthError'));
const Dashboard = lazy(() => loadCrmRoute('/'));
const Customers = lazy(() => loadCrmRoute('/customers'));
const Sales = lazy(() => loadCrmRoute('/sales'));
const Deals = lazy(() => loadCrmRoute('/deals'));
const Finance = lazy(() => loadCrmRoute('/finance'));
const FinanceEntry = lazy(() => loadCrmRoute('/finance-entry'));
const RmbProfitEstimate = lazy(() => loadCrmRoute('/rmb-profit'));
const Tasks = lazy(() => loadCrmRoute('/tasks'));
const Employees = lazy(() => loadCrmRoute('/employees'));
const Settings = lazy(() => loadCrmRoute('/settings'));
const Permissions = lazy(() => loadCrmRoute('/permissions'));
const ServiceBoard = lazy(() => loadCrmRoute('/service-board'));
const Callbacks = lazy(() => loadCrmRoute('/callbacks'));
const LoginPage = lazy(() => import('./pages/LoginPage'));
const NotFound = lazy(() => import('./pages/NotFound'));
const Payroll = lazy(() => loadCrmRoute('/payroll'));
const SalesLeads = lazy(() => loadCrmRoute('/sales-leads'));
const MerchantPool = lazy(() => loadCrmRoute('/merchant-pool'));
const SalesWorkbench = lazy(() => loadCrmRoute('/sales-workbench'));
const OperationsWorkbench = lazy(() => loadCrmRoute('/operations-workbench'));
const MediaOperations = lazy(() => loadCrmRoute('/media-ops'));
const SalesKnowledge = lazy(() => loadCrmRoute('/sales-knowledge'));
const MonthlyDeduction = lazy(() => loadCrmRoute('/settings/deduction'));
const CustomerLifecycle = lazy(() => loadCrmRoute('/customer-lifecycle'));
const ManagementDecisions = lazy(() => loadCrmRoute('/management-decisions'));
const Commissions = lazy(() => loadCrmRoute('/commissions'));
const PartnerPortal = lazy(() => loadCrmRoute('/partner-portal'));
const CompanyRoadmap = lazy(() => loadCrmRoute('/company-roadmap'));
const PrivateWorkspace = lazy(() => import('./pages/PrivateWorkspace'));

const PageFallback = () => (
  <div className="flex min-h-screen items-center justify-center bg-slate-50 px-6" role="status" aria-live="polite">
    <div className="text-center">
      <img src="/t2-marketing-logo.png?v=t2-20260822-official" alt="T2 Marketing" className="mx-auto h-14 w-14 rounded-2xl border border-slate-200 bg-white object-cover shadow-lg shadow-slate-200" />
      <p className="mt-4 text-sm font-semibold text-slate-800">T24 Marketing 客户管理系统</p>
      <div className="mx-auto mt-4 h-6 w-6 animate-spin rounded-full border-2 border-blue-100 border-b-blue-600" aria-hidden="true" />
      <p className="mt-3 text-xs text-slate-500">正在安全加载页面…</p>
    </div>
  </div>
);

function PublicPage({ children }: { children: ReactNode }) {
  return <Suspense fallback={<PageFallback />}>{children}</Suspense>;
}

function RouteFailure(): never {
  throw useRouteError();
}

function ProtectedAppShell() {
  return (
    <>
      <UnsavedNavigationGuard />
      <AppVersionNotice />
    <Layout>
      <Suspense fallback={<PageLoadState loading message="正在加载当前页面…" />}>
        <Outlet />
      </Suspense>
    </Layout>
    </>
  );
}

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 0,
      refetchOnMount: 'always',
      refetchOnWindowFocus: true,
      refetchOnReconnect: true,
      retry: 2,
    },
  },
});

const router = createBrowserRouter(createRoutesFromElements(
          <>
            <Route path="/login" element={<PublicPage><LoginPage /></PublicPage>} />
            <Route path="/auth/callback" element={<PublicPage><AuthCallback /></PublicPage>} />
            <Route path="/auth/error" element={<PublicPage><AuthError /></PublicPage>} />
            <Route element={<ProtectedAppShell />} errorElement={<AppErrorBoundary><RouteFailure /></AppErrorBoundary>}>
              <Route path="/apps" element={<div />} />
              <Route path="/more" element={<div />} />
              <Route path="/private-workspace" element={<PrivateWorkspace />} />
              <Route path="/" element={<Dashboard />} />
              <Route path="/company-roadmap" element={<CompanyRoadmap />} />
              <Route path="/merchant-pool" element={<MerchantPool />} />
              <Route path="/sales-leads" element={<SalesLeads />} />
              <Route path="/sales-workbench" element={<SalesWorkbench />} />
              <Route path="/operations-workbench" element={<OperationsWorkbench />} />
              <Route path="/media-ops" element={<MediaOperations />} />
              <Route path="/sales-knowledge" element={<SalesKnowledge />} />
              <Route path="/customers" element={<Customers />} />
              <Route path="/sales" element={<Sales />} />
              <Route path="/deals" element={<Deals />} />
              <Route path="/customer-lifecycle" element={<CustomerLifecycle />} />
              <Route path="/management-decisions" element={<ManagementDecisions />} />
              <Route path="/finance" element={<Finance />} />
              <Route path="/finance-entry" element={<FinanceEntry />} />
              <Route path="/rmb-profit" element={<RmbProfitEstimate />} />
              <Route path="/commissions" element={<Commissions />} />
              <Route path="/partner-portal" element={<PartnerPortal />} />
              <Route path="/payroll" element={<Payroll />} />
              <Route path="/tasks" element={<Tasks />} />
              <Route path="/employees" element={<Employees />} />
              <Route path="/settings" element={<Settings />} />
              <Route path="/permissions" element={<Permissions />} />
              <Route path="/service-board" element={<ServiceBoard />} />
              <Route path="/callbacks" element={<Callbacks />} />
              <Route path="/settings/deduction" element={<MonthlyDeduction />} />
            </Route>
            <Route path="*" element={<PublicPage><NotFound /></PublicPage>} />
          </>
));

const App = () => (
  <AppErrorBoundary>
  <QueryClientProvider client={queryClient}>
    <TooltipProvider>
      <Toaster />
      <RoleProvider>
          <RouterProvider router={router} />
      </RoleProvider>
    </TooltipProvider>
  </QueryClientProvider>
  </AppErrorBoundary>
);

export default App;
