import MonthlyDeduction from './pages/MonthlyDeduction';
import { Toaster } from '@/components/ui/sonner';
import { TooltipProvider } from '@/components/ui/tooltip';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { RoleProvider } from './lib/role-context';
import AuthCallback from './pages/AuthCallback';
import AuthError from './pages/AuthError';
import Layout from './components/Layout';
import Dashboard from './pages/Dashboard';
import Customers from './pages/Customers';
import Sales from './pages/Sales';
import Deals from './pages/Deals';
import Finance from './pages/Finance';
import Tasks from './pages/Tasks';
import Employees from './pages/Employees';
import Settings from './pages/Settings';
import Permissions from './pages/Permissions';
import ServiceBoard from './pages/ServiceBoard';
import Callbacks from './pages/Callbacks';
import LoginPage from './pages/LoginPage';
import NotFound from './pages/NotFound';
import Payroll from './pages/Payroll';
import SalesLeads from './pages/SalesLeads';
import MerchantPool from './pages/MerchantPool';
import SalesWorkbench from './pages/SalesWorkbench';
import SalesKnowledge from './pages/SalesKnowledge';

const queryClient = new QueryClient();

const App = () => (
  <QueryClientProvider client={queryClient}>
    <TooltipProvider>
      <Toaster />
      <RoleProvider>
        <BrowserRouter>
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
            <Route path="/finance" element={<Layout><Finance /></Layout>} />
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
        </BrowserRouter>
      </RoleProvider>
    </TooltipProvider>
  </QueryClientProvider>
);

export default App;
