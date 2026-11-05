/**
 * FE-001 · обработчики MSW для всех операций `contracts/openapi.yaml` и WebSocket.
 * Один набор для браузера (`browser.ts`, `npm run dev:mock`) и для тестов (`msw/node`).
 */
import { http, HttpResponse, delay } from 'msw';

import { mswPath, operations } from './contract';
import { currentPersona, type Persona } from './personas';
import { mockResponse } from './responses';
import { wsHandler, type WsSimulatorOptions } from './ws';

export type HandlerOptions = {
  /** чья сессия (по умолчанию — роль переключателя) */
  persona?: () => Persona;
  /** задержка ответа, мс: в браузере видны индикаторы загрузки */
  latencyMs?: number;
  ws?: WsSimulatorOptions;
};

export function buildHandlers(options: HandlerOptions = {}) {
  const getPersona = options.persona ?? currentPersona;
  // /projects/{id}/... раньше /projects/{id}: MSW берёт первый совпавший обработчик
  const ordered = [...operations].sort((a, b) => b.path.length - a.path.length);
  const httpHandlers = ordered.map((op) =>
    http[op.method](mswPath(op.path), async ({ params }) => {
      if (options.latencyMs) await delay(options.latencyMs);
      const flat = Object.fromEntries(Object.entries(params).map(([k, v]) => [k, String(v)]));
      const result = mockResponse(op, flat, getPersona());
      if (result.binary) {
        return new HttpResponse(String(result.body), {
          status: result.status,
          headers: {
            'Content-Type': 'application/octet-stream',
            'Content-Disposition': 'attachment; filename="mock.bin"',
          },
        });
      }
      if (result.body === null) return new HttpResponse(null, { status: result.status });
      const problem = result.status >= 400;
      return HttpResponse.json(result.body, {
        status: result.status,
        headers: problem ? { 'Content-Type': 'application/problem+json' } : {},
      });
    }),
  );
  return [...httpHandlers, wsHandler({ persona: getPersona, ...options.ws })];
}
