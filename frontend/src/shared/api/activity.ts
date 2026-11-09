/**
 * FE-007 · время последней активности для таймера бездействия (FR-SESS-02).
 *
 * Активность — только REST-запросы по действию пользователя: сервер продлевает сессию по ним же.
 * Запросы с `X-Background: 1`, heartbeat WebSocket и продление захватов не считаются.
 */
import type { Middleware } from 'openapi-fetch';


/** Тот же заголовок, что `BACKGROUND_HEADER` в client.ts (без циклического импорта). */
const BACKGROUND_HEADER = 'X-Background';

type Listener = (at: number) => void;

let lastActivity = Date.now();
const listeners = new Set<Listener>();

export function lastActivityAt(): number {
  return lastActivity;
}

export function markActivity(at: number = Date.now()): void {
  lastActivity = at;
  for (const listener of listeners) listener(at);
}

export function onActivity(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** Успешный ответ на пользовательский запрос (не 401) — сессия продлена сервером. */
export const activityMiddleware: Middleware = {
  onResponse({ request, response }) {
    if (request.headers.get(BACKGROUND_HEADER) === '1') return undefined;
    if (response.status !== 401) markActivity();
    return undefined;
  },
};
