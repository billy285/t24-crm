import type { CustomerEffectivePermissions } from './customer-permissions';

export type CustomerReadTicket = { actor: string; session: string; customerId: number; generation: number };

export function customerReadMatches(ticket: CustomerReadTicket, current: CustomerReadTicket) {
  return ticket.actor === current.actor && ticket.session === current.session
    && ticket.customerId === current.customerId && ticket.generation === current.generation;
}

export function customerReadDenied(error: unknown) {
  const problem = error as { status?: number; response?: { status?: number }; data?: { status?: number } };
  return [401, 403].includes(problem?.response?.status || problem?.data?.status || problem?.status || 0);
}

/** A reduced grant must never keep any previous module snapshot on screen. */
export function customerPermissionReduced(before: CustomerEffectivePermissions, after: CustomerEffectivePermissions) {
  const access = { none: 0, read_only: 1, read_write: 2 };
  const finance = { none: 0, status: 1, receipts: 2, profit: 3 };
  return access[after.access_level] < access[before.access_level]
    || finance[after.finance_access] < finance[before.finance_access]
    || Object.keys(before.modules).some(key => {
      const module = key as keyof CustomerEffectivePermissions['modules'];
      return (before.modules[module].read && !after.modules[module].read)
        || (before.modules[module].write && !after.modules[module].write);
    })
    || (['can_delete', 'can_export', 'can_reassign', 'can_manage_access', 'reveal_secrets'] as const)
      .some(key => before[key] && !after[key]);
}

/** Only detects basic-record changes; related records can change independently. */
export function customerBasicFingerprint(customer: Record<string, unknown>) {
  return JSON.stringify(Object.keys(customer).sort().filter(key => key !== 'effective_permissions')
    .map(key => [key, customer[key]]));
}
