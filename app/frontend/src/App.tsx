import { lazy, Suspense, type ReactNode } from 'react';
import { Toaster } from '@/components/ui/sonner';
import { TooltipProvider } from '@/components/ui/tooltip';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { RoleProvider } from './lib/role-context';
import Layout from './components/Layout';
import PageLoadState from './components/PageLoadState';

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
      <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-blue-600 text-sm font-bold tracking-wide text-white shadow-lg shadow-blue-200">
        T24
      </div>
      <p className="mt-4 text-sm font-semibold text-slate-800">T24 Marketing 客户管理系统</p>
      <div className="mx-auto mt-4 h-6 w-6 animate-spin rounded-full border-2 border-blue-100 border-b-blue-600" aria-hidden="true" />
      <p className="mt-3 text-xs text-slate-500">正在安全加载页面…</p>
    </div>
  </div>
);

function PublicPage({ children }: { children: ReactNode }) {
  return <Suspense fallback={<PageFallback />}>{children}</Suspense>;
}

function ProtectedPage({ children }: { children: ReactNode }) {
  return (
    <Layout>
      <Suspense fallback={<PageLoadState loading message="正在加载当前页面…" />}>
        {children}
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
  <QueryClientProvider client={queryClient}>
    <TooltipProvider>
      <Toaster />
      <RoleProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/login" element={<PublicPage><LoginPage /></PublicPage>} />
            <Route path="/auth/callback" element={<PublicPage><AuthCallback /></PublicPage>} />
            <Route path="/auth/error" element={<PublicPage><AuthError /></PublicPage>} />
            <Route path="/apps" element={<Layout><div /></Layout>} />
            <Route path="/" element={<ProtectedPage><Dashboard /></ProtectedPage>} />
            <Route path="/company-roadmap" element={<ProtectedPage><CompanyRoadmap /></ProtectedPage>} />
            <Route path="/merchant-pool" element={<ProtectedPage><MerchantPool /></ProtectedPage>} />
            <Route path="/sales-leads" element={<ProtectedPage><SalesLeads /></ProtectedPage>} />
            <Route path="/sales-workbench" element={<ProtectedPage><SalesWorkbench /></ProtectedPage>} />
            <Route path="/operations-workbench" element={<ProtectedPage><OperationsWorkbench /></ProtectedPage>} />
            <Route path="/sales-knowledge" element={<ProtectedPage><SalesKnowledge /></ProtectedPage>} />
            <Route path="/customers" element={<ProtectedPage><Customers /></ProtectedPage>} />
            <Route path="/sales" element={<ProtectedPage><Sales /></ProtectedPage>} />
            <Route path="/deals" element={<ProtectedPage><Deals /></ProtectedPage>} />
            <Route path="/customer-lifecycle" element={<ProtectedPage><CustomerLifecycle /></ProtectedPage>} />
            <Route path="/management-decisions" element={<ProtectedPage><ManagementDecisions /></ProtectedPage>} />
            <Route path="/finance" element={<ProtectedPage><Finance /></ProtectedPage>} />
            <Route path="/rmb-profit" element={<ProtectedPage><RmbProfitEstimate /></ProtectedPage>} />
            <Route path="/commissions" element={<ProtectedPage><Commissions /></ProtectedPage>} />
            <Route path="/partner-portal" element={<ProtectedPage><PartnerPortal /></ProtectedPage>} />
            <Route path="/payroll" element={<ProtectedPage><Payroll /></ProtectedPage>} />
            <Route path="/tasks" element={<ProtectedPage><Tasks /></ProtectedPage>} />
            <Route path="/employees" element={<ProtectedPage><Employees /></ProtectedPage>} />
            <Route path="/settings" element={<ProtectedPage><Settings /></ProtectedPage>} />
            <Route path="/permissions" element={<ProtectedPage><Permissions /></ProtectedPage>} />
            <Route path="/service-board" element={<ProtectedPage><ServiceBoard /></ProtectedPage>} />
            <Route path="/callbacks" element={<ProtectedPage><Callbacks /></ProtectedPage>} />
            <Route path="/settings/deduction" element={<ProtectedPage><MonthlyDeduction /></ProtectedPage>} />
            <Route path="*" element={<PublicPage><NotFound /></PublicPage>} />
          </Routes>
        </BrowserRouter>
      </RoleProvider>
    </TooltipProvider>
  </QueryClientProvider>
);

export default App;
