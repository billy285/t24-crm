import { ChevronLeft, ChevronRight, Monitor, Search, Settings2, Star } from 'lucide-react';
import { useState } from 'react';
import { toast } from 'sonner';
import { useFavoriteFunctions } from '@/lib/favorite-functions';
import { useAppVersion, checkAppVersion, applyAppUpdate } from '@/lib/app-version';
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
  const [search, setSearch] = useState('');
  const [editingFavorites, setEditingFavorites] = useState(false);
  const { favorites, isFavorite, toggleFavorite } = useFavoriteFunctions(`${employee?.id || 'unknown'}:${role}`, canAccess);
  const version = useAppVersion();
  const searchResults = groups.flatMap(entry => entry.sections.flatMap(section => section.items.map(item => ({ ...item, groupLabel: entry.label, groupKey: entry.key })))).filter(item => `${item.label} ${item.groupLabel}`.toLowerCase().includes(search.trim().toLowerCase()));
  const favoriteButton = (item: { href: string; label: string; desktopOnly?: boolean }) => editingFavorites && !item.desktopOnly ? <button type="button" className="mobile-more-favorite-button" aria-label={`${isFavorite(item.href) ? '移除' : '添加'}常用：${item.label}`} aria-pressed={isFavorite(item.href)} onClick={() => { if (!toggleFavorite(item.href)) toast.info('最多设置6个常用入口，请先移除一个；也请确认设备允许保存偏好'); }}><Star fill={isFavorite(item.href) ? 'currentColor' : 'none'} aria-hidden="true" /></button> : null;
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
        <div className="mobile-more-search"><Search aria-hidden="true" /><input aria-label="搜索全部功能" placeholder="搜索功能" value={search} onChange={event => setSearch(event.target.value)} /></div>
        <div className="mobile-more-favorite-tools"><button type="button" aria-pressed={editingFavorites} onClick={() => setEditingFavorites(value => !value)}>{editingFavorites ? '完成常用设置' : '编辑常用'}</button></div>
        {search.trim() ? (
          <div className="mobile-more-list" aria-label="功能搜索结果">
            {searchResults.map(item => <div className="mobile-more-feature-wrap" key={item.href}>{item.desktopOnly ? <div className="mobile-more-row mobile-more-desktop"><span>{item.label}</span><span className="mobile-more-meta"><Monitor aria-hidden="true" />电脑端</span></div> : <Link className="mobile-more-row" to={item.href} state={{ mobileMoreReturnTo: getMobileMoreGroupPath(item.groupKey) }}><span className="mobile-more-row-label">{item.label}<small>{item.groupLabel}</small></span><ChevronRight aria-hidden="true" /></Link>}{favoriteButton(item)}</div>)}
            {searchResults.length === 0 && <p className="mobile-more-empty">没有找到可用功能</p>}
          </div>
        ) : group ? (
          group.sections.map(section => (
            <div className="mobile-more-section" key={section.label}>
              <h2 className="mobile-more-section-label">{section.label}</h2>
              <div className="mobile-more-list">
                {section.items.map(item => <div className="mobile-more-feature-wrap" key={item.href}>{item.desktopOnly ? (
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
                )}{favoriteButton(item)}</div>)}
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

            {favorites.length > 0 && <div className="mobile-more-section"><h2 className="mobile-more-section-label">常用功能</h2><div className="mobile-more-list">{favorites.map(item => <div className="mobile-more-feature-wrap" key={item.href}><Link className="mobile-more-row" to={item.href}><span className="mobile-more-row-label">{item.label}</span><ChevronRight aria-hidden="true" /></Link>{favoriteButton(item)}</div>)}</div></div>}
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
              <button type="button" className="mobile-more-row" disabled={version.status === 'checking'} onClick={() => {
                if (version.available) { if (!applyAppUpdate()) toast.info('请先保存或取消当前编辑，再更新版本'); }
                else void checkAppVersion();
              }}><span className="mobile-more-row-label">{version.available ? '更新到新版本' : '检查更新'}<small>当前版本 {version.current}</small></span><span className="mobile-more-meta" role="status">{version.status === 'checking' ? '检查中' : version.status === 'current' ? '已是最新' : version.status === 'error' ? '检查失败，重试' : version.available ? '可更新' : ''}</span></button>
            </div>
          </>
        )}
      </div>
    </section>
  );
}
