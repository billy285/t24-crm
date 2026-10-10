import { ChevronRight, LockKeyhole } from 'lucide-react';
import { Link, useNavigate } from 'react-router-dom';
import { usePrivateWorkspaceAccess } from '@/lib/private-workspace-access';
import { DropdownMenuItem } from './ui/dropdown-menu';

export default function PrivateWorkspaceEntry({ variant = 'row', onOpen }: { variant?: 'row' | 'menu'; onOpen?: () => void }) {
  const allowed = usePrivateWorkspaceAccess();
  const navigate = useNavigate();
  if (!allowed) return null;
  if (variant === 'menu') return <DropdownMenuItem onSelect={() => { onOpen?.(); navigate('/private-workspace'); }}><LockKeyhole className="mr-2 h-4 w-4" />私人工作空间</DropdownMenuItem>;
  return <div className="mobile-more-section"><div className="mobile-more-list"><Link to="/private-workspace" onClick={onOpen} className="mobile-more-row" aria-label="打开私人工作空间，仅本人可见"><span className="mobile-more-icon"><LockKeyhole aria-hidden="true" /></span><span className="mobile-more-row-label">私人工作空间<small>仅本人可见</small></span><ChevronRight aria-hidden="true" /></Link></div></div>;
}
