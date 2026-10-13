import { useEffect, useState } from 'react';
import { client } from './api';
import { customerPermissions, type CustomerEffectivePermissions } from './customer-permissions';

export function useCustomerPermissions(customerId: number, supplied?: CustomerEffectivePermissions) {
  const [loaded, setLoaded] = useState<{id:number; permission:CustomerEffectivePermissions} | null>(null);
  useEffect(() => {
    let active = true;
    setLoaded(null);
    if (supplied || !customerId) return;
    client.entities.customers.query({query:{id:customerId},limit:1}).then(response => {
      if(active) setLoaded({id:customerId,permission:customerPermissions(response.data?.items?.[0])});
    }).catch(() => undefined);
    return () => {active=false;};
  },[customerId,supplied]);
  return supplied ? customerPermissions({effective_permissions:supplied}) : loaded?.id === customerId ? loaded.permission : customerPermissions(null);
}
