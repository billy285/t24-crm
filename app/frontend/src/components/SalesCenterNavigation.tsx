import { Link, useLocation } from 'react-router-dom';
import { useRole } from '@/lib/role-context';
import './sales-navigation.css';

export const salesWorkspacePaths = ['/sales-workbench', '/merchant-pool', '/sales-leads', '/sales-knowledge'];

const pages = [
  { path: '/sales-workbench', label: '今日拨打' },
  { path: '/merchant-pool', label: '商家池' },
  { path: '/sales-leads', label: '联系进展' },
  { path: '/sales-knowledge', label: '知识库' },
];

export default function SalesCenterNavigation({ className = '' }: { className?: string }) {
  const { pathname } = useLocation();
  const { canAccess } = useRole();
  return <nav className={`sales-center-navigation ${className}`} aria-label="销售中心导航">
    <span className="sales-center-navigation-title">销售中心</span>
    {pages.filter(page => canAccess(page.path)).map(page => <Link key={page.path} to={page.path} aria-current={pathname === page.path ? 'page' : undefined}>{page.label}</Link>)}
  </nav>;
}
