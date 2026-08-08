import { lazy, Suspense } from 'react';
import { Toaster } from '@/components/ui/sonner';
import { TooltipProvider } from '@/components/ui/tooltip';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { RoleProvider } from './lib/role-context';
import Layout from './components/Layout';

const AuthCallback = lazy(() => import('./pages/AuthCallback'));
const AuthError = lazy(() => import('./pages/AuthError'));
const Dashboard = lazy(() => import('./pages/Dashboard'));
const Customers = lazy(() => import('./pages/Customers'));
const Sales = lazy(() => import('./pages/Sales'));
const Deals = lazy(() => import('./pages/Deals'));
const Finance = lazy(() => import('./pages/Finance'));
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
const SalesKnowledge = lazy(() => import('./pages/SalesKnowledge'));
const MonthlyDeduction = lazy(() => import('./pages/MonthlyDeduction'));
const CustomerLifecycle = lazy(() => import('./pages/CustomerLifecycle'));
const ManagementDecisions = lazy(() => import('./pages/ManagementDecisions'));
const Commissions = lazy(() => import('./pages/Commissions'));
const PartnerPortal = lazy(() => import('./pages/PartnerPortal'));

const PageFallback = () => (
  <div className="flex min-h-[50vh] items-center justify-center">
    <div className="text-center">
      <div className="mx-auto h-8 w-8 animate-spin rounded-full border-b-2 border-blue-600" />
      <p className="mt-3 text-sm text-slate-500">正在加载页面…</p>
    </div>
  </div>
);

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
          <Suspense fallback={<PageFallback />}>
            <Routes>
              <Route path="/login" element={<LoginPage />} />
              <Route path="/auth/callback" element={<AuthCallback />} />
              <Route path="/auth/error" element={<AuthError />} />
              <Route path="/" element={<Layout><Dashboard /></Layout>} />
              <Route path="/merchant-pool" element={<Layout><MerchantPool /></Layout>} />
              <Route path="/sales-leads" element={<Layout><SalesLeads /></Layout>} />
              <Route path="/sales-workbench" element={<Layout><SalesWorkbench /></Layout>} />
              <Route path="/sales-knowledge" element={<Layout><SalesKnowledge /></Layout>} />
              <Route path="/customers" element={<Layout><Customers /></Layout>} />
              <Route path="/sales" element={<Layout><Sales /></Layout>} />
              <Route path="/deals" element={<Layout><Deals /></Layout>} />
              <Route path="/customer-lifecycle" element={<Layout><CustomerLifecycle /></Layout>} />
              <Route path="/management-decisions" element={<Layout><ManagementDecisions /></Layout>} />
              <Route path="/finance" element={<Layout><Finance /></Layout>} />
              <Route path="/commissions" element={<Layout><Commissions /></Layout>} />
              <Route path="/partner-portal" element={<Layout><PartnerPortal /></Layout>} />
              <Route path="/payroll" element={<Layout><Payroll /></Layout>} />
              <Route path="/tasks" element={<Layout><Tasks /></Layout>} />
              <Route path="/employees" element={<Layout><Employees /></Layout>} />
              <Route path="/settings" element={<Layout><Settings /></Layout>} />
              <Route path="/permissions" element={<Layout><Permissions /></Layout>} />
              <Route path="/service-board" element={<Layout><ServiceBoard /></Layout>} />
              <Route path="/callbacks" element={<Layout><Callbacks /></Layout>} />
              <Route path="/settings/deduction" element={<Layout><MonthlyDeduction /></Layout>} />
              <Route path="*" element={<NotFound />} />
            </Routes>
          </Suspense>
        </BrowserRouter>
      </RoleProvider>
    </TooltipProvider>
  </QueryClientProvider>
);

export default App;
