/**
 * API-006 · типизированный клиент API v1 (openapi-fetch поверх сгенерированных типов).
 *
 * Сессия — cookie (FR-SESS-01), поэтому credentials: 'same-origin'. Изменяющие запросы несут
 * X-CSRF-Token (SEC-WEB-04): токен передаёт слой сессии через setCsrfToken.
 */
import createClient, { type Middleware } from 'openapi-fetch';
import type { paths } from './generated/schema';

export type { paths, components, operations } from './generated/schema';

export const API_BASE = '/api/v1';

const SAFE_METHODS = new Set(['GET', 'HEAD', 'OPTIONS']);

let csrfToken: string | null = null;

/** Запомнить CSRF-токен текущей сессии (null — сессии нет). */
export function setCsrfToken(token: string | null): void {
  csrfToken = token;
}

export const csrfMiddleware: Middleware = {
  onRequest({ request }) {
    if (csrfToken && !SAFE_METHODS.has(request.method)) {
      request.headers.set('X-CSRF-Token', csrfToken);
    }
    return request;
  },
};

export const api = createClient<paths>({ baseUrl: API_BASE, credentials: 'same-origin' });
api.use(csrfMiddleware);
