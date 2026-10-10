import { useEffect, useState } from 'react';
import { client } from './api';
import { getAuthSessionEpoch } from './auth-storage';
import { useRole } from './role-context';

/** Visibility only. Every private API request still checks the owner on the server. */
export function usePrivateWorkspaceAccess(): boolean {
  const { employee, role, isLoggedIn, loading } = useRole();
  const identity = `${employee?.id || ''}:${getAuthSessionEpoch()}`;
  const [verified, setVerified] = useState<{ identity: string; allowed: boolean } | null>(null);

  useEffect(() => {
    let cancelled = false;
    setVerified(null);
    if (loading || !isLoggedIn || role !== 'super_admin' || !employee?.id) return;
    client.apiCall.invoke({ url: '/api/v1/private-workspace/access', method: 'GET' })
      .then(response => {
        if (!cancelled) setVerified({ identity, allowed: response?.data?.allowed === true });
      })
      .catch(() => { if (!cancelled) setVerified({ identity, allowed: false }); });
    return () => { cancelled = true; };
  }, [employee?.id, identity, isLoggedIn, loading, role]);

  return !loading && isLoggedIn && role === 'super_admin' && verified?.identity === identity && verified.allowed;
}
