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
import SystemOptions from './pages/SystemOptions';
import Permissions from './pages/Permissions';
import ServiceBoard from './pages/ServiceBoard';
import Callbacks from './pages/Callbacks';
import NotFound from './pages/NotFound';

const queryClient = new QueryClient();

function resolveRouterBasename(): string {
  const rawBase = import.meta.env.BASE_URL || '/';

  // Standard vite base like /t24-crm/
  if (rawBase.startsWith('/')) {
    return rawBase.replace(/\/$/, '') || '/';
  }

  // Relative vite base (./) used for static hosting; infer from current path.
  if (rawBase === './' || rawBase === '.') {
    if (typeof window !== 'undefined') {
      const firstSegment = window.location.pathname.split('/').filter(Boolean)[0];
      return firstSegment ? `/${firstSegment}` : '/';
    }
    return '/';
  }

  return '/';
}

const App = () => (
  <QueryClientProvider client={queryClient}>
    <TooltipProvider>
      <Toaster />
      <RoleProvider>
        <BrowserRouter basename={resolveRouterBasename()}>
          <Routes>
            <Route path="/auth/callback" element={<AuthCallback />} />
            <Route path="/auth/error" element={<AuthError />} />
            <Route path="/" element={<Layout><Dashboard /></Layout>} />
            <Route path="/customers" element={<Layout><Customers /></Layout>} />
            <Route path="/sales" element={<Layout><Sales /></Layout>} />
            <Route path="/deals" element={<Layout><Deals /></Layout>} />
            <Route path="/finance" element={<Layout><Finance /></Layout>} />
            <Route path="/tasks" element={<Layout><Tasks /></Layout>} />
            <Route path="/employees" element={<Layout><Employees /></Layout>} />
            <Route path="/settings" element={<Layout><Settings /></Layout>} />
              <Route path="/system-options" element={<Layout><SystemOptions /></Layout>} />
            <Route path="/permissions" element={<Layout><Permissions /></Layout>} />
            <Route path="/service-board" element={<Layout><ServiceBoard /></Layout>} />
            <Route path="/callbacks" element={<Layout><Callbacks /></Layout>} />
            <Route path="/settings/deduction" element={<MonthlyDeduction />} />
        <Route path="*" element={<NotFound />} />
          </Routes>
        </BrowserRouter>
      </RoleProvider>
    </TooltipProvider>
  </QueryClientProvider>
);

export default App;
