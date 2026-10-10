import { createContext, useContext, useState, useEffect, useCallback, ReactNode } from 'react';
import { client, authSessionChangedError, isAuthSessionCurrent, isRefreshTemporarilyUnavailable } from './api';
import {
  type SystemRole, type ButtonPermission, type DataScope,
  getPermissions, canAccessPage, hasButtonPermission,
  getDataScope, canViewSensitive, isAdminRole, mapToSystemRole,
  type RolePermissionConfig,
} from './permissions';
import { APP_CONFIG_UPDATED_EVENT, clearCachedAppConfig, readCachedAppConfig, syncAppConfigCache } from './app-config';
import { clearSalesWorkspaceViewState } from './sales-workspace-view-state';
import { getToken, setToken as setAccessToken, clearToken as clearTokenStore, refreshToken, invokeWithAuth } from './tokenStore';
import {
  AUTH_SESSION_EPOCH_KEY,
  AUTH_SESSION_INVALIDATED_EVENT,
  clearStoredEmployee,
  getAuthSessionEpoch,
  getAuthPersistence,
  markExplicitLogout,
  storeEmployee,
} from './auth-storage';

export type RoleType = 'super_admin' | 'admin' | 'sales' | 'sales_manager' | 'sales_partner' | 'ops' | 'design' | 'finance' | '';

interface RoleContextType {
  user: any;
  employee: any;
  role: RoleType;
  systemRole: SystemRole | null;
  loading: boolean;
  authError: string;
  retryAuth: () => Promise<void>;
  isLoggedIn: boolean;
  isAdmin: boolean;
  isDisabled: boolean;
  login: (token: string, emp: any, rememberMe?: boolean) => Promise<void>;
  logout: () => void;
  refreshEmployee: () => Promise<void>;
  // Permission helpers
  canAccess: (path: string) => boolean;
  hasPermission: (btn: ButtonPermission) => boolean;
  dataScope: DataScope;
  canViewPassword: boolean;
  canCopyPassword: boolean;
  canViewFinance: boolean;
  permissions: RolePermissionConfig | null;
}

const RoleContext = createContext<RoleContextType>({
  user: null, employee: null, role: '', systemRole: null,
  loading: true, authError: '', retryAuth: async () => {}, isLoggedIn: false, isAdmin: false, isDisabled: false,
  login: async () => {}, logout: () => {}, refreshEmployee: async () => {},
  canAccess: () => false, hasPermission: () => false,
  dataScope: 'self', canViewPassword: false, canCopyPassword: false, canViewFinance: false,
  permissions: null,
});

export function useRole() {
  return useContext(RoleContext);
}

// Re-export labels for backward compatibility
export const roleLabels: Record<string, string> = {
  super_admin: '超级管理员', admin: '管理员',
  sales: '销售', sales_manager: '销售主管', ops: '运营', design: '设计', finance: '财务',
  sales_partner: '销售合伙人',
  boss: '老板', // Legacy
};

export const empStatusLabels: Record<string, string> = {
  active: '在职', probation: '试用期', disabled: '停用', resigned: '离职',
};

export const empStatusColors: Record<string, string> = {
  active: 'bg-green-100 text-green-700',
  probation: 'bg-blue-100 text-blue-700',
  disabled: 'bg-slate-100 text-slate-600',
  resigned: 'bg-red-100 text-red-700',
};

export const departmentLabels: Record<string, string> = {
  sales: '销售部', operations: '运营部', design: '设计部', finance: '财务部', management: '管理层',
};

export const positionLabels: Record<string, string> = {
  manager: '经理', senior: '高级专员', specialist: '专员', intern: '实习生', director: '总监',
};

// Legacy nav access (kept for backward compat)
export const roleNavAccess: Record<string, string[]> = {
  super_admin: ['/', '/company-roadmap', '/customers', '/sales', '/deals', '/finance', '/partner-portal', '/tasks', '/employees', '/settings', '/settings/deduction', '/permissions'],
  admin: ['/', '/company-roadmap', '/customers', '/sales', '/deals', '/finance', '/tasks', '/employees', '/settings', '/settings/deduction', '/permissions'],
  boss: ['/', '/company-roadmap', '/customers', '/sales', '/deals', '/finance', '/partner-portal', '/tasks', '/employees', '/settings', '/settings/deduction', '/permissions'],
  sales: ['/sales-leads', '/sales-workbench', '/sales-knowledge', '/customers'],
  sales_manager: ['/merchant-pool', '/sales-leads', '/sales-workbench', '/sales-knowledge', '/customers'],
  sales_partner: ['/partner-portal'],
  ops: ['/operations-workbench', '/customers', '/tasks', '/service-board', '/callbacks'],
  design: ['/', '/tasks'],
  finance: ['/', '/company-roadmap', '/finance', '/customers', '/settings/deduction'],
};

export function RoleProvider({ children }: { children: ReactNode }) {
  const [employee, setEmployee] = useState<any>(null);
  const [role, setRole] = useState<RoleType>('');
  const [loading, setLoading] = useState(true);
  const [isDisabled, setIsDisabled] = useState(false);
  const [, setPermissionsVersion] = useState(0);
  const [authError, setAuthError] = useState('');

  useEffect(() => {
    checkAuth();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const refreshPermissions = () => setPermissionsVersion((value) => value + 1);
    window.addEventListener(APP_CONFIG_UPDATED_EVENT, refreshPermissions as EventListener);
    return () => window.removeEventListener(APP_CONFIG_UPDATED_EVENT, refreshPermissions as EventListener);
  }, []);

  useEffect(() => {
    const resetIdentity = () => {
      clearStoredEmployee();
      clearCachedAppConfig();
      clearSalesWorkspaceViewState();
      setEmployee(null);
      setRole('');
      setIsDisabled(false);
      setAuthError('');
      setLoading(false);
    };
    const handleOtherTab = (event: StorageEvent) => {
      if (event.key === AUTH_SESSION_EPOCH_KEY) {
        // A different tab changed identity. Its new credentials must never be
        // combined with this tab's employee profile or mounted sales workspace.
        clearSalesWorkspaceViewState();
        setEmployee(null);
        setRole('');
        setIsDisabled(false);
        setAuthError('');
        setLoading(false);
      }
    };
    window.addEventListener(AUTH_SESSION_INVALIDATED_EVENT, resetIdentity);
    window.addEventListener('storage', handleOtherTab);
    return () => {
      window.removeEventListener(AUTH_SESSION_INVALIDATED_EVENT, resetIdentity);
      window.removeEventListener('storage', handleOtherTab);
    };
  }, []);

  const syncVerifiedConfig = async (epoch: string) => {
    try {
      await syncAppConfigCache();
    } catch {
      // Configuration is not proof of identity. A temporary outage keeps the
      // verified employee, with checked-in role defaults and no stale cache.
      if (isAuthSessionCurrent(epoch)) clearCachedAppConfig();
    }
  };

  const checkAuth = async () => {
    const epoch = getAuthSessionEpoch();
    setLoading(true);
    setAuthError('');
    setEmployee(null);
    setRole('');
    setIsDisabled(false);
    clearCachedAppConfig();
    try {
      let token = getToken();
      if (!token) token = await refreshToken() || '';
      if (!isAuthSessionCurrent(epoch)) return;
      if (!token) {
        if (isRefreshTemporarilyUnavailable(epoch)) {
          const unavailable = new Error('身份验证服务暂不可用') as Error & { status: number };
          unavailable.status = 503;
          throw unavailable;
        }
        clearAuth();
        return;
      }
      let response;
      // Retry only this read-only verification once for a transient outage.
      // Cached employee data still cannot unlock any page or permission.
      for (let attempt = 0; attempt < 2; attempt++) {
        try {
          response = await invokeWithAuth({ url: '/api/v1/emp-auth/me', method: 'GET' });
          break;
        } catch (error: any) {
          const status = error?.response?.status || error?.data?.status || error?.status || 0;
          if (attempt === 0 && (status === 0 || status >= 500) && isAuthSessionCurrent(epoch)) {
            await new Promise(resolve => setTimeout(resolve, 300));
            continue;
          }
          throw error;
        }
      }
      if (!isAuthSessionCurrent(epoch)) return;
      const emp = response?.data;
      if (!emp?.id) {
        clearAuth();
        return;
      }
      storeEmployee(emp, getAuthPersistence());
      applyEmployee(emp);
      await syncVerifiedConfig(epoch);
    } catch (error: any) {
      if (!isAuthSessionCurrent(epoch)) return;
      const status = error?.response?.status || error?.data?.status || error?.status || 0;
      if (status === 401 || status === 403) {
        clearAuth();
      } else {
        // Preserve credentials during network/server outages, but keep the
        // unverified identity closed until a live verification succeeds.
        setEmployee(null);
        setRole('');
        setIsDisabled(false);
        setAuthError('暂时无法验证登录，请检查网络后重新尝试。');
      }
    } finally {
      if (epoch === getAuthSessionEpoch()) setLoading(false);
    }
  };

  const applyEmployee = (emp: any) => {
    if (emp.status === 'disabled' || emp.status === 'resigned') {
      setIsDisabled(true);
      setEmployee(emp);
      setRole((emp.role || '') as RoleType);
      return;
    }
    setEmployee(emp);
    setIsDisabled(false);
    const mappedRole = mapToSystemRole(emp.role || 'sales');
    if (mappedRole === 'sales_partner') clearCachedAppConfig();
    setRole(mappedRole as RoleType);
  };

  const handleLogin = async (token: string, emp: any, rememberMe = false) => {
    setLoading(true);
    setAuthError('');
    // Clear previous identity-specific convenience and permission caches before
    // exposing a newly verified login, even when optional config is unavailable.
    clearCachedAppConfig();
    clearSalesWorkspaceViewState();
    const persistence = rememberMe ? 'persistent' : 'session';
    setAccessToken(token, persistence);
    const epoch = getAuthSessionEpoch();
    storeEmployee(emp, persistence);
    applyEmployee(emp);
    try {
      await syncVerifiedConfig(epoch);
      if (!isAuthSessionCurrent(epoch)) throw authSessionChangedError();
    } finally {
      if (epoch === getAuthSessionEpoch()) setLoading(false);
    }
  };

  const clearAuth = () => {
    clearTokenStore();
    clearStoredEmployee();
    clearCachedAppConfig();
    clearSalesWorkspaceViewState();
    setEmployee(null);
    setRole('');
    setIsDisabled(false);
    setAuthError('');
    setLoading(false);
  };

  const handleLogout = async () => {
    const tokenAtLogout = getToken();

    // Clear browser-readable credentials before any network request. The marker
    // also prevents a stale HttpOnly cookie from silently restoring a session
    // if the device goes offline during logout.
    markExplicitLogout();
    clearSalesWorkspaceViewState();
    clearAuth();

    // Revoke the bearer session too when the optional refresh cookie was never
    // established; a browser-authored note is not a server audit record.
    await client.apiCall.invoke({
      url: '/api/v1/emp-auth/logout', method: 'POST',
      options: {
        withCredentials: true,
        headers: tokenAtLogout ? { Authorization: `Bearer ${tokenAtLogout}` } : {},
      },
    }).catch(() => undefined);
  };

  const refreshEmployee = async () => {
    const epoch = getAuthSessionEpoch();
    try {
      const response = await invokeWithAuth({ url: '/api/v1/emp-auth/me', method: 'GET' });
      if (!isAuthSessionCurrent(epoch)) return;
      const emp = response.data;
      if (!emp?.id) {
        clearAuth();
        return;
      }
      storeEmployee(emp, getAuthPersistence());
      applyEmployee(emp);
      await syncVerifiedConfig(epoch);
    } catch (error: any) {
      // A business 403 elsewhere is not logout. Rejection from the authoritative
      // identity endpoint itself cannot keep an old role active.
      const status = error?.response?.status || error?.data?.status || error?.status;
      if ((status === 401 || status === 403) && isAuthSessionCurrent(epoch)) clearAuth();
    }
  };

  // Permission helpers
  const sysRole = role ? mapToSystemRole(role) : null;
  const perms = role ? getPermissions(role) : null;

  const canAccess = useCallback((path: string) => {
    if (!role || isDisabled) return false;
    return canAccessPage(role, path);
  }, [role, isDisabled]);

  const hasPermission = useCallback((btn: ButtonPermission) => {
    if (!role || isDisabled) return false;
    return hasButtonPermission(role, btn);
  }, [role, isDisabled]);

  const ds = role ? getDataScope(role) : 'self' as DataScope;
  const rawRolePermissions = readCachedAppConfig<Record<string, {
    buttons?: string[];
    sensitiveFields?: { viewPassword?: boolean };
  }>>('role_permissions', {});
  const rawRoleConfig = sysRole ? rawRolePermissions[sysRole] : undefined;
  const configuredSensitiveFields = rawRoleConfig?.sensitiveFields;
  const hasExplicitPasswordDecision = Boolean(
    configuredSensitiveFields
    && Object.prototype.hasOwnProperty.call(configuredSensitiveFields, 'viewPassword'),
  );
  const securityConfig = readCachedAppConfig<{ passwordViewRoles?: string[] }>('security_config', {});
  // Keep this precedence identical to the backend reveal endpoint: the modern
  // sensitive field is authoritative (including false), followed only by the
  // legacy button/security settings and finally checked-in role defaults.
  const cvp = !role || isDisabled
    ? false
    : hasExplicitPasswordDecision
      ? configuredSensitiveFields?.viewPassword === true
      : rawRoleConfig?.buttons?.includes('view_password')
        ? true
        : Array.isArray(securityConfig.passwordViewRoles)
          ? securityConfig.passwordViewRoles.includes(sysRole || role)
          : canViewSensitive(role, 'viewPassword');
  const ccp = role && !isDisabled ? canViewSensitive(role, 'copyPassword') : false;
  const cvf = role && !isDisabled ? canViewSensitive(role, 'viewFinance') : false;

  return (
    <RoleContext.Provider value={{
      user: employee, employee, role, systemRole: sysRole, loading, authError, retryAuth: checkAuth,
      isLoggedIn: !!employee && !isDisabled, isAdmin: !!role && !isDisabled && isAdminRole(role), isDisabled,
      login: handleLogin, logout: handleLogout, refreshEmployee,
      canAccess, hasPermission,
      dataScope: ds, canViewPassword: cvp, canCopyPassword: ccp, canViewFinance: cvf,
      permissions: perms,
    }}>
      {children}
    </RoleContext.Provider>
  );
}
