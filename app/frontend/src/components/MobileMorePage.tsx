import { ChevronLeft, ChevronRight, Monitor, Settings2 } from 'lucide-react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { T24AppMark } from '@/components/MobileAppHome';
import { getMobileMoreGroupPath, getMobileMoreGroups } from '@/lib/mobile-more-navigation';
import { roleLabels, useRole } from '@/lib/role-context';
import './mobile-more-page.css';

interface MobileMorePageProps {
  onOpenProfile: () => void;
}

export default function MobileMorePage({ onOpenProfile }: MobileMorePageProps) {
  const location = useLocation();
  const navigate = useNavigate();
  const { employee, role, canAccess } = useRole();
  const groups = getMobileMoreGroups(canAccess);
  const requestedGroup = new URLSearchParams(location.search).get('group');
  const group = groups.find(entry => entry.key === requestedGroup);
  const displayRole = roleLabels[role] || roleLabels[employee?.role] || employee?.role || '管理员模式';

  const returnToRoot = () => {
    if (location.state?.mobileMoreRoot) navigate(-1);
    else navigate('/more', { replace: true });
  };

  return (
    <section className="mobile-more-page" aria-label="更多功能">
      <header className="mobile-more-header">
        {group ? (
          <button type="button" className="mobile-more-back" onClick={returnToRoot} aria-label="返回全部功能">
            <ChevronLeft aria-hidden="true" />
            <span>返回</span>
          </button>
        ) : <span className="mobile-more-brand" aria-hidden="true">T24</span>}
        <h1>{group?.label || '更多'}</h1>
        <Link className="mobile-more-home" to="/apps">返回首页</Link>
      </header>

      <div className="mobile-more-content">
        {group ? (
          group.sections.map(section => (
            <div className="mobile-more-section" key={section.label}>
              <h2 className="mobile-more-section-label">{section.label}</h2>
              <div className="mobile-more-list">
                {section.items.map(item => item.desktopOnly ? (
                  <div className="mobile-more-row mobile-more-feature mobile-more-desktop" key={item.href} aria-label={`${item.label}，请在电脑端管理`}>
                    <span className="mobile-more-row-label">{item.label}</span>
                    <span className="mobile-more-meta"><Monitor aria-hidden="true" />电脑端</span>
                  </div>
                ) : (
                  <Link
                    className="mobile-more-row mobile-more-feature"
                    key={item.href}
                    to={item.href}
                    state={{ mobileMoreReturnTo: getMobileMoreGroupPath(group.key) }}
                    aria-label={`打开${item.label}`}
                  >
                    <span className="mobile-more-row-label">{item.label}</span>
                    <ChevronRight className="mobile-more-chevron" aria-hidden="true" />
                  </Link>
                ))}
              </div>
            </div>
          ))
        ) : (
          <>
            <button type="button" className="mobile-more-profile" onClick={onOpenProfile} aria-label="查看账户与设置">
              <T24AppMark decorative className="mobile-more-avatar" />
              <span className="mobile-more-profile-copy">
                <span className="mobile-more-profile-name">{employee?.name || 'T24 员工'}</span>
                <span className="mobile-more-profile-role">{displayRole}</span>
              </span>
              <ChevronRight className="mobile-more-chevron" aria-hidden="true" />
            </button>

            <div className="mobile-more-section">
              <h2 className="mobile-more-section-label">全部功能</h2>
              <nav className="mobile-more-list" aria-label="全部业务中心">
                {groups.map(entry => {
                  const Icon = entry.icon;
                  return (
                    <Link
                      className="mobile-more-row"
                      key={entry.key}
                      to={getMobileMoreGroupPath(entry.key)}
                      state={{ mobileMoreRoot: true }}
                      aria-label={`${entry.label}，查看全部功能`}
                    >
                      <span className="mobile-more-icon"><Icon aria-hidden="true" /></span>
                      <span className="mobile-more-row-label">{entry.label}</span>
                      <ChevronRight className="mobile-more-chevron" aria-hidden="true" />
                    </Link>
                  );
                })}
                {groups.length === 0 && <p className="mobile-more-empty">暂无可用业务功能</p>}
              </nav>
            </div>

            <div className="mobile-more-list mobile-more-utility">
              <button type="button" className="mobile-more-row" onClick={onOpenProfile}>
                <span className="mobile-more-icon"><Settings2 aria-hidden="true" /></span>
                <span className="mobile-more-row-label">设置与帮助</span>
                <ChevronRight className="mobile-more-chevron" aria-hidden="true" />
              </button>
            </div>
          </>
        )}
      </div>
    </section>
  );
}
