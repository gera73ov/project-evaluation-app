/**
 * API-006, FE-003 · типизированный клиент API v1 (openapi-fetch поверх сгенерированных типов).
 *
 * Сессия — cookie (FR-SESS-01), поэтому credentials: 'same-origin'. Изменяющие запросы несут
 * X-CSRF-Token со значением cookie `__Host-csrf` (SEC-WEB-04, api-conventions 3 п. 2). Фоновые
 * запросы (опрос, предзагрузка) помечаются `X-Background: 1` и не продлевают сессию (FR-SESS-02).
 */
import createClient, { type Middleware } from 'openapi-fetch';
import type { paths } from './generated/schema';

export type { paths, components, operations } from './generated/schema';

export const API_BASE = '/api/v1';
export const CSRF_COOKIE = '__Host-csrf';
export const BACKGROUND_HEADER = 'X-Background';

const SAFE_METHODS = new Set(['GET', 'HEAD', 'OPTIONS']);

let csrfToken: string | null = null;

/** Запомнить CSRF-токен явно (тесты, моки); null — брать из cookie. */
export function setCsrfToken(token: string | null): void {
  csrfToken = token;
}

/** Токен из cookie `__Host-csrf` (не HttpOnly, api-conventions 3). */
export function readCsrfCookie(cookie: string = document.cookie): string | null {
  for (const part of cookie.split(';')) {
    const [name, ...rest] = part.trim().split('=');
    if (name === CSRF_COOKIE) return decodeURIComponent(rest.join('='));
  }
  return null;
}

export const csrfMiddleware: Middleware = {
  onRequest({ request }) {
    const token = csrfToken ?? readCsrfCookie();
    if (token && !SAFE_METHODS.has(request.method)) {
      request.headers.set('X-CSRF-Token', token);
    }
    return request;
  },
};

/** Абсолютный адрес того же origin: так `Request` строится и в браузере, и в тестах (jsdom). */
const ORIGIN = typeof window === 'undefined' ? '' : window.location.origin;

// fetch берётся в момент вызова, а не при создании клиента: моки MSW подменяют его позже.
export const api = createClient<paths>({
  baseUrl: `${ORIGIN}${API_BASE}`,
  credentials: 'same-origin',
  fetch: (request) => globalThis.fetch(request),
});
api.use(csrfMiddleware);

/** Заголовки фонового запроса: `api.GET(path, { headers: background() })`. */
export function background(): Record<string, string> {
  return { [BACKGROUND_HEADER]: '1' };
}
