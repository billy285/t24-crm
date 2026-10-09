import { useEffect } from 'react';
import { useBlocker } from 'react-router-dom';
import { confirmDiscardAllChanges, hasUnsavedChanges } from '@/lib/use-unsaved-changes';

export default function UnsavedNavigationGuard() {
  const blocker = useBlocker(({ currentLocation, nextLocation }) => (
    hasUnsavedChanges() && (
      currentLocation.pathname !== nextLocation.pathname
      || currentLocation.search !== nextLocation.search
    )
  ));

  useEffect(() => {
    if (blocker.state !== 'blocked') return;
    if (confirmDiscardAllChanges()) blocker.proceed();
    else blocker.reset();
  }, [blocker]);

  return null;
}
