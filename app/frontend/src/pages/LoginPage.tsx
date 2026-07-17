import { Navigate, useLocation, useNavigate } from 'react-router-dom';
import Login from './Login';
import { useRole } from '@/lib/role-context';

type LoginLocationState = {
  from?: {
    pathname?: string;
  };
};

export default function LoginPage() {
  const location = useLocation();
  const navigate = useNavigate();
  const { loading, isLoggedIn, isDisabled, login, role } = useRole();

  const state = location.state as LoginLocationState | null;
  const requestedRedirect = state?.from?.pathname || '/';
  const redirectTo = role === 'sales' || role === 'sales_manager' ? '/sales-leads' : requestedRedirect;

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-50 flex items-center justify-center">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600" />
      </div>
    );
  }

  if (isDisabled) {
    return <Navigate to="/" replace />;
  }

  if (isLoggedIn) {
    return <Navigate to={redirectTo} replace />;
  }

  return (
    <Login
      onLoginSuccess={async (token, employee) => {
        await login(token, employee);
        const nextPath = employee?.role === 'sales' || employee?.role === 'sales_manager'
          ? '/sales-leads'
          : requestedRedirect;
        navigate(nextPath, { replace: true });
      }}
    />
  );
}
