import { useEffect, useState } from 'react';
import { getMobileMoreGroups, type MobileMoreItem } from './mobile-more-navigation';

export function useFavoriteFunctions(identity: string, canAccess: (path: string) => boolean) {
  const key = 't24:favorite-functions:v1:' + identity;
  const allowed = getMobileMoreGroups(canAccess).flatMap(group => group.sections.flatMap(section => section.items)).filter(item => !item.desktopOnly);
  const byHref = new Map(allowed.map(item => [item.href, item]));
  const read = () => {
    try {
      const value = JSON.parse(localStorage.getItem(key) || '[]');
      return Array.isArray(value) ? [...new Set(value.filter(href => typeof href === 'string' && byHref.has(href)))].slice(0, 6) as string[] : [];
    } catch { return []; }
  };
  const [saved, setSaved] = useState<{ key: string; hrefs: string[] }>(() => ({ key, hrefs: read() }));
  const hrefs = saved.key === key ? saved.hrefs : read();
  useEffect(() => {
    setSaved({ key, hrefs: read() });
    const sync = () => { setSaved({ key, hrefs: read() }); };
    window.addEventListener('t24:favorites-changed', sync);
    window.addEventListener('storage', sync);
    return () => {
      window.removeEventListener('t24:favorites-changed', sync);
      window.removeEventListener('storage', sync);
    };
  }, [key]);
  const toggleFavorite = (href: string) => {
    if (!byHref.has(href)) return false;
    const current = read();
    const next = current.includes(href) ? current.filter(item => item !== href) : current.length < 6 ? [...current, href] : current;
    if (!current.includes(href) && current.length >= 6) return false;
    try {
      localStorage.setItem(key, JSON.stringify(next));
      setSaved({ key, hrefs: next });
      window.dispatchEvent(new Event('t24:favorites-changed'));
      return true;
    } catch { return false; }
  };
  const favorites = hrefs.flatMap(href => byHref.has(href) ? [byHref.get(href)!] : []) as MobileMoreItem[];
  return { favorites, isFavorite: (href: string) => hrefs.includes(href) && byHref.has(href), toggleFavorite };
}
