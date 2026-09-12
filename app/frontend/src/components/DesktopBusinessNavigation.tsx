import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { LogOut, PanelLeftClose, PanelLeftOpen, Search, User, X } from 'lucide-react';
import {
  type DesktopNavigationSection,
  getDesktopNavigationHref,
  isDesktopNavigationItemActive,
} from '@/lib/app-navigation';

interface DesktopBusinessNavigationProps {
  sections: DesktopNavigationSection[];
  pathname: string;
  search: string;
  homePath: string;
  employeeName?: string;
  roleLabel: string;
  open: boolean;
  collapsed: boolean;
  onClose: () => void;
  onCollapsedChange: (collapsed: boolean) => void;
  onLogout: () => void;
}

function SecondaryNavigation({ section, pathname, search, onNavigate }: {
  section: DesktopNavigationSection;
  pathname: string;
  search: string;
  onNavigate: () => void;
}) {
  const [query, setQuery] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);
  const navRef = useRef<HTMLElement>(null);
  const keyword = query.trim().toLocaleLowerCase();
  const items = section.items.filter(item => `${item.label} ${item.group}`.toLocaleLowerCase().includes(keyword));
  const groups = [...new Set(items.map(item => item.group))];

  useEffect(() => {
    const activeLink = navRef.current?.querySelector<HTMLElement>('[aria-current="page"]');
    if (activeLink?.getClientRects().length) activeLink.scrollIntoView({ block: 'nearest' });
  }, [pathname, search]);

  return (
    <>
      <div className="app-navigation-search">
        <Search aria-hidden="true" className="h-3.5 w-3.5 shrink-0" />
        <input
          ref={inputRef}
          value={query}
          onChange={event => setQuery(event.target.value)}
          onKeyDown={event => {
            if (event.key === 'Escape' && query) {
              event.stopPropagation();
              setQuery('');
            }
          }}
          aria-label={`查找${section.railLabel}功能`}
          placeholder={section.paths.includes('/finance') ? '查找财务功能' : '查找当前中心功能'}
        />
        {query && (
          <button type="button" aria-label="清除功能搜索" onClick={() => { setQuery(''); inputRef.current?.focus(); }}>
            <X aria-hidden="true" className="h-3.5 w-3.5" />
          </button>
        )}
      </div>
      <nav ref={navRef} className="app-sidebar-nav app-secondary-links" aria-label={`${section.label}功能`}>
        {groups.map(group => (
          <div className="app-navigation-group" key={group}>
            <p className="app-navigation-group-label">{group}</p>
            {items.filter(item => item.group === group).map(item => {
              const Icon = item.icon;
              const active = isDesktopNavigationItemActive(item, pathname, search);
              return (
                <Link
                  key={`${item.path}:${item.tab || ''}`}
                  to={getDesktopNavigationHref(item, pathname, search)}
                  onClick={() => { setQuery(''); onNavigate(); }}
                  aria-current={active ? 'page' : undefined}
                  className={`app-secondary-link${active ? ' is-active' : ''}`}
                >
                  <Icon aria-hidden="true" className="h-4 w-4 shrink-0" />
                  <span>{item.label}</span>
                </Link>
              );
            })}
          </div>
        ))}
        {items.length === 0 && (
          <div className="app-navigation-empty" role="status">
            <p>没有匹配的功能</p>
            <button type="button" onClick={() => { setQuery(''); inputRef.current?.focus(); }}>显示全部功能</button>
          </div>
        )}
      </nav>
    </>
  );
}

export default function DesktopBusinessNavigation({
  sections, pathname, search, homePath, employeeName, roleLabel, open, collapsed,
  onClose, onCollapsedChange, onLogout,
}: DesktopBusinessNavigationProps) {
  const activeSection = sections.find(section => section.paths.includes(pathname)) || sections[0];
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    closeRef.current?.focus();
    return () => previousFocus?.focus();
  }, [open]);

  return (
    <aside
      aria-label="业务导航"
      className={`app-sidebar hidden ${open ? 'md:flex' : ''} lg:flex${collapsed ? ' app-sidebar-collapsed' : ''}`}
      onKeyDown={event => {
        if (!open || window.matchMedia('(min-width: 1024px)').matches) return;
        if (event.key === 'Escape') onClose();
        if (event.key !== 'Tab') return;
        const controls = [...event.currentTarget.querySelectorAll<HTMLElement>('a[href], button, input')]
          .filter(element => element.getClientRects().length > 0);
        const first = controls[0];
        const last = controls[controls.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last?.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first?.focus();
        }
      }}
    >
      <div className="app-primary-rail">
        <Link to={homePath} className="app-navigation-brand" onClick={onClose} aria-label="T24 Marketing 今日工作台">
          <img src="/t2-marketing-logo.png?v=t2-20260822-official" alt="" className="h-10 w-10 rounded-xl object-cover" />
          <span>T24 CRM</span>
        </Link>
        <nav className="app-sidebar-nav app-primary-links" aria-label="业务中心">
          {sections.map(section => {
            const Icon = section.icon;
            const active = section.paths.includes(pathname);
            return (
              <Link
                key={section.label}
                to={active ? `${pathname}${search}` : getDesktopNavigationHref(section.items[0])}
                aria-label={section.label}
                aria-current={active ? 'location' : undefined}
                className={`app-primary-link${active ? ' is-active' : ''}`}
                onClick={() => onCollapsedChange(false)}
                title={section.label}
              >
                <Icon aria-hidden="true" className="h-5 w-5" />
                <span>{section.railLabel}</span>
              </Link>
            );
          })}
        </nav>
        <div className="app-primary-footer">
          <button
            type="button"
            className="app-rail-control hidden lg:flex"
            onClick={() => onCollapsedChange(!collapsed)}
            aria-label={collapsed ? '展开功能导航' : '收起功能导航'}
            title={collapsed ? '展开功能导航' : '收起功能导航'}
            aria-expanded={!collapsed}
            aria-controls="desktop-secondary-navigation"
          >
            {collapsed ? <PanelLeftOpen aria-hidden="true" className="h-4 w-4" /> : <PanelLeftClose aria-hidden="true" className="h-4 w-4" />}
            <span>{collapsed ? '展开' : '收起'}</span>
          </button>
          <button type="button" className="app-rail-control" onClick={onLogout} title="退出登录" aria-label="退出登录">
            <LogOut aria-hidden="true" className="h-4 w-4" />
            <span>退出</span>
          </button>
        </div>
      </div>
      <div className="app-secondary-panel" id="desktop-secondary-navigation">
        <div className="app-secondary-heading">
          <div className="min-w-0">
            <p className="app-secondary-eyebrow">业务中心</p>
            <h2>{activeSection?.label || '业务导航'}</h2>
            <p className="app-secondary-description">{activeSection?.description || '选择需要使用的功能'}</p>
          </div>
          <button ref={closeRef} type="button" onClick={onClose} className="app-navigation-close lg:hidden" aria-label="关闭业务导航">
            <X aria-hidden="true" className="h-4 w-4" />
          </button>
        </div>
        {activeSection && (
          <SecondaryNavigation key={activeSection.label} section={activeSection} pathname={pathname} search={search} onNavigate={onClose} />
        )}
        <div className="app-secondary-footer">
          <span className="app-navigation-avatar"><User aria-hidden="true" className="h-4 w-4" /></span>
          <div className="min-w-0">
            <p className="truncate font-medium text-slate-700" title={employeeName}>{employeeName || '当前账户'}</p>
            <p className="mt-0.5 text-[11px] text-slate-400">{roleLabel}</p>
          </div>
        </div>
      </div>
    </aside>
  );
}
