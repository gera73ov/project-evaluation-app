/**
 * FE-003 · маршрутизация SPA на History API. Своя реализация вместо пакета: маршрутов ~25, нужны
 * только шаблоны `/projects/:id/...`, ссылки и переходы (AGENTS.md 6.5 п. 3 — без новой
 * зависимости, если задачу можно решить уже подключённым).
 */
import { createContext, useContext, useEffect, useMemo, useState, type MouseEvent, type ReactNode } from 'react';

export interface Location {
  pathname: string;
  search: string;
}

interface RouterValue {
  location: Location;
  navigate: (to: string, options?: { replace?: boolean }) => void;
}

const RouterContext = createContext<RouterValue | null>(null);

function current(): Location {
  return { pathname: window.location.pathname, search: window.location.search };
}

export function RouterProvider({ children }: { children: ReactNode }) {
  const [location, setLocation] = useState<Location>(current);
  useEffect(() => {
    const onPop = () => setLocation(current());
    window.addEventListener('popstate', onPop);
    return () => window.removeEventListener('popstate', onPop);
  }, []);
  const value = useMemo<RouterValue>(
    () => ({
      location,
      navigate(to, options) {
        if (options?.replace) window.history.replaceState(null, '', to);
        else window.history.pushState(null, '', to);
        setLocation(current());
        window.scrollTo?.(0, 0);
      },
    }),
    [location],
  );
  return <RouterContext.Provider value={value}>{children}</RouterContext.Provider>;
}

function useRouter(): RouterValue {
  const value = useContext(RouterContext);
  if (!value) throw new Error('useRouter вне RouterProvider');
  return value;
}

export function useLocation(): Location {
  return useRouter().location;
}

export function useNavigate(): RouterValue['navigate'] {
  return useRouter().navigate;
}

export function useSearchParam(name: string): string | null {
  return new URLSearchParams(useLocation().search).get(name);
}

export type Params = Readonly<Record<string, string>>;

/** `/projects/:id/settings` против пути: параметры или null. Сегменты сравниваются целиком. */
export function matchPath(pattern: string, pathname: string): Params | null {
  const want = pattern.split('/').filter(Boolean);
  const got = pathname.replace(/\/+$/, '').split('/').filter(Boolean);
  if (want.length !== got.length) return null;
  const params = new Map<string, string>();
  for (const [i, segment] of want.entries()) {
    const value = got.at(i) ?? '';
    if (segment.startsWith(':')) params.set(segment.slice(1), decodeURIComponent(value));
    else if (segment !== value) return null;
  }
  return Object.freeze(Object.fromEntries(params));
}

/** Ссылка SPA: обычный `<a href>` (открывается в новой вкладке), клик без модификаторов — переход. */
export function Link({
  to,
  children,
  className,
  'aria-current': ariaCurrent,
}: {
  to: string;
  children: ReactNode;
  className?: string | undefined;
  'aria-current'?: 'page' | undefined;
}) {
  const navigate = useNavigate();
  function onClick(e: MouseEvent<HTMLAnchorElement>) {
    if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    e.preventDefault();
    navigate(to);
  }
  return (
    <a href={to} onClick={onClick} className={className} aria-current={ariaCurrent}>
      {children}
    </a>
  );
}

export function Redirect({ to }: { to: string }) {
  const navigate = useNavigate();
  useEffect(() => navigate(to, { replace: true }), [navigate, to]);
  return null;
}
