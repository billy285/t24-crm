import { lazy, Suspense, type ReactNode } from 'react';
import { Toaster } from '@/components/ui/sonner';
import { TooltipProvider } from '@/components/ui/tooltip';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter, Outlet, Routes, Route } from 'react-router-dom';
import { RoleProvider } from './lib/role-context';
import Layout from './components/Layout';
import PageLoadState from './components/PageLoadState';
import AppErrorBoundary from './components/AppErrorBoundary';

const AuthCallback = lazy(() => import('./pages/AuthCallback'));
const AuthError = lazy(() => import('./pages/AuthError'));
const Dashboard = lazy(() => import('./pages/Dashboard'));
const Customers = lazy(() => import('./pages/Customers'));
const Sales = lazy(() => import('./pages/Sales'));
const Deals = lazy(() => import('./pages/Deals'));
const Finance = lazy(() => import('./pages/Finance'));
const RmbProfitEstimate = lazy(() => import('./pages/RmbProfitEstimate'));
const Tasks = lazy(() => import('./pages/Tasks'));
const Employees = lazy(() => import('./pages/Employees'));
const Settings = lazy(() => import('./pages/Settings'));
const Permissions = lazy(() => import('./pages/Permissions'));
const ServiceBoard = lazy(() => import('./pages/ServiceBoard'));
const Callbacks = lazy(() => import('./pages/Callbacks'));
const LoginPage = lazy(() => import('./pages/LoginPage'));
const NotFound = lazy(() => import('./pages/NotFound'));
const Payroll = lazy(() => import('./pages/Payroll'));
const SalesLeads = lazy(() => import('./pages/SalesLeads'));
const MerchantPool = lazy(() => import('./pages/MerchantPool'));
const SalesWorkbench = lazy(() => import('./pages/SalesWorkbench'));
const OperationsWorkbench = lazy(() => import('./pages/OperationsWorkbench'));
const SalesKnowledge = lazy(() => import('./pages/SalesKnowledge'));
const MonthlyDeduction = lazy(() => import('./pages/MonthlyDeduction'));
const CustomerLifecycle = lazy(() => import('./pages/CustomerLifecycle'));
const ManagementDecisions = lazy(() => import('./pages/ManagementDecisions'));
const Commissions = lazy(() => import('./pages/Commissions'));
const PartnerPortal = lazy(() => import('./pages/PartnerPortal'));
const CompanyRoadmap = lazy(() => import('./pages/CompanyRoadmap'));

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

function ProtectedAppShell() {
  return (
    <Layout>
      <Suspense fallback={<PageLoadState loading message="正在加载当前页面…" />}>
        <Outlet />
      </Suspense>
    </Layout>
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

const App = () => (
  <AppErrorBoundary>
  <QueryClientProvider client={queryClient}>
    <TooltipProvider>
      <Toaster />
      <RoleProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/login" element={<PublicPage><LoginPage /></PublicPage>} />
            <Route path="/auth/callback" element={<PublicPage><AuthCallback /></PublicPage>} />
            <Route path="/auth/error" element={<PublicPage><AuthError /></PublicPage>} />
            <Route element={<ProtectedAppShell />}>
              <Route path="/apps" element={<div />} />
              <Route path="/" element={<Dashboard />} />
              <Route path="/company-roadmap" element={<CompanyRoadmap />} />
              <Route path="/merchant-pool" element={<MerchantPool />} />
              <Route path="/sales-leads" element={<SalesLeads />} />
              <Route path="/sales-workbench" element={<SalesWorkbench />} />
              <Route path="/operations-workbench" element={<OperationsWorkbench />} />
              <Route path="/sales-knowledge" element={<SalesKnowledge />} />
              <Route path="/customers" element={<Customers />} />
              <Route path="/sales" element={<Sales />} />
              <Route path="/deals" element={<Deals />} />
              <Route path="/customer-lifecycle" element={<CustomerLifecycle />} />
              <Route path="/management-decisions" element={<ManagementDecisions />} />
              <Route path="/finance" element={<Finance />} />
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
          </Routes>
        </BrowserRouter>
      </RoleProvider>
    </TooltipProvider>
  </QueryClientProvider>
  </AppErrorBoundary>
);

export default App;
