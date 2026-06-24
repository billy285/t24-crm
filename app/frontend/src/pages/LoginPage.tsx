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
  const { loading, isLoggedIn, isDisabled, login } = useRole();

  const state = location.state as LoginLocationState | null;
  const redirectTo = state?.from?.pathname || '/';

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
      onLoginSuccess={(token, employee) => {
        login(token, employee);
        navigate(redirectTo, { replace: true });
      }}
    />
  );
}
