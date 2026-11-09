// @vitest-environment node
/**
 * FE-001 · моки отвечают по контракту: каждая операция OpenAPI для каждой роли
 * переключателя даёт ответ, который проходит валидацию по схеме `contracts/openapi.yaml`;
 * события WS проходят `contracts/ws-events.schema.json`; эксперт не получает денег
 * (SEC-AUTHZ-04, TC-SEC-03 на уровне моков).
 */
import Ajv2020 from 'ajv/dist/2020';
import addFormats from 'ajv-formats';
import { setupServer } from 'msw/node';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';

import {
  openapi,
  operations,
  resolveResponse,
  successResponse,
  wsSchema,
  type Operation,
  type Schema,
} from './contract';
import { PROJECTS } from './data';
import { uuidFrom } from './ids';
import { buildHandlers } from './handlers';
import { PERSONA_KEYS, PERSONAS, type Persona } from './personas';
import { EVENT_NAMES, SCENARIO, buildEvent } from './ws';

const BASE = 'http://mock.local/api/v1';
let persona: Persona = PERSONAS.expert;
const server = setupServer(...buildHandlers({ persona: () => persona }));

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterAll(() => server.close());

const ajv = new Ajv2020({ strict: false, allErrors: true, validateSchema: false });
addFormats(ajv);
ajv.addSchema(openapi as object, 'openapi.json');
const validateWs = ajv.compile(wsSchema as object);

/** `#/components/...` внутри схемы операции → ссылка на добавленный документ OpenAPI. */
function rebase(schema: unknown): unknown {
  if (Array.isArray(schema)) return schema.map(rebase);
  if (schema && typeof schema === 'object') {
    return Object.fromEntries(
      Object.entries(schema).map(([k, v]) => [
        k,
        k === '$ref' && typeof v === 'string' && v.startsWith('#/')
          ? `openapi.json${v}`
          : rebase(v),
      ]),
    );
  }
  return schema;
}

const validators = new Map<string, ReturnType<typeof ajv.compile>>();
function validatorFor(key: string, schema: Schema) {
  let v = validators.get(key);
  if (!v) {
    v = ajv.compile(rebase(schema) as object);
    validators.set(key, v);
  }
  return v;
}
const PROBLEM: Schema = { $ref: '#/components/schemas/Problem' };

/** Значения параметров пути: UUID проекта «Портал дилеров», узла «Авторизация» и т. п. */
function urlFor(op: Operation): string {
  const portal = PROJECTS.portal;
  const leaf = portal.nodes.find((n) => n.title === 'Авторизация');
  const path = op.path.replace(/\{([^}]+)\}/g, (_, name: string) => {
    const param = op.parameters.find((p) => p.name === name && p.in === 'path');
    const enumValue = param?.schema?.enum?.[0];
    if (enumValue !== undefined) return String(enumValue);
    if (name === 'id' || name === 'project_id') {
      return op.path.startsWith('/nodes/') ? String(leaf?.id) : portal.id;
    }
    if (name === 'phase') return String(portal.branchStatuses[0]?.phase_id);
    if (name === 'discipline' || name === 'discipline_id')
      return String(portal.branchStatuses[0]?.discipline_id);
    if (name === 'year') return '2026';
    if (name === 'code') return 'USD';
    if (name === 'step' || name === 'section' || name === 'tab') return 'auth';
    return '0190f0f0-0000-7000-8000-000000000001';
  });
  return BASE + path;
}

async function call(op: Operation): Promise<{ status: number; body: unknown }> {
  const res = await fetch(urlFor(op), {
    method: op.method.toUpperCase(),
    headers: { 'Content-Type': 'application/json' },
    ...(op.method === 'get' || op.method === 'delete' ? {} : { body: '{}' }),
  });
  const text = await res.text();
  const json = (res.headers.get('content-type') ?? '').includes('json');
  return { status: res.status, body: json && text ? JSON.parse(text) : text };
}

const MONEY_KEYS = new Set(['rate', 'cost', 'currency', 'exchange_rate', 'money']);
function moneyKeys(value: unknown, path = '$'): string[] {
  if (Array.isArray(value)) return value.flatMap((v, i) => moneyKeys(v, `${path}[${i}]`));
  if (value && typeof value === 'object') {
    return Object.entries(value).flatMap(([k, v]) => [
      ...(MONEY_KEYS.has(k) || k.startsWith('rate_') || k.startsWith('cost_')
        ? [`${path}.${k}`]
        : []),
      ...moneyKeys(v, `${path}.${k}`),
    ]);
  }
  return [];
}

describe('моки HTTP по контракту OpenAPI', () => {
  it('обработчик есть у каждой операции', () => {
    expect(operations.length).toBeGreaterThanOrEqual(170);
  });

  for (const key of PERSONA_KEYS) {
    it(`все ответы для роли «${key}» проходят схему`, async () => {
      persona = PERSONAS[key];
      const failures: string[] = [];
      for (const op of operations) {
        const { status, body } = await call(op);
        const ok = successResponse(op);
        if (status === 403 || status === 404) {
          const v = validatorFor('Problem', PROBLEM);
          if (!v(body)) failures.push(`${op.operationId} ${status}: ${ajv.errorsText(v.errors)}`);
          continue;
        }
        if (status !== ok.status) {
          failures.push(`${op.operationId}: статус ${status}, ожидался ${ok.status}`);
          continue;
        }
        if (!ok.schema) continue;
        const v = validatorFor(op.operationId, ok.schema);
        if (!v(body)) failures.push(`${op.operationId}: ${ajv.errorsText(v.errors)}`);
      }
      expect(failures).toEqual([]);
    });
  }

  it.each(['expert', 'admin'] as const)(
    '«%s» не получает денежных ключей ни в одном ответе (TC-SEC-03)',
    async (key) => {
      persona = PERSONAS[key];
      const leaks: string[] = [];
      for (const op of operations) {
        const { status, body } = await call(op);
        if (status >= 400) continue;
        if (op.operationId === 'listProjects') {
          // в списке «Мои оценки» деньги есть только у «Интеграции с ФНС», где Иванов модератор
          const items = (body as { items: { id: string }[] }).items;
          const portal = items.find((i) => i.id === PROJECTS.portal.id);
          leaks.push(...moneyKeys(portal).map((k) => `${op.operationId} ${k}`));
          continue;
        }
        leaks.push(...moneyKeys(body).map((k) => `${op.operationId} ${k}`));
      }
      expect(leaks).toEqual([]);
    },
  );

  it('денежные эндпоинты: эксперту 403, модератору — суммы 6.5', async () => {
    const getMoney = operations.find((o) => o.operationId === 'getMoney');
    if (!getMoney) throw new Error('нет getMoney');
    persona = PERSONAS.expert;
    expect((await call(getMoney)).status).toBe(403);
    persona = PERSONAS.moderator;
    const { status, body } = await call(getMoney);
    expect(status).toBe(200);
    const p80 = (
      body as {
        figures: { p80: { total_rub: string; total_cur: string; total_with_vat_rub: string } };
      }
    ).figures.p80;
    expect([p80.total_rub, p80.total_cur, p80.total_with_vat_rub]).toEqual([
      '1200495',
      '12978',
      '1440594',
    ]);
  });

  it('сравнение со снимком (CR-008): схема Diff, у эксперта нет денег и денежных параметров', async () => {
    const op = operations.find((o) => o.operationId === 'diffSnapshot');
    if (!op) throw new Error('нет diffSnapshot');
    const v1 = uuidFrom('snapshot', 'portal', 'v1');
    const url = `${BASE}/snapshots/${v1}/diff?with=current`;
    const v = validatorFor(op.operationId, successResponse(op).schema as Schema);
    persona = PERSONAS.moderator;
    const mod = (await (await fetch(url)).json()) as { rows: unknown[]; params: unknown[] };
    expect(v(mod) ? [] : ajv.errorsText(v.errors)).toEqual([]);
    expect([mod.rows.length, mod.params.length]).toEqual([4, 1]);
    persona = PERSONAS.expert;
    const exp = (await (await fetch(url)).json()) as { params: unknown[] };
    expect(v(exp) ? [] : ajv.errorsText(v.errors)).toEqual([]);
    expect(exp.params).toEqual([]);
    expect(moneyKeys(exp)).toEqual([]);
  });

  it('дерево «Портала дилеров» совпадает с примером 6.5', async () => {
    persona = PERSONAS.expert;
    const getTree = operations.find((o) => o.operationId === 'getTree');
    if (!getTree) throw new Error('нет getTree');
    const { body } = await call(getTree);
    const tree = body as {
      nodes: { title: string; e: string | null }[];
      totals: { total: { e: string; p80: string } };
    };
    expect(tree.totals.total).toMatchObject({ e: '406.50', p80: '425.50' });
    expect(tree.nodes.find((n) => n.title === 'Создать типовой экран')?.e).toBe('72.00');
  });

  it('«Мои оценки» Иванова: деньги только у «Интеграции с ФНС», где он модератор', async () => {
    persona = PERSONAS.expert;
    const listProjects = operations.find((o) => o.operationId === 'listProjects');
    if (!listProjects) throw new Error('нет listProjects');
    const { body } = await call(listProjects);
    const items = (body as { items: { name: string; money?: unknown }[] }).items;
    expect(items.map((i) => [i.name, 'money' in i])).toEqual([
      ['Портал дилеров', false],
      ['Интеграция с ФНС', true],
    ]);
  });

  it('чужой проект — 404, а не 403 (R-OBJECT-CHAIN)', async () => {
    persona = PERSONAS.admin;
    const getProject = operations.find((o) => o.operationId === 'getProject');
    if (!getProject) throw new Error('нет getProject');
    expect((await call(getProject)).status).toBe(404);
    persona = PERSONAS.presale_head;
    expect((await call(getProject)).status).toBe(200);
  });

  it('ошибки отдаются как application/problem+json', () => {
    const r = resolveResponse({ $ref: '#/components/responses/Problem401' });
    expect(Object.keys(r.content ?? {})).toContain('application/problem+json');
  });
});

/** Проверка события по его ветке oneOf — для понятного текста ошибки. */
function variantValidator(name: string) {
  const variants = ((wsSchema.$defs.ServerEvent as Schema).oneOf ?? []) as Schema[];
  const variant = variants.find((v) => (v.properties?.event as Schema | undefined)?.const === name);
  const v = ajv.compile({ ...(variant as object), $defs: wsSchema.$defs });
  return v;
}

describe('имитатор WebSocket по контракту RT-001', () => {
  it('все события контракта проходят схему для модератора', () => {
    const failures: string[] = [];
    for (const name of EVENT_NAMES) {
      const event = buildEvent(name, PERSONAS.moderator);
      if (!event) {
        failures.push(`${name}: модератор не получает`);
        continue;
      }
      if (!validateWs(event)) {
        const v = variantValidator(name);
        v(event);
        failures.push(`${name}: ${ajv.errorsText(v.errors)}`);
      }
    }
    expect(failures).toEqual([]);
  });

  it('эксперт не получает событий каналов денег и заметок', () => {
    for (const name of ['money.updated', 'note.created', 'note.updated']) {
      expect(buildEvent(name, PERSONAS.expert)).toBeNull();
    }
    for (const name of SCENARIO) {
      const event = buildEvent(name, PERSONAS.expert);
      if (event) expect(moneyKeys(event)).toEqual([]);
    }
  });

  it('подписка и команды получают ack', async () => {
    persona = PERSONAS.expert;
    const socket = new WebSocket('ws://mock.local/api/v1/ws');
    const messages: { type: string; op?: string; result?: { channels: string[] } }[] = [];
    await new Promise<void>((resolve, reject) => {
      socket.addEventListener('open', () => {
        socket.send(
          JSON.stringify({ op: 'subscribe', req_id: '1', project_id: PROJECTS.portal.id }),
        );
        socket.send(JSON.stringify({ op: 'heartbeat', req_id: '2', locks: [] }));
      });
      socket.addEventListener('message', (m) => {
        messages.push(JSON.parse(String(m.data)));
        if (messages.length === 2) resolve();
      });
      socket.addEventListener('error', () => reject(new Error('ошибка WS')));
    });
    socket.close();
    expect(messages.map((m) => [m.type, m.op])).toEqual([
      ['ack', 'subscribe'],
      ['ack', 'heartbeat'],
    ]);
    expect(messages[0]?.result?.channels).toEqual([`project:${PROJECTS.portal.id}`]);
    for (const m of messages) expect(validateWs(m)).toBe(true);
  });
});
