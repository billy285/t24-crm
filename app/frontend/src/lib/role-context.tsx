import { createContext, useContext, useState, useEffect, useCallback, ReactNode } from 'react';
import { client } from './api';
import {
  type SystemRole, type ButtonPermission, type DataScope,
  getPermissions, canAccessPage, hasButtonPermission,
  getDataScope, canViewSensitive, isAdminRole, mapToSystemRole,
  type RolePermissionConfig,
} from './permissions';
import { getToken, setToken as setAccessToken, clearToken as clearTokenStore, refreshToken, invokeWithAuth } from './tokenStore';

export type RoleType = 'super_admin' | 'admin' | 'sales' | 'ops' | 'design' | 'finance' | '';

interface RoleContextType {
  user: any;
  employee: any;
  role: RoleType;
  systemRole: SystemRole | null;
  loading: boolean;
  isLoggedIn: boolean;
  isAdmin: boolean;
  isDisabled: boolean;
  login: (token: string, emp: any) => void;
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
  login: () => {}, logout: () => {}, refreshEmployee: async () => {},
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
  sales: '销售', ops: '运营', design: '设计', finance: '财务',
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
  super_admin: ['/', '/customers', '/sales', '/deals', '/finance', '/tasks', '/employees', '/settings', '/permissions'],
  admin: ['/', '/customers', '/sales', '/deals', '/finance', '/tasks', '/employees', '/settings', '/permissions'],
  boss: ['/', '/customers', '/sales', '/deals', '/finance', '/tasks', '/employees', '/settings', '/permissions'],
  sales: ['/', '/customers', '/sales', '/deals', '/tasks'],
  ops: ['/', '/customers', '/tasks'],
  design: ['/', '/tasks'],
  finance: ['/', '/finance', '/customers'],
};

const EMP_DATA_KEY = 'emp_auth_data';

export function RoleProvider({ children }: { children: ReactNode }) {
  const [employee, setEmployee] = useState<any>(null);
  const [role, setRole] = useState<RoleType>('');
  const [loading, setLoading] = useState(true);
  const [isDisabled, setIsDisabled] = useState(false);

  useEffect(() => {
    checkAuth();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const checkAuth = async () => {
    try {
      let token = getToken();
      const savedEmp = localStorage.getItem(EMP_DATA_KEY);

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
            localStorage.setItem(EMP_DATA_KEY, JSON.stringify(emp));
            applyEmployee(emp);
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
            applyEmployee(emp);
          } else {
            clearAuth();
          }
        } catch {
          // Try to use saved data as fallback
          try {
            const emp = JSON.parse(savedEmp);
            if (emp && emp.id) {
              applyEmployee(emp);
            } else {
              clearAuth();
            }
          } catch {
            clearAuth();
          }
        }
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
    setRole(mappedRole as RoleType);
  };

  const handleLogin = (token: string, emp: any) => {
    setAccessToken(token);
    localStorage.setItem(EMP_DATA_KEY, JSON.stringify(emp));
    applyEmployee(emp);
  };

  const clearAuth = () => {
    clearTokenStore();
    localStorage.removeItem(EMP_DATA_KEY);
    setEmployee(null);
    setRole('');
    setIsDisabled(false);
  };

  const handleLogout = async () => {
    // Log the logout
    if (employee) {
      try {
        await invokeWithAuth({
          url: '/api/v1/entities/operation_logs',
          method: 'POST',
          data: {
            action_type: 'other',
            action_detail: `员工退出登录: ${employee.name}`,
            operator_name: employee.name,
            ip_address: '',
            created_at: new Date().toISOString(),
          },
        });
      } catch {
        // ignore
      }
    }
    try {
      await client.apiCall.invoke({
        url: '/api/v1/emp-auth/logout',
        method: 'POST',
        options: { withCredentials: true },
      });
    } catch {
      // ignore
    }
    clearAuth();
  };

  const refreshEmployee = async () => {
    try {
      const response = await invokeWithAuth({
        url: '/api/v1/emp-auth/me',
        method: 'GET',
      });
      const emp = response.data;
      if (emp && emp.id) {
        localStorage.setItem(EMP_DATA_KEY, JSON.stringify(emp));
        applyEmployee(emp);
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
  const cvp = role ? canViewSensitive(role, 'viewPassword') : true;
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