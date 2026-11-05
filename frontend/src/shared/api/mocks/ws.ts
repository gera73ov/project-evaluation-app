/**
 * FE-001 · имитатор WebSocket `/api/v1/ws` по контракту RT-001
 * (`contracts/ws-events.schema.json`, `contracts/ws-events.md`).
 *
 * Отвечает на команды subscribe / unsubscribe / lock / unlock / heartbeat (`ack`) и раз в
 * `intervalMs` присылает следующее событие из сценария: присутствие, правка коллеги, захват
 * и снятие ячейки, сообщение, уведомление, деньги. Каналы фильтруются как на сервере
 * (SEC-AUTHZ-04): `project:{id}:money` и `:notes` получает только роль с `money.read` /
 * `notes.read`, поэтому эксперт денежных событий не видит никогда.
 */
import { ws } from 'msw';

import { resolveRef, type Schema } from './contract';
import { PEOPLE, PROJECTS, userRef, type DemoProject } from './data';
import { NOW } from './ids';
import { accessOf, currentPersona, personaId, type Persona } from './personas';
import { sample } from './sample';

type Event = Record<string, unknown> & { event: string; channel: string };

const SERVER_EVENTS = (resolveRef('#/$defs/ServerEvent').oneOf ?? []) as Schema[];

/** Схема события по имени (`node.updated`) и его канал (`project`, `money`, `notes`, `user`). */
function eventSchema(name: string): { schema: Schema; channel: string } {
  const schema = SERVER_EVENTS.find(
    (s) => (s.properties?.event as Schema | undefined)?.const === name,
  );
  if (!schema) throw new Error(`моки WS: нет события ${name} в ws-events.schema.json`);
  return { schema, channel: String(schema['x-channel']) };
}

export const EVENT_NAMES: string[] = SERVER_EVENTS.map((s) =>
  String((s.properties?.event as Schema).const),
);

function channelName(kind: string, project: DemoProject, persona: Persona): string {
  if (kind === 'user') return `user:${personaId(persona)}`;
  return kind === 'project' ? `project:${project.id}` : `project:${project.id}:${kind}`;
}

/** Может ли персона получить событие этого канала (как фильтр сервера, ws-events.md). */
export function canReceive(kind: string, project: DemoProject, persona: Persona): boolean {
  if (kind === 'user') return true;
  const { permissions } = accessOf(persona, project.key);
  if (kind === 'money') return permissions.has('money.read');
  if (kind === 'notes') return permissions.has('notes.read');
  return permissions.has('tree.read');
}

function leaf(project: DemoProject, title: string) {
  return project.nodes.find((n) => n.title === title) ?? project.nodes.at(-1) ?? {};
}

/** Данные событий сценария поверх примера по схеме. */
function dataFor(name: string, project: DemoProject): Record<string, unknown> {
  // UserRef одинаков в OpenAPI и WS (ws-events.schema.json $defs.UserRef)
  const petrov = { ...userRef(PEOPLE.petrov), color: '#2f9e6e' };
  const dashboard = leaf(project, 'Дашборд');
  const wsNode = (n: Record<string, unknown>) => ({
    id: n.id,
    parent_id: n.parent_id,
    kind: n.kind,
    phase_id: n.phase_id,
    discipline_id: n.discipline_id,
    type_id: n.type_id,
    title: n.title,
    position: n.position,
    o: n.o,
    r: n.r,
    p: n.p,
    multiplier: n.multiplier,
    comment_lines: n.comment_lines,
    reviewed_by: null,
    reviewed_at: null,
    self_review: false,
    version: Number(n.version ?? 1) + 1,
    field_versions: {},
  });
  switch (name) {
    case 'presence':
      return { users: [petrov] };
    case 'node.updated':
      return { node: wsNode(dashboard), author: petrov, changed_fields: ['r'] };
    case 'cell.locked':
      return {
        node_id: dashboard.id,
        field: 'r',
        user: petrov,
        expires_at: new Date(Date.parse(NOW) + 30_000).toISOString().replace('.000Z', 'Z'),
        forced: false,
      };
    case 'cell.unlocked':
      return { node_id: dashboard.id, field: 'r', user_id: petrov.id, reason: 'released' };
    default:
      return {};
  }
}

/** Событие `name` для персоны в проекте; null — персона его не получает (канал закрыт). */
export function buildEvent(
  name: string,
  persona: Persona,
  project: DemoProject = PROJECTS.portal,
): Event | null {
  const { schema, channel } = eventSchema(name);
  if (!canReceive(channel, project, persona)) return null;
  const base = sample(schema, { money: true }, `ws.${name}`, 0, { strictPatterns: false }) as Event;
  const data = { ...(base.data as object), ...dataFor(name, project) };
  // в пример по схеме попадает одно поле из каждой ветки oneOf — оставляем только известные
  const props = ((schema.properties?.data as Schema | undefined)?.properties ?? {}) as Record<
    string,
    Schema
  >;
  const filtered = Object.fromEntries(Object.entries(data).filter(([k]) => k in props));
  return {
    ...base,
    event: name,
    channel: channelName(channel, project, persona),
    ts: NOW,
    ...('project_version' in base ? { project_version: 22 } : {}),
    data: filtered,
  };
}

/** Порядок событий имитатора (по кругу). */
export const SCENARIO = [
  'presence',
  'cell.locked',
  'node.updated',
  'cell.unlocked',
  'message.created',
  'notification.created',
  'money.updated',
];

type Command = { op?: string; req_id?: string; project_id?: string };

export type WsSimulatorOptions = { intervalMs?: number; persona?: () => Persona };

/** Обработчик MSW для `/api/v1/ws`. */
export function wsHandler(options: WsSimulatorOptions = {}) {
  const intervalMs = options.intervalMs ?? 20_000;
  const getPersona = options.persona ?? currentPersona;
  const link = ws.link(/\/api\/v1\/ws$/);
  return link.addEventListener('connection', ({ client }) => {
    let project: DemoProject | null = null;
    let step = 0;
    const send = (payload: unknown) => client.send(JSON.stringify(payload));
    const timer = setInterval(() => {
      if (!project) return;
      for (let tries = 0; tries < SCENARIO.length; tries += 1) {
        const name = SCENARIO[step % SCENARIO.length] ?? 'presence';
        step += 1;
        const event = buildEvent(name, getPersona(), project);
        if (event) {
          send(event);
          break;
        }
      }
    }, intervalMs);
    client.addEventListener('close', () => clearInterval(timer));
    client.addEventListener('message', (message) => {
      let cmd: Command;
      try {
        cmd = JSON.parse(String(message.data)) as Command;
      } catch {
        send({ type: 'error', code: 'VALIDATION_FAILED', detail: 'не JSON' });
        return;
      }
      const reply = { type: 'ack', op: cmd.op, ...(cmd.req_id ? { req_id: cmd.req_id } : {}) };
      switch (cmd.op) {
        case 'subscribe': {
          const found = Object.values(PROJECTS).find((p) => p.id === cmd.project_id) ?? null;
          const persona = getPersona();
          if (!found || !canReceive('project', found, persona)) {
            send({
              type: 'error',
              op: 'subscribe',
              ...(cmd.req_id ? { req_id: cmd.req_id } : {}),
              code: 'NOT_FOUND',
            });
            return;
          }
          project = found;
          const channels = ['project', 'money', 'notes']
            .filter((kind) => canReceive(kind, found, persona))
            .map((kind) => channelName(kind, found, persona));
          send({ ...reply, result: { project_version: 21, channels, resync: false } });
          return;
        }
        case 'lock':
          send({ ...reply, result: { expires_at: new Date(Date.now() + 30_000).toISOString() } });
          return;
        case 'heartbeat':
          send({ ...reply, result: { extended: [], lost: [] } });
          return;
        case 'unsubscribe':
          project = null;
          send(reply);
          return;
        case 'unlock':
          send(reply);
          return;
        default:
          send({ type: 'error', code: 'VALIDATION_FAILED', detail: 'неизвестная команда' });
      }
    });
  });
}
