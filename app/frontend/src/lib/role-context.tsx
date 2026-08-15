import { createContext, useContext, useState, useEffect, useCallback, ReactNode } from 'react';
import { client } from './api';
import {
  type SystemRole, type ButtonPermission, type DataScope,
  getPermissions, canAccessPage, hasButtonPermission,
  getDataScope, canViewSensitive, isAdminRole, mapToSystemRole,
  type RolePermissionConfig,
} from './permissions';
import { APP_CONFIG_UPDATED_EVENT, clearCachedAppConfig, readCachedAppConfig, syncAppConfigCache } from './app-config';
import { getToken, setToken as setAccessToken, clearToken as clearTokenStore, refreshToken, invokeWithAuth } from './tokenStore';
import {
  clearStoredEmployee,
  getAuthPersistence,
  getStoredEmployee,
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
  loading: true, isLoggedIn: false, isAdmin: false, isDisabled: false,
  login: async () => {}, logout: () => {}, refreshEmployee: async () => {},
  canAccess: () => true, hasPermission: () => true,
  dataScope: 'all', canViewPassword: true, canCopyPassword: true, canViewFinance: true,
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

  useEffect(() => {
    checkAuth();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const refreshPermissions = () => setPermissionsVersion((value) => value + 1);
    window.addEventListener(APP_CONFIG_UPDATED_EVENT, refreshPermissions as EventListener);
    return () => window.removeEventListener(APP_CONFIG_UPDATED_EVENT, refreshPermissions as EventListener);
  }, []);

  const checkAuth = async () => {
    try {
      let token = getToken();
      const savedEmp = getStoredEmployee();

      // If no access token, try to refresh from HttpOnly cookie
      if (!token) {
        try {
          const newTok = await refreshToken();
          if (newTok) {
            setAccessToken(newTok);
            token = newTok;
          }
        } catch {
          // ignore
        }
      }

      const effectiveToken = token || getToken();
      if (effectiveToken) {
        setAccessToken(effectiveToken);
      }
      if (!effectiveToken && !savedEmp) {
        setLoading(false);
        return;
      }

      // If we have a token but no cached employee, fetch /me to populate
      if (effectiveToken && !savedEmp) {
        try {
          const respEmp = await invokeWithAuth({ url: '/api/v1/emp-auth/me', method: 'GET' });
          const emp = respEmp.data;
          if (emp && emp.id) {
            storeEmployee(emp, getAuthPersistence());
            applyEmployee(emp);
            await syncAppConfigCache();
          } else {
            clearAuth();
          }
        } catch {
          clearAuth();
        }
        setLoading(false);
        return;
      }

      // Verify token with /me when both exist
      if (effectiveToken && savedEmp) {
        try {
          const response = await invokeWithAuth({
            url: '/api/v1/emp-auth/me',
            method: 'GET',
          });
          const emp = response.data;
          if (emp && emp.id) {
            storeEmployee(emp, getAuthPersistence());
            applyEmployee(emp);
            await syncAppConfigCache();
          } else {
            clearAuth();
          }
        } catch {
          // Cached profile data never proves that an account is still active.
          // Fail closed so disabled/logged-out users cannot reopen an installed app.
          clearAuth();
        }
      } else if (savedEmp) {
        clearAuth();
      }
    } catch {
      clearAuth();
    } finally {
      setLoading(false);
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
    try {
      const persistence = rememberMe ? 'persistent' : 'session';
      setAccessToken(token, persistence);
      storeEmployee(emp, persistence);
      applyEmployee(emp);
      await syncAppConfigCache();
    } catch (err) {
      // Keep the login usable even if non-critical app config sync is temporarily unavailable.
      console.warn('Initial app config sync failed after login:', err);
    } finally {
      setLoading(false);
    }
  };

  const clearAuth = () => {
    clearTokenStore();
    clearStoredEmployee();
    setEmployee(null);
    setRole('');
    setIsDisabled(false);
  };

  const handleLogout = async () => {
    const employeeAtLogout = employee;
    const tokenAtLogout = getToken();

    // Clear browser-readable credentials before any network request. The marker
    // also prevents a stale HttpOnly cookie from silently restoring a session
    // if the device goes offline during logout.
    markExplicitLogout();
    clearAuth();

    const requests: Promise<unknown>[] = [
      client.apiCall.invoke({
        url: '/api/v1/emp-auth/logout',
        method: 'POST',
        options: { withCredentials: true },
      }),
    ];

    if (employeeAtLogout && tokenAtLogout) {
      requests.push(
        client.apiCall.invoke({
          url: '/api/v1/entities/operation_logs',
          method: 'POST',
          data: {
            action_type: 'user_note',
            action_detail: `用户备注（非系统审计）｜关联操作：退出登录｜员工退出登录: ${employeeAtLogout.name}`,
          },
          options: { headers: { Authorization: `Bearer ${tokenAtLogout}` } },
        }),
      );
    }

    await Promise.allSettled(requests);
  };

  const refreshEmployee = async () => {
    try {
      const response = await invokeWithAuth({
        url: '/api/v1/emp-auth/me',
        method: 'GET',
      });
      const emp = response.data;
      if (emp && emp.id) {
        storeEmployee(emp, getAuthPersistence());
        applyEmployee(emp);
        await syncAppConfigCache();
      }
    } catch {
      // ignore
    }
  };

  // Permission helpers
  const sysRole = role ? mapToSystemRole(role) : null;
  const perms = role ? getPermissions(role) : null;

  const canAccess = useCallback((path: string) => {
    if (!role) return true;
    return canAccessPage(role, path);
  }, [role]);

  const hasPermission = useCallback((btn: ButtonPermission) => {
    if (!role) return true;
    return hasButtonPermission(role, btn);
  }, [role]);

  const ds = role ? getDataScope(role) : 'all' as DataScope;
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
  const cvp = !role
    ? true
    : hasExplicitPasswordDecision
      ? configuredSensitiveFields?.viewPassword === true
      : rawRoleConfig?.buttons?.includes('view_password')
        ? true
        : Array.isArray(securityConfig.passwordViewRoles)
          ? securityConfig.passwordViewRoles.includes(sysRole || role)
          : canViewSensitive(role, 'viewPassword');
  const ccp = role ? canViewSensitive(role, 'copyPassword') : true;
  const cvf = role ? canViewSensitive(role, 'viewFinance') : true;

  return (
    <RoleContext.Provider value={{
      user: employee, employee, role, systemRole: sysRole, loading,
      isLoggedIn: !!employee && !isDisabled, isAdmin: !role || isAdminRole(role), isDisabled,
      login: handleLogin, logout: handleLogout, refreshEmployee,
      canAccess, hasPermission,
      dataScope: ds, canViewPassword: cvp, canCopyPassword: ccp, canViewFinance: cvf,
      permissions: perms,
    }}>
      {children}
    </RoleContext.Provider>
  );
}
