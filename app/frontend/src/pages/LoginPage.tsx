import { Navigate, useLocation, useNavigate } from 'react-router-dom';
import Login from './Login';
import { useRole } from '@/lib/role-context';
import { requestBusinessDataRefresh } from '@/lib/data-refresh';
import { getDesktopLoginPath } from '@/lib/app-navigation';
import { getSafeInternalPath } from '@/lib/navigation-state';

type LoginLocationState = {
  from?: {
    pathname?: string;
    search?: string;
    hash?: string;
  };
};

const isMobileViewport = () => typeof window !== 'undefined'
  && window.matchMedia('(max-width: 767px)').matches;

const requestedPathFromState = (state: LoginLocationState | null) => {
  const from = state?.from;
  if (!from?.pathname || from.pathname === '/login') return '';
  return getSafeInternalPath(`${from.pathname}${from.search || ''}${from.hash || ''}`);
};

const resolvePostLoginPath = (role: string | undefined, requestedPath: string) => {
  if (requestedPath) return requestedPath;
  if (isMobileViewport()) return '/apps';
  return getDesktopLoginPath(role);
};

export default function LoginPage() {
  const location = useLocation();
  const navigate = useNavigate();
  const { loading, isLoggedIn, isDisabled, login, role } = useRole();

  const state = location.state as LoginLocationState | null;
  const requestedRedirect = requestedPathFromState(state);
  const redirectTo = resolvePostLoginPath(role, requestedRedirect);

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
      onLoginSuccess={async (token, employee, rememberMe) => {
        await login(token, employee, rememberMe);
        const nextPath = resolvePostLoginPath(employee?.role, requestedRedirect);
        navigate(nextPath, { replace: true });
        window.setTimeout(() => requestBusinessDataRefresh('login'), 300);
      }}
    />
  );
}
